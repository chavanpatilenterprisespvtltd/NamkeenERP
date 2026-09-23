from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user


def _perm(engine, request, permission):
    u = authenticate(request)
    ps = permissions_for_user(engine, u.user_id)
    if permission not in ps and 'admin.users' not in ps:
        raise HTTPException(403, 'permission denied')
    return u


def _money(v):
    return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def register_v90dm_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for p in [
            ('payroll_accounting.view','View Payroll Accounting'),
            ('payroll_accounting.manage','Manage Payroll Accounting'),
            ('payroll_accounting.post','Post Payroll Accounting'),
            ('payroll_accounting.close','Close Payroll Accounting'),
            ('payroll_accounting.reconcile','Reconcile Payroll Accounting')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'), {'p':p[0], 'n':p[1]})
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_payroll_accounting_config(
            config_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            salary_expense_ledger TEXT NOT NULL DEFAULT 'SALARY_EXPENSE', salary_payable_ledger TEXT NOT NULL DEFAULT 'SALARY_PAYABLE',
            employer_statutory_ledger TEXT NOT NULL DEFAULT 'EMPLOYER_STATUTORY_PAYABLE', employee_advance_ledger TEXT NOT NULL DEFAULT 'EMPLOYEE_ADVANCES',
            payroll_clearing_ledger TEXT NOT NULL DEFAULT 'PAYROLL_CLEARING', production_labour_ledger TEXT NOT NULL DEFAULT 'PRODUCTION_LABOUR',
            UNIQUE(organization_id,entity_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_payroll_accounting_journal(
            journal_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, run_id TEXT NOT NULL,
            journal_type TEXT NOT NULL, voucher_no TEXT NOT NULL, journal_date TEXT NOT NULL, debit_total NUMERIC NOT NULL DEFAULT 0,
            credit_total NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'POSTED', created_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(run_id,journal_type))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_payroll_accounting_line(
            line_id TEXT PRIMARY KEY, journal_id TEXT NOT NULL, ledger_code TEXT NOT NULL, debit NUMERIC NOT NULL DEFAULT 0,
            credit NUMERIC NOT NULL DEFAULT 0, employee_id TEXT, department_id TEXT, production_batch_id TEXT, narration TEXT)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_payroll_expense_allocation(
            allocation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            department_id TEXT NOT NULL, amount NUMERIC NOT NULL, basis TEXT NOT NULL DEFAULT 'MANUAL', created_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(run_id,department_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_payroll_employee_recovery(
            recovery_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, employee_id TEXT NOT NULL, organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL, recovery_type TEXT NOT NULL, amount NUMERIC NOT NULL, ledger_code TEXT NOT NULL DEFAULT 'EMPLOYEE_ADVANCES',
            status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_payroll_accounting_reconciliation(
            reconciliation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            payroll_net NUMERIC NOT NULL, bank_paid NUMERIC NOT NULL, statutory_payable NUMERIC NOT NULL, gl_salary NUMERIC NOT NULL,
            gl_payable NUMERIC NOT NULL, difference NUMERIC NOT NULL, status TEXT NOT NULL DEFAULT 'EXCEPTION', notes TEXT,
            reconciled_by TEXT, reconciled_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(run_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_payroll_month_close(
            close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_id TEXT NOT NULL,
            run_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', closed_by TEXT, closed_at TIMESTAMP, notes TEXT,
            UNIQUE(organization_id,entity_id,period_id))'''))

    def _config(c, org, entity):
        r = c.execute(text('SELECT * FROM hr_payroll_accounting_config WHERE organization_id=:o AND entity_id=:e'), {'o':org,'e':entity}).mappings().first()
        if r: return dict(r)
        i = str(uuid4())
        c.execute(text('INSERT INTO hr_payroll_accounting_config(config_id,organization_id,entity_id) VALUES(:i,:o,:e)'), {'i':i,'o':org,'e':entity})
        return dict(c.execute(text('SELECT * FROM hr_payroll_accounting_config WHERE config_id=:i'), {'i':i}).mappings().first())

    def _journal(c, run, typ, lines, user_id, voucher_no=None):
        existing = c.execute(text('SELECT journal_id,status FROM hr_payroll_accounting_journal WHERE run_id=:r AND journal_type=:t'), {'r':run['run_id'],'t':typ}).mappings().first()
        if existing and existing['status'] == 'POSTED':
            return existing['journal_id']
        dr = sum((_money(x['debit']) for x in lines), Decimal('0')); cr = sum((_money(x['credit']) for x in lines), Decimal('0'))
        if dr <= 0 or dr != cr: raise HTTPException(400, 'payroll accounting journal must be balanced and positive')
        jid = existing['journal_id'] if existing else str(uuid4())
        c.execute(text('''INSERT INTO hr_payroll_accounting_journal(journal_id,organization_id,entity_id,run_id,journal_type,voucher_no,journal_date,debit_total,credit_total,status,created_by)
            VALUES(:j,:o,:e,:r,:t,:v,:d,:dr,:cr,'POSTED',:u)
            ON CONFLICT(run_id,journal_type) DO UPDATE SET debit_total=:dr,credit_total=:cr,status='POSTED' '''),
            {'j':jid,'o':run['organization_id'],'e':run['entity_id'],'r':run['run_id'],'t':typ,'v':voucher_no or f'PAY-{run["run_id"][:8]}-{typ}', 'd':str(run.get('period_id') or ''), 'dr':float(dr),'cr':float(cr),'u':str(user_id)})
        c.execute(text('DELETE FROM hr_payroll_accounting_line WHERE journal_id=:j'), {'j':jid})
        for x in lines:
            c.execute(text('''INSERT INTO hr_payroll_accounting_line(line_id,journal_id,ledger_code,debit,credit,employee_id,department_id,production_batch_id,narration)
                VALUES(:i,:j,:l,:d,:c,:e,:dp,:b,:n)'''), {'i':str(uuid4()),'j':jid,'l':x['ledger_code'],'d':float(_money(x['debit'])),'c':float(_money(x['credit'])),'e':x.get('employee_id'),'dp':x.get('department_id'),'b':x.get('production_batch_id'),'n':x.get('narration')})
        return jid

    @app.post('/v90dm/payroll/accounting/config')
    def config(body:dict, request:Request):
        u = _perm(engine, request, 'payroll_accounting.manage')
        org, ent = body.get('organization_id'), body.get('entity_id')
        if not str(org or '').strip() or not str(ent or '').strip(): raise HTTPException(400,'organization_id and entity_id are required')
        keys = ['salary_expense_ledger','salary_payable_ledger','employer_statutory_ledger','employee_advance_ledger','payroll_clearing_ledger','production_labour_ledger']
        with engine.begin() as c:
            vals = _config(c,org,ent)
            sets=[]; params={'o':org,'e':ent}
            for k in keys:
                if body.get(k): sets.append(f'{k}=:{k}'); params[k]=str(body[k])
            if sets: c.execute(text('UPDATE hr_payroll_accounting_config SET '+','.join(sets)+' WHERE organization_id=:o AND entity_id=:e'),params)
        return {'organization_id':org,'entity_id':ent,'status':'SAVED'}

    @app.post('/v90dm/payroll/runs/{run_id}/journal')
    def generate(run_id:str, request:Request):
        u = _perm(engine, request, 'payroll_accounting.post')
        with engine.begin() as c:
            run = c.execute(text('SELECT * FROM hr_payroll_run WHERE run_id=:r'), {'r':run_id}).mappings().first()
            if not run: raise HTTPException(404,'payroll run not found')
            if not run['approved']: raise HTTPException(409,'payroll run must be approved')
            cfg = _config(c,run['organization_id'],run['entity_id'])
            gross=_money(run['gross_total']); net=_money(run['net_total']); deductions=_money(run['deduction_total']); employer=_money(run['employer_cost_total'])
            lines=[{'ledger_code':cfg['salary_expense_ledger'],'debit':gross,'credit':0,'narration':'Payroll gross expense'},
                   {'ledger_code':cfg['salary_payable_ledger'],'debit':0,'credit':net,'narration':'Net salary payable'}]
            if deductions: lines.append({'ledger_code':cfg['employer_statutory_ledger'],'debit':0,'credit':deductions,'narration':'Employee deductions payable'})
            if employer-gross > 0: lines.append({'ledger_code':cfg['employer_statutory_ledger'],'debit':employer-gross,'credit':0,'narration':'Employer statutory cost'})
            # Employer cost can exceed gross while deductions are held as payable; ensure balancing by explicit clearing.
            dr=sum((_money(x['debit']) for x in lines),Decimal('0')); cr=sum((_money(x['credit']) for x in lines),Decimal('0'))
            if dr != cr:
                delta=cr-dr
                if delta>0: lines.append({'ledger_code':cfg['payroll_clearing_ledger'],'debit':delta,'credit':0,'narration':'Payroll clearing balancing line'})
                else: lines.append({'ledger_code':cfg['payroll_clearing_ledger'],'debit':0,'credit':-delta,'narration':'Payroll clearing balancing line'})
            jid=_journal(c,run,'PAYROLL',lines,u.user_id)
        return {'run_id':run_id,'journal_id':jid,'status':'POSTED'}

    @app.post('/v90dm/payroll/runs/{run_id}/expense-allocation')
    def allocation(run_id:str, body:dict, request:Request):
        u=_perm(engine,request,'payroll_accounting.manage')
        dept=str(body.get('department_id') or '').strip(); amount=_money(body.get('amount'))
        if not dept or amount<=0: raise HTTPException(400,'department_id and positive amount are required')
        with engine.begin() as c:
            r=c.execute(text('SELECT organization_id,entity_id FROM hr_payroll_run WHERE run_id=:r'),{'r':run_id}).mappings().first()
            if not r: raise HTTPException(404,'payroll run not found')
            i=str(uuid4()); c.execute(text('''INSERT INTO hr_payroll_expense_allocation(allocation_id,run_id,organization_id,entity_id,department_id,amount,basis,created_by)
                VALUES(:i,:r,:o,:e,:d,:a,:b,:u) ON CONFLICT(run_id,department_id) DO UPDATE SET amount=:a,basis=:b'''),{'i':i,'r':run_id,'o':r['organization_id'],'e':r['entity_id'],'d':dept,'a':float(amount),'b':str(body.get('basis') or 'MANUAL'),'u':str(u.user_id)})
        return {'allocation_id':i,'amount':float(amount),'status':'SAVED'}

    @app.post('/v90dm/payroll/runs/{run_id}/production-labour')
    def production_labour(run_id:str, body:dict, request:Request):
        u=_perm(engine,request,'payroll_accounting.post')
        amount=_money(body.get('amount')); batch=str(body.get('production_batch_id') or '').strip()
        if amount<=0 or not batch: raise HTTPException(400,'production_batch_id and positive amount are required')
        with engine.begin() as c:
            run=c.execute(text('SELECT * FROM hr_payroll_run WHERE run_id=:r'),{'r':run_id}).mappings().first()
            if not run: raise HTTPException(404,'payroll run not found')
            cfg=_config(c,run['organization_id'],run['entity_id'])
            jid=_journal(c,run,'PRODUCTION_LABOUR',[{'ledger_code':cfg['production_labour_ledger'],'debit':amount,'credit':0,'production_batch_id':batch,'narration':'Production labour cost'}, {'ledger_code':cfg['payroll_clearing_ledger'],'debit':0,'credit':amount,'production_batch_id':batch,'narration':'Payroll labour clearing'}],u.user_id, f'LAB-{batch}')
        return {'journal_id':jid,'production_batch_id':batch,'amount':float(amount),'status':'POSTED'}

    @app.post('/v90dm/payroll/runs/{run_id}/recovery')
    def recovery(run_id:str, body:dict, request:Request):
        u=_perm(engine,request,'payroll_accounting.manage')
        emp=str(body.get('employee_id') or '').strip(); amount=_money(body.get('amount'))
        if not emp or amount<=0: raise HTTPException(400,'employee_id and positive amount are required')
        with engine.begin() as c:
            r=c.execute(text('SELECT organization_id,entity_id FROM hr_payroll_run WHERE run_id=:r'),{'r':run_id}).mappings().first()
            if not r: raise HTTPException(404,'payroll run not found')
            i=str(uuid4()); c.execute(text('''INSERT INTO hr_payroll_employee_recovery(recovery_id,run_id,employee_id,organization_id,entity_id,recovery_type,amount,ledger_code,created_by)
                VALUES(:i,:r,:emp,:o,:e,:t,:a,:l,:u)'''),{'i':i,'r':run_id,'emp':emp,'o':r['organization_id'],'e':r['entity_id'],'t':str(body.get('recovery_type') or 'ADVANCE'),'a':float(amount),'l':str(body.get('ledger_code') or 'EMPLOYEE_ADVANCES'),'u':str(u.user_id)})
        return {'recovery_id':i,'amount':float(amount),'status':'OPEN'}

    @app.post('/v90dm/payroll/runs/{run_id}/reconcile')
    def reconcile(run_id:str, body:dict, request:Request):
        u=_perm(engine,request,'payroll_accounting.reconcile')
        with engine.begin() as c:
            r=c.execute(text('SELECT * FROM hr_payroll_run WHERE run_id=:r'),{'r':run_id}).mappings().first()
            if not r: raise HTTPException(404,'payroll run not found')
            payroll=_money(r['net_total']); bank=_money(body.get('bank_paid')); stat=_money(body.get('statutory_payable')); gl_salary=_money(body.get('gl_salary',r['gross_total'])); gl_payable=_money(body.get('gl_payable',payroll))
            diff=_money(payroll-bank)+_money(gl_payable-payroll)
            status='MATCHED' if diff==0 else 'EXCEPTION'
            i=str(uuid4()); c.execute(text('''INSERT INTO hr_payroll_accounting_reconciliation(reconciliation_id,run_id,organization_id,entity_id,payroll_net,bank_paid,statutory_payable,gl_salary,gl_payable,difference,status,notes,reconciled_by,reconciled_at)
                VALUES(:i,:r,:o,:e,:p,:b,:s,:gs,:gp,:d,:st,:n,:u,CURRENT_TIMESTAMP)
                ON CONFLICT(run_id) DO UPDATE SET bank_paid=:b,statutory_payable=:s,gl_salary=:gs,gl_payable=:gp,difference=:d,status=:st,notes=:n,reconciled_by=:u,reconciled_at=CURRENT_TIMESTAMP'''),{'i':i,'r':run_id,'o':r['organization_id'],'e':r['entity_id'],'p':float(payroll),'b':float(bank),'s':float(stat),'gs':float(gl_salary),'gp':float(gl_payable),'d':float(diff),'st':status,'n':body.get('notes'),'u':str(u.user_id)})
        return {'run_id':run_id,'status':status,'difference':float(diff)}

    @app.post('/v90dm/payroll/runs/{run_id}/close')
    def close(run_id:str, request:Request):
        u=_perm(engine,request,'payroll_accounting.close')
        with engine.begin() as c:
            r=c.execute(text('SELECT * FROM hr_payroll_run WHERE run_id=:r'),{'r':run_id}).mappings().first()
            if not r: raise HTTPException(404,'payroll run not found')
            rec=c.execute(text('SELECT status FROM hr_payroll_accounting_reconciliation WHERE run_id=:r'),{'r':run_id}).scalar()
            if rec!='MATCHED': raise HTTPException(409,'payroll accounting reconciliation must be MATCHED before close')
            i=str(uuid4()); c.execute(text('''INSERT INTO hr_payroll_month_close(close_id,organization_id,entity_id,period_id,run_id,status,closed_by,closed_at)
                VALUES(:i,:o,:e,:p,:r,'CLOSED',:u,CURRENT_TIMESTAMP) ON CONFLICT(organization_id,entity_id,period_id) DO UPDATE SET run_id=:r,status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),{'i':i,'o':r['organization_id'],'e':r['entity_id'],'p':r['period_id'],'r':run_id,'u':str(u.user_id)})
        return {'run_id':run_id,'period_id':r['period_id'],'status':'CLOSED'}

    @app.get('/v90dm/payroll/dashboard')
    def dashboard(request:Request, organization_id:str, entity_id:str):
        _perm(engine,request,'payroll_accounting.view')
        with engine.connect() as c:
            runs=c.execute(text('SELECT COUNT(*) cnt,COALESCE(SUM(net_total),0) net,COALESCE(SUM(employer_cost_total),0) employer FROM hr_payroll_run WHERE organization_id=:o AND entity_id=:e'),{'o':organization_id,'e':entity_id}).mappings().first()
            journals=c.execute(text("SELECT COUNT(*) FROM hr_payroll_accounting_journal WHERE organization_id=:o AND entity_id=:e AND status='POSTED'"),{'o':organization_id,'e':entity_id}).scalar()
            ex=c.execute(text("SELECT COUNT(*) FROM hr_payroll_accounting_reconciliation WHERE organization_id=:o AND entity_id=:e AND status='EXCEPTION'"),{'o':organization_id,'e':entity_id}).scalar()
            closed=c.execute(text("SELECT COUNT(*) FROM hr_payroll_month_close WHERE organization_id=:o AND entity_id=:e AND status='CLOSED'"),{'o':organization_id,'e':entity_id}).scalar()
        return {'payroll_runs':int(runs['cnt'] or 0),'net_payroll':float(runs['net'] or 0),'employer_cost':float(runs['employer'] or 0),'posted_journals':int(journals or 0),'reconciliation_exceptions':int(ex or 0),'closed_periods':int(closed or 0)}

    @app.get('/ui/payroll-accounting')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'payroll-accounting.html')

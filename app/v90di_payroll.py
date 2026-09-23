from __future__ import annotations
from pathlib import Path
from uuid import uuid4
from decimal import Decimal, ROUND_HALF_UP
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def _perm(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def _money(v): return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def register_v90di_routes(app: FastAPI, e):
    with e.begin() as c:
        for p,n in [('payroll.view','View Payroll'),('payroll.manage','Manage Payroll'),('payroll.approve','Approve Payroll')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_payroll_period(period_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_code TEXT NOT NULL,start_date DATE NOT NULL,end_date DATE NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,period_code))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_compensation(employee_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,basic_monthly NUMERIC NOT NULL DEFAULT 0,allowances_monthly NUMERIC NOT NULL DEFAULT 0,deductions_monthly NUMERIC NOT NULL DEFAULT 0,employer_cost_monthly NUMERIC NOT NULL DEFAULT 0,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_payroll_run(run_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'DRAFT',gross_total NUMERIC NOT NULL DEFAULT 0,deduction_total NUMERIC NOT NULL DEFAULT 0,net_total NUMERIC NOT NULL DEFAULT 0,employer_cost_total NUMERIC NOT NULL DEFAULT 0,approved BOOLEAN NOT NULL DEFAULT FALSE,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_payroll_line(line_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,employee_id TEXT NOT NULL,attendance_hours NUMERIC NOT NULL DEFAULT 0,overtime_hours NUMERIC NOT NULL DEFAULT 0,basic NUMERIC NOT NULL DEFAULT 0,allowances NUMERIC NOT NULL DEFAULT 0,overtime_pay NUMERIC NOT NULL DEFAULT 0,deductions NUMERIC NOT NULL DEFAULT 0,gross NUMERIC NOT NULL DEFAULT 0,net NUMERIC NOT NULL DEFAULT 0,employer_cost NUMERIC NOT NULL DEFAULT 0,batch_cost_allocated NUMERIC NOT NULL DEFAULT 0)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_payroll_batch_allocation(allocation_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,employee_id TEXT NOT NULL,batch_id TEXT NOT NULL,hours NUMERIC NOT NULL,cost NUMERIC NOT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_payroll_journal_boundary(journal_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,amount NUMERIC NOT NULL,status TEXT NOT NULL DEFAULT 'READY',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(run_id))'''))

    @app.post('/v90di/payroll/periods')
    def period(b:dict,request:Request):
        u=_perm(e,request,'payroll.manage')
        req=('organization_id','entity_id','period_code','start_date','end_date')
        if any(not str(b.get(k) or '').strip() for k in req): raise HTTPException(400,'required fields missing')
        i=str(uuid4())
        with e.begin() as c: c.execute(text('''INSERT INTO hr_payroll_period(period_id,organization_id,entity_id,period_code,start_date,end_date,status,created_by) VALUES(:i,:o,:e,:pc,:s,:d,:st,:u)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'pc':b['period_code'],'s':b['start_date'],'d':b['end_date'],'st':b.get('status','OPEN'),'u':str(u.user_id)})
        return {'period_id':i,'status':b.get('status','OPEN')}

    @app.post('/v90di/payroll/compensation')
    def compensation(b:dict,request:Request):
        _perm(e,request,'payroll.manage')
        req=('employee_id','organization_id','entity_id')
        if any(not str(b.get(k) or '').strip() for k in req): raise HTTPException(400,'required fields missing')
        vals={k:_money(b.get(k)) for k in ('basic_monthly','allowances_monthly','deductions_monthly','employer_cost_monthly')}
        if vals['employer_cost_monthly']==0: vals['employer_cost_monthly']=vals['basic_monthly']+vals['allowances_monthly']
        with e.begin() as c: c.execute(text('''INSERT INTO hr_compensation(employee_id,organization_id,entity_id,basic_monthly,allowances_monthly,deductions_monthly,employer_cost_monthly) VALUES(:i,:o,:e,:b,:a,:d,:ec) ON CONFLICT(employee_id) DO UPDATE SET basic_monthly=:b,allowances_monthly=:a,deductions_monthly=:d,employer_cost_monthly=:ec,updated_at=CURRENT_TIMESTAMP'''),{'i':b['employee_id'],'o':b['organization_id'],'e':b['entity_id'],'b':float(vals['basic_monthly']),'a':float(vals['allowances_monthly']),'d':float(vals['deductions_monthly']),'ec':float(vals['employer_cost_monthly'])})
        return {'employee_id':b['employee_id'],'status':'ACTIVE','employer_cost_monthly':float(vals['employer_cost_monthly'])}

    @app.post('/v90di/payroll/runs')
    def run(b:dict,request:Request):
        u=_perm(e,request,'payroll.manage')
        for k in ('organization_id','entity_id','period_id'): 
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with e.begin() as c:
            if not c.execute(text('SELECT 1 FROM hr_payroll_period WHERE period_id=:i'),{'i':b['period_id']}).scalar(): raise HTTPException(404,'payroll period not found')
            c.execute(text('INSERT INTO hr_payroll_run(run_id,organization_id,entity_id,period_id,created_by) VALUES(:i,:o,:e,:p,:u)'),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'p':b['period_id'],'u':str(u.user_id)})
        return {'run_id':i,'status':'DRAFT'}

    @app.post('/v90di/payroll/runs/{run_id}/calculate')
    def calculate(run_id:str,request:Request):
        _perm(e,request,'payroll.manage')
        with e.begin() as c:
            run=c.execute(text('SELECT * FROM hr_payroll_run WHERE run_id=:i'),{'i':run_id}).mappings().first()
            if not run: raise HTTPException(404,'payroll run not found')
            emps=c.execute(text('SELECT employee_id,basic_monthly,allowances_monthly,deductions_monthly,employer_cost_monthly FROM hr_compensation WHERE organization_id=:o AND entity_id=:e'),{'o':run['organization_id'],'e':run['entity_id']}).mappings().all()
            c.execute(text('DELETE FROM hr_payroll_line WHERE run_id=:i'),{'i':run_id})
            gross=ded=net=empc=Decimal('0')
            for x in emps:
                basic=_money(x['basic_monthly']); allow=_money(x['allowances_monthly']); d=_money(x['deductions_monthly']); emp=_money(x['employer_cost_monthly']); g=basic+allow; n=g-d
                lid=str(uuid4()); c.execute(text('''INSERT INTO hr_payroll_line(line_id,run_id,employee_id,basic,allowances,deductions,gross,net,employer_cost) VALUES(:i,:r,:e,:b,:a,:d,:g,:n,:ec)'''),{'i':lid,'r':run_id,'e':x['employee_id'],'b':float(basic),'a':float(allow),'d':float(d),'g':float(g),'n':float(n),'ec':float(emp)}); gross+=g; ded+=d; net+=n; empc+=emp
            c.execute(text('UPDATE hr_payroll_run SET gross_total=:g,deduction_total=:d,net_total=:n,employer_cost_total=:ec,status=\'CALCULATED\' WHERE run_id=:i'),{'g':float(gross),'d':float(ded),'n':float(net),'ec':float(empc),'i':run_id})
        return {'run_id':run_id,'status':'CALCULATED','gross_total':float(gross),'deduction_total':float(ded),'net_total':float(net),'employer_cost_total':float(empc)}

    @app.post('/v90di/payroll/runs/{run_id}/allocate-batch')
    def allocate(run_id:str,b:dict,request:Request):
        u=_perm(e,request,'payroll.manage')
        for k in ('employee_id','batch_id','hours'):
            if b.get(k) in (None,''): raise HTTPException(400,f'{k} is required')
        with e.begin() as c:
            row=c.execute(text('SELECT basic,allowances,overtime_pay,employer_cost FROM hr_payroll_line WHERE run_id=:r AND employee_id=:e'),{'r':run_id,'e':b['employee_id']}).mappings().first()
            if not row: raise HTTPException(404,'payroll employee line not found')
            total=float(row['basic'] or 0)+float(row['allowances'] or 0)+float(row['overtime_pay'] or 0)+float(row['employer_cost'] or 0)
            hours=float(b['hours']); cost=hours*float(b.get('hourly_rate') or (total/max(hours,1)))
            i=str(uuid4()); c.execute(text('INSERT INTO hr_payroll_batch_allocation(allocation_id,run_id,employee_id,batch_id,hours,cost,created_by) VALUES(:i,:r,:e,:b,:h,:c,:u)'),{'i':i,'r':run_id,'e':b['employee_id'],'b':b['batch_id'],'h':hours,'c':cost,'u':str(u.user_id)})
            c.execute(text('UPDATE hr_payroll_line SET batch_cost_allocated=batch_cost_allocated+:c WHERE run_id=:r AND employee_id=:e'),{'c':cost,'r':run_id,'e':b['employee_id']})
        return {'allocation_id':i,'cost':round(cost,2)}

    @app.post('/v90di/payroll/runs/{run_id}/approve')
    def approve(run_id:str,request:Request):
        _perm(e,request,'payroll.approve')
        with e.begin() as c:
            n=c.execute(text("UPDATE hr_payroll_run SET approved=TRUE,status='APPROVED' WHERE run_id=:i AND status='CALCULATED'"),{'i':run_id}).rowcount
            if not n: raise HTTPException(409,'run must be CALCULATED before approval')
        return {'run_id':run_id,'status':'APPROVED'}

    @app.post('/v90di/payroll/runs/{run_id}/journal-boundary')
    def journal_boundary(run_id:str,request:Request):
        _perm(e,request,'payroll.manage')
        with e.begin() as c:
            r=c.execute(text("SELECT organization_id,entity_id,net_total,approved FROM hr_payroll_run WHERE run_id=:i"),{'i':run_id}).mappings().first()
            if not r: raise HTTPException(404,'payroll run not found')
            if not r['approved']: raise HTTPException(409,'payroll run must be approved')
            i=str(uuid4()); c.execute(text("INSERT INTO hr_payroll_journal_boundary(journal_id,run_id,organization_id,entity_id,amount,status) VALUES(:i,:r,:o,:e,:a,'READY') ON CONFLICT(run_id) DO UPDATE SET amount=:a,status='READY'"),{'i':i,'r':run_id,'o':r['organization_id'],'e':r['entity_id'],'a':r['net_total']})
        return {'run_id':run_id,'journal_boundary':'READY','amount':float(r['net_total'] or 0)}

    @app.get('/v90di/payroll/dashboard')
    def dashboard(request:Request,organization_id:str,entity_id:str):
        _perm(e,request,'payroll.view')
        with e.connect() as c:
            x=c.execute(text('SELECT COUNT(*),COALESCE(SUM(net_total),0),COALESCE(SUM(employer_cost_total),0) FROM hr_payroll_run WHERE organization_id=:o AND entity_id=:e'),{'o':organization_id,'e':entity_id}).first()
            p=c.execute(text("SELECT COUNT(*) FROM hr_payroll_run WHERE organization_id=:o AND entity_id=:e AND status='CALCULATED'"),{'o':organization_id,'e':entity_id}).scalar()
        return {'payroll_runs':int(x[0] or 0),'net_payroll':float(x[1] or 0),'employer_cost':float(x[2] or 0),'pending_approval':int(p or 0)}

    @app.get('/ui/payroll')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'payroll.html')

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

def register_v90dl_routes(app: FastAPI, e):
    with e.begin() as c:
        for p,n in [('payroll_settlement.view','View Payroll Settlement'),('payroll_settlement.manage','Manage Payroll Settlement'),('payroll_settlement.approve','Approve Payroll Settlement'),('payroll_settlement.reconcile','Reconcile Payroll Settlement')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':p.replace('.',' ').title()})
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_employee_bank(employee_bank_id TEXT PRIMARY KEY,employee_id TEXT NOT NULL,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,bank_name TEXT NOT NULL,account_number_masked TEXT NOT NULL,ifsc TEXT NOT NULL,is_primary BOOLEAN NOT NULL DEFAULT TRUE,status TEXT NOT NULL DEFAULT 'ACTIVE',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_payroll_payment_batch(payment_batch_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,run_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'DRAFT',total_amount NUMERIC NOT NULL DEFAULT 0,approved BOOLEAN NOT NULL DEFAULT FALSE,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(run_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_payroll_payment_instruction(instruction_id TEXT PRIMARY KEY,payment_batch_id TEXT NOT NULL,employee_id TEXT NOT NULL,amount NUMERIC NOT NULL,bank_id TEXT,reference TEXT,status TEXT NOT NULL DEFAULT 'PENDING',failure_reason TEXT,paid_at TIMESTAMP,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_payslip(payslip_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,employee_id TEXT NOT NULL,period_id TEXT NOT NULL,gross NUMERIC NOT NULL, deductions NUMERIC NOT NULL,net NUMERIC NOT NULL,status TEXT NOT NULL DEFAULT 'GENERATED',issued_at TIMESTAMP,UNIQUE(run_id,employee_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_statutory_settlement(settlement_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,run_id TEXT NOT NULL,statutory_code TEXT NOT NULL,amount NUMERIC NOT NULL,reference_number TEXT,status TEXT NOT NULL DEFAULT 'PENDING',paid_at TIMESTAMP,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_payroll_settlement_reconciliation(reconciliation_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,run_id TEXT NOT NULL,payroll_amount NUMERIC NOT NULL,bank_amount NUMERIC NOT NULL,statutory_amount NUMERIC NOT NULL,difference NUMERIC NOT NULL,status TEXT NOT NULL DEFAULT 'EXCEPTION',resolution_reason TEXT,resolved_by TEXT,resolved_at TIMESTAMP,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))

    @app.post('/v90dl/payroll/bank-accounts')
    def bank(b:dict,request:Request):
        _perm(e,request,'payroll_settlement.manage')
        for k in ('employee_id','organization_id','entity_id','bank_name','account_number','ifsc'):
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4()); acct=str(b['account_number']); masked=('*' * max(0,len(acct)-4))+acct[-4:]
        with e.begin() as c: c.execute(text('INSERT INTO hr_employee_bank(employee_bank_id,employee_id,organization_id,entity_id,bank_name,account_number_masked,ifsc,is_primary) VALUES(:i,:e,:o,:en,:b,:a,:f,:p)'),{'i':i,'e':b['employee_id'],'o':b['organization_id'],'en':b['entity_id'],'b':b['bank_name'],'a':masked,'f':b['ifsc'],'p':bool(b.get('is_primary',True))})
        return {'employee_bank_id':i,'account_number_masked':masked}

    @app.post('/v90dl/payroll/runs/{run_id}/payment-batch')
    def payment_batch(run_id:str,request:Request):
        u=_perm(e,request,'payroll_settlement.manage')
        with e.begin() as c:
            r=c.execute(text('SELECT organization_id,entity_id,net_total,approved FROM hr_payroll_run WHERE run_id=:r'),{'r':run_id}).mappings().first()
            if not r: raise HTTPException(404,'payroll run not found')
            if not r['approved']: raise HTTPException(409,'payroll run must be approved')
            i=str(uuid4()); c.execute(text("INSERT INTO hr_payroll_payment_batch(payment_batch_id,organization_id,entity_id,run_id,status,total_amount,created_by) VALUES(:i,:o,:e,:r,'PREPARED',:a,:u) ON CONFLICT(run_id) DO UPDATE SET total_amount=:a,status='PREPARED'"),{'i':i,'o':r['organization_id'],'e':r['entity_id'],'r':run_id,'a':r['net_total'],'u':str(u.user_id)})
            batch=c.execute(text('SELECT payment_batch_id FROM hr_payroll_payment_batch WHERE run_id=:r'),{'r':run_id}).scalar()
            c.execute(text('DELETE FROM hr_payroll_payment_instruction WHERE payment_batch_id=:b'),{'b':batch})
            lines=c.execute(text('SELECT employee_id,net FROM hr_payroll_line WHERE run_id=:r'),{'r':run_id}).mappings().all()
            for x in lines: c.execute(text("INSERT INTO hr_payroll_payment_instruction(instruction_id,payment_batch_id,employee_id,amount,status) VALUES(:i,:b,:e,:a,'PENDING')"),{'i':str(uuid4()),'b':batch,'e':x['employee_id'],'a':x['net']})
        return {'payment_batch_id':batch,'status':'PREPARED'}

    @app.post('/v90dl/payroll/payment-batches/{batch_id}/approve')
    def approve_batch(batch_id:str,request:Request):
        _perm(e,request,'payroll_settlement.approve')
        with e.begin() as c:
            n=c.execute(text("UPDATE hr_payroll_payment_batch SET approved=TRUE,status='APPROVED' WHERE payment_batch_id=:i AND status='PREPARED'"),{'i':batch_id}).rowcount
            if not n: raise HTTPException(409,'payment batch must be PREPARED')
        return {'payment_batch_id':batch_id,'status':'APPROVED'}

    @app.post('/v90dl/payroll/payment-instructions/{instruction_id}/status')
    def instruction_status(instruction_id:str,b:dict,request:Request):
        _perm(e,request,'payroll_settlement.manage'); status=str(b.get('status') or '').upper()
        if status not in {'PENDING','PAID','FAILED'}: raise HTTPException(400,'unsupported payment status')
        with e.begin() as c:
            n=c.execute(text("UPDATE hr_payroll_payment_instruction SET status=:s,failure_reason=:f,paid_at=CASE WHEN :s='PAID' THEN CURRENT_TIMESTAMP ELSE paid_at END,reference=:r WHERE instruction_id=:i"),{'s':status,'f':b.get('failure_reason'),'r':b.get('reference'),'i':instruction_id}).rowcount
            if not n: raise HTTPException(404,'payment instruction not found')
        return {'instruction_id':instruction_id,'status':status}

    @app.post('/v90dl/payroll/runs/{run_id}/payslips')
    def payslips(run_id:str,request:Request):
        _perm(e,request,'payroll_settlement.manage')
        with e.begin() as c:
            r=c.execute(text('SELECT period_id FROM hr_payroll_run WHERE run_id=:r'),{'r':run_id}).mappings().first()
            if not r: raise HTTPException(404,'payroll run not found')
            lines=c.execute(text('SELECT employee_id,gross,deductions,net FROM hr_payroll_line WHERE run_id=:r'),{'r':run_id}).mappings().all()
            for x in lines: c.execute(text("INSERT INTO hr_payslip(payslip_id,run_id,employee_id,period_id,gross,deductions,net) VALUES(:i,:r,:e,:p,:g,:d,:n) ON CONFLICT(run_id,employee_id) DO UPDATE SET gross=:g,deductions=:d,net=:n"),{'i':str(uuid4()),'r':run_id,'e':x['employee_id'],'p':r['period_id'],'g':x['gross'],'d':x['deductions'],'n':x['net']})
        return {'run_id':run_id,'payslips_generated':len(lines)}

    @app.post('/v90dl/payroll/runs/{run_id}/statutory-settlement')
    def statutory(run_id:str,b:dict,request:Request):
        u=_perm(e,request,'payroll_settlement.manage')
        for k in ('organization_id','entity_id','statutory_code','amount'):
            if b.get(k) in (None,''): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with e.begin() as c: c.execute(text('INSERT INTO hr_statutory_settlement(settlement_id,organization_id,entity_id,run_id,statutory_code,amount,reference_number,status,created_by) VALUES(:i,:o,:e,:r,:s,:a,:ref,:st,:u)'),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'r':run_id,'s':b['statutory_code'],'a':b['amount'],'ref':b.get('reference_number'),'st':str(b.get('status','PAID')).upper(),'u':str(u.user_id)})
        return {'settlement_id':i,'status':str(b.get('status','PAID')).upper()}

    @app.post('/v90dl/payroll/runs/{run_id}/reconcile')
    def reconcile(run_id:str,b:dict,request:Request):
        u=_perm(e,request,'payroll_settlement.reconcile')
        with e.begin() as c:
            r=c.execute(text('SELECT organization_id,entity_id,net_total FROM hr_payroll_run WHERE run_id=:r'),{'r':run_id}).mappings().first()
            if not r: raise HTTPException(404,'payroll run not found')
            bank=float(b.get('bank_amount') or 0); statutory=float(b.get('statutory_amount') or 0); payroll=float(r['net_total'] or 0); diff=_money(payroll-bank)
            status='MATCHED' if diff==0 else 'EXCEPTION'; i=str(uuid4())
            c.execute(text('INSERT INTO hr_payroll_settlement_reconciliation(reconciliation_id,organization_id,entity_id,run_id,payroll_amount,bank_amount,statutory_amount,difference,status) VALUES(:i,:o,:e,:r,:p,:b,:s,:d,:st)'),{'i':i,'o':r['organization_id'],'e':r['entity_id'],'r':run_id,'p':payroll,'b':bank,'s':statutory,'d':float(diff),'st':status})
        return {'reconciliation_id':i,'status':status,'difference':float(diff)}

    @app.post('/v90dl/payroll/reconciliation/{reconciliation_id}/resolve')
    def resolve(reconciliation_id:str,b:dict,request:Request):
        u=_perm(e,request,'payroll_settlement.reconcile')
        if not str(b.get('reason') or '').strip(): raise HTTPException(400,'reason is required')
        with e.begin() as c:
            n=c.execute(text("UPDATE hr_payroll_settlement_reconciliation SET status='RESOLVED',resolution_reason=:r,resolved_by=:u,resolved_at=CURRENT_TIMESTAMP WHERE reconciliation_id=:i AND status='EXCEPTION'"),{'r':b['reason'],'u':str(u.user_id),'i':reconciliation_id}).rowcount
            if not n: raise HTTPException(409,'reconciliation is not an unresolved exception')
        return {'reconciliation_id':reconciliation_id,'status':'RESOLVED'}

    @app.get('/v90dl/payroll/dashboard')
    def dashboard(request:Request,organization_id:str,entity_id:str):
        _perm(e,request,'payroll_settlement.view')
        with e.connect() as c:
            p=c.execute(text("SELECT COUNT(*),COALESCE(SUM(total_amount),0) FROM hr_payroll_payment_batch WHERE organization_id=:o AND entity_id=:e"),{'o':organization_id,'e':entity_id}).first()
            ex=c.execute(text("SELECT COUNT(*) FROM hr_payroll_settlement_reconciliation WHERE organization_id=:o AND entity_id=:e AND status='EXCEPTION'"),{'o':organization_id,'e':entity_id}).scalar()
        return {'payment_batches':int(p[0] or 0),'payment_amount':float(p[1] or 0),'reconciliation_exceptions':int(ex or 0)}

    @app.get('/ui/payroll-settlement')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'payroll-settlement.html')

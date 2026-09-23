from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pathlib import Path
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def _perm(engine, request, permission):
    u=authenticate(request); p=permissions_for_user(engine,u.user_id)
    if permission not in p and 'admin.users' not in p: raise HTTPException(403,'permission denied')
    return u

def _ensure(engine):
    with engine.begin() as c:
        c.execute(text("""CREATE TABLE IF NOT EXISTS accounting_periods(
            period_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, period_key TEXT NOT NULL,
            start_date TEXT NOT NULL, end_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN',
            closed_by TEXT, closed_at TIMESTAMP, UNIQUE(organization_id,period_key))"""))
        c.execute(text("""CREATE TABLE IF NOT EXISTS accounting_period_closures(
            closure_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, period_key TEXT NOT NULL,
            closing_type TEXT NOT NULL, notes TEXT, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,period_key,closing_type))"""))

def _period(c,org,pk):
    r=c.execute(text('SELECT * FROM accounting_periods WHERE organization_id=:o AND period_key=:p'),{'o':org,'p':pk}).mappings().first()
    if not r: raise HTTPException(404,'accounting period not found')
    return r

def register_v90cb_routes(app, engine):
    _ensure(engine)
    @app.post('/v90cb/accounting/periods')
    def create_period(body:dict,request:Request):
        u=_perm(engine,request,'accounting.manage')
        for k in ('organization_id','period_key','start_date','end_date'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        pid=str(uuid4())
        with engine.begin() as c:
            c.execute(text('INSERT INTO accounting_periods(period_id,organization_id,period_key,start_date,end_date,status) VALUES(:i,:o,:p,:s,:e,:st)'),{'i':pid,'o':body['organization_id'],'p':body['period_key'],'s':body['start_date'],'e':body['end_date'],'st':'OPEN'})
        return {'period_id':pid,'status':'OPEN','created_by':u.user_id}

    @app.get('/v90cb/accounting/periods')
    def periods(request:Request,organization_id:str):
        _perm(engine,request,'accounting.view')
        with engine.connect() as c:return {'items':[dict(x) for x in c.execute(text('SELECT * FROM accounting_periods WHERE organization_id=:o ORDER BY period_key DESC'),{'o':organization_id}).mappings().all()]}

    @app.get('/v90cb/accounting/general-ledger')
    def general_ledger(request:Request,organization_id:str,ledger_code:str|None=None,start_date:str|None=None,end_date:str|None=None):
        _perm(engine,request,'accounting.view')
        q='''SELECT p.posting_id,p.organization_id,p.entity_id,p.source_type,p.source_id,p.posting_date,p.voucher_no,p.voucher_type,
                    l.ledger_code,l.ledger_name,l.debit,l.credit,l.tax_component,l.narration
             FROM accounting_posting_lines l JOIN accounting_postings p ON p.posting_id=l.posting_id WHERE p.organization_id=:o'''; par={'o':organization_id}
        if ledger_code:q+=' AND l.ledger_code=:lc';par['lc']=ledger_code
        if start_date:q+=' AND p.posting_date>=:s';par['s']=start_date
        if end_date:q+=' AND p.posting_date<=:e';par['e']=end_date
        q+=' ORDER BY p.posting_date,p.created_at,l.line_id'
        with engine.connect() as c: rows=[dict(x) for x in c.execute(text(q),par).mappings().all()]
        bal=Decimal('0')
        for r in rows: bal += Decimal(str(r['debit'] or 0))-Decimal(str(r['credit'] or 0))
        return {'items':rows,'net_debit':float(bal)}

    @app.get('/v90cb/accounting/trial-balance')
    def trial_balance(request:Request,organization_id:str,entity_id:str|None=None,start_date:str|None=None,end_date:str|None=None):
        _perm(engine,request,'accounting.view')
        q='''SELECT l.ledger_code,MAX(l.ledger_name) ledger_name,COALESCE(SUM(l.debit),0) debit,COALESCE(SUM(l.credit),0) credit
             FROM accounting_posting_lines l JOIN accounting_postings p ON p.posting_id=l.posting_id WHERE p.organization_id=:o'''; par={'o':organization_id}
        if entity_id:q+=' AND p.entity_id=:e';par['e']=entity_id
        if start_date:q+=' AND p.posting_date>=:s';par['s']=start_date
        if end_date:q+=' AND p.posting_date<=:ed';par['ed']=end_date
        q+=' GROUP BY l.ledger_code ORDER BY l.ledger_code'
        with engine.connect() as c: rows=[dict(x) for x in c.execute(text(q),par).mappings().all()]
        total_d=sum(Decimal(str(r['debit'] or 0)) for r in rows); total_c=sum(Decimal(str(r['credit'] or 0)) for r in rows)
        for r in rows:r['debit']=float(r['debit'] or 0);r['credit']=float(r['credit'] or 0);r['balance']=round(r['debit']-r['credit'],2)
        return {'items':rows,'total_debit':float(total_d),'total_credit':float(total_c),'balanced':total_d.quantize(Decimal('.01'))==total_c.quantize(Decimal('.01'))}

    @app.get('/v90cb/accounting/gst-reconciliation')
    def gst_reconciliation(request:Request,organization_id:str,entity_id:str|None=None,period_key:str|None=None):
        _perm(engine,request,'accounting.view')
        q='''SELECT supply_type,COALESCE(SUM(taxable_value),0) taxable,COALESCE(SUM(igst_value),0) igst,COALESCE(SUM(cgst_value),0) cgst,
                    COALESCE(SUM(sgst_value),0) sgst,COALESCE(SUM(cess_value),0) cess,COALESCE(SUM(total_tax),0) tax
             FROM tax_transaction_lines WHERE organization_id=:o''';par={'o':organization_id}
        if entity_id:q+=' AND entity_id=:e';par['e']=entity_id
        if period_key:q+=' AND substr(created_at,1,7)=:pk';par['pk']=period_key
        q+=' GROUP BY supply_type ORDER BY supply_type'
        with engine.connect() as c:rows=[dict(x) for x in c.execute(text(q),par).mappings().all()]
        for r in rows:
            for k in ('taxable','igst','cgst','sgst','cess','tax'):r[k]=float(r[k] or 0)
        return {'period_key':period_key,'items':rows,'control':'SOURCE_TAX_TRANSACTIONS'}

    @app.post('/v90cb/accounting/periods/{period_id}/close')
    def close_period(period_id:str,body:dict,request:Request):
        u=_perm(engine,request,'accounting.manage')
        with engine.begin() as c:
            r=c.execute(text('SELECT * FROM accounting_periods WHERE period_id=:i'),{'i':period_id}).mappings().first()
            if not r: raise HTTPException(404,'accounting period not found')
            if r['status']=='CLOSED': return {'period_id':period_id,'status':'CLOSED','idempotent':True}
            tb=trial_balance(request, r['organization_id'], None, r['start_date'], r['end_date'])
            if not tb['balanced']: raise HTTPException(409,'cannot close unbalanced accounting period')
            c.execute(text('UPDATE accounting_periods SET status=\'CLOSED\',closed_by=:u,closed_at=CURRENT_TIMESTAMP WHERE period_id=:i'),{'u':str(u.user_id),'i':period_id})
            c.execute(text('INSERT INTO accounting_period_closures(closure_id,organization_id,period_key,closing_type,notes,created_by) VALUES(:i,:o,:p,\'PERIOD_CLOSE\',:n,:u)'),{'i':str(uuid4()),'o':r['organization_id'],'p':r['period_key'],'n':body.get('notes'),'u':str(u.user_id)})
        return {'period_id':period_id,'status':'CLOSED','idempotent':False}

    @app.get('/ui/accounting-controls')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'accounting-controls.html')

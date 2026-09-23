from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def _perm(engine, request, permission):
    u=authenticate(request); p=permissions_for_user(engine,u.user_id)
    if permission not in p and 'admin.users' not in p: raise HTTPException(403,'permission denied')
    return u

def _d(v): return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def _ensure(engine):
    with engine.begin() as c:
        perms=[('reconciliation.view','View accounting reconciliations'),('reconciliation.manage','Manage accounting reconciliations'),('reconciliation.signoff','Sign off accounting reconciliations')]
        for p,n in perms: c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS accounting_reconciliation_runs(run_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL, reconciliation_type TEXT NOT NULL, source_total NUMERIC NOT NULL DEFAULT 0, ledger_total NUMERIC NOT NULL DEFAULT 0, difference NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL, exception_reason TEXT, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, signed_by TEXT, signed_at TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS accounting_reconciliation_exceptions(exception_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', resolution TEXT, resolved_by TEXT, resolved_at TIMESTAMP)'''))

def register_v90cm_routes(app,engine):
    _ensure(engine)
    @app.post('/v90cm/reconcile')
    def reconcile(body:dict,request:Request):
        u=_perm(engine,request,'reconciliation.manage')
        org,ent,period,typ=body.get('organization_id'),body.get('entity_id'),body.get('period_key'),body.get('reconciliation_type')
        if not all(str(x or '').strip() for x in (org,ent,period,typ)): raise HTTPException(400,'organization_id, entity_id, period_key and reconciliation_type are required')
        source=_d(body.get('source_total')); ledger=_d(body.get('ledger_total')); diff=_d(source-ledger)
        status='MATCHED' if diff==0 else 'EXCEPTION'; rid=str(uuid4())
        with engine.begin() as c:
            c.execute(text('INSERT INTO accounting_reconciliation_runs(run_id,organization_id,entity_id,period_key,reconciliation_type,source_total,ledger_total,difference,status,exception_reason,created_by) VALUES(:i,:o,:e,:p,:t,:s,:l,:d,:st,:r,:u)'),{'i':rid,'o':org,'e':ent,'p':period,'t':typ,'s':float(source),'l':float(ledger),'d':float(diff),'st':status,'r':body.get('exception_reason') if diff else None,'u':str(u.user_id)})
            if diff: c.execute(text("INSERT INTO accounting_reconciliation_exceptions(exception_id,run_id,reason) VALUES(:i,:r,:x)"),{'i':str(uuid4()),'r':rid,'x':body.get('exception_reason') or 'reconciliation difference'})
        return {'run_id':rid,'status':status,'difference':float(diff)}
    @app.get('/v90cm/reconcile')
    def list_reconcile(request:Request,organization_id:str,entity_id:str,period_key:str):
        _perm(engine,request,'reconciliation.view')
        with engine.connect() as c: rows=c.execute(text('SELECT * FROM accounting_reconciliation_runs WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY created_at DESC'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        return {'items':[dict(r) for r in rows]}
    @app.post('/v90cm/reconcile/{run_id}/signoff')
    def signoff(run_id:str,request:Request):
        u=_perm(engine,request,'reconciliation.signoff')
        with engine.begin() as c:
            r=c.execute(text('SELECT status FROM accounting_reconciliation_runs WHERE run_id=:i'),{'i':run_id}).scalar()
            if not r: raise HTTPException(404,'reconciliation run not found')
            if r!='MATCHED': raise HTTPException(409,'reconciliation has unresolved exceptions')
            c.execute(text("UPDATE accounting_reconciliation_runs SET signed_by=:u,signed_at=CURRENT_TIMESTAMP,status='SIGNED' WHERE run_id=:i"),{'u':str(u.user_id),'i':run_id})
        return {'run_id':run_id,'status':'SIGNED'}
    @app.post('/v90cm/exceptions/{exception_id}/resolve')
    def resolve(exception_id:str,body:dict,request:Request):
        u=_perm(engine,request,'reconciliation.manage'); resolution=str(body.get('resolution') or '').strip()
        if not resolution: raise HTTPException(400,'resolution is required')
        with engine.begin() as c:
            r=c.execute(text('SELECT status FROM accounting_reconciliation_exceptions WHERE exception_id=:i'),{'i':exception_id}).scalar()
            if not r: raise HTTPException(404,'exception not found')
            if r=='RESOLVED': raise HTTPException(409,'exception already resolved')
            c.execute(text("UPDATE accounting_reconciliation_exceptions SET status='RESOLVED',resolution=:r,resolved_by=:u,resolved_at=CURRENT_TIMESTAMP WHERE exception_id=:i"),{'r':resolution,'u':str(u.user_id),'i':exception_id})
        return {'exception_id':exception_id,'status':'RESOLVED'}
    @app.get('/ui/accounting-reconciliation')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'accounting-reconciliation.html')

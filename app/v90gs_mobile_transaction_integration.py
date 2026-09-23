from __future__ import annotations
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed

def _now(): return datetime.now(timezone.utc).isoformat()
def _user(engine, request, entity_id, location_id, write=False):
    u=authenticate(request); p='mobile.txn.write' if write else 'mobile.txn.view'
    if p not in permissions_for_user(engine,u.user_id): raise HTTPException(403,'permission denied')
    try: assert_entity_location_allowed(engine,u.user_id,str(entity_id),str(location_id) if location_id else None)
    except PermissionError as exc: raise HTTPException(403,str(exc)) from exc
    return u

def ensure_v90gs_schema(engine):
    stmts=[
    """CREATE TABLE IF NOT EXISTS mobile_transaction_integrations (integration_id TEXT PRIMARY KEY,event_id TEXT NOT NULL UNIQUE,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,location_id TEXT NULL,transaction_type TEXT NOT NULL,reference_type TEXT NULL,reference_id TEXT NULL,status TEXT NOT NULL DEFAULT 'PENDING',validation_code TEXT NULL,validation_message TEXT NULL,processed_at TEXT NULL,created_by TEXT NOT NULL,created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS mobile_transaction_audit (audit_id TEXT PRIMARY KEY,integration_id TEXT NOT NULL,action TEXT NOT NULL,from_status TEXT NULL,to_status TEXT NULL,message TEXT NULL,actor_user_id TEXT NOT NULL,created_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS ix_mobile_txn_scope ON mobile_transaction_integrations(entity_id,location_id,status)",
    "CREATE INDEX IF NOT EXISTS ix_mobile_txn_ref ON mobile_transaction_integrations(reference_type,reference_id,status)"]
    with engine.begin() as c:
        for s in stmts: c.execute(text(s))
        for p,n in [('mobile.txn.view','View mobile transaction integration'),('mobile.txn.write','Validate and process mobile transactions')]:
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"),{'p':p,'n':n})
        for r in ('manager','super_admin','operator','production','quality','warehouse','dispatch','salesperson','mis'):
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'mobile.txn.view') ON CONFLICT(role_id,permission_id) DO NOTHING"),{'r':r})
        for r in ('manager','super_admin','operator','production','quality','warehouse','dispatch','salesperson'):
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'mobile.txn.write') ON CONFLICT(role_id,permission_id) DO NOTHING"),{'r':r})

class IntegrateIn(BaseModel):
    organization_id: UUID; entity_id: UUID; location_id: UUID|None=None; event_id: UUID
    transaction_type: str=Field(min_length=2,max_length=60); reference_type: str|None=None; reference_id: UUID|None=None
    payload: dict={}

def register_v90gs_routes(app:FastAPI,engine):
    ensure_v90gs_schema(engine)
    @app.get('/ui/mobile-transaction-integration')
    def ui(): return FileResponse('web/mobile-transaction-integration.html')
    @app.post('/v90gs/mobile/transactions/integrate')
    def integrate(body:IntegrateIn,request:Request):
        u=_user(engine,request,body.entity_id,body.location_id,True)
        with engine.begin() as c:
            exists=c.execute(text('SELECT integration_id,status FROM mobile_transaction_integrations WHERE event_id=:e'),{'e':str(body.event_id)}).first()
            if exists: return {'integration_id':exists[0],'status':exists[1],'idempotent':True}
            iid=str(uuid4()); t=body.transaction_type.upper()
            allowed={'DELIVERY_CONFIRM','PICK_CONFIRM','RECEIPT_CONFIRM','PRODUCTION_CONFIRM','STOCK_COUNT','RETURN_CONFIRM','QUALITY_CONFIRM','DISPATCH_CONFIRM'}
            if t not in allowed:
                status,code,msg='REJECTED','UNSUPPORTED_TRANSACTION','Unsupported mobile transaction type'
            elif not body.reference_type or not body.reference_id:
                status,code,msg='REJECTED','REFERENCE_REQUIRED','Reference type and reference id are required'
            else:
                status,code,msg='READY','VALIDATED','Transaction validated and ready for ERP posting'
            c.execute(text("INSERT INTO mobile_transaction_integrations(integration_id,event_id,organization_id,entity_id,location_id,transaction_type,reference_type,reference_id,status,validation_code,validation_message,created_by,created_at) VALUES(:i,:ev,:o,:e,:l,:t,:rt,:ri,:s,:c,:m,:u,:d)"),{'i':iid,'ev':str(body.event_id),'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id) if body.location_id else None,'t':t,'rt':body.reference_type,'ri':str(body.reference_id) if body.reference_id else None,'s':status,'c':code,'m':msg,'u':u.user_id,'d':_now()})
            c.execute(text("INSERT INTO mobile_transaction_audit(audit_id,integration_id,action,from_status,to_status,message,actor_user_id,created_at) VALUES(:a,:i,'VALIDATE',NULL,:s,:m,:u,:d)"),{'a':str(uuid4()),'i':iid,'s':status,'m':msg,'u':u.user_id,'d':_now()})
        return {'integration_id':iid,'status':status,'validation_code':code,'validation_message':msg}
    @app.post('/v90gs/mobile/transactions/{integration_id}/post')
    def post(integration_id:UUID,request:Request):
        with engine.connect() as c: row=c.execute(text('SELECT * FROM mobile_transaction_integrations WHERE integration_id=:i'),{'i':str(integration_id)}).mappings().first()
        if not row: raise HTTPException(404,'integration not found')
        u=_user(engine,request,row['entity_id'],row['location_id'],True)
        if row['status']=='POSTED': return {'integration_id':str(integration_id),'status':'POSTED','idempotent':True}
        if row['status']!='READY': raise HTTPException(409,f"transaction is {row['status']} and cannot be posted")
        with engine.begin() as c:
            c.execute(text("UPDATE mobile_transaction_integrations SET status='POSTED',processed_at=:t WHERE integration_id=:i"),{'t':_now(),'i':str(integration_id)})
            c.execute(text("INSERT INTO mobile_transaction_audit(audit_id,integration_id,action,from_status,to_status,message,actor_user_id,created_at) VALUES(:a,:i,'POST',:f,'POSTED','ERP posting boundary accepted; source transaction remains system-of-record',:u,:d)"),{'a':str(uuid4()),'i':str(integration_id),'f':row['status'],'u':u.user_id,'d':_now()})
        return {'integration_id':str(integration_id),'status':'POSTED'}
    @app.get('/v90gs/mobile/transactions')
    def list_txns(organization_id:UUID,entity_id:UUID,location_id:UUID|None=None,status:str|None=None,request:Request=None):
        _user(engine,request,entity_id,location_id,False)
        q='SELECT * FROM mobile_transaction_integrations WHERE organization_id=:o AND entity_id=:e'; p={'o':str(organization_id),'e':str(entity_id)}
        if location_id: q+=' AND (location_id=:l OR location_id IS NULL)'; p['l']=str(location_id)
        if status: q+=' AND status=:s'; p['s']=status.upper()
        q+=' ORDER BY created_at DESC'
        with engine.connect() as c: rows=c.execute(text(q),p).mappings().all()
        return {'transactions':[dict(r) for r in rows]}

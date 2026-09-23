from __future__ import annotations
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine
from .auth import authenticate
from .identity import permissions_for_user
from .v90fn_security_rbac_scope_hardening import assert_security_scope

PERM_VIEW='release.sla.view'
PERM_MANAGE='release.sla.manage'
STATUSES=('OPEN','ACKNOWLEDGED','MITIGATED','CLOSED','WAIVED')
SEVERITIES=('LOW','MEDIUM','HIGH','CRITICAL')

class PolicyIn(BaseModel):
    organization_id:str|None=None; policy_code:str=Field(min_length=2,max_length=80); service_area:str=Field(min_length=2,max_length=120)
    target_minutes:int=Field(ge=1,le=525600); severity:str=Field(pattern='^(LOW|MEDIUM|HIGH|CRITICAL)$'); owner_user_id:str|None=None; note:str=Field(min_length=1,max_length=3000)
class BreachIn(BaseModel):
    policy_id:str=Field(min_length=1,max_length=100); reference_type:str=Field(min_length=2,max_length=60); reference_id:str=Field(min_length=1,max_length=100)
    opened_at:str=Field(min_length=10,max_length=40); due_at:str=Field(min_length=10,max_length=40); severity:str=Field(pattern='^(LOW|MEDIUM|HIGH|CRITICAL)$'); description:str=Field(min_length=1,max_length=3000)
class BreachUpdate(BaseModel):
    status:str=Field(pattern='^(OPEN|ACKNOWLEDGED|MITIGATED|CLOSED|WAIVED)$'); evidence_ref:str|None=None; note:str=Field(min_length=1,max_length=3000)
class ReviewIn(BaseModel):
    period_key:str=Field(min_length=4,max_length=40); organization_id:str|None=None; service_area:str=Field(min_length=2,max_length=120)
    target_compliance_pct:float=Field(ge=0,le=100); actual_compliance_pct:float=Field(ge=0,le=100); evidence_ref:str=Field(min_length=1,max_length=500); note:str=Field(min_length=1,max_length=3000)

def _u(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def _scope(e,u,o):
    try: assert_security_scope(e,u.user_id,organization_id=o)
    except PermissionError as ex: raise HTTPException(403,str(ex)) from ex

def ensure_v90gh_schema(e:Engine):
    stmts=[
    '''CREATE TABLE IF NOT EXISTS erp_ops_sla_policy(policy_id TEXT PRIMARY KEY,organization_id TEXT NULL,policy_code TEXT NOT NULL,service_area TEXT NOT NULL,target_minutes INTEGER NOT NULL,severity TEXT NOT NULL,owner_user_id TEXT NULL,status TEXT NOT NULL DEFAULT 'ACTIVE',note TEXT NOT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,policy_code))''',
    '''CREATE TABLE IF NOT EXISTS erp_ops_sla_breach(breach_id TEXT PRIMARY KEY,organization_id TEXT NULL,policy_id TEXT NOT NULL,reference_type TEXT NOT NULL,reference_id TEXT NOT NULL,opened_at TEXT NOT NULL,due_at TEXT NOT NULL,severity TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',description TEXT NOT NULL,owner_user_id TEXT NULL,evidence_ref TEXT NULL,resolution_note TEXT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS erp_ops_sla_review(review_id TEXT PRIMARY KEY,organization_id TEXT NULL,period_key TEXT NOT NULL,service_area TEXT NOT NULL,target_compliance_pct DOUBLE PRECISION NOT NULL,actual_compliance_pct DOUBLE PRECISION NOT NULL,evidence_ref TEXT NOT NULL,note TEXT NOT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,period_key,service_area))''',
    'CREATE INDEX IF NOT EXISTS ix_sla_policy_scope ON erp_ops_sla_policy(organization_id,status,service_area,policy_code)',
    'CREATE INDEX IF NOT EXISTS ix_sla_breach_scope ON erp_ops_sla_breach(organization_id,status,severity,due_at)',
    'CREATE INDEX IF NOT EXISTS ix_sla_review_scope ON erp_ops_sla_review(organization_id,period_key,service_area)']
    with e.begin() as c:
        for s in stmts: c.execute(text(s))
        for p,n in [(PERM_VIEW,'View SLA policies, breaches and service reviews'),(PERM_MANAGE,'Manage SLA policies, breaches and service reviews')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':p})

def register_v90gh_routes(app:FastAPI,e:Engine):
    ensure_v90gh_schema(e)
    @app.post('/v90gh/sla/policies')
    def create_policy(b:PolicyIn,r:Request):
        u=_u(e,r,PERM_MANAGE); _scope(e,u,b.organization_id); pid=str(uuid4())
        try:
            with e.begin() as c:c.execute(text('INSERT INTO erp_ops_sla_policy(policy_id,organization_id,policy_code,service_area,target_minutes,severity,owner_user_id,note,created_by) VALUES(:i,:o,:c,:a,:t,:s,:w,:n,:u)'),{'i':pid,'o':b.organization_id,'c':b.policy_code.upper(),'a':b.service_area,'t':b.target_minutes,'s':b.severity,'w':b.owner_user_id,'n':b.note,'u':u.user_id})
        except Exception as ex: raise HTTPException(409,'SLA policy already exists for organization and policy code') from ex
        return {'policy_id':pid,'status':'ACTIVE'}
    @app.get('/v90gh/sla/policies')
    def list_policies(r:Request,organization_id:str|None=None):
        _u(e,r,PERM_VIEW)
        with e.connect() as c: rows=[dict(x) for x in c.execute(text('SELECT * FROM erp_ops_sla_policy WHERE organization_id IS NOT DISTINCT FROM :o ORDER BY policy_code'),{'o':organization_id}).mappings().all()]
        return {'policies':rows}
    @app.post('/v90gh/sla/breaches')
    def create_breach(b:BreachIn,r:Request,organization_id:str|None=None,owner_user_id:str|None=None):
        u=_u(e,r,PERM_MANAGE); _scope(e,u,organization_id); bid=str(uuid4())
        with e.connect() as c:
            p=c.execute(text('SELECT organization_id,status FROM erp_ops_sla_policy WHERE policy_id=:i'),{'i':b.policy_id}).mappings().first()
        if not p: raise HTTPException(404,'SLA policy not found')
        if p['status']!='ACTIVE': raise HTTPException(409,'SLA policy is not active')
        if p['organization_id']!=organization_id and not (p['organization_id'] is None and organization_id is None): raise HTTPException(403,'SLA policy organization mismatch')
        with e.begin() as c:c.execute(text('INSERT INTO erp_ops_sla_breach(breach_id,organization_id,policy_id,reference_type,reference_id,opened_at,due_at,severity,description,owner_user_id,created_by) VALUES(:i,:o,:p,:t,:r,:op,:d,:s,:n,:w,:u)'),{'i':bid,'o':organization_id,'p':b.policy_id,'t':b.reference_type,'r':b.reference_id,'op':b.opened_at,'d':b.due_at,'s':b.severity,'n':b.description,'w':owner_user_id,'u':u.user_id})
        return {'breach_id':bid,'status':'OPEN'}
    @app.get('/v90gh/sla/breaches')
    def list_breaches(r:Request,organization_id:str|None=None,status:str|None=None):
        _u(e,r,PERM_VIEW); q='SELECT * FROM erp_ops_sla_breach WHERE organization_id IS NOT DISTINCT FROM :o'; p={'o':organization_id}
        if status: q+=' AND status=:s'; p['s']=status.upper()
        with e.connect() as c: rows=[dict(x) for x in c.execute(text(q+' ORDER BY due_at'),p).mappings().all()]
        return {'breaches':rows}
    @app.post('/v90gh/sla/breaches/{breach_id}/status')
    def breach_status(breach_id:str,b:BreachUpdate,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.connect() as c: row=c.execute(text('SELECT organization_id,status FROM erp_ops_sla_breach WHERE breach_id=:i'),{'i':breach_id}).mappings().first()
        if not row: raise HTTPException(404,'SLA breach not found')
        _scope(e,u,row['organization_id'])
        if b.status in ('CLOSED','WAIVED') and not b.evidence_ref: raise HTTPException(422,'evidence_ref required for CLOSED or WAIVED')
        if b.status=='CLOSED' and row['status'] not in ('MITIGATED','WAIVED'): raise HTTPException(409,'SLA breach must be MITIGATED or WAIVED before CLOSED')
        with e.begin() as c:c.execute(text('UPDATE erp_ops_sla_breach SET status=:s,evidence_ref=COALESCE(:e,evidence_ref),resolution_note=:n,updated_at=CURRENT_TIMESTAMP WHERE breach_id=:i'),{'s':b.status,'e':b.evidence_ref,'n':b.note,'i':breach_id})
        return {'breach_id':breach_id,'status':b.status}
    @app.post('/v90gh/sla/reviews')
    def review(b:ReviewIn,r:Request):
        u=_u(e,r,PERM_MANAGE); _scope(e,u,b.organization_id)
        if b.actual_compliance_pct < b.target_compliance_pct and not b.evidence_ref: raise HTTPException(422,'evidence_ref required for SLA target miss')
        rid=str(uuid4())
        try:
            with e.begin() as c:c.execute(text('INSERT INTO erp_ops_sla_review(review_id,organization_id,period_key,service_area,target_compliance_pct,actual_compliance_pct,evidence_ref,note,created_by) VALUES(:i,:o,:p,:a,:t,:v,:e,:n,:u)'),{'i':rid,'o':b.organization_id,'p':b.period_key,'a':b.service_area,'t':b.target_compliance_pct,'v':b.actual_compliance_pct,'e':b.evidence_ref,'n':b.note,'u':u.user_id})
        except Exception as ex: raise HTTPException(409,'SLA service review already exists for organization, period and service area') from ex
        return {'review_id':rid,'status':'RECORDED','within_target':b.actual_compliance_pct>=b.target_compliance_pct}
    @app.get('/v90gh/sla/dashboard')
    def dashboard(r:Request,organization_id:str|None=None):
        _u(e,r,PERM_VIEW)
        with e.connect() as c:
            policies=c.execute(text("SELECT COUNT(*) FROM erp_ops_sla_policy WHERE organization_id IS NOT DISTINCT FROM :o AND status='ACTIVE'"),{'o':organization_id}).scalar_one()
            open_breaches=c.execute(text("SELECT COUNT(*) FROM erp_ops_sla_breach WHERE organization_id IS NOT DISTINCT FROM :o AND status NOT IN ('CLOSED','WAIVED')"),{'o':organization_id}).scalar_one()
            critical=c.execute(text("SELECT COUNT(*) FROM erp_ops_sla_breach WHERE organization_id IS NOT DISTINCT FROM :o AND severity='CRITICAL' AND status NOT IN ('CLOSED','WAIVED')"),{'o':organization_id}).scalar_one()
            overdue=c.execute(text("SELECT COUNT(*) FROM erp_ops_sla_breach WHERE organization_id IS NOT DISTINCT FROM :o AND status NOT IN ('CLOSED','WAIVED') AND due_at < CURRENT_TIMESTAMP"),{'o':organization_id}).scalar_one()
            reviews=c.execute(text("SELECT COUNT(*) FROM erp_ops_sla_review WHERE organization_id IS NOT DISTINCT FROM :o"),{'o':organization_id}).scalar_one()
        return {'active_policies':int(policies),'open_breaches':int(open_breaches),'critical_open_breaches':int(critical),'overdue_open_breaches':int(overdue),'service_reviews':int(reviews),'sla_gate_pass':int(critical)==0 and int(overdue)==0}
    @app.get('/ui/operations-sla')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'operations_sla.html')
    return {'allowed':True}

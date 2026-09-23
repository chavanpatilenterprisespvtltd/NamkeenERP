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

PERM_VIEW='release.go_live.view'; PERM_MANAGE='release.go_live.manage'
CONTROLS=(('RELEASE_CERTIFICATION','V90.gc production release certification is CLOSED'),('END_TO_END_UAT','Final end-to-end UAT evidence is complete'),('PRODUCTION_CUTOVER','Production cutover decision/evidence is recorded'),('ROLLBACK_DECISION','Rollback decision point and contingency evidence are recorded'),('OPERATIONAL_ACCEPTANCE','Operations/support acceptance is recorded'),('BUSINESS_SIGNOFF','Final business owner go-live signoff'))
class GoLiveIn(BaseModel):
    organization_id:str|None=None; period_key:str=Field(min_length=4,max_length=40); release_version:str=Field(min_length=3,max_length=40); environment:str=Field(pattern='^PRODUCTION$'); business_owner:str=Field(min_length=1,max_length=200); note:str=Field(min_length=1,max_length=3000)
class CheckIn(BaseModel):
    status:str=Field(pattern='^(PASS|FAIL|BLOCKED|WAIVED)$'); evidence_ref:str|None=None; note:str=Field(min_length=1,max_length=3000)
class EvidenceIn(BaseModel):
    evidence_ref:str=Field(min_length=1,max_length=500); note:str=Field(min_length=1,max_length=3000)

def _u(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def _scope(e,u,o):
    try: assert_security_scope(e,u.user_id,organization_id=o)
    except PermissionError as ex: raise HTTPException(403,str(ex)) from ex

def ensure_v90gd_schema(e:Engine):
    stmts=[
    '''CREATE TABLE IF NOT EXISTS erp_go_live_execution(go_live_id TEXT PRIMARY KEY,organization_id TEXT NULL,period_key TEXT NOT NULL,release_version TEXT NOT NULL,environment TEXT NOT NULL,business_owner TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'REQUESTED',note TEXT NOT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,approved_at TIMESTAMP NULL,approved_by TEXT NULL,approval_evidence_ref TEXT NULL,approval_note TEXT NULL,closed_at TIMESTAMP NULL,closed_by TEXT NULL,close_evidence_ref TEXT NULL,close_note TEXT NULL,UNIQUE(organization_id,period_key,release_version,environment))''',
    '''CREATE TABLE IF NOT EXISTS erp_go_live_control(control_id TEXT PRIMARY KEY,go_live_id TEXT NOT NULL,control_code TEXT NOT NULL,control_name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',evidence_ref TEXT NULL,note TEXT NOT NULL,reviewed_by TEXT NOT NULL,reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(go_live_id,control_code))''',
    'CREATE INDEX IF NOT EXISTS ix_go_live_scope ON erp_go_live_execution(organization_id,period_key,status,created_at)',
    'CREATE INDEX IF NOT EXISTS ix_go_live_control ON erp_go_live_control(go_live_id,status,control_code)']
    with e.begin() as c:
        for s in stmts:c.execute(text(s))
        for p,n in [(PERM_VIEW,'View go-live execution and final signoff'),(PERM_MANAGE,'Manage go-live execution and final signoff')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':p})

def register_v90gd_routes(app:FastAPI,e:Engine):
    ensure_v90gd_schema(e)
    @app.post('/v90gd/go-live/executions')
    def create(b:GoLiveIn,r:Request):
        u=_u(e,r,PERM_MANAGE); _scope(e,u,b.organization_id); gid=str(uuid4())
        try:
            with e.begin() as c:
                c.execute(text('INSERT INTO erp_go_live_execution(go_live_id,organization_id,period_key,release_version,environment,business_owner,note,created_by) VALUES(:i,:o,:p,:v,:e,:bo,:n,:u)'),{'i':gid,'o':b.organization_id,'p':b.period_key,'v':b.release_version,'e':b.environment,'bo':b.business_owner,'n':b.note,'u':u.user_id})
                for code,name in CONTROLS:c.execute(text('INSERT INTO erp_go_live_control(control_id,go_live_id,control_code,control_name,note,reviewed_by) VALUES(:i,:g,:c,:n,:t,:u)'),{'i':str(uuid4()),'g':gid,'c':code,'n':name,'t':'Pending evidence','u':u.user_id})
        except Exception as ex: raise HTTPException(409,'go-live execution already exists for organization, period, release and environment') from ex
        return {'go_live_id':gid,'status':'REQUESTED','required_controls':[x[0] for x in CONTROLS]}
    @app.post('/v90gd/go-live/executions/{gid}/controls/{code}')
    def control(gid:str,code:str,b:CheckIn,r:Request):
        u=_u(e,r,PERM_MANAGE); code=code.upper()
        if not any(x[0]==code for x in CONTROLS): raise HTTPException(422,'unknown go-live control')
        if b.status in ('PASS','WAIVED') and not b.evidence_ref: raise HTTPException(422,'evidence_ref required for PASS or WAIVED')
        with e.begin() as c:
            row=c.execute(text('SELECT organization_id,status FROM erp_go_live_execution WHERE go_live_id=:i'),{'i':gid}).mappings().first()
            if not row: raise HTTPException(404,'go-live execution not found')
            _scope(e,u,row['organization_id'])
            if row['status'] in ('APPROVED','CLOSED'): raise HTTPException(409,'go-live execution is already approved or closed')
            c.execute(text('UPDATE erp_go_live_control SET status=:s,evidence_ref=:e,note=:n,reviewed_by=:u,reviewed_at=CURRENT_TIMESTAMP WHERE go_live_id=:g AND control_code=:c'),{'s':b.status,'e':b.evidence_ref,'n':b.note,'u':u.user_id,'g':gid,'c':code})
        return {'go_live_id':gid,'control_code':code,'status':b.status}
    @app.get('/v90gd/go-live/executions/{gid}/readiness')
    def readiness(gid:str,r:Request):
        _u(e,r,PERM_VIEW)
        with e.connect() as c:
            g=c.execute(text('SELECT * FROM erp_go_live_execution WHERE go_live_id=:i'),{'i':gid}).mappings().first()
            if not g: raise HTTPException(404,'go-live execution not found')
            rows=c.execute(text('SELECT control_code,status,evidence_ref,note,reviewed_by,reviewed_at FROM erp_go_live_control WHERE go_live_id=:i ORDER BY control_code'),{'i':gid}).mappings().all()
            o,p,v=g['organization_id'],g['period_key'],g['release_version']
            gc=c.execute(text("SELECT COUNT(*) FROM erp_production_release_certification WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND period_key=:p AND release_version=:v AND environment='PRODUCTION' AND status='CLOSED'"),{'o':o,'p':p,'v':v}).scalar_one()
            uat=c.execute(text("SELECT COUNT(*) FROM erp_uat_plan WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND period_key=:p AND status='CERTIFIED'"),{'o':o,'p':p}).scalar_one()
        explicit={x['control_code']:dict(x) for x in rows}
        prerequisites={'RELEASE_CERTIFICATION':gc>0,'END_TO_END_UAT':uat>0}
        explicit_ready=all(explicit.get(x[0],{}).get('status') in ('PASS','WAIVED') for x in CONTROLS)
        return {'go_live':dict(g),'ready_for_go_live':all(prerequisites.values()) and explicit_ready,'prerequisites':prerequisites,'explicit_controls':explicit,'required_controls':len(CONTROLS),'note':'This records controlled go-live evidence and decisions; it does not claim that production deployment was executed by this application.'}
    @app.post('/v90gd/go-live/executions/{gid}/approve')
    def approve(gid:str,b:EvidenceIn,r:Request):
        u=_u(e,r,PERM_MANAGE); s=readiness(gid,r)
        if not s['ready_for_go_live']: raise HTTPException(409,{'message':'go-live readiness gate failed','summary':s})
        with e.begin() as c:c.execute(text("UPDATE erp_go_live_execution SET status='APPROVED',approved_at=CURRENT_TIMESTAMP,approved_by=:u,approval_evidence_ref=:e,approval_note=:n WHERE go_live_id=:i"),{'u':u.user_id,'e':b.evidence_ref,'n':b.note,'i':gid})
        return {'go_live_id':gid,'status':'APPROVED'}
    @app.post('/v90gd/go-live/executions/{gid}/close')
    def close(gid:str,b:EvidenceIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.connect() as c:g=c.execute(text('SELECT organization_id,status FROM erp_go_live_execution WHERE go_live_id=:i'),{'i':gid}).mappings().first()
        if not g: raise HTTPException(404,'go-live execution not found')
        _scope(e,u,g['organization_id'])
        if g['status']!='APPROVED': raise HTTPException(409,'go-live must be APPROVED before close')
        with e.begin() as c:c.execute(text("UPDATE erp_go_live_execution SET status='CLOSED',closed_at=CURRENT_TIMESTAMP,closed_by=:u,close_evidence_ref=:e,close_note=:n WHERE go_live_id=:i"),{'u':u.user_id,'e':b.evidence_ref,'n':b.note,'i':gid})
        return {'go_live_id':gid,'status':'CLOSED'}
    @app.get('/ui/go-live-execution')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'go_live_execution.html')
    return {'allowed':True}

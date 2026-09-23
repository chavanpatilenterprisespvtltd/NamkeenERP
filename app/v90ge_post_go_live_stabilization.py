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

PERM_VIEW='release.post_go_live.view'; PERM_MANAGE='release.post_go_live.manage'
CONTROLS=(('POST_GO_LIVE_HEALTH','Post-go-live health evidence is PASS'),('CRITICAL_INCIDENTS','No unresolved critical incidents or alerts'),('DEFECT_DISPOSITION','Go-live defects are dispositioned with evidence'),('ROLLBACK_WINDOW_CLOSURE','Rollback window is formally closed'),('OPERATIONS_HANDOVER','Operations/support handover is accepted'),('FINAL_ACCEPTANCE','Final business acceptance is signed'))
class StabilizationIn(BaseModel):
    organization_id:str|None=None; period_key:str=Field(min_length=4,max_length=40); release_version:str=Field(min_length=3,max_length=40); environment:str=Field(pattern='^PRODUCTION$'); stabilization_days:int=Field(default=7,ge=1,le=90); business_owner:str=Field(min_length=1,max_length=200); note:str=Field(min_length=1,max_length=3000)
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

def ensure_v90ge_schema(e:Engine):
    stmts=[
    '''CREATE TABLE IF NOT EXISTS erp_post_go_live_stabilization(stabilization_id TEXT PRIMARY KEY,organization_id TEXT NULL,period_key TEXT NOT NULL,release_version TEXT NOT NULL,environment TEXT NOT NULL,stabilization_days INTEGER NOT NULL DEFAULT 7,business_owner TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',note TEXT NOT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,accepted_at TIMESTAMP NULL,accepted_by TEXT NULL,acceptance_evidence_ref TEXT NULL,acceptance_note TEXT NULL,closed_at TIMESTAMP NULL,closed_by TEXT NULL,close_evidence_ref TEXT NULL,close_note TEXT NULL,UNIQUE(organization_id,period_key,release_version,environment))''',
    '''CREATE TABLE IF NOT EXISTS erp_post_go_live_control(control_id TEXT PRIMARY KEY,stabilization_id TEXT NOT NULL,control_code TEXT NOT NULL,control_name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',evidence_ref TEXT NULL,note TEXT NOT NULL,reviewed_by TEXT NOT NULL,reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(stabilization_id,control_code))''',
    'CREATE INDEX IF NOT EXISTS ix_post_go_live_scope ON erp_post_go_live_stabilization(organization_id,period_key,status,created_at)',
    'CREATE INDEX IF NOT EXISTS ix_post_go_live_control ON erp_post_go_live_control(stabilization_id,status,control_code)']
    with e.begin() as c:
        for s in stmts:c.execute(text(s))
        for p,n in [(PERM_VIEW,'View post-go-live stabilization and final acceptance'),(PERM_MANAGE,'Manage post-go-live stabilization and final acceptance')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':p})

def register_v90ge_routes(app:FastAPI,e:Engine):
    ensure_v90ge_schema(e)
    @app.post('/v90ge/post-go-live/stabilizations')
    def create(b:StabilizationIn,r:Request):
        u=_u(e,r,PERM_MANAGE); _scope(e,u,b.organization_id); sid=str(uuid4())
        try:
            with e.begin() as c:
                c.execute(text('INSERT INTO erp_post_go_live_stabilization(stabilization_id,organization_id,period_key,release_version,environment,stabilization_days,business_owner,note,created_by) VALUES(:i,:o,:p,:v,:e,:d,:bo,:n,:u)'),{'i':sid,'o':b.organization_id,'p':b.period_key,'v':b.release_version,'e':b.environment,'d':b.stabilization_days,'bo':b.business_owner,'n':b.note,'u':u.user_id})
                for code,name in CONTROLS:c.execute(text('INSERT INTO erp_post_go_live_control(control_id,stabilization_id,control_code,control_name,note,reviewed_by) VALUES(:i,:s,:c,:n,:t,:u)'),{'i':str(uuid4()),'s':sid,'c':code,'n':name,'t':'Pending stabilization evidence','u':u.user_id})
        except Exception as ex: raise HTTPException(409,'post-go-live stabilization already exists for organization, period, release and environment') from ex
        return {'stabilization_id':sid,'status':'OPEN','required_controls':[x[0] for x in CONTROLS]}
    @app.post('/v90ge/post-go-live/stabilizations/{sid}/controls/{code}')
    def control(sid:str,code:str,b:CheckIn,r:Request):
        u=_u(e,r,PERM_MANAGE); code=code.upper()
        if not any(x[0]==code for x in CONTROLS): raise HTTPException(422,'unknown stabilization control')
        if b.status in ('PASS','WAIVED') and not b.evidence_ref: raise HTTPException(422,'evidence_ref required for PASS or WAIVED')
        with e.begin() as c:
            row=c.execute(text('SELECT organization_id,status FROM erp_post_go_live_stabilization WHERE stabilization_id=:i'),{'i':sid}).mappings().first()
            if not row: raise HTTPException(404,'stabilization record not found')
            _scope(e,u,row['organization_id'])
            if row['status']=='CLOSED': raise HTTPException(409,'stabilization is already closed')
            c.execute(text('UPDATE erp_post_go_live_control SET status=:s,evidence_ref=:e,note=:n,reviewed_by=:u,reviewed_at=CURRENT_TIMESTAMP WHERE stabilization_id=:g AND control_code=:c'),{'s':b.status,'e':b.evidence_ref,'n':b.note,'u':u.user_id,'g':sid,'c':code})
        return {'stabilization_id':sid,'control_code':code,'status':b.status}
    @app.get('/v90ge/post-go-live/stabilizations/{sid}/readiness')
    def readiness(sid:str,r:Request):
        u=_u(e,r,PERM_VIEW)
        with e.connect() as c:
            g=c.execute(text('SELECT * FROM erp_post_go_live_stabilization WHERE stabilization_id=:i'),{'i':sid}).mappings().first()
            if not g: raise HTTPException(404,'stabilization record not found')
            _scope(e,u,g['organization_id'])
            rows=c.execute(text('SELECT control_code,status,evidence_ref,note,reviewed_by,reviewed_at FROM erp_post_go_live_control WHERE stabilization_id=:i ORDER BY control_code'),{'i':sid}).mappings().all()
            o,p,v=g['organization_id'],g['period_key'],g['release_version']
            gd=c.execute(text("SELECT COUNT(*) FROM erp_go_live_execution WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND period_key=:p AND release_version=:v AND environment='PRODUCTION' AND status='CLOSED'"),{'o':o,'p':p,'v':v}).scalar_one()
            critical=c.execute(text("SELECT COUNT(*) FROM erp_ops_alert WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND status='OPEN' AND severity='CRITICAL'"),{'o':o}).scalar_one()
            incidents=c.execute(text("SELECT COUNT(*) FROM erp_ops_incident WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND severity='CRITICAL' AND status NOT IN ('RESOLVED','CLOSED')"),{'o':o}).scalar_one()
            bad_health=c.execute(text("SELECT COUNT(*) FROM erp_ops_health_check WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND result NOT IN ('PASS','WAIVED')"),{'o':o}).scalar_one()
        explicit={x['control_code']:dict(x) for x in rows}
        prerequisites={'GO_LIVE_CLOSED':gd>0,'OPERATIONAL_HEALTH':bad_health==0,'NO_CRITICAL_INCIDENTS':critical==0 and incidents==0}
        explicit_ready=all(explicit.get(x[0],{}).get('status') in ('PASS','WAIVED') for x in CONTROLS)
        return {'stabilization':dict(g),'ready_for_acceptance':all(prerequisites.values()) and explicit_ready,'prerequisites':prerequisites,'explicit_controls':explicit,'required_controls':len(CONTROLS),'note':'This records post-go-live stabilization and acceptance evidence; it does not claim that production monitoring or deployment occurred outside the application.'}
    @app.post('/v90ge/post-go-live/stabilizations/{sid}/accept')
    def accept(sid:str,b:EvidenceIn,r:Request):
        u=_u(e,r,PERM_MANAGE); s=readiness(sid,r)
        if not s['ready_for_acceptance']: raise HTTPException(409,{'message':'post-go-live acceptance gate failed','summary':s})
        with e.begin() as c:c.execute(text("UPDATE erp_post_go_live_stabilization SET status='ACCEPTED',accepted_at=CURRENT_TIMESTAMP,accepted_by=:u,acceptance_evidence_ref=:e,acceptance_note=:n WHERE stabilization_id=:i"),{'u':u.user_id,'e':b.evidence_ref,'n':b.note,'i':sid})
        return {'stabilization_id':sid,'status':'ACCEPTED'}
    @app.post('/v90ge/post-go-live/stabilizations/{sid}/close')
    def close(sid:str,b:EvidenceIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.connect() as c:g=c.execute(text('SELECT organization_id,status FROM erp_post_go_live_stabilization WHERE stabilization_id=:i'),{'i':sid}).mappings().first()
        if not g: raise HTTPException(404,'stabilization record not found')
        _scope(e,u,g['organization_id'])
        if g['status']!='ACCEPTED': raise HTTPException(409,'stabilization must be ACCEPTED before close')
        with e.begin() as c:c.execute(text("UPDATE erp_post_go_live_stabilization SET status='CLOSED',closed_at=CURRENT_TIMESTAMP,closed_by=:u,close_evidence_ref=:e,close_note=:n WHERE stabilization_id=:i"),{'u':u.user_id,'e':b.evidence_ref,'n':b.note,'i':sid})
        return {'stabilization_id':sid,'status':'CLOSED'}
    @app.get('/ui/post-go-live-stabilization')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'post_go_live_stabilization.html')
    return {'allowed':True}

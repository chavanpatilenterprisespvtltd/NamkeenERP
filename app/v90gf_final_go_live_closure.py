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

PERM_VIEW='release.go_live_closure.view'; PERM_MANAGE='release.go_live_closure.manage'
CONTROLS=(('POST_GO_LIVE_CLOSED','V90.ge post-go-live stabilization is CLOSED'),('OPEN_CRITICALS','No unresolved critical operational incidents or alerts'),('DEFECT_EXCEPTION_REGISTER','All unresolved defects have disposition and approved exception evidence'),('ROLLBACK_WINDOW_CLOSED','Rollback window is formally closed'),('OPERATIONS_HANDOVER','Operations/support ownership is formally handed over'),('BUSINESS_ACCEPTANCE','Final business acceptance is recorded'))
class ClosureIn(BaseModel):
    organization_id:str|None=None; period_key:str=Field(min_length=4,max_length=40); release_version:str=Field(min_length=3,max_length=40); environment:str=Field(pattern='^PRODUCTION$'); business_owner:str=Field(min_length=1,max_length=200); support_owner:str=Field(min_length=1,max_length=200); note:str=Field(min_length=1,max_length=3000)
class CheckIn(BaseModel):
    status:str=Field(pattern='^(PASS|FAIL|BLOCKED|WAIVED)$'); evidence_ref:str|None=None; note:str=Field(min_length=1,max_length=3000)
class EvidenceIn(BaseModel):
    evidence_ref:str=Field(min_length=1,max_length=500); note:str=Field(min_length=1,max_length=3000)
class DefectIn(BaseModel):
    defect_ref:str=Field(min_length=1,max_length=100); severity:str=Field(pattern='^(LOW|MEDIUM|HIGH|CRITICAL)$'); disposition:str=Field(pattern='^(CLOSED|ACCEPTED_EXCEPTION|DEFERRED)$'); evidence_ref:str=Field(min_length=1,max_length=500); note:str=Field(min_length=1,max_length=3000)

def _u(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def _scope(e,u,o):
    try: assert_security_scope(e,u.user_id,organization_id=o)
    except PermissionError as ex: raise HTTPException(403,str(ex)) from ex

def ensure_v90gf_schema(e:Engine):
    stmts=[
    '''CREATE TABLE IF NOT EXISTS erp_go_live_closure(closure_id TEXT PRIMARY KEY,organization_id TEXT NULL,period_key TEXT NOT NULL,release_version TEXT NOT NULL,environment TEXT NOT NULL,business_owner TEXT NOT NULL,support_owner TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',note TEXT NOT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,accepted_at TIMESTAMP NULL,accepted_by TEXT NULL,acceptance_evidence_ref TEXT NULL,acceptance_note TEXT NULL,closed_at TIMESTAMP NULL,closed_by TEXT NULL,close_evidence_ref TEXT NULL,close_note TEXT NULL,UNIQUE(organization_id,period_key,release_version,environment))''',
    '''CREATE TABLE IF NOT EXISTS erp_go_live_closure_control(control_id TEXT PRIMARY KEY,closure_id TEXT NOT NULL,control_code TEXT NOT NULL,control_name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',evidence_ref TEXT NULL,note TEXT NOT NULL,reviewed_by TEXT NOT NULL,reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(closure_id,control_code))''',
    '''CREATE TABLE IF NOT EXISTS erp_go_live_closure_defect(defect_id TEXT PRIMARY KEY,closure_id TEXT NOT NULL,defect_ref TEXT NOT NULL,severity TEXT NOT NULL,disposition TEXT NOT NULL,evidence_ref TEXT NOT NULL,note TEXT NOT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(closure_id,defect_ref))''',
    'CREATE INDEX IF NOT EXISTS ix_go_live_closure_scope ON erp_go_live_closure(organization_id,period_key,status,created_at)',
    'CREATE INDEX IF NOT EXISTS ix_go_live_closure_control ON erp_go_live_closure_control(closure_id,status,control_code)',
    'CREATE INDEX IF NOT EXISTS ix_go_live_closure_defect ON erp_go_live_closure_defect(closure_id,severity,disposition)']
    with e.begin() as c:
        for s in stmts:c.execute(text(s))
        for p,n in [(PERM_VIEW,'View final go-live closure and operational handover'),(PERM_MANAGE,'Manage final go-live closure and operational handover')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':p})

def register_v90gf_routes(app:FastAPI,e:Engine):
    ensure_v90gf_schema(e)
    @app.post('/v90gf/go-live-closures')
    def create(b:ClosureIn,r:Request):
        u=_u(e,r,PERM_MANAGE); _scope(e,u,b.organization_id); cid=str(uuid4())
        try:
            with e.begin() as c:
                c.execute(text('INSERT INTO erp_go_live_closure(closure_id,organization_id,period_key,release_version,environment,business_owner,support_owner,note,created_by) VALUES(:i,:o,:p,:v,:e,:bo,:so,:n,:u)'),{'i':cid,'o':b.organization_id,'p':b.period_key,'v':b.release_version,'e':b.environment,'bo':b.business_owner,'so':b.support_owner,'n':b.note,'u':u.user_id})
                for code,name in CONTROLS:c.execute(text('INSERT INTO erp_go_live_closure_control(control_id,closure_id,control_code,control_name,note,reviewed_by) VALUES(:i,:g,:c,:n,:t,:u)'),{'i':str(uuid4()),'g':cid,'c':code,'n':name,'t':'Pending closure evidence','u':u.user_id})
        except Exception as ex: raise HTTPException(409,'go-live closure already exists for organization, period, release and environment') from ex
        return {'closure_id':cid,'status':'OPEN','required_controls':[x[0] for x in CONTROLS]}
    @app.post('/v90gf/go-live-closures/{cid}/defects')
    def defect(cid:str,b:DefectIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.connect() as c:g=c.execute(text('SELECT organization_id,status FROM erp_go_live_closure WHERE closure_id=:i'),{'i':cid}).mappings().first()
        if not g: raise HTTPException(404,'go-live closure not found')
        _scope(e,u,g['organization_id'])
        if g['status']=='CLOSED': raise HTTPException(409,'go-live closure is already closed')
        with e.begin() as c:
            try:c.execute(text('INSERT INTO erp_go_live_closure_defect(defect_id,closure_id,defect_ref,severity,disposition,evidence_ref,note,created_by) VALUES(:i,:c,:r,:s,:d,:e,:n,:u)'),{'i':str(uuid4()),'c':cid,'r':b.defect_ref,'s':b.severity,'d':b.disposition,'e':b.evidence_ref,'n':b.note,'u':u.user_id})
            except Exception as ex: raise HTTPException(409,'defect reference already exists for this closure') from ex
        return {'closure_id':cid,'defect_ref':b.defect_ref,'disposition':b.disposition}
    @app.post('/v90gf/go-live-closures/{cid}/controls/{code}')
    def control(cid:str,code:str,b:CheckIn,r:Request):
        u=_u(e,r,PERM_MANAGE); code=code.upper()
        if not any(x[0]==code for x in CONTROLS): raise HTTPException(422,'unknown closure control')
        if b.status in ('PASS','WAIVED') and not b.evidence_ref: raise HTTPException(422,'evidence_ref required for PASS or WAIVED')
        with e.begin() as c:
            row=c.execute(text('SELECT organization_id,status FROM erp_go_live_closure WHERE closure_id=:i'),{'i':cid}).mappings().first()
            if not row: raise HTTPException(404,'go-live closure not found')
            _scope(e,u,row['organization_id'])
            if row['status']=='CLOSED': raise HTTPException(409,'go-live closure is already closed')
            c.execute(text('UPDATE erp_go_live_closure_control SET status=:s,evidence_ref=:e,note=:n,reviewed_by=:u,reviewed_at=CURRENT_TIMESTAMP WHERE closure_id=:g AND control_code=:c'),{'s':b.status,'e':b.evidence_ref,'n':b.note,'u':u.user_id,'g':cid,'c':code})
        return {'closure_id':cid,'control_code':code,'status':b.status}
    @app.get('/v90gf/go-live-closures/{cid}/readiness')
    def readiness(cid:str,r:Request):
        u=_u(e,r,PERM_VIEW)
        with e.connect() as c:
            g=c.execute(text('SELECT * FROM erp_go_live_closure WHERE closure_id=:i'),{'i':cid}).mappings().first()
            if not g: raise HTTPException(404,'go-live closure not found')
            _scope(e,u,g['organization_id'])
            rows=c.execute(text('SELECT control_code,status,evidence_ref,note,reviewed_by,reviewed_at FROM erp_go_live_closure_control WHERE closure_id=:i ORDER BY control_code'),{'i':cid}).mappings().all()
            defects=c.execute(text('SELECT defect_ref,severity,disposition,evidence_ref,note FROM erp_go_live_closure_defect WHERE closure_id=:i ORDER BY severity,defect_ref'),{'i':cid}).mappings().all()
            o,p,v=g['organization_id'],g['period_key'],g['release_version']
            ge=c.execute(text("SELECT COUNT(*) FROM erp_post_go_live_stabilization WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND period_key=:p AND release_version=:v AND environment='PRODUCTION' AND status='CLOSED'"),{'o':o,'p':p,'v':v}).scalar_one()
            critical=c.execute(text("SELECT COUNT(*) FROM erp_ops_alert WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND status='OPEN' AND severity='CRITICAL'"),{'o':o}).scalar_one()
            incidents=c.execute(text("SELECT COUNT(*) FROM erp_ops_incident WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND severity='CRITICAL' AND status NOT IN ('RESOLVED','CLOSED')"),{'o':o}).scalar_one()
        explicit={x['control_code']:dict(x) for x in rows}
        defect_ready=all(x['disposition'] in ('CLOSED','ACCEPTED_EXCEPTION') and x['evidence_ref'] for x in defects)
        prerequisites={'POST_GO_LIVE_CLOSED':ge>0,'NO_CRITICAL_OPERATIONAL_ISSUES':critical==0 and incidents==0,'DEFECT_REGISTER_READY':defect_ready}
        explicit_ready=all(explicit.get(x[0],{}).get('status') in ('PASS','WAIVED') for x in CONTROLS)
        return {'closure':dict(g),'ready_for_final_closure':all(prerequisites.values()) and explicit_ready,'prerequisites':prerequisites,'explicit_controls':explicit,'defects':[dict(x) for x in defects],'required_controls':len(CONTROLS),'note':'This governs final go-live closure and handover evidence; it does not claim external production deployment or monitoring occurred.'}
    @app.post('/v90gf/go-live-closures/{cid}/accept')
    def accept(cid:str,b:EvidenceIn,r:Request):
        u=_u(e,r,PERM_MANAGE); s=readiness(cid,r)
        if not s['ready_for_final_closure']: raise HTTPException(409,{'message':'final go-live acceptance gate failed','summary':s})
        with e.begin() as c:c.execute(text("UPDATE erp_go_live_closure SET status='ACCEPTED',accepted_at=CURRENT_TIMESTAMP,accepted_by=:u,acceptance_evidence_ref=:e,acceptance_note=:n WHERE closure_id=:i"),{'u':u.user_id,'e':b.evidence_ref,'n':b.note,'i':cid})
        return {'closure_id':cid,'status':'ACCEPTED'}
    @app.post('/v90gf/go-live-closures/{cid}/close')
    def close(cid:str,b:EvidenceIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.connect() as c:g=c.execute(text('SELECT organization_id,status FROM erp_go_live_closure WHERE closure_id=:i'),{'i':cid}).mappings().first()
        if not g: raise HTTPException(404,'go-live closure not found')
        _scope(e,u,g['organization_id'])
        if g['status']!='ACCEPTED': raise HTTPException(409,'go-live closure must be ACCEPTED before close')
        with e.begin() as c:c.execute(text("UPDATE erp_go_live_closure SET status='CLOSED',closed_at=CURRENT_TIMESTAMP,closed_by=:u,close_evidence_ref=:e,close_note=:n WHERE closure_id=:i"),{'u':u.user_id,'e':b.evidence_ref,'n':b.note,'i':cid})
        return {'closure_id':cid,'status':'CLOSED'}
    @app.get('/ui/go-live-closure')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'go_live_closure.html')
    return {'allowed':True}

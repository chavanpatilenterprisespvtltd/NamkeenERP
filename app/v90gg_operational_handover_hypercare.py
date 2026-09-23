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

PERM_VIEW='release.hypercare.view'; PERM_MANAGE='release.hypercare.manage'
CONTROLS=(('GO_LIVE_CLOSURE','V90.gf final go-live closure is CLOSED'),('HEALTH_STABILITY','Operational health evidence is PASS/WAIVED'),('CRITICAL_ISSUES','No unresolved critical incidents or alerts'),('HYPERCARE_EVIDENCE','Required hypercare checkpoints have evidence'),('SUPPORT_OWNERSHIP','Support ownership and escalation path are accepted'),('BUSINESS_KPI_ACCEPTANCE','Business KPI acceptance is recorded'))
class HypercareIn(BaseModel):
    organization_id:str|None=None; period_key:str=Field(min_length=4,max_length=40); release_version:str=Field(min_length=3,max_length=40); environment:str=Field(pattern='^PRODUCTION$'); hypercare_days:int=Field(default=14,ge=1,le=90); business_owner:str=Field(min_length=1,max_length=200); support_owner:str=Field(min_length=1,max_length=200); note:str=Field(min_length=1,max_length=3000)
class CheckIn(BaseModel):
    status:str=Field(pattern='^(PASS|FAIL|BLOCKED|WAIVED)$'); evidence_ref:str|None=None; note:str=Field(min_length=1,max_length=3000)
class EvidenceIn(BaseModel): evidence_ref:str=Field(min_length=1,max_length=500); note:str=Field(min_length=1,max_length=3000)
class CheckpointIn(BaseModel): checkpoint_date:str=Field(min_length=10,max_length=10); health_status:str=Field(pattern='^(PASS|FAIL|WAIVED)$'); incident_count:int=Field(default=0,ge=0); open_critical_count:int=Field(default=0,ge=0); kpi_status:str=Field(pattern='^(PASS|FAIL|WAIVED|PENDING)$'); evidence_ref:str=Field(min_length=1,max_length=500); note:str=Field(min_length=1,max_length=3000)


def _u(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def _scope(e,u,o):
    try: assert_security_scope(e,u.user_id,organization_id=o)
    except PermissionError as ex: raise HTTPException(403,str(ex)) from ex

def ensure_v90gg_schema(e:Engine):
    stmts=[
    '''CREATE TABLE IF NOT EXISTS erp_operational_hypercare(hypercare_id TEXT PRIMARY KEY,organization_id TEXT NULL,period_key TEXT NOT NULL,release_version TEXT NOT NULL,environment TEXT NOT NULL,hypercare_days INTEGER NOT NULL DEFAULT 14,business_owner TEXT NOT NULL,support_owner TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',note TEXT NOT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,accepted_at TIMESTAMP NULL,accepted_by TEXT NULL,acceptance_evidence_ref TEXT NULL,acceptance_note TEXT NULL,closed_at TIMESTAMP NULL,closed_by TEXT NULL,close_evidence_ref TEXT NULL,close_note TEXT NULL,UNIQUE(organization_id,period_key,release_version,environment))''',
    '''CREATE TABLE IF NOT EXISTS erp_operational_hypercare_control(control_id TEXT PRIMARY KEY,hypercare_id TEXT NOT NULL,control_code TEXT NOT NULL,control_name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',evidence_ref TEXT NULL,note TEXT NOT NULL,reviewed_by TEXT NOT NULL,reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(hypercare_id,control_code))''',
    '''CREATE TABLE IF NOT EXISTS erp_operational_hypercare_checkpoint(checkpoint_id TEXT PRIMARY KEY,hypercare_id TEXT NOT NULL,checkpoint_date TEXT NOT NULL,health_status TEXT NOT NULL,incident_count INTEGER NOT NULL DEFAULT 0,open_critical_count INTEGER NOT NULL DEFAULT 0,kpi_status TEXT NOT NULL,evidence_ref TEXT NOT NULL,note TEXT NOT NULL,recorded_by TEXT NOT NULL,recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(hypercare_id,checkpoint_date))''',
    'CREATE INDEX IF NOT EXISTS ix_hypercare_scope ON erp_operational_hypercare(organization_id,period_key,status,created_at)',
    'CREATE INDEX IF NOT EXISTS ix_hypercare_control ON erp_operational_hypercare_control(hypercare_id,status,control_code)',
    'CREATE INDEX IF NOT EXISTS ix_hypercare_checkpoint ON erp_operational_hypercare_checkpoint(hypercare_id,checkpoint_date)']
    with e.begin() as c:
        for s in stmts: c.execute(text(s))
        for p,n in [(PERM_VIEW,'View operational handover and hypercare'),(PERM_MANAGE,'Manage operational handover and hypercare')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':p})

def register_v90gg_routes(app:FastAPI,e:Engine):
    ensure_v90gg_schema(e)
    @app.post('/v90gg/hypercare')
    def create(b:HypercareIn,r:Request):
        u=_u(e,r,PERM_MANAGE); _scope(e,u,b.organization_id); hid=str(uuid4())
        try:
            with e.begin() as c:
                c.execute(text('INSERT INTO erp_operational_hypercare(hypercare_id,organization_id,period_key,release_version,environment,hypercare_days,business_owner,support_owner,note,created_by) VALUES(:i,:o,:p,:v,:e,:d,:bo,:so,:n,:u)'),{'i':hid,'o':b.organization_id,'p':b.period_key,'v':b.release_version,'e':b.environment,'d':b.hypercare_days,'bo':b.business_owner,'so':b.support_owner,'n':b.note,'u':u.user_id})
                for code,name in CONTROLS:c.execute(text('INSERT INTO erp_operational_hypercare_control(control_id,hypercare_id,control_code,control_name,note,reviewed_by) VALUES(:i,:h,:c,:n,:t,:u)'),{'i':str(uuid4()),'h':hid,'c':code,'n':name,'t':'Pending evidence','u':u.user_id})
        except Exception as ex: raise HTTPException(409,'hypercare record already exists for organization, period, release and environment') from ex
        return {'hypercare_id':hid,'status':'OPEN','required_controls':[x[0] for x in CONTROLS]}
    @app.post('/v90gg/hypercare/{hid}/controls/{code}')
    def control(hid:str,code:str,b:CheckIn,r:Request):
        u=_u(e,r,PERM_MANAGE); code=code.upper()
        if not any(x[0]==code for x in CONTROLS): raise HTTPException(422,'unknown hypercare control')
        if b.status in ('PASS','WAIVED') and not b.evidence_ref: raise HTTPException(422,'evidence_ref required for PASS or WAIVED')
        with e.begin() as c:
            row=c.execute(text('SELECT organization_id,status FROM erp_operational_hypercare WHERE hypercare_id=:i'),{'i':hid}).mappings().first()
            if not row: raise HTTPException(404,'hypercare record not found')
            _scope(e,u,row['organization_id'])
            if row['status']=='CLOSED': raise HTTPException(409,'hypercare is already closed')
            c.execute(text('UPDATE erp_operational_hypercare_control SET status=:s,evidence_ref=:e,note=:n,reviewed_by=:u,reviewed_at=CURRENT_TIMESTAMP WHERE hypercare_id=:h AND control_code=:c'),{'s':b.status,'e':b.evidence_ref,'n':b.note,'u':u.user_id,'h':hid,'c':code})
        return {'hypercare_id':hid,'control_code':code,'status':b.status}
    @app.post('/v90gg/hypercare/{hid}/checkpoints')
    def checkpoint(hid:str,b:CheckpointIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.begin() as c:
            row=c.execute(text('SELECT organization_id,status FROM erp_operational_hypercare WHERE hypercare_id=:i'),{'i':hid}).mappings().first()
            if not row: raise HTTPException(404,'hypercare record not found')
            _scope(e,u,row['organization_id'])
            if row['status']=='CLOSED': raise HTTPException(409,'hypercare is already closed')
            try:c.execute(text('INSERT INTO erp_operational_hypercare_checkpoint(checkpoint_id,hypercare_id,checkpoint_date,health_status,incident_count,open_critical_count,kpi_status,evidence_ref,note,recorded_by) VALUES(:i,:h,:d,:hs,:ic,:oc,:ks,:e,:n,:u)'),{'i':str(uuid4()),'h':hid,'d':b.checkpoint_date,'hs':b.health_status,'ic':b.incident_count,'oc':b.open_critical_count,'ks':b.kpi_status,'e':b.evidence_ref,'n':b.note,'u':u.user_id})
            except Exception as ex: raise HTTPException(409,'checkpoint date already exists for this hypercare record') from ex
        return {'hypercare_id':hid,'checkpoint_date':b.checkpoint_date,'status':'RECORDED'}
    @app.get('/v90gg/hypercare/{hid}/readiness')
    def readiness(hid:str,r:Request):
        u=_u(e,r,PERM_VIEW)
        with e.connect() as c:
            h=c.execute(text('SELECT * FROM erp_operational_hypercare WHERE hypercare_id=:i'),{'i':hid}).mappings().first()
            if not h: raise HTTPException(404,'hypercare record not found')
            _scope(e,u,h['organization_id']); rows=c.execute(text('SELECT control_code,status,evidence_ref,note,reviewed_by,reviewed_at FROM erp_operational_hypercare_control WHERE hypercare_id=:i ORDER BY control_code'),{'i':hid}).mappings().all(); cps=c.execute(text('SELECT * FROM erp_operational_hypercare_checkpoint WHERE hypercare_id=:i ORDER BY checkpoint_date'),{'i':hid}).mappings().all()
            o,p,v=h['organization_id'],h['period_key'],h['release_version']
            gf=c.execute(text("SELECT COUNT(*) FROM erp_go_live_closure WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND period_key=:p AND release_version=:v AND environment='PRODUCTION' AND status='CLOSED'"),{'o':o,'p':p,'v':v}).scalar_one()
            critical=c.execute(text("SELECT COUNT(*) FROM erp_ops_alert WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND status='OPEN' AND severity='CRITICAL'"),{'o':o}).scalar_one(); incidents=c.execute(text("SELECT COUNT(*) FROM erp_ops_incident WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND severity='CRITICAL' AND status NOT IN ('RESOLVED','CLOSED')"),{'o':o}).scalar_one(); bad_health=c.execute(text("SELECT COUNT(*) FROM erp_ops_health_check WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND result NOT IN ('PASS','WAIVED')"),{'o':o}).scalar_one()
        explicit={x['control_code']:dict(x) for x in rows}; checkpoint_ready=len(cps)>=h['hypercare_days'] and all(x['health_status'] in ('PASS','WAIVED') and x['open_critical_count']==0 and x['kpi_status'] in ('PASS','WAIVED') for x in cps)
        prerequisites={'GO_LIVE_CLOSURE_CLOSED':gf>0,'OPERATIONAL_HEALTH':bad_health==0,'NO_CRITICAL_ISSUES':critical==0 and incidents==0,'HYPERCARE_CHECKPOINTS':checkpoint_ready}
        explicit_ready=all(explicit.get(x[0],{}).get('status') in ('PASS','WAIVED') for x in CONTROLS)
        return {'hypercare':dict(h),'ready_for_closure':all(prerequisites.values()) and explicit_ready,'prerequisites':prerequisites,'explicit_controls':explicit,'checkpoints':[dict(x) for x in cps],'required_controls':len(CONTROLS),'note':'This governs operational handover and hypercare evidence; it does not claim external production monitoring or deployment occurred.'}
    @app.post('/v90gg/hypercare/{hid}/accept')
    def accept(hid:str,b:EvidenceIn,r:Request):
        u=_u(e,r,PERM_MANAGE); s=readiness(hid,r)
        if not s['ready_for_closure']: raise HTTPException(409,{'message':'hypercare closure gate failed','summary':s})
        with e.begin() as c:c.execute(text("UPDATE erp_operational_hypercare SET status='ACCEPTED',accepted_at=CURRENT_TIMESTAMP,accepted_by=:u,acceptance_evidence_ref=:e,acceptance_note=:n WHERE hypercare_id=:i"),{'u':u.user_id,'e':b.evidence_ref,'n':b.note,'i':hid})
        return {'hypercare_id':hid,'status':'ACCEPTED'}
    @app.post('/v90gg/hypercare/{hid}/close')
    def close(hid:str,b:EvidenceIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.connect() as c:g=c.execute(text('SELECT organization_id,status FROM erp_operational_hypercare WHERE hypercare_id=:i'),{'i':hid}).mappings().first()
        if not g: raise HTTPException(404,'hypercare record not found')
        _scope(e,u,g['organization_id'])
        if g['status']!='ACCEPTED': raise HTTPException(409,'hypercare must be ACCEPTED before close')
        with e.begin() as c:c.execute(text("UPDATE erp_operational_hypercare SET status='CLOSED',closed_at=CURRENT_TIMESTAMP,closed_by=:u,close_evidence_ref=:e,close_note=:n WHERE hypercare_id=:i"),{'u':u.user_id,'e':b.evidence_ref,'n':b.note,'i':hid})
        return {'hypercare_id':hid,'status':'CLOSED'}
    @app.get('/ui/operational-handover-hypercare')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'operational_handover_hypercare.html')
    return {'allowed':True}

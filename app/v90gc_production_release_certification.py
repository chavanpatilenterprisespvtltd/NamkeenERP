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

PERM_VIEW='release.production_certification.view'; PERM_MANAGE='release.production_certification.manage'
CONTROLS=(('PERFORMANCE_READINESS','V90.gb production readiness performance gate closed'),('UAT_CERTIFICATION','V90.ft UAT certification exists'),('DEPLOYMENT_READINESS','V90.fv deployment controls and rollback drill ready'),('BACKUP_DR','V90.fw backup, restore and DR readiness'),('OPERATIONAL_HEALTH','V90.fx operational health has no critical incidents'),('BUSINESS_SIGNOFF','Explicit business owner release signoff'))
class CertIn(BaseModel):
    organization_id:str|None=None; period_key:str=Field(min_length=4,max_length=40); release_version:str=Field(min_length=3,max_length=40); environment:str=Field(pattern='^(STAGING|PRODUCTION)$'); business_owner:str=Field(min_length=1,max_length=200); note:str=Field(min_length=1,max_length=3000)
class CheckIn(BaseModel):
    status:str=Field(pattern='^(PASS|FAIL|BLOCKED|WAIVED|OPEN)$'); evidence_ref:str|None=None; note:str=Field(min_length=1,max_length=3000)
class SignoffIn(BaseModel):
    evidence_ref:str=Field(min_length=1,max_length=500); note:str=Field(min_length=1,max_length=3000)

def _u(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def _scope(e,u,o):
    try: assert_security_scope(e,u.user_id,organization_id=o)
    except PermissionError as ex: raise HTTPException(403,str(ex)) from ex

def _ev(s,ref):
    if s in ('PASS','WAIVED') and not ref: raise HTTPException(422,'evidence_ref required for PASS or WAIVED')

def ensure_v90gc_schema(e:Engine):
    stmts=[
    '''CREATE TABLE IF NOT EXISTS erp_production_release_certification(certification_id TEXT PRIMARY KEY,organization_id TEXT NULL,period_key TEXT NOT NULL,release_version TEXT NOT NULL,environment TEXT NOT NULL,business_owner TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'REQUESTED',note TEXT NOT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,certified_at TIMESTAMP NULL,certified_by TEXT NULL,certification_evidence_ref TEXT NULL,certification_note TEXT NULL,closed_at TIMESTAMP NULL,closed_by TEXT NULL,close_evidence_ref TEXT NULL,close_note TEXT NULL,UNIQUE(organization_id,period_key,release_version,environment))''',
    '''CREATE TABLE IF NOT EXISTS erp_production_release_control(control_id TEXT PRIMARY KEY,certification_id TEXT NOT NULL,control_code TEXT NOT NULL,control_name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',evidence_ref TEXT NULL,note TEXT NOT NULL,reviewed_by TEXT NOT NULL,reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(certification_id,control_code))''',
    'CREATE INDEX IF NOT EXISTS ix_release_cert_scope ON erp_production_release_certification(organization_id,period_key,status,created_at)',
    'CREATE INDEX IF NOT EXISTS ix_release_control ON erp_production_release_control(certification_id,status,control_code)']
    with e.begin() as c:
        for s in stmts:c.execute(text(s))
        for p,n in [(PERM_VIEW,'View production release certification'),(PERM_MANAGE,'Manage production release certification')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':p})

def register_v90gc_routes(app:FastAPI,e:Engine):
    ensure_v90gc_schema(e)
    @app.post('/v90gc/production-release/certifications')
    def create(b:CertIn,r:Request):
        u=_u(e,r,PERM_MANAGE); _scope(e,u,b.organization_id); cid=str(uuid4())
        try:
            with e.begin() as c:
                c.execute(text('INSERT INTO erp_production_release_certification(certification_id,organization_id,period_key,release_version,environment,business_owner,note,created_by) VALUES(:i,:o,:p,:v,:e,:bo,:n,:u)'),{'i':cid,'o':b.organization_id,'p':b.period_key,'v':b.release_version,'e':b.environment,'bo':b.business_owner,'n':b.note,'u':u.user_id})
                for code,name in CONTROLS:c.execute(text('INSERT INTO erp_production_release_control(control_id,certification_id,control_code,control_name,note,reviewed_by) VALUES(:i,:c,:x,:n,:t,:u)'),{'i':str(uuid4()),'c':cid,'x':code,'n':name,'t':'Pending evidence/signoff','u':u.user_id})
        except Exception as ex: raise HTTPException(409,'production release certification already exists for organization, period, release and environment') from ex
        return {'certification_id':cid,'status':'REQUESTED','required_controls':[x[0] for x in CONTROLS]}
    @app.post('/v90gc/production-release/certifications/{cid}/controls/{code}')
    def control(cid:str,code:str,b:CheckIn,r:Request):
        u=_u(e,r,PERM_MANAGE); code=code.upper(); _ev(b.status,b.evidence_ref)
        if not any(x[0]==code for x in CONTROLS): raise HTTPException(422,'unknown release certification control')
        with e.begin() as c:
            row=c.execute(text('SELECT organization_id,status FROM erp_production_release_certification WHERE certification_id=:i'),{'i':cid}).mappings().first()
            if not row: raise HTTPException(404,'production release certification not found')
            _scope(e,u,row['organization_id'])
            if row['status'] in ('CLOSED','CERTIFIED'): raise HTTPException(409,'certification is already certified or closed')
            c.execute(text('UPDATE erp_production_release_control SET status=:s,evidence_ref=:e,note=:n,reviewed_by=:u,reviewed_at=CURRENT_TIMESTAMP WHERE certification_id=:c AND control_code=:x'),{'s':b.status,'e':b.evidence_ref,'n':b.note,'u':u.user_id,'c':cid,'x':code})
        return {'certification_id':cid,'control_code':code,'status':b.status}
    @app.post('/v90gc/production-release/certifications/{cid}/business-signoff')
    def signoff(cid:str,b:SignoffIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.begin() as c:
            row=c.execute(text('SELECT organization_id,status FROM erp_production_release_certification WHERE certification_id=:i'),{'i':cid}).mappings().first()
            if not row: raise HTTPException(404,'production release certification not found')
            _scope(e,u,row['organization_id'])
            c.execute(text("UPDATE erp_production_release_control SET status='PASS',evidence_ref=:e,note=:n,reviewed_by=:u,reviewed_at=CURRENT_TIMESTAMP WHERE certification_id=:c AND control_code='BUSINESS_SIGNOFF'"),{'e':b.evidence_ref,'n':b.note,'u':u.user_id,'c':cid})
        return {'certification_id':cid,'business_signoff':'PASS'}
    @app.get('/v90gc/production-release/certifications/{cid}/readiness')
    def readiness(cid:str,r:Request):
        _u(e,r,PERM_VIEW)
        with e.connect() as c:
            cert=c.execute(text('SELECT * FROM erp_production_release_certification WHERE certification_id=:i'),{'i':cid}).mappings().first()
            if not cert: raise HTTPException(404,'production release certification not found')
            rows=c.execute(text('SELECT control_code,status,evidence_ref,note,reviewed_by,reviewed_at FROM erp_production_release_control WHERE certification_id=:i ORDER BY control_code'),{'i':cid}).mappings().all()
            o,p,v,env=cert['organization_id'],cert['period_key'],cert['release_version'],cert['environment']
            perf=c.execute(text("SELECT COUNT(*) FROM erp_perf_production_readiness_gate WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND period_key=:p AND release_version=:v AND environment=:e AND status='CLOSED'"),{'o':o,'p':p,'v':v,'e':env}).scalar_one()
            uat=c.execute(text("SELECT COUNT(*) FROM erp_uat_plan WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND period_key=:p AND status='CERTIFIED'"),{'o':o,'p':p}).scalar_one()
            deps=c.execute(text("SELECT deployment_id FROM erp_deployment_cutover WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND release_version=:v AND environment=:e ORDER BY requested_at DESC"),{'o':o,'v':v,'e':env}).fetchall(); dep_ok=False
            for d in deps:
                total=c.execute(text('SELECT COUNT(*) FROM erp_deployment_control WHERE deployment_id=:d'),{'d':d[0]}).scalar_one(); good=c.execute(text("SELECT COUNT(*) FROM erp_deployment_control WHERE deployment_id=:d AND status IN ('PASS','WAIVED')"),{'d':d[0]}).scalar_one(); drill=c.execute(text("SELECT COUNT(*) FROM erp_rollback_drill WHERE deployment_id=:d AND result='PASS'"),{'d':d[0]}).scalar_one()
                if total>0 and good==total and drill>0: dep_ok=True; break
            back=c.execute(text("SELECT COUNT(*) FROM erp_backup_execution WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND status='SUCCESS'"),{'o':o}).scalar_one(); rest=c.execute(text("SELECT COUNT(*) FROM erp_restore_validation rv JOIN erp_backup_execution b ON b.backup_id=rv.backup_id WHERE ((:o IS NULL AND b.organization_id IS NULL) OR b.organization_id=:o) AND rv.result='PASS'"),{'o':o}).scalar_one(); dr=c.execute(text("SELECT COUNT(*) FROM erp_dr_recovery_drill WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND result='PASS'"),{'o':o}).scalar_one()
            health=c.execute(text("SELECT COUNT(*) FROM erp_ops_health_check WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND result NOT IN ('PASS','WAIVED')"),{'o':o}).scalar_one(); critical=c.execute(text("SELECT COUNT(*) FROM erp_ops_alert WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND severity='CRITICAL' AND status NOT IN ('RESOLVED','CLOSED')"),{'o':o}).scalar_one(); incidents=c.execute(text("SELECT COUNT(*) FROM erp_ops_incident WHERE ((:o IS NULL AND organization_id IS NULL) OR organization_id=:o) AND status NOT IN ('RESOLVED','CLOSED') AND severity='CRITICAL'"),{'o':o}).scalar_one()
        derived={'PERFORMANCE_READINESS':perf>0,'UAT_CERTIFICATION':uat>0,'DEPLOYMENT_READINESS':dep_ok,'BACKUP_DR':back>0 and rest>0 and dr>0,'OPERATIONAL_HEALTH':health==0 and critical==0 and incidents==0}
        cm={x['control_code']:dict(x) for x in rows}; explicit=all(cm.get(x[0],{}).get('status') in ('PASS','WAIVED') for x in CONTROLS); ready=all(derived.values()) and explicit
        return {'certification':dict(cert),'ready_for_certification':ready,'derived_controls':derived,'explicit_controls':cm,'required_controls':len(CONTROLS)}
    @app.post('/v90gc/production-release/certifications/{cid}/certify')
    def certify(cid:str,b:SignoffIn,r:Request):
        u=_u(e,r,PERM_MANAGE); s=readiness(cid,r)
        if not s['ready_for_certification']: raise HTTPException(409,{'message':'production release certification gate failed','summary':s})
        with e.begin() as c:c.execute(text("UPDATE erp_production_release_certification SET status='CERTIFIED',certified_at=CURRENT_TIMESTAMP,certified_by=:u,certification_evidence_ref=:e,certification_note=:n WHERE certification_id=:i"),{'u':u.user_id,'e':b.evidence_ref,'n':b.note,'i':cid})
        return {'certification_id':cid,'status':'CERTIFIED'}
    @app.post('/v90gc/production-release/certifications/{cid}/close')
    def close(cid:str,b:SignoffIn,r:Request):
        u=_u(e,r,PERM_MANAGE); s=readiness(cid,r)
        if s['certification']['status']!='CERTIFIED': raise HTTPException(409,'release must be CERTIFIED before close')
        with e.begin() as c:c.execute(text("UPDATE erp_production_release_certification SET status='CLOSED',closed_at=CURRENT_TIMESTAMP,closed_by=:u,close_evidence_ref=:e,close_note=:n WHERE certification_id=:i"),{'u':u.user_id,'e':b.evidence_ref,'n':b.note,'i':cid})
        return {'certification_id':cid,'status':'CLOSED'}
    @app.get('/ui/production-release-certification')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'production_release_certification.html')
    return {'allowed':True}

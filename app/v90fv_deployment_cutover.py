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

PERM_VIEW='deployment.cutover.view'; PERM_MANAGE='deployment.cutover.manage'
class DeployIn(BaseModel):
    organization_id:str|None=None; environment:str=Field(pattern='^(STAGING|PRODUCTION)$'); release_version:str=Field(min_length=3,max_length=40); migration_target:int=Field(ge=61); change_note:str=Field(min_length=1,max_length=3000)
class EvidenceIn(BaseModel):
    status:str=Field(pattern='^(PASS|FAIL|BLOCKED|WAIVED)$'); evidence_ref:str|None=None; note:str=Field(min_length=1,max_length=3000)
class CloseIn(BaseModel):
    signoff_note:str=Field(min_length=1,max_length=3000); evidence_ref:str=Field(min_length=1,max_length=500)

CONTROLS=(('PRE_APPROVAL','Pre-deployment approval'),('ARTIFACT','Release artifact/checksum verified'),('MIGRATION','Migration execution evidence'),('HEALTH','Post-deployment health verification'),('SMOKE','Post-deployment smoke verification'),('UAT','UAT/certification verification'),('ROLLBACK','Rollback readiness/drill evidence'),('CUTOVER','Business cutover confirmation'))

def _u(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def ensure_v90fv_schema(e:Engine):
    stmts=[
    '''CREATE TABLE IF NOT EXISTS erp_deployment_cutover(deployment_id TEXT PRIMARY KEY,organization_id TEXT NULL,environment TEXT NOT NULL,release_version TEXT NOT NULL,migration_target INTEGER NOT NULL,change_note TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'REQUESTED',requested_by TEXT NOT NULL,requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,started_at TIMESTAMP NULL,closed_at TIMESTAMP NULL,closed_by TEXT NULL,signoff_note TEXT NULL,signoff_evidence_ref TEXT NULL)''',
    '''CREATE TABLE IF NOT EXISTS erp_deployment_control(control_id TEXT PRIMARY KEY,deployment_id TEXT NOT NULL,control_code TEXT NOT NULL,control_name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',evidence_ref TEXT NULL,note TEXT NOT NULL,reviewed_by TEXT NOT NULL,reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(deployment_id,control_code))''',
    '''CREATE TABLE IF NOT EXISTS erp_rollback_drill(drill_id TEXT PRIMARY KEY,deployment_id TEXT NOT NULL,scenario TEXT NOT NULL,result TEXT NOT NULL,evidence_ref TEXT NULL,notes TEXT NOT NULL,performed_by TEXT NOT NULL,performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    'CREATE INDEX IF NOT EXISTS ix_deployment_cutover_scope ON erp_deployment_cutover(organization_id,environment,status,requested_at)',
    'CREATE INDEX IF NOT EXISTS ix_deployment_control ON erp_deployment_control(deployment_id,status)',
    ]
    with e.begin() as c:
        for s in stmts:c.execute(text(s))
        for p,n in [(PERM_VIEW,'View deployment and cutover controls'),(PERM_MANAGE,'Manage deployment and cutover controls')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':p})

def register_v90fv_routes(app:FastAPI,e:Engine):
    ensure_v90fv_schema(e)
    @app.post('/v90fv/deployments')
    def create(b:DeployIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        try: assert_security_scope(e,u.user_id,organization_id=b.organization_id)
        except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
        did=str(uuid4())
        with e.begin() as c:c.execute(text('INSERT INTO erp_deployment_cutover(deployment_id,organization_id,environment,release_version,migration_target,change_note,requested_by) VALUES(:i,:o,:e,:v,:m,:n,:u)'),{'i':did,'o':b.organization_id,'e':b.environment,'v':b.release_version,'m':b.migration_target,'n':b.change_note,'u':u.user_id})
        return {'deployment_id':did,'status':'REQUESTED','control_catalog':[x[0] for x in CONTROLS]}
    @app.get('/v90fv/deployments')
    def listing(r:Request,organization_id:str|None=None,status:str|None=None):
        _u(e,r,PERM_VIEW); q='SELECT * FROM erp_deployment_cutover WHERE 1=1'; p={}
        if organization_id:q+=' AND organization_id=:o';p['o']=organization_id
        if status:q+=' AND status=:s';p['s']=status.upper()
        with e.connect() as c: rows=[dict(x) for x in c.execute(text(q+' ORDER BY requested_at DESC'),p).mappings().all()]
        return {'deployments':rows}
    @app.post('/v90fv/deployments/{did}/start')
    def start(did:str,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.begin() as c:
            row=c.execute(text('SELECT * FROM erp_deployment_cutover WHERE deployment_id=:i'),{'i':did}).mappings().first()
            if not row: raise HTTPException(404,'deployment not found')
            if row['status']!='REQUESTED': raise HTTPException(409,'deployment must be REQUESTED')
            c.execute(text("UPDATE erp_deployment_cutover SET status='EXECUTING',started_at=CURRENT_TIMESTAMP WHERE deployment_id=:i"),{'i':did})
        return {'deployment_id':did,'status':'EXECUTING'}
    @app.post('/v90fv/deployments/{did}/controls/{code}')
    def control(did:str,code:str,b:EvidenceIn,r:Request):
        u=_u(e,r,PERM_MANAGE); code=code.upper(); cat=next((x for x in CONTROLS if x[0]==code),None)
        if not cat: raise HTTPException(422,'unknown deployment control')
        if b.status in ('PASS','WAIVED') and not b.evidence_ref: raise HTTPException(422,'evidence_ref required for PASS or WAIVED')
        with e.begin() as c:
            row=c.execute(text('SELECT organization_id,status FROM erp_deployment_cutover WHERE deployment_id=:i'),{'i':did}).mappings().first()
            if not row: raise HTTPException(404,'deployment not found')
            if row['status']!='EXECUTING': raise HTTPException(409,'deployment must be EXECUTING')
            try: assert_security_scope(e,u.user_id,organization_id=row['organization_id'])
            except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
            cid=str(uuid4()); c.execute(text('''INSERT INTO erp_deployment_control(control_id,deployment_id,control_code,control_name,status,evidence_ref,note,reviewed_by) VALUES(:i,:d,:c,:n,:s,:e,:x,:u) ON CONFLICT(deployment_id,control_code) DO UPDATE SET status=:s,evidence_ref=:e,note=:x,reviewed_by=:u,reviewed_at=CURRENT_TIMESTAMP'''),{'i':cid,'d':did,'c':code,'n':cat[1],'s':b.status,'e':b.evidence_ref,'x':b.note,'u':u.user_id})
        return {'deployment_id':did,'control_code':code,'status':b.status}
    @app.post('/v90fv/deployments/{did}/rollback-drill')
    def drill(did:str,b:EvidenceIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.begin() as c:
            row=c.execute(text('SELECT status FROM erp_deployment_cutover WHERE deployment_id=:i'),{'i':did}).mappings().first()
            if not row: raise HTTPException(404,'deployment not found')
            if b.status not in ('PASS','FAIL','BLOCKED'): raise HTTPException(422,'rollback drill must be PASS, FAIL or BLOCKED')
            c.execute(text('INSERT INTO erp_rollback_drill(drill_id,deployment_id,scenario,result,evidence_ref,notes,performed_by) VALUES(:i,:d,:s,:r,:e,:n,:u)'),{'i':str(uuid4()),'d':did,'s':'Controlled rollback readiness drill','r':b.status,'e':b.evidence_ref,'n':b.note,'u':u.user_id})
        return {'deployment_id':did,'rollback_drill':b.status}
    @app.get('/v90fv/deployments/{did}/readiness')
    def readiness(did:str,r:Request):
        _u(e,r,PERM_VIEW)
        with e.connect() as c:
            dep=c.execute(text('SELECT * FROM erp_deployment_cutover WHERE deployment_id=:i'),{'i':did}).mappings().first()
            if not dep: raise HTTPException(404,'deployment not found')
            controls=c.execute(text('SELECT control_code,status,evidence_ref,note,reviewed_by,reviewed_at FROM erp_deployment_control WHERE deployment_id=:d'),{'d':did}).mappings().all()
            drills=c.execute(text('SELECT result,COUNT(*) n FROM erp_rollback_drill WHERE deployment_id=:d GROUP BY result'),{'d':did}).mappings().all()
        cm={x['control_code']:dict(x) for x in controls}; dm={x['result']:int(x['n']) for x in drills}
        ready=len(cm)==len(CONTROLS) and all(cm[x[0]]['status'] in ('PASS','WAIVED') for x in CONTROLS) and dm.get('PASS',0)>0
        return {'deployment':dict(dep),'ready_for_cutover':ready,'controls':cm,'rollback_drills':dm,'required_controls':len(CONTROLS)}
    @app.post('/v90fv/deployments/{did}/close')
    def close(did:str,b:CloseIn,r:Request):
        u=_u(e,r,PERM_MANAGE); s=readiness(did,r)
        if not s['ready_for_cutover']: raise HTTPException(409,{'message':'cutover readiness gate failed','summary':s})
        with e.begin() as c:c.execute(text("UPDATE erp_deployment_cutover SET status='CLOSED',closed_at=CURRENT_TIMESTAMP,closed_by=:u,signoff_note=:n,signoff_evidence_ref=:e WHERE deployment_id=:i"),{'u':u.user_id,'n':b.signoff_note,'e':b.evidence_ref,'i':did})
        return {'deployment_id':did,'status':'CLOSED','closed_by':u.user_id}
    @app.get('/ui/deployment-cutover')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'deployment_cutover.html')
    return {'allowed':True}

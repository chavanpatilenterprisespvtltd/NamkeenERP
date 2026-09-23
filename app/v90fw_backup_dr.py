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

PERM_VIEW='backup.dr.view'; PERM_MANAGE='backup.dr.manage'
BACKUP_STATUSES=('SUCCESS','FAILED','PARTIAL')
RESTORE_RESULTS=('PASS','FAIL','BLOCKED','WAIVED')
DR_RESULTS=('PASS','FAIL','BLOCKED','WAIVED')

class BackupIn(BaseModel):
    organization_id:str|None=None; environment:str=Field(pattern='^(STAGING|PRODUCTION)$'); backup_type:str=Field(pattern='^(FULL|INCREMENTAL|SNAPSHOT)$'); artifact_ref:str=Field(min_length=1,max_length=500); size_bytes:int|None=Field(default=None,ge=0); started_at:str|None=None; completed_at:str|None=None; status:str=Field(pattern='^(SUCCESS|FAILED|PARTIAL)$'); evidence_ref:str|None=None; notes:str=Field(min_length=1,max_length=3000)
class RestoreIn(BaseModel):
    backup_id:str; environment:str=Field(pattern='^(STAGING|DR)$'); result:str=Field(pattern='^(PASS|FAIL|BLOCKED|WAIVED)$'); restored_schema:int|None=Field(default=None,ge=0); validation_evidence_ref:str|None=None; notes:str=Field(min_length=1,max_length=3000)
class DrillIn(BaseModel):
    scenario:str=Field(min_length=2,max_length=3000); result:str=Field(pattern='^(PASS|FAIL|BLOCKED|WAIVED)$'); rpo_minutes:int|None=Field(default=None,ge=0); rto_minutes:int|None=Field(default=None,ge=0); evidence_ref:str|None=None; notes:str=Field(min_length=1,max_length=3000)
class CloseIn(BaseModel):
    signoff_note:str=Field(min_length=1,max_length=3000); evidence_ref:str=Field(min_length=1,max_length=500)

def _u(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def ensure_v90fw_schema(e:Engine):
    stmts=[
    '''CREATE TABLE IF NOT EXISTS erp_backup_execution(backup_id TEXT PRIMARY KEY,organization_id TEXT NULL,environment TEXT NOT NULL,backup_type TEXT NOT NULL,artifact_ref TEXT NOT NULL,size_bytes BIGINT NULL,started_at TIMESTAMP NULL,completed_at TIMESTAMP NULL,status TEXT NOT NULL,evidence_ref TEXT NULL,notes TEXT NOT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS erp_restore_validation(restore_id TEXT PRIMARY KEY,backup_id TEXT NOT NULL,environment TEXT NOT NULL,result TEXT NOT NULL,restored_schema INTEGER NULL,validation_evidence_ref TEXT NULL,notes TEXT NOT NULL,validated_by TEXT NOT NULL,validated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS erp_dr_recovery_drill(drill_id TEXT PRIMARY KEY,organization_id TEXT NULL,scenario TEXT NOT NULL,result TEXT NOT NULL,rpo_minutes INTEGER NULL,rto_minutes INTEGER NULL,evidence_ref TEXT NULL,notes TEXT NOT NULL,performed_by TEXT NOT NULL,performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS erp_dr_close(close_id TEXT PRIMARY KEY,organization_id TEXT NULL,period_key TEXT NOT NULL,signoff_note TEXT NOT NULL,evidence_ref TEXT NOT NULL,closed_by TEXT NOT NULL,closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    'CREATE INDEX IF NOT EXISTS ix_backup_execution_scope ON erp_backup_execution(organization_id,environment,status,created_at)',
    'CREATE INDEX IF NOT EXISTS ix_restore_validation_backup ON erp_restore_validation(backup_id,result,validated_at)',
    'CREATE INDEX IF NOT EXISTS ix_dr_drill_scope ON erp_dr_recovery_drill(organization_id,result,performed_at)']
    with e.begin() as c:
        for s in stmts:c.execute(text(s))
        for p,n in [(PERM_VIEW,'View backup, restore and disaster recovery controls'),(PERM_MANAGE,'Manage backup, restore and disaster recovery controls')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':p})

def register_v90fw_routes(app:FastAPI,e:Engine):
    ensure_v90fw_schema(e)
    @app.post('/v90fw/backups')
    def backup(b:BackupIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        try: assert_security_scope(e,u.user_id,organization_id=b.organization_id)
        except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
        bid=str(uuid4())
        with e.begin() as c:c.execute(text('INSERT INTO erp_backup_execution(backup_id,organization_id,environment,backup_type,artifact_ref,size_bytes,started_at,completed_at,status,evidence_ref,notes,created_by) VALUES(:i,:o,:e,:t,:a,:z,:s,:c,:st,:ev,:n,:u)'),{'i':bid,'o':b.organization_id,'e':b.environment,'t':b.backup_type,'a':b.artifact_ref,'z':b.size_bytes,'s':b.started_at,'c':b.completed_at,'st':b.status,'ev':b.evidence_ref,'n':b.notes,'u':u.user_id})
        return {'backup_id':bid,'status':b.status}
    @app.get('/v90fw/backups')
    def backups(r:Request,organization_id:str|None=None,environment:str|None=None):
        _u(e,r,PERM_VIEW); q='SELECT * FROM erp_backup_execution WHERE 1=1'; p={}
        if organization_id:q+=' AND organization_id=:o';p['o']=organization_id
        if environment:q+=' AND environment=:e';p['e']=environment.upper()
        with e.connect() as c: rows=[dict(x) for x in c.execute(text(q+' ORDER BY created_at DESC'),p).mappings().all()]
        return {'backups':rows}
    @app.post('/v90fw/restores')
    def restore(b:RestoreIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        if b.result in ('PASS','WAIVED') and not b.validation_evidence_ref: raise HTTPException(422,'validation_evidence_ref required for PASS or WAIVED')
        with e.begin() as c:
            row=c.execute(text('SELECT backup_id,organization_id FROM erp_backup_execution WHERE backup_id=:i'),{'i':b.backup_id}).mappings().first()
            if not row: raise HTTPException(404,'backup not found')
            try: assert_security_scope(e,u.user_id,organization_id=row['organization_id'])
            except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
            rid=str(uuid4()); c.execute(text('INSERT INTO erp_restore_validation(restore_id,backup_id,environment,result,restored_schema,validation_evidence_ref,notes,validated_by) VALUES(:i,:b,:e,:r,:s,:v,:n,:u)'),{'i':rid,'b':b.backup_id,'e':b.environment,'r':b.result,'s':b.restored_schema,'v':b.validation_evidence_ref,'n':b.notes,'u':u.user_id})
        return {'restore_id':rid,'result':b.result}
    @app.get('/v90fw/restores')
    def restores(r:Request,backup_id:str|None=None):
        _u(e,r,PERM_VIEW); q='SELECT * FROM erp_restore_validation WHERE 1=1'; p={}
        if backup_id:q+=' AND backup_id=:b';p['b']=backup_id
        with e.connect() as c: rows=[dict(x) for x in c.execute(text(q+' ORDER BY validated_at DESC'),p).mappings().all()]
        return {'restores':rows}
    @app.post('/v90fw/dr-drills')
    def drill(b:DrillIn,r:Request):
        u=_u(e,r,PERM_MANAGE); did=str(uuid4())
        with e.begin() as c:c.execute(text('INSERT INTO erp_dr_recovery_drill(drill_id,scenario,result,rpo_minutes,rto_minutes,evidence_ref,notes,performed_by) VALUES(:i,:s,:r,:p,:t,:e,:n,:u)'),{'i':did,'s':b.scenario,'r':b.result,'p':b.rpo_minutes,'t':b.rto_minutes,'e':b.evidence_ref,'n':b.notes,'u':u.user_id})
        return {'drill_id':did,'result':b.result}
    @app.get('/v90fw/recovery-readiness')
    def readiness(r:Request,organization_id:str|None=None):
        _u(e,r,PERM_VIEW)
        with e.connect() as c:
            if organization_id:
                b=c.execute(text("SELECT COUNT(*) n FROM erp_backup_execution WHERE organization_id=:o AND status='SUCCESS'"),{'o':organization_id}).scalar_one()
                rv=c.execute(text("SELECT COUNT(*) n FROM erp_restore_validation rv JOIN erp_backup_execution b ON b.backup_id=rv.backup_id WHERE b.organization_id=:o AND rv.result='PASS'"),{'o':organization_id}).scalar_one()
                d=c.execute(text("SELECT COUNT(*) n FROM erp_dr_recovery_drill WHERE organization_id=:o AND result='PASS'"),{'o':organization_id}).scalar_one()
            else:
                b=c.execute(text("SELECT COUNT(*) n FROM erp_backup_execution WHERE status='SUCCESS'"),{}).scalar_one()
                rv=c.execute(text("SELECT COUNT(*) n FROM erp_restore_validation WHERE result='PASS'"),{}).scalar_one()
                d=c.execute(text("SELECT COUNT(*) n FROM erp_dr_recovery_drill WHERE result='PASS'"),{}).scalar_one()
        ready=(b>0 and rv>0 and d>0)
        return {'ready_for_dr':ready,'successful_backups':int(b),'passed_restores':int(rv),'passed_drills':int(d),'requirements':['successful backup','passed isolated restore validation','passed DR recovery drill']}
    @app.post('/v90fw/{period_key}/close')
    def close(period_key:str,b:CloseIn,r:Request,organization_id:str|None=None):
        u=_u(e,r,PERM_MANAGE); s=readiness(r,organization_id)
        if not s['ready_for_dr']: raise HTTPException(409,{'message':'DR readiness gate failed','summary':s})
        with e.begin() as c:c.execute(text('INSERT INTO erp_dr_close(close_id,organization_id,period_key,signoff_note,evidence_ref,closed_by) VALUES(:i,:o,:p,:n,:e,:u)'),{'i':str(uuid4()),'o':organization_id,'p':period_key,'n':b.signoff_note,'e':b.evidence_ref,'u':u.user_id})
        return {'period_key':period_key,'status':'CLOSED','closed_by':u.user_id}
    @app.get('/ui/backup-dr')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'backup_dr.html')
    return {'allowed':True}

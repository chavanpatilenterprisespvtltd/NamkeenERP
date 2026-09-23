from __future__ import annotations
from pathlib import Path
from uuid import uuid4
from datetime import date
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine
from .auth import authenticate
from .identity import permissions_for_user
from .v90fn_security_rbac_scope_hardening import assert_security_scope
from .v90fq_governance_certification import CRITICAL_ACTIONS

PERM_VIEW='governance.remediation_uat.view'; PERM_MANAGE='governance.remediation_uat.manage'
class RemediationIn(BaseModel):
    gap_id:str=Field(min_length=1,max_length=80); owner_user_id:str=Field(min_length=1,max_length=120)
    due_date:date|None=None; remediation_plan:str=Field(min_length=1,max_length=3000)
class EvidenceIn(BaseModel): evidence_ref:str=Field(min_length=1,max_length=500); note:str=Field(min_length=1,max_length=2000)
class UATIn(BaseModel):
    critical_action_code:str=Field(min_length=2,max_length=128); test_case:str=Field(min_length=1,max_length=2000)
    result:str=Field(pattern='^(PASS|FAIL|BLOCKED|WAIVED)$'); evidence_ref:str|None=Field(default=None,max_length=500); reviewer_note:str=Field(min_length=1,max_length=2000)

def _u(e:Engine,r:Request,p:str):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def ensure_v90fs_schema(e:Engine):
    stmts=[
    '''CREATE TABLE IF NOT EXISTS erp_governance_remediation(remediation_id TEXT PRIMARY KEY,gap_id TEXT NOT NULL,organization_id TEXT NULL,module_name TEXT NOT NULL,action_code TEXT NOT NULL,owner_user_id TEXT NOT NULL,due_date DATE NULL,remediation_plan TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'REQUESTED',requested_by TEXT NOT NULL,requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,started_at TIMESTAMP NULL,completed_at TIMESTAMP NULL,blocked_reason TEXT NULL,cancel_reason TEXT NULL,completion_note TEXT NULL,completion_evidence_ref TEXT NULL)''',
    '''CREATE TABLE IF NOT EXISTS erp_governance_remediation_evidence(evidence_id TEXT PRIMARY KEY,remediation_id TEXT NOT NULL,evidence_ref TEXT NOT NULL,note TEXT NOT NULL,added_by TEXT NOT NULL,added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS erp_governance_uat_case(uat_id TEXT PRIMARY KEY,remediation_id TEXT NULL,organization_id TEXT NULL,module_name TEXT NOT NULL,action_code TEXT NOT NULL,test_case TEXT NOT NULL,result TEXT NOT NULL,evidence_ref TEXT NULL,reviewer_note TEXT NOT NULL,reviewed_by TEXT NOT NULL,reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE IF NOT EXISTS erp_governance_remediation_close(close_id TEXT PRIMARY KEY,organization_id TEXT NULL,period_key TEXT NOT NULL,closed_by TEXT NOT NULL,closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,force BOOLEAN NOT NULL DEFAULT FALSE,note TEXT NOT NULL,UNIQUE(organization_id,period_key))''',
    'CREATE INDEX IF NOT EXISTS ix_governance_remediation_scope ON erp_governance_remediation(organization_id,status,owner_user_id,due_date)',
    'CREATE INDEX IF NOT EXISTS ix_governance_uat_scope ON erp_governance_uat_case(organization_id,result,module_name,action_code)']
    with e.begin() as c:
        for s in stmts:c.execute(text(s))
        for p,n in [(PERM_VIEW,'View governance remediation and UAT'),(PERM_MANAGE,'Manage governance remediation and UAT')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':p})

def register_v90fs_routes(app:FastAPI,e:Engine):
    ensure_v90fs_schema(e)
    @app.post('/v90fs/governance/remediation')
    def create(b:RemediationIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.begin() as c:
            gap=c.execute(text("SELECT * FROM erp_governance_coverage_gap WHERE gap_id=:id"),{'id':b.gap_id}).mappings().first()
            if not gap: raise HTTPException(404,'coverage gap not found')
            try: assert_security_scope(e,u.user_id,organization_id=gap['organization_id'])
            except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
            active=c.execute(text("SELECT remediation_id FROM erp_governance_remediation WHERE gap_id=:g AND status NOT IN ('COMPLETED','CANCELLED')"),{'g':b.gap_id}).first()
            if active: raise HTTPException(409,'active remediation already exists')
            rid=str(uuid4()); c.execute(text('''INSERT INTO erp_governance_remediation(remediation_id,gap_id,organization_id,module_name,action_code,owner_user_id,due_date,remediation_plan,requested_by) VALUES(:id,:g,:o,:m,:a,:owner,:d,:p,:u)'''),{'id':rid,'g':b.gap_id,'o':gap['organization_id'],'m':gap['module_name'],'a':gap['action_code'],'owner':b.owner_user_id,'d':b.due_date,'p':b.remediation_plan,'u':u.user_id})
        return {'remediation_id':rid,'status':'REQUESTED'}
    @app.get('/v90fs/governance/remediation')
    def listing(r:Request,organization_id:str|None=None,status:str|None=None):
        _u(e,r,PERM_VIEW); q='SELECT * FROM erp_governance_remediation WHERE 1=1'; p={}
        if organization_id:q+=' AND organization_id=:o';p['o']=organization_id
        if status:q+=' AND status=:s';p['s']=status.upper()
        with e.connect() as c: rows=[dict(x) for x in c.execute(text(q+' ORDER BY due_date NULLS LAST,requested_at DESC'),p).mappings().all()]
        return {'remediation':rows}
    def transition(rid,r,status,reason=None):
        u=_u(e,r,PERM_MANAGE)
        with e.begin() as c:
            row=c.execute(text('SELECT * FROM erp_governance_remediation WHERE remediation_id=:id'),{'id':rid}).mappings().first()
            if not row: raise HTTPException(404,'remediation not found')
            try: assert_security_scope(e,u.user_id,organization_id=row['organization_id'])
            except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
            allowed={'IN_PROGRESS':['REQUESTED','BLOCKED'],'COMPLETED':['IN_PROGRESS'],'BLOCKED':['REQUESTED','IN_PROGRESS'],'CANCELLED':['REQUESTED','IN_PROGRESS','BLOCKED']}
            if row['status'] not in allowed.get(status,[]): raise HTTPException(409,f"cannot transition {row['status']} to {status}")
            if status in ('BLOCKED','CANCELLED') and not reason: raise HTTPException(422,'reason required')
            if status=='COMPLETED' and not row['completion_evidence_ref']: raise HTTPException(409,'completion evidence is required')
            sets={'status':status}
            if status=='IN_PROGRESS': q='UPDATE erp_governance_remediation SET status=:s,started_at=CURRENT_TIMESTAMP WHERE remediation_id=:id'
            elif status=='COMPLETED': q='UPDATE erp_governance_remediation SET status=:s,completed_at=CURRENT_TIMESTAMP,completion_note=:r WHERE remediation_id=:id';sets['r']=reason or 'completed'
            elif status=='BLOCKED': q='UPDATE erp_governance_remediation SET status=:s,blocked_reason=:r WHERE remediation_id=:id';sets['r']=reason
            else: q='UPDATE erp_governance_remediation SET status=:s,cancel_reason=:r WHERE remediation_id=:id';sets['r']=reason
            sets['s']=status;sets['id']=rid;c.execute(text(q),sets)
        return {'remediation_id':rid,'status':status}
    @app.post('/v90fs/governance/remediation/{rid}/start')
    def start(rid:str,r:Request): return transition(rid,r,'IN_PROGRESS')
    @app.post('/v90fs/governance/remediation/{rid}/block')
    def block(rid:str,b:EvidenceIn,r:Request): return transition(rid,r,'BLOCKED',b.note)
    @app.post('/v90fs/governance/remediation/{rid}/cancel')
    def cancel(rid:str,b:EvidenceIn,r:Request): return transition(rid,r,'CANCELLED',b.note)
    @app.post('/v90fs/governance/remediation/{rid}/complete')
    def complete(rid:str,b:EvidenceIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.begin() as c:
            row=c.execute(text('SELECT * FROM erp_governance_remediation WHERE remediation_id=:id'),{'id':rid}).mappings().first()
            if not row: raise HTTPException(404,'remediation not found')
            if row['status']!='IN_PROGRESS': raise HTTPException(409,'remediation must be IN_PROGRESS')
            c.execute(text('UPDATE erp_governance_remediation SET completion_evidence_ref=:e,completion_note=:n WHERE remediation_id=:id'),{'e':b.evidence_ref,'n':b.note,'id':rid})
        return transition(rid,r,'COMPLETED',b.note)
    @app.post('/v90fs/governance/remediation/{rid}/evidence')
    def evidence(rid:str,b:EvidenceIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.begin() as c:
            row=c.execute(text('SELECT organization_id FROM erp_governance_remediation WHERE remediation_id=:id'),{'id':rid}).mappings().first()
            if not row: raise HTTPException(404,'remediation not found')
            c.execute(text('INSERT INTO erp_governance_remediation_evidence(evidence_id,remediation_id,evidence_ref,note,added_by) VALUES(:id,:r,:e,:n,:u)'),{'id':str(uuid4()),'r':rid,'e':b.evidence_ref,'n':b.note,'u':u.user_id})
        return {'status':'RECORDED'}
    @app.post('/v90fs/governance/remediation/{rid}/uat')
    def uat(rid:str,b:UATIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.begin() as c:
            row=c.execute(text('SELECT * FROM erp_governance_remediation WHERE remediation_id=:id'),{'id':rid}).mappings().first()
            if not row: raise HTTPException(404,'remediation not found')
            if b.result in ('PASS','WAIVED') and not b.evidence_ref: raise HTTPException(422,'evidence_ref required for PASS or WAIVED')
            if b.critical_action_code.upper()!=row['action_code'].upper(): raise HTTPException(422,'UAT action code must match remediation action')
            uid=str(uuid4()); c.execute(text('''INSERT INTO erp_governance_uat_case(uat_id,remediation_id,organization_id,module_name,action_code,test_case,result,evidence_ref,reviewer_note,reviewed_by) VALUES(:id,:r,:o,:m,:a,:t,:x,:e,:n,:u)'''),{'id':uid,'r':rid,'o':row['organization_id'],'m':row['module_name'],'a':row['action_code'],'t':b.test_case,'x':b.result,'e':b.evidence_ref,'n':b.reviewer_note,'u':u.user_id})
        return {'uat_id':uid,'result':b.result}
    @app.get('/v90fs/governance/uat')
    def uat_list(r:Request,organization_id:str|None=None,result:str|None=None):
        _u(e,r,PERM_VIEW); q='SELECT * FROM erp_governance_uat_case WHERE 1=1';p={}
        if organization_id:q+=' AND organization_id=:o';p['o']=organization_id
        if result:q+=' AND result=:x';p['x']=result.upper()
        with e.connect() as c: rows=[dict(x) for x in c.execute(text(q+' ORDER BY reviewed_at DESC'),p).mappings().all()]
        return {'uat':rows}
    @app.get('/v90fs/governance/certification-readiness')
    def readiness(r:Request,organization_id:str|None=None):
        _u(e,r,PERM_VIEW);p={'o':organization_id}
        with e.connect() as c:
            open_gaps=c.execute(text("SELECT COUNT(*) FROM erp_governance_coverage_gap WHERE organization_id IS NOT DISTINCT FROM :o AND status='OPEN'"),p).scalar() or 0
            active=c.execute(text("SELECT COUNT(*) FROM erp_governance_remediation WHERE organization_id IS NOT DISTINCT FROM :o AND status IN ('REQUESTED','IN_PROGRESS','BLOCKED')"),p).scalar() or 0
            failed=c.execute(text("SELECT COUNT(*) FROM erp_governance_uat_case WHERE organization_id IS NOT DISTINCT FROM :o AND result='FAIL'"),p).scalar() or 0
            passed=c.execute(text("SELECT COUNT(*) FROM erp_governance_uat_case WHERE organization_id IS NOT DISTINCT FROM :o AND result='PASS'"),p).scalar() or 0
            total=c.execute(text("SELECT COUNT(*) FROM erp_governance_uat_case WHERE organization_id IS NOT DISTINCT FROM :o"),p).scalar() or 0
        ready=(open_gaps==0 and active==0 and failed==0 and total>0 and passed==total)
        return {'organization_id':organization_id,'ready':ready,'open_gaps':open_gaps,'active_remediations':active,'failed_uat':failed,'uat_total':total,'uat_passed':passed}
    @app.post('/v90fs/governance/{period_key}/close')
    def close(period_key:str,r:Request,organization_id:str|None=None,force:bool=False,note:str=''):
        u=_u(e,r,PERM_MANAGE)
        if not note: raise HTTPException(422,'note required')
        ready=readiness(r,organization_id)
        if not ready['ready'] and not force: raise HTTPException(409,{'message':'governance remediation/UAT readiness gate failed','readiness':ready})
        with e.begin() as c:
            cid=str(uuid4()); c.execute(text('INSERT INTO erp_governance_remediation_close(close_id,organization_id,period_key,closed_by,force,note) VALUES(:id,:o,:p,:u,:f,:n) ON CONFLICT(organization_id,period_key) DO NOTHING'),{'id':cid,'o':organization_id,'p':period_key,'u':u.user_id,'f':force,'n':note})
        return {'period_key':period_key,'closed':True,'force':force,'readiness':ready}
    @app.get('/ui/governance-remediation-uat')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'governance_remediation_uat.html')
    return {'allowed':True}

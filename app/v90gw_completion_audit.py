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

PERM_VIEW='erp.completion_audit.view'; PERM_MANAGE='erp.completion_audit.manage'
RESULTS=('PASS','FAIL','BLOCKED','WAIVED')
CONTROLS=(
 ('SECURITY','Authentication, authorization, entity/location scope and security hardening are evidenced'),
 ('AUDIT','Critical transaction changes and approvals have auditable evidence'),
 ('BACKUP_DR','Verified backup, restore validation and DR drill are evidenced'),
 ('PERFORMANCE','Performance/scalability readiness is certified'),
 ('DEPLOYMENT','Deployment/cutover and rollback controls are certified'),
 ('UAT','Business UAT is certified for the release'),
 ('OPERATIONS','Operational health, alerts and critical incidents are clear'),
 ('MOBILE','Mobile integration exceptions are reconciled and resolved'),
 ('DATA_INTEGRITY','Migration history/checksums and transaction continuity are verified'),
 ('BUSINESS_SIGNOFF','Final business owner sign-off is evidenced'),
)
class CheckIn(BaseModel):
    control_code:str=Field(min_length=2,max_length=80); result:str=Field(pattern='^(PASS|FAIL|BLOCKED|WAIVED)$'); evidence_ref:str|None=None; notes:str=Field(min_length=1,max_length=3000)
class SignoffIn(BaseModel):
    note:str=Field(min_length=1,max_length=3000); evidence_ref:str=Field(min_length=1,max_length=500)

def _u(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def ensure_v90gw_schema(e:Engine):
    stmts=[
    '''CREATE TABLE IF NOT EXISTS erp_completion_audit(audit_id TEXT PRIMARY KEY,organization_id TEXT NULL,period_key TEXT NOT NULL,release_version TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,closed_by TEXT NULL,closed_at TIMESTAMP NULL,close_note TEXT NULL,close_evidence_ref TEXT NULL)''',
    '''CREATE TABLE IF NOT EXISTS erp_completion_audit_control(control_id TEXT PRIMARY KEY,audit_id TEXT NOT NULL,control_code TEXT NOT NULL,control_name TEXT NOT NULL,result TEXT NOT NULL DEFAULT 'BLOCKED',evidence_ref TEXT NULL,notes TEXT NOT NULL,reviewed_by TEXT NOT NULL,reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(audit_id,control_code))''',
    'CREATE INDEX IF NOT EXISTS ix_completion_audit_scope ON erp_completion_audit(organization_id,period_key,status,created_at)',
    'CREATE INDEX IF NOT EXISTS ix_completion_control ON erp_completion_audit_control(audit_id,result,control_code)']
    with e.begin() as c:
        for s in stmts:c.execute(text(s))
        for p,n in [(PERM_VIEW,'View ERP completion audit'),(PERM_MANAGE,'Manage ERP completion audit and final signoff')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':p})

def register_v90gw_routes(app:FastAPI,e:Engine):
    ensure_v90gw_schema(e)
    @app.post('/v90gw/completion-audits')
    def create(body:dict,r:Request):
        u=_u(e,r,PERM_MANAGE); o=str(body.get('organization_id') or '') or None; p=str(body.get('period_key') or '').strip(); v=str(body.get('release_version') or 'v90.gw').strip()
        if not p: raise HTTPException(422,'period_key required')
        try: assert_security_scope(e,u.user_id,organization_id=o)
        except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
        aid=str(uuid4())
        with e.begin() as c:
            c.execute(text('INSERT INTO erp_completion_audit(audit_id,organization_id,period_key,release_version,created_by) VALUES(:i,:o,:p,:v,:u)'),{'i':aid,'o':o,'p':p,'v':v,'u':u.user_id})
            for code,name in CONTROLS:c.execute(text('INSERT INTO erp_completion_audit_control(control_id,audit_id,control_code,control_name,notes,reviewed_by) VALUES(:i,:a,:c,:n,:n2,:u)'),{'i':str(uuid4()),'a':aid,'c':code,'n':name,'n2':'Pending evidence/signoff','u':u.user_id})
        return {'audit_id':aid,'status':'OPEN','required_controls':[x[0] for x in CONTROLS]}
    @app.get('/v90gw/completion-audits/{audit_id}')
    def get(audit_id:str,r:Request):
        _u(e,r,PERM_VIEW)
        with e.connect() as c:
            a=c.execute(text('SELECT * FROM erp_completion_audit WHERE audit_id=:i'),{'i':audit_id}).mappings().first()
            if not a: raise HTTPException(404,'completion audit not found')
            rows=c.execute(text('SELECT * FROM erp_completion_audit_control WHERE audit_id=:i ORDER BY control_code'),{'i':audit_id}).mappings().all()
        return {'audit':dict(a),'controls':[dict(x) for x in rows],'ready_for_closure':all(x['result'] in ('PASS','WAIVED') for x in rows)}
    @app.post('/v90gw/completion-audits/{audit_id}/controls/{code}')
    def control(audit_id:str,code:str,b:CheckIn,r:Request):
        u=_u(e,r,PERM_MANAGE); code=code.upper()
        if code not in [x[0] for x in CONTROLS]: raise HTTPException(422,'unknown completion control')
        if b.result in ('PASS','WAIVED') and not b.evidence_ref: raise HTTPException(422,'evidence_ref required for PASS or WAIVED')
        with e.begin() as c:
            row=c.execute(text('SELECT organization_id,status FROM erp_completion_audit WHERE audit_id=:i'),{'i':audit_id}).mappings().first()
            if not row: raise HTTPException(404,'completion audit not found')
            if row['status']=='CLOSED': raise HTTPException(409,'completion audit is closed')
            try: assert_security_scope(e,u.user_id,organization_id=row['organization_id'])
            except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
            c.execute(text('UPDATE erp_completion_audit_control SET result=:r,evidence_ref=:e,notes=:n,reviewed_by=:u,reviewed_at=CURRENT_TIMESTAMP WHERE audit_id=:a AND control_code=:c'),{'r':b.result,'e':b.evidence_ref,'n':b.notes,'u':u.user_id,'a':audit_id,'c':code})
        return {'audit_id':audit_id,'control_code':code,'result':b.result}
    @app.get('/v90gw/completion-audits')
    def list_audits(r:Request,organization_id:str|None=None,status:str|None=None):
        _u(e,r,PERM_VIEW); q='SELECT * FROM erp_completion_audit WHERE organization_id IS NOT DISTINCT FROM :o'; p={'o':organization_id}
        if status:q+=' AND status=:s';p['s']=status.upper()
        with e.connect() as c: rows=[dict(x) for x in c.execute(text(q+' ORDER BY created_at DESC'),p).mappings().all()]
        return {'audits':rows}
    @app.post('/v90gw/completion-audits/{audit_id}/close')
    def close(audit_id:str,b:SignoffIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.connect() as c:
            row=c.execute(text('SELECT organization_id,status FROM erp_completion_audit WHERE audit_id=:i'),{'i':audit_id}).mappings().first()
            if not row: raise HTTPException(404,'completion audit not found')
            if row['status']=='CLOSED': raise HTTPException(409,'completion audit already closed')
            n=c.execute(text('SELECT COUNT(*) FROM erp_completion_audit_control WHERE audit_id=:i'),{'i':audit_id}).scalar_one(); good=c.execute(text("SELECT COUNT(*) FROM erp_completion_audit_control WHERE audit_id=:i AND result IN ('PASS','WAIVED')"),{'i':audit_id}).scalar_one()
            if n==0 or good!=n: raise HTTPException(409,{'message':'completion audit gate failed','controls_total':int(n),'controls_pass_or_waived':int(good)})
            try: assert_security_scope(e,u.user_id,organization_id=row['organization_id'])
            except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
        with e.begin() as c:c.execute(text("UPDATE erp_completion_audit SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP,close_note=:n,close_evidence_ref=:ev WHERE audit_id=:i"),{'u':u.user_id,'n':b.note,'ev':b.evidence_ref,'i':audit_id})
        return {'audit_id':audit_id,'status':'CLOSED','erp_completion_certified':True}
    @app.get('/ui/completion-audit')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'completion-audit.html')
    return {'allowed':True}

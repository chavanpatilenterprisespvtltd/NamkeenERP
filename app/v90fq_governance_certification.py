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

PERM_VIEW='governance.certification.view'; PERM_MANAGE='governance.certification.manage'
CRITICAL_ACTIONS=[('PROCUREMENT','PROCUREMENT.WRITE'),('RECEIVING_QC','RECEIVING_QC.WRITE'),('INVENTORY','INVENTORY.WRITE'),('PRODUCTION','PRODUCTION.WRITE'),('PROCESS_QC','PROCESS_QC.WRITE'),('BATCH_PACKING','BATCH_PACKING.WRITE'),('FG_DISPATCH','FG_DISPATCH.WRITE'),('SALES','SALES.WRITE'),('RETURNS','RETURNS.WRITE'),('RETURN_DISPOSITION','RETURN_DISPOSITION.WRITE'),('ACCOUNTING','ACCOUNTING.WRITE'),('INTERCOMPANY','INTERCOMPANY.WRITE')]

class CertificationIn(BaseModel):
    module_name:str=Field(min_length=2,max_length=80); action_code:str=Field(min_length=2,max_length=128)
    organization_id:str|None=None; certification_status:str=Field(default='CERTIFIED',pattern='^(CERTIFIED|EXCEPTION|NOT_APPLICABLE)$')
    control_note:str=Field(min_length=1,max_length=2000); evidence_ref:str|None=Field(default=None,max_length=500)
class ResolveIn(BaseModel):
    resolution_note:str=Field(min_length=1,max_length=2000); evidence_ref:str=Field(min_length=1,max_length=500)


def _u(e:Engine,r:Request,p:str):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def ensure_v90fq_schema(e:Engine):
    stmts=[
    '''CREATE TABLE IF NOT EXISTS erp_governance_critical_action_certification(certification_id TEXT PRIMARY KEY,organization_id TEXT NULL,module_name TEXT NOT NULL,action_code TEXT NOT NULL,certification_status TEXT NOT NULL,control_note TEXT NOT NULL,evidence_ref TEXT NULL,certified_by TEXT NOT NULL,certified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,active BOOLEAN NOT NULL DEFAULT TRUE,UNIQUE(organization_id,module_name,action_code))''',
    '''CREATE TABLE IF NOT EXISTS erp_governance_certification_exception(exception_id TEXT PRIMARY KEY,organization_id TEXT NULL,module_name TEXT NOT NULL,action_code TEXT NOT NULL,reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',opened_by TEXT NOT NULL,opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,resolved_by TEXT NULL,resolved_at TIMESTAMP NULL,resolution_note TEXT NULL,evidence_ref TEXT NULL)''',
    '''CREATE TABLE IF NOT EXISTS erp_governance_certification_close(close_id TEXT PRIMARY KEY,organization_id TEXT NULL,closed_by TEXT NOT NULL,closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,force BOOLEAN NOT NULL DEFAULT FALSE,note TEXT NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS ix_critical_cert_scope ON erp_governance_critical_action_certification(organization_id,module_name,action_code,active)',
    'CREATE INDEX IF NOT EXISTS ix_cert_exception_scope ON erp_governance_certification_exception(organization_id,status,module_name,action_code)']
    with e.begin() as c:
        for s in stmts: c.execute(text(s))
        for pid,pn in [(PERM_VIEW,'View ERP critical-action certification'),(PERM_MANAGE,'Manage ERP critical-action certification')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':pid,'n':pn})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':pid})

def register_v90fq_routes(app:FastAPI,e:Engine):
    ensure_v90fq_schema(e)
    @app.post('/v90fq/governance/certifications')
    def certify(b:CertificationIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        try: assert_security_scope(e,u.user_id,organization_id=b.organization_id)
        except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
        cid=str(uuid4())
        with e.begin() as c:
            c.execute(text('''INSERT INTO erp_governance_critical_action_certification(certification_id,organization_id,module_name,action_code,certification_status,control_note,evidence_ref,certified_by) VALUES(:id,:o,:m,:a,:s,:n,:r,:u) ON CONFLICT(organization_id,module_name,action_code) DO UPDATE SET certification_status=:s,control_note=:n,evidence_ref=:r,certified_by=:u,certified_at=CURRENT_TIMESTAMP,active=TRUE'''),{'id':cid,'o':b.organization_id,'m':b.module_name.upper(),'a':b.action_code.upper(),'s':b.certification_status,'n':b.control_note,'r':b.evidence_ref,'u':u.user_id})
        return {'certification_id':cid,'status':b.certification_status}
    @app.post('/v90fq/governance/certifications/bootstrap')
    def bootstrap(r:Request,organization_id:str|None=None):
        u=_u(e,r,PERM_MANAGE)
        try: assert_security_scope(e,u.user_id,organization_id=organization_id)
        except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
        made=0
        with e.begin() as c:
            for m,a in CRITICAL_ACTIONS:
                exists=c.execute(text('SELECT 1 FROM erp_governance_critical_action_certification WHERE organization_id IS NOT DISTINCT FROM :o AND module_name=:m AND action_code=:a AND active=TRUE'),{'o':organization_id,'m':m,'a':a}).first()
                if not exists:
                    c.execute(text("INSERT INTO erp_governance_critical_action_certification(certification_id,organization_id,module_name,action_code,certification_status,control_note,certified_by) VALUES(:id,:o,:m,:a,'EXCEPTION','Awaiting critical-action control certification',:u)"),{'id':str(uuid4()),'o':organization_id,'m':m,'a':a,'u':u.user_id}); made+=1
        return {'created':made,'critical_actions':len(CRITICAL_ACTIONS)}
    @app.get('/v90fq/governance/certifications')
    def list_cert(r:Request,organization_id:str|None=None,status:str|None=None):
        _u(e,r,PERM_VIEW); q='SELECT * FROM erp_governance_critical_action_certification WHERE active=TRUE';p={}
        if organization_id:q+=' AND organization_id=:o';p['o']=organization_id
        if status:q+=' AND certification_status=:s';p['s']=status.upper()
        with e.connect() as c: rows=[dict(x) for x in c.execute(text(q+' ORDER BY module_name,action_code'),p).mappings().all()]
        return {'certifications':rows}
    @app.get('/v90fq/governance/coverage')
    def coverage(r:Request,organization_id:str|None=None):
        _u(e,r,PERM_VIEW);p={'o':organization_id}
        with e.connect() as c:
            base='SELECT COUNT(*) FROM erp_governance_critical_action_certification WHERE active=TRUE AND organization_id IS NOT DISTINCT FROM :o'
            certified=c.execute(text(base+" AND certification_status='CERTIFIED'"),p).scalar() or 0
            exceptions=c.execute(text(base+" AND certification_status='EXCEPTION'"),p).scalar() or 0
            openx=c.execute(text("SELECT COUNT(*) FROM erp_governance_certification_exception WHERE status='OPEN' AND organization_id IS NOT DISTINCT FROM :o"),p).scalar() or 0
        return {'total_critical_actions':len(CRITICAL_ACTIONS),'certified':certified,'exceptions':exceptions,'open_exceptions':openx,'coverage_percent':round(certified*100/len(CRITICAL_ACTIONS),2)}
    @app.post('/v90fq/governance/exceptions')
    def open_exception(b:CertificationIn,r:Request):
        u=_u(e,r,PERM_MANAGE); eid=str(uuid4())
        try: assert_security_scope(e,u.user_id,organization_id=b.organization_id)
        except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
        with e.begin() as c:c.execute(text('INSERT INTO erp_governance_certification_exception(exception_id,organization_id,module_name,action_code,reason,opened_by) VALUES(:id,:o,:m,:a,:r,:u)'),{'id':eid,'o':b.organization_id,'m':b.module_name.upper(),'a':b.action_code.upper(),'r':b.control_note,'u':u.user_id})
        return {'exception_id':eid,'status':'OPEN'}
    @app.get('/v90fq/governance/exceptions')
    def exceptions(r:Request,organization_id:str|None=None,status:str='OPEN'):
        _u(e,r,PERM_VIEW);q='SELECT * FROM erp_governance_certification_exception WHERE status=:s';p={'s':status.upper()}
        if organization_id:q+=' AND organization_id=:o';p['o']=organization_id
        with e.connect() as c:rows=[dict(x) for x in c.execute(text(q+' ORDER BY opened_at DESC'),p).mappings().all()]
        return {'exceptions':rows}
    @app.post('/v90fq/governance/exceptions/{exception_id}/resolve')
    def resolve(exception_id:str,b:ResolveIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.begin() as c:
            row=c.execute(text("SELECT * FROM erp_governance_certification_exception WHERE exception_id=:id AND status='OPEN'"),{'id':exception_id}).mappings().first()
            if not row:raise HTTPException(404,'open certification exception not found')
            try: assert_security_scope(e,u.user_id,organization_id=str(row['organization_id']) if row['organization_id'] else None)
            except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
            c.execute(text("UPDATE erp_governance_certification_exception SET status='RESOLVED',resolved_by=:u,resolved_at=CURRENT_TIMESTAMP,resolution_note=:n,evidence_ref=:r WHERE exception_id=:id"),{'id':exception_id,'u':u.user_id,'n':b.resolution_note,'r':b.evidence_ref})
        return {'exception_id':exception_id,'status':'RESOLVED'}
    @app.post('/v90fq/governance/{period_key}/close')
    def close(period_key:str,r:Request,force:bool=False,note:str=''):
        u=_u(e,r,PERM_MANAGE)
        with e.begin() as c:
            n=c.execute(text("SELECT COUNT(*) FROM erp_governance_certification_exception WHERE status='OPEN'"),{}).scalar() or 0
            unc=c.execute(text("SELECT COUNT(*) FROM erp_governance_critical_action_certification WHERE active=TRUE AND certification_status='EXCEPTION'"),{}).scalar() or 0
            if (n or unc) and not force: raise HTTPException(409,'open certification exceptions or uncertified critical actions block close')
            c.execute(text('INSERT INTO erp_governance_certification_close(close_id,organization_id,closed_by,force,note) VALUES(:id,NULL,:u,:f,:n)'),{'id':str(uuid4()),'u':u.user_id,'f':force,'n':note or f'Closed {period_key}'})
        return {'period_key':period_key,'status':'CLOSED','force':force}
    @app.get('/ui/governance-certification')
    def ui():return FileResponse(Path(__file__).resolve().parents[1]/'web'/'governance_certification.html')

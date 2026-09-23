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

PERM_VIEW='release.incident.view'
PERM_MANAGE='release.incident.manage'
SEVERITIES=('LOW','MEDIUM','HIGH','CRITICAL')
INCIDENT_STATUSES=('OPEN','ACKNOWLEDGED','RESOLVED','CLOSED')
PROBLEM_STATUSES=('OPEN','INVESTIGATING','MITIGATED','RESOLVED','CLOSED','ACCEPTED_EXCEPTION')
ESC_STATUSES=('OPEN','ACKNOWLEDGED','RESOLVED','CLOSED','WAIVED')

class ProblemIn(BaseModel):
    organization_id:str|None=None; problem_code:str=Field(min_length=2,max_length=80); title:str=Field(min_length=2,max_length=300)
    description:str=Field(min_length=1,max_length=3000); severity:str=Field(pattern='^(LOW|MEDIUM|HIGH|CRITICAL)$'); owner_user_id:str|None=None; root_cause:str|None=None; note:str=Field(min_length=1,max_length=3000)
class ProblemStatus(BaseModel):
    status:str=Field(pattern='^(OPEN|INVESTIGATING|MITIGATED|RESOLVED|CLOSED|ACCEPTED_EXCEPTION)$'); root_cause:str|None=None; evidence_ref:str|None=None; note:str=Field(min_length=1,max_length=3000)
class LinkIn(BaseModel):
    reference_type:str=Field(min_length=2,max_length=60); reference_id:str=Field(min_length=1,max_length=100); note:str=Field(min_length=1,max_length=3000)
class EscalationIn(BaseModel):
    problem_id:str=Field(min_length=1,max_length=100); level:int=Field(ge=1,le=10); owner_user_id:str|None=None; due_at:str=Field(min_length=10,max_length=40); reason:str=Field(min_length=1,max_length=3000)
class EscalationStatus(BaseModel):
    status:str=Field(pattern='^(OPEN|ACKNOWLEDGED|RESOLVED|CLOSED|WAIVED)$'); evidence_ref:str|None=None; note:str=Field(min_length=1,max_length=3000)
class ClosureIn(BaseModel):
    evidence_ref:str=Field(min_length=1,max_length=500); note:str=Field(min_length=1,max_length=3000)

def _u(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def _scope(e,u,o):
    try: assert_security_scope(e,u.user_id,organization_id=o)
    except PermissionError as ex: raise HTTPException(403,str(ex)) from ex

def ensure_v90gi_schema(e:Engine):
    stmts=[
    '''CREATE TABLE IF NOT EXISTS erp_ops_problem(problem_id TEXT PRIMARY KEY,organization_id TEXT NULL,problem_code TEXT NOT NULL,title TEXT NOT NULL,description TEXT NOT NULL,severity TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',owner_user_id TEXT NULL,root_cause TEXT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,resolved_at TIMESTAMP NULL,closed_at TIMESTAMP NULL,closure_evidence_ref TEXT NULL,closure_note TEXT NULL,UNIQUE(organization_id,problem_code))''',
    '''CREATE TABLE IF NOT EXISTS erp_ops_problem_link(link_id TEXT PRIMARY KEY,problem_id TEXT NOT NULL,reference_type TEXT NOT NULL,reference_id TEXT NOT NULL,note TEXT NOT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(problem_id,reference_type,reference_id))''',
    '''CREATE TABLE IF NOT EXISTS erp_ops_escalation(escalation_id TEXT PRIMARY KEY,organization_id TEXT NULL,problem_id TEXT NOT NULL,level INTEGER NOT NULL,owner_user_id TEXT NULL,due_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',reason TEXT NOT NULL,evidence_ref TEXT NULL,closure_note TEXT NULL,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(problem_id,level))''',
    'CREATE INDEX IF NOT EXISTS ix_problem_scope ON erp_ops_problem(organization_id,status,severity,created_at)',
    'CREATE INDEX IF NOT EXISTS ix_problem_link ON erp_ops_problem_link(problem_id,reference_type,reference_id)',
    'CREATE INDEX IF NOT EXISTS ix_escalation_scope ON erp_ops_escalation(organization_id,status,level,due_at)']
    with e.begin() as c:
        for s in stmts:c.execute(text(s))
        for p,n in [(PERM_VIEW,'View incidents, problems and escalations'),(PERM_MANAGE,'Manage incidents, problems and escalations')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':p})

def register_v90gi_routes(app:FastAPI,e:Engine):
    ensure_v90gi_schema(e)
    @app.post('/v90gi/problems')
    def create_problem(b:ProblemIn,r:Request):
        u=_u(e,r,PERM_MANAGE); _scope(e,u,b.organization_id); pid=str(uuid4())
        with e.begin() as c:
            try:c.execute(text('INSERT INTO erp_ops_problem(problem_id,organization_id,problem_code,title,description,severity,owner_user_id,root_cause,created_by) VALUES(:i,:o,:c,:t,:d,:s,:w,:rc,:u)'),{'i':pid,'o':b.organization_id,'c':b.problem_code.upper(),'t':b.title,'d':b.description,'s':b.severity,'w':b.owner_user_id,'rc':b.root_cause,'u':u.user_id})
            except Exception as ex: raise HTTPException(409,'problem code already exists for organization') from ex
        return {'problem_id':pid,'status':'OPEN'}
    @app.get('/v90gi/problems')
    def list_problems(r:Request,organization_id:str|None=None,status:str|None=None):
        _u(e,r,PERM_VIEW); q='SELECT * FROM erp_ops_problem WHERE organization_id IS NOT DISTINCT FROM :o'; p={'o':organization_id}
        if status:q+=' AND status=:s';p['s']=status.upper()
        with e.connect() as c: rows=[dict(x) for x in c.execute(text(q+' ORDER BY created_at DESC'),p).mappings().all()]
        return {'problems':rows}
    @app.post('/v90gi/problems/{problem_id}/links')
    def link(problem_id:str,b:LinkIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.connect() as c: row=c.execute(text('SELECT organization_id FROM erp_ops_problem WHERE problem_id=:i'),{'i':problem_id}).mappings().first()
        if not row:raise HTTPException(404,'problem not found')
        _scope(e,u,row['organization_id']); lid=str(uuid4())
        try:
            with e.begin() as c:c.execute(text('INSERT INTO erp_ops_problem_link(link_id,problem_id,reference_type,reference_id,note,created_by) VALUES(:i,:p,:t,:r,:n,:u)'),{'i':lid,'p':problem_id,'t':b.reference_type.upper(),'r':b.reference_id,'n':b.note,'u':u.user_id})
        except Exception as ex:raise HTTPException(409,'problem link already exists') from ex
        return {'link_id':lid,'status':'LINKED'}
    @app.post('/v90gi/problems/{problem_id}/status')
    def problem_status(problem_id:str,b:ProblemStatus,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.connect() as c:row=c.execute(text('SELECT organization_id,status FROM erp_ops_problem WHERE problem_id=:i'),{'i':problem_id}).mappings().first()
        if not row:raise HTTPException(404,'problem not found')
        _scope(e,u,row['organization_id'])
        if b.status in ('RESOLVED','CLOSED','ACCEPTED_EXCEPTION') and not b.evidence_ref:raise HTTPException(422,'evidence_ref required for resolved, closed or accepted exception status')
        if b.status=='CLOSED' and row['status'] not in ('RESOLVED','ACCEPTED_EXCEPTION'):raise HTTPException(409,'problem must be RESOLVED or ACCEPTED_EXCEPTION before CLOSED')
        with e.begin() as c:c.execute(text('UPDATE erp_ops_problem SET status=:s,root_cause=COALESCE(:rc,root_cause),updated_at=CURRENT_TIMESTAMP,resolved_at=CASE WHEN :s IN (\'RESOLVED\',\'ACCEPTED_EXCEPTION\') THEN CURRENT_TIMESTAMP ELSE resolved_at END,closed_at=CASE WHEN :s=\'CLOSED\' THEN CURRENT_TIMESTAMP ELSE closed_at END,closure_evidence_ref=CASE WHEN :s IN (\'CLOSED\',\'ACCEPTED_EXCEPTION\') THEN :e ELSE closure_evidence_ref END,closure_note=CASE WHEN :s IN (\'CLOSED\',\'ACCEPTED_EXCEPTION\') THEN :n ELSE closure_note END WHERE problem_id=:i'),{'s':b.status,'rc':b.root_cause,'e':b.evidence_ref,'n':b.note,'i':problem_id})
        return {'problem_id':problem_id,'status':b.status}
    @app.post('/v90gi/escalations')
    def create_escalation(b:EscalationIn,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.connect() as c:row=c.execute(text('SELECT organization_id,status FROM erp_ops_problem WHERE problem_id=:i'),{'i':b.problem_id}).mappings().first()
        if not row:raise HTTPException(404,'problem not found')
        _scope(e,u,row['organization_id'])
        eid=str(uuid4())
        try:
            with e.begin() as c:c.execute(text('INSERT INTO erp_ops_escalation(escalation_id,organization_id,problem_id,level,owner_user_id,due_at,reason,created_by) VALUES(:i,:o,:p,:l,:w,:d,:r,:u)'),{'i':eid,'o':row['organization_id'],'p':b.problem_id,'l':b.level,'w':b.owner_user_id,'d':b.due_at,'r':b.reason,'u':u.user_id})
        except Exception as ex:raise HTTPException(409,'escalation level already exists for problem') from ex
        return {'escalation_id':eid,'status':'OPEN'}
    @app.post('/v90gi/escalations/{escalation_id}/status')
    def escalation_status(escalation_id:str,b:EscalationStatus,r:Request):
        u=_u(e,r,PERM_MANAGE)
        with e.connect() as c:row=c.execute(text('SELECT organization_id,status FROM erp_ops_escalation WHERE escalation_id=:i'),{'i':escalation_id}).mappings().first()
        if not row:raise HTTPException(404,'escalation not found')
        _scope(e,u,row['organization_id'])
        if b.status in ('CLOSED','WAIVED') and not b.evidence_ref:raise HTTPException(422,'evidence_ref required for CLOSED or WAIVED')
        with e.begin() as c:c.execute(text('UPDATE erp_ops_escalation SET status=:s,evidence_ref=COALESCE(:e,evidence_ref),closure_note=:n,updated_at=CURRENT_TIMESTAMP WHERE escalation_id=:i'),{'s':b.status,'e':b.evidence_ref,'n':b.note,'i':escalation_id})
        return {'escalation_id':escalation_id,'status':b.status}
    @app.get('/v90gi/dashboard')
    def dashboard(r:Request,organization_id:str|None=None):
        _u(e,r,PERM_VIEW)
        with e.connect() as c:
            open_problems=c.execute(text("SELECT COUNT(*) FROM erp_ops_problem WHERE organization_id IS NOT DISTINCT FROM :o AND status NOT IN ('CLOSED','ACCEPTED_EXCEPTION')"),{'o':organization_id}).scalar_one()
            critical=c.execute(text("SELECT COUNT(*) FROM erp_ops_problem WHERE organization_id IS NOT DISTINCT FROM :o AND severity='CRITICAL' AND status NOT IN ('CLOSED','ACCEPTED_EXCEPTION')"),{'o':organization_id}).scalar_one()
            open_esc=c.execute(text("SELECT COUNT(*) FROM erp_ops_escalation WHERE organization_id IS NOT DISTINCT FROM :o AND status NOT IN ('CLOSED','WAIVED')"),{'o':organization_id}).scalar_one()
            overdue=c.execute(text("SELECT COUNT(*) FROM erp_ops_escalation WHERE organization_id IS NOT DISTINCT FROM :o AND status NOT IN ('CLOSED','WAIVED') AND due_at < CURRENT_TIMESTAMP"),{'o':organization_id}).scalar_one()
        return {'open_problems':int(open_problems),'critical_open_problems':int(critical),'open_escalations':int(open_esc),'overdue_escalations':int(overdue),'governance_gate_pass':int(critical)==0 and int(overdue)==0}
    @app.get('/ui/incident-problem-escalation')
    def ui():return FileResponse(Path(__file__).resolve().parents[1]/'web'/'incident_problem_escalation.html')
    return {'allowed':True}

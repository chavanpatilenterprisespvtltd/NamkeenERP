from __future__ import annotations
import json
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

PERMISSIONS = ('governance.audit.view','governance.approval.view','governance.approval.manage','governance.evidence.manage','governance.action.manage')


def _require(e: Engine, r: Request, permission: str):
    u = authenticate(r)
    ps = permissions_for_user(e, u.user_id)
    if permission not in ps and 'admin.users' not in ps:
        raise HTTPException(403, 'permission denied')
    return u


def ensure_v90fo_schema(e: Engine):
    stmts = [
        '''CREATE TABLE IF NOT EXISTS erp_governed_action_policy(
            policy_id TEXT PRIMARY KEY, organization_id TEXT NULL, action_code TEXT NOT NULL,
            module_name TEXT NOT NULL, risk_level TEXT NOT NULL DEFAULT 'MEDIUM',
            approval_required BOOLEAN NOT NULL DEFAULT TRUE, evidence_required BOOLEAN NOT NULL DEFAULT TRUE,
            active BOOLEAN NOT NULL DEFAULT TRUE, created_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,action_code))''',
        '''CREATE TABLE IF NOT EXISTS erp_governed_action(
            action_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NULL,
            module_name TEXT NOT NULL, action_code TEXT NOT NULL, subject_type TEXT NOT NULL,
            subject_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'REQUESTED',
            requested_by TEXT NOT NULL, requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            approved_by TEXT NULL, approved_at TIMESTAMP NULL, decision_note TEXT NULL,
            evidence_required BOOLEAN NOT NULL DEFAULT TRUE, evidence_complete BOOLEAN NOT NULL DEFAULT FALSE,
            executed_by TEXT NULL, executed_at TIMESTAMP NULL, cancelled_by TEXT NULL,
            cancelled_at TIMESTAMP NULL, cancellation_note TEXT NULL,
            UNIQUE(organization_id,module_name,action_code,subject_type,subject_id,status))''',
        '''CREATE TABLE IF NOT EXISTS erp_governed_action_evidence(
            evidence_id TEXT PRIMARY KEY, action_id TEXT NOT NULL, evidence_type TEXT NOT NULL,
            evidence_ref TEXT NULL, evidence_note TEXT NOT NULL, added_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        '''CREATE TABLE IF NOT EXISTS erp_audit_event(
            audit_id TEXT PRIMARY KEY, organization_id TEXT NULL, entity_id TEXT NULL,
            module_name TEXT NOT NULL, action_code TEXT NOT NULL, subject_type TEXT NULL,
            subject_id TEXT NULL, actor_user_id TEXT NOT NULL, outcome TEXT NOT NULL,
            governed_action_id TEXT NULL, details_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        'CREATE INDEX IF NOT EXISTS ix_governed_action_queue ON erp_governed_action(organization_id,status,module_name,action_code,requested_at)',
        'CREATE INDEX IF NOT EXISTS ix_governed_action_subject ON erp_governed_action(subject_type,subject_id,status)',
        'CREATE INDEX IF NOT EXISTS ix_governed_evidence_action ON erp_governed_action_evidence(action_id,created_at)',
        'CREATE INDEX IF NOT EXISTS ix_erp_audit_scope ON erp_audit_event(organization_id,entity_id,created_at)',
        'CREATE INDEX IF NOT EXISTS ix_erp_audit_action ON erp_audit_event(module_name,action_code,created_at)',
    ]
    with e.begin() as c:
        for s in stmts:
            c.execute(text(s))
        perms = {
            'governance.audit.view':'View ERP audit trail',
            'governance.approval.view':'View governed approval queue',
            'governance.approval.manage':'Approve or reject governed actions',
            'governance.evidence.manage':'Add evidence to governed actions',
            'governance.action.manage':'Create governed actions and policies',
        }
        for p,n in perms.items():
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {'p':p,'n':n})
        grants={
            'super_admin':perms.keys(),
            'manager':('governance.audit.view','governance.approval.view','governance.approval.manage','governance.evidence.manage'),
            'operator':('governance.audit.view','governance.approval.view','governance.evidence.manage'),
        }
        for role,ps in grants.items():
            for p in ps:
                c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role,'p':p})


def write_audit(e: Engine, *, actor_user_id: str, module_name: str, action_code: str, outcome: str,
                organization_id: str | None = None, entity_id: str | None = None,
                subject_type: str | None = None, subject_id: str | None = None,
                governed_action_id: str | None = None, details: dict | None = None):
    with e.begin() as c:
        c.execute(text('''INSERT INTO erp_audit_event(audit_id,organization_id,entity_id,module_name,action_code,subject_type,subject_id,actor_user_id,outcome,governed_action_id,details_json)
                          VALUES(:id,:o,:e,:m,:a,:st,:si,:u,:out,:ga,:d)'''), {
            'id':str(uuid4()), 'o':organization_id, 'e':entity_id, 'm':module_name.upper(), 'a':action_code.upper(),
            'st':subject_type, 'si':subject_id, 'u':actor_user_id, 'out':outcome.upper(), 'ga':governed_action_id,
            'd':json.dumps(details or {}, default=str),
        })


def create_governed_action(e: Engine, *, actor_user_id: str, organization_id: str, module_name: str,
                           action_code: str, subject_type: str, subject_id: str, entity_id: str | None = None,
                           evidence_required: bool | None = None) -> str:
    try:
        assert_security_scope(e, actor_user_id, organization_id=organization_id, entity_id=entity_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    with e.begin() as c:
        pol=c.execute(text('''SELECT * FROM erp_governed_action_policy WHERE (organization_id=:o OR organization_id IS NULL) AND action_code=:a AND active=TRUE ORDER BY organization_id NULLS LAST LIMIT 1'''), {'o':organization_id,'a':action_code.upper()}).mappings().first()
        ev_req = bool(evidence_required) if evidence_required is not None else bool(pol['evidence_required']) if pol else True
        aid=str(uuid4())
        c.execute(text('''INSERT INTO erp_governed_action(action_id,organization_id,entity_id,module_name,action_code,subject_type,subject_id,status,requested_by,evidence_required)
                          VALUES(:id,:o,:e,:m,:a,:st,:si,'REQUESTED',:u,:ev)'''), {'id':aid,'o':organization_id,'e':entity_id,'m':module_name.upper(),'a':action_code.upper(),'st':subject_type.upper(),'si':subject_id,'u':actor_user_id,'ev':ev_req})
    write_audit(e, actor_user_id=actor_user_id,module_name=module_name,action_code=action_code,outcome='REQUESTED',organization_id=organization_id,entity_id=entity_id,subject_type=subject_type,subject_id=subject_id,governed_action_id=aid)
    return aid


def require_executable_action(e: Engine, *, actor_user_id: str, action_id: str, organization_id: str,
                              module_name: str, action_code: str, subject_type: str, subject_id: str):
    with e.begin() as c:
        row=c.execute(text('''SELECT * FROM erp_governed_action WHERE action_id=:id AND organization_id=:o AND module_name=:m AND action_code=:a AND subject_type=:st AND subject_id=:si'''), {'id':action_id,'o':organization_id,'m':module_name.upper(),'a':action_code.upper(),'st':subject_type.upper(),'si':subject_id}).mappings().first()
        if not row: raise HTTPException(404,'governed action not found')
        if row['status']!='APPROVED': raise HTTPException(409,f'governed action status is {row["status"]}')
        if row['evidence_required'] and not row['evidence_complete']: raise HTTPException(409,'required evidence is incomplete')
        c.execute(text("UPDATE erp_governed_action SET status='EXECUTED',executed_by=:u,executed_at=CURRENT_TIMESTAMP WHERE action_id=:id"), {'u':actor_user_id,'id':action_id})
    write_audit(e,actor_user_id=actor_user_id,module_name=module_name,action_code=action_code,outcome='EXECUTED',organization_id=organization_id,governed_action_id=action_id,subject_type=subject_type,subject_id=subject_id)


class PolicyIn(BaseModel):
    organization_id: str | None = None
    action_code: str = Field(min_length=2,max_length=80)
    module_name: str = Field(min_length=2,max_length=80)
    risk_level: str = Field(default='MEDIUM',min_length=3,max_length=20)
    approval_required: bool = True
    evidence_required: bool = True

class ActionIn(BaseModel):
    organization_id: str
    entity_id: str | None = None
    module_name: str
    action_code: str
    subject_type: str
    subject_id: str
    evidence_required: bool | None = None

class DecisionIn(BaseModel):
    decision_note: str = Field(min_length=1,max_length=2000)

class EvidenceIn(BaseModel):
    evidence_type: str = Field(min_length=2,max_length=50)
    evidence_ref: str | None = Field(default=None,max_length=500)
    evidence_note: str = Field(min_length=1,max_length=3000)


def register_v90fo_routes(app: FastAPI, e: Engine):
    ensure_v90fo_schema(e)

    @app.post('/v90fo/governance/policies')
    def create_policy(body: PolicyIn, request: Request):
        u=_require(e,request,'governance.action.manage')
        with e.begin() as c:
            pid=str(uuid4())
            c.execute(text('''INSERT INTO erp_governed_action_policy(policy_id,organization_id,action_code,module_name,risk_level,approval_required,evidence_required,created_by)
                              VALUES(:id,:o,:a,:m,:r,:ar,:er,:u) ON CONFLICT(organization_id,action_code) DO UPDATE SET module_name=:m,risk_level=:r,approval_required=:ar,evidence_required=:er,active=TRUE'''), {'id':pid,'o':body.organization_id,'a':body.action_code.upper(),'m':body.module_name.upper(),'r':body.risk_level.upper(),'ar':body.approval_required,'er':body.evidence_required,'u':u.user_id})
        write_audit(e,actor_user_id=u.user_id,module_name='GOVERNANCE',action_code='POLICY_UPSERT',outcome='SUCCESS',organization_id=body.organization_id,subject_type='POLICY',subject_id=body.action_code.upper())
        return {'policy_id':pid,'status':'ACTIVE'}

    @app.get('/v90fo/governance/policies')
    def list_policies(request: Request, organization_id: str|None=None):
        _require(e,request,'governance.audit.view')
        q='SELECT * FROM erp_governed_action_policy WHERE active=TRUE'; p={}
        if organization_id: q+=' AND (organization_id=:o OR organization_id IS NULL)'; p['o']=organization_id
        with e.connect() as c: rows=[dict(r) for r in c.execute(text(q+' ORDER BY module_name,action_code'),p).mappings().all()]
        return {'policies':rows}

    @app.post('/v90fo/governance/actions')
    def create_action(body: ActionIn, request: Request):
        u=_require(e,request,'governance.action.manage')
        aid=create_governed_action(e,actor_user_id=u.user_id,organization_id=body.organization_id,module_name=body.module_name,action_code=body.action_code,subject_type=body.subject_type,subject_id=body.subject_id,entity_id=body.entity_id,evidence_required=body.evidence_required)
        return {'action_id':aid,'status':'REQUESTED'}

    @app.get('/v90fo/governance/actions')
    def list_actions(request: Request, organization_id: str, status: str|None=None):
        _require(e,request,'governance.approval.view')
        q='SELECT * FROM erp_governed_action WHERE organization_id=:o'; p={'o':organization_id}
        if status: q+=' AND status=:s'; p['s']=status.upper()
        with e.connect() as c: rows=[dict(r) for r in c.execute(text(q+' ORDER BY requested_at DESC LIMIT 1000'),p).mappings().all()]
        return {'actions':rows}

    @app.post('/v90fo/governance/actions/{action_id}/approve')
    def approve(action_id: str, body: DecisionIn, request: Request):
        u=_require(e,request,'governance.approval.manage')
        with e.begin() as c:
            row=c.execute(text("SELECT * FROM erp_governed_action WHERE action_id=:id AND status='REQUESTED'"),{'id':action_id}).mappings().first()
            if not row: raise HTTPException(404,'requested governed action not found')
            if str(row['requested_by'])==str(u.user_id): raise HTTPException(409,'self-approval is not allowed')
            if row['evidence_required']:
                n=c.execute(text('SELECT COUNT(*) FROM erp_governed_action_evidence WHERE action_id=:id'),{'id':action_id}).scalar() or 0
                if n==0: raise HTTPException(409,'required evidence must be recorded before approval')
            c.execute(text("UPDATE erp_governed_action SET status='APPROVED',approved_by=:u,approved_at=CURRENT_TIMESTAMP,decision_note=:n,evidence_complete=CASE WHEN evidence_required THEN TRUE ELSE evidence_complete END WHERE action_id=:id"),{'u':u.user_id,'n':body.decision_note,'id':action_id})
        write_audit(e,actor_user_id=u.user_id,module_name='GOVERNANCE',action_code='ACTION_APPROVE',outcome='SUCCESS',organization_id=str(row['organization_id']),entity_id=row['entity_id'],subject_type=row['subject_type'],subject_id=row['subject_id'],governed_action_id=action_id,details={'decision_note':body.decision_note})
        return {'action_id':action_id,'status':'APPROVED'}

    @app.post('/v90fo/governance/actions/{action_id}/reject')
    def reject(action_id: str, body: DecisionIn, request: Request):
        u=_require(e,request,'governance.approval.manage')
        with e.begin() as c:
            row=c.execute(text("SELECT * FROM erp_governed_action WHERE action_id=:id AND status='REQUESTED'"),{'id':action_id}).mappings().first()
            if not row: raise HTTPException(404,'requested governed action not found')
            if str(row['requested_by'])==str(u.user_id): raise HTTPException(409,'self-rejection is not allowed')
            c.execute(text("UPDATE erp_governed_action SET status='REJECTED',approved_by=:u,approved_at=CURRENT_TIMESTAMP,decision_note=:n WHERE action_id=:id"),{'u':u.user_id,'n':body.decision_note,'id':action_id})
        write_audit(e,actor_user_id=u.user_id,module_name='GOVERNANCE',action_code='ACTION_REJECT',outcome='SUCCESS',organization_id=str(row['organization_id']),entity_id=row['entity_id'],subject_type=row['subject_type'],subject_id=row['subject_id'],governed_action_id=action_id)
        return {'action_id':action_id,'status':'REJECTED'}

    @app.post('/v90fo/governance/actions/{action_id}/evidence')
    def add_evidence(action_id: str, body: EvidenceIn, request: Request):
        u=_require(e,request,'governance.evidence.manage')
        with e.begin() as c:
            row=c.execute(text('SELECT * FROM erp_governed_action WHERE action_id=:id'),{'id':action_id}).mappings().first()
            if not row: raise HTTPException(404,'governed action not found')
            evid=str(uuid4())
            c.execute(text('''INSERT INTO erp_governed_action_evidence(evidence_id,action_id,evidence_type,evidence_ref,evidence_note,added_by) VALUES(:id,:a,:t,:r,:n,:u)'''), {'id':evid,'a':action_id,'t':body.evidence_type.upper(),'r':body.evidence_ref,'n':body.evidence_note,'u':u.user_id})
            c.execute(text("UPDATE erp_governed_action SET evidence_complete=TRUE WHERE action_id=:id"),{'id':action_id})
        write_audit(e,actor_user_id=u.user_id,module_name='GOVERNANCE',action_code='EVIDENCE_ADD',outcome='SUCCESS',organization_id=str(row['organization_id']),entity_id=row['entity_id'],subject_type=row['subject_type'],subject_id=row['subject_id'],governed_action_id=action_id,details={'evidence_type':body.evidence_type.upper()})
        return {'evidence_id':evid,'action_id':action_id,'evidence_complete':True}

    @app.get('/v90fo/governance/audit')
    def audit(request: Request, organization_id: str|None=None, module_name: str|None=None, action_code: str|None=None, limit: int=500):
        _require(e,request,'governance.audit.view'); limit=max(1,min(limit,1000))
        q='SELECT * FROM erp_audit_event WHERE 1=1'; p={}
        if organization_id:q+=' AND organization_id=:o';p['o']=organization_id
        if module_name:q+=' AND module_name=:m';p['m']=module_name.upper()
        if action_code:q+=' AND action_code=:a';p['a']=action_code.upper()
        q+=' ORDER BY created_at DESC LIMIT :lim';p['lim']=limit
        with e.connect() as c: rows=[dict(r) for r in c.execute(text(q),p).mappings().all()]
        return {'events':rows}

    @app.get('/ui/governance-control')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'governance_control.html')

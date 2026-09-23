from __future__ import annotations
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed
from .v90fo_audit_approval_evidence import write_audit


def _scope(engine, request: Request, permission: str, entity_id: str | None = None, location_id: str | None = None):
    user = authenticate(request)
    if permission not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    if entity_id:
        try: assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
        except PermissionError as exc: raise HTTPException(403, str(exc)) from exc
    return user


def ensure_v90bd_schema(engine):
    stmts = [
      """CREATE TABLE IF NOT EXISTS notification_templates (
        template_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NULL,
        template_code TEXT NOT NULL, channel TEXT NOT NULL, subject_template TEXT NULL,
        body_template TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,template_code,channel))""",
      """CREATE TABLE IF NOT EXISTS notifications (
        notification_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NULL,
        location_id TEXT NULL, recipient_user_id TEXT NULL, recipient_address TEXT NULL,
        template_id TEXT NULL, channel TEXT NOT NULL, subject TEXT NULL, body TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING', related_type TEXT NULL, related_id TEXT NULL,
        scheduled_at TEXT NULL, sent_at TEXT NULL, failure_reason TEXT NULL,
        created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
      """CREATE TABLE IF NOT EXISTS approval_workflows (
        workflow_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NULL,
        workflow_code TEXT NOT NULL, workflow_name TEXT NOT NULL, module_name TEXT NOT NULL,
        min_amount REAL NULL, active INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,workflow_code))""",
      """CREATE TABLE IF NOT EXISTS approval_requests (
        approval_request_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NULL,
        location_id TEXT NULL, workflow_id TEXT NOT NULL, subject_type TEXT NOT NULL,
        subject_id TEXT NOT NULL, requested_by TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
        requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, decided_by TEXT NULL,
        decided_at TEXT NULL, decision_reason TEXT NULL, payload_json TEXT NOT NULL DEFAULT '{}')""",
      """CREATE TABLE IF NOT EXISTS approval_steps (
        step_id TEXT PRIMARY KEY, approval_request_id TEXT NOT NULL, step_no INTEGER NOT NULL,
        approver_user_id TEXT NULL, approver_role_id TEXT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
        decided_by TEXT NULL, decided_at TEXT NULL, decision_reason TEXT NULL,
        UNIQUE(approval_request_id,step_no))""",
      "CREATE INDEX IF NOT EXISTS ix_notifications_queue ON notifications(status,scheduled_at,created_at)",
      "CREATE INDEX IF NOT EXISTS ix_approval_queue ON approval_requests(organization_id,entity_id,status,requested_at)",
    ]
    with engine.begin() as c:
      for s in stmts: c.execute(text(s))
      perms={'notification.view':'View notifications','notification.send':'Create/send notifications','approval.view':'View approval queue','approval.submit':'Submit approvals','approval.decide':'Approve/reject workflow requests','approval.manage':'Manage approval workflows'}
      for p,n in perms.items(): c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"),{'p':p,'n':n})
      grants={
        'manager':['notification.view','notification.send','approval.view','approval.submit','approval.decide','approval.manage'],
        'super_admin':['notification.view','notification.send','approval.view','approval.submit','approval.decide','approval.manage'],
        'operator':['notification.view','approval.view','approval.submit'],
        'production':['notification.view','notification.send','approval.view','approval.submit'],
        'quality':['notification.view','notification.send','approval.view','approval.submit'],
        'warehouse':['notification.view','notification.send','approval.view','approval.submit'],
        'dispatch':['notification.view','notification.send','approval.view','approval.submit'],
        'salesperson':['notification.view','notification.send','approval.view','approval.submit'],
      }
      for role,ps in grants.items():
        for p in ps: c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'r':role,'p':p})


class TemplateIn(BaseModel):
    organization_id: UUID; entity_id: UUID|None=None; template_code: str=Field(min_length=2,max_length=80)
    channel: str=Field(default='IN_APP',min_length=2,max_length=30); subject_template: str|None=None
    body_template: str=Field(min_length=1,max_length=5000)

class NotificationIn(BaseModel):
    organization_id: UUID; entity_id: UUID|None=None; location_id: UUID|None=None
    recipient_user_id: UUID|None=None; recipient_address: str|None=None; template_id: UUID|None=None
    channel: str=Field(default='IN_APP',min_length=2,max_length=30); subject: str|None=None; body: str=Field(min_length=1,max_length=5000)
    related_type: str|None=None; related_id: str|None=None; scheduled_at: str|None=None

class WorkflowIn(BaseModel):
    organization_id: UUID; entity_id: UUID|None=None; workflow_code: str=Field(min_length=2,max_length=80)
    workflow_name: str=Field(min_length=2,max_length=160); module_name: str=Field(min_length=2,max_length=80); min_amount: float|None=None

class ApprovalIn(BaseModel):
    organization_id: UUID; entity_id: UUID|None=None; location_id: UUID|None=None; workflow_id: UUID
    subject_type: str=Field(min_length=2,max_length=80); subject_id: str=Field(min_length=1,max_length=120); payload: dict={}

class DecisionIn(BaseModel):
    reason: str|None=None


def register_v90bd_routes(app: FastAPI, engine):
    ensure_v90bd_schema(engine)
    @app.post('/v90bd/notification-templates')
    def create_template(body: TemplateIn, request: Request):
        user=_scope(engine,request,'approval.manage',str(body.entity_id) if body.entity_id else None)
        tid=str(uuid4())
        with engine.begin() as c:
            c.execute(text("INSERT INTO notification_templates(template_id,organization_id,entity_id,template_code,channel,subject_template,body_template,created_by) VALUES(:i,:o,:e,:c,:ch,:s,:b,:u)"),{'i':tid,'o':str(body.organization_id),'e':str(body.entity_id) if body.entity_id else None,'c':body.template_code.upper(),'ch':body.channel.upper(),'s':body.subject_template,'b':body.body_template,'u':user.user_id})
        return {'template_id':tid,'status':'ACTIVE'}

    @app.post('/v90bd/notifications')
    def create_notification(body: NotificationIn, request: Request):
        user=_scope(engine,request,'notification.send',str(body.entity_id) if body.entity_id else None,str(body.location_id) if body.location_id else None)
        nid=str(uuid4()); status='SCHEDULED' if body.scheduled_at else 'PENDING'
        with engine.begin() as c:
            if body.template_id:
                t=c.execute(text('SELECT * FROM notification_templates WHERE template_id=:i AND active=1'),{'i':str(body.template_id)}).mappings().first()
                if not t: raise HTTPException(404,'notification template not found')
            c.execute(text("INSERT INTO notifications(notification_id,organization_id,entity_id,location_id,recipient_user_id,recipient_address,template_id,channel,subject,body,status,related_type,related_id,scheduled_at,created_by) VALUES(:i,:o,:e,:l,:ru,:ra,:t,:ch,:s,:b,:st,:rt,:ri,:sa,:u)"),{'i':nid,'o':str(body.organization_id),'e':str(body.entity_id) if body.entity_id else None,'l':str(body.location_id) if body.location_id else None,'ru':str(body.recipient_user_id) if body.recipient_user_id else None,'ra':body.recipient_address,'t':str(body.template_id) if body.template_id else None,'ch':body.channel.upper(),'s':body.subject,'b':body.body,'st':status,'rt':body.related_type,'ri':body.related_id,'sa':body.scheduled_at,'u':user.user_id})
        return {'notification_id':nid,'status':status}

    @app.get('/v90bd/notifications')
    def list_notifications(organization_id: UUID, status: str|None=None, request: Request=None):
        _scope(engine,request,'notification.view')
        sql='SELECT * FROM notifications WHERE organization_id=:o'; params={'o':str(organization_id)}
        if status: sql+=' AND status=:s'; params['s']=status.upper()
        sql+=' ORDER BY created_at DESC'
        with engine.connect() as c: rows=[dict(r) for r in c.execute(text(sql),params).mappings().all()]
        return {'notifications':rows}

    @app.post('/v90bd/workflows')
    def create_workflow(body: WorkflowIn, request: Request):
        user=_scope(engine,request,'approval.manage',str(body.entity_id) if body.entity_id else None)
        wid=str(uuid4())
        with engine.begin() as c:
            c.execute(text("INSERT INTO approval_workflows(workflow_id,organization_id,entity_id,workflow_code,workflow_name,module_name,min_amount,created_by) VALUES(:i,:o,:e,:c,:n,:m,:a,:u)"),{'i':wid,'o':str(body.organization_id),'e':str(body.entity_id) if body.entity_id else None,'c':body.workflow_code.upper(),'n':body.workflow_name,'m':body.module_name.upper(),'a':body.min_amount,'u':user.user_id})
        return {'workflow_id':wid,'status':'ACTIVE'}

    @app.post('/v90bd/approvals')
    def submit_approval(body: ApprovalIn, request: Request):
        user=_scope(engine,request,'approval.submit',str(body.entity_id) if body.entity_id else None,str(body.location_id) if body.location_id else None)
        with engine.connect() as c: wf=c.execute(text('SELECT * FROM approval_workflows WHERE workflow_id=:i AND active=1'),{'i':str(body.workflow_id)}).mappings().first()
        if not wf: raise HTTPException(404,'approval workflow not found')
        aid=str(uuid4())
        with engine.begin() as c:
            c.execute(text("INSERT INTO approval_requests(approval_request_id,organization_id,entity_id,location_id,workflow_id,subject_type,subject_id,requested_by,payload_json) VALUES(:i,:o,:e,:l,:w,:st,:si,:u,:p)"),{'i':aid,'o':str(body.organization_id),'e':str(body.entity_id) if body.entity_id else None,'l':str(body.location_id) if body.location_id else None,'w':str(body.workflow_id),'st':body.subject_type.upper(),'si':body.subject_id,'u':user.user_id,'p':json.dumps(body.payload)})
            c.execute(text("INSERT INTO approval_steps(step_id,approval_request_id,step_no,approver_role_id) VALUES(:i,:r,1,'manager')"),{'i':str(uuid4()),'r':aid})
        write_audit(engine, actor_user_id=str(user.user_id), module_name='APPROVAL', action_code='REQUEST_CREATE', outcome='SUCCESS', organization_id=str(body.organization_id), entity_id=str(body.entity_id) if body.entity_id else None, subject_type=body.subject_type.upper(), subject_id=body.subject_id, details={'workflow_id':str(body.workflow_id)})
        return {'approval_request_id':aid,'status':'PENDING','current_step':1}

    @app.get('/v90bd/approvals')
    def approval_queue(organization_id: UUID, status: str='PENDING', request: Request=None):
        _scope(engine,request,'approval.view')
        with engine.connect() as c:
            rows=[dict(r) for r in c.execute(text("SELECT ar.*, aw.workflow_code, aw.workflow_name FROM approval_requests ar JOIN approval_workflows aw ON aw.workflow_id=ar.workflow_id WHERE ar.organization_id=:o AND ar.status=:s ORDER BY ar.requested_at"),{'o':str(organization_id),'s':status.upper()}).mappings().all()]
        return {'approvals':rows}

    @app.post('/v90bd/approvals/{approval_request_id}/approve')
    def approve(approval_request_id: UUID, body: DecisionIn, request: Request):
        user=_scope(engine,request,'approval.decide')
        with engine.begin() as c:
            ar=c.execute(text('SELECT * FROM approval_requests WHERE approval_request_id=:i AND status=\'PENDING\''),{'i':str(approval_request_id)}).mappings().first()
            if not ar: raise HTTPException(404,'pending approval not found')
            if str(ar['requested_by'])==str(user.user_id): raise HTTPException(409,'self-approval is not allowed')
            step=c.execute(text("SELECT * FROM approval_steps WHERE approval_request_id=:i AND status='PENDING' ORDER BY step_no LIMIT 1"),{'i':str(approval_request_id)}).mappings().first()
            if not step: raise HTTPException(409,'approval step not pending')
            c.execute(text("UPDATE approval_steps SET status='APPROVED',decided_by=:u,decided_at=CURRENT_TIMESTAMP,decision_reason=:r WHERE step_id=:s"),{'u':user.user_id,'r':body.reason,'s':step['step_id']})
            c.execute(text("UPDATE approval_requests SET status='APPROVED',decided_by=:u,decided_at=CURRENT_TIMESTAMP,decision_reason=:r WHERE approval_request_id=:i"),{'u':user.user_id,'r':body.reason,'i':str(approval_request_id)})
        write_audit(engine, actor_user_id=str(user.user_id), module_name='APPROVAL', action_code='REQUEST_APPROVE', outcome='SUCCESS', organization_id=str(ar['organization_id']), entity_id=ar.get('entity_id'), subject_type=ar['subject_type'], subject_id=ar['subject_id'], details={'approval_request_id':str(approval_request_id)})
        return {'approval_request_id':str(approval_request_id),'status':'APPROVED'}

    @app.post('/v90bd/approvals/{approval_request_id}/reject')
    def reject(approval_request_id: UUID, body: DecisionIn, request: Request):
        user=_scope(engine,request,'approval.decide')
        if not body.reason: raise HTTPException(422,'rejection reason is required')
        with engine.begin() as c:
            ar=c.execute(text('SELECT * FROM approval_requests WHERE approval_request_id=:i AND status=\'PENDING\''),{'i':str(approval_request_id)}).mappings().first()
            if not ar: raise HTTPException(404,'pending approval not found')
            if str(ar['requested_by'])==str(user.user_id): raise HTTPException(409,'self-rejection is not allowed')
            step=c.execute(text("SELECT * FROM approval_steps WHERE approval_request_id=:i AND status='PENDING' ORDER BY step_no LIMIT 1"),{'i':str(approval_request_id)}).mappings().first()
            if not step: raise HTTPException(409,'approval step not pending')
            c.execute(text("UPDATE approval_steps SET status='REJECTED',decided_by=:u,decided_at=CURRENT_TIMESTAMP,decision_reason=:r WHERE step_id=:s"),{'u':user.user_id,'r':body.reason,'s':step['step_id']})
            c.execute(text("UPDATE approval_requests SET status='REJECTED',decided_by=:u,decided_at=CURRENT_TIMESTAMP,decision_reason=:r WHERE approval_request_id=:i"),{'u':user.user_id,'r':body.reason,'i':str(approval_request_id)})
        write_audit(engine, actor_user_id=str(user.user_id), module_name='APPROVAL', action_code='REQUEST_REJECT', outcome='SUCCESS', organization_id=str(ar['organization_id']), entity_id=ar.get('entity_id'), subject_type=ar['subject_type'], subject_id=ar['subject_id'], details={'approval_request_id':str(approval_request_id)})
        return {'approval_request_id':str(approval_request_id),'status':'REJECTED'}

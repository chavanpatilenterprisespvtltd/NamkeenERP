from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


def _now(): return datetime.now(timezone.utc).isoformat()

def _scope(engine, request: Request, entity_id: str, location_id: str | None, write: bool):
    user = authenticate(request)
    need = 'evidence.write' if write else 'evidence.view'
    if need not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    try: assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc: raise HTTPException(403, str(exc)) from exc
    return user


def ensure_v90bc_schema(engine):
    stmts = [
      """CREATE TABLE IF NOT EXISTS evidence_attachments (
        attachment_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
        subject_type TEXT NOT NULL, subject_id TEXT NOT NULL, document_type TEXT NOT NULL, filename TEXT NOT NULL,
        mime_type TEXT NOT NULL, storage_ref TEXT NOT NULL, sha256 TEXT NULL, size_bytes INTEGER NULL,
        captured_at TEXT NULL, captured_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        active INTEGER NOT NULL DEFAULT 1, metadata_json TEXT NOT NULL DEFAULT '{}')""",
      """CREATE TABLE IF NOT EXISTS evidence_gps (
        evidence_gps_id TEXT PRIMARY KEY, attachment_id TEXT NOT NULL UNIQUE, latitude REAL NOT NULL, longitude REAL NOT NULL,
        accuracy_m REAL NULL, altitude_m REAL NULL, captured_at TEXT NULL, device_id TEXT NULL, provider TEXT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(attachment_id) REFERENCES evidence_attachments(attachment_id))""",
      """CREATE TABLE IF NOT EXISTS evidence_events (
        event_id TEXT PRIMARY KEY, attachment_id TEXT NOT NULL, event_type TEXT NOT NULL, event_payload_json TEXT NOT NULL,
        actor_id TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
      "CREATE INDEX IF NOT EXISTS ix_evidence_subject ON evidence_attachments(entity_id,location_id,subject_type,subject_id,active)",
      "CREATE INDEX IF NOT EXISTS ix_evidence_gps ON evidence_gps(latitude,longitude,captured_at)"
    ]
    with engine.begin() as c:
      for s in stmts: c.execute(text(s))
      perms={'evidence.view':'View attachments and GPS evidence','evidence.write':'Create, activate and audit attachments and GPS evidence'}
      for p,n in perms.items(): c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"),{'p':p,'n':n})
      for r in ('manager','super_admin','operator','production','quality','warehouse','dispatch','salesperson','mis'):
        c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'evidence.view') ON CONFLICT(role_id,permission_id) DO NOTHING"),{'r':r})
      for r in ('manager','super_admin','operator','production','quality','warehouse','dispatch','salesperson'):
        c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'evidence.write') ON CONFLICT(role_id,permission_id) DO NOTHING"),{'r':r})

class AttachmentIn(BaseModel):
    organization_id: UUID; entity_id: UUID; location_id: UUID|None=None
    subject_type: str=Field(min_length=2,max_length=80); subject_id: str=Field(min_length=2,max_length=120)
    document_type: str=Field(min_length=2,max_length=60); filename: str=Field(min_length=1,max_length=255)
    mime_type: str=Field(min_length=3,max_length=120); storage_ref: str=Field(min_length=2,max_length=500)
    sha256: str|None=None; size_bytes: int|None=Field(default=None,ge=0); captured_at: str|None=None; metadata: dict={}

class GPSIn(BaseModel):
    latitude: float=Field(ge=-90,le=90); longitude: float=Field(ge=-180,le=180)
    accuracy_m: float|None=Field(default=None,ge=0); altitude_m: float|None=None; captured_at: str|None=None
    device_id: UUID|None=None; provider: str|None=Field(default=None,max_length=40)


def register_v90bc_routes(app: FastAPI, engine):
    ensure_v90bc_schema(engine)
    @app.post('/v90bc/attachments')
    def create_attachment(body: AttachmentIn, request: Request):
      user=_scope(engine,request,str(body.entity_id),str(body.location_id) if body.location_id else None,True)
      if body.sha256 and len(body.sha256)!=64: raise HTTPException(422,'sha256 must be 64 hex characters')
      aid=str(uuid4())
      with engine.begin() as c:
        c.execute(text("INSERT INTO evidence_attachments(attachment_id,organization_id,entity_id,location_id,subject_type,subject_id,document_type,filename,mime_type,storage_ref,sha256,size_bytes,captured_at,captured_by,metadata_json) VALUES(:a,:o,:e,:l,:st,:si,:dt,:fn,:mt,:sr,:sh,:sz,:ca,:u,:m)"),{'a':aid,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id) if body.location_id else None,'st':body.subject_type.upper(),'si':body.subject_id,'dt':body.document_type.upper(),'fn':body.filename,'mt':body.mime_type,'sr':body.storage_ref,'sh':body.sha256.lower() if body.sha256 else None,'sz':body.size_bytes,'ca':body.captured_at,'u':user.user_id,'m':json.dumps(body.metadata)})
        c.execute(text("INSERT INTO evidence_events(event_id,attachment_id,event_type,event_payload_json,actor_id) VALUES(:i,:a,'CREATED',:p,:u)"),{'i':str(uuid4()),'a':aid,'p':json.dumps({'document_type':body.document_type.upper(),'subject_type':body.subject_type.upper()}),'u':user.user_id})
      return {'attachment_id':aid,'status':'ACTIVE'}

    @app.post('/v90bc/attachments/{attachment_id}/gps')
    def capture_gps(attachment_id: UUID, body: GPSIn, request: Request):
      user=authenticate(request)
      if 'evidence.write' not in permissions_for_user(engine,user.user_id): raise HTTPException(403,'permission denied')
      with engine.begin() as c:
        a=c.execute(text('SELECT * FROM evidence_attachments WHERE attachment_id=:a AND active=1'),{'a':str(attachment_id)}).mappings().first()
        if not a: raise HTTPException(404,'attachment not found')
        try: assert_entity_location_allowed(engine,user.user_id,str(a['entity_id']),str(a['location_id']) if a['location_id'] else None)
        except PermissionError as exc: raise HTTPException(403,str(exc)) from exc
        existing=c.execute(text('SELECT evidence_gps_id FROM evidence_gps WHERE attachment_id=:a'),{'a':str(attachment_id)}).first()
        if existing: raise HTTPException(409,'GPS evidence already captured')
        gid=str(uuid4())
        c.execute(text("INSERT INTO evidence_gps(evidence_gps_id,attachment_id,latitude,longitude,accuracy_m,altitude_m,captured_at,device_id,provider) VALUES(:i,:a,:la,:lo,:ac,:al,:ca,:d,:p)"),{'i':gid,'a':str(attachment_id),'la':body.latitude,'lo':body.longitude,'ac':body.accuracy_m,'al':body.altitude_m,'ca':body.captured_at,'d':str(body.device_id) if body.device_id else None,'p':body.provider})
        c.execute(text("INSERT INTO evidence_events(event_id,attachment_id,event_type,event_payload_json,actor_id) VALUES(:i,:a,'GPS_CAPTURED',:p,:u)"),{'i':str(uuid4()),'a':str(attachment_id),'p':json.dumps({'latitude':body.latitude,'longitude':body.longitude,'accuracy_m':body.accuracy_m}),'u':user.user_id})
      return {'attachment_id':str(attachment_id),'status':'GPS_CAPTURED','latitude':body.latitude,'longitude':body.longitude}

    @app.get('/v90bc/attachments')
    def list_attachments(organization_id: UUID, entity_id: UUID, location_id: UUID|None=None, subject_type: str|None=None, subject_id: str|None=None, request: Request=None):
      _scope(engine,request,str(entity_id),str(location_id) if location_id else None,False)
      sql='SELECT a.*, g.latitude, g.longitude, g.accuracy_m, g.altitude_m, g.captured_at AS gps_captured_at FROM evidence_attachments a LEFT JOIN evidence_gps g ON g.attachment_id=a.attachment_id WHERE a.organization_id=:o AND a.entity_id=:e AND (a.location_id=:l OR :l IS NULL) AND a.active=1'
      params={'o':str(organization_id),'e':str(entity_id),'l':str(location_id) if location_id else None}
      if subject_type: sql+=' AND a.subject_type=:st'; params['st']=subject_type.upper()
      if subject_id: sql+=' AND a.subject_id=:si'; params['si']=subject_id
      sql+=' ORDER BY a.created_at DESC'
      with engine.connect() as c: rows=c.execute(text(sql),params).mappings().all()
      out=[]
      for r in rows:
        d=dict(r); d['metadata']=json.loads(d.pop('metadata_json') or '{}'); out.append(d)
      return {'attachments':out}

    @app.post('/v90bc/attachments/{attachment_id}/deactivate')
    def deactivate_attachment(attachment_id: UUID, request: Request):
      user=authenticate(request)
      if 'evidence.write' not in permissions_for_user(engine,user.user_id): raise HTTPException(403,'permission denied')
      with engine.begin() as c:
        a=c.execute(text('SELECT * FROM evidence_attachments WHERE attachment_id=:a'),{'a':str(attachment_id)}).mappings().first()
        if not a: raise HTTPException(404,'attachment not found')
        try: assert_entity_location_allowed(engine,user.user_id,str(a['entity_id']),str(a['location_id']) if a['location_id'] else None)
        except PermissionError as exc: raise HTTPException(403,str(exc)) from exc
        c.execute(text('UPDATE evidence_attachments SET active=0 WHERE attachment_id=:a'),{'a':str(attachment_id)})
        c.execute(text("INSERT INTO evidence_events(event_id,attachment_id,event_type,event_payload_json,actor_id) VALUES(:i,:a,'DEACTIVATED','{}',:u)"),{'i':str(uuid4()),'a':str(attachment_id),'u':user.user_id})
      return {'attachment_id':str(attachment_id),'status':'INACTIVE'}

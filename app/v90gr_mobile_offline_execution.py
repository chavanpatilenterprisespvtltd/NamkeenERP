from __future__ import annotations
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed

def _now(): return datetime.now(timezone.utc).isoformat()
def _user(engine, request, entity_id, location_id, write=False):
    u=authenticate(request); p='mobile.execution.write' if write else 'mobile.execution.view'
    if p not in permissions_for_user(engine,u.user_id): raise HTTPException(403,'permission denied')
    try: assert_entity_location_allowed(engine,u.user_id,str(entity_id),str(location_id) if location_id else None)
    except PermissionError as exc: raise HTTPException(403,str(exc)) from exc
    return u

def ensure_v90gr_schema(engine):
    stmts=[
    """CREATE TABLE IF NOT EXISTS mobile_execution_sessions (session_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,location_id TEXT NULL,device_id TEXT NOT NULL,worker_user_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',started_at TEXT NOT NULL,ended_at TEXT NULL,last_sequence INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS mobile_execution_events (event_id TEXT PRIMARY KEY,session_id TEXT NOT NULL,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,location_id TEXT NULL,device_id TEXT NOT NULL,sequence_no INTEGER NOT NULL,event_type TEXT NOT NULL,reference_type TEXT NULL,reference_id TEXT NULL,payload_json TEXT NOT NULL,client_event_id TEXT NOT NULL,received_at TEXT NOT NULL,UNIQUE(device_id,client_event_id),UNIQUE(session_id,sequence_no))""",
    """CREATE TABLE IF NOT EXISTS mobile_execution_exceptions (exception_id TEXT PRIMARY KEY,event_id TEXT NOT NULL,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,location_id TEXT NULL,exception_code TEXT NOT NULL,message TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',created_at TEXT NOT NULL,resolved_at TEXT NULL,resolved_by TEXT NULL)""",
    "CREATE INDEX IF NOT EXISTS ix_mobile_exec_session_scope ON mobile_execution_sessions(entity_id,location_id,status)",
    "CREATE INDEX IF NOT EXISTS ix_mobile_exec_events_session ON mobile_execution_events(session_id,sequence_no)",
    "CREATE INDEX IF NOT EXISTS ix_mobile_exec_exceptions_scope ON mobile_execution_exceptions(entity_id,location_id,status)"]
    with engine.begin() as c:
        for s in stmts: c.execute(text(s))
        for p,n in [('mobile.execution.view','View mobile execution sessions/events'),('mobile.execution.write','Record mobile execution events and exceptions')]:
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"),{'p':p,'n':n})
        for r in ('manager','super_admin','operator','production','quality','warehouse','dispatch','salesperson','mis'):
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'mobile.execution.view') ON CONFLICT(role_id,permission_id) DO NOTHING"),{'r':r})
        for r in ('manager','super_admin','operator','production','quality','warehouse','dispatch','salesperson'):
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'mobile.execution.write') ON CONFLICT(role_id,permission_id) DO NOTHING"),{'r':r})
class SessionIn(BaseModel):
    organization_id: UUID; entity_id: UUID; location_id: UUID|None=None; device_id: UUID
class EventIn(BaseModel):
    organization_id: UUID; entity_id: UUID; location_id: UUID|None=None; device_id: UUID; session_id: UUID
    sequence_no: int=Field(ge=1); event_type: str=Field(min_length=2,max_length=60); reference_type: str|None=None; reference_id: UUID|None=None
    payload: dict={}; client_event_id: str=Field(min_length=2,max_length=120)
def register_v90gr_routes(app:FastAPI,engine):
    ensure_v90gr_schema(engine)
    @app.get('/ui/mobile-offline-execution')
    def ui(): return FileResponse('web/mobile-offline-execution.html')
    @app.post('/v90gr/mobile/sessions')
    def start(body:SessionIn,request:Request):
        u=_user(engine,request,body.entity_id,body.location_id,True); sid=str(uuid4())
        with engine.begin() as c: c.execute(text("INSERT INTO mobile_execution_sessions(session_id,organization_id,entity_id,location_id,device_id,worker_user_id,started_at) VALUES(:s,:o,:e,:l,:d,:u,:t)"),{'s':sid,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id) if body.location_id else None,'d':str(body.device_id),'u':u.user_id,'t':_now()})
        return {'session_id':sid,'status':'OPEN'}
    @app.post('/v90gr/mobile/events')
    def event(body:EventIn,request:Request):
        u=_user(engine,request,body.entity_id,body.location_id,True)
        with engine.begin() as c:
            sess=c.execute(text('SELECT * FROM mobile_execution_sessions WHERE session_id=:s AND device_id=:d AND status=\'OPEN\''),{'s':str(body.session_id),'d':str(body.device_id)}).mappings().first()
            if not sess: raise HTTPException(404,'open mobile session not found')
            if str(sess['entity_id'])!=str(body.entity_id): raise HTTPException(403,'session scope mismatch')
            dup=c.execute(text('SELECT event_id FROM mobile_execution_events WHERE device_id=:d AND client_event_id=:c'),{'d':str(body.device_id),'c':body.client_event_id}).first()
            if dup: return {'event_id':dup[0],'status':'ACCEPTED','idempotent':True}
            expected=int(sess['last_sequence'])+1
            if body.sequence_no!=expected:
                eid=str(uuid4()); code='SEQUENCE_GAP' if body.sequence_no>expected else 'SEQUENCE_REPLAY'
                c.execute(text("INSERT INTO mobile_execution_exceptions(exception_id,event_id,organization_id,entity_id,location_id,exception_code,message,created_at) VALUES(:x,:e,:o,:en,:l,:c,:m,:t)"),{'x':str(uuid4()),'e':eid,'o':str(body.organization_id),'en':str(body.entity_id),'l':str(body.location_id) if body.location_id else None,'c':code,'m':f'Expected sequence {expected}, received {body.sequence_no}','t':_now()})
                c.execute(text("INSERT INTO mobile_execution_events(event_id,session_id,organization_id,entity_id,location_id,device_id,sequence_no,event_type,reference_type,reference_id,payload_json,client_event_id,received_at) VALUES(:i,:s,:o,:e,:l,:d,:q,:t,:rt,:ri,:p,:c,:r)"),{'i':eid,'s':str(body.session_id),'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id) if body.location_id else None,'d':str(body.device_id),'q':body.sequence_no,'t':body.event_type.upper(),'rt':body.reference_type,'ri':str(body.reference_id) if body.reference_id else None,'p':json.dumps(body.payload),'c':body.client_event_id,'r':_now()})
                return {'event_id':eid,'status':'EXCEPTION','exception_code':code,'expected_sequence':expected}
            eid=str(uuid4()); c.execute(text("INSERT INTO mobile_execution_events(event_id,session_id,organization_id,entity_id,location_id,device_id,sequence_no,event_type,reference_type,reference_id,payload_json,client_event_id,received_at) VALUES(:i,:s,:o,:e,:l,:d,:q,:t,:rt,:ri,:p,:c,:r)"),{'i':eid,'s':str(body.session_id),'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id) if body.location_id else None,'d':str(body.device_id),'q':body.sequence_no,'t':body.event_type.upper(),'rt':body.reference_type,'ri':str(body.reference_id) if body.reference_id else None,'p':json.dumps(body.payload),'c':body.client_event_id,'r':_now()})
            c.execute(text('UPDATE mobile_execution_sessions SET last_sequence=:q WHERE session_id=:s'),{'q':body.sequence_no,'s':str(body.session_id)})
        return {'event_id':eid,'status':'ACCEPTED','sequence_no':body.sequence_no}
    @app.post('/v90gr/mobile/sessions/{session_id}/close')
    def close(session_id:UUID,request:Request):
        with engine.connect() as c: s=c.execute(text('SELECT entity_id,location_id,status FROM mobile_execution_sessions WHERE session_id=:s'),{'s':str(session_id)}).mappings().first()
        if not s: raise HTTPException(404,'session not found')
        u=_user(engine,request,s['entity_id'],s['location_id'],True)
        with engine.begin() as c: c.execute(text("UPDATE mobile_execution_sessions SET status='CLOSED',ended_at=:t WHERE session_id=:s AND status='OPEN'"),{'t':_now(),'s':str(session_id)})
        return {'session_id':str(session_id),'status':'CLOSED'}
    @app.get('/v90gr/mobile/exceptions')
    def exceptions(organization_id:UUID,entity_id:UUID,location_id:UUID|None=None,request:Request=None):
        _user(engine,request,entity_id,location_id,False)
        q='SELECT * FROM mobile_execution_exceptions WHERE organization_id=:o AND entity_id=:e'; p={'o':str(organization_id),'e':str(entity_id)}
        if location_id: q+=' AND (location_id=:l OR location_id IS NULL)'; p['l']=str(location_id)
        q+=' ORDER BY created_at DESC'
        with engine.connect() as c: rows=c.execute(text(q),p).mappings().all()
        return {'exceptions':[dict(r) for r in rows]}

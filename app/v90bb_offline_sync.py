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


def _now(): return datetime.now(timezone.utc).isoformat()

def _require(engine, request: Request, entity_id: str, location_id: str | None, write: bool):
    user = authenticate(request)
    needed = 'sync.write' if write else 'sync.view'
    if needed not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    try: assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc: raise HTTPException(403, str(exc)) from exc
    return user


def ensure_v90bb_schema(engine):
    stmts = [
      """CREATE TABLE IF NOT EXISTS sync_devices (
        device_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
        device_code TEXT NOT NULL, device_name TEXT NOT NULL, platform TEXT NOT NULL DEFAULT 'ANDROID',
        last_seen_at TEXT NULL, active INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id, device_code))""",
      """CREATE TABLE IF NOT EXISTS sync_operations (
        sync_operation_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
        device_id TEXT NOT NULL, client_operation_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL,
        operation_type TEXT NOT NULL, base_version INTEGER NOT NULL DEFAULT 0, payload_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING', conflict_code TEXT NULL, server_version INTEGER NULL,
        received_by TEXT NOT NULL, received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        resolved_at TEXT NULL, resolved_by TEXT NULL,
        UNIQUE(device_id, client_operation_id))""",
      """CREATE TABLE IF NOT EXISTS sync_conflicts (
        conflict_id TEXT PRIMARY KEY, sync_operation_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
        location_id TEXT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL,
        base_version INTEGER NOT NULL, server_version INTEGER NOT NULL, client_payload_json TEXT NOT NULL,
        server_payload_json TEXT NOT NULL, resolution TEXT NULL, resolved_by TEXT NULL, resolved_at TEXT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
      """CREATE TABLE IF NOT EXISTS sync_aggregate_versions (
        organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 0, payload_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_by TEXT NOT NULL, PRIMARY KEY(organization_id, entity_id, aggregate_type, aggregate_id))""",
      """CREATE TABLE IF NOT EXISTS sync_pull_cursors (
        device_id TEXT PRIMARY KEY, cursor_at TEXT NULL, cursor_version INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
      "CREATE INDEX IF NOT EXISTS ix_sync_ops_device_status ON sync_operations(device_id,status,received_at)",
      "CREATE INDEX IF NOT EXISTS ix_sync_conflicts_scope ON sync_conflicts(entity_id,location_id,resolution,created_at)",
    ]
    with engine.begin() as c:
      for s in stmts: c.execute(text(s))
      perms={'sync.view':'View offline sync queue, conflicts and device state','sync.write':'Submit offline sync operations and resolve conflicts'}
      for p,n in perms.items(): c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"),{'p':p,'n':n})
      for r in ('manager','super_admin','operator','production','quality','warehouse','dispatch','salesperson','mis'):
        c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'sync.view') ON CONFLICT(role_id,permission_id) DO NOTHING"),{'r':r})
      for r in ('manager','super_admin','operator','production','quality','warehouse','dispatch','salesperson'):
        c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'sync.write') ON CONFLICT(role_id,permission_id) DO NOTHING"),{'r':r})

class DeviceIn(BaseModel):
    organization_id: UUID; entity_id: UUID; location_id: UUID|None=None
    device_code: str=Field(min_length=2,max_length=100); device_name: str=Field(min_length=2,max_length=160); platform: str='ANDROID'

class OperationIn(BaseModel):
    organization_id: UUID; entity_id: UUID; location_id: UUID|None=None; device_id: UUID
    client_operation_id: str=Field(min_length=2,max_length=120); aggregate_type: str=Field(min_length=2,max_length=80)
    aggregate_id: UUID; operation_type: str=Field(min_length=2,max_length=40); base_version: int=Field(default=0, ge=0)
    payload: dict

class ResolveIn(BaseModel):
    resolution: str=Field(min_length=3,max_length=30)
    merged_payload: dict|None=None


def _json(v): return json.loads(v) if isinstance(v,str) else (v or {})

def register_v90bb_routes(app: FastAPI, engine):
    ensure_v90bb_schema(engine)
    @app.post('/v90bb/devices/register')
    def register_device(body: DeviceIn, request: Request):
      user=_require(engine,request,str(body.entity_id),str(body.location_id),True)
      did=str(uuid4())
      with engine.begin() as c:
        dup=c.execute(text('SELECT device_id FROM sync_devices WHERE organization_id=:o AND device_code=:d'),{'o':str(body.organization_id),'d':body.device_code.strip()}).first()
        if dup: raise HTTPException(409,'device already registered')
        c.execute(text("INSERT INTO sync_devices(device_id,organization_id,entity_id,location_id,device_code,device_name,platform,created_by,last_seen_at) VALUES(:i,:o,:e,:l,:c,:n,:p,:u,:t)"),{'i':did,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id) if body.location_id else None,'c':body.device_code.strip(),'n':body.device_name.strip(),'p':body.platform.upper(),'u':user.user_id,'t':_now()})
        c.execute(text("INSERT INTO sync_pull_cursors(device_id) VALUES(:i) ON CONFLICT(device_id) DO NOTHING"),{'i':did})
      return {'device_id':did,'status':'ACTIVE'}

    @app.post('/v90bb/sync/push')
    def push_operation(body: OperationIn, request: Request):
      user=_require(engine,request,str(body.entity_id),str(body.location_id),True)
      with engine.begin() as c:
        dev=c.execute(text('SELECT * FROM sync_devices WHERE device_id=:d AND organization_id=:o AND active=1'),{'d':str(body.device_id),'o':str(body.organization_id)}).mappings().first()
        if not dev: raise HTTPException(404,'device not found')
        if str(dev['entity_id'])!=str(body.entity_id) or (dev['location_id'] and str(dev['location_id'])!=str(body.location_id)): raise HTTPException(403,'device scope mismatch')
        existing=c.execute(text('SELECT * FROM sync_operations WHERE device_id=:d AND client_operation_id=:c'),{'d':str(body.device_id),'c':body.client_operation_id}).mappings().first()
        if existing: return {'sync_operation_id':existing['sync_operation_id'],'status':existing['status'],'idempotent':True,'conflict_code':existing['conflict_code']}
        agg=c.execute(text('SELECT * FROM sync_aggregate_versions WHERE organization_id=:o AND entity_id=:e AND aggregate_type=:t AND aggregate_id=:a'),{'o':str(body.organization_id),'e':str(body.entity_id),'t':body.aggregate_type.upper(),'a':str(body.aggregate_id)}).mappings().first()
        current_ver=int(agg['version']) if agg else 0; server_payload=_json(agg['payload_json']) if agg else {}
        sid=str(uuid4()); status='APPLIED'; conflict=None; new_ver=current_ver
        if body.base_version != current_ver:
          status='CONFLICT'; conflict='STALE_BASE_VERSION'
          c.execute(text("INSERT INTO sync_conflicts(conflict_id,sync_operation_id,organization_id,entity_id,location_id,aggregate_type,aggregate_id,base_version,server_version,client_payload_json,server_payload_json) VALUES(:i,:s,:o,:e,:l,:t,:a,:bv,:sv,:cp,:sp)"),{'i':str(uuid4()),'s':sid,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id) if body.location_id else None,'t':body.aggregate_type.upper(),'a':str(body.aggregate_id),'bv':body.base_version,'sv':current_ver,'cp':json.dumps(body.payload),'sp':json.dumps(server_payload)})
        else:
          new_ver=current_ver+1
          c.execute(text("INSERT INTO sync_aggregate_versions(organization_id,entity_id,aggregate_type,aggregate_id,version,payload_json,updated_by,updated_at) VALUES(:o,:e,:t,:a,:v,:p,:u,:tme) ON CONFLICT(organization_id,entity_id,aggregate_type,aggregate_id) DO UPDATE SET version=excluded.version,payload_json=excluded.payload_json,updated_by=excluded.updated_by,updated_at=excluded.updated_at"),{'o':str(body.organization_id),'e':str(body.entity_id),'t':body.aggregate_type.upper(),'a':str(body.aggregate_id),'v':new_ver,'p':json.dumps(body.payload),'u':user.user_id,'tme':_now()})
        c.execute(text("INSERT INTO sync_operations(sync_operation_id,organization_id,entity_id,location_id,device_id,client_operation_id,aggregate_type,aggregate_id,operation_type,base_version,payload_json,status,conflict_code,server_version,received_by) VALUES(:s,:o,:e,:l,:d,:c,:t,:a,:ot,:bv,:p,:st,:cc,:sv,:u)"),{'s':sid,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id) if body.location_id else None,'d':str(body.device_id),'c':body.client_operation_id,'t':body.aggregate_type.upper(),'a':str(body.aggregate_id),'ot':body.operation_type.upper(),'bv':body.base_version,'p':json.dumps(body.payload),'st':status,'cc':conflict,'sv':new_ver,'u':user.user_id})
        c.execute(text('UPDATE sync_devices SET last_seen_at=CURRENT_TIMESTAMP WHERE device_id=:d'),{'d':str(body.device_id)})
      return {'sync_operation_id':sid,'status':status,'server_version':new_ver,'conflict_code':conflict}

    @app.get('/v90bb/sync/conflicts')
    def list_conflicts(organization_id:UUID,entity_id:UUID,location_id:UUID|None=None,request:Request=None):
      _require(engine,request,str(entity_id),str(location_id) if location_id else None,False)
      q='SELECT * FROM sync_conflicts WHERE organization_id=:o AND entity_id=:e AND (resolution IS NULL OR resolution NOT IN (\'APPLIED\',\'DISCARDED\'))'
      params={'o':str(organization_id),'e':str(entity_id)}
      if location_id: q += ' AND (location_id=:l OR location_id IS NULL)'; params['l']=str(location_id)
      q+=' ORDER BY created_at'
      with engine.connect() as c: rows=c.execute(text(q),params).mappings().all()
      return {'conflicts':[dict(r) for r in rows]}

    @app.post('/v90bb/sync/conflicts/{conflict_id}/resolve')
    def resolve_conflict(conflict_id:UUID,body:ResolveIn,request:Request):
      user=authenticate(request)
      if 'sync.write' not in permissions_for_user(engine,user.user_id): raise HTTPException(403,'permission denied')
      with engine.begin() as c:
        row=c.execute(text('SELECT * FROM sync_conflicts WHERE conflict_id=:i'),{'i':str(conflict_id)}).mappings().first()
        if not row: raise HTTPException(404,'conflict not found')
        try: assert_entity_location_allowed(engine,user.user_id,str(row['entity_id']),str(row['location_id']) if row['location_id'] else None)
        except PermissionError as exc: raise HTTPException(403,str(exc)) from exc
        res=body.resolution.upper()
        if res not in ('APPLIED','DISCARDED'): raise HTTPException(422,'resolution must be APPLIED or DISCARDED')
        op=c.execute(text('SELECT * FROM sync_operations WHERE sync_operation_id=:s'),{'s':row['sync_operation_id']}).mappings().first()
        if not op or op['status']!='CONFLICT': raise HTTPException(409,'conflict already resolved')
        if res=='APPLIED':
          payload=body.merged_payload if body.merged_payload is not None else _json(row['client_payload_json'])
          c.execute(text("INSERT INTO sync_aggregate_versions(organization_id,entity_id,aggregate_type,aggregate_id,version,payload_json,updated_by,updated_at) VALUES(:o,:e,:t,:a,:v,:p,:u,:tme) ON CONFLICT(organization_id,entity_id,aggregate_type,aggregate_id) DO UPDATE SET version=:v,payload_json=:p,updated_by=:u,updated_at=:tme"),{'o':row['organization_id'],'e':row['entity_id'],'t':row['aggregate_type'],'a':row['aggregate_id'],'v':int(row['server_version'])+1,'p':json.dumps(payload),'u':user.user_id,'tme':_now()})
        c.execute(text("UPDATE sync_conflicts SET resolution=:r,resolved_by=:u,resolved_at=:t WHERE conflict_id=:i"),{'r':res,'u':user.user_id,'t':_now(),'i':str(conflict_id)})
        c.execute(text("UPDATE sync_operations SET status=:s,resolved_by=:u,resolved_at=:t WHERE sync_operation_id=:i"),{'s':res,'u':user.user_id,'t':_now(),'i':row['sync_operation_id']})
      return {'conflict_id':str(conflict_id),'status':res}

    @app.get('/v90bb/sync/pull')
    def pull(device_id:UUID,after_version:int=0,limit:int=100,request:Request=None):
      user=authenticate(request)
      if 'sync.view' not in permissions_for_user(engine,user.user_id): raise HTTPException(403,'permission denied')
      with engine.connect() as c:
        dev=c.execute(text('SELECT * FROM sync_devices WHERE device_id=:d AND active=1'),{'d':str(device_id)}).mappings().first()
        if not dev: raise HTTPException(404,'device not found')
        try: assert_entity_location_allowed(engine,user.user_id,str(dev['entity_id']),str(dev['location_id']) if dev['location_id'] else None)
        except PermissionError as exc: raise HTTPException(403,str(exc)) from exc
        rows=c.execute(text('SELECT * FROM sync_operations WHERE entity_id=:e AND status=\'APPLIED\' AND server_version>:v ORDER BY server_version LIMIT :lim'),{'e':dev['entity_id'],'v':after_version,'lim':max(1,min(limit,500))}).mappings().all()
      items=[dict(r) for r in rows]
      for x in items: x['payload_json']=_json(x['payload_json'])
      return {'device_id':str(device_id),'after_version':after_version,'items':items,'next_version':max([after_version]+[int(x['server_version']) for x in items])}

from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require(engine, request: Request, entity_id: UUID, location_id: UUID, write: bool=True):
    user = authenticate(request)
    perms = permissions_for_user(engine, user.user_id)
    needed = 'production.edit' if write else 'production.view'
    if needed not in perms:
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, str(entity_id), str(location_id))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def ensure_v90s_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS production_process_log (
            process_log_id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            production_order_id TEXT NOT NULL,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            operator_user_id TEXT NULL,
            machine_id TEXT NULL,
            started_at TEXT NULL,
            ended_at TEXT NULL,
            temperature_c NUMERIC NULL,
            frying_time_sec NUMERIC NULL,
            process_value NUMERIC NULL,
            process_uom TEXT NULL,
            status TEXT NOT NULL DEFAULT 'RECORDED',
            deviation_flag INTEGER NOT NULL DEFAULT 0,
            deviation_reason TEXT NULL,
            notes TEXT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_process_log_batch ON production_process_log(batch_id, stage, created_at)",
        """CREATE TABLE IF NOT EXISTS production_process_measurement (
            measurement_id TEXT PRIMARY KEY,
            process_log_id TEXT NOT NULL,
            parameter_code TEXT NOT NULL,
            parameter_name TEXT NOT NULL,
            value_num NUMERIC NULL,
            value_text TEXT NULL,
            uom TEXT NULL,
            target_min NUMERIC NULL,
            target_max NUMERIC NULL,
            pass_flag INTEGER NULL,
            measured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_process_measurement_log ON production_process_measurement(process_log_id, parameter_code)",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))


class ProcessLogIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    batch_id: UUID
    production_order_id: UUID
    stage: str = Field(min_length=1, max_length=80)
    operator_user_id: str | None = None
    machine_id: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    temperature_c: float | None = None
    frying_time_sec: float | None = Field(default=None, ge=0)
    process_value: float | None = None
    process_uom: str | None = None
    deviation_reason: str | None = None
    notes: str | None = None


class MeasurementIn(BaseModel):
    parameter_code: str = Field(min_length=1, max_length=60)
    parameter_name: str = Field(min_length=1, max_length=120)
    value_num: float | None = None
    value_text: str | None = None
    uom: str | None = None
    target_min: float | None = None
    target_max: float | None = None
    pass_flag: bool | None = None


class MeasurementsIn(BaseModel):
    measurements: list[MeasurementIn] = Field(min_length=1)


def register_v90s_routes(app: FastAPI, engine) -> None:
    ensure_v90s_schema(engine)

    @app.post('/v90s/batches/{batch_id}/process-logs')
    def create_process_log(batch_id: UUID, body: ProcessLogIn, request: Request):
        user = _require(engine, request, body.entity_id, body.location_id, True)
        if str(batch_id) != str(body.batch_id):
            raise HTTPException(422, 'path batch_id does not match payload')
        with engine.connect() as conn:
            batch = conn.execute(text('SELECT * FROM production_batch WHERE batch_id=:b'), {'b':str(batch_id)}).mappings().first()
            if not batch:
                raise HTTPException(404, 'batch not found')
            if str(batch['production_order_id']) != str(body.production_order_id):
                raise HTTPException(422, 'production order mismatch')
            if str(batch['entity_id']) != str(body.entity_id) or str(batch['location_id']) != str(body.location_id):
                raise HTTPException(422, 'batch scope mismatch')
            if batch['status'] not in ('OPEN','RUNNING'):
                raise HTTPException(409, 'process log allowed only for open/running batch')
        start = body.started_at or _now()
        deviation = bool(body.deviation_reason)
        log_id = uuid4()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO production_process_log(
                process_log_id,batch_id,production_order_id,organization_id,entity_id,location_id,stage,
                operator_user_id,machine_id,started_at,ended_at,temperature_c,frying_time_sec,process_value,
                process_uom,status,deviation_flag,deviation_reason,notes,created_by)
                VALUES(:id,:b,:o,:org,:e,:l,:stage,:op,:m,:s,:en,:temp,:ftime,:pv,:pu,'RECORDED',:dev,:reason,:notes,:by)"""), {
                'id':str(log_id),'b':str(body.batch_id),'o':str(body.production_order_id),'org':str(body.organization_id),
                'e':str(body.entity_id),'l':str(body.location_id),'stage':body.stage,'op':body.operator_user_id,'m':body.machine_id,
                's':start,'en':body.ended_at,'temp':body.temperature_c,'ftime':body.frying_time_sec,'pv':body.process_value,
                'pu':body.process_uom,'dev':1 if deviation else 0,'reason':body.deviation_reason,'notes':body.notes,'by':str(user.user_id)
            })
        return {'process_log_id':str(log_id),'batch_id':str(batch_id),'status':'RECORDED','deviation_flag':deviation}

    @app.post('/v90s/process-logs/{process_log_id}/measurements')
    def add_measurements(process_log_id: UUID, body: MeasurementsIn, request: Request):
        user = authenticate(request)
        if 'production.edit' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403,'permission denied')
        with engine.connect() as conn:
            log = conn.execute(text('SELECT entity_id,location_id FROM production_process_log WHERE process_log_id=:p'), {'p':str(process_log_id)}).mappings().first()
            if not log:
                raise HTTPException(404,'process log not found')
        try:
            assert_entity_location_allowed(engine, user.user_id, str(log['entity_id']), str(log['location_id']))
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        ids=[]
        with engine.begin() as conn:
            for m in body.measurements:
                mid=uuid4()
                conn.execute(text("""INSERT INTO production_process_measurement(
                    measurement_id,process_log_id,parameter_code,parameter_name,value_num,value_text,uom,target_min,target_max,pass_flag)
                    VALUES(:id,:log,:code,:name,:vn,:vt,:uom,:min,:max,:pass)"""), {
                        'id':str(mid),'log':str(process_log_id),'code':m.parameter_code,'name':m.parameter_name,
                        'vn':m.value_num,'vt':m.value_text,'uom':m.uom,'min':m.target_min,'max':m.target_max,
                        'pass':None if m.pass_flag is None else (1 if m.pass_flag else 0)})
                ids.append(str(mid))
        return {'process_log_id':str(process_log_id),'measurement_count':len(ids),'measurement_ids':ids}

    @app.get('/v90s/batches/{batch_id}/process-logs')
    def list_process_logs(batch_id: UUID, request: Request):
        user = authenticate(request)
        if 'production.view' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403,'permission denied')
        with engine.connect() as conn:
            batch=conn.execute(text('SELECT entity_id,location_id FROM production_batch WHERE batch_id=:b'),{'b':str(batch_id)}).mappings().first()
            if not batch: raise HTTPException(404,'batch not found')
            try: assert_entity_location_allowed(engine,user.user_id,str(batch['entity_id']),str(batch['location_id']))
            except PermissionError as exc: raise HTTPException(403,str(exc)) from exc
            rows=conn.execute(text('SELECT * FROM production_process_log WHERE batch_id=:b ORDER BY created_at,process_log_id'),{'b':str(batch_id)}).mappings().all()
        return {'batch_id':str(batch_id),'process_logs':[dict(x) for x in rows]}

    @app.get('/v90s/process-logs/{process_log_id}')
    def get_process_log(process_log_id: UUID, request: Request):
        user = authenticate(request)
        if 'production.view' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403,'permission denied')
        with engine.connect() as conn:
            row=conn.execute(text('SELECT * FROM production_process_log WHERE process_log_id=:p'),{'p':str(process_log_id)}).mappings().first()
            if not row: raise HTTPException(404,'process log not found')
            try: assert_entity_location_allowed(engine,user.user_id,str(row['entity_id']),str(row['location_id']))
            except PermissionError as exc: raise HTTPException(403,str(exc)) from exc
            ms=conn.execute(text('SELECT * FROM production_process_measurement WHERE process_log_id=:p ORDER BY measured_at,measurement_id'),{'p':str(process_log_id)}).mappings().all()
        return {'process_log':dict(row),'measurements':[dict(x) for x in ms]}

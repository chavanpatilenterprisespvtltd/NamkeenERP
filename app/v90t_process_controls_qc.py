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


def _require(engine, request: Request, entity_id: UUID, location_id: UUID, write: bool = True):
    user = authenticate(request)
    needed = 'production.edit' if write else 'production.view'
    if needed not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, str(entity_id), str(location_id))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def ensure_v90t_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS production_process_control (
            control_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            parameter_code TEXT NOT NULL,
            parameter_name TEXT NOT NULL,
            uom TEXT NULL,
            target_min NUMERIC NULL,
            target_max NUMERIC NULL,
            severity TEXT NOT NULL DEFAULT 'WARNING',
            action_on_breach TEXT NOT NULL DEFAULT 'FLAG',
            active INTEGER NOT NULL DEFAULT 1,
            effective_from TEXT NULL,
            effective_to TEXT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_process_control_scope ON production_process_control(entity_id, location_id, stage, parameter_code, effective_from)",
        "CREATE INDEX IF NOT EXISTS ix_process_control_lookup ON production_process_control(entity_id, location_id, stage, parameter_code, active)",
        """CREATE TABLE IF NOT EXISTS production_process_qc_decision (
            decision_id TEXT PRIMARY KEY,
            process_log_id TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            reason TEXT NULL,
            source TEXT NOT NULL DEFAULT 'PROCESS_QC',
            decided_by TEXT NOT NULL,
            decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_process_qc_decision_batch ON production_process_qc_decision(batch_id, decided_at)",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))


class ControlIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    stage: str = Field(min_length=1, max_length=80)
    parameter_code: str = Field(min_length=1, max_length=60)
    parameter_name: str = Field(min_length=1, max_length=120)
    uom: str | None = None
    target_min: float | None = None
    target_max: float | None = None
    severity: str = Field(default='WARNING', min_length=1, max_length=20)
    action_on_breach: str = Field(default='FLAG', min_length=1, max_length=30)
    active: bool = True
    effective_from: str | None = None
    effective_to: str | None = None


class DecisionIn(BaseModel):
    decision: str = Field(min_length=2, max_length=20)
    reason: str | None = None


def _control_status(value: float | None, target_min: float | None, target_max: float | None) -> bool | None:
    if value is None:
        return None
    if target_min is not None and value < target_min:
        return False
    if target_max is not None and value > target_max:
        return False
    return True


def register_v90t_routes(app: FastAPI, engine) -> None:
    ensure_v90t_schema(engine)

    @app.post('/v90t/process-controls')
    def create_control(body: ControlIn, request: Request):
        user = _require(engine, request, body.entity_id, body.location_id, True)
        if body.target_min is not None and body.target_max is not None and body.target_min > body.target_max:
            raise HTTPException(422, 'target_min cannot exceed target_max')
        cid = uuid4()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO production_process_control(
                control_id,organization_id,entity_id,location_id,stage,parameter_code,parameter_name,uom,
                target_min,target_max,severity,action_on_breach,active,effective_from,effective_to,created_by)
                VALUES(:id,:org,:e,:l,:stage,:code,:name,:uom,:min,:max,:sev,:action,:active,:ef,:et,:by)"""), {
                'id':str(cid),'org':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),
                'stage':body.stage,'code':body.parameter_code,'name':body.parameter_name,'uom':body.uom,
                'min':body.target_min,'max':body.target_max,'sev':body.severity.upper(),'action':body.action_on_breach.upper(),
                'active':1 if body.active else 0,'ef':body.effective_from,'et':body.effective_to,'by':str(user.user_id)
            })
        return {'control_id':str(cid),'status':'CREATED'}

    @app.get('/v90t/process-controls')
    def list_controls(request: Request, entity_id: UUID, location_id: UUID, stage: str | None = None):
        _require(engine, request, entity_id, location_id, False)
        sql = 'SELECT * FROM production_process_control WHERE entity_id=:e AND location_id=:l'
        params = {'e':str(entity_id),'l':str(location_id)}
        if stage:
            sql += ' AND stage=:stage'; params['stage'] = stage
        sql += ' ORDER BY stage, parameter_code, created_at'
        with engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        return {'controls':[dict(r) for r in rows]}

    @app.post('/v90t/process-logs/{process_log_id}/evaluate')
    def evaluate_process_log(process_log_id: UUID, request: Request):
        user = authenticate(request)
        if 'production.edit' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.connect() as conn:
            log = conn.execute(text('SELECT * FROM production_process_log WHERE process_log_id=:p'), {'p':str(process_log_id)}).mappings().first()
            if not log:
                raise HTTPException(404, 'process log not found')
            try:
                assert_entity_location_allowed(engine, user.user_id, str(log['entity_id']), str(log['location_id']))
            except PermissionError as exc:
                raise HTTPException(403, str(exc)) from exc
            measurements = conn.execute(text('SELECT * FROM production_process_measurement WHERE process_log_id=:p ORDER BY measured_at,measurement_id'), {'p':str(process_log_id)}).mappings().all()
            controls = conn.execute(text("""SELECT * FROM production_process_control
                WHERE entity_id=:e AND location_id=:l AND stage=:stage AND active=1
                ORDER BY parameter_code, effective_from DESC"""), {'e':str(log['entity_id']), 'l':str(log['location_id']), 'stage':str(log['stage'])}).mappings().all()
        by_code = {}
        for c in controls:
            by_code.setdefault(c['parameter_code'], c)
        results = []
        breach = False
        hold = False
        for m in measurements:
            c = by_code.get(m['parameter_code'])
            if not c:
                continue
            ok = _control_status(float(m['value_num']) if m['value_num'] is not None else None, float(c['target_min']) if c['target_min'] is not None else None, float(c['target_max']) if c['target_max'] is not None else None)
            action = str(c['action_on_breach']).upper()
            if ok is False:
                breach = True
                if action in ('HOLD','REJECT'):
                    hold = True
            results.append({'measurement_id':str(m['measurement_id']),'parameter_code':m['parameter_code'],'within_control':ok,'action_on_breach':action,'severity':c['severity']})
        decision = 'HOLD' if hold else ('PASS' if results and all(r['within_control'] is not False for r in results) else ('WARNING' if breach else 'PASS'))
        return {'process_log_id':str(process_log_id),'decision':decision,'breach':breach,'hold':hold,'results':results}

    @app.post('/v90t/process-logs/{process_log_id}/qc-decision')
    def qc_decision(process_log_id: UUID, body: DecisionIn, request: Request):
        user = authenticate(request)
        if 'production.edit' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        decision = body.decision.upper()
        if decision not in ('PASS','HOLD','REJECT','RELEASE'):
            raise HTTPException(422, 'unsupported QC decision')
        with engine.connect() as conn:
            log = conn.execute(text('SELECT * FROM production_process_log WHERE process_log_id=:p'), {'p':str(process_log_id)}).mappings().first()
            if not log:
                raise HTTPException(404, 'process log not found')
            try:
                assert_entity_location_allowed(engine, user.user_id, str(log['entity_id']), str(log['location_id']))
            except PermissionError as exc:
                raise HTTPException(403, str(exc)) from exc
        if decision in ('PASS','RELEASE'):
            ev = app.openapi  # keep branch explicit for readability
        did = uuid4()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO production_process_qc_decision(
                decision_id,process_log_id,batch_id,organization_id,entity_id,location_id,decision,reason,decided_by)
                VALUES(:id,:p,:b,:o,:e,:l,:d,:r,:by)"""), {
                'id':str(did),'p':str(process_log_id),'b':str(log['batch_id']),'o':str(log['organization_id']),
                'e':str(log['entity_id']),'l':str(log['location_id']),'d':decision,'r':body.reason,'by':str(user.user_id)
            })
            conn.execute(text('UPDATE production_process_log SET status=:s WHERE process_log_id=:p'), {'s':decision,'p':str(process_log_id)})
        return {'decision_id':str(did),'process_log_id':str(process_log_id),'decision':decision}

    @app.get('/v90t/batches/{batch_id}/qc-status')
    def batch_qc_status(batch_id: UUID, request: Request):
        user = authenticate(request)
        if 'production.view' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.connect() as conn:
            batch = conn.execute(text('SELECT entity_id,location_id FROM production_batch WHERE batch_id=:b'), {'b':str(batch_id)}).mappings().first()
            if not batch:
                raise HTTPException(404, 'batch not found')
            try:
                assert_entity_location_allowed(engine, user.user_id, str(batch['entity_id']), str(batch['location_id']))
            except PermissionError as exc:
                raise HTTPException(403, str(exc)) from exc
            rows = conn.execute(text('SELECT * FROM production_process_qc_decision WHERE batch_id=:b ORDER BY decided_at,decision_id'), {'b':str(batch_id)}).mappings().all()
        latest = rows[-1] if rows else None
        return {'batch_id':str(batch_id),'latest_decision':dict(latest) if latest else None,'decisions':[dict(r) for r in rows]}

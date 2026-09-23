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


def ensure_production_planning_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS production_plan (
            plan_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL, plan_no TEXT NOT NULL, period_start TEXT NOT NULL,
            period_end TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT', source TEXT NULL,
            notes TEXT NULL, created_by TEXT NOT NULL, approved_by TEXT NULL,
            approved_at TEXT NULL, approval_reason TEXT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS production_plan_line (
            plan_line_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, line_no INTEGER NOT NULL,
            item_master_id TEXT NOT NULL, uom TEXT NOT NULL, planned_qty NUMERIC NOT NULL,
            priority INTEGER NOT NULL DEFAULT 1, due_date TEXT NULL, status TEXT NOT NULL DEFAULT 'PLANNED',
            notes TEXT NULL, FOREIGN KEY(plan_id) REFERENCES production_plan(plan_id)
        )""",
        """CREATE TABLE IF NOT EXISTS production_plan_requirement (
            requirement_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, plan_line_id TEXT NOT NULL,
            requirement_type TEXT NOT NULL, item_master_id TEXT NOT NULL, required_qty NUMERIC NOT NULL,
            uom TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', notes TEXT NULL,
            FOREIGN KEY(plan_id) REFERENCES production_plan(plan_id),
            FOREIGN KEY(plan_line_id) REFERENCES production_plan_line(plan_line_id)
        )""",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))


class PlanLineIn(BaseModel):
    item_master_id: UUID
    uom: str = Field(min_length=1)
    planned_qty: float = Field(gt=0)
    priority: int = Field(default=1, ge=1, le=9)
    due_date: str | None = None
    notes: str | None = None


class PlanIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    plan_no: str = Field(min_length=1)
    period_start: str
    period_end: str
    source: str | None = None
    notes: str | None = None
    lines: list[PlanLineIn] = Field(min_length=1)


class PlanDecisionIn(BaseModel):
    reason: str = ''


def _require(engine, request: Request, entity_id: UUID, location_id: UUID, write: bool, approve: bool = False):
    user = authenticate(request)
    perms = permissions_for_user(engine, user.user_id)
    needed = 'production.approve' if approve else ('production.edit' if write else 'production.view')
    if needed not in perms:
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, str(entity_id), str(location_id))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def _product_exists(engine, organization_id: UUID, entity_id: UUID, product_id: UUID):
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT master_id, entity_id, active FROM master_record
            WHERE replace(lower(organization_id),'-','')=replace(lower(:o),'-','')
              AND master_type='PRODUCT'
              AND replace(lower(master_id),'-','')=replace(lower(:p),'-','')
        """), {'o': str(organization_id), 'p': str(product_id)}).mappings().first()
    if not row or not row['active']:
        raise HTTPException(422, 'Referenced PRODUCT not found')
    if row['entity_id'] not in (None, str(entity_id), str(entity_id).replace('-', '')):
        raise HTTPException(422, 'Referenced PRODUCT is outside entity scope')


def register_v90o_routes(app: FastAPI, engine) -> None:
    ensure_production_planning_schema(engine)

    @app.get('/v90o/production-planning/overview')
    def overview(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID):
        _require(engine, request, entity_id, location_id, False)
        with engine.connect() as conn:
            counts = {
                'plans': conn.execute(text('SELECT COUNT(*) FROM production_plan WHERE organization_id=:o AND entity_id=:e'), {'o':str(organization_id),'e':str(entity_id)}).scalar_one(),
                'draft': conn.execute(text("SELECT COUNT(*) FROM production_plan WHERE organization_id=:o AND entity_id=:e AND status='DRAFT'"), {'o':str(organization_id),'e':str(entity_id)}).scalar_one(),
                'approved': conn.execute(text("SELECT COUNT(*) FROM production_plan WHERE organization_id=:o AND entity_id=:e AND status='APPROVED'"), {'o':str(organization_id),'e':str(entity_id)}).scalar_one(),
            }
        return {'organization_id':str(organization_id),'entity_id':str(entity_id),'location_id':str(location_id),'counts':counts}

    @app.post('/v90o/production-planning/plans')
    def create_plan(body: PlanIn, request: Request):
        user = _require(engine, request, body.entity_id, body.location_id, True)
        with engine.connect() as conn:
            if conn.execute(text('SELECT 1 FROM production_plan WHERE organization_id=:o AND plan_no=:n'), {'o':str(body.organization_id),'n':body.plan_no}).first():
                raise HTTPException(409, 'Production plan number already exists')
        if body.period_end < body.period_start:
            raise HTTPException(422, 'period_end must be on/after period_start')
        for line in body.lines:
            _product_exists(engine, body.organization_id, body.entity_id, line.item_master_id)
        plan_id = uuid4()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO production_plan
                (plan_id,organization_id,entity_id,location_id,plan_no,period_start,period_end,status,source,notes,created_by)
                VALUES(:id,:o,:e,:l,:n,:ps,:pe,'DRAFT',:s,:notes,:u)"""),
                {'id':str(plan_id),'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'n':body.plan_no,'ps':body.period_start,'pe':body.period_end,'s':body.source,'notes':body.notes,'u':str(user.user_id)})
            for i, line in enumerate(body.lines, 1):
                conn.execute(text("""INSERT INTO production_plan_line
                    (plan_line_id,plan_id,line_no,item_master_id,uom,planned_qty,priority,due_date,status,notes)
                    VALUES(:id,:p,:n,:m,:u,:q,:pr,:d,'PLANNED',:notes)"""),
                    {'id':str(uuid4()),'p':str(plan_id),'n':i,'m':str(line.item_master_id),'u':line.uom,'q':line.planned_qty,'pr':line.priority,'d':line.due_date,'notes':line.notes})
        return {'plan_id':str(plan_id),'status':'DRAFT'}

    @app.get('/v90o/production-planning/plans')
    def list_plans(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, status: str | None = None):
        _require(engine, request, entity_id, location_id, False)
        q = "SELECT plan_id,plan_no,period_start,period_end,status,source,created_by,created_at FROM production_plan WHERE organization_id=:o AND entity_id=:e AND location_id=:l"
        params={'o':str(organization_id),'e':str(entity_id),'l':str(location_id)}
        if status:
            q += ' AND status=:s'; params['s']=status
        q += ' ORDER BY created_at DESC'
        with engine.connect() as conn:
            rows = conn.execute(text(q),params).mappings().all()
        return {'items':[dict(r) for r in rows]}

    @app.get('/v90o/production-planning/plans/{plan_id}')
    def get_plan(plan_id: UUID, request: Request):
        user = authenticate(request)
        if 'production.view' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.connect() as conn:
            plan = conn.execute(text('SELECT * FROM production_plan WHERE plan_id=:p'), {'p':str(plan_id)}).mappings().first()
            if not plan:
                raise HTTPException(404,'production plan not found')
            lines = conn.execute(text('SELECT * FROM production_plan_line WHERE plan_id=:p ORDER BY line_no'), {'p':str(plan_id)}).mappings().all()
            reqs = conn.execute(text('SELECT * FROM production_plan_requirement WHERE plan_id=:p ORDER BY requirement_id'), {'p':str(plan_id)}).mappings().all()
        try:
            assert_entity_location_allowed(engine, user.user_id, str(plan['entity_id']), str(plan['location_id']))
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        return {'plan':dict(plan),'lines':[dict(x) for x in lines],'requirements':[dict(x) for x in reqs]}

    @app.post('/v90o/production-planning/plans/{plan_id}/submit')
    def submit_plan(plan_id: UUID, body: PlanDecisionIn, request: Request):
        user = authenticate(request)
        if 'production.edit' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403,'permission denied')
        with engine.begin() as conn:
            row = conn.execute(text('SELECT status,created_by FROM production_plan WHERE plan_id=:p'), {'p':str(plan_id)}).mappings().first()
            if not row: raise HTTPException(404,'production plan not found')
            if row['status'] != 'DRAFT': raise HTTPException(409,'only draft plans can be submitted')
            conn.execute(text("UPDATE production_plan SET status='PENDING_APPROVAL' WHERE plan_id=:p"), {'p':str(plan_id)})
        return {'plan_id':str(plan_id),'status':'PENDING_APPROVAL'}

    @app.post('/v90o/production-planning/plans/{plan_id}/approve')
    def approve_plan(plan_id: UUID, body: PlanDecisionIn, request: Request):
        user = authenticate(request)
        if 'production.approve' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403,'permission denied')
        with engine.begin() as conn:
            row = conn.execute(text('SELECT status,created_by FROM production_plan WHERE plan_id=:p'), {'p':str(plan_id)}).mappings().first()
            if not row: raise HTTPException(404,'production plan not found')
            if row['status'] != 'PENDING_APPROVAL': raise HTTPException(409,'only pending plans can be approved')
            if str(row['created_by']) == str(user.user_id): raise HTTPException(409,'self-approval is not allowed')
            conn.execute(text("UPDATE production_plan SET status='APPROVED', approved_by=:u, approved_at=CURRENT_TIMESTAMP, approval_reason=:r WHERE plan_id=:p"), {'u':str(user.user_id),'r':body.reason,'p':str(plan_id)})
        return {'plan_id':str(plan_id),'status':'APPROVED'}

    @app.post('/v90o/production-planning/plans/{plan_id}/requirements')
    def add_requirement(plan_id: UUID, payload: dict, request: Request):
        user = authenticate(request)
        if 'production.edit' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403,'permission denied')
        item_master_id = payload.get('item_master_id')
        qty = float(payload.get('required_qty',0))
        if not item_master_id or qty <= 0 or not payload.get('uom'):
            raise HTTPException(422,'item_master_id, required_qty and uom are required')
        with engine.begin() as conn:
            plan = conn.execute(text('SELECT entity_id,location_id,status FROM production_plan WHERE plan_id=:p'), {'p':str(plan_id)}).mappings().first()
            if not plan: raise HTTPException(404,'production plan not found')
            if plan['status'] not in ('DRAFT','PENDING_APPROVAL'): raise HTTPException(409,'requirements can only change before approval')
            try:
                assert_entity_location_allowed(engine, user.user_id, str(plan['entity_id']), str(plan['location_id']))
            except PermissionError as exc:
                raise HTTPException(403,str(exc)) from exc
            line_id = payload.get('plan_line_id')
            if not line_id:
                line_id = conn.execute(text('SELECT plan_line_id FROM production_plan_line WHERE plan_id=:p ORDER BY line_no LIMIT 1'), {'p':str(plan_id)}).scalar_one_or_none()
            if not line_id: raise HTTPException(422,'plan has no lines')
            req_id=uuid4()
            conn.execute(text("""INSERT INTO production_plan_requirement
                (requirement_id,plan_id,plan_line_id,requirement_type,item_master_id,required_qty,uom,status,notes)
                VALUES(:id,:p,:pl,:t,:m,:q,:u,'OPEN',:n)"""), {'id':str(req_id),'p':str(plan_id),'pl':str(line_id),'t':payload.get('requirement_type','RAW_MATERIAL'),'m':str(item_master_id),'q':qty,'u':payload['uom'],'n':payload.get('notes')})
        return {'requirement_id':str(req_id),'status':'OPEN'}

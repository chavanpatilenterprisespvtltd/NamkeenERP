from __future__ import annotations
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


def ensure_v90q_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS material_reservation (
            reservation_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            plan_id TEXT NULL,
            plan_line_id TEXT NULL,
            material_requirement_id TEXT NULL,
            material_master_id TEXT NOT NULL,
            requirement_type TEXT NOT NULL,
            requested_qty NUMERIC NOT NULL,
            reserved_qty NUMERIC NOT NULL DEFAULT 0,
            released_qty NUMERIC NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'OPEN',
            notes TEXT NULL,
            created_by TEXT NOT NULL,
            approved_by TEXT NULL,
            approved_at TEXT NULL,
            approval_reason TEXT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE INDEX IF NOT EXISTS ix_material_reservation_scope
            ON material_reservation(organization_id, entity_id, location_id, material_master_id, status)""",
        """CREATE TABLE IF NOT EXISTS production_order (
            production_order_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            plan_id TEXT NOT NULL,
            plan_line_id TEXT NOT NULL,
            order_no TEXT NOT NULL,
            product_master_id TEXT NOT NULL,
            planned_qty NUMERIC NOT NULL,
            uom TEXT NOT NULL,
            scheduled_start TEXT NULL,
            scheduled_end TEXT NULL,
            status TEXT NOT NULL DEFAULT 'DRAFT',
            notes TEXT NULL,
            created_by TEXT NOT NULL,
            approved_by TEXT NULL,
            approved_at TEXT NULL,
            approval_reason TEXT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE UNIQUE INDEX IF NOT EXISTS ux_production_order_no
            ON production_order(organization_id, entity_id, order_no)""",
        """CREATE TABLE IF NOT EXISTS production_order_material (
            order_material_id TEXT PRIMARY KEY,
            production_order_id TEXT NOT NULL,
            material_master_id TEXT NOT NULL,
            requirement_type TEXT NOT NULL,
            required_qty NUMERIC NOT NULL,
            reserved_qty NUMERIC NOT NULL DEFAULT 0,
            uom TEXT NOT NULL,
            notes TEXT NULL,
            FOREIGN KEY(production_order_id) REFERENCES production_order(production_order_id)
        )""",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))


class ReservationIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    plan_id: UUID
    plan_line_id: UUID
    material_requirement_id: UUID | None = None
    material_master_id: UUID
    requirement_type: str = 'RAW_MATERIAL'
    requested_qty: float = Field(gt=0)
    notes: str | None = None


class ProductionOrderIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    plan_id: UUID
    plan_line_id: UUID
    order_no: str = Field(min_length=1)
    product_master_id: UUID
    planned_qty: float = Field(gt=0)
    uom: str = Field(min_length=1)
    scheduled_start: str | None = None
    scheduled_end: str | None = None
    notes: str | None = None


class DecisionIn(BaseModel):
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


def _stock_available(engine, entity_id: UUID, location_id: UUID, material_master_id: UUID) -> float:
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT COALESCE(SUM(available_qty),0) AS qty
            FROM inventory_lot
            WHERE replace(lower(entity_id),'-','')=replace(lower(:e),'-','')
              AND replace(lower(location_id),'-','')=replace(lower(:l),'-','')
              AND replace(lower(item_master_id),'-','')=replace(lower(:m),'-','')
              AND status='AVAILABLE' AND qc_status='RELEASED' AND available_qty>0
        """), {'e':str(entity_id),'l':str(location_id),'m':str(material_master_id)}).mappings().first()
        return float(row['qty'] or 0) if row is not None else 0.0


def register_v90q_routes(app: FastAPI, engine) -> None:
    ensure_v90q_schema(engine)

    @app.post('/v90q/reservations')
    def create_reservation(body: ReservationIn, request: Request):
        user = _require(engine, request, body.entity_id, body.location_id, True)
        with engine.connect() as conn:
            plan = conn.execute(text('SELECT organization_id, entity_id, location_id FROM production_plan WHERE plan_id=:p'), {'p':str(body.plan_id)}).mappings().first()
            line = conn.execute(text('SELECT plan_id FROM production_plan_line WHERE plan_line_id=:pl AND plan_id=:p'), {'pl':str(body.plan_line_id),'p':str(body.plan_id)}).mappings().first()
            if not plan or not line:
                raise HTTPException(404, 'production plan/line not found')
            req = None
            if body.material_requirement_id:
                req = conn.execute(text('SELECT required_qty, material_master_id, requirement_type, plan_line_id FROM material_requirement_calc WHERE calc_id=:c'), {'c':str(body.material_requirement_id)}).mappings().first()
                if not req:
                    raise HTTPException(404, 'material requirement not found')
                if req['plan_line_id'] != str(body.plan_line_id):
                    raise HTTPException(422, 'requirement does not belong to plan line')
                if str(req['material_master_id']).replace('-','').lower() != str(body.material_master_id).replace('-','').lower():
                    raise HTTPException(422, 'material does not match requirement')
            existing = conn.execute(text("""SELECT COALESCE(SUM(CASE WHEN status='APPROVED' THEN reserved_qty ELSE requested_qty END - released_qty),0) AS open_qty
                FROM material_reservation WHERE plan_line_id=:pl AND material_master_id=:m AND status IN ('OPEN','APPROVED')"""), {'pl':str(body.plan_line_id),'m':str(body.material_master_id)}).mappings().first()
            open_qty=float(existing['open_qty'] or 0) if existing else 0
        available=_stock_available(engine,body.entity_id,body.location_id,body.material_master_id)
        if body.requested_qty > max(0, available-open_qty)+1e-9:
            raise HTTPException(409, f'insufficient available stock; available_for_reservation={max(0, available-open_qty):.6f}')
        rid=uuid4()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO material_reservation
                (reservation_id,organization_id,entity_id,location_id,plan_id,plan_line_id,material_requirement_id,material_master_id,requirement_type,requested_qty,status,notes,created_by)
                VALUES(:id,:o,:e,:l,:p,:pl,:rc,:m,:t,:q,'OPEN',:n,:u)"""),{
                'id':str(rid),'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'p':str(body.plan_id),'pl':str(body.plan_line_id),'rc':str(body.material_requirement_id) if body.material_requirement_id else None,'m':str(body.material_master_id),'t':body.requirement_type,'q':body.requested_qty,'n':body.notes,'u':str(user.user_id)})
        return {'reservation_id':str(rid),'status':'OPEN','requested_qty':body.requested_qty,'available_stock':available}

    @app.get('/v90q/reservations')
    def list_reservations(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, plan_line_id: UUID | None = None):
        _require(engine, request, entity_id, location_id, False)
        q='SELECT * FROM material_reservation WHERE organization_id=:o AND entity_id=:e AND location_id=:l'
        p={'o':str(organization_id),'e':str(entity_id),'l':str(location_id)}
        if plan_line_id: q+=' AND plan_line_id=:pl'; p['pl']=str(plan_line_id)
        q+=' ORDER BY created_at DESC'
        with engine.connect() as conn: rows=conn.execute(text(q),p).mappings().all()
        return {'items':[dict(r) for r in rows]}

    @app.post('/v90q/reservations/{reservation_id}/approve')
    def approve_reservation(reservation_id: UUID, body: DecisionIn, request: Request):
        user=authenticate(request)
        if 'production.approve' not in permissions_for_user(engine,user.user_id): raise HTTPException(403,'permission denied')
        with engine.begin() as conn:
            row=conn.execute(text('SELECT status,created_by,entity_id,location_id,requested_qty,material_master_id FROM material_reservation WHERE reservation_id=:r'),{'r':str(reservation_id)}).mappings().first()
            if not row: raise HTTPException(404,'reservation not found')
            if row['status']!='OPEN': raise HTTPException(409,'only open reservation can be approved')
            if str(row['created_by'])==str(user.user_id): raise HTTPException(409,'self-approval is not allowed')
            try: assert_entity_location_allowed(engine,user.user_id,str(row['entity_id']),str(row['location_id']))
            except PermissionError as exc: raise HTTPException(403,str(exc)) from exc
            conn.execute(text("UPDATE material_reservation SET status='APPROVED',reserved_qty=requested_qty,approved_by=:u,approved_at=CURRENT_TIMESTAMP,approval_reason=:r WHERE reservation_id=:id"),{'u':str(user.user_id),'r':body.reason,'id':str(reservation_id)})
        return {'reservation_id':str(reservation_id),'status':'APPROVED'}

    @app.post('/v90q/reservations/{reservation_id}/release')
    def release_reservation(reservation_id: UUID, body: DecisionIn, request: Request):
        user= _require(engine,request,UUID('00000000-0000-0000-0000-000000000000'),UUID('00000000-0000-0000-0000-000000000000'),True) if False else authenticate(request)
        if 'production.edit' not in permissions_for_user(engine,user.user_id): raise HTTPException(403,'permission denied')
        with engine.begin() as conn:
            row=conn.execute(text('SELECT status,reserved_qty,released_qty FROM material_reservation WHERE reservation_id=:r'),{'r':str(reservation_id)}).mappings().first()
            if not row: raise HTTPException(404,'reservation not found')
            if row['status'] not in ('OPEN','APPROVED'): raise HTTPException(409,'reservation cannot be released')
            conn.execute(text("UPDATE material_reservation SET status='RELEASED',released_qty=reserved_qty WHERE reservation_id=:id"),{'id':str(reservation_id)})
        return {'reservation_id':str(reservation_id),'status':'RELEASED'}

    @app.post('/v90q/production-orders')
    def create_production_order(body: ProductionOrderIn, request: Request):
        user=_require(engine,request,body.entity_id,body.location_id,True)
        with engine.connect() as conn:
            plan=conn.execute(text('SELECT organization_id,entity_id,location_id FROM production_plan WHERE plan_id=:p'),{'p':str(body.plan_id)}).mappings().first()
            line=conn.execute(text('SELECT item_master_id,planned_qty,plan_id FROM production_plan_line WHERE plan_line_id=:pl AND plan_id=:p'),{'pl':str(body.plan_line_id),'p':str(body.plan_id)}).mappings().first()
            if not plan or not line: raise HTTPException(404,'production plan/line not found')
            if str(line['item_master_id']).replace('-','').lower()!=str(body.product_master_id).replace('-','').lower(): raise HTTPException(422,'product does not match plan line')
            if body.scheduled_end and body.scheduled_start and body.scheduled_end<body.scheduled_start: raise HTTPException(422,'scheduled_end must be on/after scheduled_start')
            dup=conn.execute(text('SELECT 1 FROM production_order WHERE organization_id=:o AND entity_id=:e AND order_no=:n'),{'o':str(body.organization_id),'e':str(body.entity_id),'n':body.order_no}).first()
            if dup: raise HTTPException(409,'production order number already exists')
        oid=uuid4()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO production_order
                (production_order_id,organization_id,entity_id,location_id,plan_id,plan_line_id,order_no,product_master_id,planned_qty,uom,scheduled_start,scheduled_end,status,notes,created_by)
                VALUES(:id,:o,:e,:l,:p,:pl,:n,:m,:q,:u,:ss,:se,'DRAFT',:notes,:by)"""),{'id':str(oid),'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'p':str(body.plan_id),'pl':str(body.plan_line_id),'n':body.order_no,'m':str(body.product_master_id),'q':body.planned_qty,'u':body.uom,'ss':body.scheduled_start,'se':body.scheduled_end,'notes':body.notes,'by':str(user.user_id)})
            reqs=conn.execute(text('SELECT material_master_id,requirement_type,required_qty,uom FROM material_requirement_calc WHERE plan_id=:p AND plan_line_id=:pl ORDER BY created_at'),{'p':str(body.plan_id),'pl':str(body.plan_line_id)}).mappings().all()
            for r in reqs:
                factor=body.planned_qty/max(1e-9, float(conn.execute(text('SELECT planned_qty FROM production_plan_line WHERE plan_line_id=:pl'),{'pl':str(body.plan_line_id)}).scalar_one()))
                qty=float(r['required_qty'])*factor
                conn.execute(text("""INSERT INTO production_order_material(order_material_id,production_order_id,material_master_id,requirement_type,required_qty,uom)
                    VALUES(:id,:o,:m,:t,:q,:u)"""),{'id':str(uuid4()),'o':str(oid),'m':r['material_master_id'],'t':r['requirement_type'],'q':qty,'u':r['uom']})
        return {'production_order_id':str(oid),'status':'DRAFT'}

    @app.get('/v90q/production-orders/{order_id}')
    def get_production_order(order_id: UUID, request: Request):
        user=authenticate(request)
        if 'production.view' not in permissions_for_user(engine,user.user_id): raise HTTPException(403,'permission denied')
        with engine.connect() as conn:
            order=conn.execute(text('SELECT * FROM production_order WHERE production_order_id=:o'),{'o':str(order_id)}).mappings().first()
            if not order: raise HTTPException(404,'production order not found')
            try: assert_entity_location_allowed(engine,user.user_id,str(order['entity_id']),str(order['location_id']))
            except PermissionError as exc: raise HTTPException(403,str(exc)) from exc
            mats=conn.execute(text('SELECT * FROM production_order_material WHERE production_order_id=:o ORDER BY order_material_id'),{'o':str(order_id)}).mappings().all()
        return {'production_order':dict(order),'materials':[dict(x) for x in mats]}

    @app.post('/v90q/production-orders/{order_id}/submit')
    def submit_production_order(order_id: UUID, body: DecisionIn, request: Request):
        user=authenticate(request)
        if 'production.edit' not in permissions_for_user(engine,user.user_id): raise HTTPException(403,'permission denied')
        with engine.begin() as conn:
            row=conn.execute(text('SELECT status FROM production_order WHERE production_order_id=:o'),{'o':str(order_id)}).mappings().first()
            if not row: raise HTTPException(404,'production order not found')
            if row['status']!='DRAFT': raise HTTPException(409,'only draft order can be submitted')
            conn.execute(text("UPDATE production_order SET status='PENDING_APPROVAL' WHERE production_order_id=:o"),{'o':str(order_id)})
        return {'production_order_id':str(order_id),'status':'PENDING_APPROVAL'}

    @app.post('/v90q/production-orders/{order_id}/approve')
    def approve_production_order(order_id: UUID, body: DecisionIn, request: Request):
        user=authenticate(request)
        if 'production.approve' not in permissions_for_user(engine,user.user_id): raise HTTPException(403,'permission denied')
        with engine.begin() as conn:
            row=conn.execute(text('SELECT status,created_by,entity_id,location_id FROM production_order WHERE production_order_id=:o'),{'o':str(order_id)}).mappings().first()
            if not row: raise HTTPException(404,'production order not found')
            if row['status']!='PENDING_APPROVAL': raise HTTPException(409,'only pending order can be approved')
            if str(row['created_by'])==str(user.user_id): raise HTTPException(409,'self-approval is not allowed')
            try: assert_entity_location_allowed(engine,user.user_id,str(row['entity_id']),str(row['location_id']))
            except PermissionError as exc: raise HTTPException(403,str(exc)) from exc
            conn.execute(text("UPDATE production_order SET status='APPROVED',approved_by=:u,approved_at=CURRENT_TIMESTAMP,approval_reason=:r WHERE production_order_id=:o"),{'u':str(user.user_id),'r':body.reason,'o':str(order_id)})
        return {'production_order_id':str(order_id),'status':'APPROVED'}

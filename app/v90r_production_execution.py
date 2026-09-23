
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


def _require(engine, request: Request, entity_id: UUID, location_id: UUID, write: bool, batch: bool=False):
    user = authenticate(request)
    perms = permissions_for_user(engine, user.user_id)
    needed = 'production.edit' if batch else ('production.edit' if write else 'production.view')
    if needed not in perms:
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, str(entity_id), str(location_id))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def ensure_v90r_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS production_material_issue (
            issue_id TEXT PRIMARY KEY, production_order_id TEXT NOT NULL, order_material_id TEXT NULL,
            organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NOT NULL,
            warehouse_id TEXT NOT NULL, material_master_id TEXT NOT NULL, lot_id TEXT NOT NULL,
            issued_qty NUMERIC NOT NULL, uom TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'POSTED',
            issued_by TEXT NOT NULL, issued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            notes TEXT NULL
        )""",
        """CREATE INDEX IF NOT EXISTS ix_prod_issue_order ON production_material_issue(production_order_id, material_master_id, lot_id)""",
        """CREATE TABLE IF NOT EXISTS production_batch (
            batch_id TEXT PRIMARY KEY, production_order_id TEXT NOT NULL, organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL, location_id TEXT NOT NULL, batch_no TEXT NOT NULL,
            product_master_id TEXT NOT NULL, planned_qty NUMERIC NOT NULL, uom TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN', operator_user_id TEXT NULL, machine_id TEXT NULL,
            start_at TEXT NULL, end_at TEXT NULL, created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, notes TEXT NULL
        )""",
        """CREATE UNIQUE INDEX IF NOT EXISTS ux_production_batch_no ON production_batch(organization_id, entity_id, batch_no)""",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))


class IssueLine(BaseModel):
    order_material_id: UUID | None = None
    material_master_id: UUID
    lot_id: UUID
    warehouse_id: UUID
    issued_qty: float = Field(gt=0)
    uom: str = Field(min_length=1)
    notes: str | None = None

class MaterialIssueIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    production_order_id: UUID
    lines: list[IssueLine] = Field(min_length=1)
    notes: str | None = None

class BatchCreate(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    production_order_id: UUID
    batch_no: str = Field(min_length=1)
    operator_user_id: str | None = None
    machine_id: str | None = None
    notes: str | None = None

class BatchDecision(BaseModel):
    reason: str = ''


def _warehouse_ok(engine, warehouse_id: UUID, entity_id: UUID, location_id: UUID):
    with engine.connect() as conn:
        row = conn.execute(text("SELECT warehouse_id FROM erp_warehouses WHERE warehouse_id=:w AND entity_id=:e AND location_id=:l AND active=1"),
                           {'w':str(warehouse_id), 'e':str(entity_id), 'l':str(location_id)}).first()
    if not row:
        raise HTTPException(422, 'warehouse not found in entity/location scope')


def _lot_available(engine, *, organization_id: UUID, entity_id: UUID, location_id: UUID, warehouse_id: UUID, material_master_id: UUID, lot_id: UUID):
    with engine.connect() as conn:
        row = conn.execute(text("""SELECT lot_id,item_master_id,uom,available_qty,status,qc_status FROM inventory_lot
            WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w AND lot_id=:lot AND item_master_id=:m"""),
            {'o':str(organization_id),'e':str(entity_id),'l':str(location_id),'w':str(warehouse_id),'lot':str(lot_id),'m':str(material_master_id)}).mappings().first()
    if not row:
        raise HTTPException(422, 'lot not found in warehouse for material')
    if row['status'] != 'AVAILABLE' or row['qc_status'] != 'RELEASED':
        raise HTTPException(409, 'lot is not released/available')
    return row


def register_v90r_routes(app: FastAPI, engine) -> None:
    ensure_v90r_schema(engine)

    @app.post('/v90r/production-orders/{order_id}/issues')
    def issue_material(order_id: UUID, body: MaterialIssueIn, request: Request):
        user = _require(engine, request, body.entity_id, body.location_id, True)
        if str(order_id) != str(body.production_order_id):
            raise HTTPException(422, 'path order_id does not match payload')
        with engine.connect() as conn:
            order = conn.execute(text("SELECT * FROM production_order WHERE production_order_id=:o"), {'o':str(order_id)}).mappings().first()
            if not order: raise HTTPException(404, 'production order not found')
            if order['status'] != 'APPROVED': raise HTTPException(409, 'production order must be approved before material issue')
            if str(order['entity_id']) != str(body.entity_id) or str(order['location_id']) != str(body.location_id):
                raise HTTPException(422, 'order scope mismatch')
            materials = {str(r['order_material_id']): r for r in conn.execute(text("SELECT * FROM production_order_material WHERE production_order_id=:o"), {'o':str(order_id)}).mappings().all()}
        prepared=[]
        for line in body.lines:
            _warehouse_ok(engine, line.warehouse_id, body.entity_id, body.location_id)
            lot=_lot_available(engine, organization_id=body.organization_id, entity_id=body.entity_id, location_id=body.location_id,
                               warehouse_id=line.warehouse_id, material_master_id=line.material_master_id, lot_id=line.lot_id)
            if line.order_material_id:
                om = materials.get(str(line.order_material_id))
                if not om: raise HTTPException(422, 'order material line not found')
                if str(om['material_master_id']).replace('-','').lower() != str(line.material_master_id).replace('-','').lower():
                    raise HTTPException(422, 'issue material does not match order material line')
                if line.uom != om['uom']:
                    raise HTTPException(422, 'issue UOM does not match order material line')
            already = 0.0
            with engine.connect() as conn:
                already = float(conn.execute(text("SELECT COALESCE(SUM(issued_qty),0) FROM production_material_issue WHERE production_order_id=:o AND material_master_id=:m AND status='POSTED'"),
                    {'o':str(order_id),'m':str(line.material_master_id)}).scalar_one() or 0)
            required = sum(float(x['required_qty']) for x in materials.values() if str(x['material_master_id']).replace('-','').lower()==str(line.material_master_id).replace('-','').lower())
            if already + line.issued_qty > required + 1e-9:
                raise HTTPException(409, f'issue exceeds remaining requirement; remaining={max(required-already,0):g}')
            if line.issued_qty > float(lot['available_qty']) + 1e-9:
                raise HTTPException(409, 'issue exceeds lot available quantity')
            prepared.append((line, lot))
        ids=[]
        with engine.begin() as conn:
            for line, lot in prepared:
                iid=uuid4()
                conn.execute(text("""INSERT INTO production_material_issue(issue_id,production_order_id,order_material_id,organization_id,entity_id,location_id,warehouse_id,material_master_id,lot_id,issued_qty,uom,status,issued_by,notes)
                    VALUES(:i,:o,:om,:org,:e,:l,:w,:m,:lot,:q,:u,'POSTED',:by,:n)"""),
                    {'i':str(iid),'o':str(order_id),'om':str(line.order_material_id) if line.order_material_id else None,'org':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'w':str(line.warehouse_id),'m':str(line.material_master_id),'lot':str(line.lot_id),'q':line.issued_qty,'u':line.uom,'by':str(user.user_id),'n':line.notes})
                conn.execute(text("UPDATE inventory_lot SET available_qty=available_qty-:q WHERE lot_id=:lot AND available_qty>=:q"), {'q':line.issued_qty,'lot':str(line.lot_id)})
                ids.append(str(iid))
        return {'production_order_id':str(order_id),'issued_count':len(ids),'issue_ids':ids,'status':'POSTED'}

    @app.post('/v90r/production-orders/{order_id}/batches')
    def create_batch(order_id: UUID, body: BatchCreate, request: Request):
        user = _require(engine, request, body.entity_id, body.location_id, True, batch=True)
        if str(order_id) != str(body.production_order_id): raise HTTPException(422, 'path order_id does not match payload')
        with engine.connect() as conn:
            order = conn.execute(text('SELECT * FROM production_order WHERE production_order_id=:o'), {'o':str(order_id)}).mappings().first()
            if not order: raise HTTPException(404, 'production order not found')
            if order['status'] != 'APPROVED': raise HTTPException(409, 'production order must be approved')
            issued = float(conn.execute(text("SELECT COALESCE(SUM(issued_qty),0) FROM production_material_issue WHERE production_order_id=:o AND status='POSTED'"), {'o':str(order_id)}).scalar_one() or 0)
            if issued <= 0: raise HTTPException(409, 'at least one posted material issue is required before batch creation')
            exists = conn.execute(text('SELECT batch_id FROM production_batch WHERE organization_id=:org AND entity_id=:e AND batch_no=:b'), {'org':str(body.organization_id),'e':str(body.entity_id),'b':body.batch_no}).first()
            if exists: raise HTTPException(409, 'batch number already exists')
        bid=uuid4()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO production_batch(batch_id,production_order_id,organization_id,entity_id,location_id,batch_no,product_master_id,planned_qty,uom,status,operator_user_id,machine_id,created_by,notes)
                VALUES(:id,:o,:org,:e,:l,:b,:p,:q,:u,'OPEN',:op,:m,:by,:n)"""),
                {'id':str(bid),'o':str(order_id),'org':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'b':body.batch_no,'p':str(order['product_master_id']),'q':order['planned_qty'],'u':order['uom'],'op':body.operator_user_id,'m':body.machine_id,'by':str(user.user_id),'n':body.notes})
        return {'batch_id':str(bid),'batch_no':body.batch_no,'status':'OPEN'}

    @app.post('/v90r/batches/{batch_id}/start')
    def start_batch(batch_id: UUID, body: BatchDecision, request: Request):
        user=authenticate(request)
        if 'production.edit' not in permissions_for_user(engine,user.user_id): raise HTTPException(403,'permission denied')
        with engine.begin() as conn:
            row=conn.execute(text('SELECT status FROM production_batch WHERE batch_id=:b'),{'b':str(batch_id)}).mappings().first()
            if not row: raise HTTPException(404,'batch not found')
            if row['status']!='OPEN': raise HTTPException(409,'only open batch can start')
            conn.execute(text("UPDATE production_batch SET status='RUNNING',start_at=:t WHERE batch_id=:b"),{'t':_now(),'b':str(batch_id)})
        return {'batch_id':str(batch_id),'status':'RUNNING'}

    @app.post('/v90r/batches/{batch_id}/complete')
    def complete_batch(batch_id: UUID, body: BatchDecision, request: Request):
        user=authenticate(request)
        if 'production.edit' not in permissions_for_user(engine,user.user_id): raise HTTPException(403,'permission denied')
        with engine.begin() as conn:
            row=conn.execute(text('SELECT status FROM production_batch WHERE batch_id=:b'),{'b':str(batch_id)}).mappings().first()
            if not row: raise HTTPException(404,'batch not found')
            if row['status']!='RUNNING': raise HTTPException(409,'only running batch can complete')
            conn.execute(text("UPDATE production_batch SET status='COMPLETED',end_at=:t,notes=CASE WHEN :r='' THEN notes ELSE :r END WHERE batch_id=:b"),{'t':_now(),'r':body.reason,'b':str(batch_id)})
        return {'batch_id':str(batch_id),'status':'COMPLETED'}

    @app.get('/v90r/batches/{batch_id}')
    def get_batch(batch_id: UUID, request: Request):
        user=authenticate(request)
        if 'production.view' not in permissions_for_user(engine,user.user_id): raise HTTPException(403,'permission denied')
        with engine.connect() as conn:
            batch=conn.execute(text('SELECT * FROM production_batch WHERE batch_id=:b'),{'b':str(batch_id)}).mappings().first()
            if not batch: raise HTTPException(404,'batch not found')
            try: assert_entity_location_allowed(engine,user.user_id,str(batch['entity_id']),str(batch['location_id']))
            except PermissionError as exc: raise HTTPException(403,str(exc)) from exc
            issues=conn.execute(text('SELECT * FROM production_material_issue WHERE production_order_id=:o ORDER BY issued_at,issue_id'),{'o':batch['production_order_id']}).mappings().all()
        return {'batch':dict(batch),'material_issues':[dict(x) for x in issues]}

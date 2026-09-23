from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require(engine, request: Request, entity_id: UUID, location_id: UUID | None, write: bool):
    user = authenticate(request)
    perms = permissions_for_user(engine, user.user_id)
    needed = 'inventory.edit' if write else 'inventory.view'
    if needed not in perms:
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, str(entity_id), str(location_id) if location_id else None)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def ensure_inventory_ops_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS inventory_reservation (
            reservation_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, item_master_id TEXT NOT NULL,
            quantity NUMERIC NOT NULL, reserved_qty NUMERIC NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'OPEN', reference_type TEXT NULL, reference_id TEXT NULL,
            created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            released_at TEXT NULL, release_reason TEXT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS inventory_transfer (
            transfer_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            from_location_id TEXT NOT NULL, from_warehouse_id TEXT NOT NULL,
            to_location_id TEXT NOT NULL, to_warehouse_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT',
            notes TEXT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            posted_at TEXT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS inventory_transfer_line (
            transfer_line_id TEXT PRIMARY KEY, transfer_id TEXT NOT NULL, item_master_id TEXT NOT NULL,
            lot_id TEXT NOT NULL, quantity NUMERIC NOT NULL, uom TEXT NOT NULL,
            FOREIGN KEY(transfer_id) REFERENCES inventory_transfer(transfer_id)
        )""",
    ]
    with engine.begin() as conn:
        for s in stmts:
            conn.execute(text(s))


class ReservationCreate(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    warehouse_id: UUID
    item_master_id: UUID
    quantity: float = Field(gt=0)
    reference_type: str | None = None
    reference_id: str | None = None


class TransferCreate(BaseModel):
    organization_id: UUID
    entity_id: UUID
    from_location_id: UUID
    from_warehouse_id: UUID
    to_location_id: UUID
    to_warehouse_id: UUID
    notes: str | None = None
    lines: list[dict[str, Any]] = Field(min_length=1)


def _warehouse_ok(engine, warehouse_id: UUID, entity_id: UUID, location_id: UUID):
    with engine.connect() as conn:
        row = conn.execute(text("SELECT warehouse_id FROM erp_warehouses WHERE warehouse_id=:w AND entity_id=:e AND location_id=:l AND active=1"),
                           {'w': str(warehouse_id), 'e': str(entity_id), 'l': str(location_id)}).first()
    if not row:
        raise HTTPException(422, 'Warehouse not found in entity/location scope')


def _available_unreserved(engine, body: ReservationCreate) -> float:
    with engine.connect() as conn:
        bal = conn.execute(text("""SELECT COALESCE(available_qty,0) FROM inventory_stock_balance
                                  WHERE organization_id=:o AND entity_id=:e AND location_id=:l
                                    AND warehouse_id=:w AND item_master_id=:m"""),
                           {'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'w':str(body.warehouse_id),'m':str(body.item_master_id)}).scalar_one_or_none() or 0
        reserved = conn.execute(text("""SELECT COALESCE(SUM(reserved_qty),0) FROM inventory_reservation
                                      WHERE organization_id=:o AND entity_id=:e AND location_id=:l
                                        AND warehouse_id=:w AND item_master_id=:m AND status='OPEN'"""),
                                {'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'w':str(body.warehouse_id),'m':str(body.item_master_id)}).scalar_one() or 0
    return float(bal) - float(reserved)


def register_v90n_routes(app: FastAPI, engine) -> None:
    ensure_inventory_ops_schema(engine)

    @app.post('/v90n/inventory/reservations')
    def create_reservation(body: ReservationCreate, request: Request):
        user = _require(engine, request, body.entity_id, body.location_id, True)
        _warehouse_ok(engine, body.warehouse_id, body.entity_id, body.location_id)
        available = _available_unreserved(engine, body)
        if body.quantity > available:
            raise HTTPException(409, f'insufficient unreserved stock: {available}')
        rid = uuid4()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO inventory_reservation
                (reservation_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,quantity,reserved_qty,status,reference_type,reference_id,created_by)
                VALUES (:r,:o,:e,:l,:w,:m,:q,:q,'OPEN',:rt,:ri,:u)"""),
                {'r':str(rid),'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'w':str(body.warehouse_id),'m':str(body.item_master_id),'q':body.quantity,'rt':body.reference_type,'ri':body.reference_id,'u':str(user.user_id)})
        return {'reservation_id':str(rid),'status':'OPEN','quantity':body.quantity}

    @app.post('/v90n/inventory/reservations/{reservation_id}/release')
    def release_reservation(reservation_id: UUID, request: Request, reason: str = ''):
        user = authenticate(request)
        if 'inventory.edit' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.begin() as conn:
            row = conn.execute(text('SELECT reservation_id,status FROM inventory_reservation WHERE reservation_id=:r'), {'r':str(reservation_id)}).mappings().first()
            if not row:
                raise HTTPException(404, 'reservation not found')
            if row['status'] != 'OPEN':
                raise HTTPException(409, 'reservation is not open')
            conn.execute(text("UPDATE inventory_reservation SET status='RELEASED', released_at=:t, release_reason=:reason WHERE reservation_id=:r"), {'t':_now(),'reason':reason,'r':str(reservation_id)})
        return {'reservation_id':str(reservation_id),'status':'RELEASED'}

    @app.get('/v90n/inventory/fefo-preview')
    def fefo_preview(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, warehouse_id: UUID, item_master_id: UUID, quantity: float):
        _require(engine, request, entity_id, location_id, False)
        if quantity <= 0:
            raise HTTPException(422, 'quantity must be greater than zero')
        _warehouse_ok(engine, warehouse_id, entity_id, location_id)
        with engine.connect() as conn:
            rows = conn.execute(text("""SELECT lot_id, lot_code, expiry_date, available_qty, uom
                FROM inventory_lot WHERE organization_id=:o AND entity_id=:e AND location_id=:l
                  AND warehouse_id=:w AND item_master_id=:m AND status='AVAILABLE' AND qc_status='RELEASED'
                  AND available_qty>0
                ORDER BY CASE WHEN expiry_date IS NULL THEN 1 ELSE 0 END, expiry_date, created_at"""),
                {'o':str(organization_id),'e':str(entity_id),'l':str(location_id),'w':str(warehouse_id),'m':str(item_master_id)}).mappings().all()
        remain = quantity; allocation=[]
        for row in rows:
            take=min(remain,float(row['available_qty']))
            if take>0:
                allocation.append({'lot_id':row['lot_id'],'lot_code':row['lot_code'],'expiry_date':row['expiry_date'],'quantity':take,'uom':row['uom']})
                remain-=take
            if remain<=0: break
        return {'requested_qty':quantity,'allocated_qty':quantity-remain,'short_qty':max(remain,0),'fefo':allocation}

    @app.post('/v90n/inventory/transfers')
    def create_transfer(body: TransferCreate, request: Request):
        user = _require(engine, request, body.entity_id, body.from_location_id, True)
        _warehouse_ok(engine, body.from_warehouse_id, body.entity_id, body.from_location_id)
        _warehouse_ok(engine, body.to_warehouse_id, body.entity_id, body.to_location_id)
        if body.from_warehouse_id == body.to_warehouse_id and body.from_location_id == body.to_location_id:
            raise HTTPException(422, 'source and destination must differ')
        prepared=[]
        for line in body.lines:
            qty=float(line.get('quantity',0)); lot_id=str(line.get('lot_id') or '')
            if qty<=0 or not lot_id: raise HTTPException(422,'Each transfer line requires lot_id and positive quantity')
            with engine.connect() as conn:
                lot=conn.execute(text("SELECT lot_id,item_master_id,uom,available_qty,status,qc_status FROM inventory_lot WHERE lot_id=:lot AND organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w"), {'lot':lot_id,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.from_location_id),'w':str(body.from_warehouse_id)}).mappings().first()
            if not lot: raise HTTPException(422,'Lot not found in source warehouse')
            if lot['status']!='AVAILABLE' or lot['qc_status']!='RELEASED': raise HTTPException(409,'Lot is not available for transfer')
            if qty>float(lot['available_qty']): raise HTTPException(409,'Transfer quantity exceeds lot availability')
            prepared.append((lot,qty))
        tid=uuid4()
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO inventory_transfer(transfer_id,organization_id,entity_id,from_location_id,from_warehouse_id,to_location_id,to_warehouse_id,status,notes,created_by)
                             VALUES(:t,:o,:e,:fl,:fw,:tl,:tw,'DRAFT',:n,:u)"""), {'t':str(tid),'o':str(body.organization_id),'e':str(body.entity_id),'fl':str(body.from_location_id),'fw':str(body.from_warehouse_id),'tl':str(body.to_location_id),'tw':str(body.to_warehouse_id),'n':body.notes,'u':str(user.user_id)})
            for lot,qty in prepared:
                conn.execute(text("INSERT INTO inventory_transfer_line(transfer_line_id,transfer_id,item_master_id,lot_id,quantity,uom) VALUES(:id,:t,:m,:lot,:q,:u)"), {'id':str(uuid4()),'t':str(tid),'m':lot['item_master_id'],'lot':lot['lot_id'],'q':qty,'u':lot['uom']})
        return {'transfer_id':str(tid),'status':'DRAFT','line_count':len(prepared)}

    @app.post('/v90n/inventory/transfers/{transfer_id}/post')
    def post_transfer(transfer_id: UUID, request: Request):
        with engine.connect() as conn:
            transfer=conn.execute(text('SELECT * FROM inventory_transfer WHERE transfer_id=:t'), {'t':str(transfer_id)}).mappings().first()
            lines=conn.execute(text('SELECT * FROM inventory_transfer_line WHERE transfer_id=:t'), {'t':str(transfer_id)}).mappings().all()
        if not transfer: raise HTTPException(404,'transfer not found')
        user=_require(engine,request,UUID(transfer['entity_id']),UUID(transfer['from_location_id']),True)
        if transfer['status']!='DRAFT': raise HTTPException(409,'transfer is not draft')
        with engine.begin() as conn:
            for line in lines:
                lot=conn.execute(text('SELECT * FROM inventory_lot WHERE lot_id=:l'), {'l':line['lot_id']}).mappings().first()
                if not lot or lot['status']!='AVAILABLE' or float(lot['available_qty'])<float(line['quantity']):
                    raise HTTPException(409,'Lot availability changed; recheck transfer')
                # move by ledger and balance only; receiving lot is represented by a new lot at destination.
                new_lot=uuid4()
                conn.execute(text("""INSERT INTO inventory_lot(lot_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,source_grn_id,source_grn_line_id,supplier_id,supplier_lot_no,lot_code,mfg_date,expiry_date,received_qty,accepted_qty,available_qty,rejected_qty,uom,qc_status,status)
                    SELECT :newid,organization_id,entity_id,:tl,:tw,item_master_id,source_grn_id,source_grn_line_id,supplier_id,supplier_lot_no,lot_code,mfg_date,expiry_date,:q,:q,:q,0,uom,'RELEASED','AVAILABLE' FROM inventory_lot WHERE lot_id=:oldid"""), {'newid':str(new_lot),'tl':transfer['to_location_id'],'tw':transfer['to_warehouse_id'],'q':line['quantity'],'oldid':line['lot_id']})
                conn.execute(text("UPDATE inventory_lot SET available_qty=available_qty-:q WHERE lot_id=:l"), {'q':line['quantity'],'l':line['lot_id']})
                conn.execute(text("INSERT INTO inventory_stock_ledger(movement_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,lot_id,movement_type,quantity,uom,reference_type,reference_id,status,created_by) VALUES(:id,:o,:e,:l,:w,:m,:lot,'TRANSFER_OUT',:q,:u,'TRANSFER',:t,'POSTED',:by),(:id2,:o,:e,:tl,:tw,:m,:newlot,'TRANSFER_IN',:q,:u,'TRANSFER',:t,'POSTED',:by)"), {'id':str(uuid4()),'id2':str(uuid4()),'o':transfer['organization_id'],'e':transfer['entity_id'],'l':transfer['from_location_id'],'w':transfer['from_warehouse_id'],'tl':transfer['to_location_id'],'tw':transfer['to_warehouse_id'],'m':line['item_master_id'],'lot':line['lot_id'],'newlot':str(new_lot),'q':line['quantity'],'u':line['uom'],'t':str(transfer_id),'by':str(user.user_id)})
                conn.execute(text("UPDATE inventory_stock_balance SET available_qty=available_qty-:q, updated_at=CURRENT_TIMESTAMP WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND warehouse_id=:w AND item_master_id=:m AND uom=:u"), {'q':line['quantity'],'o':transfer['organization_id'],'e':transfer['entity_id'],'l':transfer['from_location_id'],'w':transfer['from_warehouse_id'],'m':line['item_master_id'],'u':line['uom']})
                conn.execute(text("""INSERT INTO inventory_stock_balance(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom,available_qty,updated_at)
                    VALUES(:o,:e,:l,:w,:m,:u,:q,CURRENT_TIMESTAMP)
                    ON CONFLICT(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom) DO UPDATE SET available_qty=inventory_stock_balance.available_qty+excluded.available_qty, updated_at=CURRENT_TIMESTAMP"""), {'o':transfer['organization_id'],'e':transfer['entity_id'],'l':transfer['to_location_id'],'w':transfer['to_warehouse_id'],'m':line['item_master_id'],'u':line['uom'],'q':line['quantity']})
            conn.execute(text("UPDATE inventory_transfer SET status='POSTED',posted_at=CURRENT_TIMESTAMP WHERE transfer_id=:t"), {'t':str(transfer_id)})
        return {'transfer_id':str(transfer_id),'status':'POSTED'}

    @app.get('/v90n/inventory/reservations')
    def list_reservations(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, warehouse_id: UUID | None = None, status: str | None = None):
        _require(engine, request, entity_id, location_id, False)
        sql='SELECT * FROM inventory_reservation WHERE organization_id=:o AND entity_id=:e AND location_id=:l'; params={'o':str(organization_id),'e':str(entity_id),'l':str(location_id)}
        if warehouse_id: sql+=' AND warehouse_id=:w'; params['w']=str(warehouse_id)
        if status: sql+=' AND status=:s'; params['s']=status
        sql+=' ORDER BY created_at DESC'
        with engine.connect() as conn: rows=conn.execute(text(sql),params).mappings().all()
        return {'items':[dict(r) for r in rows]}

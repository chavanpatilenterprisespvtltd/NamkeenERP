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


def _require(engine, request: Request, entity_id: UUID, location_id: UUID | None, write: bool, approve: bool = False):
    user = authenticate(request)
    perms = permissions_for_user(engine, user.user_id)
    needed = 'inventory.edit' if write else 'inventory.view'
    if approve:
        needed = 'qc.approve'
    if needed not in perms:
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, str(entity_id), str(location_id) if location_id else None)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def ensure_receiving_qc_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS inventory_grn (
            grn_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, po_id TEXT NULL,
            grn_no TEXT NOT NULL, supplier_id TEXT NOT NULL, received_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'DRAFT', notes TEXT NULL, created_by TEXT NOT NULL,
            approved_by TEXT NULL, approved_at TEXT NULL, approval_reason TEXT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS inventory_grn_line (
            grn_line_id TEXT PRIMARY KEY, grn_id TEXT NOT NULL, po_line_id TEXT NULL, line_no INTEGER NOT NULL,
            item_master_id TEXT NOT NULL, ordered_qty NUMERIC NOT NULL, received_qty NUMERIC NOT NULL,
            accepted_qty NUMERIC NOT NULL DEFAULT 0, rejected_qty NUMERIC NOT NULL DEFAULT 0,
            uom TEXT NOT NULL, unit_rate NUMERIC NULL, supplier_lot_no TEXT NULL,
            mfg_date TEXT NULL, expiry_date TEXT NULL, qc_required INTEGER NOT NULL DEFAULT 1,
            qc_status TEXT NOT NULL DEFAULT 'PENDING', rejection_reason TEXT NULL,
            FOREIGN KEY(grn_id) REFERENCES inventory_grn(grn_id)
        )""",
        """CREATE TABLE IF NOT EXISTS inventory_lot (
            lot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, item_master_id TEXT NOT NULL,
            source_grn_id TEXT NOT NULL, source_grn_line_id TEXT NOT NULL, supplier_id TEXT NOT NULL,
            supplier_lot_no TEXT NULL, lot_code TEXT NOT NULL, mfg_date TEXT NULL, expiry_date TEXT NULL,
            received_qty NUMERIC NOT NULL, accepted_qty NUMERIC NOT NULL, available_qty NUMERIC NOT NULL,
            rejected_qty NUMERIC NOT NULL DEFAULT 0, uom TEXT NOT NULL, qc_status TEXT NOT NULL DEFAULT 'HOLD',
            status TEXT NOT NULL DEFAULT 'QUARANTINE', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS inventory_stock_ledger (
            movement_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, item_master_id TEXT NOT NULL,
            lot_id TEXT NULL, movement_type TEXT NOT NULL, quantity NUMERIC NOT NULL,
            uom TEXT NOT NULL, reference_type TEXT NOT NULL, reference_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'POSTED', created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS inventory_stock_balance (
            organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NOT NULL,
            warehouse_id TEXT NOT NULL, item_master_id TEXT NOT NULL, uom TEXT NOT NULL,
            available_qty NUMERIC NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (organization_id, entity_id, location_id, warehouse_id, item_master_id, uom)
        )""",
        """CREATE TABLE IF NOT EXISTS inventory_qc_result (
            qc_id TEXT PRIMARY KEY, grn_id TEXT NOT NULL, grn_line_id TEXT NOT NULL,
            inspection_no TEXT NOT NULL, inspector_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
            tested_qty NUMERIC NOT NULL, accepted_qty NUMERIC NOT NULL DEFAULT 0,
            rejected_qty NUMERIC NOT NULL DEFAULT 0, reason TEXT NULL, remarks TEXT NULL,
            inspected_at TEXT NOT NULL, approved_by TEXT NULL, approved_at TEXT NULL,
            FOREIGN KEY(grn_id) REFERENCES inventory_grn(grn_id), FOREIGN KEY(grn_line_id) REFERENCES inventory_grn_line(grn_line_id)
        )""",
    ]
    with engine.begin() as conn:
        for s in stmts:
            conn.execute(text(s))


class GRNCreate(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    warehouse_id: UUID
    po_id: UUID
    grn_no: str = Field(min_length=1)
    supplier_id: UUID
    received_at: str | None = None
    notes: str | None = None
    lines: list[dict[str, Any]] = Field(min_length=1)


class QCDecision(BaseModel):
    grn_line_id: UUID
    status: str
    accepted_qty: float = Field(ge=0)
    rejected_qty: float = Field(ge=0)
    reason: str | None = None
    remarks: str | None = None
    inspection_no: str | None = None


class ReleaseDecision(BaseModel):
    reason: str = ''


def _warehouse_ok(engine, warehouse_id: UUID, entity_id: UUID, location_id: UUID):
    with engine.connect() as conn:
        row = conn.execute(text("SELECT warehouse_id FROM erp_warehouses WHERE warehouse_id=:w AND entity_id=:e AND location_id=:l AND active=1"),
                           {'w': str(warehouse_id), 'e': str(entity_id), 'l': str(location_id)}).first()
    if not row:
        raise HTTPException(422, 'Warehouse not found in entity/location scope')


def _po_and_line(engine, po_id: UUID, po_line_id: str, org: UUID, ent: UUID, loc: UUID):
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT p.po_id,p.supplier_id,p.status,pl.line_id,pl.item_master_id,pl.qty,pl.uom,pl.unit_rate
            FROM procurement_po p JOIN procurement_po_line pl ON pl.po_id=p.po_id
            WHERE p.po_id=:p AND p.organization_id=:o AND p.entity_id=:e AND p.location_id=:l AND pl.line_id=:pl
        """), {'p':str(po_id),'o':str(org),'e':str(ent),'l':str(loc),'pl':str(po_line_id)}).mappings().first()
    if not row:
        raise HTTPException(422, 'PO/PO line not found in scope')
    if row['status'] != 'APPROVED':
        raise HTTPException(422, 'Only approved PO can be received')
    return row


def register_v90m_routes(app: FastAPI, engine) -> None:
    ensure_receiving_qc_schema(engine)

    @app.get('/v90m/inventory/overview')
    def overview(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID):
        _require(engine, request, entity_id, location_id, False)
        with engine.connect() as conn:
            counts = {
                'grn': conn.execute(text('SELECT COUNT(*) FROM inventory_grn WHERE organization_id=:o AND entity_id=:e'), {'o':str(organization_id),'e':str(entity_id)}).scalar_one(),
                'lots': conn.execute(text('SELECT COUNT(*) FROM inventory_lot WHERE organization_id=:o AND entity_id=:e'), {'o':str(organization_id),'e':str(entity_id)}).scalar_one(),
                'quarantine_lots': conn.execute(text("SELECT COUNT(*) FROM inventory_lot WHERE organization_id=:o AND entity_id=:e AND status='QUARANTINE'"), {'o':str(organization_id),'e':str(entity_id)}).scalar_one(),
            }
        return {'organization_id':str(organization_id),'entity_id':str(entity_id),'location_id':str(location_id),'counts':counts}

    @app.post('/v90m/inventory/grn')
    def create_grn(body: GRNCreate, request: Request):
        user = _require(engine, request, body.entity_id, body.location_id, True)
        _warehouse_ok(engine, body.warehouse_id, body.entity_id, body.location_id)
        with engine.connect() as conn:
            existing = conn.execute(text('SELECT 1 FROM inventory_grn WHERE organization_id=:o AND grn_no=:n'), {'o':str(body.organization_id),'n':body.grn_no}).first()
        if existing:
            raise HTTPException(409, 'GRN number already exists')
        grn_id = uuid4()
        prepared = []
        for i, line in enumerate(body.lines, 1):
            pol = _po_and_line(engine, body.po_id, str(line.get('po_line_id') or ''), body.organization_id, body.entity_id, body.location_id)
            received = float(line.get('received_qty', 0))
            if received <= 0:
                raise HTTPException(422, 'received_qty must be greater than zero')
            if received > float(pol['qty']):
                raise HTTPException(422, 'received_qty exceeds PO line quantity')
            prepared.append((pol, received, line, i))
        if any(str(line.get('supplier_id') or body.supplier_id) != str(body.supplier_id) for _,_,line,_ in prepared):
            raise HTTPException(422, 'Supplier mismatch')
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO inventory_grn(grn_id,organization_id,entity_id,location_id,warehouse_id,po_id,grn_no,supplier_id,received_at,status,notes,created_by)
                              VALUES (:id,:o,:e,:l,:w,:p,:n,:s,:r,'RECEIVED',:notes,:u)"""),
                         {'id':str(grn_id),'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'w':str(body.warehouse_id),'p':str(body.po_id),'n':body.grn_no,'s':str(body.supplier_id),'r':body.received_at or _now(),'notes':body.notes,'u':str(user.user_id)})
            for pol, received, line, i in prepared:
                conn.execute(text("""INSERT INTO inventory_grn_line(grn_line_id,grn_id,po_line_id,line_no,item_master_id,ordered_qty,received_qty,accepted_qty,rejected_qty,uom,unit_rate,supplier_lot_no,mfg_date,expiry_date,qc_required,qc_status,rejection_reason)
                                  VALUES (:id,:g,:pl,:n,:m,:oq,:rq,0,0,:u,:rate,:lot,:mfg,:exp,:qc,'PENDING',NULL)"""),
                             {'id':str(uuid4()),'g':str(grn_id),'pl':str(pol['line_id']),'n':i,'m':str(pol['item_master_id']),'oq':pol['qty'],'rq':received,'u':str(line.get('uom') or pol['uom']),'rate':pol['unit_rate'],'lot':line.get('supplier_lot_no'),'mfg':line.get('mfg_date'),'exp':line.get('expiry_date'),'qc':1 if line.get('qc_required',True) else 0})
        return {'grn_id':str(grn_id),'status':'RECEIVED','qc_required':True}

    @app.post('/v90m/inventory/qc')
    def record_qc(body: QCDecision, request: Request):
        user = authenticate(request)
        if 'inventory.edit' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        if body.status not in {'PASS','PARTIAL','REJECT'}:
            raise HTTPException(422, 'status must be PASS, PARTIAL or REJECT')
        with engine.connect() as conn:
            row = conn.execute(text("SELECT g.grn_id,g.organization_id,g.entity_id,g.location_id,g.warehouse_id,g.supplier_id,l.item_master_id,l.received_qty,l.uom,l.supplier_lot_no,l.mfg_date,l.expiry_date,l.qc_status FROM inventory_grn_line l JOIN inventory_grn g ON g.grn_id=l.grn_id WHERE l.grn_line_id=:l"), {'l':str(body.grn_line_id)}).mappings().first()
        if not row: raise HTTPException(404, 'GRN line not found')
        _require(engine, request, UUID(str(row['entity_id'])), UUID(str(row['location_id'])), True)
        if body.accepted_qty + body.rejected_qty > float(row['received_qty']):
            raise HTTPException(422, 'Accepted + rejected quantity cannot exceed received quantity')
        if body.status == 'PASS' and abs((body.accepted_qty + body.rejected_qty) - float(row['received_qty'])) > 1e-9:
            raise HTTPException(422, 'PASS requires full disposition of received quantity')
        if body.status == 'REJECT' and body.rejected_qty <= 0:
            raise HTTPException(422, 'REJECT requires rejected quantity')
        qc_id=uuid4(); inspection_no=body.inspection_no or ('QC-'+qc_id.hex[:10].upper())
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO inventory_qc_result(qc_id,grn_id,grn_line_id,inspection_no,inspector_id,status,tested_qty,accepted_qty,rejected_qty,reason,remarks,inspected_at) VALUES (:id,:g,:gl,:no,:u,:s,:t,:a,:r,:reason,:remarks,:at)"), {'id':str(qc_id),'g':str(row['grn_id']),'gl':str(body.grn_line_id),'no':inspection_no,'u':str(user.user_id),'s':body.status,'t':row['received_qty'],'a':body.accepted_qty,'r':body.rejected_qty,'reason':body.reason,'remarks':body.remarks,'at':_now()})
            qstatus='RELEASED' if body.status == 'PASS' else ('PARTIAL' if body.status == 'PARTIAL' else 'REJECTED')
            conn.execute(text("UPDATE inventory_grn_line SET accepted_qty=:a,rejected_qty=:r,qc_status=:s,rejection_reason=:reason WHERE grn_line_id=:l"), {'a':body.accepted_qty,'r':body.rejected_qty,'s':qstatus,'reason':body.reason,'l':str(body.grn_line_id)})
        return {'qc_id':str(qc_id),'grn_line_id':str(body.grn_line_id),'status':qstatus}

    @app.post('/v90m/inventory/qc/{grn_id}/release')
    def release_grn(grn_id: UUID, body: ReleaseDecision, request: Request):
        user = authenticate(request)
        if 'qc.approve' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.connect() as conn:
            grn = conn.execute(text('SELECT * FROM inventory_grn WHERE grn_id=:g'), {'g':str(grn_id)}).mappings().first()
            lines = conn.execute(text('SELECT * FROM inventory_grn_line WHERE grn_id=:g ORDER BY line_no'), {'g':str(grn_id)}).mappings().all()
        if not grn: raise HTTPException(404,'GRN not found')
        if grn['status'] == 'QC_RELEASED': raise HTTPException(409, 'GRN is already QC released')
        # Re-check actual scope using GRN dimensions.
        try:
            assert_entity_location_allowed(engine, user.user_id, str(grn['entity_id']), str(grn['location_id']))
        except PermissionError as exc: raise HTTPException(403,str(exc)) from exc
        if not lines: raise HTTPException(422,'GRN has no lines')
        if any(x['qc_status'] == 'PENDING' for x in lines): raise HTTPException(409,'All GRN lines require QC disposition before release')
        with engine.begin() as conn:
            for line in lines:
                if float(line['accepted_qty']) > 0:
                    lot_id=uuid4(); lot_code=f"{str(grn['grn_no']).strip()}-{line['line_no']:03d}"
                    conn.execute(text("""INSERT INTO inventory_lot(lot_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,source_grn_id,source_grn_line_id,supplier_id,supplier_lot_no,lot_code,mfg_date,expiry_date,received_qty,accepted_qty,available_qty,rejected_qty,uom,qc_status,status)
                                      VALUES (:id,:o,:e,:l,:w,:m,:g,:gl,:s,:sl,:lc,:mfg,:exp,:rq,:aq,:aq,:rej,:u,'RELEASED','AVAILABLE')"""), {'id':str(lot_id),'o':grn['organization_id'],'e':grn['entity_id'],'l':grn['location_id'],'w':grn['warehouse_id'],'m':line['item_master_id'],'g':grn['grn_id'],'gl':line['grn_line_id'],'s':grn['supplier_id'],'sl':line['supplier_lot_no'],'lc':lot_code,'mfg':line['mfg_date'],'exp':line['expiry_date'],'rq':line['received_qty'],'aq':line['accepted_qty'],'rej':line['rejected_qty'],'u':line['uom']})
                    conn.execute(text("INSERT INTO inventory_stock_ledger(movement_id,organization_id,entity_id,location_id,warehouse_id,item_master_id,lot_id,movement_type,quantity,uom,reference_type,reference_id,status,created_by) VALUES (:id,:o,:e,:l,:w,:m,:lot,'RECEIPT',:q,:u,'GRN',:g,'POSTED',:by)"), {'id':str(uuid4()),'o':grn['organization_id'],'e':grn['entity_id'],'l':grn['location_id'],'w':grn['warehouse_id'],'m':line['item_master_id'],'lot':str(lot_id),'q':line['accepted_qty'],'u':line['uom'],'g':grn['grn_id'],'by':str(user.user_id)})
                    conn.execute(text("INSERT INTO inventory_stock_balance(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom,available_qty,updated_at) VALUES (:o,:e,:l,:w,:m,:u,:q,CURRENT_TIMESTAMP) ON CONFLICT(organization_id,entity_id,location_id,warehouse_id,item_master_id,uom) DO UPDATE SET available_qty=inventory_stock_balance.available_qty+excluded.available_qty, updated_at=CURRENT_TIMESTAMP"), {'o':grn['organization_id'],'e':grn['entity_id'],'l':grn['location_id'],'w':grn['warehouse_id'],'m':line['item_master_id'],'u':line['uom'],'q':line['accepted_qty']})
                if float(line['rejected_qty']) > 0:
                    conn.execute(text("UPDATE inventory_lot SET status='REJECTED', qc_status='REJECTED' WHERE 1=0"))
            conn.execute(text("UPDATE inventory_grn SET status='QC_RELEASED',approved_by=:u,approved_at=CURRENT_TIMESTAMP,approval_reason=:r WHERE grn_id=:g"), {'u':str(user.user_id),'r':body.reason,'g':str(grn_id)})
        return {'grn_id':str(grn_id),'status':'QC_RELEASED'}

    @app.get('/v90m/inventory/balances')
    def balances(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, warehouse_id: UUID | None = None):
        _require(engine, request, entity_id, location_id, False)
        sql='SELECT * FROM inventory_stock_balance WHERE organization_id=:o AND entity_id=:e AND location_id=:l'
        params={'o':str(organization_id),'e':str(entity_id),'l':str(location_id)}
        if warehouse_id:
            sql += ' AND warehouse_id=:w'; params['w']=str(warehouse_id)
        sql += ' ORDER BY item_master_id'
        with engine.connect() as conn: rows=conn.execute(text(sql),params).mappings().all()
        return {'items':[dict(r) for r in rows]}

    @app.get('/v90m/inventory/lots')
    def lots(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, warehouse_id: UUID | None = None, qc_status: str | None = None):
        _require(engine, request, entity_id, location_id, False)
        sql='SELECT * FROM inventory_lot WHERE organization_id=:o AND entity_id=:e AND location_id=:l'
        params={'o':str(organization_id),'e':str(entity_id),'l':str(location_id)}
        if warehouse_id:
            sql += ' AND warehouse_id=:w'; params['w']=str(warehouse_id)
        if qc_status:
            sql += ' AND qc_status=:q'; params['q']=qc_status
        sql += ' ORDER BY expiry_date NULLS LAST, created_at'
        with engine.connect() as conn:
            rows=conn.execute(text(sql),params).mappings().all()
        return {'items':[dict(r) for r in rows]}

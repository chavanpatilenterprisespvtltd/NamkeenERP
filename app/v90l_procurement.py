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


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    import json
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _load_json(value):
    import json
    if value is None:
        return {}
    return json.loads(value)


def ensure_procurement_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS procurement_requisition (
            requisition_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL, requested_by TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT',
            required_date TEXT NULL, purpose TEXT NULL, notes TEXT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS procurement_requisition_line (
            line_id TEXT PRIMARY KEY, requisition_id TEXT NOT NULL, line_no INTEGER NOT NULL,
            item_master_id TEXT NOT NULL, description TEXT NULL, qty NUMERIC NOT NULL, uom TEXT NOT NULL,
            required_date TEXT NULL, notes TEXT NULL, FOREIGN KEY(requisition_id) REFERENCES procurement_requisition(requisition_id)
        )""",
        """CREATE TABLE IF NOT EXISTS procurement_quote (
            quote_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            requisition_id TEXT NULL, supplier_id TEXT NOT NULL, quote_no TEXT NOT NULL,
            quote_date TEXT NULL, valid_until TEXT NULL, currency TEXT NOT NULL DEFAULT 'INR',
            status TEXT NOT NULL DEFAULT 'RECEIVED', notes TEXT NULL, created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS procurement_quote_line (
            line_id TEXT PRIMARY KEY, quote_id TEXT NOT NULL, line_no INTEGER NOT NULL,
            item_master_id TEXT NOT NULL, qty NUMERIC NOT NULL, uom TEXT NOT NULL,
            unit_rate NUMERIC NOT NULL, tax_rate NUMERIC NULL, freight NUMERIC NULL, discount NUMERIC NULL,
            notes TEXT NULL, FOREIGN KEY(quote_id) REFERENCES procurement_quote(quote_id)
        )""",
        """CREATE TABLE IF NOT EXISTS procurement_po (
            po_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL, supplier_id TEXT NOT NULL, requisition_id TEXT NULL,
            quote_id TEXT NULL, po_no TEXT NOT NULL, po_date TEXT NOT NULL, expected_date TEXT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING_APPROVAL', currency TEXT NOT NULL DEFAULT 'INR',
            payment_terms_days INTEGER NULL, delivery_terms TEXT NULL, notes TEXT NULL,
            requested_by TEXT NOT NULL, approved_by TEXT NULL, approved_at TEXT NULL, approval_reason TEXT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS procurement_po_line (
            line_id TEXT PRIMARY KEY, po_id TEXT NOT NULL, line_no INTEGER NOT NULL,
            item_master_id TEXT NOT NULL, description TEXT NULL, qty NUMERIC NOT NULL, uom TEXT NOT NULL,
            unit_rate NUMERIC NOT NULL, discount NUMERIC NULL, tax_rate NUMERIC NULL, expected_date TEXT NULL,
            notes TEXT NULL, FOREIGN KEY(po_id) REFERENCES procurement_po(po_id)
        )""",
        """CREATE TABLE IF NOT EXISTS procurement_grn_prep (
            grn_prep_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, po_id TEXT NOT NULL,
            reference_no TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT', notes TEXT NULL,
            prepared_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS procurement_grn_prep_line (
            line_id TEXT PRIMARY KEY, grn_prep_id TEXT NOT NULL, po_line_id TEXT NOT NULL,
            ordered_qty NUMERIC NOT NULL, planned_receive_qty NUMERIC NOT NULL, uom TEXT NOT NULL,
            lot_capture_required INTEGER NOT NULL DEFAULT 1, notes TEXT NULL,
            FOREIGN KEY(grn_prep_id) REFERENCES procurement_grn_prep(grn_prep_id)
        )""",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))


class RequisitionLineIn(BaseModel):
    item_master_id: UUID
    description: str | None = None
    qty: float = Field(gt=0)
    uom: str = Field(min_length=1)
    required_date: str | None = None
    notes: str | None = None


class RequisitionIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    purpose: str | None = None
    required_date: str | None = None
    notes: str | None = None
    lines: list[RequisitionLineIn] = Field(min_length=1)


class QuoteLineIn(BaseModel):
    item_master_id: UUID
    qty: float = Field(gt=0)
    uom: str = Field(min_length=1)
    unit_rate: float = Field(ge=0)
    tax_rate: float | None = Field(default=None, ge=0)
    freight: float | None = Field(default=None, ge=0)
    discount: float | None = Field(default=None, ge=0)
    notes: str | None = None


class QuoteIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    supplier_id: UUID
    requisition_id: UUID | None = None
    quote_no: str = Field(min_length=1)
    quote_date: str | None = None
    valid_until: str | None = None
    notes: str | None = None
    lines: list[QuoteLineIn] = Field(min_length=1)


class POLineIn(BaseModel):
    item_master_id: UUID
    description: str | None = None
    qty: float = Field(gt=0)
    uom: str = Field(min_length=1)
    unit_rate: float = Field(ge=0)
    discount: float | None = Field(default=None, ge=0)
    tax_rate: float | None = Field(default=None, ge=0)
    expected_date: str | None = None
    notes: str | None = None


class POIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    supplier_id: UUID
    requisition_id: UUID | None = None
    quote_id: UUID | None = None
    po_no: str = Field(min_length=1)
    po_date: str | None = None
    expected_date: str | None = None
    payment_terms_days: int | None = Field(default=None, ge=0)
    delivery_terms: str | None = None
    notes: str | None = None
    lines: list[POLineIn] = Field(min_length=1)


class DecisionIn(BaseModel):
    reason: str = ""


class GRNPrepIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    warehouse_id: UUID
    po_id: UUID
    reference_no: str = Field(min_length=1)
    notes: str | None = None
    lines: list[dict[str, Any]] = Field(min_length=1)


def _require(engine, request: Request, entity_id: UUID, location_id: UUID | None, write: bool, approve: bool = False):
    user = authenticate(request)
    perms = permissions_for_user(engine, user.user_id)
    needed = "procurement.approve" if approve else ("procurement.edit" if write else "procurement.view")
    if needed not in perms:
        raise HTTPException(403, "permission denied")
    try:
        assert_entity_location_allowed(engine, user.user_id, str(entity_id) if entity_id else None, str(location_id) if location_id else None)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def _master_exists(engine, organization_id: UUID, master_type: str, master_id: UUID, entity_id: UUID | None = None):
    row = None
    with engine.connect() as conn:
        row = conn.execute(text("SELECT master_id, entity_id, active, data FROM master_record WHERE replace(lower(organization_id),'-','')=replace(lower(:o),'-','') AND master_type=:t AND replace(lower(master_id),'-','')=replace(lower(:m),'-','')"),
                           {"o": str(organization_id), "t": master_type, "m": str(master_id)}).mappings().first()
    if not row or not row["active"]:
        raise HTTPException(422, f"Referenced {master_type} not found")
    if entity_id is not None and row["entity_id"] not in (None, str(entity_id), str(entity_id).replace("-", "")):
        raise HTTPException(422, f"Referenced {master_type} is outside entity scope")
    return row


def _warehouse_exists(engine, warehouse_id: UUID, entity_id: UUID, location_id: UUID):
    with engine.connect() as conn:
        row = conn.execute(text("SELECT warehouse_id FROM erp_warehouses WHERE warehouse_id=:w AND entity_id=:e AND location_id=:l AND active=1"),
                           {"w": str(warehouse_id), "e": str(entity_id), "l": str(location_id)}).first()
    if not row:
        raise HTTPException(422, "Warehouse not found in entity/location scope")


def register_v90l_routes(app: FastAPI, engine) -> None:
    ensure_procurement_schema(engine)

    @app.get('/v90l/procurement/overview')
    def overview(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID):
        _require(engine, request, entity_id, location_id, False)
        with engine.connect() as conn:
            counts = {}
            for table, key in (("procurement_requisition", "requisitions"), ("procurement_quote", "quotes"), ("procurement_po", "purchase_orders"), ("procurement_grn_prep", "grn_preparation")):
                counts[key] = conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE organization_id=:o AND entity_id=:e"), {"o": str(organization_id), "e": str(entity_id)}).scalar_one()
        return {"organization_id": str(organization_id), "entity_id": str(entity_id), "location_id": str(location_id), "counts": counts}

    @app.post('/v90l/procurement/requisitions')
    def create_requisition(body: RequisitionIn, request: Request):
        user = _require(engine, request, body.entity_id, body.location_id, True)
        for line in body.lines:
            _master_exists(engine, body.organization_id, "PRODUCT", line.item_master_id, body.entity_id)
        rid = uuid4()
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO procurement_requisition(requisition_id,organization_id,entity_id,location_id,requested_by,status,required_date,purpose,notes) VALUES (:id,:o,:e,:l,:u,'DRAFT',:rd,:p,:n)"),
                         {"id": str(rid), "o": str(body.organization_id), "e": str(body.entity_id), "l": str(body.location_id), "u": str(user.user_id), "rd": body.required_date, "p": body.purpose, "n": body.notes})
            for i, line in enumerate(body.lines, 1):
                conn.execute(text("INSERT INTO procurement_requisition_line(line_id,requisition_id,line_no,item_master_id,description,qty,uom,required_date,notes) VALUES (:id,:r,:n,:m,:d,:q,:u,:rd,:notes)"),
                             {"id": str(uuid4()), "r": str(rid), "n": i, "m": str(line.item_master_id), "d": line.description, "q": line.qty, "u": line.uom, "rd": line.required_date, "notes": line.notes})
        return {"requisition_id": str(rid), "status": "DRAFT"}

    @app.post('/v90l/procurement/requisitions/{requisition_id}/submit')
    def submit_requisition(requisition_id: UUID, request: Request):
        user = authenticate(request)
        if 'procurement.edit' not in permissions_for_user(engine, user.user_id): raise HTTPException(403, 'permission denied')
        with engine.begin() as conn:
            row = conn.execute(text("SELECT entity_id, location_id, status FROM procurement_requisition WHERE requisition_id=:r"), {"r": str(requisition_id)}).mappings().first()
            if not row: raise HTTPException(404, 'requisition not found')
            if row['status'] != 'DRAFT': raise HTTPException(409, 'only draft requisitions can be submitted')
            try:
                assert_entity_location_allowed(engine, user.user_id, str(row['entity_id']), str(row['location_id']))
            except PermissionError as exc:
                raise HTTPException(403, str(exc)) from exc
            conn.execute(text("UPDATE procurement_requisition SET status='PENDING_APPROVAL', updated_at=CURRENT_TIMESTAMP WHERE requisition_id=:r"), {"r": str(requisition_id)})
        return {"requisition_id": str(requisition_id), "status": "PENDING_APPROVAL"}

    @app.post('/v90l/procurement/quotes')
    def create_quote(body: QuoteIn, request: Request):
        user = _require(engine, request, body.entity_id, None, True)
        for line in body.lines:
            _master_exists(engine, body.organization_id, "PRODUCT", line.item_master_id, body.entity_id)
        if body.requisition_id:
            with engine.connect() as conn:
                ok = conn.execute(text("SELECT 1 FROM procurement_requisition WHERE requisition_id=:r AND organization_id=:o AND entity_id=:e"), {"r": str(body.requisition_id), "o": str(body.organization_id), "e": str(body.entity_id)}).first()
            if not ok: raise HTTPException(422, 'Requisition not found in scope')
        _master_exists(engine, body.organization_id, "SUPPLIER", body.supplier_id, body.entity_id)
        qid = uuid4()
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO procurement_quote(quote_id,organization_id,entity_id,requisition_id,supplier_id,quote_no,quote_date,valid_until,status,notes,created_by) VALUES (:id,:o,:e,:r,:s,:qn,:qd,:vu,'RECEIVED',:n,:u)"),
                         {"id": str(qid), "o": str(body.organization_id), "e": str(body.entity_id), "r": str(body.requisition_id) if body.requisition_id else None, "s": str(body.supplier_id), "qn": body.quote_no, "qd": body.quote_date, "vu": body.valid_until, "n": body.notes, "u": str(user.user_id)})
            for i, line in enumerate(body.lines, 1):
                conn.execute(text("INSERT INTO procurement_quote_line(line_id,quote_id,line_no,item_master_id,qty,uom,unit_rate,tax_rate,freight,discount,notes) VALUES (:id,:q,:n,:m,:qty,:u,:r,:t,:f,:d,:notes)"),
                             {"id": str(uuid4()), "q": str(qid), "n": i, "m": str(line.item_master_id), "qty": line.qty, "u": line.uom, "r": line.unit_rate, "t": line.tax_rate, "f": line.freight, "d": line.discount, "notes": line.notes})
        return {"quote_id": str(qid), "status": "RECEIVED"}

    @app.post('/v90l/procurement/purchase-orders')
    def create_po(body: POIn, request: Request):
        user = _require(engine, request, body.entity_id, body.location_id, True)
        _master_exists(engine, body.organization_id, "SUPPLIER", body.supplier_id, body.entity_id)
        if body.requisition_id:
            with engine.connect() as conn:
                if not conn.execute(text("SELECT 1 FROM procurement_requisition WHERE requisition_id=:r AND organization_id=:o AND entity_id=:e AND status IN ('PENDING_APPROVAL','APPROVED')"), {"r":str(body.requisition_id),"o":str(body.organization_id),"e":str(body.entity_id)}).first():
                    raise HTTPException(422, 'Requisition is not eligible for PO')
        if body.quote_id:
            with engine.connect() as conn:
                if not conn.execute(text("SELECT 1 FROM procurement_quote WHERE quote_id=:q AND organization_id=:o AND entity_id=:e AND supplier_id=:s"), {"q":str(body.quote_id),"o":str(body.organization_id),"e":str(body.entity_id),"s":str(body.supplier_id)}).first():
                    raise HTTPException(422, 'Quote is not valid for this supplier/entity')
        for line in body.lines:
            _master_exists(engine, body.organization_id, "PRODUCT", line.item_master_id, body.entity_id)
        poid = uuid4(); po_date = body.po_date or _now()
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO procurement_po(po_id,organization_id,entity_id,location_id,supplier_id,requisition_id,quote_id,po_no,po_date,expected_date,status,currency,payment_terms_days,delivery_terms,notes,requested_by) VALUES (:id,:o,:e,:l,:s,:r,:q,:pn,:pd,:ed,'PENDING_APPROVAL','INR',:pt,:dt,:n,:u)"),
                         {"id":str(poid),"o":str(body.organization_id),"e":str(body.entity_id),"l":str(body.location_id),"s":str(body.supplier_id),"r":str(body.requisition_id) if body.requisition_id else None,"q":str(body.quote_id) if body.quote_id else None,"pn":body.po_no,"pd":po_date,"ed":body.expected_date,"pt":body.payment_terms_days,"dt":body.delivery_terms,"n":body.notes,"u":str(user.user_id)})
            for i,line in enumerate(body.lines,1):
                conn.execute(text("INSERT INTO procurement_po_line(line_id,po_id,line_no,item_master_id,description,qty,uom,unit_rate,discount,tax_rate,expected_date,notes) VALUES (:id,:p,:n,:m,:d,:q,:u,:r,:di,:t,:ed,:notes)"),
                             {"id":str(uuid4()),"p":str(poid),"n":i,"m":str(line.item_master_id),"d":line.description,"q":line.qty,"u":line.uom,"r":line.unit_rate,"di":line.discount,"t":line.tax_rate,"ed":line.expected_date,"notes":line.notes})
        return {"po_id":str(poid),"status":"PENDING_APPROVAL"}

    @app.post('/v90l/procurement/purchase-orders/{po_id}/approve')
    def approve_po(po_id: UUID, body: DecisionIn, request: Request):
        user = authenticate(request)
        if 'procurement.approve' not in permissions_for_user(engine, user.user_id): raise HTTPException(403, 'permission denied')
        with engine.begin() as conn:
            row = conn.execute(text("SELECT status, requested_by FROM procurement_po WHERE po_id=:p"), {"p":str(po_id)}).mappings().first()
            if not row: raise HTTPException(404, 'purchase order not found')
            if row['status'] != 'PENDING_APPROVAL': raise HTTPException(409, 'only pending purchase orders can be approved')
            if str(row['requested_by']) == str(user.user_id): raise HTTPException(409, 'self-approval is not allowed')
            conn.execute(text("UPDATE procurement_po SET status='APPROVED', approved_by=:u, approved_at=CURRENT_TIMESTAMP, approval_reason=:r, updated_at=CURRENT_TIMESTAMP WHERE po_id=:p"), {"u":str(user.user_id),"r":body.reason,"p":str(po_id)})
        return {"po_id":str(po_id),"status":"APPROVED"}

    @app.post('/v90l/procurement/grn-preparations')
    def prepare_grn(body: GRNPrepIn, request: Request):
        user = _require(engine, request, body.entity_id, body.location_id, True)
        _warehouse_exists(engine, body.warehouse_id, body.entity_id, body.location_id)
        with engine.connect() as conn:
            po = conn.execute(text("SELECT status FROM procurement_po WHERE po_id=:p AND organization_id=:o AND entity_id=:e AND location_id=:l"), {"p":str(body.po_id),"o":str(body.organization_id),"e":str(body.entity_id),"l":str(body.location_id)}).first()
        if not po or po[0] != 'APPROVED': raise HTTPException(422, 'Only approved PO can create GRN preparation')
        with engine.begin() as conn:
            po_lines = conn.execute(text("SELECT line_id,qty,uom FROM procurement_po_line WHERE po_id=:p ORDER BY line_no"), {"p":str(body.po_id)}).mappings().all()
            by_id = {str(x['line_id']): x for x in po_lines}
            by_no = {str(i+1): x for i,x in enumerate(po_lines)}
            gid=uuid4()
            conn.execute(text("INSERT INTO procurement_grn_prep(grn_prep_id,organization_id,entity_id,location_id,warehouse_id,po_id,reference_no,status,notes,prepared_by) VALUES (:id,:o,:e,:l,:w,:p,:r,'DRAFT',:n,:u)"), {"id":str(gid),"o":str(body.organization_id),"e":str(body.entity_id),"l":str(body.location_id),"w":str(body.warehouse_id),"p":str(body.po_id),"r":body.reference_no,"n":body.notes,"u":str(user.user_id)})
            for line in body.lines:
                pol = by_id.get(str(line.get('po_line_id'))) or by_no.get(str(line.get('line_no')))
                if not pol: raise HTTPException(422, 'Invalid PO line reference')
                receive = float(line.get('planned_receive_qty', 0))
                if receive <= 0: raise HTTPException(422, 'planned_receive_qty must be greater than zero')
                if receive > float(pol['qty']): raise HTTPException(422, 'planned receipt exceeds ordered quantity')
                conn.execute(text("INSERT INTO procurement_grn_prep_line(line_id,grn_prep_id,po_line_id,ordered_qty,planned_receive_qty,uom,lot_capture_required,notes) VALUES (:id,:g,:pl,:oq,:rq,:u,:lot,:n)"), {"id":str(uuid4()),"g":str(gid),"pl":str(line.get('po_line_id') or pol['line_id']),"oq":pol['qty'],"rq":receive,"u":str(line.get('uom') or pol['uom']),"lot":1 if line.get('lot_capture_required', True) else 0,"n":line.get('notes')})
        return {"grn_prep_id":str(gid),"status":"DRAFT"}

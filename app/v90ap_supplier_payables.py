from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed

BUCKETS = ("CURRENT", "1_30", "31_60", "61_90", "91_180", "181_PLUS")


class SupplierInvoiceIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    supplier_id: UUID
    po_id: UUID | None = None
    invoice_no: str = Field(min_length=1, max_length=80)
    invoice_date: date
    due_date: date | None = None
    subtotal: float = Field(ge=0)
    tax_amount: float = Field(ge=0)
    grand_total: float = Field(gt=0)
    notes: str | None = None


class SupplierPaymentIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    supplier_id: UUID
    amount: float = Field(gt=0)
    mode: str = Field(min_length=2, max_length=30)
    payment_date: date
    reference_no: str = Field(min_length=1, max_length=100)
    notes: str | None = None


class SupplierAllocationIn(BaseModel):
    invoice_id: UUID
    amount: float = Field(gt=0)


def ensure_v90ap_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS supplier_invoices (
            supplier_invoice_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            supplier_id TEXT NOT NULL,
            po_id TEXT NULL,
            invoice_no TEXT NOT NULL,
            invoice_date DATE NOT NULL,
            due_date DATE NULL,
            subtotal NUMERIC NOT NULL,
            tax_amount NUMERIC NOT NULL,
            grand_total NUMERIC NOT NULL,
            status TEXT NOT NULL DEFAULT 'POSTED',
            notes TEXT NULL,
            created_by TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(entity_id, invoice_no)
        )""",
        """CREATE TABLE IF NOT EXISTS supplier_payment_transactions (
            supplier_payment_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            supplier_id TEXT NOT NULL,
            amount NUMERIC NOT NULL,
            mode TEXT NOT NULL,
            payment_date DATE NOT NULL,
            reference_no TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'POSTED',
            notes TEXT NULL,
            created_by TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(entity_id, reference_no)
        )""",
        """CREATE TABLE IF NOT EXISTS supplier_payment_allocations (
            allocation_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            supplier_id TEXT NOT NULL,
            supplier_payment_id TEXT NOT NULL,
            supplier_invoice_id TEXT NOT NULL,
            amount NUMERIC NOT NULL,
            status TEXT NOT NULL DEFAULT 'POSTED',
            allocated_by TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(supplier_payment_id, supplier_invoice_id)
        )""",
        """CREATE TABLE IF NOT EXISTS supplier_payable_followups (
            followup_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            location_id TEXT NULL,
            supplier_id TEXT NOT NULL,
            follow_up_date DATE NOT NULL,
            mode TEXT NOT NULL,
            note TEXT NOT NULL,
            assigned_to_user_id TEXT NULL,
            created_by TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_supplier_invoices_aging ON supplier_invoices(entity_id,supplier_id,due_date,status)",
        "CREATE INDEX IF NOT EXISTS ix_supplier_payments_supplier ON supplier_payment_transactions(entity_id,supplier_id,payment_date,status)",
        "CREATE INDEX IF NOT EXISTS ix_supplier_alloc_invoice ON supplier_payment_allocations(entity_id,supplier_invoice_id,status)",
        "CREATE INDEX IF NOT EXISTS ix_supplier_followups ON supplier_payable_followups(entity_id,supplier_id,follow_up_date)",
        "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('payables.view','View supplier payables and ageing') ON CONFLICT(permission_id) DO NOTHING",
        "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('payables.edit','Create supplier invoices and payments') ON CONFLICT(permission_id) DO NOTHING",
        "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('payables.allocate','Allocate supplier payments') ON CONFLICT(permission_id) DO NOTHING",
        "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('payables.followup','Record supplier payment follow-up') ON CONFLICT(permission_id) DO NOTHING",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))
        for role in ("manager", "super_admin", "accounts"):
            for perm in ("payables.view", "payables.edit", "payables.allocate", "payables.followup"):
                conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"), {"r": role, "p": perm})
        for role in ("purchase",):
            for perm in ("payables.view", "payables.edit"):
                conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"), {"r": role, "p": perm})


def _require(engine, request: Request, permission: str, entity_id: str, location_id: str | None):
    user = authenticate(request)
    if permission not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, "permission denied")
    try:
        assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def _supplier_exists(conn, organization_id: str, entity_id: str, supplier_id: str) -> bool:
    row = conn.execute(
        text("""SELECT master_id FROM master_record
                WHERE replace(lower(master_id),'-','')=replace(lower(:m),'-','')
                  AND replace(lower(organization_id),'-','')=replace(lower(:o),'-','')
                  AND master_type='SUPPLIER' AND active=1
                  AND (entity_id IS NULL OR replace(lower(entity_id),'-','')=replace(lower(:e),'-',''))"""),
        {"m": supplier_id, "o": organization_id, "e": entity_id},
    ).first()
    return row is not None


def _invoice_aging(engine, entity_id: str, supplier_id: str, as_of: date):
    with engine.connect() as conn:
        invoices = conn.execute(
            text("""SELECT supplier_invoice_id,organization_id,entity_id,location_id,supplier_id,po_id,invoice_no,
                          invoice_date,due_date,subtotal,tax_amount,grand_total,status
                   FROM supplier_invoices
                   WHERE entity_id=:e AND supplier_id=:s AND status='POSTED'
                   ORDER BY invoice_date, supplier_invoice_id"""),
            {"e": entity_id, "s": supplier_id},
        ).mappings().all()
        out = []
        for inv in invoices:
            due = _as_date(inv["due_date"]) if inv["due_date"] else _as_date(inv["invoice_date"])
            allocated = float(conn.execute(text("SELECT COALESCE(SUM(amount),0) FROM supplier_payment_allocations WHERE supplier_invoice_id=:i AND status='POSTED'"), {"i": inv["supplier_invoice_id"]}).scalar() or 0)
            outstanding = max(0.0, float(inv["grand_total"] or 0) - allocated)
            if outstanding <= 1e-9:
                continue
            overdue_days = max(0, (as_of - due).days)
            if as_of < due:
                bucket = "CURRENT"
            elif overdue_days <= 30:
                bucket = "1_30"
            elif overdue_days <= 60:
                bucket = "31_60"
            elif overdue_days <= 90:
                bucket = "61_90"
            elif overdue_days <= 180:
                bucket = "91_180"
            else:
                bucket = "181_PLUS"
            out.append({
                "supplier_invoice_id": str(inv["supplier_invoice_id"]),
                "invoice_no": inv["invoice_no"],
                "invoice_date": _as_date(inv["invoice_date"]).isoformat(),
                "due_date": due.isoformat(),
                "days_overdue": overdue_days,
                "bucket": bucket,
                "invoice_total": round(float(inv["grand_total"] or 0), 2),
                "allocated_amount": round(allocated, 2),
                "outstanding": round(outstanding, 2),
            })
        return out


def register_v90ap_routes(app: FastAPI, engine) -> None:
    ensure_v90ap_schema(engine)

    @app.post("/v90ap/supplier-invoices")
    def create_supplier_invoice(body: SupplierInvoiceIn, request: Request):
        user = _require(engine, request, "payables.edit", str(body.entity_id), str(body.location_id))
        if abs((body.subtotal + body.tax_amount) - body.grand_total) > 0.01:
            raise HTTPException(422, "grand_total must equal subtotal + tax_amount")
        with engine.begin() as conn:
            if not _supplier_exists(conn, str(body.organization_id), str(body.entity_id), str(body.supplier_id)):
                raise HTTPException(422, "supplier not found in organization/entity scope")
            if body.po_id:
                po = conn.execute(text("SELECT entity_id,organization_id FROM procurement_po WHERE po_id=:p"), {"p": str(body.po_id)}).first()
                if not po:
                    raise HTTPException(422, "purchase order not found")
                if str(po[0]) != str(body.entity_id) or str(po[1]) != str(body.organization_id):
                    raise HTTPException(409, "purchase order scope mismatch")
            iid = str(uuid4())
            try:
                conn.execute(text("""INSERT INTO supplier_invoices
                    (supplier_invoice_id,organization_id,entity_id,location_id,supplier_id,po_id,invoice_no,invoice_date,due_date,subtotal,tax_amount,grand_total,status,notes,created_by)
                    VALUES(:i,:o,:e,:l,:s,:p,:n,:d,:dd,:sub,:tax,:gt,'POSTED',:notes,:u)"""), {
                    "i": iid, "o": str(body.organization_id), "e": str(body.entity_id), "l": str(body.location_id),
                    "s": str(body.supplier_id), "p": str(body.po_id) if body.po_id else None, "n": body.invoice_no,
                    "d": body.invoice_date, "dd": body.due_date, "sub": body.subtotal, "tax": body.tax_amount,
                    "gt": body.grand_total, "notes": body.notes, "u": str(user.user_id),
                })
            except Exception as exc:
                if "UNIQUE" in str(exc).upper():
                    raise HTTPException(409, "supplier invoice number already exists for this entity") from exc
                raise
        return {"status": "created", "supplier_invoice_id": iid}

    @app.post("/v90ap/supplier-payments")
    def create_supplier_payment(body: SupplierPaymentIn, request: Request):
        user = _require(engine, request, "payables.edit", str(body.entity_id), str(body.location_id))
        with engine.begin() as conn:
            if not _supplier_exists(conn, str(body.organization_id), str(body.entity_id), str(body.supplier_id)):
                raise HTTPException(422, "supplier not found in organization/entity scope")
            pid = str(uuid4())
            try:
                conn.execute(text("""INSERT INTO supplier_payment_transactions
                    (supplier_payment_id,organization_id,entity_id,location_id,supplier_id,amount,mode,payment_date,reference_no,status,notes,created_by)
                    VALUES(:p,:o,:e,:l,:s,:a,:m,:d,:r,'POSTED',:n,:u)"""), {
                    "p": pid, "o": str(body.organization_id), "e": str(body.entity_id), "l": str(body.location_id),
                    "s": str(body.supplier_id), "a": body.amount, "m": body.mode.upper(), "d": body.payment_date,
                    "r": body.reference_no, "n": body.notes, "u": str(user.user_id),
                })
            except Exception as exc:
                if "UNIQUE" in str(exc).upper():
                    raise HTTPException(409, "payment reference already exists for this entity") from exc
                raise
        return {"status": "created", "supplier_payment_id": pid}

    @app.post("/v90ap/supplier-payments/{payment_id}/allocate")
    def allocate_supplier_payment(payment_id: UUID, body: SupplierAllocationIn, request: Request):
        with engine.connect() as conn:
            p = conn.execute(text("SELECT * FROM supplier_payment_transactions WHERE supplier_payment_id=:p"), {"p": str(payment_id)}).mappings().first()
            inv = conn.execute(text("SELECT * FROM supplier_invoices WHERE supplier_invoice_id=:i"), {"i": str(body.invoice_id)}).mappings().first()
        if not p:
            raise HTTPException(404, "supplier payment not found")
        if not inv:
            raise HTTPException(404, "supplier invoice not found")
        user = _require(engine, request, "payables.allocate", str(p["entity_id"]), str(p["location_id"]))
        if str(p["supplier_id"]) != str(inv["supplier_id"]) or str(p["entity_id"]) != str(inv["entity_id"]) or str(p["organization_id"]) != str(inv["organization_id"]):
            raise HTTPException(409, "payment and invoice scope mismatch")
        with engine.begin() as conn:
            total_alloc = float(conn.execute(text("SELECT COALESCE(SUM(amount),0) FROM supplier_payment_allocations WHERE supplier_payment_id=:p AND status='POSTED'"), {"p": str(payment_id)}).scalar() or 0)
            invoice_alloc = float(conn.execute(text("SELECT COALESCE(SUM(amount),0) FROM supplier_payment_allocations WHERE supplier_invoice_id=:i AND status='POSTED'"), {"i": str(body.invoice_id)}).scalar() or 0)
            unallocated = max(0.0, float(p["amount"]) - total_alloc)
            invoice_open = max(0.0, float(inv["grand_total"]) - invoice_alloc)
            if body.amount > unallocated + 0.005:
                raise HTTPException(409, "allocation exceeds unallocated supplier payment")
            if body.amount > invoice_open + 0.005:
                raise HTTPException(409, "allocation exceeds supplier invoice outstanding")
            existing = conn.execute(text("SELECT allocation_id FROM supplier_payment_allocations WHERE supplier_payment_id=:p AND supplier_invoice_id=:i"), {"p": str(payment_id), "i": str(body.invoice_id)}).first()
            if existing:
                raise HTTPException(409, "supplier payment is already allocated to this invoice")
            aid = str(uuid4())
            conn.execute(text("""INSERT INTO supplier_payment_allocations
                (allocation_id,organization_id,entity_id,location_id,supplier_id,supplier_payment_id,supplier_invoice_id,amount,status,allocated_by)
                VALUES(:a,:o,:e,:l,:s,:p,:i,:amt,'POSTED',:u)"""), {
                    "a": aid, "o": str(p["organization_id"]), "e": str(p["entity_id"]), "l": str(p["location_id"]),
                    "s": str(p["supplier_id"]), "p": str(payment_id), "i": str(body.invoice_id), "amt": body.amount, "u": str(user.user_id),
                })
        return {"status": "ALLOCATED", "allocation_id": aid, "unallocated_amount": round(unallocated - body.amount, 2), "invoice_outstanding": round(invoice_open - body.amount, 2)}

    @app.get("/v90ap/suppliers/{supplier_id}/aging")
    def supplier_aging(supplier_id: UUID, request: Request, entity_id: UUID, as_of_date: date | None = None):
        _require(engine, request, "payables.view", str(entity_id), None)
        as_of = as_of_date or date.today()
        rows = _invoice_aging(engine, str(entity_id), str(supplier_id), as_of)
        buckets = {b: 0.0 for b in BUCKETS}
        for r in rows:
            buckets[r["bucket"]] += r["outstanding"]
        overdue = sum(v for b, v in buckets.items() if b != "CURRENT")
        return {
            "supplier_id": str(supplier_id), "entity_id": str(entity_id), "as_of_date": as_of.isoformat(),
            "invoices": rows, "buckets": {k: round(v, 2) for k, v in buckets.items()},
            "summary": {"total_outstanding": round(sum(buckets.values()), 2), "overdue_amount": round(overdue, 2), "current_amount": round(buckets["CURRENT"], 2), "invoice_count": len(rows)},
        }

    @app.get("/v90ap/overdue")
    def overdue(request: Request, entity_id: UUID, min_days_overdue: int = 1, as_of_date: date | None = None):
        _require(engine, request, "payables.view", str(entity_id), None)
        as_of = as_of_date or date.today()
        with engine.connect() as conn:
            suppliers = conn.execute(text("SELECT DISTINCT supplier_id FROM supplier_invoices WHERE entity_id=:e AND status='POSTED'"), {"e": str(entity_id)}).scalars().all()
        items = []
        for supplier_id in suppliers:
            for row in _invoice_aging(engine, str(entity_id), str(supplier_id), as_of):
                if row["days_overdue"] >= min_days_overdue and row["bucket"] != "CURRENT":
                    items.append(row | {"supplier_id": str(supplier_id)})
        items.sort(key=lambda x: (-x["days_overdue"], -x["outstanding"]))
        return {"entity_id": str(entity_id), "as_of_date": as_of.isoformat(), "count": len(items), "total_overdue": round(sum(x["outstanding"] for x in items), 2), "items": items}

    @app.post("/v90ap/followups")
    def create_followup(body: dict, request: Request):
        entity_id = str(body.get("entity_id")); supplier_id = str(body.get("supplier_id"))
        user = _require(engine, request, "payables.followup", entity_id, str(body.get("location_id")) if body.get("location_id") else None)
        note = str(body.get("note", "")).strip()
        mode = str(body.get("mode", "")).strip()
        if not note or not mode or not body.get("follow_up_date"):
            raise HTTPException(422, "follow_up_date, mode and note are required")
        with engine.begin() as conn:
            fid = str(uuid4())
            conn.execute(text("""INSERT INTO supplier_payable_followups
                (followup_id,organization_id,entity_id,location_id,supplier_id,follow_up_date,mode,note,assigned_to_user_id,created_by)
                VALUES(:f,:o,:e,:l,:s,:d,:m,:n,:a,:u)"""), {
                    "f": fid, "o": str(body.get("organization_id", "")), "e": entity_id,
                    "l": body.get("location_id"), "s": supplier_id, "d": body["follow_up_date"],
                    "m": mode, "n": note, "a": body.get("assigned_to_user_id"), "u": str(user.user_id),
                })
        return {"status": "created", "followup_id": fid}

from __future__ import annotations
from datetime import date
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


class AllocationIn(BaseModel):
    invoice_id: UUID
    amount: float = Field(gt=0)


class DepositIn(BaseModel):
    deposit_ref: str = Field(min_length=2, max_length=120)
    deposit_date: date
    notes: str = ''


class ChequeClearIn(BaseModel):
    clearance_ref: str = Field(min_length=2, max_length=120)
    cleared_date: date
    notes: str = ''


def ensure_v90ak_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS payment_allocations (
            allocation_id TEXT PRIMARY KEY,
            payment_id TEXT NOT NULL,
            invoice_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            amount NUMERIC NOT NULL CHECK(amount > 0),
            status TEXT NOT NULL DEFAULT 'POSTED',
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(payment_id, invoice_id)
        )""",
        """CREATE TABLE IF NOT EXISTS cash_collection_events (
            collection_event_id TEXT PRIMARY KEY,
            payment_id TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            evidence_file_id TEXT,
            handover_at TEXT,
            deposited_at TEXT,
            deposit_ref TEXT,
            deposit_date TEXT,
            verified_by TEXT,
            verified_at TEXT,
            reason TEXT,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS payment_lifecycle_events (
            lifecycle_event_id TEXT PRIMARY KEY,
            payment_id TEXT NOT NULL,
            from_status TEXT,
            to_status TEXT NOT NULL,
            event_type TEXT NOT NULL,
            reference_no TEXT,
            notes TEXT,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_payment_allocations_payment ON payment_allocations(payment_id,status)",
        "CREATE INDEX IF NOT EXISTS ix_payment_allocations_invoice ON payment_allocations(invoice_id,status)",
        "CREATE INDEX IF NOT EXISTS ix_payment_lifecycle_payment ON payment_lifecycle_events(payment_id,created_at)",
        "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('collections.view','View collection lifecycle') ON CONFLICT(permission_id) DO NOTHING",
        "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('collections.edit','Record collection lifecycle') ON CONFLICT(permission_id) DO NOTHING",
        "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('collections.verify','Verify deposits and cheque clearance') ON CONFLICT(permission_id) DO NOTHING",
    ]
    with engine.begin() as conn:
        for s in stmts:
            conn.execute(text(s))
        for role in ('manager','super_admin'):
            for p in ('collections.view','collections.edit','collections.verify'):
                conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role,'p':p})
        for role in ('salesperson',):
            for p in ('collections.view','collections.edit'):
                conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role,'p':p})


def _require(engine, request: Request, perm: str, entity_id: str, location_id: str | None):
    user = authenticate(request)
    if perm not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def _payment(engine, payment_id: str):
    with engine.connect() as conn:
        return conn.execute(text('SELECT * FROM payment_transactions WHERE payment_id=:p'), {'p':payment_id}).mappings().first()


def _allocated(engine, payment_id: str):
    with engine.connect() as conn:
        return float(conn.execute(text("SELECT COALESCE(SUM(amount),0) FROM payment_allocations WHERE payment_id=:p AND status='POSTED'"), {'p':payment_id}).scalar_one() or 0)


def register_v90ak_routes(app: FastAPI, engine) -> None:
    ensure_v90ak_schema(engine)

    @app.post('/v90ak/payments/{payment_id}/allocate')
    def allocate_payment(payment_id: UUID, body: AllocationIn, request: Request):
        p = _payment(engine, str(payment_id))
        if not p:
            raise HTTPException(404, 'payment not found')
        user = _require(engine, request, 'collections.edit', str(p['entity_id']), str(p['location_id']))
        if p['status'] not in {'VERIFIED','PARTIALLY_ALLOCATED'}:
            raise HTTPException(409, 'only verified or partially allocated payments can be allocated')
        with engine.connect() as conn:
            inv = conn.execute(text('SELECT * FROM sales_invoices WHERE invoice_id=:i'), {'i':str(body.invoice_id)}).mappings().first()
        if not inv:
            raise HTTPException(404, 'invoice not found')
        if str(inv['entity_id']) != str(p['entity_id']) or str(inv['organization_id']) != str(p['organization_id']):
            raise HTTPException(409, 'payment and invoice scope mismatch')
        if str(inv['status']) != 'POSTED':
            raise HTTPException(409, 'invoice is not posted')
        with engine.connect() as conn:
            already = float(conn.execute(text("SELECT COALESCE(SUM(amount),0) FROM payment_allocations WHERE invoice_id=:i AND status='POSTED'"), {'i':str(body.invoice_id)}).scalar_one() or 0)
        invoice_total = float(inv['grand_total'] or 0)
        if already + body.amount > invoice_total + 1e-9:
            raise HTTPException(409, 'allocation exceeds invoice balance')
        used = _allocated(engine, str(payment_id))
        if used + body.amount > float(p['amount']) + 1e-9:
            raise HTTPException(409, 'allocation exceeds payment balance')
        aid = str(uuid4())
        with engine.begin() as conn:
            try:
                conn.execute(text("INSERT INTO payment_allocations(allocation_id,payment_id,invoice_id,customer_id,organization_id,entity_id,amount,status,created_by) VALUES(:a,:p,:i,:c,:o,:e,:amt,'POSTED',:u)"), {
                    'a':aid,'p':str(payment_id),'i':str(body.invoice_id),'c':str(p['customer_id']),'o':str(p['organization_id']),'e':str(p['entity_id']),'amt':body.amount,'u':str(user.user_id)})
            except Exception as exc:
                if 'UNIQUE' in str(exc).upper():
                    raise HTTPException(409, 'payment already allocated to this invoice') from exc
                raise
            new_status = 'ALLOCATED' if used + body.amount >= float(p['amount']) - 1e-9 else 'PARTIALLY_ALLOCATED'
            conn.execute(text("UPDATE payment_transactions SET status=:s WHERE payment_id=:p"), {'s':new_status,'p':str(payment_id)})
            conn.execute(text("INSERT INTO payment_lifecycle_events(lifecycle_event_id,payment_id,from_status,to_status,event_type,reference_no,notes,created_by) VALUES(:id,:p,:f,:t,'ALLOCATE',:r,:n,:u)"), {'id':str(uuid4()),'p':str(payment_id),'f':p['status'],'t':new_status,'r':str(body.invoice_id),'n':f'allocated {body.amount:g}','u':str(user.user_id)})
        return {'status':new_status,'payment_id':str(payment_id),'allocation_id':aid,'allocated_amount':body.amount,'unallocated_amount':round(float(p['amount'])-used-body.amount,2)}

    @app.post('/v90ak/payments/{payment_id}/cash/evidence')
    def cash_evidence(payment_id: UUID, request: Request):
        p = _payment(engine, str(payment_id))
        if not p: raise HTTPException(404, 'payment not found')
        user = _require(engine, request, 'collections.edit', str(p['entity_id']), str(p['location_id']))
        if p['mode'] != 'CASH': raise HTTPException(409, 'cash lifecycle applies only to CASH payments')
        with engine.begin() as conn:
            row = conn.execute(text('SELECT * FROM cash_collection_events WHERE payment_id=:p'), {'p':str(payment_id)}).mappings().first()
            if row:
                return dict(row)
            cid = str(uuid4())
            conn.execute(text("INSERT INTO cash_collection_events(collection_event_id,payment_id,status,evidence_file_id,created_by) VALUES(:c,:p,'EVIDENCE_CAPTURED',:f,:u)"), {'c':cid,'p':str(payment_id),'f':p['proof_file_id'],'u':str(user.user_id)})
            conn.execute(text("INSERT INTO payment_lifecycle_events(lifecycle_event_id,payment_id,to_status,event_type,reference_no,notes,created_by) VALUES(:id,:p,'EVIDENCE_CAPTURED','CASH_EVIDENCE',:r,:n,:u)"), {'id':str(uuid4()),'p':str(payment_id),'r':p['proof_file_id'],'n':'collection evidence captured','u':str(user.user_id)})
        return {'payment_id':str(payment_id),'status':'EVIDENCE_CAPTURED','evidence_file_id':p['proof_file_id']}

    @app.post('/v90ak/payments/{payment_id}/cash/deposit')
    def cash_deposit(payment_id: UUID, body: DepositIn, request: Request):
        p = _payment(engine, str(payment_id))
        if not p: raise HTTPException(404, 'payment not found')
        user = _require(engine, request, 'collections.edit', str(p['entity_id']), str(p['location_id']))
        if p['mode'] != 'CASH': raise HTTPException(409, 'cash lifecycle applies only to CASH payments')
        with engine.begin() as conn:
            row = conn.execute(text('SELECT * FROM cash_collection_events WHERE payment_id=:p'), {'p':str(payment_id)}).mappings().first()
            if not row or row['status'] not in {'EVIDENCE_CAPTURED','WITH_SALESPERSON'}:
                raise HTTPException(409, 'cash evidence must be captured before deposit')
            conn.execute(text("UPDATE cash_collection_events SET status='DEPOSITED',deposited_at=CURRENT_TIMESTAMP,deposit_ref=:r,deposit_date=:d WHERE payment_id=:p"), {'r':body.deposit_ref,'d':body.deposit_date.isoformat(),'p':str(payment_id)})
            conn.execute(text("UPDATE payment_transactions SET status='PENDING_VERIFICATION' WHERE payment_id=:p AND status IN ('PENDING','PENDING_VERIFICATION')"), {'p':str(payment_id)})
            conn.execute(text("INSERT INTO payment_lifecycle_events(lifecycle_event_id,payment_id,to_status,event_type,reference_no,notes,created_by) VALUES(:id,:p,'DEPOSITED','CASH_DEPOSIT',:r,:n,:u)"), {'id':str(uuid4()),'p':str(payment_id),'r':body.deposit_ref,'n':body.notes,'u':str(user.user_id)})
        return {'payment_id':str(payment_id),'status':'DEPOSITED','deposit_ref':body.deposit_ref}

    @app.post('/v90ak/payments/{payment_id}/deposit/verify')
    def verify_deposit(payment_id: UUID, request: Request):
        p = _payment(engine, str(payment_id))
        if not p: raise HTTPException(404, 'payment not found')
        user = _require(engine, request, 'collections.verify', str(p['entity_id']), str(p['location_id']))
        if p['mode'] == 'CHEQUE':
            raise HTTPException(409, 'use cheque clearance endpoint for CHEQUE')
        with engine.begin() as conn:
            conn.execute(text("UPDATE payment_transactions SET status='VERIFIED',verified_by=:u,verified_at=CURRENT_TIMESTAMP WHERE payment_id=:p AND status IN ('PENDING_VERIFICATION','PENDING')"), {'u':str(user.user_id),'p':str(payment_id)})
            conn.execute(text("UPDATE cash_collection_events SET status='VERIFIED',verified_by=:u,verified_at=CURRENT_TIMESTAMP WHERE payment_id=:p"), {'u':str(user.user_id),'p':str(payment_id)})
            conn.execute(text("INSERT INTO payment_lifecycle_events(lifecycle_event_id,payment_id,to_status,event_type,notes,created_by) VALUES(:id,:p,'VERIFIED','DEPOSIT_VERIFY','deposit verified',:u)"), {'id':str(uuid4()),'p':str(payment_id),'u':str(user.user_id)})
        return {'payment_id':str(payment_id),'status':'VERIFIED'}

    @app.post('/v90ak/payments/{payment_id}/cheque/clear')
    def clear_cheque(payment_id: UUID, body: ChequeClearIn, request: Request):
        p = _payment(engine, str(payment_id))
        if not p: raise HTTPException(404, 'payment not found')
        user = _require(engine, request, 'collections.verify', str(p['entity_id']), str(p['location_id']))
        if p['mode'] != 'CHEQUE': raise HTTPException(409, 'payment is not CHEQUE')
        if not p['cheque_no']: raise HTTPException(409, 'cheque number missing')
        with engine.begin() as conn:
            if p['status'] == 'VERIFIED':
                return {'payment_id':str(payment_id),'status':'VERIFIED','idempotent':True}
            if p['status'] == 'REJECTED':
                raise HTTPException(409, 'rejected payment cannot be cleared')
            conn.execute(text("UPDATE payment_transactions SET status='VERIFIED',verified_by=:u,verified_at=CURRENT_TIMESTAMP,notes=CASE WHEN notes IS NULL OR notes='' THEN :n ELSE notes || ' | ' || :n END WHERE payment_id=:p"), {'u':str(user.user_id),'p':str(payment_id),'n':body.clearance_ref})
            conn.execute(text("INSERT INTO payment_lifecycle_events(lifecycle_event_id,payment_id,to_status,event_type,reference_no,notes,created_by) VALUES(:id,:p,'VERIFIED','CHEQUE_CLEAR',:r,:n,:u)"), {'id':str(uuid4()),'p':str(payment_id),'r':body.clearance_ref,'n':body.notes,'u':str(user.user_id)})
        return {'payment_id':str(payment_id),'status':'VERIFIED','clearance_ref':body.clearance_ref}

    @app.get('/v90ak/customers/{customer_id}/statement')
    def customer_statement(customer_id: UUID, request: Request, entity_id: UUID):
        user = authenticate(request)
        if 'collections.view' not in permissions_for_user(engine, user.user_id): raise HTTPException(403, 'permission denied')
        try: assert_entity_location_allowed(engine, user.user_id, str(entity_id), None)
        except PermissionError as exc: raise HTTPException(403, str(exc)) from exc
        with engine.connect() as conn:
            invoices = conn.execute(text("SELECT si.invoice_id,si.invoice_no,si.grand_total,si.status,si.created_at FROM sales_invoices si JOIN sales_orders so ON so.sales_order_id=si.sales_order_id WHERE si.entity_id=:e AND so.customer_id=:c AND si.status='POSTED' ORDER BY si.created_at"), {'e':str(entity_id),'c':str(customer_id)}).mappings().all()
            payments = conn.execute(text("SELECT * FROM payment_transactions WHERE entity_id=:e AND customer_id=:c ORDER BY payment_date,created_at"), {'e':str(entity_id),'c':str(customer_id)}).mappings().all()
            allocations = conn.execute(text("SELECT * FROM payment_allocations WHERE entity_id=:e AND customer_id=:c AND status='POSTED' ORDER BY created_at"), {'e':str(entity_id),'c':str(customer_id)}).mappings().all()
        total_invoices = sum(float(x['grand_total'] or 0) for x in invoices)
        total_verified = sum(float(x['amount'] or 0) for x in payments if x['status'] in {'VERIFIED','ALLOCATED','PARTIALLY_ALLOCATED'})
        total_allocated = sum(float(x['amount'] or 0) for x in allocations)
        return {'customer_id':str(customer_id),'entity_id':str(entity_id),'invoices':[dict(x) for x in invoices], 'payments':[dict(x) for x in payments], 'allocations':[dict(x) for x in allocations], 'summary':{'invoice_total':round(total_invoices,2),'verified_payment_total':round(total_verified,2),'allocated_total':round(total_allocated,2),'unallocated_verified':round(total_verified-total_allocated,2),'net_outstanding':round(total_invoices-total_allocated,2)}}

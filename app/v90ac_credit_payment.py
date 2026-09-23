from __future__ import annotations
from datetime import datetime, timezone, date, timedelta
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed


class CreditPolicyIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    customer_id: UUID
    credit_limit: float = Field(ge=0)
    credit_days: int = Field(default=0, ge=0, le=3650)
    active: bool = True
    notes: str = ''


class CreditCheckIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    customer_id: UUID
    proposed_order_total: float = Field(gt=0)
    sales_order_id: UUID | None = None


class PaymentIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    customer_id: UUID
    amount: float = Field(gt=0)
    mode: str
    reference_no: str | None = None
    cheque_no: str | None = None
    bank_name: str | None = None
    payment_date: date
    sales_order_id: UUID | None = None
    proof_file_id: str | None = None
    notes: str = ''


def ensure_v90ac_schema(engine):
    stmts = [
        """CREATE TABLE IF NOT EXISTS customer_credit_policies (
            credit_policy_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            customer_id TEXT NOT NULL, credit_limit REAL NOT NULL, credit_days INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1, notes TEXT, created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id, entity_id, customer_id)
        )""",
        """CREATE TABLE IF NOT EXISTS credit_reviews (
            credit_review_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL, customer_id TEXT NOT NULL, proposed_order_total REAL NOT NULL,
            current_outstanding REAL NOT NULL, available_credit REAL NOT NULL, overdue_amount REAL NOT NULL,
            credit_limit REAL NOT NULL, credit_days INTEGER NOT NULL, status TEXT NOT NULL,
            reason TEXT, sales_order_id TEXT, reviewed_by TEXT NOT NULL,
            reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS payment_transactions (
            payment_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL, customer_id TEXT NOT NULL, sales_order_id TEXT,
            amount REAL NOT NULL, mode TEXT NOT NULL, reference_no TEXT, cheque_no TEXT,
            bank_name TEXT, payment_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
            proof_file_id TEXT, notes TEXT, created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, verified_by TEXT, verified_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS payment_proofs (
            payment_proof_id TEXT PRIMARY KEY, payment_id TEXT NOT NULL, file_id TEXT NOT NULL,
            proof_type TEXT, captured_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_credit_policy_customer ON customer_credit_policies(entity_id,customer_id,active)",
        "CREATE INDEX IF NOT EXISTS ix_credit_reviews_customer ON credit_reviews(entity_id,customer_id,reviewed_at)",
        "CREATE INDEX IF NOT EXISTS ix_payment_customer_status ON payment_transactions(entity_id,customer_id,status,payment_date)",
    ]
    with engine.begin() as conn:
        for s in stmts:
            conn.execute(text(s))


def _require(engine, request: Request, perm: str, entity_id: UUID, location_id: UUID | None):
    user = authenticate(request)
    if perm not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, str(entity_id), str(location_id) if location_id else None)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def _policy(engine, organization_id: str, entity_id: str, customer_id: str):
    with engine.connect() as conn:
        return conn.execute(text("""SELECT * FROM customer_credit_policies
            WHERE organization_id=:o AND entity_id=:e AND customer_id=:c AND active=1"""),
            {'o': organization_id, 'e': entity_id, 'c': customer_id}).mappings().first()


def _approved_sales_outstanding(engine, entity_id: str, customer_id: str):
    with engine.connect() as conn:
        gross = conn.execute(text("""SELECT COALESCE(SUM(grand_total),0) v FROM sales_orders
            WHERE entity_id=:e AND customer_id=:c AND status='APPROVED'"""), {'e': entity_id, 'c': customer_id}).scalar_one()
        paid = conn.execute(text("""SELECT COALESCE(SUM(amount),0) v FROM payment_transactions
            WHERE entity_id=:e AND customer_id=:c AND status='VERIFIED'"""), {'e': entity_id, 'c': customer_id}).scalar_one()
    return max(float(gross or 0) - float(paid or 0), 0.0)


def _overdue_amount(engine, entity_id: str, customer_id: str, credit_days: int):
    cutoff = date.today() - timedelta(days=credit_days)
    with engine.connect() as conn:
        # Approved orders older than the configured credit period, net of verified customer payments.
        overdue = conn.execute(text("""SELECT COALESCE(SUM(grand_total),0) FROM sales_orders
            WHERE entity_id=:e AND customer_id=:c AND status='APPROVED' AND date(approved_at) < :cut"""),
            {'e': entity_id, 'c': customer_id, 'cut': cutoff.isoformat()}).scalar_one()
        paid = conn.execute(text("""SELECT COALESCE(SUM(amount),0) FROM payment_transactions
            WHERE entity_id=:e AND customer_id=:c AND status='VERIFIED' AND date(payment_date) < :cut"""),
            {'e': entity_id, 'c': customer_id, 'cut': cutoff.isoformat()}).scalar_one()
    return max(float(overdue or 0) - float(paid or 0), 0.0)


def register_v90ac_routes(app: FastAPI, engine):
    ensure_v90ac_schema(engine)

    @app.post('/v90ac/credit/policies')
    def create_policy(body: CreditPolicyIn, request: Request):
        user = _require(engine, request, 'credit_policy.edit', body.entity_id, None)
        pid = str(uuid4())
        try:
            with engine.begin() as conn:
                conn.execute(text("""INSERT INTO customer_credit_policies
                    (credit_policy_id,organization_id,entity_id,customer_id,credit_limit,credit_days,active,notes,created_by)
                    VALUES(:id,:o,:e,:c,:l,:d,:a,:n,:u)"""), {
                    'id': pid, 'o': str(body.organization_id), 'e': str(body.entity_id), 'c': str(body.customer_id),
                    'l': body.credit_limit, 'd': body.credit_days, 'a': 1 if body.active else 0, 'n': body.notes, 'u': str(user.user_id)})
        except Exception as exc:
            if 'UNIQUE' in str(exc).upper() or 'unique' in str(exc).lower():
                raise HTTPException(409, 'active credit policy already exists') from exc
            raise
        return {'status': 'created', 'credit_policy_id': pid}

    @app.get('/v90ac/credit/policies')
    def list_policies(request: Request, organization_id: UUID, entity_id: UUID):
        _require(engine, request, 'credit_policy.view', entity_id, None)
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM customer_credit_policies WHERE organization_id=:o AND entity_id=:e ORDER BY created_at DESC"), {'o':str(organization_id),'e':str(entity_id)}).mappings().all()
        return {'items': [dict(r) for r in rows]}

    @app.post('/v90ac/credit/check')
    def check_credit(body: CreditCheckIn, request: Request):
        user = _require(engine, request, 'sales.edit', body.entity_id, body.location_id)
        policy = _policy(engine, str(body.organization_id), str(body.entity_id), str(body.customer_id))
        if not policy:
            status, reason, limit, days = 'HOLD', 'no approved credit policy', 0.0, 0
            outstanding, overdue, available = _approved_sales_outstanding(engine, str(body.entity_id), str(body.customer_id)), 0.0, -body.proposed_order_total
        else:
            limit, days = float(policy['credit_limit']), int(policy['credit_days'])
            outstanding = _approved_sales_outstanding(engine, str(body.entity_id), str(body.customer_id))
            overdue = _overdue_amount(engine, str(body.entity_id), str(body.customer_id), days)
            available = limit - outstanding
            if overdue > 0:
                status, reason = 'HOLD', 'customer has overdue outstanding'
            elif body.proposed_order_total > available:
                status, reason = 'HOLD', 'proposed order exceeds available credit'
            else:
                status, reason = 'PASS', ''
        rid = str(uuid4())
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO credit_reviews
                (credit_review_id,organization_id,entity_id,location_id,customer_id,proposed_order_total,current_outstanding,available_credit,overdue_amount,credit_limit,credit_days,status,reason,sales_order_id,reviewed_by)
                VALUES(:id,:o,:e,:l,:c,:p,:out,:av,:od,:lim,:d,:s,:r,:so,:u)"""), {
                'id': rid,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'c':str(body.customer_id),
                'p':body.proposed_order_total,'out':outstanding,'av':available,'od':overdue,'lim':limit,'d':days,'s':status,'r':reason,
                'so':str(body.sales_order_id) if body.sales_order_id else None,'u':str(user.user_id)})
        return {'status':status,'reason':reason,'credit_review_id':rid,'credit_limit':limit,'credit_days':days,
                'current_outstanding':round(outstanding,2),'available_credit':round(available,2),'overdue_amount':round(overdue,2)}

    @app.post('/v90ac/payments')
    def record_payment(body: PaymentIn, request: Request):
        user = _require(engine, request, 'sales.edit', body.entity_id, body.location_id)
        mode = body.mode.upper()
        if mode not in {'CASH','UPI','CHEQUE','BANK_TRANSFER','OTHER'}:
            raise HTTPException(422, 'unsupported payment mode')
        if mode == 'CHEQUE' and not body.cheque_no:
            raise HTTPException(422, 'cheque_no required for CHEQUE payment')
        pid = str(uuid4())
        status = 'PENDING'
        if mode in {'CASH','UPI','BANK_TRANSFER','OTHER'}:
            status = 'PENDING_VERIFICATION'
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO payment_transactions
                (payment_id,organization_id,entity_id,location_id,customer_id,sales_order_id,amount,mode,reference_no,cheque_no,bank_name,payment_date,status,proof_file_id,notes,created_by)
                VALUES(:id,:o,:e,:l,:c,:so,:a,:m,:r,:ch,:b,:d,:s,:p,:n,:u)"""), {
                    'id':pid,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'c':str(body.customer_id),
                    'so':str(body.sales_order_id) if body.sales_order_id else None,'a':body.amount,'m':mode,'r':body.reference_no,
                    'ch':body.cheque_no,'b':body.bank_name,'d':body.payment_date.isoformat(),'s':status,'p':body.proof_file_id,'n':body.notes,'u':str(user.user_id)})
            if body.proof_file_id:
                conn.execute(text("""INSERT INTO payment_proofs(payment_proof_id,payment_id,file_id,proof_type,captured_by)
                    VALUES(:id,:p,:f,:t,:u)"""), {'id':str(uuid4()),'p':pid,'f':body.proof_file_id,'t':mode,'u':str(user.user_id)})
        return {'status': 'recorded', 'payment_id': pid, 'payment_status': status}

    @app.post('/v90ac/payments/{payment_id}/verify')
    def verify_payment(payment_id: UUID, request: Request):
        user = authenticate(request)
        if 'payments.verify' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM payment_transactions WHERE payment_id=:p"), {'p':str(payment_id)}).mappings().first()
        if not row:
            raise HTTPException(404, 'payment not found')
        if row['mode'] == 'CHEQUE':
            raise HTTPException(409, 'cheque must be cleared through /v90ak/payments/{payment_id}/cheque/clear')
        if row['status'] == 'VERIFIED':
            return {'payment_id':str(payment_id),'status':'VERIFIED','idempotent':True}
        with engine.begin() as conn:
            conn.execute(text("UPDATE payment_transactions SET status='VERIFIED',verified_by=:u,verified_at=CURRENT_TIMESTAMP WHERE payment_id=:p"), {'p':str(payment_id),'u':str(user.user_id)})
        return {'payment_id':str(payment_id),'status':'VERIFIED'}

    @app.post('/v90ac/payments/{payment_id}/reject')
    def reject_payment(payment_id: UUID, request: Request):
        user = authenticate(request)
        if 'payments.verify' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        with engine.connect() as conn:
            row = conn.execute(text("SELECT payment_id FROM payment_transactions WHERE payment_id=:p"), {'p':str(payment_id)}).first()
        if not row:
            raise HTTPException(404, 'payment not found')
        with engine.begin() as conn:
            conn.execute(text("UPDATE payment_transactions SET status='REJECTED',verified_by=:u,verified_at=CURRENT_TIMESTAMP WHERE payment_id=:p"), {'p':str(payment_id),'u':str(user.user_id)})
        return {'payment_id':str(payment_id),'status':'REJECTED'}

    @app.get('/v90ac/receivables')
    def receivables(request: Request, organization_id: UUID, entity_id: UUID, customer_id: UUID):
        user = authenticate(request)
        if 'sales.view' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        try:
            assert_entity_location_allowed(engine, user.user_id, str(entity_id), None)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        policy = _policy(engine, str(organization_id), str(entity_id), str(customer_id))
        outstanding = _approved_sales_outstanding(engine, str(entity_id), str(customer_id))
        overdue = _overdue_amount(engine, str(entity_id), str(customer_id), int(policy['credit_days']) if policy else 0)
        limit = float(policy['credit_limit']) if policy else 0.0
        return {'customer_id':str(customer_id),'credit_limit':limit,'outstanding':round(outstanding,2),'overdue':round(overdue,2),'available_credit':round(limit-outstanding,2)}

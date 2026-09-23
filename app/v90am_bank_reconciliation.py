from __future__ import annotations
from datetime import date
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed

class BankStatementLineIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID | None = None
    bank_name: str = Field(min_length=2, max_length=160)
    statement_date: date
    statement_ref: str = Field(min_length=2, max_length=160)
    amount: float = Field(gt=0)
    transaction_type: str = Field(min_length=3, max_length=20)
    bank_reference: str | None = Field(default=None, max_length=160)
    notes: str = ''

class MatchIn(BaseModel):
    payment_id: UUID

class ReconcileIn(BaseModel):
    notes: str = ''

def ensure_v90am_schema(engine) -> None:
    stmts = [
        """CREATE TABLE IF NOT EXISTS bank_reconciliation_lines (
            bank_line_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT, bank_name TEXT NOT NULL, statement_date DATE NOT NULL, statement_ref TEXT NOT NULL,
            amount NUMERIC(18,2) NOT NULL CHECK(amount > 0), transaction_type TEXT NOT NULL,
            bank_reference TEXT, status TEXT NOT NULL DEFAULT 'UNMATCHED', matched_payment_id TEXT,
            matched_by TEXT, matched_at TIMESTAMP, reconciled_by TEXT, reconciled_at TIMESTAMP,
            notes TEXT, created_by TEXT NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(entity_id, statement_ref)
        )""",
        """CREATE TABLE IF NOT EXISTS bank_reconciliation_events (
            event_id TEXT PRIMARY KEY, bank_line_id TEXT NOT NULL, from_status TEXT, to_status TEXT NOT NULL,
            event_type TEXT NOT NULL, payment_id TEXT, notes TEXT, created_by TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_bank_recon_scope ON bank_reconciliation_lines(entity_id,statement_date,status)",
        "CREATE INDEX IF NOT EXISTS ix_bank_recon_payment ON bank_reconciliation_lines(matched_payment_id,status)",
        "CREATE INDEX IF NOT EXISTS ix_bank_recon_ref ON bank_reconciliation_lines(entity_id,statement_ref)",
        "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('bank_recon.view','View bank reconciliation') ON CONFLICT(permission_id) DO NOTHING",
        "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('bank_recon.edit','Import and match bank lines') ON CONFLICT(permission_id) DO NOTHING",
        "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('bank_recon.reconcile','Finalize bank reconciliation') ON CONFLICT(permission_id) DO NOTHING",
    ]
    with engine.begin() as conn:
        for stmt in stmts: conn.execute(text(stmt))
        for role in ('manager','super_admin','accounts'):
            for perm in ('bank_recon.view','bank_recon.edit','bank_recon.reconcile'):
                conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role,'p':perm})

def _require(engine, request: Request, perm: str, entity_id: str, location_id: str | None):
    user = authenticate(request)
    if perm not in permissions_for_user(engine, user.user_id): raise HTTPException(403,'permission denied')
    try: assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc: raise HTTPException(403,str(exc)) from exc
    return user

def register_v90am_routes(app: FastAPI, engine) -> None:
    ensure_v90am_schema(engine)

    @app.post('/v90am/bank-lines')
    def create_bank_line(body: BankStatementLineIn, request: Request):
        user=_require(engine,request,'bank_recon.edit',str(body.entity_id),str(body.location_id) if body.location_id else None)
        if body.transaction_type.upper() not in {'CREDIT','DEBIT'}: raise HTTPException(422,'transaction_type must be CREDIT or DEBIT')
        with engine.begin() as conn:
            entity_exists=conn.execute(text('SELECT 1 FROM erp_entities WHERE entity_id=:e'),{'e':str(body.entity_id)}).scalar()
            if not entity_exists: raise HTTPException(404,'entity not found')
            bid=str(uuid4())
            try:
                conn.execute(text("""INSERT INTO bank_reconciliation_lines
                (bank_line_id,organization_id,entity_id,location_id,bank_name,statement_date,statement_ref,amount,transaction_type,bank_reference,notes,created_by)
                VALUES(:id,:o,:e,:l,:b,:d,:r,:a,:t,:br,:n,:u)"""),{'id':bid,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id) if body.location_id else None,'b':body.bank_name,'d':body.statement_date,'r':body.statement_ref,'a':body.amount,'t':body.transaction_type.upper(),'br':body.bank_reference,'n':body.notes,'u':str(user.user_id)})
            except Exception as exc:
                if 'UNIQUE' in str(exc).upper(): raise HTTPException(409,'statement_ref already imported for this entity') from exc
                raise
        return {'status':'created','bank_line_id':bid,'reconciliation_status':'UNMATCHED'}

    @app.get('/v90am/bank-lines')
    def list_bank_lines(request: Request, entity_id: UUID, status: str | None = None, from_date: date | None = None, to_date: date | None = None):
        _require(engine,request,'bank_recon.view',str(entity_id),None)
        clauses=['entity_id=:e']; params={'e':str(entity_id)}
        if status: clauses.append('status=:s'); params['s']=status.upper()
        if from_date: clauses.append('statement_date>=:f'); params['f']=from_date
        if to_date: clauses.append('statement_date<=:t'); params['t']=to_date
        with engine.connect() as conn:
            rows=conn.execute(text(f"SELECT * FROM bank_reconciliation_lines WHERE {' AND '.join(clauses)} ORDER BY statement_date DESC,created_at DESC"),params).mappings().all()
        return {'entity_id':str(entity_id),'items':[dict(r) for r in rows],'count':len(rows)}

    @app.post('/v90am/bank-lines/{bank_line_id}/match')
    def match_bank_line(bank_line_id: UUID, body: MatchIn, request: Request):
        with engine.connect() as conn:
            line=conn.execute(text('SELECT * FROM bank_reconciliation_lines WHERE bank_line_id=:b'),{'b':str(bank_line_id)}).mappings().first()
            payment=conn.execute(text('SELECT * FROM payment_transactions WHERE payment_id=:p'),{'p':str(body.payment_id)}).mappings().first()
        if not line: raise HTTPException(404,'bank reconciliation line not found')
        if not payment: raise HTTPException(404,'payment not found')
        user=_require(engine,request,'bank_recon.edit',str(line['entity_id']),str(line['location_id']) if line['location_id'] else None)
        if str(payment['entity_id'])!=str(line['entity_id']) or str(payment['organization_id'])!=str(line['organization_id']): raise HTTPException(409,'payment and bank line scope mismatch')
        if payment['mode'] not in {'BANK_TRANSFER','UPI','CHEQUE'}: raise HTTPException(409,'payment mode is not bank-matchable')
        if abs(float(payment['amount'])-float(line['amount']))>0.005: raise HTTPException(409,'bank amount does not match payment amount')
        if line['transaction_type'].upper()!='CREDIT': raise HTTPException(409,'only credit statement lines can match customer receipts')
        with engine.begin() as conn:
            if line['status']=='RECONCILED' and str(line['matched_payment_id'])==str(body.payment_id): return {'bank_line_id':str(bank_line_id),'payment_id':str(body.payment_id),'status':'RECONCILED','idempotent':True}
            if line['status'] not in {'UNMATCHED','MATCHED'}: raise HTTPException(409,'bank line cannot be matched from current status')
            existing=conn.execute(text("SELECT bank_line_id FROM bank_reconciliation_lines WHERE matched_payment_id=:p AND status IN ('MATCHED','RECONCILED') AND bank_line_id<>:b"),{'p':str(body.payment_id),'b':str(bank_line_id)}).first()
            if existing: raise HTTPException(409,'payment already matched to another bank line')
            old=line['status']
            conn.execute(text("UPDATE bank_reconciliation_lines SET status='MATCHED',matched_payment_id=:p,matched_by=:u,matched_at=CURRENT_TIMESTAMP WHERE bank_line_id=:b"),{'p':str(body.payment_id),'u':str(user.user_id),'b':str(bank_line_id)})
            conn.execute(text("INSERT INTO bank_reconciliation_events(event_id,bank_line_id,from_status,to_status,event_type,payment_id,created_by) VALUES(:id,:b,:f,'MATCHED','PAYMENT_MATCH',:p,:u)"),{'id':str(uuid4()),'b':str(bank_line_id),'f':old,'p':str(body.payment_id),'u':str(user.user_id)})
        return {'bank_line_id':str(bank_line_id),'payment_id':str(body.payment_id),'status':'MATCHED'}

    @app.post('/v90am/bank-lines/{bank_line_id}/reconcile')
    def reconcile_bank_line(bank_line_id: UUID, body: ReconcileIn, request: Request):
        with engine.connect() as conn: line=conn.execute(text('SELECT * FROM bank_reconciliation_lines WHERE bank_line_id=:b'),{'b':str(bank_line_id)}).mappings().first()
        if not line: raise HTTPException(404,'bank reconciliation line not found')
        user=_require(engine,request,'bank_recon.reconcile',str(line['entity_id']),str(line['location_id']) if line['location_id'] else None)
        if line['status']!='MATCHED': raise HTTPException(409,'only matched bank lines can be reconciled')
        with engine.begin() as conn:
            conn.execute(text("UPDATE bank_reconciliation_lines SET status='RECONCILED',reconciled_by=:u,reconciled_at=CURRENT_TIMESTAMP,notes=CASE WHEN notes IS NULL OR notes='' THEN :n ELSE notes || ' | ' || :n END WHERE bank_line_id=:b"),{'u':str(user.user_id),'n':body.notes,'b':str(bank_line_id)})
            conn.execute(text("INSERT INTO bank_reconciliation_events(event_id,bank_line_id,from_status,to_status,event_type,notes,created_by) VALUES(:id,:b,'MATCHED','RECONCILED','RECONCILE',:n,:u)"),{'id':str(uuid4()),'b':str(bank_line_id),'n':body.notes,'u':str(user.user_id)})
        return {'bank_line_id':str(bank_line_id),'status':'RECONCILED'}

    @app.get('/v90am/summary')
    def reconciliation_summary(request: Request, entity_id: UUID, from_date: date | None = None, to_date: date | None = None):
        _require(engine,request,'bank_recon.view',str(entity_id),None)
        clauses=['entity_id=:e']; params={'e':str(entity_id)}
        if from_date: clauses.append('statement_date>=:f'); params['f']=from_date
        if to_date: clauses.append('statement_date<=:t'); params['t']=to_date
        with engine.connect() as conn: rows=conn.execute(text(f"SELECT status, COUNT(*) count, COALESCE(SUM(amount),0) amount FROM bank_reconciliation_lines WHERE {' AND '.join(clauses)} GROUP BY status"),params).mappings().all()
        by={r['status']:{'count':int(r['count']),'amount':round(float(r['amount'] or 0),2)} for r in rows}
        return {'entity_id':str(entity_id),'statuses':by,'total_lines':sum(x['count'] for x in by.values()),'total_amount':round(sum(x['amount'] for x in by.values()),2)}

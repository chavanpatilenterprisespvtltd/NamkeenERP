from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID, uuid4
from typing import Any
import json
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed

CUSTOMER_TYPES = {"DISTRIBUTOR", "DEALER", "WHOLESALER", "RETAILER", "OTHER"}

class TerritoryChange(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID | None = None
    territory_id: str = Field(min_length=1, max_length=100)
    territory_name: str = Field(min_length=1, max_length=200)
    active: bool = True

class PortfolioAssignment(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID | None = None
    customer_id: UUID
    customer_type: str = "DEALER"
    territory_id: str = Field(min_length=1, max_length=100)
    salesperson_user_id: UUID | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    reason: str | None = None

class ReassignmentRequest(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID | None = None
    customer_type: str = "DEALER"
    territory_id: str
    salesperson_user_id: UUID | None = None
    reason: str | None = None


def _require(engine, request: Request, entity_id: str, location_id: str | None, perm: str):
    user = authenticate(request)
    if perm not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, "permission denied")
    try:
        assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def _now():
    return datetime.now(timezone.utc).isoformat()


def _customer(conn, organization_id: str, entity_id: str, customer_id: str):
    row = conn.execute(text("""
        SELECT master_id, entity_id, data, active FROM master_record
        WHERE organization_id=:o AND master_type='CUSTOMER' AND master_id=:c
    """), {"o": organization_id, "c": customer_id}).mappings().first()
    if not row or not row["active"]:
        raise HTTPException(404, "customer not found")
    if row["entity_id"] not in (None, entity_id):
        raise HTTPException(409, "customer outside entity scope")
    try:
        data = json.loads(row["data"] or "{}") if isinstance(row["data"], str) else dict(row["data"] or {})
    except Exception:
        data = {}
    return row, data


def ensure_v90au_schema(engine):
    stmts = [
        """CREATE TABLE IF NOT EXISTS sales_territories (
            territory_row_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT NULL, territory_id TEXT NOT NULL, territory_name TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id, entity_id, territory_id)
        )""",
        """CREATE TABLE IF NOT EXISTS customer_portfolio_assignments (
            assignment_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT NULL, customer_id TEXT NOT NULL, customer_type TEXT NOT NULL,
            territory_id TEXT NOT NULL, salesperson_user_id TEXT NULL, effective_from TEXT NULL,
            effective_to TEXT NULL, reason TEXT NULL, active INTEGER NOT NULL DEFAULT 1,
            assigned_by TEXT NOT NULL, assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_customer_portfolio_active ON customer_portfolio_assignments(organization_id,entity_id,customer_id,active,assigned_at)",
        "CREATE INDEX IF NOT EXISTS ix_customer_portfolio_salesperson ON customer_portfolio_assignments(organization_id,entity_id,salesperson_user_id,active)",
        """CREATE TABLE IF NOT EXISTS customer_portfolio_audit (
            audit_id TEXT PRIMARY KEY, assignment_id TEXT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            customer_id TEXT NOT NULL, action TEXT NOT NULL, before_data TEXT NULL, after_data TEXT NULL,
            actor_user_id TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS ix_portfolio_audit_customer ON customer_portfolio_audit(organization_id,entity_id,customer_id,created_at)",
        "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('sales_portfolio.view','View distributor/dealer portfolios and territories') ON CONFLICT(permission_id) DO NOTHING",
        "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('sales_portfolio.edit','Manage distributor/dealer portfolios and territories') ON CONFLICT(permission_id) DO NOTHING",
        "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('sales_portfolio.assign','Assign/reassign customer portfolios') ON CONFLICT(permission_id) DO NOTHING",
    ]
    with engine.begin() as conn:
        for s in stmts: conn.execute(text(s))
        for role in ('manager','super_admin','accounts'):
            for p in ('sales_portfolio.view','sales_portfolio.edit','sales_portfolio.assign'):
                conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role,'p':p})
        conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('salesperson','sales_portfolio.view') ON CONFLICT(role_id,permission_id) DO NOTHING"))


def register_v90au_routes(app: FastAPI, engine):
    ensure_v90au_schema(engine)

    @app.post('/v90au/territories')
    def create_territory(body: TerritoryChange, request: Request):
        user = _require(engine, request, str(body.entity_id), str(body.location_id) if body.location_id else None, 'sales_portfolio.edit')
        tid = str(body.territory_id).strip()
        if not tid: raise HTTPException(422, 'territory_id required')
        rid = str(uuid4())
        try:
            with engine.begin() as conn:
                conn.execute(text("""INSERT INTO sales_territories
                    (territory_row_id,organization_id,entity_id,location_id,territory_id,territory_name,active,created_by)
                    VALUES(:id,:o,:e,:l,:t,:n,:a,:u)"""), {'id':rid,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id) if body.location_id else None,'t':tid,'n':body.territory_name.strip(),'a':1 if body.active else 0,'u':str(user.user_id)})
        except Exception as exc:
            if 'UNIQUE' in str(exc).upper() or 'duplicate' in str(exc).lower():
                raise HTTPException(409, 'territory already exists') from exc
            raise
        return {'territory_row_id': rid, 'territory_id': tid, 'territory_name': body.territory_name.strip(), 'active': body.active}

    @app.get('/v90au/territories')
    def list_territories(organization_id: UUID, entity_id: UUID, request: Request, location_id: UUID | None = None, active: bool = True):
        _require(engine, request, str(entity_id), str(location_id) if location_id else None, 'sales_portfolio.view')
        loc = ' AND location_id=:l' if location_id else ''
        params={'o':str(organization_id),'e':str(entity_id),'a':1 if active else 0}
        if location_id: params['l']=str(location_id)
        with engine.connect() as conn:
            rows=conn.execute(text(f"SELECT * FROM sales_territories WHERE organization_id=:o AND entity_id=:e AND active=:a{loc} ORDER BY territory_id"),params).mappings().all()
        return {'items':[dict(r) for r in rows]}

    @app.post('/v90au/portfolio/assign')
    def assign(body: PortfolioAssignment, request: Request):
        actor = _require(engine, request, str(body.entity_id), str(body.location_id) if body.location_id else None, 'sales_portfolio.assign')
        ctype = body.customer_type.upper()
        if ctype not in CUSTOMER_TYPES: raise HTTPException(422, 'unsupported customer_type')
        with engine.begin() as conn:
            _, customer_data = _customer(conn, str(body.organization_id), str(body.entity_id), str(body.customer_id))
            if body.salesperson_user_id:
                exists=conn.execute(text("SELECT 1 FROM erp_entity_user_access WHERE user_id=:u AND entity_id=:e"),{'u':str(body.salesperson_user_id),'e':str(body.entity_id)}).first()
                if not exists: raise HTTPException(422,'salesperson is outside entity access')
            current=conn.execute(text("SELECT * FROM customer_portfolio_assignments WHERE organization_id=:o AND entity_id=:e AND customer_id=:c AND active=1 ORDER BY assigned_at DESC LIMIT 1"),{'o':str(body.organization_id),'e':str(body.entity_id),'c':str(body.customer_id)}).mappings().first()
            if current:
                before=dict(current)
                conn.execute(text("UPDATE customer_portfolio_assignments SET active=0 WHERE assignment_id=:id"),{'id':current['assignment_id']})
            else:
                before=None
            aid=str(uuid4())
            conn.execute(text("""INSERT INTO customer_portfolio_assignments
                (assignment_id,organization_id,entity_id,location_id,customer_id,customer_type,territory_id,salesperson_user_id,effective_from,effective_to,reason,active,assigned_by)
                VALUES(:id,:o,:e,:l,:c,:ct,:t,:s,:ef,:et,:r,1,:u)"""),
                {'id':aid,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id) if body.location_id else None,'c':str(body.customer_id),'ct':ctype,'t':body.territory_id,'s':str(body.salesperson_user_id) if body.salesperson_user_id else None,'ef':body.effective_from,'et':body.effective_to,'r':body.reason,'u':str(actor.user_id)})
            after={'assignment_id':aid,'territory_id':body.territory_id,'salesperson_user_id':str(body.salesperson_user_id) if body.salesperson_user_id else None,'customer_type':ctype,'effective_from':body.effective_from,'effective_to':body.effective_to,'active':1}
            conn.execute(text("INSERT INTO customer_portfolio_audit(audit_id,assignment_id,organization_id,entity_id,customer_id,action,before_data,after_data,actor_user_id) VALUES(:id,:a,:o,:e,:c,:act,:b,:af,:u)"),{'id':str(uuid4()),'a':aid,'o':str(body.organization_id),'e':str(body.entity_id),'c':str(body.customer_id),'act':'REASSIGN' if before else 'ASSIGN','b':json.dumps(before,default=str) if before else None,'af':json.dumps(after),'u':str(actor.user_id)})
            customer_data.update({'customer_type':ctype,'territory_id':body.territory_id,'salesperson_user_id':str(body.salesperson_user_id) if body.salesperson_user_id else None})
            conn.execute(text("UPDATE master_record SET data=:d, version_no=version_no+1 WHERE master_id=:c AND organization_id=:o AND master_type='CUSTOMER'"),{'d':json.dumps(customer_data),'c':str(body.customer_id),'o':str(body.organization_id)})
        return {'assignment_id':aid,'status':'ASSIGNED','reassigned':bool(current),'territory_id':body.territory_id,'salesperson_user_id':str(body.salesperson_user_id) if body.salesperson_user_id else None}

    @app.get('/v90au/portfolio/customer/{customer_id}')
    def customer_portfolio(customer_id: UUID, organization_id: UUID, entity_id: UUID, request: Request, location_id: UUID | None = None):
        _require(engine, request, str(entity_id), str(location_id) if location_id else None, 'sales_portfolio.view')
        with engine.connect() as conn:
            _, data = _customer(conn,str(organization_id),str(entity_id),str(customer_id))
            row=conn.execute(text("SELECT * FROM customer_portfolio_assignments WHERE organization_id=:o AND entity_id=:e AND customer_id=:c AND active=1 ORDER BY assigned_at DESC LIMIT 1"),{'o':str(organization_id),'e':str(entity_id),'c':str(customer_id)}).mappings().first()
        return {'customer_id':str(customer_id),'customer':data,'assignment':dict(row) if row else None}

    @app.post('/v90au/portfolio/customer/{customer_id}/reassign')
    def reassign(customer_id: UUID, body: ReassignmentRequest, request: Request):
        payload=PortfolioAssignment(organization_id=body.organization_id,entity_id=body.entity_id,location_id=body.location_id,customer_id=customer_id,customer_type=body.customer_type,territory_id=body.territory_id,salesperson_user_id=body.salesperson_user_id,reason=body.reason)
        return assign(payload,request)

    @app.get('/v90au/portfolio/salesperson/{salesperson_user_id}/customers')
    def salesperson_customers(salesperson_user_id: UUID, organization_id: UUID, entity_id: UUID, request: Request, customer_type: str | None = None):
        _require(engine, request, str(entity_id), None, 'sales_portfolio.view')
        params={'o':str(organization_id),'e':str(entity_id),'s':str(salesperson_user_id)}
        typ=''
        if customer_type:
            params['ct']=customer_type.upper(); typ=' AND customer_type=:ct'
        with engine.connect() as conn:
            rows=conn.execute(text(f"SELECT * FROM customer_portfolio_assignments WHERE organization_id=:o AND entity_id=:e AND salesperson_user_id=:s AND active=1{typ} ORDER BY customer_id"),params).mappings().all()
        return {'salesperson_user_id':str(salesperson_user_id),'items':[dict(r) for r in rows]}

    @app.get('/v90au/portfolio/audit/{customer_id}')
    def portfolio_audit(customer_id: UUID, organization_id: UUID, entity_id: UUID, request: Request):
        _require(engine,request,str(entity_id),None,'sales_portfolio.view')
        with engine.connect() as conn:
            rows=conn.execute(text("SELECT * FROM customer_portfolio_audit WHERE organization_id=:o AND entity_id=:e AND customer_id=:c ORDER BY created_at DESC"),{'o':str(organization_id),'e':str(entity_id),'c':str(customer_id)}).mappings().all()
        return {'items':[dict(r) for r in rows]}

from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed

class VisitIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    customer_id: UUID
    visit_at: datetime
    purpose: str = Field(min_length=2, max_length=120)
    outcome: str = Field(default='', max_length=500)
    next_action: str = Field(default='', max_length=500)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

class CustomerOnboardIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    payload: dict = Field(min_length=1)


def ensure_v90bq_schema(engine) -> None:
    with engine.begin() as c:
        perms = {"salesperson_ui.view": "View salesperson workspace", "salesperson_ui.manage": "Manage salesperson workspace"}
        for pid, name in perms.items():
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {"p": pid, "n": name})
        for role in ("super_admin", "manager", "salesperson", "mis"):
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'salesperson_ui.view') ON CONFLICT(role_id,permission_id) DO NOTHING"), {"r": role})
        for role in ("super_admin", "manager", "salesperson"):
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'salesperson_ui.manage') ON CONFLICT(role_id,permission_id) DO NOTHING"), {"r": role})
        c.execute(text("""CREATE TABLE IF NOT EXISTS sales_customer_visits(
            visit_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL, customer_id TEXT NOT NULL, visit_at TEXT NOT NULL,
            purpose TEXT NOT NULL, outcome TEXT NOT NULL DEFAULT '', next_action TEXT NOT NULL DEFAULT '',
            latitude REAL, longitude REAL, created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""))
        c.execute(text("CREATE INDEX IF NOT EXISTS ix_sales_customer_visits_scope ON sales_customer_visits(entity_id,location_id,customer_id,visit_at DESC)"))
        c.execute(text("""CREATE TABLE IF NOT EXISTS ui_saved_order_drafts(
            draft_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL, customer_id TEXT NOT NULL, draft_name TEXT NOT NULL,
            payload TEXT NOT NULL, created_by TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(entity_id,location_id,customer_id,draft_name,created_by))"""))


def _require(engine, request: Request, entity_id: UUID, location_id: UUID | None, perm: str):
    u = authenticate(request)
    if perm not in permissions_for_user(engine, u.user_id):
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, u.user_id, str(entity_id), str(location_id) if location_id else None)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return u


def register_v90bq_routes(app: FastAPI, engine) -> None:
    ensure_v90bq_schema(engine)

    @app.get('/v90bq/salesperson/summary')
    def summary(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID):
        _require(engine, request, entity_id, location_id, 'salesperson_ui.view')
        with engine.connect() as c:
            orders = c.execute(text("SELECT COUNT(*) n, COALESCE(SUM(grand_total),0) total FROM sales_orders WHERE organization_id=:o AND entity_id=:e AND location_id=:l"), {'o':str(organization_id),'e':str(entity_id),'l':str(location_id)}).mappings().one()
            visits = c.execute(text("SELECT COUNT(*) n FROM sales_customer_visits WHERE organization_id=:o AND entity_id=:e AND location_id=:l"), {'o':str(organization_id),'e':str(entity_id),'l':str(location_id)}).scalar_one()
            pending = c.execute(text("SELECT COUNT(*) FROM sales_orders WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND status IN ('DRAFT','SUBMITTED','HOLD')"), {'o':str(organization_id),'e':str(entity_id),'l':str(location_id)}).scalar_one()
            cust = c.execute(text("SELECT COUNT(*) FROM master_record WHERE organization_id=:o AND master_type='CUSTOMER' AND active=1 AND (entity_id=:e OR entity_id IS NULL)"), {'o':str(organization_id),'e':str(entity_id)}).scalar_one()
        return {'counts': {'orders': int(orders['n']), 'order_value': float(orders['total']), 'visits': int(visits), 'open_orders': int(pending), 'active_customers': int(cust)}}

    @app.get('/v90bq/salesperson/customers')
    def customers(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, q: str = '', limit: int = 100):
        _require(engine, request, entity_id, location_id, 'salesperson_ui.view')
        from .v77.persistent_master import MasterRecordORM
        from sqlalchemy.orm import Session
        rows=[]
        with Session(engine, expire_on_commit=False) as s:
            recs = s.query(MasterRecordORM).filter(MasterRecordORM.organization_id==organization_id, MasterRecordORM.master_type=='CUSTOMER', MasterRecordORM.active.is_(True), (MasterRecordORM.entity_id==entity_id) | (MasterRecordORM.entity_id.is_(None))).limit(limit).all()
            ql=q.lower().strip()
            for r in recs:
                d=dict(r.data or {})
                blob=str(d).lower()
                if ql and ql not in blob: continue
                rows.append({**d,'customer_id':str(r.master_id),'entity_id':str(r.entity_id) if r.entity_id else None})
        return {'items': rows, 'total': len(rows)}

    @app.post('/v90bq/salesperson/visits')
    def create_visit(body: VisitIn, request: Request):
        u=_require(engine, request, body.entity_id, body.location_id, 'salesperson_ui.manage')
        visit_id=str(uuid4())
        with engine.begin() as c:
            c.execute(text("""INSERT INTO sales_customer_visits(visit_id,organization_id,entity_id,location_id,customer_id,visit_at,purpose,outcome,next_action,latitude,longitude,created_by) VALUES(:i,:o,:e,:l,:c,:v,:p,:ou,:n,:la,:lo,:u)"""), {'i':visit_id,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'c':str(body.customer_id),'v':body.visit_at.astimezone(timezone.utc).isoformat(),'p':body.purpose,'ou':body.outcome,'n':body.next_action,'la':body.latitude,'lo':body.longitude,'u':str(u.user_id)})
        return {'visit_id':visit_id,'status':'RECORDED'}

    @app.get('/v90bq/salesperson/visits')
    def list_visits(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, customer_id: UUID|None=None, limit:int=100):
        _require(engine, request, entity_id, location_id, 'salesperson_ui.view')
        sql="SELECT * FROM sales_customer_visits WHERE organization_id=:o AND entity_id=:e AND location_id=:l"; params={'o':str(organization_id),'e':str(entity_id),'l':str(location_id)}
        if customer_id: sql += ' AND customer_id=:c'; params['c']=str(customer_id)
        sql += ' ORDER BY visit_at DESC LIMIT :lim'; params['lim']=limit
        with engine.connect() as c: rows=c.execute(text(sql),params).mappings().all()
        return {'items':[dict(r) for r in rows]}

    @app.post('/v90bq/salesperson/onboard/customer')
    def onboard(body: CustomerOnboardIn, request: Request):
        u=_require(engine, request, body.entity_id, body.location_id, 'salesperson_ui.manage')
        code=str(body.payload.get('code') or '').strip(); name=str(body.payload.get('name') or '').strip()
        if not code or not name: raise HTTPException(422,'customer code and name are required')
        # Reuse the operational master approval path; no bypass of existing master governance.
        from .v90k_operational_master import OperationalMasterChange
        from .v90k_operational_master import _service, ChangeRequest, _is_uuid
        from uuid import UUID as _UUID
        try:
            rid=_service(engine).request(ChangeRequest(organization_id=body.organization_id, master_type='CUSTOMER', action='CREATE', requested_by=_UUID(str(u.user_id)) if _is_uuid(u.user_id) else _UUID(int=0), payload=dict(body.payload), entity_id=body.entity_id, effective_from=None,effective_to=None,base_version_no=None,client_event_id=None))
        except Exception as exc:
            raise HTTPException(422,str(exc)) from exc
        return {'request_id':str(rid),'status':'PENDING_APPROVAL'}

    @app.post('/v90bq/salesperson/order-drafts')
    def save_order_draft(body: dict, request: Request):
        required={'organization_id','entity_id','location_id','customer_id','draft_name','payload'}
        if not required.issubset(body): raise HTTPException(422,'missing draft fields')
        u=_require(engine, request, UUID(str(body['entity_id'])), UUID(str(body['location_id'])), 'salesperson_ui.manage')
        import json
        did=str(uuid4())
        with engine.begin() as c:
            c.execute(text("INSERT INTO ui_saved_order_drafts(draft_id,organization_id,entity_id,location_id,customer_id,draft_name,payload,created_by) VALUES(:i,:o,:e,:l,:c,:n,:p,:u) ON CONFLICT(entity_id,location_id,customer_id,draft_name,created_by) DO UPDATE SET payload=excluded.payload,updated_at=CURRENT_TIMESTAMP"), {'i':did,'o':str(body['organization_id']),'e':str(body['entity_id']),'l':str(body['location_id']),'c':str(body['customer_id']),'n':str(body['draft_name']),'p':json.dumps(body['payload']),'u':str(u.user_id)})
        return {'draft_id':did,'status':'SAVED'}

    @app.get('/v90bq/salesperson/order-drafts')
    def list_order_drafts(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, customer_id: UUID|None=None):
        u=_require(engine, request, entity_id, location_id, 'salesperson_ui.view')
        import json
        sql='SELECT * FROM ui_saved_order_drafts WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND created_by=:u'; p={'o':str(organization_id),'e':str(entity_id),'l':str(location_id),'u':str(u.user_id)}
        if customer_id: sql+=' AND customer_id=:c'; p['c']=str(customer_id)
        with engine.connect() as c: rows=c.execute(text(sql+' ORDER BY updated_at DESC'),p).mappings().all()
        return {'items':[{**dict(r),'payload':json.loads(r['payload'])} for r in rows]}

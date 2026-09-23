from __future__ import annotations
from datetime import datetime
from uuid import UUID, uuid4
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed

class PolicyIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    sku_id: UUID | None = None
    target_price: float = Field(gt=0)
    floor_price: float = Field(gt=0)
    min_margin_pct: float | None = Field(default=None, ge=0)
    incentive_basis: str = 'NET_OF_GST'
    effective_from: datetime
    effective_to: datetime | None = None
    notes: str = ''

class PriceCheckIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    sku_id: UUID
    unit_cost: float = Field(gt=0)
    proposed_price: float = Field(gt=0)
    discount_pct: float = Field(default=0, ge=0, lt=100)
    gst_rate: float = Field(default=0, ge=0)

def _ensure(engine: Engine):
    with engine.begin() as c:
        c.execute(text("""CREATE TABLE IF NOT EXISTS price_margin_policy (
            policy_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            sku_id TEXT, target_price REAL NOT NULL, floor_price REAL NOT NULL, min_margin_pct REAL,
            incentive_basis TEXT NOT NULL, effective_from TEXT NOT NULL, effective_to TEXT,
            active INTEGER NOT NULL DEFAULT 1, notes TEXT, created_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""))
        c.execute(text("""CREATE TABLE IF NOT EXISTS price_exception (
            exception_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL, sku_id TEXT NOT NULL, unit_cost REAL NOT NULL,
            proposed_price REAL NOT NULL, discount_pct REAL NOT NULL, taxable_unit_price REAL NOT NULL,
            gst_rate REAL NOT NULL, margin_pct REAL NOT NULL, target_price REAL, floor_price REAL,
            status TEXT NOT NULL, reason TEXT, requested_by TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""))

def _require(engine, request, perm):
    u = authenticate(request)
    if perm not in permissions_for_user(engine, u.user_id):
        raise HTTPException(403, 'permission denied')
    return u

def register_v90aa_routes(app, engine):
    _ensure(engine)
    @app.post('/v90aa/price-policies')
    def create_policy(body: PolicyIn, request: Request):
        u = _require(engine, request, 'price_policy.edit')
        if body.floor_price > body.target_price:
            raise HTTPException(422, 'floor price cannot exceed target price')
        try: assert_entity_location_allowed(engine, u.user_id, str(body.entity_id), None)
        except PermissionError as e: raise HTTPException(403, str(e))
        pid = str(uuid4())
        with engine.begin() as c:
            c.execute(text("""INSERT INTO price_margin_policy
                (policy_id,organization_id,entity_id,sku_id,target_price,floor_price,min_margin_pct,
                 incentive_basis,effective_from,effective_to,notes,created_by)
                VALUES(:id,:o,:e,:s,:t,:f,:m,:b,:ef,:et,:n,:u)"""), {
                'id':pid,'o':str(body.organization_id),'e':str(body.entity_id),
                's':str(body.sku_id) if body.sku_id else None,'t':body.target_price,
                'f':body.floor_price,'m':body.min_margin_pct,'b':body.incentive_basis,
                'ef':body.effective_from.isoformat(),'et':body.effective_to.isoformat() if body.effective_to else None,
                'n':body.notes,'u':str(u.user_id)})
        return {'status':'created','policy_id':pid}

    @app.get('/v90aa/price-policies')
    def list_policies(request: Request, organization_id: UUID, entity_id: UUID):
        u = _require(engine, request, 'price_policy.view')
        try: assert_entity_location_allowed(engine, u.user_id, str(entity_id), None)
        except PermissionError as e: raise HTTPException(403, str(e))
        with engine.connect() as c:
            rows = c.execute(text('SELECT * FROM price_margin_policy WHERE organization_id=:o AND entity_id=:e AND active=1 ORDER BY effective_from DESC'), {'o':str(organization_id),'e':str(entity_id)}).mappings().all()
        return {'items':[dict(r) for r in rows]}

    @app.post('/v90aa/price-check')
    def price_check(body: PriceCheckIn, request: Request):
        u = _require(engine, request, 'sales.edit')
        try: assert_entity_location_allowed(engine, u.user_id, str(body.entity_id), str(body.location_id))
        except PermissionError as e: raise HTTPException(403, str(e))
        with engine.connect() as c:
            pol = c.execute(text("""SELECT * FROM price_margin_policy
                WHERE organization_id=:o AND entity_id=:e AND (sku_id=:s OR sku_id IS NULL) AND active=1
                  AND effective_from <= CURRENT_TIMESTAMP
                  AND (effective_to IS NULL OR effective_to >= CURRENT_TIMESTAMP)
                ORDER BY CASE WHEN sku_id IS NULL THEN 1 ELSE 0 END, effective_from DESC"""),
                {'o':str(body.organization_id),'e':str(body.entity_id),'s':str(body.sku_id)}).mappings().first()
        net = body.proposed_price * (1 - body.discount_pct/100)
        margin = (net - body.unit_cost) / body.unit_cost * 100
        status, reason = 'OK', ''
        if pol and net < float(pol['floor_price']):
            status, reason = 'BELOW_FLOOR', 'net negotiated price is below protected floor'
        elif pol and pol['min_margin_pct'] is not None and margin < float(pol['min_margin_pct']):
            status, reason = 'BELOW_MIN_MARGIN', 'margin below policy threshold'
        return {'status':status,'reason':reason,'unit_cost':body.unit_cost,
                'target_price':float(pol['target_price']) if pol else None,
                'floor_price':float(pol['floor_price']) if pol else None,
                'proposed_price':body.proposed_price,'discount_pct':body.discount_pct,
                'taxable_unit_price':round(net,2),'gst_rate':body.gst_rate,
                'gst_amount':round(net*body.gst_rate/100,2),
                'invoice_unit_total':round(net*(1+body.gst_rate/100),2),
                'margin_pct':round(margin,2),'approval_required':status!='OK'}

    @app.post('/v90aa/price-exceptions')
    def request_exception(body: PriceCheckIn, request: Request):
        u = _require(engine, request, 'sales.edit')
        pricing = price_check(body, request)
        if not pricing['approval_required']:
            return {'status':'NOT_REQUIRED','pricing':pricing}
        eid = str(uuid4())
        with engine.begin() as c:
            c.execute(text("""INSERT INTO price_exception
                (exception_id,organization_id,entity_id,location_id,sku_id,unit_cost,proposed_price,
                 discount_pct,taxable_unit_price,gst_rate,margin_pct,target_price,floor_price,status,reason,requested_by)
                VALUES(:id,:o,:e,:l,:s,:c,:p,:d,:t,:g,:m,:tp,:fp,'PENDING',:r,:u)"""), {
                'id':eid,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),
                's':str(body.sku_id),'c':body.unit_cost,'p':body.proposed_price,'d':body.discount_pct,
                't':pricing['taxable_unit_price'],'g':body.gst_rate,'m':pricing['margin_pct'],
                'tp':pricing['target_price'],'fp':pricing['floor_price'],'r':pricing['reason'],'u':str(u.user_id)})
        return {'status':'PENDING_APPROVAL','exception_id':eid,'pricing':pricing}

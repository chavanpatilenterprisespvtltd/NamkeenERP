from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed

class IncentiveRuleIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    rule_name: str = Field(min_length=2, max_length=120)
    rule_type: str = Field(default='PERCENT_OF_NET_SALES')
    rate: float = Field(gt=0)
    min_margin_pct: float | None = Field(default=None, ge=0)
    min_net_price: float | None = Field(default=None, gt=0)
    fixed_amount: float | None = Field(default=None, gt=0)
    effective_from: datetime
    effective_to: datetime | None = None
    active: bool = True
    notes: str = ''

class IncentiveCalculateIn(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID
    salesperson_user_id: str
    sku_id: UUID
    quantity: float = Field(gt=0)
    unit_cost: float = Field(gt=0)
    approved_net_unit_price: float = Field(gt=0)
    discount_pct: float = Field(default=0, ge=0, le=100)
    gst_rate: float = Field(default=0, ge=0)
    sales_order_id: UUID | None = None


def ensure_v90ab_schema(engine):
    stmts = [
        """CREATE TABLE IF NOT EXISTS incentive_rules (
            incentive_rule_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            rule_name TEXT NOT NULL, rule_type TEXT NOT NULL, rate REAL NOT NULL,
            min_margin_pct REAL, min_net_price REAL, fixed_amount REAL,
            effective_from TEXT NOT NULL, effective_to TEXT, active INTEGER NOT NULL DEFAULT 1,
            notes TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS incentive_accruals (
            incentive_accrual_id TEXT PRIMARY KEY, incentive_rule_id TEXT NOT NULL, organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL, location_id TEXT NOT NULL, salesperson_user_id TEXT NOT NULL,
            sku_id TEXT NOT NULL, sales_order_id TEXT, quantity REAL NOT NULL, unit_cost REAL NOT NULL,
            gross_net_sales REAL NOT NULL, net_sales REAL NOT NULL, margin_pct REAL NOT NULL,
            incentive_amount REAL NOT NULL, status TEXT NOT NULL DEFAULT 'ACCRUED', reason TEXT,
            created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        "CREATE INDEX IF NOT EXISTS ix_incentive_rules_scope ON incentive_rules(organization_id,entity_id,active,effective_from)",
        "CREATE INDEX IF NOT EXISTS ix_incentive_accrual_scope ON incentive_accruals(entity_id,salesperson_user_id,status,created_at)",
    ]
    with engine.begin() as conn:
        for s in stmts:
            conn.execute(text(s))


def _require(engine, request: Request, perm: str):
    user = authenticate(request)
    if perm not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    return user


def _active_rule(engine, organization_id: str, entity_id: str):
    now = datetime.now(timezone.utc)
    with engine.connect() as conn:
        rows = conn.execute(text("""SELECT * FROM incentive_rules
                WHERE organization_id=:o AND entity_id=:e AND active=1
                ORDER BY effective_from DESC"""), {'o': organization_id, 'e': entity_id}).mappings().all()
    for rule in rows:
        try:
            start = datetime.fromisoformat(str(rule['effective_from']).replace('Z', '+00:00'))
            if start.tzinfo is None: start = start.replace(tzinfo=timezone.utc)
            end = rule['effective_to']
            end_dt = None
            if end:
                end_dt = datetime.fromisoformat(str(end).replace('Z', '+00:00'))
                if end_dt.tzinfo is None: end_dt = end_dt.replace(tzinfo=timezone.utc)
            if start <= now and (end_dt is None or end_dt >= now):
                return rule
        except (TypeError, ValueError):
            continue
    return None

def register_v90ab_routes(app: FastAPI, engine):
    ensure_v90ab_schema(engine)

    @app.post('/v90ab/incentive-rules')
    def create_rule(body: IncentiveRuleIn, request: Request):
        user = _require(engine, request, 'incentive_policy.edit')
        if body.rule_type not in {'PERCENT_OF_NET_SALES','FIXED_PER_UNIT'}:
            raise HTTPException(422, 'unsupported incentive rule type')
        if body.rule_type == 'FIXED_PER_UNIT' and body.fixed_amount is None:
            raise HTTPException(422, 'fixed_amount required for FIXED_PER_UNIT')
        if body.rule_type == 'PERCENT_OF_NET_SALES' and body.rate > 100:
            raise HTTPException(422, 'rate cannot exceed 100')
        if body.effective_to and body.effective_to < body.effective_from:
            raise HTTPException(422, 'effective_to must be after effective_from')
        try: assert_entity_location_allowed(engine, user.user_id, str(body.entity_id), None)
        except PermissionError as e: raise HTTPException(403, str(e))
        rid = str(uuid4())
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO incentive_rules
                (incentive_rule_id,organization_id,entity_id,rule_name,rule_type,rate,min_margin_pct,min_net_price,fixed_amount,effective_from,effective_to,active,notes,created_by)
                VALUES(:id,:o,:e,:n,:t,:r,:mm,:mn,:fa,:ef,:et,:a,:notes,:u)"""), {
                'id':rid,'o':str(body.organization_id),'e':str(body.entity_id),'n':body.rule_name,'t':body.rule_type,
                'r':body.rate,'mm':body.min_margin_pct,'mn':body.min_net_price,'fa':body.fixed_amount,
                'ef':body.effective_from.isoformat(),'et':body.effective_to.isoformat() if body.effective_to else None,
                'a':1 if body.active else 0,'notes':body.notes,'u':str(user.user_id)})
        return {'status':'created','incentive_rule_id':rid}

    @app.get('/v90ab/incentive-rules')
    def list_rules(request: Request, organization_id: UUID, entity_id: UUID):
        user = _require(engine, request, 'incentive_policy.view')
        try: assert_entity_location_allowed(engine, user.user_id, str(entity_id), None)
        except PermissionError as e: raise HTTPException(403, str(e))
        with engine.connect() as conn:
            rows = conn.execute(text('SELECT * FROM incentive_rules WHERE organization_id=:o AND entity_id=:e ORDER BY effective_from DESC'), {'o':str(organization_id),'e':str(entity_id)}).mappings().all()
        return {'items':[dict(r) for r in rows]}

    @app.post('/v90ab/incentives/calculate')
    def calculate(body: IncentiveCalculateIn, request: Request):
        user = _require(engine, request, 'sales.edit')
        try: assert_entity_location_allowed(engine, user.user_id, str(body.entity_id), str(body.location_id))
        except PermissionError as e: raise HTTPException(403, str(e))
        rule = _active_rule(engine, str(body.organization_id), str(body.entity_id))
        net_unit = body.approved_net_unit_price * (1 - body.discount_pct/100)
        margin_pct = (net_unit - body.unit_cost) / body.unit_cost * 100
        gross_net_sales = body.quantity * body.approved_net_unit_price
        net_sales = body.quantity * net_unit
        eligible = bool(rule)
        reason = '' if rule else 'no active incentive rule'
        amount = 0.0
        if rule:
            if rule['min_net_price'] is not None and net_unit < float(rule['min_net_price']):
                eligible = False; reason = 'net price below incentive threshold'
            elif rule['min_margin_pct'] is not None and margin_pct < float(rule['min_margin_pct']):
                eligible = False; reason = 'margin below incentive threshold'
            elif rule['rule_type'] == 'PERCENT_OF_NET_SALES':
                amount = net_sales * float(rule['rate'])/100
            else:
                amount = body.quantity * float(rule['fixed_amount'])
        return {'eligible':eligible,'reason':reason,'incentive_rule_id':rule['incentive_rule_id'] if rule and eligible else None,
                'rule_name':rule['rule_name'] if rule else None,'net_unit_price':round(net_unit,4),'net_sales':round(net_sales,2),
                'gross_net_sales':round(gross_net_sales,2),'margin_pct':round(margin_pct,2),'incentive_amount':round(amount,2),
                'gst_amount':round(net_sales*body.gst_rate/100,2),'basis':'NET_OF_GST'}

    @app.post('/v90ab/incentives/accrue')
    def accrue(body: IncentiveCalculateIn, request: Request):
        user = _require(engine, request, 'sales.edit')
        calc = calculate(body, request)
        if not calc['eligible']:
            return {'status':'NOT_ELIGIBLE','calculation':calc}
        aid = str(uuid4())
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO incentive_accruals
                (incentive_accrual_id,incentive_rule_id,organization_id,entity_id,location_id,salesperson_user_id,sku_id,sales_order_id,quantity,unit_cost,gross_net_sales,net_sales,margin_pct,incentive_amount,status,reason,created_by)
                VALUES(:id,:r,:o,:e,:l,:s,:sku,:so,:q,:c,:g,:n,:m,:a,'ACCRUED',:reason,:u)"""), {
                'id':aid,'r':calc['incentive_rule_id'],'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),
                's':body.salesperson_user_id,'sku':str(body.sku_id),'so':str(body.sales_order_id) if body.sales_order_id else None,
                'q':body.quantity,'c':body.unit_cost,'g':calc['gross_net_sales'],'n':calc['net_sales'],'m':calc['margin_pct'],'a':calc['incentive_amount'],'reason':'qualifying commercial event','u':str(user.user_id)})
        return {'status':'ACCRUED','incentive_accrual_id':aid,'calculation':calc}

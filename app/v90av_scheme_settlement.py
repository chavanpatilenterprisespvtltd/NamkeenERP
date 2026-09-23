from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed

MONEY = Decimal('0.01')
def money(v): return float(Decimal(str(v or 0)).quantize(MONEY, rounding=ROUND_HALF_UP))

def _require(engine, request: Request, perm: str, entity_id: str, location_id: Optional[str]=None):
    user = authenticate(request)
    if perm not in permissions_for_user(engine, user.user_id): raise HTTPException(403, 'permission denied')
    try: assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc: raise HTTPException(403, str(exc)) from exc
    return user

class SchemeIn(BaseModel):
    organization_id: UUID; entity_id: UUID; scheme_name: str = Field(min_length=2, max_length=160)
    scheme_type: str = Field(default='PERCENT_DISCOUNT'); discount_pct: float = Field(default=0, ge=0, le=100)
    fixed_amount: float | None = Field(default=None, ge=0); min_invoice_value: float | None = Field(default=None, ge=0)
    max_settlement: float | None = Field(default=None, ge=0); effective_from: datetime; effective_to: datetime | None = None
    active: bool = True; notes: str = ''

class DiscountSettlementIn(BaseModel):
    organization_id: UUID; entity_id: UUID; location_id: UUID; sales_invoice_id: UUID
    scheme_id: UUID; eligible_base: float = Field(gt=0); requested_discount: float = Field(ge=0)
    settlement_reference: str = Field(min_length=2, max_length=120); notes: str = ''

class IncentiveSettlementIn(BaseModel):
    organization_id: UUID; entity_id: UUID; location_id: UUID; salesperson_user_id: str
    period_from: str; period_to: str; settlement_reference: str = Field(min_length=2, max_length=120)
    notes: str = ''

def ensure_v90av_schema(engine):
    stmts=[
      """CREATE TABLE IF NOT EXISTS commercial_schemes (
        scheme_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
        scheme_name TEXT NOT NULL, scheme_type TEXT NOT NULL, discount_pct NUMERIC NOT NULL DEFAULT 0,
        fixed_amount NUMERIC, min_invoice_value NUMERIC, max_settlement NUMERIC,
        effective_from TEXT NOT NULL, effective_to TEXT, active INTEGER NOT NULL DEFAULT 1,
        notes TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
      """CREATE TABLE IF NOT EXISTS discount_settlements (
        discount_settlement_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
        location_id TEXT NOT NULL, sales_invoice_id TEXT NOT NULL, scheme_id TEXT NOT NULL,
        eligible_base NUMERIC NOT NULL, requested_discount NUMERIC NOT NULL, approved_discount NUMERIC NOT NULL,
        status TEXT NOT NULL, settlement_reference TEXT NOT NULL, notes TEXT, created_by TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(sales_invoice_id, scheme_id, settlement_reference))""",
      """CREATE TABLE IF NOT EXISTS incentive_settlements (
        incentive_settlement_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
        location_id TEXT NOT NULL, salesperson_user_id TEXT NOT NULL, period_from TEXT NOT NULL, period_to TEXT NOT NULL,
        gross_accrual NUMERIC NOT NULL, reversal_total NUMERIC NOT NULL, payable_amount NUMERIC NOT NULL,
        status TEXT NOT NULL, settlement_reference TEXT NOT NULL, notes TEXT, created_by TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(salesperson_user_id,period_from,period_to,settlement_reference))""",
      "CREATE INDEX IF NOT EXISTS ix_scheme_scope ON commercial_schemes(entity_id,active,effective_from)",
      "CREATE INDEX IF NOT EXISTS ix_discount_settlement_scope ON discount_settlements(entity_id,location_id,created_at)",
      "CREATE INDEX IF NOT EXISTS ix_incentive_settlement_scope ON incentive_settlements(entity_id,salesperson_user_id,period_from,period_to)",
      "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('scheme.view','View commercial schemes') ON CONFLICT(permission_id) DO NOTHING",
      "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('scheme.edit','Manage commercial schemes and settlements') ON CONFLICT(permission_id) DO NOTHING",
      "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('incentive.settle','Settle salesperson incentives') ON CONFLICT(permission_id) DO NOTHING",
    ]
    with engine.begin() as c:
      for s in stmts: c.execute(text(s))
      for role in ('manager','super_admin','accounts'):
        for p in ('scheme.view','scheme.edit','incentive.settle'):
          c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'r':role,'p':p})
      c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('salesperson','scheme.view') ON CONFLICT(role_id,permission_id) DO NOTHING"))

def register_v90av_routes(app: FastAPI, engine):
    ensure_v90av_schema(engine)
    @app.post('/v90av/schemes')
    def create_scheme(body: SchemeIn, request: Request):
      u=_require(engine,request,'scheme.edit',str(body.entity_id))
      if body.scheme_type not in {'PERCENT_DISCOUNT','FIXED_DISCOUNT'}: raise HTTPException(422,'unsupported scheme type')
      if body.scheme_type=='PERCENT_DISCOUNT' and body.discount_pct<=0: raise HTTPException(422,'discount_pct required')
      if body.scheme_type=='FIXED_DISCOUNT' and (body.fixed_amount is None or body.fixed_amount<=0): raise HTTPException(422,'fixed_amount required')
      if body.effective_to and body.effective_to<body.effective_from: raise HTTPException(422,'effective_to must be after effective_from')
      sid=str(uuid4())
      with engine.begin() as c: c.execute(text("""INSERT INTO commercial_schemes(scheme_id,organization_id,entity_id,scheme_name,scheme_type,discount_pct,fixed_amount,min_invoice_value,max_settlement,effective_from,effective_to,active,notes,created_by) VALUES(:id,:o,:e,:n,:t,:d,:f,:m,:x,:ef,:et,:a,:notes,:u)"""),{'id':sid,'o':str(body.organization_id),'e':str(body.entity_id),'n':body.scheme_name,'t':body.scheme_type,'d':body.discount_pct,'f':body.fixed_amount,'m':body.min_invoice_value,'x':body.max_settlement,'ef':body.effective_from.isoformat(),'et':body.effective_to.isoformat() if body.effective_to else None,'a':1 if body.active else 0,'notes':body.notes,'u':str(u.user_id)})
      return {'status':'created','scheme_id':sid}

    @app.get('/v90av/schemes')
    def list_schemes(organization_id: UUID, entity_id: UUID, request: Request):
      _require(engine,request,'scheme.view',str(entity_id))
      with engine.connect() as c: rows=c.execute(text('SELECT * FROM commercial_schemes WHERE organization_id=:o AND entity_id=:e ORDER BY effective_from DESC'),{'o':str(organization_id),'e':str(entity_id)}).mappings().all()
      return {'items':[dict(r) for r in rows]}

    @app.post('/v90av/discount-settlements')
    def settle_discount(body: DiscountSettlementIn, request: Request):
      u=_require(engine,request,'scheme.edit',str(body.entity_id),str(body.location_id))
      if body.requested_discount>body.eligible_base: raise HTTPException(422,'discount cannot exceed eligible base')
      with engine.connect() as c:
        scheme=c.execute(text('SELECT * FROM commercial_schemes WHERE scheme_id=:s AND organization_id=:o AND entity_id=:e AND active=1'),{'s':str(body.scheme_id),'o':str(body.organization_id),'e':str(body.entity_id)}).mappings().first()
      if not scheme: raise HTTPException(404,'scheme not found')
      if scheme['min_invoice_value'] is not None and body.eligible_base < float(scheme['min_invoice_value']): raise HTTPException(422,'invoice/base below scheme minimum')
      computed=body.eligible_base*float(scheme['discount_pct'])/100 if scheme['scheme_type']=='PERCENT_DISCOUNT' else float(scheme['fixed_amount'])
      approved=min(body.requested_discount,computed)
      if scheme['max_settlement'] is not None: approved=min(approved,float(scheme['max_settlement']))
      sid=str(uuid4())
      with engine.begin() as c: c.execute(text("""INSERT INTO discount_settlements(discount_settlement_id,organization_id,entity_id,location_id,sales_invoice_id,scheme_id,eligible_base,requested_discount,approved_discount,status,settlement_reference,notes,created_by) VALUES(:id,:o,:e,:l,:i,:s,:b,:r,:a,'APPROVED',:ref,:n,:u)"""),{'id':sid,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'i':str(body.sales_invoice_id),'s':str(body.scheme_id),'b':money(body.eligible_base),'r':money(body.requested_discount),'a':money(approved),'ref':body.settlement_reference,'n':body.notes,'u':str(u.user_id)})
      return {'status':'APPROVED','discount_settlement_id':sid,'approved_discount':money(approved)}

    @app.post('/v90av/incentive-settlements')
    def settle_incentives(body: IncentiveSettlementIn, request: Request):
      u=_require(engine,request,'incentive.settle',str(body.entity_id),str(body.location_id))
      try: datetime.fromisoformat(body.period_from); datetime.fromisoformat(body.period_to)
      except ValueError as exc: raise HTTPException(422,'invalid period date') from exc
      with engine.connect() as c:
        gross=float(c.execute(text("SELECT COALESCE(SUM(incentive_amount),0) FROM incentive_accruals WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND salesperson_user_id=:s AND date(created_at) BETWEEN date(:f) AND date(:t) AND status IN ('ACCRUED','APPROVED')"),{'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'s':body.salesperson_user_id,'f':body.period_from,'t':body.period_to}).scalar() or 0)
        rev=float(c.execute(text("SELECT COALESCE(SUM(reversal_amount),0) FROM incentive_reversals WHERE salesperson_user_id=:s AND date(created_at) BETWEEN date(:f) AND date(:t)"),{'s':body.salesperson_user_id,'f':body.period_from,'t':body.period_to}).scalar() or 0)
      payable=max(0,gross-rev)
      sid=str(uuid4())
      with engine.begin() as c: c.execute(text("""INSERT INTO incentive_settlements(incentive_settlement_id,organization_id,entity_id,location_id,salesperson_user_id,period_from,period_to,gross_accrual,reversal_total,payable_amount,status,settlement_reference,notes,created_by) VALUES(:id,:o,:e,:l,:s,:f,:t,:g,:r,:p,'SETTLED',:ref,:n,:u)"""),{'id':sid,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id),'s':body.salesperson_user_id,'f':body.period_from,'t':body.period_to,'g':money(gross),'r':money(rev),'p':money(payable),'ref':body.settlement_reference,'n':body.notes,'u':str(u.user_id)})
      return {'status':'SETTLED','incentive_settlement_id':sid,'gross_accrual':money(gross),'reversal_total':money(rev),'payable_amount':money(payable)}

    @app.get('/v90av/incentive-settlements')
    def list_incentive_settlements(organization_id: UUID, entity_id: UUID, request: Request, salesperson_user_id: str|None=None):
      _require(engine,request,'scheme.view',str(entity_id))
      params={'o':str(organization_id),'e':str(entity_id)}; sql='SELECT * FROM incentive_settlements WHERE organization_id=:o AND entity_id=:e'
      if salesperson_user_id: sql+=' AND salesperson_user_id=:s'; params['s']=salesperson_user_id
      sql+=' ORDER BY created_at DESC'
      with engine.connect() as c: rows=c.execute(text(sql),params).mappings().all()
      return {'items':[dict(r) for r in rows]}

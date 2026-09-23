from __future__ import annotations
import json
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed

MONEY = Decimal('0.01')

def _money(v):
    return float(Decimal(str(v or 0)).quantize(MONEY, rounding=ROUND_HALF_UP))

def _as_date(v: str | None) -> str:
    if not v:
        return date.today().isoformat()
    try:
        return datetime.fromisoformat(v.replace('Z', '+00:00')).date().isoformat()
    except ValueError as exc:
        raise HTTPException(422, 'invalid date; use ISO-8601') from exc

def _require(engine, request: Request, entity_id: str, location_id: str | None, write=False):
    user = authenticate(request)
    perm = 'sales_mis.edit' if write else 'sales_mis.view'
    if perm not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user

def ensure_v90at_schema(engine):
    stmts = [
        """CREATE TABLE IF NOT EXISTS sales_mis_snapshot (
            snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT NULL, from_date TEXT NOT NULL, to_date TEXT NOT NULL,
            gross_sales NUMERIC NOT NULL DEFAULT 0, net_sales NUMERIC NOT NULL DEFAULT 0,
            gst_value NUMERIC NOT NULL DEFAULT 0, order_count INTEGER NOT NULL DEFAULT 0,
            customer_count INTEGER NOT NULL DEFAULT 0, dispatched_qty NUMERIC NOT NULL DEFAULT 0,
            invoice_count INTEGER NOT NULL DEFAULT 0, collections NUMERIC NOT NULL DEFAULT 0,
            outstanding NUMERIC NOT NULL DEFAULT 0, overdue_outstanding NUMERIC NOT NULL DEFAULT 0,
            credit_utilization_pct NUMERIC NOT NULL DEFAULT 0, calculated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            calculated_by TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS ix_sales_mis_scope ON sales_mis_snapshot(entity_id,location_id,from_date,to_date,calculated_at)",
        "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('sales_mis.view','View sales MIS and territory reporting') ON CONFLICT(permission_id) DO NOTHING",
        "INSERT INTO erp_permissions(permission_id,permission_name) VALUES('sales_mis.edit','Create sales MIS snapshots') ON CONFLICT(permission_id) DO NOTHING",
    ]
    with engine.begin() as conn:
        for s in stmts:
            conn.execute(text(s))
        for role in ('manager','super_admin','accounts'):
            for p in ('sales_mis.view','sales_mis.edit'):
                conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role,'p':p})
        conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('salesperson','sales_mis.view') ON CONFLICT(role_id,permission_id) DO NOTHING"))

def _customer_profile(data):
    try:
        return json.loads(data or '{}') if isinstance(data, str) else dict(data or {})
    except Exception:
        return {}

def _customer_meta(conn, organization_id: str, entity_id: str):
    rows = conn.execute(text("SELECT master_id,data FROM master_record WHERE organization_id=:o AND master_type='CUSTOMER' AND active=1 AND (entity_id IS NULL OR entity_id=:e)"), {'o':organization_id,'e':entity_id}).mappings().all()
    meta = {}
    for r in rows:
        d = _customer_profile(r['data'])
        meta[str(r['master_id'])] = {
            'name': d.get('name') or d.get('customer_name') or str(r['master_id']),
            'channel': str(d.get('channel') or d.get('customer_type') or d.get('customer_category') or 'UNCLASSIFIED'),
            'territory_id': d.get('territory_id') or d.get('territory') or 'UNASSIGNED',
            'territory_name': d.get('territory_name'),
            'salesperson_user_id': d.get('salesperson_user_id') or d.get('salesperson_id') or 'UNASSIGNED',
            'credit_limit': float(d.get('credit_limit') or 0),
        }
    return meta

def _date_where(alias, column, fd, td, loc):
    clause = f"date({alias}.{column}) BETWEEN :fd AND :td"
    if loc: clause += f" AND {alias}.location_id=:l"
    return clause

def _compute(engine, organization_id: str, entity_id: str, location_id: str | None, fd: str, td: str):
    with engine.connect() as conn:
        meta = _customer_meta(conn, organization_id, entity_id)
        params={'o':organization_id,'e':entity_id,'fd':fd,'td':td}
        if location_id: params['l']=location_id
        loc_sales = ' AND so.location_id=:l' if location_id else ''
        loc_inv = ' AND si.location_id=:l' if location_id else ''
        loc_disp = ' AND d.location_id=:l' if location_id else ''
        orders = conn.execute(text(f"SELECT sales_order_id,customer_id,subtotal,discount_total,taxable_value,gst_total,grand_total FROM sales_orders so WHERE so.organization_id=:o AND so.entity_id=:e AND date(so.created_at) BETWEEN :fd AND :td{loc_sales}"), params).mappings().all()
        invoices = conn.execute(text(f"SELECT si.invoice_id,so.customer_id,si.grand_total,si.gst_total,si.created_at FROM sales_invoices si JOIN sales_orders so ON so.sales_order_id=si.sales_order_id WHERE si.organization_id=:o AND si.entity_id=:e AND si.status='POSTED' AND date(si.created_at) BETWEEN :fd AND :td{loc_inv}"), params).mappings().all()
        dispatched = conn.execute(text(f"SELECT COALESCE(SUM(dl.dispatched_qty),0) qty FROM dispatch_lines dl JOIN dispatches d ON d.dispatch_id=dl.dispatch_id WHERE d.organization_id=:o AND d.entity_id=:e AND date(COALESCE(d.posted_at,d.created_at)) BETWEEN :fd AND :td{loc_disp}"), params).scalar() or 0
        # Collections are intentionally tied to allocation/payment tables rather than raw proof rows.
        collections = conn.execute(text(f"SELECT COALESCE(SUM(pa.amount),0) FROM payment_allocations pa JOIN payment_transactions cp ON cp.payment_id=pa.payment_id WHERE cp.organization_id=:o AND cp.entity_id=:e AND cp.status IN ('VERIFIED','CLEARED','POSTED') AND date(cp.payment_date) BETWEEN :fd AND :td"), params).scalar() or 0
        customers = sorted(set(str(o['customer_id']) for o in orders))
        by_territory = {}; by_salesperson = {}; by_channel = {}
        for o in orders:
            cid=str(o['customer_id']); m=meta.get(cid, {'name':cid,'channel':'UNCLASSIFIED','territory_id':'UNASSIGNED','territory_name':None,'salesperson_user_id':'UNASSIGNED','credit_limit':0})
            net=float(o['grand_total'] or 0)
            for bucket,key in ((by_territory,m['territory_id']),(by_salesperson,m['salesperson_user_id']),(by_channel,m['channel'])):
                x=bucket.setdefault(key, {'key':key,'order_count':0,'sales_value':0.0,'customer_count':set()})
                x['order_count']+=1; x['sales_value']+=net; x['customer_count'].add(cid)
        for bucket in (by_territory,by_salesperson,by_channel):
            for x in bucket.values(): x['sales_value']=_money(x['sales_value']); x['customer_count']=len(x['customer_count'])
        gross=sum(float(o['subtotal'] or 0) for o in orders); net=sum(float(i['grand_total'] or 0) for i in invoices); gst=sum(float(i['gst_total'] or 0) for i in invoices)
        outstanding_rows=conn.execute(text("SELECT si.invoice_id,so.customer_id,si.grand_total FROM sales_invoices si JOIN sales_orders so ON so.sales_order_id=si.sales_order_id WHERE si.organization_id=:o AND si.entity_id=:e AND si.status='POSTED'"), {'o':organization_id,'e':entity_id}).mappings().all()
        outstanding=0.0
        for r in outstanding_rows:
            alloc=conn.execute(text("SELECT COALESCE(SUM(amount),0) FROM payment_allocations pa JOIN payment_transactions cp ON cp.payment_id=pa.payment_id WHERE cp.entity_id=:e AND pa.invoice_id=:i AND cp.status IN ('VERIFIED','CLEARED','POSTED')"), {'e':entity_id,'i':r.get('invoice_id')}).scalar() or 0
            outstanding += max(0.0,float(r['grand_total'] or 0)-float(alloc))
        credit_limit=sum(meta.get(c,{}).get('credit_limit',0) for c in customers)
        util=(outstanding*100/credit_limit) if credit_limit else 0.0
        return {
            'organization_id':organization_id,'entity_id':entity_id,'location_id':location_id,'from_date':fd,'to_date':td,
            'gross_sales':_money(gross),'net_sales':_money(net),'gst_value':_money(gst),'order_count':len(orders),
            'customer_count':len(customers),'dispatched_qty':_money(dispatched),'invoice_count':len(invoices),
            'collections':_money(collections),'outstanding':_money(outstanding),'overdue_outstanding':_money(0),
            'credit_utilization_pct':_money(util),'by_territory':list(by_territory.values()),
            'by_salesperson':list(by_salesperson.values()),'by_channel':list(by_channel.values())}

class SalesMISQuery(BaseModel):
    organization_id: UUID
    entity_id: UUID
    location_id: UUID | None = None
    from_date: str | None = None
    to_date: str | None = None


def register_v90at_routes(app: FastAPI, engine):
    ensure_v90at_schema(engine)
    @app.post('/v90at/sales-mis/snapshots')
    def create_snapshot(body: SalesMISQuery, request: Request):
        user=_require(engine,request,str(body.entity_id),str(body.location_id) if body.location_id else None,write=True)
        fd=_as_date(body.from_date); td=_as_date(body.to_date or body.from_date)
        if fd>td: raise HTTPException(422,'from_date cannot be after to_date')
        data=_compute(engine,str(body.organization_id),str(body.entity_id),str(body.location_id) if body.location_id else None,fd,td)
        sid=str(uuid4())
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO sales_mis_snapshot(snapshot_id,organization_id,entity_id,location_id,from_date,to_date,gross_sales,net_sales,gst_value,order_count,customer_count,dispatched_qty,invoice_count,collections,outstanding,overdue_outstanding,credit_utilization_pct,calculated_by) VALUES(:id,:o,:e,:l,:fd,:td,:gs,:ns,:gst,:oc,:cc,:dq,:ic,:col,:out,:ov,:cu,:by)"""), {**{'id':sid,'o':data['organization_id'],'e':data['entity_id'],'l':data['location_id'],'fd':fd,'td':td,'gs':data['gross_sales'],'ns':data['net_sales'],'gst':data['gst_value'],'oc':data['order_count'],'cc':data['customer_count'],'dq':data['dispatched_qty'],'ic':data['invoice_count'],'col':data['collections'],'out':data['outstanding'],'ov':data['overdue_outstanding'],'cu':data['credit_utilization_pct'],'by':str(user.user_id)}})
        return {'status':'created','snapshot_id':sid,'report':data}

    @app.get('/v90at/sales-mis')
    def sales_mis(organization_id: UUID, entity_id: UUID, request: Request, location_id: UUID|None=None, from_date: str|None=None, to_date: str|None=None):
        _require(engine,request,str(entity_id),str(location_id) if location_id else None)
        fd=_as_date(from_date); td=_as_date(to_date or from_date)
        if fd>td: raise HTTPException(422,'from_date cannot be after to_date')
        return _compute(engine,str(organization_id),str(entity_id),str(location_id) if location_id else None,fd,td)

    @app.get('/v90at/sales-mis/snapshots')
    def list_snapshots(organization_id: UUID, entity_id: UUID, request: Request, location_id: UUID|None=None, limit: int=20):
        _require(engine,request,str(entity_id),str(location_id) if location_id else None)
        limit=max(1,min(limit,100)); params={'o':str(organization_id),'e':str(entity_id),'lim':limit}
        sql='SELECT * FROM sales_mis_snapshot WHERE organization_id=:o AND entity_id=:e'
        if location_id: sql+=' AND location_id=:l'; params['l']=str(location_id)
        sql+=' ORDER BY calculated_at DESC LIMIT :lim'
        with engine.connect() as conn: rows=conn.execute(text(sql),params).mappings().all()
        return {'snapshots':[dict(r) for r in rows]}

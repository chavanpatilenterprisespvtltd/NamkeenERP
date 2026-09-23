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

MONEY=Decimal('0.01')
def money(v): return float(Decimal(str(v or 0)).quantize(MONEY, rounding=ROUND_HALF_UP))
def iso_date(v):
    if not v: return date.today().isoformat()
    try: return datetime.fromisoformat(v.replace('Z','+00:00')).date().isoformat()
    except ValueError as e: raise HTTPException(422,'invalid date; use ISO-8601') from e

def require(engine, request, entity_id, location_id=None, write=False):
    u=authenticate(request); p='sales_distribution.edit' if write else 'sales_distribution.view'
    if p not in permissions_for_user(engine,u.user_id): raise HTTPException(403,'permission denied')
    try: assert_entity_location_allowed(engine,u.user_id,str(entity_id),str(location_id) if location_id else None)
    except PermissionError as e: raise HTTPException(403,str(e)) from e
    return u

def ensure_v90gn_schema(engine):
    with engine.begin() as c:
        c.execute(text("""CREATE TABLE IF NOT EXISTS erp_sales_distribution_snapshot (snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL, from_date TEXT NOT NULL, to_date TEXT NOT NULL, net_sales NUMERIC NOT NULL DEFAULT 0, invoice_count INTEGER NOT NULL DEFAULT 0, order_count INTEGER NOT NULL DEFAULT 0, customer_count INTEGER NOT NULL DEFAULT 0, dispatched_qty NUMERIC NOT NULL DEFAULT 0, return_value NUMERIC NOT NULL DEFAULT 0, collection_value NUMERIC NOT NULL DEFAULT 0, active_customer_count INTEGER NOT NULL DEFAULT 0, repeat_customer_count INTEGER NOT NULL DEFAULT 0, on_time_dispatch_pct NUMERIC NOT NULL DEFAULT 0, return_rate_pct NUMERIC NOT NULL DEFAULT 0, collection_realization_pct NUMERIC NOT NULL DEFAULT 0, avg_order_value NUMERIC NOT NULL DEFAULT 0, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id,location_id,from_date,to_date))"""))
        c.execute(text("""CREATE TABLE IF NOT EXISTS erp_sales_distribution_dimension_snapshot (row_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL, dimension_type TEXT NOT NULL, dimension_key TEXT NOT NULL, dimension_name TEXT NULL, sales_value NUMERIC NOT NULL DEFAULT 0, order_count INTEGER NOT NULL DEFAULT 0, customer_count INTEGER NOT NULL DEFAULT 0, dispatched_qty NUMERIC NOT NULL DEFAULT 0, collection_value NUMERIC NOT NULL DEFAULT 0, return_value NUMERIC NOT NULL DEFAULT 0, productivity_score NUMERIC NOT NULL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(snapshot_id,dimension_type,dimension_key))"""))
        c.execute(text("""CREATE TABLE IF NOT EXISTS erp_sales_distribution_actions (action_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL, dimension_type TEXT NOT NULL, dimension_key TEXT NOT NULL, action_type TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'MEDIUM', reason TEXT NOT NULL, owner_user_id TEXT NULL, due_date TEXT NULL, status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, closed_at TIMESTAMP NULL)"""))
        c.execute(text("CREATE INDEX IF NOT EXISTS ix_sales_distribution_scope ON erp_sales_distribution_snapshot(organization_id,entity_id,location_id,to_date)"))
        c.execute(text("CREATE INDEX IF NOT EXISTS ix_sales_distribution_dimension ON erp_sales_distribution_dimension_snapshot(snapshot_id,dimension_type)"))
        c.execute(text("CREATE INDEX IF NOT EXISTS ix_sales_distribution_actions_scope ON erp_sales_distribution_actions(organization_id,entity_id,status,priority)"))
        c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES('sales_distribution.view','View advanced sales and distribution performance') ON CONFLICT(permission_id) DO NOTHING"))
        c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES('sales_distribution.edit','Create sales and distribution snapshots and actions') ON CONFLICT(permission_id) DO NOTHING"))
        for r in ('manager','super_admin','accounts'):
            for p in ('sales_distribution.view','sales_distribution.edit'):
                c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'r':r,'p':p})
        c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('salesperson','sales_distribution.view') ON CONFLICT(role_id,permission_id) DO NOTHING"))

def customer_meta(c,o,e):
    rows=c.execute(text("SELECT master_id,data FROM master_record WHERE organization_id=:o AND master_type='CUSTOMER' AND active=1 AND (entity_id IS NULL OR entity_id=:e)"),{'o':o,'e':e}).mappings().all(); out={}
    for r in rows:
        try: d=json.loads(r['data'] or '{}') if isinstance(r['data'],str) else dict(r['data'] or {})
        except Exception: d={}
        out[str(r['master_id'])]={'name':d.get('name') or d.get('customer_name') or str(r['master_id']),'territory':d.get('territory_id') or d.get('territory') or 'UNASSIGNED','salesperson':d.get('salesperson_user_id') or d.get('salesperson_id') or 'UNASSIGNED','channel':d.get('channel') or d.get('customer_type') or 'UNCLASSIFIED'}
    return out

def compute(engine,o,e,l,fd,td):
    with engine.connect() as c:
        p={'o':o,'e':e,'fd':fd,'td':td}; loc=''
        if l: p['l']=l; loc=' AND location_id=:l'
        meta=customer_meta(c,o,e)
        invoices=c.execute(text(f"SELECT invoice_id, sales_order_id, grand_total, created_at FROM sales_invoices WHERE organization_id=:o AND entity_id=:e AND status='POSTED' AND date(created_at) BETWEEN :fd AND :td{loc}"),p).mappings().all()
        orders=c.execute(text(f"SELECT sales_order_id,customer_id,grand_total,created_at FROM sales_orders WHERE organization_id=:o AND entity_id=:e AND date(created_at) BETWEEN :fd AND :td{loc}"),p).mappings().all()
        disp=c.execute(text(f"SELECT COALESCE(SUM(dl.dispatched_qty),0) FROM dispatch_lines dl JOIN dispatches d ON d.dispatch_id=dl.dispatch_id WHERE d.organization_id=:o AND d.entity_id=:e AND date(COALESCE(d.posted_at,d.created_at)) BETWEEN :fd AND :td"),p).scalar() or 0
        ret=c.execute(text(f"SELECT COALESCE(SUM(rc.grand_total),0) FROM return_credit_notes rc WHERE rc.organization_id=:o AND rc.entity_id=:e AND date(rc.created_at) BETWEEN :fd AND :td{loc.replace('location_id=', 'rc.location_id=')}"),p).scalar() or 0
        coll=c.execute(text("SELECT COALESCE(SUM(pa.amount),0) FROM payment_allocations pa JOIN payment_transactions pt ON pt.payment_id=pa.payment_id WHERE pt.organization_id=:o AND pt.entity_id=:e AND pt.status IN ('VERIFIED','CLEARED','POSTED') AND date(pt.payment_date) BETWEEN :fd AND :td"),p).scalar() or 0
        # Distribution dimensions are derived from governed customer master assignments; no duplicate ownership table is created.
        buckets={k:{} for k in ('TERRITORY','SALESPERSON','CHANNEL','CUSTOMER')}
        for orec in orders:
            cid=str(orec['customer_id']); m=meta.get(cid,{'name':cid,'territory':'UNASSIGNED','salesperson':'UNASSIGNED','channel':'UNCLASSIFIED'})
            for typ,key,name in [('TERRITORY',m['territory'],m['territory']),('SALESPERSON',m['salesperson'],m['salesperson']),('CHANNEL',m['channel'],m['channel']),('CUSTOMER',cid,m['name'])]:
                x=buckets[typ].setdefault(str(key),{'dimension_key':str(key),'dimension_name':name,'sales_value':0.0,'order_count':0,'customer_ids':set()}); x['sales_value']+=float(orec['grand_total'] or 0); x['order_count']+=1; x['customer_ids'].add(cid)
        dims=[]
        for typ,items in buckets.items():
            for x in items.values():
                x['customer_count']=len(x.pop('customer_ids')); x['sales_value']=money(x['sales_value']); x['dispatched_qty']=0.0; x['collection_value']=0.0; x['return_value']=0.0; x['productivity_score']=money(x['sales_value']/max(1,x['order_count'])); x['dimension_type']=typ; dims.append(x)
        customer_ids={str(x['customer_id']) for x in orders}; repeat=sum(1 for cid in customer_ids if sum(1 for x in orders if str(x['customer_id'])==cid)>1)
        net=money(sum(float(x['grand_total'] or 0) for x in invoices)); avg=money(net/max(1,len(invoices)))
        return {'net_sales':net,'invoice_count':len(invoices),'order_count':len(orders),'customer_count':len(customer_ids),'dispatched_qty':money(disp),'return_value':money(ret),'collection_value':money(coll),'active_customer_count':len(meta),'repeat_customer_count':repeat,'on_time_dispatch_pct':0.0,'return_rate_pct':money(float(ret)*100/net) if net else 0.0,'collection_realization_pct':money(float(coll)*100/net) if net else 0.0,'avg_order_value':avg,'dimensions':dims}

class SalesDistributionQuery(BaseModel):
    organization_id: UUID; entity_id: UUID; location_id: UUID|None=None; from_date: str|None=None; to_date: str|None=None
class ActionIn(BaseModel):
    organization_id: UUID; entity_id: UUID; location_id: UUID|None=None; dimension_type: str=Field(min_length=1,max_length=30); dimension_key: str=Field(min_length=1,max_length=200); action_type: str=Field(min_length=1,max_length=50); priority: str='MEDIUM'; reason: str=Field(min_length=1,max_length=500); owner_user_id: UUID|None=None; due_date: str|None=None

def register_v90gn_routes(app:FastAPI,engine):
    ensure_v90gn_schema(engine)
    @app.get('/v90gn/sales-distribution')
    def performance(request:Request, organization_id:UUID, entity_id:UUID, location_id:UUID|None=None, from_date:str|None=None, to_date:str|None=None):
        require(engine,request,entity_id,location_id); fd=iso_date(from_date); td=iso_date(to_date or from_date)
        if fd>td: raise HTTPException(422,'from_date cannot be after to_date')
        return {'from_date':fd,'to_date':td,**compute(engine,str(organization_id),str(entity_id),str(location_id) if location_id else None,fd,td)}
    @app.post('/v90gn/sales-distribution/snapshots')
    def snapshot(q:SalesDistributionQuery,request:Request):
        u=require(engine,request,q.entity_id,q.location_id,True); fd=iso_date(q.from_date); td=iso_date(q.to_date or q.from_date)
        if fd>td: raise HTTPException(422,'from_date cannot be after to_date')
        d=compute(engine,str(q.organization_id),str(q.entity_id),str(q.location_id) if q.location_id else None,fd,td); sid=str(uuid4())
        with engine.begin() as c:
            c.execute(text("INSERT INTO erp_sales_distribution_snapshot(snapshot_id,organization_id,entity_id,location_id,from_date,to_date,net_sales,invoice_count,order_count,customer_count,dispatched_qty,return_value,collection_value,active_customer_count,repeat_customer_count,on_time_dispatch_pct,return_rate_pct,collection_realization_pct,avg_order_value,created_by) VALUES(:i,:o,:e,:l,:fd,:td,:n,:ic,:oc,:cc,:dq,:rv,:cv,:ac,:rc,:ot,:rr,:cr,:av,:u) ON CONFLICT(organization_id,entity_id,location_id,from_date,to_date) DO UPDATE SET net_sales=excluded.net_sales,invoice_count=excluded.invoice_count,order_count=excluded.order_count,customer_count=excluded.customer_count,dispatched_qty=excluded.dispatched_qty,return_value=excluded.return_value,collection_value=excluded.collection_value,repeat_customer_count=excluded.repeat_customer_count,return_rate_pct=excluded.return_rate_pct,collection_realization_pct=excluded.collection_realization_pct,avg_order_value=excluded.avg_order_value,created_by=excluded.created_by"),{'i':sid,'o':str(q.organization_id),'e':str(q.entity_id),'l':str(q.location_id) if q.location_id else None,'fd':fd,'td':td,'n':d['net_sales'],'ic':d['invoice_count'],'oc':d['order_count'],'cc':d['customer_count'],'dq':d['dispatched_qty'],'rv':d['return_value'],'cv':d['collection_value'],'ac':d['active_customer_count'],'rc':d['repeat_customer_count'],'ot':d['on_time_dispatch_pct'],'rr':d['return_rate_pct'],'cr':d['collection_realization_pct'],'av':d['avg_order_value'],'u':str(u.user_id)})
            for x in d['dimensions']:
                c.execute(text("INSERT INTO erp_sales_distribution_dimension_snapshot(row_id,snapshot_id,dimension_type,dimension_key,dimension_name,sales_value,order_count,customer_count,dispatched_qty,collection_value,return_value,productivity_score) VALUES(:i,:s,:t,:k,:n,:v,:o,:c,0,0,0,:p) ON CONFLICT(snapshot_id,dimension_type,dimension_key) DO UPDATE SET sales_value=excluded.sales_value,order_count=excluded.order_count,customer_count=excluded.customer_count,productivity_score=excluded.productivity_score"),{'i':str(uuid4()),'s':sid,'t':x['dimension_type'],'k':x['dimension_key'],'n':x['dimension_name'],'v':x['sales_value'],'o':x['order_count'],'c':x['customer_count'],'p':x['productivity_score']})
        return {'snapshot_id':sid,**d}
    @app.get('/v90gn/sales-distribution/snapshots')
    def snapshots(organization_id:UUID,entity_id:UUID,request:Request,location_id:UUID|None=None,limit:int=50):
        require(engine,request,entity_id,location_id); p={'o':str(organization_id),'e':str(entity_id),'lim':max(1,min(limit,200))}; loc=''
        if location_id: p['l']=str(location_id); loc=' AND location_id=:l'
        with engine.connect() as c: rows=c.execute(text(f"SELECT * FROM erp_sales_distribution_snapshot WHERE organization_id=:o AND entity_id=:e{loc} ORDER BY to_date DESC,created_at DESC LIMIT :lim"),p).mappings().all()
        return {'snapshots':[dict(r) for r in rows]}
    @app.get('/ui/sales-distribution')
    def ui():
        from pathlib import Path
        from fastapi.responses import FileResponse
        return FileResponse(Path(__file__).resolve().parents[1]/'web'/'sales-distribution.html')
    @app.post('/v90gn/actions')
    def action(body:ActionIn,request:Request):
        u=require(engine,request,body.entity_id,body.location_id,True); aid=str(uuid4())
        if body.priority.upper() not in ('LOW','MEDIUM','HIGH','CRITICAL'): raise HTTPException(422,'invalid priority')
        with engine.begin() as c: c.execute(text("INSERT INTO erp_sales_distribution_actions(action_id,organization_id,entity_id,location_id,dimension_type,dimension_key,action_type,priority,reason,owner_user_id,due_date,created_by) VALUES(:i,:o,:e,:l,:t,:k,:a,:p,:r,:u,:d,:by)"),{'i':aid,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id) if body.location_id else None,'t':body.dimension_type.upper(),'k':body.dimension_key,'a':body.action_type,'p':body.priority.upper(),'r':body.reason,'u':str(body.owner_user_id) if body.owner_user_id else None,'d':body.due_date,'by':str(u.user_id)})
        return {'action_id':aid,'status':'OPEN'}
    @app.get('/v90gn/actions')
    def actions(organization_id:UUID,entity_id:UUID,request:Request,location_id:UUID|None=None,status:str='OPEN'):
        require(engine,request,entity_id,location_id); p={'o':str(organization_id),'e':str(entity_id),'s':status}; loc=''
        if location_id: p['l']=str(location_id); loc=' AND location_id=:l'
        with engine.connect() as c: rows=c.execute(text(f"SELECT * FROM erp_sales_distribution_actions WHERE organization_id=:o AND entity_id=:e AND status=:s{loc} ORDER BY CASE priority WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'MEDIUM' THEN 3 ELSE 4 END,created_at DESC"),p).mappings().all()
        return {'actions':[dict(r) for r in rows]}

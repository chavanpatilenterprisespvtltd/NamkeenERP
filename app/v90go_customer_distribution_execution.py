from __future__ import annotations
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed

MONEY=Decimal('0.01')
def money(v): return float(Decimal(str(v or 0)).quantize(MONEY, rounding=ROUND_HALF_UP))
def as_date(v):
    if not v: return date.today()
    try: return datetime.fromisoformat(v.replace('Z','+00:00')).date()
    except ValueError as exc: raise HTTPException(422,'invalid date; use ISO-8601') from exc

def require(engine, request, entity_id, location_id=None, write=False):
    u=authenticate(request); perm='customer_execution.edit' if write else 'customer_execution.view'
    if perm not in permissions_for_user(engine,u.user_id): raise HTTPException(403,'permission denied')
    try: assert_entity_location_allowed(engine,u.user_id,str(entity_id),str(location_id) if location_id else None)
    except PermissionError as exc: raise HTTPException(403,str(exc)) from exc
    return u

def ensure_v90go_schema(engine):
    with engine.begin() as c:
        c.execute(text("""CREATE TABLE IF NOT EXISTS erp_customer_execution_snapshot (
            snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
            from_date TEXT NOT NULL, to_date TEXT NOT NULL, planned_stops INTEGER NOT NULL DEFAULT 0,
            completed_stops INTEGER NOT NULL DEFAULT 0, completion_pct NUMERIC NOT NULL DEFAULT 0,
            planned_beats INTEGER NOT NULL DEFAULT 0, customers_visited INTEGER NOT NULL DEFAULT 0,
            active_customers INTEGER NOT NULL DEFAULT 0, at_risk_customers INTEGER NOT NULL DEFAULT 0,
            churned_customers INTEGER NOT NULL DEFAULT 0, open_service_exceptions INTEGER NOT NULL DEFAULT 0,
            created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,location_id,from_date,to_date))"""))
        c.execute(text("""CREATE TABLE IF NOT EXISTS erp_customer_execution_actions (
            action_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
            customer_id TEXT NOT NULL, action_type TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'MEDIUM',
            reason TEXT NOT NULL, owner_user_id TEXT NULL, due_date TEXT NULL, status TEXT NOT NULL DEFAULT 'OPEN',
            created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, closed_at TIMESTAMP NULL)"""))
        c.execute(text("CREATE INDEX IF NOT EXISTS ix_customer_execution_snapshot ON erp_customer_execution_snapshot(entity_id,location_id,to_date)"))
        c.execute(text("CREATE INDEX IF NOT EXISTS ix_customer_execution_actions ON erp_customer_execution_actions(entity_id,location_id,status,priority)"))
        for pid,name in [('customer_execution.view','View customer and distribution execution'),('customer_execution.edit','Manage customer execution actions and snapshots')]:
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"),{'p':pid,'n':name})
        for role in ('manager','super_admin','accounts','mis'):
            for p in ('customer_execution.view','customer_execution.edit'):
                c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'r':role,'p':p})
        c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('salesperson','customer_execution.view') ON CONFLICT(role_id,permission_id) DO NOTHING"))

def customer_rows(c,o,e):
    return c.execute(text("SELECT master_id,data FROM master_record WHERE organization_id=:o AND master_type='CUSTOMER' AND active=1 AND (entity_id IS NULL OR entity_id=:e)"),{'o':o,'e':e}).mappings().all()

def profile(raw):
    import json
    try: return json.loads(raw or '{}') if isinstance(raw,str) else dict(raw or {})
    except Exception: return {}

def compute(engine,o,e,l,fd,td):
    prior=fd-timedelta(days=90)
    with engine.connect() as c:
        params={'o':o,'e':e,'fd':fd.isoformat(),'td':td.isoformat(),'prior':prior.isoformat()}
        loc=' AND location_id=:l' if l else ''
        if l: params['l']=l
        stops=c.execute(text("SELECT bs.stop_id,bs.customer_id,bs.status,bs.completed_at,bp.beat_date,bp.status beat_status FROM field_sales_beat_stops bs JOIN field_sales_beat_plans bp ON bp.beat_plan_id=bs.beat_plan_id WHERE bp.organization_id=:o AND bp.entity_id=:e AND bp.beat_date BETWEEN :fd AND :td"),params).mappings().all()
        if l:
            # Beat plans have no location column in the governed foundation, so scope cannot be narrowed further here.
            pass
        visits=c.execute(text("SELECT customer_id,visit_at FROM sales_customer_visits WHERE organization_id=:o AND entity_id=:e AND date(visit_at) BETWEEN :fd AND :td"),params).mappings().all()
        orders=c.execute(text("SELECT sales_order_id,customer_id,grand_total,created_at FROM sales_orders WHERE organization_id=:o AND entity_id=:e AND date(created_at) BETWEEN :prior AND :td"),params).mappings().all()
        current={}; prior_orders={}
        for r in orders:
            cid=str(r['customer_id']); d=datetime.fromisoformat(str(r['created_at']).replace('Z','+00:00')).date()
            if d>=fd: current.setdefault(cid,[]).append(r)
            else: prior_orders.setdefault(cid,[]).append(r)
        metas={str(r['master_id']):profile(r['data']) for r in customer_rows(c,o,e)}
        all_customers=set(metas)|set(current)|set(prior_orders)
        health=[]
        for cid in sorted(all_customers):
            cur=current.get(cid,[]); old=prior_orders.get(cid,[])
            last=max([str(x['created_at']) for x in cur+old],default=None)
            if not cur and old: status='AT_RISK'
            elif not cur and not old: status='CHURNED'
            else: status='ACTIVE'
            health.append({'customer_id':cid,'customer_name':metas.get(cid,{}).get('name') or metas.get(cid,{}).get('customer_name') or cid,'status':status,'current_order_count':len(cur),'current_sales':money(sum(float(x['grand_total'] or 0) for x in cur)),'previous_90d_order_count':len(old),'last_order_at':last})
        planned=len(stops); completed=sum(1 for x in stops if str(x['status']).upper() in ('COMPLETED','DONE','VISITED') or x['completed_at'])
        visited=len({str(x['customer_id']) for x in visits})
        at_risk=sum(x['status']=='AT_RISK' for x in health); churned=sum(x['status']=='CHURNED' for x in health)
        # Service exception = approved/submitted order with no dispatch linkage within the reporting window.
        exceptions=c.execute(text("""SELECT COUNT(*) FROM sales_orders so WHERE so.organization_id=:o AND so.entity_id=:e AND date(so.created_at) BETWEEN :fd AND :td AND so.status NOT IN ('DRAFT','CANCELLED','REJECTED') AND NOT EXISTS (SELECT 1 FROM sales_invoices si WHERE si.sales_order_id=so.sales_order_id AND si.status='POSTED')"""),params).scalar() or 0
        return {'planned_stops':planned,'completed_stops':completed,'completion_pct':money(completed*100/planned) if planned else 0.0,'planned_beats':len({str(x['beat_status'])+str(x['beat_date']) for x in stops}),'customers_visited':visited,'active_customers':sum(x['status']=='ACTIVE' for x in health),'at_risk_customers':at_risk,'churned_customers':churned,'open_service_exceptions':int(exceptions),'customer_health':health}

class Query(BaseModel):
    organization_id: UUID; entity_id: UUID; location_id: UUID|None=None; from_date: str|None=None; to_date: str|None=None
class ActionIn(BaseModel):
    organization_id: UUID; entity_id: UUID; location_id: UUID|None=None; customer_id: UUID; action_type: str=Field(min_length=1,max_length=50); priority: str='MEDIUM'; reason: str=Field(min_length=1,max_length=500); owner_user_id: UUID|None=None; due_date: str|None=None

def register_v90go_routes(app:FastAPI,engine):
    ensure_v90go_schema(engine)
    @app.get('/ui/customer-distribution-execution')
    def ui(): return FileResponse(__import__('pathlib').Path(__file__).resolve().parents[1]/'web'/'customer-distribution-execution.html')
    @app.get('/v90go/customer-execution')
    def dashboard(request:Request,organization_id:UUID,entity_id:UUID,location_id:UUID|None=None,from_date:str|None=None,to_date:str|None=None):
        require(engine,request,entity_id,location_id); fd=as_date(from_date); td=as_date(to_date or from_date)
        if fd>td: raise HTTPException(422,'from_date cannot be after to_date')
        return compute(engine,str(organization_id),str(entity_id),str(location_id) if location_id else None,fd,td)
    @app.post('/v90go/customer-execution/snapshots')
    def snapshot(body:Query,request:Request):
        u=require(engine,request,body.entity_id,body.location_id,True); fd=as_date(body.from_date); td=as_date(body.to_date or body.from_date)
        if fd>td: raise HTTPException(422,'from_date cannot be after to_date')
        d=compute(engine,str(body.organization_id),str(body.entity_id),str(body.location_id) if body.location_id else None,fd,td)
        sid=str(UUID(int=__import__('uuid').uuid4().int)); loc=str(body.location_id) if body.location_id else None
        with engine.begin() as c:
            c.execute(text("DELETE FROM erp_customer_execution_snapshot WHERE organization_id=:o AND entity_id=:e AND ((location_id=:l) OR (location_id IS NULL AND :l IS NULL)) AND from_date=:fd AND to_date=:td"),{'o':str(body.organization_id),'e':str(body.entity_id),'l':loc,'fd':fd.isoformat(),'td':td.isoformat()})
            c.execute(text("INSERT INTO erp_customer_execution_snapshot(snapshot_id,organization_id,entity_id,location_id,from_date,to_date,planned_stops,completed_stops,completion_pct,planned_beats,customers_visited,active_customers,at_risk_customers,churned_customers,open_service_exceptions,created_by) VALUES(:i,:o,:e,:l,:fd,:td,:ps,:cs,:cp,:pb,:cv,:ac,:ar,:ch,:se,:u)"),{'i':sid,'o':str(body.organization_id),'e':str(body.entity_id),'l':loc,'fd':fd.isoformat(),'td':td.isoformat(),'ps':d['planned_stops'],'cs':d['completed_stops'],'cp':d['completion_pct'],'pb':d['planned_beats'],'cv':d['customers_visited'],'ac':d['active_customers'],'ar':d['at_risk_customers'],'ch':d['churned_customers'],'se':d['open_service_exceptions'],'u':str(u.user_id)})
        return {'snapshot_id':sid,'metrics':{k:v for k,v in d.items() if k!='customer_health'}}
    @app.get('/v90go/customer-execution/health')
    def health(request:Request,organization_id:UUID,entity_id:UUID,location_id:UUID|None=None,from_date:str|None=None,to_date:str|None=None,status:str|None=None):
        require(engine,request,entity_id,location_id); fd=as_date(from_date); td=as_date(to_date or from_date); h=compute(engine,str(organization_id),str(entity_id),str(location_id) if location_id else None,fd,td)['customer_health']
        if status: h=[x for x in h if x['status']==status.upper()]
        return {'items':h,'total':len(h)}
    @app.post('/v90go/customer-execution/actions')
    def action(body:ActionIn,request:Request):
        u=require(engine,request,body.entity_id,body.location_id,True); aid=str(__import__('uuid').uuid4())
        with engine.begin() as c: c.execute(text("INSERT INTO erp_customer_execution_actions(action_id,organization_id,entity_id,location_id,customer_id,action_type,priority,reason,owner_user_id,due_date,created_by) VALUES(:i,:o,:e,:l,:c,:a,:p,:r,:w,:d,:u)"),{'i':aid,'o':str(body.organization_id),'e':str(body.entity_id),'l':str(body.location_id) if body.location_id else None,'c':str(body.customer_id),'a':body.action_type,'p':body.priority,'r':body.reason,'w':str(body.owner_user_id) if body.owner_user_id else None,'d':body.due_date,'u':str(u.user_id)})
        return {'action_id':aid,'status':'OPEN'}
    @app.get('/v90go/customer-execution/actions')
    def actions(request:Request,organization_id:UUID,entity_id:UUID,location_id:UUID|None=None,status:str='OPEN'):
        require(engine,request,entity_id,location_id)
        with engine.connect() as c: rows=c.execute(text("SELECT * FROM erp_customer_execution_actions WHERE organization_id=:o AND entity_id=:e AND ((location_id=:l) OR (location_id IS NULL AND :l IS NULL)) AND status=:s ORDER BY priority,created_at DESC"),{'o':str(organization_id),'e':str(entity_id),'l':str(location_id) if location_id else None,'s':status}).mappings().all()
        return {'actions':[dict(r) for r in rows]}

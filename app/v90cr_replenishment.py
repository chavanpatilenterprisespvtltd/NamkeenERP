from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def _perm(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def _d(v): return Decimal(str(v or 0)).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)

def _ensure(e):
    with e.begin() as c:
        for p,n in [('replenishment.view','View Replenishment'),('replenishment.manage','Manage Replenishment'),('replenishment.approve','Approve Replenishment')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS replenishment_policy(
            policy_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NOT NULL,
            material_master_id TEXT NOT NULL, supplier_id TEXT NULL, min_qty NUMERIC NOT NULL DEFAULT 0, max_qty NUMERIC NOT NULL DEFAULT 0,
            reorder_point NUMERIC NOT NULL DEFAULT 0, safety_stock NUMERIC NOT NULL DEFAULT 0, lead_time_days INTEGER NOT NULL DEFAULT 0,
            order_multiple NUMERIC NOT NULL DEFAULT 1, uom TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,location_id,material_master_id,supplier_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS replenishment_suggestions(
            suggestion_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NOT NULL,
            material_master_id TEXT NOT NULL, supplier_id TEXT NULL, source_mrp_run_id TEXT NULL, policy_id TEXT NULL,
            on_hand NUMERIC NOT NULL, open_po_qty NUMERIC NOT NULL DEFAULT 0, mrp_shortage_qty NUMERIC NOT NULL DEFAULT 0,
            reorder_point NUMERIC NOT NULL DEFAULT 0, safety_stock NUMERIC NOT NULL DEFAULT 0, suggested_qty NUMERIC NOT NULL,
            uom TEXT NOT NULL, required_date TEXT NULL, status TEXT NOT NULL DEFAULT 'SUGGESTED', notes TEXT NULL, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS replenishment_requisitions(
            requisition_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NOT NULL,
            source_run_id TEXT NULL, status TEXT NOT NULL DEFAULT 'DRAFT', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_replenishment_scope ON replenishment_policy(organization_id,entity_id,location_id,material_master_id,active)'))

def _stock(e,ent,loc,mat):
    with e.connect() as c:
        try: return _d(c.execute(text("SELECT COALESCE(SUM(available_qty),0) FROM inventory_lot WHERE replace(lower(entity_id),'-','')=replace(lower(:e),'-','') AND replace(lower(location_id),'-','')=replace(lower(:l),'-','') AND replace(lower(item_master_id),'-','')=replace(lower(:m),'-','') AND status='AVAILABLE' AND qc_status='RELEASED' AND available_qty>0"),{'e':ent,'l':loc,'m':mat}).scalar())
        except Exception: return Decimal('0')

def _open_po(e,ent,loc,mat):
    with e.connect() as c:
        try:
            return _d(c.execute(text("""SELECT COALESCE(SUM(l.qty),0) FROM procurement_po_line l JOIN procurement_po p ON p.po_id=l.po_id WHERE p.entity_id=:e AND p.location_id=:l AND l.item_master_id=:m AND p.status NOT IN ('CANCELLED','CLOSED','REJECTED')"""),{'e':ent,'l':loc,'m':mat}).scalar())
        except Exception: return Decimal('0')

def _ceil_multiple(q,m):
    q=_d(q); m=_d(m)
    if q<=0:return Decimal('0')
    if m<=0:return q
    n=(q/m).to_integral_value(rounding='ROUND_CEILING'); return _d(n*m)

def register_v90cr_routes(app:FastAPI,e):
    _ensure(e)
    @app.post('/v90cr/replenishment/policies')
    def policy(body:dict,request:Request):
        u=_perm(e,request,'replenishment.manage')
        req=('organization_id','entity_id','location_id','material_master_id','uom')
        if any(not str(body.get(k) or '').strip() for k in req): raise HTTPException(400,'required fields missing')
        pid=str(uuid4())
        with e.begin() as c:
            c.execute(text('''INSERT INTO replenishment_policy(policy_id,organization_id,entity_id,location_id,material_master_id,supplier_id,min_qty,max_qty,reorder_point,safety_stock,lead_time_days,order_multiple,uom) VALUES(:i,:o,:e,:l,:m,:s,:min,:max,:r,:ss,:lt,:om,:u) ON CONFLICT(organization_id,entity_id,location_id,material_master_id,supplier_id) DO UPDATE SET min_qty=:min,max_qty=:max,reorder_point=:r,safety_stock=:ss,lead_time_days=:lt,order_multiple=:om,uom=:u,active=1'''),{'i':pid,'o':body['organization_id'],'e':body['entity_id'],'l':body['location_id'],'m':body['material_master_id'],'s':body.get('supplier_id'),'min':float(body.get('min_qty',0)),'max':float(body.get('max_qty',0)),'r':float(body.get('reorder_point',0)),'ss':float(body.get('safety_stock',0)),'lt':int(body.get('lead_time_days',0)),'om':float(body.get('order_multiple',1)),'u':body['uom']})
        return {'policy_id':pid,'status':'ACTIVE'}

    @app.post('/v90cr/replenishment/suggest')
    def suggest(body:dict,request:Request):
        u=_perm(e,request,'replenishment.manage'); o,eid,l=body.get('organization_id'),body.get('entity_id'),body.get('location_id')
        if not all(str(x or '').strip() for x in (o,eid,l)): raise HTTPException(400,'organization_id, entity_id and location_id are required')
        with e.begin() as c:
            policies=c.execute(text('SELECT * FROM replenishment_policy WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND active=1'),{'o':o,'e':eid,'l':l}).mappings().all()
            created=[]
            for p in policies:
                on=_stock(e,eid,l,p['material_master_id']); po=_open_po(e,eid,l,p['material_master_id'])
                mrp=_d(c.execute(text("SELECT COALESCE(SUM(suggested_order_qty),0) FROM mrp_requirements WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND material_master_id=:m AND mrp_run_id IN (SELECT mrp_run_id FROM mrp_runs WHERE status IN ('CALCULATED','APPROVED'))"),{'o':o,'e':eid,'l':l,'m':p['material_master_id']}).scalar())
                net=on+po; threshold=max(_d(p['reorder_point']),_d(p['min_qty']))
                target=max(_d(p['max_qty']),_d(p['reorder_point'])+_d(p['safety_stock']))
                need=max(Decimal('0'),target-net, mrp)
                qty=_ceil_multiple(need,p['order_multiple'])
                if qty<=0: continue
                sid=str(uuid4()); req_date=body.get('required_date')
                c.execute(text('''INSERT INTO replenishment_suggestions(suggestion_id,organization_id,entity_id,location_id,material_master_id,supplier_id,policy_id,on_hand,open_po_qty,mrp_shortage_qty,reorder_point,safety_stock,suggested_qty,uom,required_date,notes,created_by) VALUES(:i,:o,:e,:l,:m,:s,:p,:h,:po,:mrp,:r,:ss,:q,:u,:d,:n,:by)'''),{'i':sid,'o':o,'e':eid,'l':l,'m':p['material_master_id'],'s':p['supplier_id'],'p':p['policy_id'],'h':float(on),'po':float(po),'mrp':float(mrp),'r':float(threshold),'ss':float(p['safety_stock']),'q':float(qty),'u':p['uom'],'d':req_date,'n':'MRP shortage / reorder / max-stock replenishment' if mrp>0 else 'Reorder/max-stock replenishment','by':str(u.user_id)})
                created.append(sid)
        return {'suggestions_created':len(created),'suggestion_ids':created}

    @app.get('/v90cr/replenishment/suggestions')
    def suggestions(organization_id:str,entity_id:str,location_id:str,request:Request):
        _perm(e,request,'replenishment.view')
        with e.connect() as c: rows=c.execute(text('SELECT * FROM replenishment_suggestions WHERE organization_id=:o AND entity_id=:e AND location_id=:l ORDER BY created_at DESC'),{'o':organization_id,'e':entity_id,'l':location_id}).mappings().all()
        return {'suggestions':[dict(x) for x in rows]}

    @app.post('/v90cr/replenishment/suggestions/{sid}/approve')
    def approve(sid:str,request:Request):
        _perm(e,request,'replenishment.approve')
        with e.begin() as c:
            r=c.execute(text("UPDATE replenishment_suggestions SET status='APPROVED' WHERE suggestion_id=:i AND status='SUGGESTED' RETURNING suggestion_id"),{'i':sid}).first()
            if not r: raise HTTPException(409,'suggestion not found or already processed')
        return {'suggestion_id':sid,'status':'APPROVED'}

    @app.get('/ui/replenishment')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'replenishment.html')

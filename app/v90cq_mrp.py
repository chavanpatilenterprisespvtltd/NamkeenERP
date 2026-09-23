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
        for p,n in [('mrp.view','View MRP'),('mrp.manage','Manage MRP'),('mrp.approve','Approve MRP')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS mrp_runs(
            mrp_run_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NOT NULL,
            plan_id TEXT, run_no TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT', planning_date TEXT, notes TEXT,
            created_by TEXT NOT NULL, approved_by TEXT, approved_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,run_no))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS mrp_requirements(
            mrp_requirement_id TEXT PRIMARY KEY, mrp_run_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            location_id TEXT NOT NULL, product_master_id TEXT NOT NULL, material_master_id TEXT NOT NULL, requirement_type TEXT NOT NULL,
            gross_requirement NUMERIC NOT NULL, scheduled_receipt NUMERIC NOT NULL DEFAULT 0, on_hand NUMERIC NOT NULL DEFAULT 0,
            safety_stock NUMERIC NOT NULL DEFAULT 0, projected_available NUMERIC NOT NULL DEFAULT 0, shortage_qty NUMERIC NOT NULL DEFAULT 0,
            suggested_order_qty NUMERIC NOT NULL DEFAULT 0, uom TEXT NOT NULL, source_plan_line_id TEXT, notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(mrp_run_id) REFERENCES mrp_runs(mrp_run_id))'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_mrp_req_scope ON mrp_requirements(organization_id,entity_id,location_id,material_master_id,mrp_run_id)'))
        c.execute(text('''CREATE TABLE IF NOT EXISTS mrp_plan_exceptions(
            exception_id TEXT PRIMARY KEY, mrp_run_id TEXT NOT NULL, material_master_id TEXT NOT NULL, exception_type TEXT NOT NULL,
            severity TEXT NOT NULL, shortage_qty NUMERIC NOT NULL DEFAULT 0, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN',
            resolved_by TEXT, resolved_at TIMESTAMP, resolution_note TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))

def _stock(e, ent, loc, mat):
    with e.connect() as c:
        try:
            r=c.execute(text('''SELECT COALESCE(SUM(available_qty),0) qty FROM inventory_lot WHERE replace(lower(entity_id),'-','')=replace(lower(:e),'-','') AND replace(lower(location_id),'-','')=replace(lower(:l),'-','') AND replace(lower(item_master_id),'-','')=replace(lower(:m),'-','') AND status='AVAILABLE' AND qc_status='RELEASED' AND available_qty>0'''),{'e':ent,'l':loc,'m':mat}).scalar()
            return _d(r)
        except Exception: return Decimal('0')

def register_v90cq_routes(app,e):
    _ensure(e)
    @app.post('/v90cq/mrp/runs')
    def create_run(body:dict,request:Request):
        u=_perm(e,request,'mrp.manage')
        for k in ('organization_id','entity_id','location_id','run_no'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        rid=str(uuid4())
        with e.begin() as c:
            c.execute(text('INSERT INTO mrp_runs(mrp_run_id,organization_id,entity_id,location_id,plan_id,run_no,planning_date,notes,created_by) VALUES(:i,:o,:e,:l,:p,:n,:d,:t,:u)'),{'i':rid,'o':body['organization_id'],'e':body['entity_id'],'l':body['location_id'],'p':body.get('plan_id'),'n':body['run_no'],'d':body.get('planning_date'),'t':body.get('notes'),'u':str(u.user_id)})
        return {'mrp_run_id':rid,'status':'DRAFT'}

    @app.post('/v90cq/mrp/runs/{rid}/calculate')
    def calculate(rid:str,request:Request):
        u=_perm(e,request,'mrp.manage')
        with e.begin() as c:
            run=c.execute(text('SELECT * FROM mrp_runs WHERE mrp_run_id=:i'),{'i':rid}).mappings().first()
            if not run: raise HTTPException(404,'MRP run not found')
            if run['status']=='APPROVED': raise HTTPException(409,'approved MRP run cannot be recalculated')
            c.execute(text('DELETE FROM mrp_requirements WHERE mrp_run_id=:i'),{'i':rid}); c.execute(text('DELETE FROM mrp_plan_exceptions WHERE mrp_run_id=:i'),{'i':rid})
            lines=[]
            if run['plan_id']:
                lines=c.execute(text('''SELECT l.plan_line_id,l.product_master_id,l.planned_qty,l.uom FROM production_plan_line l WHERE l.plan_id=:p'''),{'p':run['plan_id']}).mappings().all()
            total=0; exceptions=0
            for line in lines:
                # Versioned BOM: use latest approved recipe for the product, then scale by planned quantity / recipe yield.
                recipes=c.execute(text('''SELECT recipe_id,yield_qty,yield_uom FROM recipe WHERE organization_id=:o AND entity_id=:e AND product_master_id=:p AND status='APPROVED' ORDER BY version_no DESC LIMIT 1'''),{'o':run['organization_id'],'e':run['entity_id'],'p':line['product_master_id']}).mappings().first()
                if not recipes: continue
                mats=c.execute(text('SELECT material_master_id,material_type,qty,uom,scrap_pct FROM recipe_line WHERE recipe_id=:r'),{'r':recipes['recipe_id']}).mappings().all()
                factor=_d(line['planned_qty'])/_d(recipes['yield_qty']) if _d(recipes['yield_qty']) else Decimal('0')
                for m in mats:
                    gross=_d(m['qty'])*factor; scrap=gross*_d(m['scrap_pct'])/Decimal('100'); req=gross+scrap; on=_stock(e,run['entity_id'],run['location_id'],m['material_master_id']); safety=Decimal('0')
                    projected=on-req; shortage=max(Decimal('0'),safety-projected); suggested=shortage
                    st='SHORTAGE' if shortage>0 else 'OK'
                    c.execute(text('''INSERT INTO mrp_requirements(mrp_requirement_id,mrp_run_id,organization_id,entity_id,location_id,product_master_id,material_master_id,requirement_type,gross_requirement,on_hand,safety_stock,projected_available,shortage_qty,suggested_order_qty,uom,source_plan_line_id,notes) VALUES(:i,:r,:o,:e,:l,:p,:m,:t,:g,:h,:s,:v,:q,:a,:u,:pl,:n)'''),{'i':str(uuid4()),'r':rid,'o':run['organization_id'],'e':run['entity_id'],'l':run['location_id'],'p':line['product_master_id'],'m':m['material_master_id'],'t':m['material_type'],'g':float(req),'h':float(on),'s':float(safety),'v':float(projected),'q':float(shortage),'a':float(suggested),'u':m['uom'],'pl':line['plan_line_id'],'n':st})
                    total+=1
                    if shortage>0:
                        exceptions+=1; c.execute(text('INSERT INTO mrp_plan_exceptions(exception_id,mrp_run_id,material_master_id,exception_type,severity,shortage_qty,message) VALUES(:i,:r,:m,\'MATERIAL_SHORTAGE\',\'HIGH\',:q,:msg)'),{'i':str(uuid4()),'r':rid,'m':m['material_master_id'],'q':float(shortage),'msg':f'Material shortage projected: {shortage} {m["uom"]}'})
            c.execute(text("UPDATE mrp_runs SET status='CALCULATED' WHERE mrp_run_id=:i"),{'i':rid})
        return {'mrp_run_id':rid,'status':'CALCULATED','requirements':total,'exceptions':exceptions}

    @app.get('/v90cq/mrp/runs/{rid}')
    def get_run(rid:str,request:Request):
        _perm(e,request,'mrp.view')
        with e.connect() as c:
            r=c.execute(text('SELECT * FROM mrp_runs WHERE mrp_run_id=:i'),{'i':rid}).mappings().first()
            if not r: raise HTTPException(404,'MRP run not found')
            req=c.execute(text('SELECT * FROM mrp_requirements WHERE mrp_run_id=:i ORDER BY material_master_id'),{'i':rid}).mappings().all(); ex=c.execute(text("SELECT * FROM mrp_plan_exceptions WHERE mrp_run_id=:i AND status='OPEN' ORDER BY severity DESC"),{'i':rid}).mappings().all()
        return {'run':dict(r),'requirements':[dict(x) for x in req],'exceptions':[dict(x) for x in ex]}

    @app.post('/v90cq/mrp/runs/{rid}/approve')
    def approve(rid:str,body:dict,request:Request):
        u=_perm(e,request,'mrp.approve')
        with e.begin() as c:
            r=c.execute(text('SELECT status FROM mrp_runs WHERE mrp_run_id=:i'),{'i':rid}).mappings().first()
            if not r: raise HTTPException(404,'MRP run not found')
            if r['status']!='CALCULATED': raise HTTPException(409,'MRP run must be CALCULATED before approval')
            open_ex=c.execute(text("SELECT COUNT(*) FROM mrp_plan_exceptions WHERE mrp_run_id=:i AND status='OPEN' AND severity='CRITICAL'"),{'i':rid}).scalar() or 0
            if open_ex: raise HTTPException(409,'critical MRP exceptions must be resolved before approval')
            c.execute(text("UPDATE mrp_runs SET status='APPROVED',approved_by=:u,approved_at=CURRENT_TIMESTAMP WHERE mrp_run_id=:i"),{'u':str(u.user_id),'i':rid})
        return {'mrp_run_id':rid,'status':'APPROVED'}

    @app.post('/v90cq/mrp/exceptions/{eid}/resolve')
    def resolve(eid:str,body:dict,request:Request):
        u=_perm(e,request,'mrp.manage'); note=str(body.get('resolution_note') or '').strip()
        if not note: raise HTTPException(400,'resolution_note is required')
        with e.begin() as c:
            if not c.execute(text('SELECT 1 FROM mrp_plan_exceptions WHERE exception_id=:i'),{'i':eid}).scalar(): raise HTTPException(404,'MRP exception not found')
            c.execute(text("UPDATE mrp_plan_exceptions SET status='RESOLVED',resolved_by=:u,resolved_at=CURRENT_TIMESTAMP,resolution_note=:n WHERE exception_id=:i"),{'u':str(u.user_id),'n':note,'i':eid})
        return {'exception_id':eid,'status':'RESOLVED'}

    @app.get('/ui/mrp')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'mrp.html')

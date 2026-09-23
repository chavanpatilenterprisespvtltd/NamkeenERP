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
        for p,n in [('mfg_cost.view','View Manufacturing Costing'),('mfg_cost.manage','Manage Manufacturing Costing'),('mfg_cost.approve','Approve Cost Adjustments')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':p.replace('_',' ').title()})
        c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_batch_cost(
            cost_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, batch_id TEXT NOT NULL,
            product_id TEXT NOT NULL, period_key TEXT NOT NULL, planned_qty NUMERIC NOT NULL DEFAULT 0, good_qty NUMERIC NOT NULL DEFAULT 0,
            rework_qty NUMERIC NOT NULL DEFAULT 0, wastage_qty NUMERIC NOT NULL DEFAULT 0, byproduct_qty NUMERIC NOT NULL DEFAULT 0,
            material_cost NUMERIC NOT NULL DEFAULT 0, packaging_cost NUMERIC NOT NULL DEFAULT 0, labor_cost NUMERIC NOT NULL DEFAULT 0,
            overhead_cost NUMERIC NOT NULL DEFAULT 0, rework_cost NUMERIC NOT NULL DEFAULT 0, total_cost NUMERIC NOT NULL DEFAULT 0,
            cost_per_kg NUMERIC NOT NULL DEFAULT 0, cost_per_pack NUMERIC NOT NULL DEFAULT 0, yield_pct NUMERIC NOT NULL DEFAULT 0,
            standard_cost NUMERIC NOT NULL DEFAULT 0, variance_value NUMERIC NOT NULL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,batch_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_cost_adjustment(
            adjustment_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, batch_id TEXT NOT NULL,
            adjustment_type TEXT NOT NULL, amount NUMERIC NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
            created_by TEXT NOT NULL, approved_by TEXT, approved_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_mfg_cost_scope ON manufacturing_batch_cost(organization_id,entity_id,period_key,product_id)'))

def register_v90cw_routes(app:FastAPI,e):
    _ensure(e)
    @app.post('/v90cw/manufacturing/batch-cost')
    def record(body:dict,request:Request):
        _perm(e,request,'mfg_cost.manage')
        required=('organization_id','entity_id','batch_id','product_id','period_key','planned_qty','good_qty')
        for k in required:
            if body.get(k) is None or (isinstance(body.get(k),str) and not body.get(k).strip()): raise HTTPException(400,f'{k} is required')
        planned,good,rework,waste,byprod=map(_d,[body.get('planned_qty'),body.get('good_qty'),body.get('rework_qty'),body.get('wastage_qty'),body.get('byproduct_qty')])
        mat,pack,labor,oh,rc=map(_d,[body.get('material_cost'),body.get('packaging_cost'),body.get('labor_cost'),body.get('overhead_cost'),body.get('rework_cost')])
        total=mat+pack+labor+oh+rc; yield_pct=(good/planned*100 if planned else Decimal(0)); cpk=(total/good if good else Decimal(0)); std=_d(body.get('standard_cost')); variance=total-std
        cid=str(uuid4())
        with e.begin() as c:
            c.execute(text('''INSERT INTO manufacturing_batch_cost(cost_id,organization_id,entity_id,batch_id,product_id,period_key,planned_qty,good_qty,rework_qty,wastage_qty,byproduct_qty,material_cost,packaging_cost,labor_cost,overhead_cost,rework_cost,total_cost,cost_per_kg,cost_per_pack,yield_pct,standard_cost,variance_value) VALUES(:i,:o,:e,:b,:p,:pk,:pl,:g,:rw,:wa,:bp,:m,:pa,:l,:oh,:rc,:t,:ck,:cp,:y,:s,:v) ON CONFLICT(organization_id,entity_id,batch_id) DO UPDATE SET planned_qty=:pl,good_qty=:g,rework_qty=:rw,wastage_qty=:wa,byproduct_qty=:bp,material_cost=:m,packaging_cost=:pa,labor_cost=:l,overhead_cost=:oh,rework_cost=:rc,total_cost=:t,cost_per_kg=:ck,cost_per_pack=:cp,yield_pct=:y,standard_cost=:s,variance_value=:v'''),dict(i=cid,o=body['organization_id'],e=body['entity_id'],b=body['batch_id'],p=body['product_id'],pk=body['period_key'],pl=float(planned),g=float(good),rw=float(rework),wa=float(waste),bp=float(byprod),m=float(mat),pa=float(pack),l=float(labor),oh=float(oh),rc=float(rc),t=float(total),ck=float(cpk),cp=float(cpk),y=float(yield_pct),s=float(std),v=float(variance)))
        return {'cost_id':cid,'total_cost':float(total),'yield_pct':float(yield_pct),'cost_per_kg':float(cpk),'variance_value':float(variance),'status':'RECORDED'}

    @app.get('/v90cw/manufacturing/batch-cost')
    def listing(request:Request,organization_id:str,entity_id:str,period_key:str):
        _perm(e,request,'mfg_cost.view')
        with e.connect() as c: rows=c.execute(text('SELECT * FROM manufacturing_batch_cost WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY created_at DESC'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        return {'batch_costs':[dict(x) for x in rows]}

    @app.post('/v90cw/manufacturing/adjustment')
    def adjustment(body:dict,request:Request):
        u=_perm(e,request,'mfg_cost.manage')
        for k in ('organization_id','entity_id','batch_id','adjustment_type','amount','reason'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        aid=str(uuid4())
        with e.begin() as c: c.execute(text('INSERT INTO manufacturing_cost_adjustment(adjustment_id,organization_id,entity_id,batch_id,adjustment_type,amount,reason,created_by) VALUES(:i,:o,:e,:b,:t,:a,:r,:u)'),{'i':aid,'o':body['organization_id'],'e':body['entity_id'],'b':body['batch_id'],'t':body['adjustment_type'],'a':float(_d(body['amount'])),'r':body['reason'],'u':str(u.user_id)})
        return {'adjustment_id':aid,'status':'PENDING'}

    @app.post('/v90cw/manufacturing/adjustment/{adjustment_id}/approve')
    def approve(adjustment_id:str,request:Request):
        u=_perm(e,request,'mfg_cost.approve')
        with e.begin() as c:
            r=c.execute(text("UPDATE manufacturing_cost_adjustment SET status='APPROVED',approved_by=:u,approved_at=CURRENT_TIMESTAMP WHERE adjustment_id=:i AND status='PENDING' RETURNING adjustment_id"),{'i':adjustment_id,'u':str(u.user_id)}).first()
            if not r: raise HTTPException(404,'pending adjustment not found')
        return {'adjustment_id':adjustment_id,'status':'APPROVED'}

    @app.get('/ui/manufacturing-costing')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'manufacturing-costing.html')

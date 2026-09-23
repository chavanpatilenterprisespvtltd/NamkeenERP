from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.engine import Engine
from .auth import authenticate
from .identity import permissions_for_user
from .v90fn_security_rbac_scope_hardening import assert_security_scope
PERM_VIEW='costing.profitability.view'; PERM_MANAGE='costing.profitability.manage'
def _d(v): return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
def _u(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u
def _scope(e,u,o,ei):
    try: assert_security_scope(e,u.user_id,organization_id=o,entity_id=ei)
    except PermissionError as ex: raise HTTPException(403,str(ex)) from ex
def ensure_v90gk_schema(e:Engine):
    with e.begin() as c:
        for s in [
        '''CREATE TABLE IF NOT EXISTS erp_costing_profitability_snapshot(snapshot_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,product_id TEXT NOT NULL,period_key TEXT NOT NULL,units_sold NUMERIC NOT NULL DEFAULT 0,net_sales NUMERIC NOT NULL DEFAULT 0,production_cost NUMERIC NOT NULL DEFAULT 0,material_cost NUMERIC NOT NULL DEFAULT 0,packaging_cost NUMERIC NOT NULL DEFAULT 0,labour_cost NUMERIC NOT NULL DEFAULT 0,overhead_cost NUMERIC NOT NULL DEFAULT 0,return_cost NUMERIC NOT NULL DEFAULT 0,total_cost NUMERIC NOT NULL DEFAULT 0,gross_margin NUMERIC NOT NULL DEFAULT 0,gross_margin_pct NUMERIC NOT NULL DEFAULT 0,cost_per_unit NUMERIC NOT NULL DEFAULT 0,standard_cost NUMERIC NOT NULL DEFAULT 0,cost_variance NUMERIC NOT NULL DEFAULT 0,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,product_id,period_key))''',
        'CREATE INDEX IF NOT EXISTS ix_cost_profit_scope ON erp_costing_profitability_snapshot(organization_id,entity_id,period_key,product_id)']:
            c.execute(text(s))
        for p,n in [(PERM_VIEW,'View costing and product profitability'),(PERM_MANAGE,'Create costing and profitability snapshots')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':p})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES('super_admin',:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'p':p})
        for role in ('manager','accounts','costing','mis','production'): c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'r':role,'p':PERM_VIEW})
        for role in ('manager','accounts','costing','mis'): c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'r':role,'p':PERM_MANAGE})
def register_v90gk_routes(app:FastAPI,e:Engine):
    ensure_v90gk_schema(e)
    @app.post('/v90gk/costing/profitability/snapshot')
    def snapshot(body:dict,request:Request):
        u=_u(e,request,PERM_MANAGE); o=str(body.get('organization_id') or '').strip(); ei=str(body.get('entity_id') or '').strip(); prod=str(body.get('product_id') or '').strip(); pk=str(body.get('period_key') or '').strip()
        if not all((o,ei,prod,pk)): raise HTTPException(400,'organization_id, entity_id, product_id and period_key are required')
        _scope(e,u,o,ei)
        units=_d(body.get('units_sold')); sales=_d(body.get('net_sales')); mat=_d(body.get('material_cost')); pack=_d(body.get('packaging_cost')); lab=_d(body.get('labour_cost')); oh=_d(body.get('overhead_cost')); ret=_d(body.get('return_cost')); std=_d(body.get('standard_cost'))
        total=mat+pack+lab+oh+ret; margin=sales-total; mp=(margin/sales*100) if sales else Decimal(0); cpu=(total/units) if units else Decimal(0); variance=total-(std*units if std and units else _d(body.get('production_cost')))
        sid=str(uuid4())
        with e.begin() as c:
            c.execute(text('''INSERT INTO erp_costing_profitability_snapshot(snapshot_id,organization_id,entity_id,product_id,period_key,units_sold,net_sales,production_cost,material_cost,packaging_cost,labour_cost,overhead_cost,return_cost,total_cost,gross_margin,gross_margin_pct,cost_per_unit,standard_cost,cost_variance,created_by) VALUES(:i,:o,:e,:p,:k,:u,:s,:pc,:m,:pa,:l,:oh,:r,:t,:gm,:gp,:cpu,:std,:cv,:by) ON CONFLICT(organization_id,entity_id,product_id,period_key) DO UPDATE SET units_sold=:u,net_sales=:s,production_cost=:pc,material_cost=:m,packaging_cost=:pa,labour_cost=:l,overhead_cost=:oh,return_cost=:r,total_cost=:t,gross_margin=:gm,gross_margin_pct=:gp,cost_per_unit=:cpu,standard_cost=:std,cost_variance=:cv,created_by=:by,created_at=CURRENT_TIMESTAMP'''),{'i':sid,'o':o,'e':ei,'p':prod,'k':pk,'u':float(units),'s':float(sales),'pc':float(total),'m':float(mat),'pa':float(pack),'l':float(lab),'oh':float(oh),'r':float(ret),'t':float(total),'gm':float(margin),'gp':float(mp),'cpu':float(cpu),'std':float(std),'cv':float(variance),'by':str(u.user_id)})
        return {'snapshot_id':sid,'gross_margin':float(margin),'gross_margin_pct':float(mp),'cost_per_unit':float(cpu),'cost_variance':float(variance)}
    @app.get('/v90gk/costing/profitability')
    def listing(organization_id:str,entity_id:str,period_key:str,request:Request):
        u=_u(e,request,PERM_VIEW); _scope(e,u,organization_id,entity_id)
        with e.connect() as c: rows=c.execute(text('SELECT * FROM erp_costing_profitability_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY gross_margin ASC,product_id'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        total=sum((_d(r['gross_margin']) for r in rows),Decimal(0)); sales=sum((_d(r['net_sales']) for r in rows),Decimal(0)); costs=sum((_d(r['total_cost']) for r in rows),Decimal(0));
        return {'count':len(rows),'total_net_sales':float(sales),'total_cost':float(costs),'total_gross_margin':float(total),'gross_margin_pct':float((total/sales*100) if sales else 0),'products':[dict(r) for r in rows]}
    @app.get('/ui/costing-profitability')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'costing-profitability.html')
    return {'allowed':True}

from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pathlib import Path
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def _n(v):
    return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def _perm(engine, request, p):
    u=authenticate(request); ps=permissions_for_user(engine,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def register_v90dx_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for p,n in [('workforce_cost.view','View Workforce Cost Reconciliation'),('workforce_cost.reconcile','Run Workforce Cost Reconciliation'),('workforce_cost.close','Close Workforce Cost Reconciliation')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})

    @app.post('/v90dx/workforce/cost-reconciliation')
    def reconcile(body:dict, request:Request):
        u=_perm(engine,request,'workforce_cost.reconcile')
        for k in ('organization_id','entity_id','period_id','run_id'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        o,e,p,r=body['organization_id'],body['entity_id'],body['period_id'],body['run_id']
        with engine.connect() as c:
            payroll=c.execute(text('''SELECT COALESCE(SUM(employer_cost),0) v FROM hr_payroll_mis_snapshot WHERE organization_id=:o AND entity_id=:e AND period_id=:p AND run_id=:r'''),{'o':o,'e':e,'p':p,'r':r}).scalar()
            allocated=c.execute(text('''SELECT COALESCE(SUM(allocated_amount),0) v FROM hr_payroll_cost_allocation WHERE organization_id=:o AND entity_id=:e AND run_id=:r'''),{'o':o,'e':e,'r':r}).scalar()
            production=c.execute(text('''SELECT COALESCE(SUM(labour_cost),0) v, COALESCE(SUM(labour_hours),0) h, COALESCE(SUM(output_qty),0) q FROM hr_production_labour_capture WHERE organization_id=:o AND entity_id=:e AND run_id=:r'''),{'o':o,'e':e,'r':r}).mappings().first()
            budget=c.execute(text('''SELECT COALESCE(SUM(budget_cost),0) v FROM hr_labour_budget WHERE organization_id=:o AND entity_id=:e AND period_id=:p'''),{'o':o,'e':e,'p':p}).scalar()
        payroll=_n(payroll); allocated=_n(allocated); production_cost=_n(production['v']); hours=_n(production['h']); output=_n(production['q']); budget=_n(budget)
        pa=_n(payroll-allocated); ap=_n(allocated-production_cost); bp=_n(production_cost-budget)
        pa_pct=_n(pa/payroll*100) if payroll else Decimal('0'); bp_pct=_n(bp/budget*100) if budget else Decimal('0')
        cpu=_n(production_cost/output) if output else Decimal('0')
        status='RECONCILED' if abs(pa)<=_n(body.get('tolerance') or 0.01) and abs(ap)<=_n(body.get('tolerance') or 0.01) else 'VARIANCE'
        rid=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_workforce_cost_reconciliation(reconciliation_id,organization_id,entity_id,period_id,run_id,payroll_employer_cost,allocated_labour_cost,production_labour_cost,labour_budget_cost,payroll_to_allocation_variance,allocation_to_production_variance,budget_to_production_variance,payroll_allocation_variance_pct,production_budget_variance_pct,labour_hours,output_qty,labour_cost_per_unit,status,created_by)
            VALUES(:id,:o,:e,:p,:r,:pay,:alloc,:prod,:bud,:pa,:ap,:bp,:pap,:bpp,:h,:q,:cpu,:s,:u)
            ON CONFLICT(organization_id,entity_id,period_id,run_id) DO UPDATE SET payroll_employer_cost=:pay,allocated_labour_cost=:alloc,production_labour_cost=:prod,labour_budget_cost=:bud,payroll_to_allocation_variance=:pa,allocation_to_production_variance=:ap,budget_to_production_variance=:bp,payroll_allocation_variance_pct=:pap,production_budget_variance_pct=:bpp,labour_hours=:h,output_qty=:q,labour_cost_per_unit=:cpu,status=:s'''),dict(id=rid,o=o,e=e,p=p,r=r,pay=float(payroll),alloc=float(allocated),prod=float(production_cost),bud=float(budget),pa=float(pa),ap=float(ap),bp=float(bp),pap=float(pa_pct),bpp=float(bp_pct),h=float(hours),q=float(output),cpu=float(cpu),s=status,u=str(u.user_id)))
        return {'reconciliation_id':rid,'payroll_employer_cost':float(payroll),'allocated_labour_cost':float(allocated),'production_labour_cost':float(production_cost),'labour_budget_cost':float(budget),'payroll_to_allocation_variance':float(pa),'allocation_to_production_variance':float(ap),'budget_to_production_variance':float(bp),'payroll_allocation_variance_pct':float(pa_pct),'production_budget_variance_pct':float(bp_pct),'labour_cost_per_unit':float(cpu),'status':status}

    @app.get('/v90dx/workforce/cost-reconciliation')
    def get_reconciliation(request:Request, organization_id:str, entity_id:str, period_id:str, run_id:str|None=None):
        _perm(engine,request,'workforce_cost.view'); where='organization_id=:o AND entity_id=:e AND period_id=:p'; params={'o':organization_id,'e':entity_id,'p':period_id}
        if run_id: where+=' AND run_id=:r'; params['r']=run_id
        with engine.connect() as c: rows=c.execute(text(f'SELECT * FROM hr_workforce_cost_reconciliation WHERE {where} ORDER BY created_at DESC'),params).mappings().all()
        return [dict(x) for x in rows]

    @app.post('/v90dx/workforce/cost-reconciliation/{period_id}/close')
    def close(period_id:str, body:dict, request:Request):
        u=_perm(engine,request,'workforce_cost.close')
        for k in ('organization_id','entity_id','reconciliation_id'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        cid=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_workforce_cost_reconciliation_close(close_id,organization_id,entity_id,period_id,reconciliation_id,closed_by) VALUES(:i,:o,:e,:p,:r,:u)
            ON CONFLICT(organization_id,entity_id,period_id) DO UPDATE SET reconciliation_id=:r,status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),{'i':cid,'o':body['organization_id'],'e':body['entity_id'],'p':period_id,'r':body['reconciliation_id'],'u':str(u.user_id)})
            c.execute(text("UPDATE hr_workforce_cost_reconciliation SET status='CLOSED' WHERE reconciliation_id=:r"),{'r':body['reconciliation_id']})
        return {'period_id':period_id,'reconciliation_id':body['reconciliation_id'],'status':'CLOSED'}

    @app.get('/v90dx/workforce/cost-reconciliation/dashboard')
    def dashboard(request:Request, organization_id:str, entity_id:str, period_id:str|None=None):
        _perm(engine,request,'workforce_cost.view'); where='organization_id=:o AND entity_id=:e'; params={'o':organization_id,'e':entity_id}
        if period_id: where+=' AND period_id=:p'; params['p']=period_id
        with engine.connect() as c: x=c.execute(text(f'''SELECT COUNT(*) runs,COALESCE(SUM(payroll_employer_cost),0) payroll,COALESCE(SUM(allocated_labour_cost),0) allocated,COALESCE(SUM(production_labour_cost),0) production,COALESCE(SUM(labour_budget_cost),0) budget,COALESCE(SUM(labour_hours),0) hours,COALESCE(SUM(output_qty),0) output,COALESCE(AVG(payroll_allocation_variance_pct),0) payroll_var_pct,COALESCE(AVG(production_budget_variance_pct),0) budget_var_pct FROM hr_workforce_cost_reconciliation WHERE {where}'''),params).mappings().first()
        return {k:float(_n(x[k])) if k not in ('runs',) else int(x[k] or 0) for k in x}

    @app.get('/ui/workforce-cost-reconciliation')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'workforce-cost-reconciliation.html')

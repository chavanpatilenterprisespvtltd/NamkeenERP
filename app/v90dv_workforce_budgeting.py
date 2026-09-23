from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user


def _n(v):
    return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _perm(engine, request, p):
    u = authenticate(request)
    ps = permissions_for_user(engine, u.user_id)
    if p not in ps and 'admin.users' not in ps:
        raise HTTPException(403, 'permission denied')
    return u


def _nonneg(body, keys):
    out = {}
    for k in keys:
        out[k] = _n(body.get(k))
        if out[k] < 0:
            raise HTTPException(400, f'{k} must be non-negative')
    return out


def register_v90dv_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for p, n in [
            ('labour_budget.view', 'View Labour Budget Benchmarking'),
            ('labour_budget.manage', 'Manage Labour Budgets'),
            ('labour_budget.post', 'Post Labour Budget Actuals'),
            ('labour_budget.snapshot', 'Create Labour Benchmark Snapshots')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'), {'p': p, 'n': n})

    @app.post('/v90dv/workforce/budgets')
    def budget(body: dict, request: Request):
        u = _perm(engine, request, 'labour_budget.manage')
        for k in ('organization_id', 'entity_id', 'period_id'):
            if not str(body.get(k) or '').strip():
                raise HTTPException(400, f'{k} is required')
        v = _nonneg(body, ['budget_hours','budget_cost','target_cost_per_unit','planned_output_qty'])
        bid = str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_labour_budget(
                budget_id,organization_id,entity_id,period_id,department_id,product_id,
                budget_hours,budget_cost,target_cost_per_unit,planned_output_qty,status,created_by)
                VALUES(:id,:o,:e,:p,:d,:prod,:h,:c,:t,:q,'OPEN',:u)
                ON CONFLICT(organization_id,entity_id,period_id,department_id,product_id) DO UPDATE SET
                budget_hours=:h,budget_cost=:c,target_cost_per_unit=:t,planned_output_qty=:q,status='OPEN' '''),
                {'id':bid,'o':body['organization_id'],'e':body['entity_id'],'p':body['period_id'],
                 'd':body.get('department_id'),'prod':body.get('product_id'),'h':float(v['budget_hours']),
                 'c':float(v['budget_cost']),'t':float(v['target_cost_per_unit']),'q':float(v['planned_output_qty']),'u':str(u.user_id)})
        return {'budget_id': bid, 'status':'OPEN'}

    @app.post('/v90dv/workforce/actuals')
    def actual(body: dict, request: Request):
        u = _perm(engine, request, 'labour_budget.post')
        for k in ('organization_id', 'entity_id', 'period_id'):
            if not str(body.get(k) or '').strip():
                raise HTTPException(400, f'{k} is required')
        v = _nonneg(body, ['actual_hours','actual_cost','actual_output_qty','overtime_hours'])
        if v['overtime_hours'] > v['actual_hours']:
            raise HTTPException(400, 'overtime_hours cannot exceed actual_hours')
        aid = str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_labour_budget_actual(
                actual_id,organization_id,entity_id,period_id,department_id,product_id,
                actual_hours,actual_cost,actual_output_qty,overtime_hours,created_by)
                VALUES(:id,:o,:e,:p,:d,:prod,:h,:c,:q,:ot,:u)
                ON CONFLICT(organization_id,entity_id,period_id,department_id,product_id) DO UPDATE SET
                actual_hours=:h,actual_cost=:c,actual_output_qty=:q,overtime_hours=:ot'''),
                {'id':aid,'o':body['organization_id'],'e':body['entity_id'],'p':body['period_id'],
                 'd':body.get('department_id'),'prod':body.get('product_id'),'h':float(v['actual_hours']),
                 'c':float(v['actual_cost']),'q':float(v['actual_output_qty']),'ot':float(v['overtime_hours']),'u':str(u.user_id)})
        return {'actual_id':aid,'status':'RECORDED'}

    @app.post('/v90dv/workforce/snapshots')
    def snapshot(body: dict, request: Request):
        u = _perm(engine, request, 'labour_budget.snapshot')
        for k in ('organization_id','entity_id','period_id'):
            if not str(body.get(k) or '').strip():
                raise HTTPException(400, f'{k} is required')
        params={'o':body['organization_id'],'e':body['entity_id'],'p':body['period_id'], 'd':body.get('department_id'), 'prod':body.get('product_id')}
        with engine.connect() as c:
            b=c.execute(text('''SELECT * FROM hr_labour_budget WHERE organization_id=:o AND entity_id=:e AND period_id=:p
                AND ((department_id=:d) OR (department_id IS NULL AND :d IS NULL)) AND ((product_id=:prod) OR (product_id IS NULL AND :prod IS NULL))'''),params).mappings().first()
            a=c.execute(text('''SELECT * FROM hr_labour_budget_actual WHERE organization_id=:o AND entity_id=:e AND period_id=:p
                AND ((department_id=:d) OR (department_id IS NULL AND :d IS NULL)) AND ((product_id=:prod) OR (product_id IS NULL AND :prod IS NULL))'''),params).mappings().first()
        if not b or not a:
            raise HTTPException(409,'budget and actual are both required for snapshot')
        bh,ah=_n(b['budget_hours']),_n(a['actual_hours']); bc,ac=_n(b['budget_cost']),_n(a['actual_cost'])
        bq,aq=_n(b['planned_output_qty']),_n(a['actual_output_qty']); ot=_n(a['overtime_hours'])
        hv=_n(ah-bh); cv=_n(ac-bc); ov=_n(aq-bq)
        cvpct=_n(cv/bc*100) if bc else Decimal('0')
        budget_cpu=_n(bc/bq) if bq else Decimal('0'); actual_cpu=_n(ac/aq) if aq else Decimal('0')
        efficiency=_n(budget_cpu/actual_cpu*100) if actual_cpu else Decimal('0')
        sid=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_labour_benchmark_snapshot(
                snapshot_id,organization_id,entity_id,period_id,department_id,product_id,budget_hours,actual_hours,
                hours_variance,budget_cost,actual_cost,cost_variance,budget_output_qty,actual_output_qty,output_variance,
                overtime_hours,cost_variance_pct,efficiency_index_pct,status,created_by)
                VALUES(:id,:o,:e,:p,:d,:prod,:bh,:ah,:hv,:bc,:ac,:cv,:bq,:aq,:ov,:ot,:cvp,:eff,'READY',:u)
                ON CONFLICT(organization_id,entity_id,period_id,department_id,product_id) DO UPDATE SET
                budget_hours=:bh,actual_hours=:ah,hours_variance=:hv,budget_cost=:bc,actual_cost=:ac,cost_variance=:cv,
                budget_output_qty=:bq,actual_output_qty=:aq,output_variance=:ov,overtime_hours=:ot,cost_variance_pct=:cvp,
                efficiency_index_pct=:eff,status='READY' '''),
                {'id':sid,'o':body['organization_id'],'e':body['entity_id'],'p':body['period_id'],'d':body.get('department_id'),
                 'prod':body.get('product_id'),'bh':float(bh),'ah':float(ah),'hv':float(hv),'bc':float(bc),'ac':float(ac),
                 'cv':float(cv),'bq':float(bq),'aq':float(aq),'ov':float(ov),'ot':float(ot),'cvp':float(cvp),'eff':float(efficiency),'u':str(u.user_id)})
        return {'snapshot_id':sid,'hours_variance':float(hv),'cost_variance':float(cv),'output_variance':float(ov),'cost_variance_pct':float(cvp),'efficiency_index_pct':float(efficiency),'status':'READY'}

    @app.get('/v90dv/workforce/dashboard')
    def dashboard(request: Request, organization_id: str, entity_id: str, period_id: str | None = None):
        _perm(engine, request, 'labour_budget.view')
        where='organization_id=:o AND entity_id=:e'; params={'o':organization_id,'e':entity_id}
        if period_id: where += ' AND period_id=:p'; params['p']=period_id
        with engine.connect() as c:
            r=c.execute(text(f'''SELECT COUNT(*) runs,COALESCE(SUM(budget_cost),0) bc,COALESCE(SUM(actual_cost),0) ac,
                COALESCE(SUM(cost_variance),0) cv,COALESCE(SUM(overtime_hours),0) ot,
                COALESCE(AVG(efficiency_index_pct),0) eff FROM hr_labour_benchmark_snapshot WHERE {where}'''),params).mappings().first()
        return {'snapshots':int(r['runs'] or 0),'budget_labour_cost':float(_n(r['bc'])),'actual_labour_cost':float(_n(r['ac'])),
                'labour_cost_variance':float(_n(r['cv'])),'overtime_hours':float(_n(r['ot'])),'avg_efficiency_index_pct':float(_n(r['eff']))}

    @app.get('/ui/workforce-budgeting')
    def page():
        return FileResponse(Path(__file__).resolve().parents[1] / 'web' / 'workforce-budgeting.html')

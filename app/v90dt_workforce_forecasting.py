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


def register_v90dt_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for p, n in [
            ('workforce_forecast.view', 'View Workforce Forecast'),
            ('workforce_forecast.manage', 'Manage Workforce Forecast'),
            ('workforce_forecast.post', 'Post Workforce Forecast'),
        ]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'), {'p': p, 'n': n})

    @app.post('/v90dt/workforce/optimization-rules')
    def rule(body: dict, request: Request):
        u = _perm(engine, request, 'workforce_forecast.manage')
        for k in ('organization_id', 'entity_id', 'rule_code', 'rule_name'):
            if not str(body.get(k) or '').strip():
                raise HTTPException(400, f'{k} is required')
        min_util = _n(body.get('min_utilization_pct'))
        max_ot = _n(body.get('max_overtime_hours'))
        max_gap = _n(body.get('max_capacity_gap_hours'))
        if min_util < 0 or min_util > 100 or max_ot < 0 or max_gap < 0:
            raise HTTPException(400, 'invalid optimization-rule values')
        rid = str(uuid4())
        with engine.begin() as c:
            c.execute(text('''
                INSERT INTO hr_workforce_optimization_rule(
                    rule_id,organization_id,entity_id,rule_code,rule_name,min_utilization_pct,
                    max_overtime_hours,max_capacity_gap_hours,active,created_by
                ) VALUES(:id,:o,:e,:code,:name,:util,:ot,:gap,TRUE,:u)
                ON CONFLICT(organization_id,entity_id,rule_code) DO UPDATE SET
                    rule_name=:name,min_utilization_pct=:util,max_overtime_hours=:ot,
                    max_capacity_gap_hours=:gap,active=TRUE
            '''), {
                'id': rid, 'o': body['organization_id'], 'e': body['entity_id'],
                'code': body['rule_code'], 'name': body['rule_name'], 'util': float(min_util),
                'ot': float(max_ot), 'gap': float(max_gap), 'u': str(u.user_id)
            })
        return {'rule_id': rid, 'status': 'ACTIVE'}

    @app.post('/v90dt/workforce/forecasts')
    def forecast(body: dict, request: Request):
        u = _perm(engine, request, 'workforce_forecast.post')
        for k in ('organization_id', 'entity_id', 'forecast_date'):
            if not str(body.get(k) or '').strip():
                raise HTTPException(400, f'{k} is required')
        required_h = _n(body.get('required_hours'))
        available_h = _n(body.get('available_hours'))
        forecast_h = _n(body.get('forecast_hours')) if body.get('forecast_hours') is not None else available_h
        required_hc = max(0, int(body.get('required_headcount') or 0))
        available_hc = max(0, int(body.get('available_headcount') or 0))
        cost = _n(body.get('forecast_cost'))
        confidence = _n(body.get('confidence_pct'))
        if min(required_h, available_h, forecast_h, cost) < 0 or confidence < 0 or confidence > 100:
            raise HTTPException(400, 'invalid workforce forecast values')
        gap = max(Decimal('0.00'), required_h - forecast_h)
        hc_gap = max(0, required_hc - available_hc)
        fid = str(uuid4())
        with engine.begin() as c:
            c.execute(text('''
                INSERT INTO hr_workforce_forecast(
                    forecast_id,organization_id,entity_id,forecast_date,department_id,shift_code,
                    required_hours,available_hours,forecast_hours,required_headcount,available_headcount,
                    headcount_gap,capacity_gap_hours,forecast_cost,confidence_pct,status,created_by
                ) VALUES(:id,:o,:e,:d,:dep,:shift,:rh,:ah,:fh,:rhc,:ahc,:hgap,:gap,:cost,:conf,'FORECAST',:u)
                ON CONFLICT(organization_id,entity_id,forecast_date,department_id,shift_code) DO UPDATE SET
                    required_hours=:rh,available_hours=:ah,forecast_hours=:fh,required_headcount=:rhc,
                    available_headcount=:ahc,headcount_gap=:hgap,capacity_gap_hours=:gap,
                    forecast_cost=:cost,confidence_pct=:conf,status='FORECAST'
            '''), {
                'id': fid, 'o': body['organization_id'], 'e': body['entity_id'], 'd': body['forecast_date'],
                'dep': body.get('department_id'), 'shift': body.get('shift_code'), 'rh': float(required_h),
                'ah': float(available_h), 'fh': float(forecast_h), 'rhc': required_hc, 'ahc': available_hc,
                'hgap': hc_gap, 'gap': float(gap), 'cost': float(cost), 'conf': float(confidence), 'u': str(u.user_id)
            })
        return {'forecast_id': fid, 'headcount_gap': hc_gap, 'capacity_gap_hours': float(gap), 'status': 'FORECAST'}

    @app.post('/v90dt/workforce/optimization-results')
    def optimization(body: dict, request: Request):
        u = _perm(engine, request, 'workforce_forecast.post')
        for k in ('organization_id', 'entity_id', 'plan_date'):
            if not str(body.get(k) or '').strip():
                raise HTTPException(400, f'{k} is required')
        current_h = _n(body.get('current_hours'))
        optimized_h = _n(body.get('optimized_hours'))
        current_cost = _n(body.get('current_cost'))
        optimized_cost = _n(body.get('optimized_cost'))
        utilization = _n(body.get('utilization_pct'))
        if min(current_h, optimized_h, current_cost, optimized_cost) < 0 or utilization < 0 or utilization > 100:
            raise HTTPException(400, 'invalid optimization-result values')
        sh = _n(current_h - optimized_h)
        sc = _n(current_cost - optimized_cost)
        result_id = str(uuid4())
        with engine.begin() as c:
            c.execute(text('''
                INSERT INTO hr_workforce_optimization_result(
                    result_id,organization_id,entity_id,plan_date,department_id,current_hours,
                    optimized_hours,current_cost,optimized_cost,saving_hours,saving_cost,
                    utilization_pct,rule_id,status,created_by
                ) VALUES(:id,:o,:e,:d,:dep,:ch,:oh,:cc,:oc,:sh,:sc,:util,:rule,'READY',:u)
                ON CONFLICT(organization_id,entity_id,plan_date,department_id) DO UPDATE SET
                    current_hours=:ch,optimized_hours=:oh,current_cost=:cc,optimized_cost=:oc,
                    saving_hours=:sh,saving_cost=:sc,utilization_pct=:util,rule_id=:rule,status='READY'
            '''), {
                'id': result_id, 'o': body['organization_id'], 'e': body['entity_id'], 'd': body['plan_date'],
                'dep': body.get('department_id'), 'ch': float(current_h), 'oh': float(optimized_h),
                'cc': float(current_cost), 'oc': float(optimized_cost), 'sh': float(sh), 'sc': float(sc),
                'util': float(utilization), 'rule': body.get('rule_id'), 'u': str(u.user_id)
            })
        return {'result_id': result_id, 'saving_hours': float(sh), 'saving_cost': float(sc), 'status': 'READY'}

    @app.get('/v90dt/workforce/dashboard')
    def dashboard(request: Request, organization_id: str, entity_id: str):
        _perm(engine, request, 'workforce_forecast.view')
        with engine.connect() as c:
            f = c.execute(text('''
                SELECT COALESCE(SUM(required_hours),0) rh, COALESCE(SUM(forecast_hours),0) fh,
                       COALESCE(SUM(capacity_gap_hours),0) gap, COALESCE(SUM(headcount_gap),0) hgap,
                       COALESCE(AVG(confidence_pct),0) conf FROM hr_workforce_forecast
                WHERE organization_id=:o AND entity_id=:e
            '''), {'o': organization_id, 'e': entity_id}).mappings().first()
            r = c.execute(text('''
                SELECT COALESCE(SUM(saving_hours),0) sh, COALESCE(SUM(saving_cost),0) sc,
                       COALESCE(AVG(utilization_pct),0) util FROM hr_workforce_optimization_result
                WHERE organization_id=:o AND entity_id=:e
            '''), {'o': organization_id, 'e': entity_id}).mappings().first()
        return {
            'required_hours': float(_n(f['rh'])),
            'forecast_hours': float(_n(f['fh'])),
            'capacity_gap_hours': float(_n(f['gap'])),
            'headcount_gap': int(f['hgap'] or 0),
            'avg_confidence_pct': float(_n(f['conf'])),
            'optimization_saving_hours': float(_n(r['sh'])),
            'optimization_saving_cost': float(_n(r['sc'])),
            'avg_utilization_pct': float(_n(r['util'])),
        }

    @app.get('/ui/workforce-forecasting')
    def page():
        return FileResponse(Path(__file__).resolve().parents[1] / 'web' / 'workforce-forecasting.html')

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
    vals = {}
    for k in keys:
        vals[k] = _n(body.get(k))
        if vals[k] < 0:
            raise HTTPException(400, f'{k} must be non-negative')
    return vals


def register_v90du_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for p, n in [
            ('labour_benchmark.view', 'View Labour Benchmarking'),
            ('labour_benchmark.manage', 'Manage Labour Efficiency Targets'),
            ('labour_benchmark.post', 'Post Labour Benchmarks'),
            ('labour_benchmark.close', 'Close Labour Benchmarking')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'), {'p': p, 'n': n})

    @app.post('/v90du/workforce/efficiency-targets')
    def target(body: dict, request: Request):
        u = _perm(engine, request, 'labour_benchmark.manage')
        for k in ('organization_id', 'entity_id', 'target_name', 'target_value'):
            if not str(body.get(k) or '').strip():
                raise HTTPException(400, f'{k} is required')
        value = _n(body['target_value'])
        if value <= 0:
            raise HTTPException(400, 'target_value must be positive')
        target_id = str(uuid4())
        with engine.begin() as c:
            c.execute(text('''
                INSERT INTO hr_labour_efficiency_target(
                    target_id,organization_id,entity_id,department_id,product_id,target_name,
                    target_basis,target_value,uom,active,created_by
                ) VALUES(:id,:o,:e,:d,:p,:n,:b,:v,:u,:a,:by)
                ON CONFLICT(organization_id,entity_id,department_id,product_id,target_name) DO UPDATE SET
                    target_basis=:b,target_value=:v,uom=:u,active=:a
            '''), {
                'id': target_id, 'o': body['organization_id'], 'e': body['entity_id'],
                'd': body.get('department_id'), 'p': body.get('product_id'), 'n': body['target_name'],
                'b': str(body.get('target_basis') or 'OUTPUT_PER_HOUR').upper(), 'v': float(value),
                'u': body.get('uom'), 'a': bool(body.get('active', True)), 'by': str(u.user_id)
            })
        return {'target_id': target_id, 'status': 'SAVED', 'target_value': float(value)}

    @app.post('/v90du/workforce/benchmarks')
    def benchmark(body: dict, request: Request):
        u = _perm(engine, request, 'labour_benchmark.post')
        for k in ('organization_id', 'entity_id', 'period_id'):
            if not str(body.get(k) or '').strip():
                raise HTTPException(400, f'{k} is required')
        v = _nonneg(body, ['labour_hours', 'labour_cost', 'output_qty', 'productive_hours', 'target_output_per_hour', 'target_cost_per_unit'])
        hours = v['labour_hours']; productive = v['productive_hours'] or max(hours, Decimal('0'))
        output = v['output_qty']; cost = v['labour_cost']
        if productive > hours and hours > 0:
            raise HTTPException(400, 'productive_hours cannot exceed labour_hours')
        oph = _n(output / productive) if productive else Decimal('0')
        cpu = _n(cost / output) if output else Decimal('0')
        utilization = _n(productive / hours * 100) if hours else Decimal('0')
        target_oph = v['target_output_per_hour']
        target_cpu = v['target_cost_per_unit']
        efficiency = _n((oph / target_oph) * 100) if target_oph else Decimal('0')
        out_var = _n(oph - target_oph)
        cost_var = _n(cpu - target_cpu)
        bid = str(uuid4())
        with engine.begin() as c:
            c.execute(text('''
                INSERT INTO hr_labour_performance_benchmark(
                    benchmark_id,organization_id,entity_id,period_id,department_id,production_batch_id,
                    labour_hours,labour_cost,output_qty,productive_hours,output_per_hour,labour_cost_per_unit,
                    utilization_pct,efficiency_pct,target_output_per_hour,target_cost_per_unit,
                    variance_output_per_hour,variance_cost_per_unit,status,created_by
                ) VALUES(:id,:o,:e,:period,:dep,:batch,:h,:cost,:q,:ph,:oph,:cpu,:util,:eff,:toph,:tcpu,:ov,:cv,'READY',:by)
                ON CONFLICT(organization_id,entity_id,period_id,department_id,production_batch_id) DO UPDATE SET
                    labour_hours=:h,labour_cost=:cost,output_qty=:q,productive_hours=:ph,
                    output_per_hour=:oph,labour_cost_per_unit=:cpu,utilization_pct=:util,efficiency_pct=:eff,
                    target_output_per_hour=:toph,target_cost_per_unit=:tcpu,variance_output_per_hour=:ov,
                    variance_cost_per_unit=:cv,status='READY'
            '''), {
                'id': bid, 'o': body['organization_id'], 'e': body['entity_id'], 'period': body['period_id'],
                'dep': body.get('department_id'), 'batch': body.get('production_batch_id'),
                'h': float(hours), 'cost': float(cost), 'q': float(output), 'ph': float(productive),
                'oph': float(oph), 'cpu': float(cpu), 'util': float(utilization), 'eff': float(efficiency),
                'toph': float(target_oph), 'tcpu': float(target_cpu), 'ov': float(out_var), 'cv': float(cost_var),
                'by': str(u.user_id)
            })
        return {
            'benchmark_id': bid, 'output_per_hour': float(oph), 'labour_cost_per_unit': float(cpu),
            'utilization_pct': float(utilization), 'efficiency_pct': float(efficiency),
            'variance_output_per_hour': float(out_var), 'variance_cost_per_unit': float(cost_var), 'status': 'READY'
        }

    @app.post('/v90du/workforce/labour-cost-forecasts')
    def forecast(body: dict, request: Request):
        u = _perm(engine, request, 'labour_benchmark.post')
        for k in ('organization_id', 'entity_id', 'period_id', 'planned_output_qty', 'planned_labour_hours', 'forecast_cost'):
            if body.get(k) in (None, ''):
                raise HTTPException(400, f'{k} is required')
        v = _nonneg(body, ['planned_output_qty', 'planned_labour_hours', 'forecast_cost', 'target_cost_per_unit', 'confidence_pct'])
        confidence = v['confidence_pct']
        if confidence > 100:
            raise HTTPException(400, 'confidence_pct must be between 0 and 100')
        qty = v['planned_output_qty']; cost = v['forecast_cost']; target = v['target_cost_per_unit']
        cpu = _n(cost / qty) if qty else Decimal('0')
        variance = _n((cpu - target) * qty) if target and qty else Decimal('0')
        fid = str(uuid4())
        with engine.begin() as c:
            c.execute(text('''
                INSERT INTO hr_production_labour_cost_forecast(
                    forecast_id,organization_id,entity_id,period_id,department_id,product_id,
                    planned_output_qty,planned_labour_hours,forecast_cost,cost_per_unit,target_cost_per_unit,
                    forecast_variance_cost,confidence_pct,status,created_by
                ) VALUES(:id,:o,:e,:period,:dep,:prod,:q,:h,:cost,:cpu,:target,:var,:conf,'FORECAST',:by)
                ON CONFLICT(organization_id,entity_id,period_id,department_id,product_id) DO UPDATE SET
                    planned_output_qty=:q,planned_labour_hours=:h,forecast_cost=:cost,cost_per_unit=:cpu,
                    target_cost_per_unit=:target,forecast_variance_cost=:var,confidence_pct=:conf,status='FORECAST'
            '''), {
                'id': fid, 'o': body['organization_id'], 'e': body['entity_id'], 'period': body['period_id'],
                'dep': body.get('department_id'), 'prod': body.get('product_id'), 'q': float(qty), 'h': float(v['planned_labour_hours']),
                'cost': float(cost), 'cpu': float(cpu), 'target': float(target), 'var': float(variance),
                'conf': float(confidence), 'by': str(u.user_id)
            })
        return {'forecast_id': fid, 'cost_per_unit': float(cpu), 'forecast_variance_cost': float(variance), 'status': 'FORECAST'}

    @app.get('/v90du/workforce/dashboard')
    def dashboard(request: Request, organization_id: str, entity_id: str, period_id: str | None = None):
        _perm(engine, request, 'labour_benchmark.view')
        with engine.connect() as c:
            params = {'o': organization_id, 'e': entity_id}
            where = 'organization_id=:o AND entity_id=:e'
            if period_id:
                where += ' AND period_id=:p'; params['p'] = period_id
            b = c.execute(text(f'''SELECT COUNT(*) runs,COALESCE(AVG(efficiency_pct),0) eff,
                COALESCE(AVG(utilization_pct),0) util,COALESCE(AVG(output_per_hour),0) oph,
                COALESCE(AVG(labour_cost_per_unit),0) cpu,COALESCE(SUM(labour_cost),0) cost
                FROM hr_labour_performance_benchmark WHERE {where}'''), params).mappings().first()
            f = c.execute(text(f'''SELECT COUNT(*) forecasts,COALESCE(SUM(forecast_cost),0) forecast_cost,
                COALESCE(SUM(forecast_variance_cost),0) variance_cost,COALESCE(AVG(confidence_pct),0) confidence
                FROM hr_production_labour_cost_forecast WHERE {where}'''), params).mappings().first()
        return {
            'benchmarks': int(b['runs'] or 0), 'avg_efficiency_pct': float(_n(b['eff'])),
            'avg_utilization_pct': float(_n(b['util'])), 'avg_output_per_hour': float(_n(b['oph'])),
            'avg_labour_cost_per_unit': float(_n(b['cpu'])), 'labour_cost': float(_n(b['cost'])),
            'forecasts': int(f['forecasts'] or 0), 'forecast_labour_cost': float(_n(f['forecast_cost'])),
            'forecast_variance_cost': float(_n(f['variance_cost'])), 'avg_forecast_confidence_pct': float(_n(f['confidence']))
        }

    @app.post('/v90du/workforce/periods/{period_id}/close')
    def close(period_id: str, body: dict, request: Request):
        u = _perm(engine, request, 'labour_benchmark.close')
        for k in ('organization_id', 'entity_id'):
            if not str(body.get(k) or '').strip():
                raise HTTPException(400, f'{k} is required')
        with engine.begin() as c:
            exists = c.execute(text('''SELECT COUNT(*) FROM hr_labour_performance_benchmark
                WHERE organization_id=:o AND entity_id=:e AND period_id=:p'''),
                {'o': body['organization_id'], 'e': body['entity_id'], 'p': period_id}).scalar()
            if int(exists or 0) == 0:
                raise HTTPException(409, 'no labour benchmarks available for period')
            # Reuse existing workforce close-control convention through a dedicated immutable audit row.
            c.execute(text('''CREATE TABLE IF NOT EXISTS hr_labour_benchmark_close(
                close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
                period_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'CLOSED',
                closed_by TEXT NOT NULL, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(organization_id,entity_id,period_id))'''))
            cid = str(uuid4())
            c.execute(text('''INSERT INTO hr_labour_benchmark_close(close_id,organization_id,entity_id,period_id,status,closed_by)
                VALUES(:id,:o,:e,:p,'CLOSED',:u)
                ON CONFLICT(organization_id,entity_id,period_id) DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),
                {'id': cid, 'o': body['organization_id'], 'e': body['entity_id'], 'p': period_id, 'u': str(u.user_id)})
        return {'period_id': period_id, 'status': 'CLOSED'}

    @app.get('/ui/workforce-benchmarking')
    def page():
        return FileResponse(Path(__file__).resolve().parents[1] / 'web' / 'workforce-benchmarking.html')

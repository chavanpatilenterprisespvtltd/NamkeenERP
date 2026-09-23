from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user


def _n(v, places='0.01'):
    return Decimal(str(v or 0)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _perm(engine, request, permission):
    u = authenticate(request)
    ps = permissions_for_user(engine, u.user_id)
    if permission not in ps and 'admin.users' not in ps:
        raise HTTPException(403, 'permission denied')
    return u


def _req(body, keys):
    for k in keys:
        if not str(body.get(k) or '').strip():
            raise HTTPException(400, f'{k} is required')


def register_v90dz_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for p, n in [
            ('workforce_standard.view', 'View Labour Standards'),
            ('workforce_standard.manage', 'Manage Labour Standards'),
            ('workforce_standard.post', 'Post Labour Standard Performance'),
            ('workforce_overtime.view', 'View Overtime Efficiency'),
            ('workforce_overtime.calculate', 'Calculate Overtime Efficiency'),
            ('workforce_dz.close', 'Close Workforce Productivity Period'),
        ]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'), {'p': p, 'n': n})

    @app.post('/v90dz/workforce/labour-standards')
    def labour_standard(body: dict, request: Request):
        u = _perm(engine, request, 'workforce_standard.manage')
        _req(body, ('organization_id', 'entity_id'))
        basis = _n(body.get('standard_basis_qty') or 1)
        hours = _n(body.get('standard_hours'))
        cost = _n(body.get('standard_cost'))
        if basis <= 0 or hours <= 0:
            raise HTTPException(400, 'standard_basis_qty and standard_hours must be positive')
        sid = str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_labour_standard(
                standard_id,organization_id,entity_id,department_id,product_id,standard_basis_qty,standard_uom,
                standard_hours,standard_cost,effective_from,effective_to,active,created_by)
                VALUES(:id,:o,:e,:d,:prod,:b,:u,:h,:c,:f,:t,:a,:by)
                ON CONFLICT(organization_id,entity_id,department_id,product_id,effective_from) DO UPDATE SET
                  standard_basis_qty=:b,standard_uom=:u,standard_hours=:h,standard_cost=:c,effective_to=:t,active=:a'''),
                {'id': sid, 'o': body['organization_id'], 'e': body['entity_id'], 'd': body.get('department_id'),
                 'prod': body.get('product_id'), 'b': float(basis), 'u': body.get('standard_uom') or 'UNIT',
                 'h': float(hours), 'c': float(cost), 'f': body.get('effective_from'), 't': body.get('effective_to'),
                 'a': bool(body.get('active', True)), 'by': str(u.user_id)})
        return {'standard_id': sid, 'standard_basis_qty': float(basis), 'standard_hours': float(hours), 'standard_cost': float(cost), 'status': 'SAVED'}

    @app.get('/v90dz/workforce/labour-standards')
    def labour_standards(request: Request, organization_id: str, entity_id: str,
                         department_id: str | None = None, product_id: str | None = None):
        _perm(engine, request, 'workforce_standard.view')
        where = 'organization_id=:o AND entity_id=:e'; params = {'o': organization_id, 'e': entity_id}
        if department_id:
            where += ' AND department_id=:d'; params['d'] = department_id
        if product_id:
            where += ' AND product_id=:p'; params['p'] = product_id
        with engine.connect() as c:
            rows = c.execute(text(f'SELECT * FROM hr_labour_standard WHERE {where} ORDER BY effective_from DESC NULLS LAST, created_at DESC'), params).mappings().all()
        return [dict(x) for x in rows]

    @app.post('/v90dz/workforce/labour-standards/performance')
    def standard_performance(body: dict, request: Request):
        u = _perm(engine, request, 'workforce_standard.post')
        _req(body, ('organization_id', 'entity_id', 'period_id', 'run_id'))
        actual_hours = _n(body.get('actual_hours'))
        output = _n(body.get('output_qty'))
        overtime = _n(body.get('overtime_hours'))
        actual_cost = _n(body.get('actual_cost'))
        if actual_hours < 0 or output < 0 or overtime < 0 or actual_cost < 0:
            raise HTTPException(400, 'performance values cannot be negative')
        if overtime > actual_hours:
            raise HTTPException(400, 'overtime_hours cannot exceed actual_hours')
        standard_id = body.get('standard_id')
        sh = _n(body.get('standard_hours'))
        sc = _n(body.get('standard_cost'))
        if standard_id:
            with engine.connect() as c:
                std = c.execute(text('SELECT standard_basis_qty,standard_hours,standard_cost FROM hr_labour_standard WHERE standard_id=:id'), {'id': standard_id}).mappings().first()
            if not std:
                raise HTTPException(404, 'labour standard not found')
            if output > 0:
                sh = _n(output / _n(std['standard_basis_qty']) * _n(std['standard_hours']))
                sc = _n(output / _n(std['standard_basis_qty']) * _n(std['standard_cost']))
            else:
                sh = Decimal('0'); sc = Decimal('0')
        elif sh <= 0:
            raise HTTPException(400, 'standard_id or positive standard_hours is required')
        regular = _n(actual_hours - overtime)
        hv = _n(actual_hours - sh)
        cv = _n(actual_cost - sc)
        efficiency = _n(sh / actual_hours * 100) if actual_hours else Decimal('0')
        ot_pct = _n(overtime / actual_hours * 100) if actual_hours else Decimal('0')
        status = 'ABOVE_STANDARD' if hv <= 0 else 'OVER_STANDARD'
        pid = str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_labour_standard_performance(
                performance_id,organization_id,entity_id,period_id,run_id,department_id,product_id,standard_id,
                standard_hours,actual_hours,regular_hours,overtime_hours,output_qty,standard_cost,actual_cost,
                hours_variance,cost_variance,efficiency_pct,overtime_hours_pct,status,created_by)
                VALUES(:id,:o,:e,:p,:r,:d,:prod,:sid,:sh,:ah,:rh,:ot,:q,:sc,:ac,:hv,:cv,:eff,:otp,:s,:by)
                ON CONFLICT(organization_id,entity_id,period_id,run_id) DO UPDATE SET
                  department_id=:d,product_id=:prod,standard_id=:sid,standard_hours=:sh,actual_hours=:ah,regular_hours=:rh,
                  overtime_hours=:ot,output_qty=:q,standard_cost=:sc,actual_cost=:ac,hours_variance=:hv,cost_variance=:cv,
                  efficiency_pct=:eff,overtime_hours_pct=:otp,status=:s'''),
                {'id': pid, 'o': body['organization_id'], 'e': body['entity_id'], 'p': body['period_id'], 'r': body['run_id'],
                 'd': body.get('department_id'), 'prod': body.get('product_id'), 'sid': standard_id,
                 'sh': float(sh), 'ah': float(actual_hours), 'rh': float(regular), 'ot': float(overtime), 'q': float(output),
                 'sc': float(sc), 'ac': float(actual_cost), 'hv': float(hv), 'cv': float(cv), 'eff': float(efficiency),
                 'otp': float(ot_pct), 's': status, 'by': str(u.user_id)})
        return {'performance_id': pid, 'standard_hours': float(sh), 'actual_hours': float(actual_hours), 'hours_variance': float(hv),
                'cost_variance': float(cv), 'efficiency_pct': float(efficiency), 'overtime_hours_pct': float(ot_pct), 'status': status}

    @app.post('/v90dz/workforce/overtime-efficiency')
    def overtime_efficiency(body: dict, request: Request):
        u = _perm(engine, request, 'workforce_overtime.calculate')
        _req(body, ('organization_id', 'entity_id', 'period_id'))
        rh = _n(body.get('regular_hours'))
        oh = _n(body.get('overtime_hours'))
        q = _n(body.get('output_qty'))
        total_cost = _n(body.get('total_labour_cost'))
        ot_cost = _n(body.get('overtime_cost'))
        max_ot = _n(body.get('max_overtime_hours'))
        if min(rh, oh, q, total_cost, ot_cost, max_ot) < 0:
            raise HTTPException(400, 'overtime efficiency values cannot be negative')
        if ot_cost > total_cost:
            raise HTTPException(400, 'overtime_cost cannot exceed total_labour_cost')
        if 'overtime_output_qty' in body:
            otq = _n(body.get('overtime_output_qty'))
            if otq > q:
                raise HTTPException(400, 'overtime_output_qty cannot exceed output_qty')
        else:
            otq = _n(q * oh / (rh + oh)) if (rh + oh) else Decimal('0')
        rq = _n(q - otq)
        roph = _n(rq / rh) if rh else Decimal('0')
        toph = _n(otq / oh) if oh else Decimal('0')
        ratio = _n(toph / roph * 100) if roph else Decimal('0')
        ot_pct = _n(ot_cost / total_cost * 100) if total_cost else Decimal('0')
        excess = _n(max(oh - max_ot, Decimal('0'))) if max_ot else Decimal('0')
        status = 'EFFICIENT' if oh == 0 or ratio >= 100 else 'REVIEW'
        sid = str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_overtime_efficiency_snapshot(
                snapshot_id,organization_id,entity_id,period_id,department_id,product_id,regular_hours,overtime_hours,
                total_hours,output_qty,regular_output_qty,overtime_output_qty,regular_output_per_hour,overtime_output_per_hour,
                overtime_efficiency_pct,overtime_cost,total_labour_cost,overtime_cost_pct,excess_overtime_hours,status,created_by)
                VALUES(:id,:o,:e,:p,:d,:prod,:rh,:oh,:th,:q,:rq,:oq,:roph,:toph,:ratio,:oc,:tc,:otp,:ex,:s,:by)
                ON CONFLICT(organization_id,entity_id,period_id,department_id,product_id) DO UPDATE SET
                  regular_hours=:rh,overtime_hours=:oh,total_hours=:th,output_qty=:q,regular_output_qty=:rq,overtime_output_qty=:oq,
                  regular_output_per_hour=:roph,overtime_output_per_hour=:toph,overtime_efficiency_pct=:ratio,overtime_cost=:oc,
                  total_labour_cost=:tc,overtime_cost_pct=:otp,excess_overtime_hours=:ex,status=:s'''),
                {'id': sid, 'o': body['organization_id'], 'e': body['entity_id'], 'p': body['period_id'], 'd': body.get('department_id'),
                 'prod': body.get('product_id'), 'rh': float(rh), 'oh': float(oh), 'th': float(rh + oh), 'q': float(q),
                 'rq': float(rq), 'oq': float(otq), 'roph': float(roph), 'toph': float(toph), 'ratio': float(ratio),
                 'oc': float(ot_cost), 'tc': float(total_cost), 'otp': float(ot_pct), 'ex': float(excess), 's': status, 'by': str(u.user_id)})
        return {'snapshot_id': sid, 'regular_output_qty': float(rq), 'overtime_output_qty': float(otq),
                'regular_output_per_hour': float(roph), 'overtime_output_per_hour': float(toph),
                'overtime_efficiency_pct': float(ratio), 'overtime_cost_pct': float(ot_pct), 'excess_overtime_hours': float(excess), 'status': status}

    @app.get('/v90dz/workforce/overtime-efficiency')
    def overtime_efficiency_get(request: Request, organization_id: str, entity_id: str, period_id: str):
        _perm(engine, request, 'workforce_overtime.view')
        with engine.connect() as c:
            rows = c.execute(text('''SELECT * FROM hr_overtime_efficiency_snapshot
                WHERE organization_id=:o AND entity_id=:e AND period_id=:p ORDER BY created_at DESC'''),
                {'o': organization_id, 'e': entity_id, 'p': period_id}).mappings().all()
        return [dict(x) for x in rows]

    @app.get('/v90dz/workforce/dashboard')
    def dashboard(request: Request, organization_id: str, entity_id: str, period_id: str | None = None):
        _perm(engine, request, 'workforce_standard.view')
        where = 'organization_id=:o AND entity_id=:e'; params = {'o': organization_id, 'e': entity_id}
        if period_id:
            where += ' AND period_id=:p'; params['p'] = period_id
        with engine.connect() as c:
            p = c.execute(text(f'''SELECT COUNT(*) runs,COALESCE(AVG(efficiency_pct),0) efficiency,
                COALESCE(SUM(hours_variance),0) hours_var,COALESCE(SUM(cost_variance),0) cost_var,
                COALESCE(SUM(overtime_hours),0) overtime_hours,COALESCE(AVG(overtime_hours_pct),0) overtime_pct
                FROM hr_labour_standard_performance WHERE {where}'''), params).mappings().first()
            o = c.execute(text(f'''SELECT COUNT(*) snapshots,COALESCE(AVG(overtime_efficiency_pct),0) overtime_efficiency,
                COALESCE(SUM(excess_overtime_hours),0) excess_overtime_hours,COALESCE(AVG(overtime_cost_pct),0) overtime_cost_pct
                FROM hr_overtime_efficiency_snapshot WHERE {where}'''), params).mappings().first()
        return {'standard_runs': int(p['runs'] or 0), 'avg_efficiency_pct': float(_n(p['efficiency'])),
                'hours_variance': float(_n(p['hours_var'])), 'cost_variance': float(_n(p['cost_var'])),
                'overtime_hours': float(_n(p['overtime_hours'])), 'avg_overtime_hours_pct': float(_n(p['overtime_pct'])),
                'overtime_snapshots': int(o['snapshots'] or 0), 'avg_overtime_efficiency_pct': float(_n(o['overtime_efficiency'])),
                'excess_overtime_hours': float(_n(o['excess_overtime_hours'])), 'avg_overtime_cost_pct': float(_n(o['overtime_cost_pct']))}

    @app.post('/v90dz/workforce/periods/{period_id}/close')
    def close(period_id: str, body: dict, request: Request):
        u = _perm(engine, request, 'workforce_dz.close')
        _req(body, ('organization_id', 'entity_id'))
        with engine.connect() as c:
            count = c.execute(text('SELECT COUNT(*) FROM hr_labour_standard_performance WHERE organization_id=:o AND entity_id=:e AND period_id=:p'),
                              {'o': body['organization_id'], 'e': body['entity_id'], 'p': period_id}).scalar()
        if not count:
            raise HTTPException(409, 'no labour standard performance available for period')
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_workforce_dz_period_close(close_id,organization_id,entity_id,period_id,status,closed_by)
                VALUES(:id,:o,:e,:p,'CLOSED',:u)
                ON CONFLICT(organization_id,entity_id,period_id) DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),
                {'id': str(uuid4()), 'o': body['organization_id'], 'e': body['entity_id'], 'p': period_id, 'u': str(u.user_id)})
            c.execute(text('UPDATE hr_labour_standard_performance SET status=CASE WHEN status IN (\'ABOVE_STANDARD\',\'OVER_STANDARD\') THEN status ELSE \'CLOSED\' END WHERE organization_id=:o AND entity_id=:e AND period_id=:p'),
                      {'o': body['organization_id'], 'e': body['entity_id'], 'p': period_id})
        return {'period_id': period_id, 'status': 'CLOSED'}

    @app.get('/ui/workforce-overtime-standards')
    def page():
        return FileResponse(Path(__file__).resolve().parents[1] / 'web' / 'workforce-overtime-standards.html')

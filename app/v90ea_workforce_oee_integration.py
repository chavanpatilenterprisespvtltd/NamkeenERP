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
    permissions = permissions_for_user(engine, u.user_id)
    if permission not in permissions and 'admin.users' not in permissions:
        raise HTTPException(403, 'permission denied')
    return u


def _required(body, *keys):
    for key in keys:
        if not str(body.get(key) or '').strip():
            raise HTTPException(400, f'{key} is required')


def register_v90ea_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for permission_id, permission_name in [
            ('workforce_oee.view', 'View Workforce + OEE Integration'),
            ('workforce_oee.calculate', 'Calculate Workforce + OEE Integration'),
            ('workforce_oee.close', 'Close Workforce + OEE Integration Period'),
        ]:
            c.execute(
                text('''INSERT INTO erp_permissions(permission_id, permission_name)
                       VALUES(:p,:n)
                       ON CONFLICT(permission_id) DO NOTHING'''),
                {'p': permission_id, 'n': permission_name},
            )

    @app.post('/v90ea/workforce-oee/calculate')
    def calculate(body: dict, request: Request):
        u = _perm(engine, request, 'workforce_oee.calculate')
        _required(body, 'organization_id', 'entity_id', 'period_start', 'period_end')

        o = body['organization_id']
        e = body['entity_id']
        start = body['period_start']
        end = body['period_end']
        work_center_id = body.get('work_center_id')
        product_id = body.get('product_id')
        department_id = body.get('department_id')
        labour_weight = _n(body.get('labour_efficiency_weight') or 0.50)
        oee_weight = _n(body.get('oee_weight') or 0.50)
        total_weight = labour_weight + oee_weight
        if labour_weight < 0 or oee_weight < 0 or total_weight <= 0:
            raise HTTPException(400, 'integration weights must be non-negative and sum to a positive value')
        labour_weight = _n(labour_weight / total_weight)
        oee_weight = _n(oee_weight / total_weight)
        strong_threshold = _n(body.get('strong_threshold') or 85)
        review_threshold = _n(body.get('review_threshold') or 70)
        if review_threshold > strong_threshold:
            raise HTTPException(400, 'review_threshold cannot exceed strong_threshold')

        conditions = [
            'lp.organization_id=:o', 'lp.entity_id=:e',
            'DATE(mr.created_at) BETWEEN :s AND :d',
        ]
        params = {'o': o, 'e': e, 's': start, 'd': end}
        if work_center_id:
            conditions.append('mr.work_center_id=:w')
            params['w'] = work_center_id
        if product_id:
            conditions.append('lp.product_id=:p')
            params['p'] = product_id
        if department_id:
            conditions.append('lp.department_id=:dept')
            params['dept'] = department_id
        where = ' AND '.join(conditions)

        sql = f'''
            WITH lab AS (
                SELECT
                    mr.work_center_id,
                    lp.department_id,
                    lp.product_id,
                    COALESCE(SUM(lp.standard_hours),0) AS standard_hours,
                    COALESCE(SUM(lp.actual_hours),0) AS labour_hours,
                    COALESCE(SUM(lp.output_qty),0) AS output_qty,
                    COALESCE(SUM(lp.standard_cost),0) AS standard_cost,
                    COALESCE(SUM(lp.actual_cost),0) AS labour_cost
                FROM manufacturing_machine_run mr
                JOIN hr_labour_standard_performance lp
                  ON lp.organization_id=mr.organization_id
                 AND lp.entity_id=mr.entity_id
                 AND lp.run_id=mr.run_id
                WHERE {where}
                GROUP BY mr.work_center_id, lp.department_id, lp.product_id
            ),
            oee AS (
                SELECT
                    work_center_id,
                    AVG(availability_pct) AS availability_pct,
                    AVG(performance_pct) AS performance_pct,
                    AVG(quality_pct) AS quality_pct,
                    AVG(oee_pct) AS oee_pct
                FROM manufacturing_machine_oee
                WHERE organization_id=:o AND entity_id=:e
                  AND period_start >= :s AND period_end <= :d
                GROUP BY work_center_id
            )
            SELECT
                lab.work_center_id, lab.department_id, lab.product_id,
                lab.standard_hours, lab.labour_hours, lab.output_qty,
                lab.standard_cost, lab.labour_cost,
                oee.availability_pct, oee.performance_pct, oee.quality_pct, oee.oee_pct
            FROM lab
            LEFT JOIN oee ON oee.work_center_id=lab.work_center_id
            ORDER BY lab.work_center_id, lab.product_id NULLS FIRST
        '''
        with engine.connect() as c:
            rows = c.execute(text(sql), params).mappings().all()

        if not rows:
            raise HTTPException(409, 'no linked workforce and machine/OEE records available for period')

        created = []
        with engine.begin() as c:
            for row in rows:
                standard_hours = _n(row['standard_hours'])
                labour_hours = _n(row['labour_hours'])
                output_qty = _n(row['output_qty'])
                standard_cost = _n(row['standard_cost'])
                labour_cost = _n(row['labour_cost'])
                availability = _n(row['availability_pct'])
                performance = _n(row['performance_pct'])
                quality = _n(row['quality_pct'])
                oee = _n(row['oee_pct'])
                labour_eff = _n(standard_hours / labour_hours * 100) if labour_hours else Decimal('0')
                output_per_hour = _n(output_qty / labour_hours) if labour_hours else Decimal('0')
                cost_per_unit = _n(labour_cost / output_qty) if output_qty else Decimal('0')
                weighted = _n(labour_eff * labour_weight + oee * oee_weight)
                gap = _n(labour_eff - oee)
                if weighted >= strong_threshold:
                    status = 'STRONG'
                elif weighted >= review_threshold:
                    status = 'WATCH'
                else:
                    status = 'REVIEW'

                sid = str(uuid4())
                c.execute(text('''
                    INSERT INTO hr_workforce_oee_integration_snapshot(
                        snapshot_id,organization_id,entity_id,period_start,period_end,
                        work_center_id,department_id,product_id,standard_hours,labour_hours,
                        output_qty,standard_cost,labour_cost,availability_pct,performance_pct,
                        quality_pct,oee_pct,labour_efficiency_pct,output_per_labour_hour,
                        labour_cost_per_unit,combined_efficiency_score,labour_oee_gap,status,
                        labour_weight,oee_weight,created_by)
                    VALUES(:id,:o,:e,:s,:d,:w,:dept,:p,:sh,:lh,:q,:sc,:lc,:a,:perf,:qual,:oee,
                           :le,:oph,:cpu,:score,:gap,:status,:lw,:ow,:by)
                    ON CONFLICT(organization_id,entity_id,period_start,period_end,work_center_id,department_id,product_id)
                    DO UPDATE SET
                        standard_hours=:sh,labour_hours=:lh,output_qty=:q,standard_cost=:sc,labour_cost=:lc,
                        availability_pct=:a,performance_pct=:perf,quality_pct=:qual,oee_pct=:oee,
                        labour_efficiency_pct=:le,output_per_labour_hour=:oph,labour_cost_per_unit=:cpu,
                        combined_efficiency_score=:score,labour_oee_gap=:gap,status=:status,
                        labour_weight=:lw,oee_weight=:ow,created_by=:by,created_at=CURRENT_TIMESTAMP
                    RETURNING snapshot_id
                '''), {
                    'id': sid, 'o': o, 'e': e, 's': start, 'd': end,
                    'w': row['work_center_id'], 'dept': row['department_id'], 'p': row['product_id'],
                    'sh': float(standard_hours), 'lh': float(labour_hours), 'q': float(output_qty),
                    'sc': float(standard_cost), 'lc': float(labour_cost), 'a': float(availability),
                    'perf': float(performance), 'qual': float(quality), 'oee': float(oee),
                    'le': float(labour_eff), 'oph': float(output_per_hour), 'cpu': float(cost_per_unit),
                    'score': float(weighted), 'gap': float(gap), 'status': status,
                    'lw': float(labour_weight), 'ow': float(oee_weight), 'by': str(u.user_id),
                })
                created.append({
                    'work_center_id': row['work_center_id'],
                    'department_id': row['department_id'],
                    'product_id': row['product_id'],
                    'labour_hours': float(labour_hours),
                    'output_qty': float(output_qty),
                    'labour_efficiency_pct': float(labour_eff),
                    'oee_pct': float(oee),
                    'combined_efficiency_score': float(weighted),
                    'labour_oee_gap': float(gap),
                    'status': status,
                })
        return {'period_start': start, 'period_end': end, 'rows': created, 'status': 'CALCULATED'}

    @app.get('/v90ea/workforce-oee')
    def snapshots(request: Request, organization_id: str, entity_id: str,
                  period_start: str, period_end: str, work_center_id: str | None = None):
        _perm(engine, request, 'workforce_oee.view')
        where = 'organization_id=:o AND entity_id=:e AND period_start=:s AND period_end=:d'
        params = {'o': organization_id, 'e': entity_id, 's': period_start, 'd': period_end}
        if work_center_id:
            where += ' AND work_center_id=:w'
            params['w'] = work_center_id
        with engine.connect() as c:
            rows = c.execute(text(f'SELECT * FROM hr_workforce_oee_integration_snapshot WHERE {where} ORDER BY combined_efficiency_score DESC'), params).mappings().all()
        return [dict(x) for x in rows]

    @app.get('/v90ea/workforce-oee/dashboard')
    def dashboard(request: Request, organization_id: str, entity_id: str,
                  period_start: str, period_end: str):
        _perm(engine, request, 'workforce_oee.view')
        with engine.connect() as c:
            row = c.execute(text('''
                SELECT COUNT(*) rows_count,
                       COALESCE(AVG(labour_efficiency_pct),0) labour_efficiency_pct,
                       COALESCE(AVG(oee_pct),0) oee_pct,
                       COALESCE(AVG(combined_efficiency_score),0) combined_score,
                       COALESCE(AVG(labour_oee_gap),0) labour_oee_gap,
                       COALESCE(SUM(labour_hours),0) labour_hours,
                       COALESCE(SUM(output_qty),0) output_qty,
                       COALESCE(SUM(labour_cost),0) labour_cost,
                       COALESCE(SUM(CASE WHEN status='STRONG' THEN 1 ELSE 0 END),0) strong_count,
                       COALESCE(SUM(CASE WHEN status='WATCH' THEN 1 ELSE 0 END),0) watch_count,
                       COALESCE(SUM(CASE WHEN status='REVIEW' THEN 1 ELSE 0 END),0) review_count
                FROM hr_workforce_oee_integration_snapshot
                WHERE organization_id=:o AND entity_id=:e AND period_start=:s AND period_end=:d
            '''), {'o': organization_id, 'e': entity_id, 's': period_start, 'd': period_end}).mappings().first()
        return {k: (int(v or 0) if k.endswith('_count') or k == 'rows_count' else float(_n(v))) for k, v in row.items()}

    @app.post('/v90ea/workforce-oee/periods/close')
    def close(body: dict, request: Request):
        u = _perm(engine, request, 'workforce_oee.close')
        _required(body, 'organization_id', 'entity_id', 'period_start', 'period_end')
        with engine.begin() as c:
            count = c.execute(text('''SELECT COUNT(*) FROM hr_workforce_oee_integration_snapshot
                                      WHERE organization_id=:o AND entity_id=:e
                                        AND period_start=:s AND period_end=:d'''),
                               {'o': body['organization_id'], 'e': body['entity_id'], 's': body['period_start'], 'd': body['period_end']}).scalar()
            if not count:
                raise HTTPException(409, 'no workforce + OEE integration snapshots available for period')
            cid = str(uuid4())
            c.execute(text('''INSERT INTO hr_workforce_oee_integration_close(
                                close_id,organization_id,entity_id,period_start,period_end,status,closed_by)
                             VALUES(:id,:o,:e,:s,:d,'CLOSED',:u)
                             ON CONFLICT(organization_id,entity_id,period_start,period_end)
                             DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),
                       {'id': cid, 'o': body['organization_id'], 'e': body['entity_id'],
                        's': body['period_start'], 'd': body['period_end'], 'u': str(u.user_id)})
        return {'period_start': body['period_start'], 'period_end': body['period_end'], 'status': 'CLOSED'}

    @app.get('/ui/workforce-oee')
    def page():
        return FileResponse(Path(__file__).resolve().parents[1] / 'web' / 'workforce-oee.html')

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


def register_v90ec_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for permission_id, permission_name in [
            ('factory_bottleneck_optimization.view', 'View Factory Bottleneck Optimization'),
            ('factory_bottleneck_optimization.calculate', 'Calculate Factory Bottleneck Optimization'),
            ('factory_bottleneck_optimization.close', 'Close Factory Bottleneck Optimization Period'),
        ]:
            c.execute(text('''INSERT INTO erp_permissions(permission_id, permission_name)
                              VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'''),
                      {'p': permission_id, 'n': permission_name})

    @app.post('/v90ec/factory-bottleneck/calculate')
    def calculate(body: dict, request: Request):
        u = _perm(engine, request, 'factory_bottleneck_optimization.calculate')
        _required(body, 'organization_id', 'entity_id', 'period_start', 'period_end')
        o, e = body['organization_id'], body['entity_id']
        start, end = body['period_start'], body['period_end']
        wc_filter = body.get('work_center_id')
        working_day_hours = _n(body.get('working_day_hours') or 24, '0.01')
        overload_threshold = _n(body.get('overload_threshold') or 100)
        high_threshold = _n(body.get('high_threshold') or 90)
        moderate_threshold = _n(body.get('moderate_threshold') or 75)
        if not (0 < working_day_hours <= 24):
            raise HTTPException(400, 'working_day_hours must be > 0 and <= 24')
        if not (0 < moderate_threshold <= high_threshold <= overload_threshold):
            raise HTTPException(400, 'thresholds must satisfy 0 < moderate <= high <= overload')

        params = {'o': o, 'e': e, 's': start, 'd': end}
        wc_pred = ''
        if wc_filter:
            wc_pred = ' AND b.work_center_id=:w'
            params['w'] = wc_filter

        sql = f'''
            WITH dates AS (
                SELECT GREATEST(1, (CAST(:d AS DATE) - CAST(:s AS DATE)) + 1) AS day_count
            ),
            scheduled AS (
                SELECT work_center_id,
                       SUM(total_hours) AS scheduled_hours
                FROM manufacturing_optimized_schedule
                WHERE organization_id=:o AND entity_id=:e
                  AND scheduled_date BETWEEN :s AND :d
                  AND status IN ('PROPOSED','APPROVED','PLANNED')
                GROUP BY work_center_id
                UNION ALL
                SELECT work_center_id,
                       SUM(required_hours) AS scheduled_hours
                FROM manufacturing_schedule
                WHERE organization_id=:o AND entity_id=:e
                  AND schedule_date BETWEEN :s AND :d
                  AND status IN ('PLANNED','APPROVED')
                  AND NOT EXISTS (
                    SELECT 1 FROM manufacturing_optimized_schedule m
                    WHERE m.organization_id=manufacturing_schedule.organization_id
                      AND m.entity_id=manufacturing_schedule.entity_id
                      AND m.production_order_id=manufacturing_schedule.production_order_id
                      AND m.scheduled_date=manufacturing_schedule.schedule_date
                  )
                GROUP BY work_center_id
            ),
            sched AS (
                SELECT work_center_id, SUM(scheduled_hours) scheduled_hours
                FROM scheduled GROUP BY work_center_id
            ),
            labour_req AS (
                SELECT department_id, SUM(required_hours) required_hours
                FROM hr_workforce_capacity_plan
                WHERE organization_id=:o AND entity_id=:e
                  AND plan_date BETWEEN :s AND :d
                GROUP BY department_id
            ),
            labour_avail AS (
                SELECT department_id,
                       SUM(COALESCE(net_available_hours, available_hours)) available_hours
                FROM hr_labour_availability_forecast
                WHERE organization_id=:o AND entity_id=:e
                  AND forecast_date BETWEEN :s AND :d
                GROUP BY department_id
            )
            SELECT b.snapshot_id source_snapshot_id,
                   b.work_center_id,
                   b.department_id,
                   b.oee_pct,
                   b.labour_efficiency_pct,
                   b.combined_efficiency_score,
                   COALESCE(w.capacity_per_shift,0) capacity_per_shift,
                   COALESCE(w.shifts_per_day,1) shifts_per_day,
                   COALESCE(sch.scheduled_hours,0) scheduled_hours,
                   COALESCE(lr.required_hours,0) labour_required_hours,
                   COALESCE(la.available_hours,0) labour_available_hours,
                   dates.day_count
            FROM hr_workforce_bottleneck_snapshot b
            LEFT JOIN manufacturing_work_center w
              ON w.organization_id=b.organization_id AND w.entity_id=b.entity_id
             AND w.work_center_id=b.work_center_id
            LEFT JOIN sched sch ON sch.work_center_id=b.work_center_id
            LEFT JOIN labour_req lr ON lr.department_id=b.department_id
            LEFT JOIN labour_av la ON la.department_id=b.department_id
            CROSS JOIN dates
            WHERE b.organization_id=:o AND b.entity_id=:e
              AND b.period_start=:s AND b.period_end=:d{wc_pred}
            ORDER BY b.rank_no ASC
        '''
        with engine.connect() as c:
            rows = c.execute(text(sql), params).mappings().all()
        if not rows:
            raise HTTPException(409, 'no workforce bottleneck snapshots available for period')

        created = []
        with engine.begin() as c:
            for row in rows:
                machine_capacity = _n(_n(row['capacity_per_shift']) * _n(row['shifts_per_day']) * _n(row['day_count']))
                scheduled_hours = _n(row['scheduled_hours'])
                machine_load = _n(scheduled_hours / machine_capacity * 100) if machine_capacity else Decimal('0')
                labour_required = _n(row['labour_required_hours'])
                labour_available = _n(row['labour_available_hours'])
                labour_load = _n(labour_required / labour_available * 100) if labour_available else (Decimal('100') if labour_required else Decimal('0'))
                combined_load = _n(max(machine_load, labour_load))
                cap_gap = _n(scheduled_hours - machine_capacity) if machine_capacity else scheduled_hours
                labour_gap = _n(labour_required - labour_available)
                overtime = _n(max(Decimal('0'), labour_gap))
                oee = _n(row['oee_pct'])
                labour_eff = _n(row['labour_efficiency_pct'])
                base = _n(row['combined_efficiency_score'])
                overload = max(Decimal('0'), combined_load - 100)
                bottleneck_score = _n(min(100, max(0, base - overload)))
                machine_over = machine_load > overload_threshold
                labour_over = labour_load > overload_threshold
                machine_high = machine_load >= high_threshold
                labour_high = labour_load >= high_threshold
                if machine_over and labour_over:
                    constraint, status = 'BOTH', 'CRITICAL'
                elif machine_over:
                    constraint, status = 'MACHINE_CAPACITY', 'CRITICAL'
                elif labour_over:
                    constraint, status = 'LABOUR_CAPACITY', 'CRITICAL'
                elif machine_high and labour_high:
                    constraint, status = 'BOTH', 'HIGH'
                elif machine_high:
                    constraint, status = 'MACHINE_CAPACITY', 'HIGH'
                elif labour_high:
                    constraint, status = 'LABOUR_CAPACITY', 'HIGH'
                elif combined_load >= moderate_threshold:
                    constraint, status = ('MACHINE_CAPACITY' if machine_load >= labour_load else 'LABOUR_CAPACITY'), 'MODERATE'
                else:
                    constraint, status = 'NONE', 'LOW'
                if constraint == 'BOTH':
                    recommendation = 'Rebalance schedule and workforce; prioritize overtime only after machine capacity relief.'
                elif constraint == 'MACHINE_CAPACITY':
                    recommendation = 'Shift work to compatible work centres, improve OEE, or reschedule lower-priority orders.'
                elif constraint == 'LABOUR_CAPACITY':
                    recommendation = 'Reallocate skilled labour, adjust shifts, or use approved overtime/training plan.'
                else:
                    recommendation = 'No immediate capacity intervention required; continue monitoring.'

                sid = str(uuid4())
                c.execute(text('''
                    INSERT INTO hr_factory_bottleneck_optimization_snapshot(
                        snapshot_id,organization_id,entity_id,period_start,period_end,work_center_id,
                        department_id,machine_capacity_hours,scheduled_hours,machine_load_pct,
                        labour_required_hours,labour_available_hours,labour_load_pct,combined_load_pct,
                        capacity_gap_hours,labour_gap_hours,overtime_required_hours,oee_pct,
                        labour_efficiency_pct,bottleneck_score,constraint_type,status,recommendation,
                        source_bottleneck_snapshot_id,created_by)
                    VALUES(:id,:o,:e,:s,:d,:w,:dept,:mcap,:sched,:mload,:lreq,:lavail,:lload,:cload,
                           :cgap,:lgap,:ot,:oee,:le,:score,:ctype,:status,:rec,:source,:by)
                    ON CONFLICT(organization_id,entity_id,period_start,period_end,work_center_id)
                    DO UPDATE SET
                      department_id=:dept,machine_capacity_hours=:mcap,scheduled_hours=:sched,
                      machine_load_pct=:mload,labour_required_hours=:lreq,labour_available_hours=:lavail,
                      labour_load_pct=:lload,combined_load_pct=:cload,capacity_gap_hours=:cgap,
                      labour_gap_hours=:lgap,overtime_required_hours=:ot,oee_pct=:oee,
                      labour_efficiency_pct=:le,bottleneck_score=:score,constraint_type=:ctype,
                      status=:status,recommendation=:rec,source_bottleneck_snapshot_id=:source,
                      created_by=:by,created_at=CURRENT_TIMESTAMP
                '''), {
                    'id': sid, 'o': o, 'e': e, 's': start, 'd': end, 'w': row['work_center_id'],
                    'dept': row['department_id'], 'mcap': float(machine_capacity), 'sched': float(scheduled_hours),
                    'mload': float(machine_load), 'lreq': float(labour_required), 'lavail': float(labour_available),
                    'lload': float(labour_load), 'cload': float(combined_load), 'cgap': float(cap_gap),
                    'lgap': float(labour_gap), 'ot': float(overtime), 'oee': float(oee), 'le': float(labour_eff),
                    'score': float(bottleneck_score), 'ctype': constraint, 'status': status,
                    'rec': recommendation, 'source': row['source_snapshot_id'], 'by': str(u.user_id),
                })
                created.append({
                    'work_center_id': row['work_center_id'], 'department_id': row['department_id'],
                    'machine_capacity_hours': float(machine_capacity), 'scheduled_hours': float(scheduled_hours),
                    'machine_load_pct': float(machine_load), 'labour_required_hours': float(labour_required),
                    'labour_available_hours': float(labour_available), 'labour_load_pct': float(labour_load),
                    'combined_load_pct': float(combined_load), 'capacity_gap_hours': float(cap_gap),
                    'labour_gap_hours': float(labour_gap), 'overtime_required_hours': float(overtime),
                    'oee_pct': float(oee), 'labour_efficiency_pct': float(labour_eff),
                    'bottleneck_score': float(bottleneck_score), 'constraint_type': constraint,
                    'status': status, 'recommendation': recommendation,
                })
        return {'period_start': start, 'period_end': end, 'rows': created, 'status': 'CALCULATED'}

    @app.get('/v90ec/factory-bottleneck')
    def snapshots(request: Request, organization_id: str, entity_id: str, period_start: str, period_end: str,
                  work_center_id: str | None = None):
        _perm(engine, request, 'factory_bottleneck_optimization.view')
        where = 'organization_id=:o AND entity_id=:e AND period_start=:s AND period_end=:d'
        params = {'o': organization_id, 'e': entity_id, 's': period_start, 'd': period_end}
        if work_center_id:
            where += ' AND work_center_id=:w'; params['w'] = work_center_id
        with engine.connect() as c:
            rows = c.execute(text(f'SELECT * FROM hr_factory_bottleneck_optimization_snapshot WHERE {where} ORDER BY combined_load_pct DESC, bottleneck_score ASC'), params).mappings().all()
        return [dict(r) for r in rows]

    @app.get('/v90ec/factory-bottleneck/dashboard')
    def dashboard(request: Request, organization_id: str, entity_id: str, period_start: str, period_end: str):
        _perm(engine, request, 'factory_bottleneck_optimization.view')
        with engine.connect() as c:
            row = c.execute(text('''
                SELECT COUNT(*) rows_count,
                       COALESCE(AVG(machine_load_pct),0) machine_load_pct,
                       COALESCE(AVG(labour_load_pct),0) labour_load_pct,
                       COALESCE(AVG(combined_load_pct),0) combined_load_pct,
                       COALESCE(AVG(bottleneck_score),0) bottleneck_score,
                       COALESCE(SUM(capacity_gap_hours),0) capacity_gap_hours,
                       COALESCE(SUM(labour_gap_hours),0) labour_gap_hours,
                       COALESCE(SUM(overtime_required_hours),0) overtime_required_hours,
                       COALESCE(SUM(CASE WHEN status='CRITICAL' THEN 1 ELSE 0 END),0) critical_count,
                       COALESCE(SUM(CASE WHEN status='HIGH' THEN 1 ELSE 0 END),0) high_count,
                       COALESCE(SUM(CASE WHEN status='MODERATE' THEN 1 ELSE 0 END),0) moderate_count,
                       COALESCE(SUM(CASE WHEN status='LOW' THEN 1 ELSE 0 END),0) low_count
                FROM hr_factory_bottleneck_optimization_snapshot
                WHERE organization_id=:o AND entity_id=:e AND period_start=:s AND period_end=:d'''),
                {'o': organization_id, 'e': entity_id, 's': period_start, 'd': period_end}).mappings().first()
        return {k: (int(v or 0) if k.endswith('_count') or k == 'rows_count' else float(_n(v))) for k, v in row.items()}

    @app.post('/v90ec/factory-bottleneck/periods/close')
    def close(body: dict, request: Request):
        u = _perm(engine, request, 'factory_bottleneck_optimization.close')
        _required(body, 'organization_id', 'entity_id', 'period_start', 'period_end')
        with engine.begin() as c:
            n = c.execute(text('''SELECT COUNT(*) FROM hr_factory_bottleneck_optimization_snapshot
                                  WHERE organization_id=:organization_id AND entity_id=:entity_id
                                    AND period_start=:period_start AND period_end=:period_end'''), body).scalar()
            if not n:
                raise HTTPException(409, 'no factory bottleneck optimization snapshots available for period')
            c.execute(text('''INSERT INTO hr_factory_bottleneck_optimization_close(
                                close_id,organization_id,entity_id,period_start,period_end,status,closed_by)
                             VALUES(:id,:organization_id,:entity_id,:period_start,:period_end,'CLOSED',:u)
                             ON CONFLICT(organization_id,entity_id,period_start,period_end)
                             DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),
                      {**body, 'id': str(uuid4()), 'u': str(u.user_id)})
        return {'period_start': body['period_start'], 'period_end': body['period_end'], 'status': 'CLOSED'}

    @app.get('/ui/factory-bottleneck')
    def page():
        return FileResponse(Path(__file__).resolve().parents[1] / 'web' / 'factory-bottleneck.html')

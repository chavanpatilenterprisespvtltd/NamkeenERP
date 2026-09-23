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


def register_v90ed_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for permission_id, permission_name in [
            ('factory_bottleneck_scenario.view', 'View Factory Bottleneck Scenarios'),
            ('factory_bottleneck_scenario.simulate', 'Simulate Factory Bottleneck Scenarios'),
            ('factory_bottleneck_scenario.close', 'Close Factory Bottleneck Scenario Period'),
        ]:
            c.execute(text('''INSERT INTO erp_permissions(permission_id, permission_name)
                              VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'''),
                      {'p': permission_id, 'n': permission_name})

    @app.post('/v90ed/factory-bottleneck/scenarios/simulate')
    def simulate(body: dict, request: Request):
        u = _perm(engine, request, 'factory_bottleneck_scenario.simulate')
        _required(body, 'organization_id', 'entity_id', 'period_start', 'period_end', 'scenario_name')
        o, e = body['organization_id'], body['entity_id']
        start, end = body['period_start'], body['period_end']
        scenario_name = body['scenario_name'].strip()
        if len(scenario_name) > 120:
            raise HTTPException(400, 'scenario_name too long')
        default_oee_gain = _n(body.get('oee_gain_pct') or 0)
        default_labour_hours = _n(body.get('labour_reallocation_hours') or 0)
        default_overtime = _n(body.get('overtime_hours') or 0)
        default_schedule_reduce = _n(body.get('schedule_reduction_hours') or 0)
        if min(default_oee_gain, default_labour_hours, default_overtime, default_schedule_reduce) < 0:
            raise HTTPException(400, 'scenario adjustments cannot be negative')
        actions = body.get('work_centers') or []
        if not isinstance(actions, list):
            raise HTTPException(400, 'work_centers must be an array')
        action_map = {}
        for action in actions:
            if not isinstance(action, dict) or not str(action.get('work_center_id') or '').strip():
                raise HTTPException(400, 'each work_centers entry requires work_center_id')
            wid = str(action['work_center_id'])
            action_map[wid] = {
                'oee_gain_pct': _n(action.get('oee_gain_pct') if action.get('oee_gain_pct') is not None else default_oee_gain),
                'labour_reallocation_hours': _n(action.get('labour_reallocation_hours') if action.get('labour_reallocation_hours') is not None else default_labour_hours),
                'overtime_hours': _n(action.get('overtime_hours') if action.get('overtime_hours') is not None else default_overtime),
                'schedule_reduction_hours': _n(action.get('schedule_reduction_hours') if action.get('schedule_reduction_hours') is not None else default_schedule_reduce),
            }
            if any(v < 0 for v in action_map[wid].values()):
                raise HTTPException(400, f'negative adjustment for {wid}')

        params = {'o': o, 'e': e, 's': start, 'd': end}
        with engine.connect() as c:
            base = c.execute(text('''SELECT * FROM hr_factory_bottleneck_optimization_snapshot
                                     WHERE organization_id=:o AND entity_id=:e
                                       AND period_start=:s AND period_end=:d
                                     ORDER BY combined_load_pct DESC, work_center_id'''), params).mappings().all()
        if not base:
            raise HTTPException(409, 'no factory bottleneck optimization snapshots available for period')

        scenario_id = str(uuid4())
        result_rows = []
        improved = 0
        remaining = 0
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_factory_bottleneck_scenario(
                scenario_id,organization_id,entity_id,period_start,period_end,scenario_name,status,created_by)
                VALUES(:id,:o,:e,:s,:d,:name,'SIMULATED',:u)'''),
                      {'id': scenario_id, 'o': o, 'e': e, 's': start, 'd': end, 'name': scenario_name, 'u': str(u.user_id)})
            for row in base:
                adj = action_map.get(str(row['work_center_id']), {
                    'oee_gain_pct': default_oee_gain,
                    'labour_reallocation_hours': default_labour_hours,
                    'overtime_hours': default_overtime,
                    'schedule_reduction_hours': default_schedule_reduce,
                })
                capacity = _n(row['machine_capacity_hours'])
                scheduled = _n(max(0, _n(row['scheduled_hours']) - adj['schedule_reduction_hours']))
                labour_required = _n(max(0, _n(row['labour_required_hours']) - adj['labour_reallocation_hours']))
                labour_available = _n(_n(row['labour_available_hours']) + adj['overtime_hours'])
                machine_load = _n(scheduled / capacity * 100) if capacity else _n(100 if scheduled else 0)
                oee_after = _n(min(100, _n(row['oee_pct']) + adj['oee_gain_pct']))
                labour_load = _n(labour_required / labour_available * 100) if labour_available else _n(100 if labour_required else 0)
                combined_load = _n(max(machine_load, labour_load))
                capacity_gap = _n(max(0, scheduled - capacity))
                labour_gap = _n(max(0, labour_required - labour_available))
                overtime_after = _n(labour_gap)
                before = _n(row['combined_load_pct'])
                relief = _n(before - combined_load)
                if relief > 0:
                    improved += 1
                if combined_load > 100:
                    remaining += 1
                if combined_load > 100:
                    status = 'CRITICAL'
                elif combined_load >= 90:
                    status = 'HIGH'
                elif combined_load >= 75:
                    status = 'MODERATE'
                else:
                    status = 'LOW'
                rid = str(uuid4())
                c.execute(text('''INSERT INTO hr_factory_bottleneck_scenario_result(
                    result_id,scenario_id,work_center_id,baseline_load_pct,scenario_load_pct,
                    baseline_oee_pct,scenario_oee_pct,baseline_labour_gap_hours,scenario_labour_gap_hours,
                    schedule_reduction_hours,labour_reallocation_hours,overtime_hours,oee_gain_pct,
                    bottleneck_relief_pct,capacity_gap_hours,overtime_required_hours,status)
                    VALUES(:id,:sid,:w,:bl,:sl,:bo,:so,:bg,:sg,:sr,:lr,:ot,:og,:rel,:cg,:orh,:st)'''), {
                    'id': rid, 'sid': scenario_id, 'w': row['work_center_id'], 'bl': float(before),
                    'sl': float(combined_load), 'bo': float(_n(row['oee_pct'])), 'so': float(oee_after),
                    'bg': float(_n(row['labour_gap_hours'])), 'sg': float(labour_gap),
                    'sr': float(adj['schedule_reduction_hours']), 'lr': float(adj['labour_reallocation_hours']),
                    'ot': float(adj['overtime_hours']), 'og': float(adj['oee_gain_pct']), 'rel': float(relief),
                    'cg': float(capacity_gap), 'orh': float(overtime_after), 'st': status,
                })
                result_rows.append({
                    'work_center_id': row['work_center_id'], 'baseline_load_pct': float(before),
                    'scenario_load_pct': float(combined_load), 'bottleneck_relief_pct': float(relief),
                    'scenario_oee_pct': float(oee_after), 'scenario_labour_gap_hours': float(labour_gap),
                    'capacity_gap_hours': float(capacity_gap), 'overtime_required_hours': float(overtime_after),
                    'status': status,
                })
            c.execute(text('''UPDATE hr_factory_bottleneck_scenario SET improved_work_centers=:i,
                              remaining_overloaded_work_centers=:r,updated_at=CURRENT_TIMESTAMP
                              WHERE scenario_id=:id'''), {'i': improved, 'r': remaining, 'id': scenario_id})
        return {'scenario_id': scenario_id, 'scenario_name': scenario_name, 'status': 'SIMULATED',
                'improved_work_centers': improved, 'remaining_overloaded_work_centers': remaining,
                'rows': result_rows}

    @app.get('/v90ed/factory-bottleneck/scenarios')
    def scenarios(request: Request, organization_id: str, entity_id: str, period_start: str, period_end: str):
        _perm(engine, request, 'factory_bottleneck_scenario.view')
        with engine.connect() as c:
            rows = c.execute(text('''SELECT * FROM hr_factory_bottleneck_scenario
                                     WHERE organization_id=:o AND entity_id=:e
                                       AND period_start=:s AND period_end=:d
                                     ORDER BY created_at DESC'''),
                             {'o': organization_id, 'e': entity_id, 's': period_start, 'd': period_end}).mappings().all()
        return [dict(r) for r in rows]

    @app.get('/v90ed/factory-bottleneck/scenarios/{scenario_id}')
    def scenario_detail(scenario_id: str, request: Request):
        _perm(engine, request, 'factory_bottleneck_scenario.view')
        with engine.connect() as c:
            scenario = c.execute(text('SELECT * FROM hr_factory_bottleneck_scenario WHERE scenario_id=:id'), {'id': scenario_id}).mappings().first()
            if not scenario:
                raise HTTPException(404, 'scenario not found')
            rows = c.execute(text('''SELECT * FROM hr_factory_bottleneck_scenario_result
                                     WHERE scenario_id=:id ORDER BY scenario_load_pct DESC, work_center_id'''), {'id': scenario_id}).mappings().all()
        return {'scenario': dict(scenario), 'results': [dict(r) for r in rows]}

    @app.post('/v90ed/factory-bottleneck/scenarios/periods/close')
    def close(body: dict, request: Request):
        u = _perm(engine, request, 'factory_bottleneck_scenario.close')
        _required(body, 'organization_id', 'entity_id', 'period_start', 'period_end')
        with engine.begin() as c:
            count = c.execute(text('''SELECT COUNT(*) FROM hr_factory_bottleneck_scenario
                                      WHERE organization_id=:o AND entity_id=:e AND period_start=:s AND period_end=:d'''),
                               {'o': body['organization_id'], 'e': body['entity_id'], 's': body['period_start'], 'd': body['period_end']}).scalar()
            if not count:
                raise HTTPException(409, 'no factory bottleneck scenarios available for period')
            cid = str(uuid4())
            c.execute(text('''INSERT INTO hr_factory_bottleneck_scenario_close(
                close_id,organization_id,entity_id,period_start,period_end,status,closed_by)
                VALUES(:id,:o,:e,:s,:d,'CLOSED',:u)
                ON CONFLICT(organization_id,entity_id,period_start,period_end)
                DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),
                      {'id': cid, 'o': body['organization_id'], 'e': body['entity_id'],
                       's': body['period_start'], 'd': body['period_end'], 'u': str(u.user_id)})
        return {'period_start': body['period_start'], 'period_end': body['period_end'], 'status': 'CLOSED'}

    @app.get('/ui/factory-bottleneck-scenarios')
    def page():
        return FileResponse(Path(__file__).resolve().parents[1] / 'web' / 'factory-bottleneck-scenarios.html')

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


def register_v90ee_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for permission_id, permission_name in [
            ('factory_scenario.view', 'View Factory Scenario Comparisons'),
            ('factory_scenario.compare', 'Compare Factory Scenarios'),
            ('factory_scenario.approve', 'Approve Factory Scenario'),
            ('factory_scenario.handoff', 'Handoff Approved Factory Scenario'),
        ]:
            c.execute(text('''INSERT INTO erp_permissions(permission_id, permission_name)
                              VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'''),
                      {'p': permission_id, 'n': permission_name})

    @app.post('/v90ee/factory-bottleneck/scenarios/compare')
    def compare(body: dict, request: Request):
        u = _perm(engine, request, 'factory_scenario.compare')
        _required(body, 'organization_id', 'entity_id', 'period_start', 'period_end')
        scenario_ids = body.get('scenario_ids')
        if not isinstance(scenario_ids, list) or len(scenario_ids) < 2:
            raise HTTPException(400, 'scenario_ids must contain at least two scenarios')
        scenario_ids = [str(x).strip() for x in scenario_ids if str(x).strip()]
        if len(set(scenario_ids)) != len(scenario_ids):
            raise HTTPException(400, 'scenario_ids must be unique')
        relief_weight = _n(body.get('relief_weight') if body.get('relief_weight') is not None else 0.50)
        load_weight = _n(body.get('load_weight') if body.get('load_weight') is not None else 0.30)
        overtime_weight = _n(body.get('overtime_weight') if body.get('overtime_weight') is not None else 0.20)
        if min(relief_weight, load_weight, overtime_weight) < 0:
            raise HTTPException(400, 'comparison weights cannot be negative')
        total = relief_weight + load_weight + overtime_weight
        if total <= 0:
            raise HTTPException(400, 'comparison weights must sum to a positive value')
        relief_weight, load_weight, overtime_weight = [x / total for x in (relief_weight, load_weight, overtime_weight)]
        params = {'o': body['organization_id'], 'e': body['entity_id'], 's': body['period_start'], 'd': body['period_end']}
        placeholders = ','.join(f':sid{i}' for i in range(len(scenario_ids)))
        params.update({f'sid{i}': sid for i, sid in enumerate(scenario_ids)})
        with engine.connect() as c:
            rows = c.execute(text(f'''SELECT s.scenario_id, s.scenario_name, s.status,
                                             s.improved_work_centers, s.remaining_overloaded_work_centers,
                                             COALESCE(AVG(r.scenario_load_pct),0) avg_scenario_load_pct,
                                             COALESCE(AVG(r.bottleneck_relief_pct),0) avg_relief_pct,
                                             COALESCE(SUM(r.overtime_required_hours),0) overtime_required_hours,
                                             COALESCE(AVG(r.scenario_oee_pct),0) avg_oee_pct
                                      FROM hr_factory_bottleneck_scenario s
                                      LEFT JOIN hr_factory_bottleneck_scenario_result r ON r.scenario_id=s.scenario_id
                                      WHERE s.organization_id=:o AND s.entity_id=:e
                                        AND s.period_start=:s AND s.period_end=:d
                                        AND s.scenario_id IN ({placeholders})
                                      GROUP BY s.scenario_id, s.scenario_name, s.status,
                                               s.improved_work_centers, s.remaining_overloaded_work_centers'''), params).mappings().all()
        if len(rows) != len(scenario_ids):
            raise HTTPException(404, 'one or more scenarios were not found in the requested scope')
        summary = []
        for row in rows:
            relief = _n(row['avg_relief_pct'])
            load = _n(row['avg_scenario_load_pct'])
            ot = _n(row['overtime_required_hours'])
            rank_score = _n(relief * relief_weight + (Decimal('100') - min(Decimal('100'), load)) * load_weight + (Decimal('100') - min(Decimal('100'), ot)) * overtime_weight)
            summary.append({**dict(row), 'rank_score': float(rank_score), 'avg_relief_pct': float(relief), 'avg_scenario_load_pct': float(load), 'overtime_required_hours': float(ot)})
        summary.sort(key=lambda x: (-x['rank_score'], x['avg_scenario_load_pct'], x['overtime_required_hours']))
        comparison_id = str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_factory_bottleneck_scenario_comparison(
                comparison_id,organization_id,entity_id,period_start,period_end,scenario_count,
                relief_weight,load_weight,overtime_weight,status,created_by)
                VALUES(:id,:o,:e,:s,:d,:cnt,:rw,:lw,:ow,'DRAFT',:u)'''), {
                'id': comparison_id, 'o': body['organization_id'], 'e': body['entity_id'],
                's': body['period_start'], 'd': body['period_end'], 'cnt': len(summary),
                'rw': float(relief_weight), 'lw': float(load_weight), 'ow': float(overtime_weight), 'u': str(u.user_id)})
            for rank, item in enumerate(summary, start=1):
                c.execute(text('''INSERT INTO hr_factory_bottleneck_scenario_comparison_line(
                    line_id,comparison_id,scenario_id,rank_no,rank_score,avg_scenario_load_pct,
                    avg_relief_pct,overtime_required_hours,improved_work_centers,remaining_overloaded_work_centers)
                    VALUES(:id,:cid,:sid,:rk,:rs,:load,:rel,:ot,:imp,:rem)'''), {
                    'id': str(uuid4()), 'cid': comparison_id, 'sid': item['scenario_id'], 'rk': rank,
                    'rs': item['rank_score'], 'load': item['avg_scenario_load_pct'], 'rel': item['avg_relief_pct'],
                    'ot': item['overtime_required_hours'], 'imp': int(item['improved_work_centers'] or 0),
                    'rem': int(item['remaining_overloaded_work_centers'] or 0)})
            best_id = summary[0]['scenario_id'] if summary else None
            c.execute(text('UPDATE hr_factory_bottleneck_scenario_comparison SET recommended_scenario_id=:sid WHERE comparison_id=:id'), {'sid': best_id, 'id': comparison_id})
        return {'comparison_id': comparison_id, 'status': 'DRAFT', 'recommended_scenario_id': summary[0]['scenario_id'], 'rows': summary}

    @app.get('/v90ee/factory-bottleneck/scenarios/comparisons')
    def comparisons(request: Request, organization_id: str, entity_id: str, period_start: str, period_end: str):
        _perm(engine, request, 'factory_scenario.view')
        with engine.connect() as c:
            rows = c.execute(text('''SELECT * FROM hr_factory_bottleneck_scenario_comparison
                                     WHERE organization_id=:o AND entity_id=:e AND period_start=:s AND period_end=:d
                                     ORDER BY created_at DESC'''),
                             {'o': organization_id, 'e': entity_id, 's': period_start, 'd': period_end}).mappings().all()
        return [dict(r) for r in rows]

    @app.get('/v90ee/factory-bottleneck/scenarios/comparisons/{comparison_id}')
    def comparison_detail(comparison_id: str, request: Request):
        _perm(engine, request, 'factory_scenario.view')
        with engine.connect() as c:
            comp = c.execute(text('SELECT * FROM hr_factory_bottleneck_scenario_comparison WHERE comparison_id=:id'), {'id': comparison_id}).mappings().first()
            if not comp:
                raise HTTPException(404, 'comparison not found')
            lines = c.execute(text('''SELECT l.*, s.scenario_name, s.status AS scenario_status
                                      FROM hr_factory_bottleneck_scenario_comparison_line l
                                      JOIN hr_factory_bottleneck_scenario s ON s.scenario_id=l.scenario_id
                                      WHERE l.comparison_id=:id ORDER BY l.rank_no'''), {'id': comparison_id}).mappings().all()
            approval = c.execute(text('''SELECT * FROM hr_factory_bottleneck_scenario_approval WHERE comparison_id=:id ORDER BY created_at DESC'''), {'id': comparison_id}).mappings().all()
        return {'comparison': dict(comp), 'lines': [dict(x) for x in lines], 'approvals': [dict(x) for x in approval]}

    @app.post('/v90ee/factory-bottleneck/scenarios/comparisons/{comparison_id}/approve')
    def approve(comparison_id: str, body: dict, request: Request):
        u = _perm(engine, request, 'factory_scenario.approve')
        _required(body, 'scenario_id', 'decision')
        decision = str(body['decision']).upper().strip()
        if decision not in {'APPROVED', 'REJECTED'}:
            raise HTTPException(400, 'decision must be APPROVED or REJECTED')
        with engine.begin() as c:
            comp = c.execute(text('SELECT * FROM hr_factory_bottleneck_scenario_comparison WHERE comparison_id=:id'), {'id': comparison_id}).mappings().first()
            if not comp:
                raise HTTPException(404, 'comparison not found')
            exists = c.execute(text('SELECT 1 FROM hr_factory_bottleneck_scenario_comparison_line WHERE comparison_id=:cid AND scenario_id=:sid'), {'cid': comparison_id, 'sid': body['scenario_id']}).first()
            if not exists:
                raise HTTPException(400, 'scenario is not part of comparison')
            if decision == 'APPROVED':
                prior = c.execute(text('''SELECT approval_id FROM hr_factory_bottleneck_scenario_approval
                                          WHERE organization_id=:o AND entity_id=:e AND period_start=:s AND period_end=:d
                                            AND decision='APPROVED' AND scenario_id<>:sid LIMIT 1'''),
                                  {'o': comp['organization_id'], 'e': comp['entity_id'], 's': comp['period_start'], 'd': comp['period_end'], 'sid': body['scenario_id']}).first()
                if prior:
                    raise HTTPException(409, 'another scenario is already approved for this period')
            aid = str(uuid4())
            c.execute(text('''INSERT INTO hr_factory_bottleneck_scenario_approval(
                approval_id,comparison_id,scenario_id,organization_id,entity_id,period_start,period_end,decision,remarks,approved_by)
                VALUES(:id,:cid,:sid,:o,:e,:s,:d,:dec,:remarks,:u)
                ON CONFLICT(comparison_id,scenario_id) DO UPDATE SET decision=:dec,remarks=:remarks,approved_by=:u,created_at=CURRENT_TIMESTAMP'''), {
                'id': aid, 'cid': comparison_id, 'sid': body['scenario_id'], 'o': comp['organization_id'], 'e': comp['entity_id'],
                's': comp['period_start'], 'd': comp['period_end'], 'dec': decision, 'remarks': str(body.get('remarks') or ''), 'u': str(u.user_id)})
            c.execute(text('UPDATE hr_factory_bottleneck_scenario_comparison SET status=:st,approved_scenario_id=:sid,updated_at=CURRENT_TIMESTAMP WHERE comparison_id=:id'),
                      {'st': decision, 'sid': body['scenario_id'] if decision == 'APPROVED' else None, 'id': comparison_id})
        return {'comparison_id': comparison_id, 'scenario_id': body['scenario_id'], 'decision': decision}

    @app.post('/v90ee/factory-bottleneck/scenarios/{scenario_id}/handoff')
    def handoff(scenario_id: str, body: dict, request: Request):
        u = _perm(engine, request, 'factory_scenario.handoff')
        with engine.begin() as c:
            scenario = c.execute(text('SELECT * FROM hr_factory_bottleneck_scenario WHERE scenario_id=:id'), {'id': scenario_id}).mappings().first()
            if not scenario:
                raise HTTPException(404, 'scenario not found')
            approved = c.execute(text('''SELECT * FROM hr_factory_bottleneck_scenario_approval
                                         WHERE scenario_id=:sid AND decision='APPROVED'
                                         ORDER BY created_at DESC LIMIT 1'''), {'sid': scenario_id}).mappings().first()
            if not approved:
                raise HTTPException(409, 'scenario must be approved before handoff')
            existing = c.execute(text('SELECT * FROM hr_factory_bottleneck_scenario_handoff WHERE scenario_id=:sid AND status<>\'CANCELLED\' LIMIT 1'), {'sid': scenario_id}).mappings().first()
            if existing:
                return {'handoff_id': existing['handoff_id'], 'status': existing['status'], 'idempotent': True}
            results = c.execute(text('''SELECT * FROM hr_factory_bottleneck_scenario_result
                                       WHERE scenario_id=:sid ORDER BY scenario_load_pct DESC'''), {'sid': scenario_id}).mappings().all()
            hid = str(uuid4())
            c.execute(text('''INSERT INTO hr_factory_bottleneck_scenario_handoff(
                handoff_id,scenario_id,organization_id,entity_id,period_start,period_end,target_module,status,notes,created_by)
                VALUES(:id,:sid,:o,:e,:s,:d,'MANUFACTURING_SCHEDULING','READY',:notes,:u)'''), {
                'id': hid, 'sid': scenario_id, 'o': scenario['organization_id'], 'e': scenario['entity_id'],
                's': scenario['period_start'], 'd': scenario['period_end'], 'notes': str(body.get('notes') or ''), 'u': str(u.user_id)})
            for row in results:
                c.execute(text('''INSERT INTO hr_factory_bottleneck_scenario_handoff_action(
                    action_id,handoff_id,work_center_id,schedule_reduction_hours,labour_reallocation_hours,
                    overtime_hours,oee_gain_pct,scenario_load_pct,overtime_required_hours,status)
                    VALUES(:id,:hid,:w,:sr,:lr,:ot,:og,:load,:otr,'READY')'''), {
                    'id': str(uuid4()), 'hid': hid, 'w': row['work_center_id'], 'sr': row['schedule_reduction_hours'],
                    'lr': row['labour_reallocation_hours'], 'ot': row['overtime_hours'], 'og': row['oee_gain_pct'],
                    'load': row['scenario_load_pct'], 'otr': row['overtime_required_hours']})
        return {'handoff_id': hid, 'scenario_id': scenario_id, 'status': 'READY', 'target_module': 'MANUFACTURING_SCHEDULING', 'action_count': len(results)}

    @app.get('/v90ee/factory-bottleneck/handoffs')
    def handoffs(request: Request, organization_id: str, entity_id: str, period_start: str, period_end: str):
        _perm(engine, request, 'factory_scenario.view')
        with engine.connect() as c:
            rows = c.execute(text('''SELECT h.*, s.scenario_name
                                     FROM hr_factory_bottleneck_scenario_handoff h
                                     JOIN hr_factory_bottleneck_scenario s ON s.scenario_id=h.scenario_id
                                     WHERE h.organization_id=:o AND h.entity_id=:e AND h.period_start=:s AND h.period_end=:d
                                     ORDER BY h.created_at DESC'''),
                             {'o': organization_id, 'e': entity_id, 's': period_start, 'd': period_end}).mappings().all()
        return [dict(r) for r in rows]

    @app.get('/ui/factory-bottleneck-scenario-handoff')
    def page():
        return FileResponse(Path(__file__).resolve().parents[1] / 'web' / 'factory-bottleneck-scenario-handoff.html')

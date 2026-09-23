from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user


def _d(v):
    return Decimal(str(v or 0)).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)


def _perm(e, r, p):
    u = authenticate(r)
    ps = permissions_for_user(e, u.user_id)
    if p not in ps and 'admin.users' not in ps:
        raise HTTPException(403, 'permission denied')
    return u


def _required(body, *keys):
    for k in keys:
        if body.get(k) is None or (isinstance(body.get(k), str) and not body[k].strip()):
            raise HTTPException(400, f'{k} is required')


def register_v90eg_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for pid, name in [
            ('mfg_exec_recon.view', 'View Manufacturing Execution Reconciliation'),
            ('mfg_exec_recon.reconcile', 'Reconcile Manufacturing Scenario Execution'),
            ('mfg_exec_recon.close', 'Close Manufacturing Execution Reconciliation Period'),
        ]:
            c.execute(text('''INSERT INTO erp_permissions(permission_id,permission_name)
                              VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'''), {'p': pid, 'n': name})

    @app.post('/v90eg/manufacturing/scenario-executions/{execution_id}/reconcile')
    def reconcile(execution_id: str, body: dict, request: Request):
        u = _perm(engine, request, 'mfg_exec_recon.reconcile')
        with engine.begin() as c:
            ex = c.execute(text('SELECT * FROM manufacturing_scenario_execution WHERE execution_id=:i'), {'i': execution_id}).mappings().first()
            if not ex:
                raise HTTPException(404, 'scenario execution not found')
            if ex['status'] != 'EXECUTED':
                raise HTTPException(409, 'scenario execution must be EXECUTED before reconciliation')
            prior = c.execute(text('''SELECT reconciliation_id,status FROM manufacturing_scenario_execution_reconciliation
                                      WHERE execution_id=:i ORDER BY created_at DESC LIMIT 1'''), {'i': execution_id}).mappings().first()
            if prior and prior['status'] == 'CLOSED':
                return {'reconciliation_id': prior['reconciliation_id'], 'status': prior['status'], 'idempotent': True}
            lines = c.execute(text('''SELECT l.*, s.planned_qty AS actual_planned_qty,
                                            s.required_hours AS actual_required_hours
                                     FROM manufacturing_scenario_execution_line l
                                     JOIN manufacturing_schedule s ON s.schedule_id=l.schedule_id
                                     WHERE l.execution_id=:i'''), {'i': execution_id}).mappings().all()
            if not lines:
                raise HTTPException(409, 'execution has no reconciliation lines')
            recon_id = str(uuid4())
            line_count = len(lines)
            total_orig_qty = sum((_d(r['original_planned_qty']) for r in lines), Decimal('0'))
            total_exec_qty = sum((_d(r['proposed_planned_qty']) for r in lines), Decimal('0'))
            total_actual_qty = sum((_d(r['actual_planned_qty']) for r in lines), Decimal('0'))
            total_orig_hours = sum((_d(r['original_required_hours']) for r in lines), Decimal('0'))
            total_exec_hours = sum((_d(r['proposed_required_hours']) for r in lines), Decimal('0'))
            total_actual_hours = sum((_d(r['actual_required_hours']) for r in lines), Decimal('0'))
            overtime = c.execute(text('''SELECT COALESCE(SUM(overtime_hours),0) h FROM manufacturing_scenario_overtime
                                        WHERE execution_id=:i AND status='EXECUTED' '''), {'i': execution_id}).scalar_one()
            baseline_reduction_qty = total_orig_qty - total_exec_qty
            actual_reduction_qty = total_orig_qty - total_actual_qty
            baseline_reduction_hours = total_orig_hours - total_exec_hours
            actual_reduction_hours = total_orig_hours - total_actual_hours
            qty_variance = total_actual_qty - total_exec_qty
            hours_variance = total_actual_hours - total_exec_hours
            overtime_actual = _d(overtime)
            plan_overtime = c.execute(text('''SELECT COALESCE(SUM(overtime_hours),0) h FROM manufacturing_scenario_overtime
                                              WHERE execution_id=:i'''), {'i': execution_id}).scalar_one()
            overtime_variance = overtime_actual - _d(plan_overtime)
            status = 'ON_TRACK'
            if abs(hours_variance) > _d(body.get('hours_tolerance', 0)) or abs(qty_variance) > _d(body.get('qty_tolerance', 0)) or overtime_variance > _d(body.get('overtime_tolerance', 0)):
                status = 'VARIANCE'
            c.execute(text('''INSERT INTO manufacturing_scenario_execution_reconciliation(
                reconciliation_id,execution_id,organization_id,entity_id,period_start,period_end,status,
                original_qty,planned_qty,actual_qty,original_hours,planned_hours,actual_hours,
                planned_overtime_hours,actual_overtime_hours,qty_variance,hours_variance,overtime_variance,
                notes,reconciled_by)
                VALUES(:id,:e,:o,:ent,:s,:d,:st,:oq,:pq,:aq,:oh,:ph,:ah,:pot,:aot,:qv,:hv,:ov,:n,:u)'''), {
                'id': recon_id, 'e': execution_id, 'o': ex['organization_id'], 'ent': ex['entity_id'],
                's': ex['period_start'], 'd': ex['period_end'], 'st': status,
                'oq': float(total_orig_qty), 'pq': float(total_exec_qty), 'aq': float(total_actual_qty),
                'oh': float(total_orig_hours), 'ph': float(total_exec_hours), 'ah': float(total_actual_hours),
                'pot': float(_d(plan_overtime)), 'aot': float(overtime_actual), 'qv': float(qty_variance),
                'hv': float(hours_variance), 'ov': float(overtime_variance), 'n': str(body.get('notes') or ''), 'u': str(u.user_id)})
            for row in lines:
                line_status = 'ON_TRACK'
                lqv = _d(row['actual_planned_qty']) - _d(row['proposed_planned_qty'])
                lhv = _d(row['actual_required_hours']) - _d(row['proposed_required_hours'])
                if abs(lqv) > _d(body.get('qty_tolerance', 0)) or abs(lhv) > _d(body.get('hours_tolerance', 0)):
                    line_status = 'VARIANCE'
                c.execute(text('''INSERT INTO manufacturing_scenario_execution_reconciliation_line(
                    reconciliation_line_id,reconciliation_id,work_center_id,schedule_id,
                    planned_qty,actual_qty,qty_variance,planned_hours,actual_hours,hours_variance,status,created_at)
                    VALUES(:id,:r,:w,:s,:pq,:aq,:qv,:ph,:ah,:hv,:st,CURRENT_TIMESTAMP)'''), {
                    'id': str(uuid4()), 'r': recon_id, 'w': row['work_center_id'], 's': row['schedule_id'],
                    'pq': float(_d(row['proposed_planned_qty'])), 'aq': float(_d(row['actual_planned_qty'])),
                    'qv': float(lqv), 'ph': float(_d(row['proposed_required_hours'])), 'ah': float(_d(row['actual_required_hours'])),
                    'hv': float(lhv), 'st': line_status})
            return {'reconciliation_id': recon_id, 'status': status, 'line_count': line_count,
                    'qty_variance': float(qty_variance), 'hours_variance': float(hours_variance),
                    'overtime_variance': float(overtime_variance), 'baseline_reduction_qty': float(baseline_reduction_qty),
                    'actual_reduction_qty': float(actual_reduction_qty), 'baseline_reduction_hours': float(baseline_reduction_hours),
                    'actual_reduction_hours': float(actual_reduction_hours)}

    @app.get('/v90eg/manufacturing/scenario-execution-reconciliations/{reconciliation_id}')
    def detail(reconciliation_id: str, request: Request):
        _perm(engine, request, 'mfg_exec_recon.view')
        with engine.connect() as c:
            r = c.execute(text('SELECT * FROM manufacturing_scenario_execution_reconciliation WHERE reconciliation_id=:i'), {'i': reconciliation_id}).mappings().first()
            if not r:
                raise HTTPException(404, 'reconciliation not found')
            lines = c.execute(text('''SELECT * FROM manufacturing_scenario_execution_reconciliation_line
                                      WHERE reconciliation_id=:i ORDER BY work_center_id,schedule_id'''), {'i': reconciliation_id}).mappings().all()
            exceptions = c.execute(text('''SELECT * FROM manufacturing_scenario_execution_reconciliation_exception
                                           WHERE reconciliation_id=:i ORDER BY created_at'''), {'i': reconciliation_id}).mappings().all()
        return {'reconciliation': dict(r), 'lines': [dict(x) for x in lines], 'exceptions': [dict(x) for x in exceptions]}

    @app.get('/v90eg/manufacturing/scenario-execution-reconciliations')
    def listing(request: Request, organization_id: str, entity_id: str, period_start: str, period_end: str):
        _perm(engine, request, 'mfg_exec_recon.view')
        with engine.connect() as c:
            rows = c.execute(text('''SELECT * FROM manufacturing_scenario_execution_reconciliation
                                     WHERE organization_id=:o AND entity_id=:e AND period_start=:s AND period_end=:d
                                     ORDER BY created_at DESC'''), {'o': organization_id, 'e': entity_id, 's': period_start, 'd': period_end}).mappings().all()
        return [dict(x) for x in rows]

    @app.post('/v90eg/manufacturing/scenario-execution-reconciliations/{reconciliation_id}/close')
    def close(reconciliation_id: str, request: Request):
        u = _perm(engine, request, 'mfg_exec_recon.close')
        with engine.begin() as c:
            r = c.execute(text('SELECT * FROM manufacturing_scenario_execution_reconciliation WHERE reconciliation_id=:i'), {'i': reconciliation_id}).mappings().first()
            if not r:
                raise HTTPException(404, 'reconciliation not found')
            if r['status'] == 'CLOSED':
                return {'reconciliation_id': reconciliation_id, 'status': 'CLOSED', 'idempotent': True}
            c.execute(text('''UPDATE manufacturing_scenario_execution_reconciliation
                              SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP
                              WHERE reconciliation_id=:i'''), {'u': str(u.user_id), 'i': reconciliation_id})
        return {'reconciliation_id': reconciliation_id, 'status': 'CLOSED'}

    @app.get('/ui/manufacturing-scenario-execution-reconciliation')
    def page():
        return FileResponse(Path(__file__).resolve().parents[1] / 'web' / 'manufacturing-scenario-execution-reconciliation.html')

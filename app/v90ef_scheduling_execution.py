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


def register_v90ef_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for pid, name in [
            ('mfg_scenario_execution.view', 'View Manufacturing Scenario Execution'),
            ('mfg_scenario_execution.create', 'Create Manufacturing Scenario Execution'),
            ('mfg_scenario_execution.approve', 'Approve Manufacturing Scenario Execution'),
            ('mfg_scenario_execution.execute', 'Execute Manufacturing Scenario Execution'),
            ('mfg_scenario_execution.close', 'Close Manufacturing Scenario Execution Period'),
        ]:
            c.execute(text('''INSERT INTO erp_permissions(permission_id,permission_name)
                              VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'''), {'p': pid, 'n': name})

    @app.post('/v90ef/manufacturing/scenario-executions')
    def create_execution(body: dict, request: Request):
        u = _perm(engine, request, 'mfg_scenario_execution.create')
        _required(body, 'handoff_id')
        with engine.begin() as c:
            handoff = c.execute(text('''SELECT * FROM hr_factory_bottleneck_scenario_handoff
                                        WHERE handoff_id=:h AND status='READY' '''), {'h': body['handoff_id']}).mappings().first()
            if not handoff:
                raise HTTPException(404, 'ready scenario handoff not found')
            existing = c.execute(text('''SELECT execution_id,status FROM manufacturing_scenario_execution
                                         WHERE handoff_id=:h AND status <> 'CANCELLED' LIMIT 1'''), {'h': body['handoff_id']}).mappings().first()
            if existing:
                return {'execution_id': existing['execution_id'], 'status': existing['status'], 'idempotent': True}
            actions = c.execute(text('''SELECT * FROM hr_factory_bottleneck_scenario_handoff_action
                                        WHERE handoff_id=:h ORDER BY work_center_id'''), {'h': body['handoff_id']}).mappings().all()
            if not actions:
                raise HTTPException(409, 'scenario handoff has no work-centre actions')
            eid = str(uuid4())
            c.execute(text('''INSERT INTO manufacturing_scenario_execution(
                execution_id,handoff_id,organization_id,entity_id,period_start,period_end,status,notes,created_by)
                VALUES(:i,:h,:o,:e,:s,:d,'PROPOSED',:n,:u)'''), {
                'i': eid, 'h': body['handoff_id'], 'o': handoff['organization_id'], 'e': handoff['entity_id'],
                's': handoff['period_start'], 'd': handoff['period_end'], 'n': str(body.get('notes') or ''), 'u': str(u.user_id)})
            created = 0
            for a in actions:
                schedules = c.execute(text('''SELECT schedule_id,planned_qty,required_hours,work_center_id
                                              FROM manufacturing_schedule
                                              WHERE organization_id=:o AND entity_id=:e AND work_center_id=:w
                                                AND schedule_date BETWEEN :s AND :d
                                                AND status IN ('PLANNED','APPROVED')
                                              ORDER BY schedule_date,created_at,schedule_id'''), {
                    'o': handoff['organization_id'], 'e': handoff['entity_id'], 'w': a['work_center_id'],
                    's': handoff['period_start'], 'd': handoff['period_end']}).mappings().all()
                total_hours = sum((_d(x['required_hours']) for x in schedules), Decimal('0'))
                reduction = min(_d(a['schedule_reduction_hours']), total_hours) if total_hours else Decimal('0')
                for s in schedules:
                    share = (reduction * _d(s['required_hours']) / total_hours) if total_hours else Decimal('0')
                    qty_reduction = (_d(s['planned_qty']) * share / _d(s['required_hours'])) if _d(s['required_hours']) > 0 else Decimal('0')
                    c.execute(text('''INSERT INTO manufacturing_scenario_execution_line(
                        line_id,execution_id,work_center_id,schedule_id,original_planned_qty,original_required_hours,
                        proposed_planned_qty,proposed_required_hours,overtime_hours,status)
                        VALUES(:i,:e,:w,:s,:oq,:oh,:pq,:ph,:ot,'PROPOSED')'''), {
                        'i': str(uuid4()), 'e': eid, 'w': s['work_center_id'], 's': s['schedule_id'],
                        'oq': float(s['planned_qty']), 'oh': float(s['required_hours']),
                        'pq': float(max(Decimal('0'), _d(s['planned_qty'])-qty_reduction)),
                        'ph': float(max(Decimal('0'), _d(s['required_hours'])-share)), 'ot': 0.0})
                    created += 1
                ot = _d(a['overtime_hours'])
                if ot > 0:
                    c.execute(text('''INSERT INTO manufacturing_scenario_overtime(
                        overtime_id,execution_id,work_center_id,overtime_hours,status)
                        VALUES(:i,:e,:w,:h,'PROPOSED')'''), {'i': str(uuid4()), 'e': eid, 'w': a['work_center_id'], 'h': float(ot)})
            c.execute(text('UPDATE manufacturing_scenario_execution SET proposal_line_count=:n WHERE execution_id=:i'), {'n': created, 'i': eid})
        return {'execution_id': eid, 'status': 'PROPOSED', 'proposal_line_count': created}

    @app.get('/v90ef/manufacturing/scenario-executions/{execution_id}')
    def execution_detail(execution_id: str, request: Request):
        _perm(engine, request, 'mfg_scenario_execution.view')
        with engine.connect() as c:
            ex = c.execute(text('SELECT * FROM manufacturing_scenario_execution WHERE execution_id=:i'), {'i': execution_id}).mappings().first()
            if not ex:
                raise HTTPException(404, 'scenario execution not found')
            lines = c.execute(text('''SELECT * FROM manufacturing_scenario_execution_line
                                      WHERE execution_id=:i ORDER BY work_center_id,schedule_id'''), {'i': execution_id}).mappings().all()
            ot = c.execute(text('SELECT * FROM manufacturing_scenario_overtime WHERE execution_id=:i ORDER BY work_center_id'), {'i': execution_id}).mappings().all()
        return {'execution': dict(ex), 'lines': [dict(x) for x in lines], 'overtime': [dict(x) for x in ot]}

    @app.get('/v90ef/manufacturing/scenario-executions')
    def executions(request: Request, organization_id: str, entity_id: str, period_start: str, period_end: str):
        _perm(engine, request, 'mfg_scenario_execution.view')
        with engine.connect() as c:
            rows = c.execute(text('''SELECT * FROM manufacturing_scenario_execution
                                     WHERE organization_id=:o AND entity_id=:e AND period_start=:s AND period_end=:d
                                     ORDER BY created_at DESC'''), {'o':organization_id,'e':entity_id,'s':period_start,'d':period_end}).mappings().all()
        return [dict(r) for r in rows]

    @app.post('/v90ef/manufacturing/scenario-executions/{execution_id}/approve')
    def approve(execution_id: str, body: dict, request: Request):
        u = _perm(engine, request, 'mfg_scenario_execution.approve')
        with engine.begin() as c:
            ex = c.execute(text('SELECT * FROM manufacturing_scenario_execution WHERE execution_id=:i'), {'i': execution_id}).mappings().first()
            if not ex:
                raise HTTPException(404, 'scenario execution not found')
            if ex['status'] != 'PROPOSED':
                raise HTTPException(409, 'scenario execution is not in PROPOSED status')
            c.execute(text('''UPDATE manufacturing_scenario_execution
                              SET status='APPROVED',approved_by=:u,approved_at=CURRENT_TIMESTAMP,notes=:n
                              WHERE execution_id=:i'''), {'u':str(u.user_id), 'n':str(body.get('remarks') or ex['notes'] or ''), 'i':execution_id})
            c.execute(text("UPDATE manufacturing_scenario_execution_line SET status='APPROVED' WHERE execution_id=:i"), {'i':execution_id})
            c.execute(text("UPDATE manufacturing_scenario_overtime SET status='APPROVED' WHERE execution_id=:i"), {'i':execution_id})
        return {'execution_id': execution_id, 'status': 'APPROVED'}

    @app.post('/v90ef/manufacturing/scenario-executions/{execution_id}/execute')
    def execute(execution_id: str, request: Request):
        u = _perm(engine, request, 'mfg_scenario_execution.execute')
        with engine.begin() as c:
            ex = c.execute(text('SELECT * FROM manufacturing_scenario_execution WHERE execution_id=:i'), {'i': execution_id}).mappings().first()
            if not ex:
                raise HTTPException(404, 'scenario execution not found')
            if ex['status'] != 'APPROVED':
                raise HTTPException(409, 'scenario execution must be approved before execution')
            lines = c.execute(text('SELECT * FROM manufacturing_scenario_execution_line WHERE execution_id=:i AND status=\'APPROVED\''), {'i': execution_id}).mappings().all()
            for line in lines:
                current = c.execute(text('SELECT status FROM manufacturing_schedule WHERE schedule_id=:s'), {'s':line['schedule_id']}).first()
                if not current:
                    raise HTTPException(409, f'schedule {line["schedule_id"]} no longer exists')
                if current[0] not in ('PLANNED','APPROVED'):
                    raise HTTPException(409, f'schedule {line["schedule_id"]} is no longer executable')
                c.execute(text('''UPDATE manufacturing_schedule
                                  SET planned_qty=:q, required_hours=:h
                                  WHERE schedule_id=:s AND planned_qty=:oq AND required_hours=:oh'''), {
                    'q':line['proposed_planned_qty'], 'h':line['proposed_required_hours'], 's':line['schedule_id'],
                    'oq':line['original_planned_qty'], 'oh':line['original_required_hours']})
                c.execute(text('''UPDATE manufacturing_scenario_execution_line
                                  SET status='EXECUTED',executed_at=CURRENT_TIMESTAMP WHERE line_id=:i'''), {'i':line['line_id']})
            c.execute(text('UPDATE manufacturing_scenario_overtime SET status=\'EXECUTED\',executed_at=CURRENT_TIMESTAMP WHERE execution_id=:i AND status=\'APPROVED\''), {'i':execution_id})
            c.execute(text('''UPDATE manufacturing_scenario_execution SET status='EXECUTED',executed_by=:u,executed_at=CURRENT_TIMESTAMP WHERE execution_id=:i'''), {'u':str(u.user_id),'i':execution_id})
        return {'execution_id':execution_id,'status':'EXECUTED'}

    @app.post('/v90ef/manufacturing/scenario-executions/periods/close')
    def close_period(body: dict, request: Request):
        u = _perm(engine, request, 'mfg_scenario_execution.close')
        _required(body, 'organization_id', 'entity_id', 'period_start', 'period_end')
        with engine.begin() as c:
            pending = c.execute(text("SELECT COUNT(*) FROM manufacturing_scenario_execution WHERE organization_id=:o AND entity_id=:e AND period_start=:s AND period_end=:d AND status IN ('PROPOSED','APPROVED')"), {'o':body['organization_id'],'e':body['entity_id'],'s':body['period_start'],'d':body['period_end']}).scalar_one()
            if pending:
                raise HTTPException(409, 'pending scenario executions remain for period')
            cid = str(uuid4())
            c.execute(text('''INSERT INTO manufacturing_scenario_execution_close(
                close_id,organization_id,entity_id,period_start,period_end,status,closed_by)
                VALUES(:i,:o,:e,:s,:d,'CLOSED',:u)
                ON CONFLICT(organization_id,entity_id,period_start,period_end)
                DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''), {'i':cid,'o':body['organization_id'],'e':body['entity_id'],'s':body['period_start'],'d':body['period_end'],'u':str(u.user_id)})
        return {'status':'CLOSED','organization_id':body['organization_id'],'entity_id':body['entity_id'],'period_start':body['period_start'],'period_end':body['period_end']}

    @app.get('/ui/manufacturing-scenario-execution')
    def page():
        return FileResponse(Path(__file__).resolve().parents[1] / 'web' / 'manufacturing-scenario-execution.html')
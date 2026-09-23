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


def register_v90eh_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for pid, name in [
            ('factory_benefit.view', 'View Factory Execution Benefit Realization'),
            ('factory_benefit.realize', 'Calculate Factory Execution Benefit Realization'),
            ('factory_benefit.close', 'Close Factory Execution Benefit Period'),
        ]:
            c.execute(text('''INSERT INTO erp_permissions(permission_id,permission_name)
                              VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'''), {'p': pid, 'n': name})

    @app.post('/v90eh/factory-bottleneck/benefit-realizations')
    def realize(body: dict, request: Request):
        u = _perm(engine, request, 'factory_benefit.realize')
        reconciliation_id = str(body.get('reconciliation_id') or '').strip()
        if not reconciliation_id:
            raise HTTPException(400, 'reconciliation_id is required')
        with engine.begin() as c:
            recon = c.execute(text('''SELECT * FROM manufacturing_scenario_execution_reconciliation
                                      WHERE reconciliation_id=:r'''), {'r': reconciliation_id}).mappings().first()
            if not recon:
                raise HTTPException(404, 'reconciliation not found')
            if recon['status'] != 'CLOSED':
                raise HTTPException(409, 'reconciliation must be CLOSED before benefit realization')
            existing = c.execute(text('''SELECT realization_id,status,closure_status FROM hr_factory_execution_benefit_realization
                                         WHERE reconciliation_id=:r'''), {'r': reconciliation_id}).mappings().first()
            if existing:
                return {'realization_id': existing['realization_id'], 'status': existing['status'], 'closure_status': existing['closure_status'], 'idempotent': True}
            ex = c.execute(text('SELECT * FROM manufacturing_scenario_execution WHERE execution_id=:e'), {'e': recon['execution_id']}).mappings().first()
            if not ex:
                raise HTTPException(404, 'scenario execution not found')
            handoff = c.execute(text('SELECT * FROM hr_factory_bottleneck_scenario_handoff WHERE handoff_id=:h'), {'h': ex['handoff_id']}).mappings().first()
            if not handoff:
                raise HTTPException(404, 'scenario handoff not found')
            scenario_id = str(handoff['scenario_id'])
            scenario = c.execute(text('SELECT * FROM hr_factory_bottleneck_scenario WHERE scenario_id=:s'), {'s': scenario_id}).mappings().first()
            if not scenario:
                raise HTTPException(404, 'scenario not found')
            planned_overtime = _d(recon['planned_overtime_hours'])
            actual_overtime = _d(recon['actual_overtime_hours'])
            planned_hours_reduction = _d(recon['original_hours']) - _d(recon['planned_hours'])
            actual_hours_reduction = _d(recon['original_hours']) - _d(recon['actual_hours'])
            planned_capacity_gap = _d(c.execute(text('''SELECT COALESCE(SUM(capacity_gap_hours),0) FROM hr_factory_bottleneck_scenario_result WHERE scenario_id=:s'''), {'s': scenario_id}).scalar_one())
            baseline_loads = c.execute(text('''SELECT r.work_center_id,r.baseline_load_pct,r.scenario_load_pct,
                                                      r.bottleneck_relief_pct,r.overtime_hours,r.overtime_required_hours,
                                                      r.capacity_gap_hours
                                               FROM hr_factory_bottleneck_scenario_result r WHERE r.scenario_id=:s'''), {'s': scenario_id}).mappings().all()
            if not baseline_loads:
                raise HTTPException(409, 'scenario has no result rows')
            recon_lines = c.execute(text('''SELECT l.* FROM manufacturing_scenario_execution_reconciliation_line l
                                             WHERE l.reconciliation_id=:r'''), {'r': reconciliation_id}).mappings().all()
            line_map = {str(x['work_center_id']): x for x in recon_lines}
            execution_lines = c.execute(text('''SELECT work_center_id,
                                                      SUM(original_required_hours) AS original_hours,
                                                      SUM(proposed_required_hours) AS proposed_hours
                                               FROM manufacturing_scenario_execution_line
                                               WHERE execution_id=:e
                                               GROUP BY work_center_id'''), {'e': recon['execution_id']}).mappings().all()
            execution_line_map = {str(x['work_center_id']): x for x in execution_lines}
            planned_relief = sum((_d(x['bottleneck_relief_pct']) for x in baseline_loads), Decimal('0')) / Decimal(len(baseline_loads))
            realized_reliefs = []
            lines = []
            for x in baseline_loads:
                wc = str(x['work_center_id'])
                recon_line = line_map.get(wc)
                planned_load = _d(x['scenario_load_pct'])
                realized_load = planned_load
                exec_line = execution_line_map.get(wc)
                planned_reduction = (_d(exec_line['original_hours']) - _d(exec_line['proposed_hours'])) if exec_line else Decimal('0')
                actual_reduction = (planned_reduction if not recon_line else (_d(exec_line['original_hours']) - _d(recon_line['actual_hours']) if exec_line else _d(recon_line['planned_hours']) - _d(recon_line['actual_hours'])))
                if recon_line:
                    execution_planned = _d(recon_line['planned_hours'])
                    execution_actual = _d(recon_line['actual_hours'])
                    if planned_reduction > 0:
                        realization_ratio = max(Decimal('0'), min(Decimal('1'), actual_reduction / planned_reduction))
                    else:
                        realization_ratio = Decimal('1') if execution_actual == execution_planned else Decimal('0')
                    planned_relief_line = _d(x['bottleneck_relief_pct'])
                    realized_relief = _d(planned_relief_line * realization_ratio)
                    realized_load = _d(x['baseline_load_pct']) - realized_relief
                    actual_gap = _d(max(0, _d(x['capacity_gap_hours']) * (Decimal('1') - realization_ratio)))
                else:
                    actual_gap = _d(x['capacity_gap_hours'])
                    realized_relief = Decimal('0')
                realized_relief = _d(max(Decimal('0'), realized_relief))
                realized_reliefs.append(realized_relief)
                ot_planned = _d(x['overtime_hours'])
                ot_actual = _d(max(Decimal('0'), actual_reduction - planned_reduction)) if recon_line else Decimal('0')
                benefit = _d((realized_relief / planned_relief * 100) if planned_relief > 0 else (100 if realized_relief == 0 else 0))
                benefit = _d(min(100, max(0, benefit)))
                status = 'REALIZED' if benefit >= 80 else ('PARTIAL' if benefit >= 40 else 'MISSED')
                lines.append((wc, planned_load, realized_load, _d(x['bottleneck_relief_pct']), realized_relief,
                              ot_planned, ot_actual, actual_reduction, actual_gap, benefit, status))
            realized_relief = sum(realized_reliefs, Decimal('0')) / Decimal(len(realized_reliefs))
            savings_factor = _d((actual_hours_reduction / planned_hours_reduction * 100) if planned_hours_reduction > 0 else (100 if actual_hours_reduction == 0 else 0))
            overtime_factor = _d((planned_overtime / actual_overtime * 100) if actual_overtime > 0 else (100 if planned_overtime == 0 else 0))
            benefit_score = _d((realized_relief + min(savings_factor, Decimal('100')) + min(overtime_factor, Decimal('100'))) / Decimal('3'))
            closure_status = 'CLOSED' if benefit_score >= 80 and actual_overtime <= planned_overtime else 'OPEN'
            rid = str(uuid4())
            c.execute(text('''INSERT INTO hr_factory_execution_benefit_realization(
                realization_id,reconciliation_id,execution_id,scenario_id,organization_id,entity_id,period_start,period_end,
                status,planned_bottleneck_relief_pct,realized_bottleneck_relief_pct,planned_overtime_hours,actual_overtime_hours,
                planned_hours_reduction,actual_hours_reduction,planned_capacity_gap_hours,realized_capacity_gap_hours,
                benefit_score_pct,closure_status,notes,created_by)
                VALUES(:id,:r,:e,:s,:o,:ent,:ps,:pe,'REALIZED',:pr,:rr,:pot,:aot,:phr,:ahr,:pcg,:rcg,:score,:cs,:n,:u)'''), {
                'id': rid,'r':reconciliation_id,'e':recon['execution_id'],'s':scenario_id,'o':recon['organization_id'],'ent':recon['entity_id'],
                'ps':recon['period_start'],'pe':recon['period_end'],'pr':float(planned_relief),'rr':float(realized_relief),
                'pot':float(planned_overtime),'aot':float(actual_overtime),'phr':float(planned_hours_reduction),'ahr':float(actual_hours_reduction),
                'pcg':float(planned_capacity_gap),'rcg':float(max(0, planned_capacity_gap - (actual_hours_reduction if actual_hours_reduction > 0 else Decimal('0')))),
                'score':float(benefit_score),'cs':closure_status,'n':str(body.get('notes') or ''),'u':str(u.user_id)})
            for wc, pl, rl, p_rel, r_rel, p_ot, a_ot, a_save, a_gap, score, status in lines:
                c.execute(text('''INSERT INTO hr_factory_execution_benefit_realization_line(
                    realization_line_id,realization_id,work_center_id,planned_load_pct,realized_load_pct,
                    planned_relief_pct,realized_relief_pct,planned_overtime_hours,realized_overtime_hours,
                    planned_hours_reduction,actual_hours_reduction,planned_capacity_gap_hours,realized_capacity_gap_hours,
                    benefit_score_pct,status,created_at)
                    VALUES(:id,:r,:w,:pl,:rl,:pr,:rr,:pot,:aot,:phr,:ahr,:pcg,:rcg,:score,:st,CURRENT_TIMESTAMP)'''), {
                    'id':str(uuid4()),'r':rid,'w':wc,'pl':float(pl),'rl':float(rl),'pr':float(p_rel),'rr':float(r_rel),
                    'pot':float(p_ot),'aot':float(a_ot),'phr':float(a_save + _d(0)),'ahr':float(a_save),'pcg':float(max(0,_d(a_gap))),
                    'rcg':float(max(0,_d(a_gap))),'score':float(score),'st':status})
        return {'realization_id': rid,'status':'REALIZED','closure_status':closure_status,'planned_bottleneck_relief_pct':float(planned_relief),
                'realized_bottleneck_relief_pct':float(realized_relief),'planned_overtime_hours':float(planned_overtime),
                'actual_overtime_hours':float(actual_overtime),'planned_hours_reduction':float(planned_hours_reduction),
                'actual_hours_reduction':float(actual_hours_reduction),'benefit_score_pct':float(benefit_score)}

    @app.get('/v90eh/factory-bottleneck/benefit-realizations/{realization_id}')
    def detail(realization_id: str, request: Request):
        _perm(engine, request, 'factory_benefit.view')
        with engine.connect() as c:
            r = c.execute(text('SELECT * FROM hr_factory_execution_benefit_realization WHERE realization_id=:i'), {'i': realization_id}).mappings().first()
            if not r: raise HTTPException(404, 'benefit realization not found')
            lines = c.execute(text('SELECT * FROM hr_factory_execution_benefit_realization_line WHERE realization_id=:i ORDER BY work_center_id'), {'i': realization_id}).mappings().all()
        return {'realization':dict(r),'lines':[dict(x) for x in lines]}

    @app.get('/v90eh/factory-bottleneck/benefit-realizations')
    def listing(request: Request, organization_id: str, entity_id: str, period_start: str, period_end: str):
        _perm(engine, request, 'factory_benefit.view')
        with engine.connect() as c:
            rows = c.execute(text('''SELECT * FROM hr_factory_execution_benefit_realization
                                     WHERE organization_id=:o AND entity_id=:e AND period_start=:s AND period_end=:d
                                     ORDER BY created_at DESC'''), {'o':organization_id,'e':entity_id,'s':period_start,'d':period_end}).mappings().all()
        return [dict(x) for x in rows]

    @app.post('/v90eh/factory-bottleneck/benefit-realizations/{realization_id}/close')
    def close(realization_id: str, request: Request):
        u = _perm(engine, request, 'factory_benefit.close')
        with engine.begin() as c:
            r = c.execute(text('SELECT * FROM hr_factory_execution_benefit_realization WHERE realization_id=:i'), {'i':realization_id}).mappings().first()
            if not r: raise HTTPException(404, 'benefit realization not found')
            if r['closure_status'] == 'CLOSED':
                return {'realization_id':realization_id,'closure_status':'CLOSED','idempotent':True}
            c.execute(text('''UPDATE hr_factory_execution_benefit_realization SET closure_status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP WHERE realization_id=:i'''), {'u':str(u.user_id),'i':realization_id})
        return {'realization_id':realization_id,'closure_status':'CLOSED'}

    @app.get('/ui/factory-execution-benefit-realization')
    def page():
        return FileResponse(Path(__file__).resolve().parents[1] / 'web' / 'factory-execution-benefit-realization.html')

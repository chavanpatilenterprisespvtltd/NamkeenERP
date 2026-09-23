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

def register_v90eb_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for permission_id, permission_name in [
            ('workforce_bottleneck.view', 'View Workforce Bottleneck Analytics'),
            ('workforce_bottleneck.calculate', 'Calculate Workforce Bottleneck Analytics'),
            ('workforce_bottleneck.close', 'Close Workforce Bottleneck Analytics Period'),
        ]:
            c.execute(text('''INSERT INTO erp_permissions(permission_id, permission_name)
                              VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'''),
                      {'p': permission_id, 'n': permission_name})

    @app.post('/v90eb/workforce-bottleneck/calculate')
    def calculate(body: dict, request: Request):
        u = _perm(engine, request, 'workforce_bottleneck.calculate')
        _required(body, 'organization_id', 'entity_id', 'period_start', 'period_end')
        o,e,s,d = body['organization_id'], body['entity_id'], body['period_start'], body['period_end']
        wc = body.get('work_center_id')
        labour_weight = _n(body.get('labour_weight') or 0.50)
        oee_weight = _n(body.get('oee_weight') or 0.50)
        if labour_weight < 0 or oee_weight < 0 or labour_weight + oee_weight <= 0:
            raise HTTPException(400, 'weights must be non-negative and sum to a positive value')
        total = labour_weight + oee_weight
        labour_weight = _n(labour_weight / total); oee_weight = _n(oee_weight / total)
        bottleneck_threshold = _n(body.get('bottleneck_threshold') or 70)
        severe_threshold = _n(body.get('severe_threshold') or 50)
        if severe_threshold > bottleneck_threshold:
            raise HTTPException(400, 'severe_threshold cannot exceed bottleneck_threshold')
        where = 's.organization_id=:o AND s.entity_id=:e AND s.period_start=:s AND s.period_end=:d'
        params = {'o':o,'e':e,'s':s,'d':d}
        if wc:
            where += ' AND s.work_center_id=:w'; params['w']=wc
        sql = f'''
            SELECT s.work_center_id,
                   MAX(s.department_id) AS department_id,
                   MAX(s.product_id) AS product_id,
                   AVG(s.labour_efficiency_pct) AS labour_efficiency_pct,
                   AVG(s.oee_pct) AS oee_pct,
                   AVG(s.combined_efficiency_score) AS combined_efficiency_score,
                   AVG(s.labour_oee_gap) AS labour_oee_gap,
                   SUM(s.labour_hours) AS labour_hours,
                   SUM(s.output_qty) AS output_qty,
                   SUM(s.labour_cost) AS labour_cost,
                   COALESCE((SELECT SUM(r.downtime_minutes) FROM manufacturing_machine_run r
                             WHERE r.organization_id=s.organization_id AND r.entity_id=s.entity_id
                               AND r.work_center_id=s.work_center_id
                               AND DATE(r.created_at) BETWEEN :s AND :d),0) AS downtime_minutes,
                   COALESCE((SELECT SUM(st.duration_minutes) FROM manufacturing_machine_status st
                             WHERE st.organization_id=s.organization_id AND st.entity_id=s.entity_id
                               AND st.work_center_id=s.work_center_id
                               AND DATE(st.event_at) BETWEEN :s AND :d),0) AS status_minutes
            FROM hr_workforce_oee_integration_snapshot s
            WHERE {where}
            GROUP BY s.work_center_id, s.organization_id, s.entity_id
            ORDER BY combined_efficiency_score ASC
        '''
        with engine.connect() as c:
            rows = c.execute(text(sql), params).mappings().all()
        if not rows:
            raise HTTPException(409, 'no workforce + OEE snapshots available for period')
        created=[]
        with engine.begin() as c:
            for idx,row in enumerate(rows, start=1):
                lab=_n(row['labour_efficiency_pct']); oee=_n(row['oee_pct']); score=_n(row['combined_efficiency_score'])
                downtime=_n(row['downtime_minutes']); labour_hours=_n(row['labour_hours']); output=_n(row['output_qty']); cost=_n(row['labour_cost'])
                labour_per_hour=_n(output/labour_hours) if labour_hours else Decimal('0')
                cost_per_unit=_n(cost/output) if output else Decimal('0')
                combined=_n(lab*labour_weight + oee*oee_weight)
                gap=_n(lab-oee)
                downtime_pct=_n(downtime/(downtime+labour_hours*60)*100) if downtime + labour_hours*60 else Decimal('0')
                if combined <= severe_threshold: status='SEVERE_BOTTLENECK'
                elif combined < bottleneck_threshold: status='BOTTLENECK'
                elif combined < 85: status='WATCH'
                else: status='HEALTHY'
                bid=str(uuid4())
                c.execute(text('''INSERT INTO hr_workforce_bottleneck_snapshot(
                    snapshot_id,organization_id,entity_id,period_start,period_end,work_center_id,
                    department_id,product_id,labour_efficiency_pct,oee_pct,combined_efficiency_score,
                    labour_oee_gap,labour_hours,output_qty,labour_cost,output_per_labour_hour,
                    labour_cost_per_unit,downtime_minutes,downtime_pct,rank_no,status,labour_weight,oee_weight,created_by)
                    VALUES(:id,:o,:e,:s,:d,:w,:dept,:p,:le,:oee,:cs,:gap,:lh,:q,:lc,:oph,:cpu,:dm,:dp,:rk,:st,:lw,:ow,:by)
                    ON CONFLICT(organization_id,entity_id,period_start,period_end,work_center_id)
                    DO UPDATE SET department_id=:dept,product_id=:p,labour_efficiency_pct=:le,oee_pct=:oee,
                      combined_efficiency_score=:cs,labour_oee_gap=:gap,labour_hours=:lh,output_qty=:q,
                      labour_cost=:lc,output_per_labour_hour=:oph,labour_cost_per_unit=:cpu,
                      downtime_minutes=:dm,downtime_pct=:dp,rank_no=:rk,status=:st,labour_weight=:lw,
                      oee_weight=:ow,created_by=:by,created_at=CURRENT_TIMESTAMP
                    RETURNING snapshot_id'''),{
                    'id':bid,'o':o,'e':e,'s':s,'d':d,'w':row['work_center_id'],'dept':row['department_id'],'p':row['product_id'],
                    'le':float(lab),'oee':float(oee),'cs':float(combined),'gap':float(gap),'lh':float(labour_hours),'q':float(output),
                    'lc':float(cost),'oph':float(labour_per_hour),'cpu':float(cost_per_unit),'dm':float(downtime),'dp':float(downtime_pct),
                    'rk':idx,'st':status,'lw':float(labour_weight),'ow':float(oee_weight),'by':str(u.user_id)})
                created.append({'work_center_id':row['work_center_id'],'rank':idx,'combined_efficiency_score':float(combined),
                                'labour_efficiency_pct':float(lab),'oee_pct':float(oee),'labour_oee_gap':float(gap),
                                'downtime_minutes':float(downtime),'downtime_pct':float(downtime_pct),'status':status})
        return {'period_start':s,'period_end':d,'rows':created,'status':'CALCULATED'}

    @app.get('/v90eb/workforce-bottleneck')
    def snapshots(request: Request, organization_id: str, entity_id: str, period_start: str, period_end: str,
                  work_center_id: str|None=None):
        _perm(engine, request, 'workforce_bottleneck.view')
        where='organization_id=:o AND entity_id=:e AND period_start=:s AND period_end=:d'; p={'o':organization_id,'e':entity_id,'s':period_start,'d':period_end}
        if work_center_id: where += ' AND work_center_id=:w'; p['w']=work_center_id
        with engine.connect() as c:
            rows=c.execute(text(f'SELECT * FROM hr_workforce_bottleneck_snapshot WHERE {where} ORDER BY rank_no'),p).mappings().all()
        return [dict(r) for r in rows]

    @app.get('/v90eb/workforce-bottleneck/dashboard')
    def dashboard(request: Request, organization_id: str, entity_id: str, period_start: str, period_end: str):
        _perm(engine, request, 'workforce_bottleneck.view')
        with engine.connect() as c:
            row=c.execute(text('''SELECT COUNT(*) rows_count,
                COALESCE(AVG(labour_efficiency_pct),0) labour_efficiency_pct,
                COALESCE(AVG(oee_pct),0) oee_pct,
                COALESCE(AVG(combined_efficiency_score),0) combined_efficiency_score,
                COALESCE(AVG(labour_oee_gap),0) labour_oee_gap,
                COALESCE(SUM(labour_hours),0) labour_hours,
                COALESCE(SUM(output_qty),0) output_qty,
                COALESCE(SUM(labour_cost),0) labour_cost,
                COALESCE(SUM(downtime_minutes),0) downtime_minutes,
                COALESCE(SUM(CASE WHEN status='SEVERE_BOTTLENECK' THEN 1 ELSE 0 END),0) severe_count,
                COALESCE(SUM(CASE WHEN status='BOTTLENECK' THEN 1 ELSE 0 END),0) bottleneck_count,
                COALESCE(SUM(CASE WHEN status='WATCH' THEN 1 ELSE 0 END),0) watch_count,
                COALESCE(SUM(CASE WHEN status='HEALTHY' THEN 1 ELSE 0 END),0) healthy_count
                FROM hr_workforce_bottleneck_snapshot
                WHERE organization_id=:o AND entity_id=:e AND period_start=:s AND period_end=:d'''),
                       {'o':organization_id,'e':entity_id,'s':period_start,'d':period_end}).mappings().first()
        return {k:(int(v or 0) if k.endswith('_count') or k=='rows_count' else float(_n(v))) for k,v in row.items()}

    @app.post('/v90eb/workforce-bottleneck/periods/close')
    def close(body: dict, request: Request):
        u=_perm(engine,request,'workforce_bottleneck.close'); _required(body,'organization_id','entity_id','period_start','period_end')
        with engine.begin() as c:
            n=c.execute(text('''SELECT COUNT(*) FROM hr_workforce_bottleneck_snapshot WHERE organization_id=:o AND entity_id=:e AND period_start=:s AND period_end=:d'''),body).scalar()
            if not n: raise HTTPException(409,'no bottleneck snapshots available for period')
            c.execute(text('''INSERT INTO hr_workforce_bottleneck_close(close_id,organization_id,entity_id,period_start,period_end,status,closed_by)
                             VALUES(:id,:organization_id,:entity_id,:period_start,:period_end,'CLOSED',:u)
                             ON CONFLICT(organization_id,entity_id,period_start,period_end)
                             DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),
                      {**body,'id':str(uuid4()),'u':str(u.user_id)})
        return {'period_start':body['period_start'],'period_end':body['period_end'],'status':'CLOSED'}

    @app.get('/ui/workforce-bottleneck')
    def page():
        return FileResponse(Path(__file__).resolve().parents[1] / 'web' / 'workforce-bottleneck.html')

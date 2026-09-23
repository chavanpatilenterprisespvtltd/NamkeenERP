from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def d(v): return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
def perm(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def valid(pk):
    try:
        y,m=map(int,pk.split('-'))
        if y<2000 or not 1<=m<=12: raise ValueError
    except Exception: raise HTTPException(400,'period_key must be YYYY-MM')

def register_v90er_routes(app: FastAPI,e):
    with e.begin() as c:
        for p,n in [('maintenance_execution_feedback.view','View Maintenance Execution Feedback'),('maintenance_execution_feedback.manage','Calculate Maintenance Execution Feedback'),('maintenance_execution_feedback.close','Close Maintenance Execution Feedback')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_execution_feedback_snapshot(
 feedback_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL, work_center_id TEXT,
 queue_rank INTEGER NOT NULL DEFAULT 0, priority_level TEXT NOT NULL DEFAULT 'LOW', priority_score NUMERIC NOT NULL DEFAULT 0,
 risk_level TEXT NOT NULL DEFAULT 'LOW', risk_score NUMERIC NOT NULL DEFAULT 0, maintenance_orders INTEGER NOT NULL DEFAULT 0,
 intervention_orders INTEGER NOT NULL DEFAULT 0, intervention_events INTEGER NOT NULL DEFAULT 0, responded_orders INTEGER NOT NULL DEFAULT 0,
 response_hours NUMERIC NOT NULL DEFAULT 0, sla_hours NUMERIC NOT NULL DEFAULT 72, sla_compliant_orders INTEGER NOT NULL DEFAULT 0,
 sla_compliance_pct NUMERIC NOT NULL DEFAULT 0, breakdowns_after_intervention INTEGER NOT NULL DEFAULT 0, risk_hits INTEGER NOT NULL DEFAULT 0,
 false_positives INTEGER NOT NULL DEFAULT 0, missed_risks INTEGER NOT NULL DEFAULT 0, repeat_failures INTEGER NOT NULL DEFAULT 0,
 outcome_window_days INTEGER NOT NULL DEFAULT 30, risk_calibration_error NUMERIC NOT NULL DEFAULT 0, outcome_status TEXT NOT NULL DEFAULT 'OBSERVED',
 status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ux_maintenance_execution_feedback_key ON maintenance_execution_feedback_snapshot(organization_id,entity_id,period_key,work_center_id)'))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_execution_feedback_close(close_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_key TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'CLOSED',closed_by TEXT NOT NULL,closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,period_key))'''))

    @app.post('/v90er/maintenance/execution-feedback/snapshot')
    def snapshot(body:dict,request:Request):
        u=perm(e,request,'maintenance_execution_feedback.manage')
        for k in ('organization_id','entity_id','period_key'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        o,ei,pk=body['organization_id'],body['entity_id'],body['period_key']; valid(pk)
        wc=body.get('work_center_id'); sla=float(body.get('sla_hours') or 72); window=int(body.get('outcome_window_days') or 30)
        if sla<=0 or window<=0: raise HTTPException(400,'sla_hours and outcome_window_days must be positive')
        wc_clause=' AND q.work_center_id=:w' if wc else ''
        params={'o':o,'e':ei,'p':pk,'w':wc}
        with e.connect() as c:
            if c.execute(text('SELECT 1 FROM maintenance_execution_feedback_close WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),params).first(): raise HTTPException(409,'period is closed')
            queues=c.execute(text(f'''SELECT q.work_center_id,q.queue_rank,q.priority_level,q.priority_score,r.risk_level,r.risk_score
                FROM maintenance_priority_snapshot q LEFT JOIN maintenance_risk_snapshot r ON r.organization_id=q.organization_id AND r.entity_id=q.entity_id AND r.period_key=q.period_key AND ((r.work_center_id=q.work_center_id) OR (r.work_center_id IS NULL AND q.work_center_id IS NULL))
                WHERE q.organization_id=:o AND q.entity_id=:e AND q.period_key=:p{wc_clause} ORDER BY q.queue_rank'''),params).mappings().all()
            results=[]
            for q in queues:
                w=q['work_center_id']; p2={**params,'w2':w}
                order_clause=' AND mo.work_center_id=:w2' if w else ''
                orders=c.execute(text(f'''SELECT mo.order_id,mo.order_type,mo.scheduled_date FROM maintenance_order mo
                    WHERE mo.organization_id=:o AND mo.entity_id=:e AND CAST(mo.scheduled_date AS TEXT) LIKE :p||'%' {order_clause}'''),p2).mappings().all()
                interventions=0; events=0; responded=0; compliant=0; response_sum=Decimal(0); after=0; repeat=0
                for mo in orders:
                    evs=c.execute(text('''SELECT event_type,event_at FROM maintenance_event WHERE organization_id=:o AND entity_id=:e AND maintenance_order_id=:id ORDER BY event_at'''),{'o':o,'e':ei,'id':mo['order_id']}).mappings().all()
                    ints=[x for x in evs if str(x['event_type']).upper()!='BREAKDOWN']
                    if ints:
                        interventions+=1; events+=len(ints); responded+=1
                        first=ints[0]['event_at']
                        if mo['scheduled_date']:
                            from datetime import datetime
                            def _dt(v):
                                if isinstance(v, datetime): return v
                                return datetime.fromisoformat(str(v).replace('Z',''))
                            diff=(_dt(first)-_dt(mo['scheduled_date'])).total_seconds()/3600.0
                            rh=d(max(0,diff)); response_sum+=rh
                            if float(rh)<=sla: compliant+=1
                        br_events=c.execute(text("SELECT event_at FROM maintenance_event WHERE organization_id=:o AND entity_id=:e AND work_center_id=:w AND event_type='BREAKDOWN'"),{'o':o,'e':ei,'w':w}).scalars().all()
                        if first:
                            first_dt=_dt(first)
                            br=sum(1 for bt in br_events if _dt(bt)>first_dt and _dt(bt)<=first_dt.fromtimestamp(first_dt.timestamp()+window*86400))
                            if br:
                                after+=int(br); repeat+=max(0,int(br)-1)
                morders=len(orders); avg=d(response_sum/responded) if responded else d(0)
                risk=Decimal(str(q['risk_score'] or 0)); priority=str(q['priority_level'] or 'LOW')
                hit=after if priority in ('HIGH','CRITICAL') else 0
                fp=1 if priority in ('HIGH','CRITICAL') and after==0 and responded else 0
                missed=after if priority in ('LOW','MEDIUM') else 0
                # Calibration is an observational absolute error between normalized risk probability proxy and observed event rate.
                observed=d(after/max(1,interventions)*100)
                calib=d(abs(risk-observed))
                results.append((q,morders,interventions,events,responded,response_sum,compliant,after,hit,fp,missed,repeat,avg,calib))
        with e.begin() as c:
            for q,morders,interventions,events,responded,response_sum,compliant,after,hit,fp,missed,repeat,avg,calib in results:
                fid=str(uuid4()); w=q['work_center_id']; avg_resp=float(avg); pct=float(d(Decimal(compliant)/Decimal(responded)*100)) if responded else 0
                c.execute(text('''INSERT INTO maintenance_execution_feedback_snapshot(feedback_id,organization_id,entity_id,period_key,work_center_id,queue_rank,priority_level,priority_score,risk_level,risk_score,maintenance_orders,intervention_orders,intervention_events,responded_orders,response_hours,sla_hours,sla_compliant_orders,sla_compliance_pct,breakdowns_after_intervention,risk_hits,false_positives,missed_risks,repeat_failures,outcome_window_days,risk_calibration_error,outcome_status,status,created_by)
                VALUES(:i,:o,:e,:p,:w,:qr,:pl,:ps,:rl,:rs,:mo,:io,:ie,:ro,:rh,:sla,:sc,:sp,:ba,:hit,:fp,:mr,:rf,:wd,:ce,'OBSERVED','OPEN',:u)
                ON CONFLICT(organization_id,entity_id,period_key,work_center_id) DO UPDATE SET queue_rank=:qr,priority_level=:pl,priority_score=:ps,risk_level=:rl,risk_score=:rs,maintenance_orders=:mo,intervention_orders=:io,intervention_events=:ie,responded_orders=:ro,response_hours=:rh,sla_hours=:sla,sla_compliant_orders=:sc,sla_compliance_pct=:sp,breakdowns_after_intervention=:ba,risk_hits=:hit,false_positives=:fp,missed_risks=:mr,repeat_failures=:rf,outcome_window_days=:wd,risk_calibration_error=:ce,outcome_status='OBSERVED',status='OPEN',created_by=:u,created_at=CURRENT_TIMESTAMP'''),{'i':fid,'o':o,'e':ei,'p':pk,'w':w,'qr':q['queue_rank'],'pl':q['priority_level'],'ps':float(q['priority_score'] or 0),'rl':q['risk_level'] or 'LOW','rs':float(q['risk_score'] or 0),'mo':morders,'io':interventions,'ie':events,'ro':responded,'rh':avg_resp,'sla':sla,'sc':compliant,'sp':pct,'ba':after,'hit':hit,'fp':fp,'mr':missed,'rf':repeat,'wd':window,'ce':float(calib),'u':str(u.user_id)})
        return {'period_key':pk,'count':len(results),'rows':[{'work_center_id':r[0]['work_center_id'],'priority_level':r[0]['priority_level'],'risk_level':r[0]['risk_level'],'responded_orders':r[4],'avg_response_hours':float(r[12]),'sla_compliance_pct':float(d(Decimal(r[6])/Decimal(r[4])*100)) if r[4] else 0,'breakdowns_after_intervention':r[7],'risk_hits':r[8],'false_positives':r[9],'missed_risks':r[10],'repeat_failures':r[11],'risk_calibration_error':float(r[13])} for r in results]}

    @app.get('/v90er/maintenance/execution-feedback/dashboard')
    def dashboard(request:Request,organization_id:str,entity_id:str,period_key:str):
        perm(e,request,'maintenance_execution_feedback.view')
        with e.connect() as c: rows=c.execute(text('SELECT * FROM maintenance_execution_feedback_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY queue_rank'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        return {'count':len(rows),'avg_response_hours':float(d(sum(Decimal(str(r['response_hours'] or 0)) for r in rows)/len(rows))) if rows else 0,'sla_compliance_pct':float(d(sum(Decimal(str(r['sla_compliance_pct'] or 0)) for r in rows)/len(rows))) if rows else 0,'risk_hits':sum(int(r['risk_hits'] or 0) for r in rows),'false_positives':sum(int(r['false_positives'] or 0) for r in rows),'missed_risks':sum(int(r['missed_risks'] or 0) for r in rows),'repeat_failures':sum(int(r['repeat_failures'] or 0) for r in rows),'rows':[dict(r) for r in rows]}

    @app.get('/v90er/maintenance/execution-feedback/calibration')
    def calibration(request:Request,organization_id:str,entity_id:str,period_key:str):
        perm(e,request,'maintenance_execution_feedback.view')
        with e.connect() as c: rows=c.execute(text('SELECT work_center_id,risk_score,risk_level,priority_level,risk_calibration_error,breakdowns_after_intervention,risk_hits,false_positives,missed_risks FROM maintenance_execution_feedback_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY risk_calibration_error DESC'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        return {'count':len(rows),'calibration_is_observational':True,'rows':[dict(r) for r in rows]}

    @app.get('/v90er/maintenance/execution-feedback/trend')
    def trend(request:Request,organization_id:str,entity_id:str,work_center_id:str|None=None,limit:int=12):
        perm(e,request,'maintenance_execution_feedback.view'); limit=max(1,min(36,limit)); params={'o':organization_id,'e':entity_id,'limit':limit}; clause=''
        if work_center_id: clause=' AND work_center_id=:w'; params['w']=work_center_id
        with e.connect() as c: rows=c.execute(text(f'''SELECT period_key,work_center_id,avg(response_hours) AS response_hours,avg(sla_compliance_pct) AS sla_compliance_pct,sum(risk_hits) AS risk_hits,sum(false_positives) AS false_positives,sum(missed_risks) AS missed_risks,sum(repeat_failures) AS repeat_failures FROM maintenance_execution_feedback_snapshot WHERE organization_id=:o AND entity_id=:e{clause} GROUP BY period_key,work_center_id ORDER BY period_key DESC LIMIT :limit'''),params).mappings().all()
        return {'count':len(rows),'trend':[dict(r) for r in rows]}

    @app.post('/v90er/maintenance/execution-feedback/{period_key}/close')
    def close(period_key:str,body:dict,request:Request):
        u=perm(e,request,'maintenance_execution_feedback.close'); valid(period_key)
        if not body.get('organization_id') or not body.get('entity_id'): raise HTTPException(400,'organization_id and entity_id are required')
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_execution_feedback_close(close_id,organization_id,entity_id,period_key,closed_by) VALUES(:i,:o,:e,:p,:u) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),{'i':str(uuid4()),'o':body['organization_id'],'e':body['entity_id'],'p':period_key,'u':str(u.user_id)})
            c.execute(text('UPDATE maintenance_execution_feedback_snapshot SET status=\'CLOSED\' WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':body['organization_id'],'e':body['entity_id'],'p':period_key})
        return {'period_key':period_key,'status':'CLOSED'}

    @app.get('/ui/maintenance-execution-feedback')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-execution-feedback.html')

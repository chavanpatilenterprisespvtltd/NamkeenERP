from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def d(v):
    return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def perm(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def valid(pk):
    try:
        y,m=map(int,pk.split('-'))
        if y<2000 or not 1<=m<=12: raise ValueError
    except Exception: raise HTTPException(400,'period_key must be YYYY-MM')

def pct_gap(target,actual):
    t=d(target); a=d(actual)
    return d(a-t) if t else d(a)

def score_target_met(target,actual):
    return d(actual) >= d(target)

def effectiveness_status(score,target,repeat,rollback):
    failed = d(score) < d(target) or int(repeat or 0)>0
    if str(rollback or '').upper() in ('REQUESTED','COMPLETED'):
        failed = True
    if failed: return 'FAILED_CHANGE'
    if d(score) >= d(target): return 'TARGET_MET'
    return 'REVIEW_REQUIRED'

def recommendation(status,repeat,rollback):
    if str(rollback or '').upper()=='COMPLETED': return 'VALIDATE_ROLLBACK_AND_REASSESS'
    if str(rollback or '').upper()=='REQUESTED': return 'REVIEW_ROLLBACK'
    if int(repeat or 0)>0: return 'REVIEW_REPEAT_FAILURE'
    if status=='FAILED_CHANGE': return 'REVIEW_OR_REVISE'
    return 'CONTINUE_AND_MONITOR'

def register_v90ew_routes(app:FastAPI,e):
    with e.begin() as c:
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_change_effectiveness_snapshot(
            effectiveness_id TEXT PRIMARY KEY, implementation_id TEXT NOT NULL, proposal_id TEXT,
            organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            work_center_id TEXT, target_effectiveness_score NUMERIC NOT NULL DEFAULT 60,
            actual_effectiveness_score NUMERIC NOT NULL DEFAULT 0,
            target_breakdown_reduction_pct NUMERIC NOT NULL DEFAULT 0,
            actual_breakdown_reduction_pct NUMERIC NOT NULL DEFAULT 0,
            target_downtime_reduction_hours NUMERIC NOT NULL DEFAULT 0,
            actual_downtime_reduction_hours NUMERIC NOT NULL DEFAULT 0,
            target_maintenance_cost_impact NUMERIC NOT NULL DEFAULT 0,
            actual_maintenance_cost_impact NUMERIC NOT NULL DEFAULT 0,
            effectiveness_variance NUMERIC NOT NULL DEFAULT 0,
            target_met INTEGER NOT NULL DEFAULT 0, repeat_failure_count INTEGER NOT NULL DEFAULT 0,
            rollback_status TEXT NOT NULL DEFAULT 'NOT_REQUESTED', pm_revision_status TEXT,
            failure_flag INTEGER NOT NULL DEFAULT 0, recommendation TEXT, status TEXT NOT NULL DEFAULT 'ASSESSED',
            created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(implementation_id))'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_change_effectiveness_scope ON maintenance_reliability_change_effectiveness_snapshot(organization_id,entity_id,period_key,work_center_id,status,failure_flag)'))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_improvement_feedback(
            feedback_id TEXT PRIMARY KEY, effectiveness_id TEXT NOT NULL, organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL, period_key TEXT NOT NULL, work_center_id TEXT, feedback_type TEXT NOT NULL,
            recommendation TEXT NOT NULL, rationale TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'MEDIUM',
            status TEXT NOT NULL DEFAULT 'PROPOSED', linked_governance_proposal_id TEXT,
            approved_by TEXT, approved_at TIMESTAMP, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(effectiveness_id,feedback_type))'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_improvement_feedback_scope ON maintenance_reliability_improvement_feedback(organization_id,entity_id,period_key,status,priority)'))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_change_effectiveness_close(
            close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'CLOSED', closed_by TEXT NOT NULL, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key))'''))
        for p,n in [('maintenance_reliability_change_effectiveness.view','View Reliability Change Effectiveness'),('maintenance_reliability_change_effectiveness.manage','Manage Reliability Change Effectiveness'),('maintenance_reliability_change_effectiveness.feedback','Manage Reliability Improvement Feedback'),('maintenance_reliability_change_effectiveness.close','Close Reliability Change Effectiveness')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})

    @app.post('/v90ew/maintenance/reliability-change/effectiveness/snapshot')
    def snapshot(body:dict,request:Request):
        u=perm(e,request,'maintenance_reliability_change_effectiveness.manage')
        o,ei,pk=body.get('organization_id'),body.get('entity_id'),body.get('period_key')
        if not o or not ei or not pk: raise HTTPException(400,'organization_id, entity_id and period_key are required')
        valid(pk)
        with e.begin() as c:
            if c.execute(text('SELECT 1 FROM maintenance_reliability_change_effectiveness_close WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':pk}).first(): raise HTTPException(409,'period is closed')
            gov=c.execute(text('SELECT * FROM maintenance_reliability_governance_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':pk}).mappings().first()
            g=gov or {'target_effectiveness_score':60,'target_breakdown_reduction_pct':0,'target_downtime_reduction_hours':0,'target_maintenance_cost_impact':0}
            impls=c.execute(text('''SELECT i.*, p.work_center_id AS proposal_work_center_id
                FROM maintenance_reliability_change_implementation i
                LEFT JOIN maintenance_reliability_change_proposal p ON p.proposal_id=i.proposal_id
                WHERE i.organization_id=:o AND i.entity_id=:e AND i.period_key=:p AND i.implementation_status='IMPLEMENTED'
                ORDER BY i.created_at'''),{'o':o,'e':ei,'p':pk}).mappings().all()
            assessed=[]; failures=0; feedback_created=0
            for i in impls:
                rev=c.execute(text('SELECT status,rollback_status,work_center_id FROM maintenance_reliability_plan_change_revision WHERE implementation_id=:i'),{'i':i['implementation_id']}).mappings().first()
                repeat=int(c.execute(text('''SELECT COUNT(*) FROM maintenance_event WHERE organization_id=:o AND entity_id=:e AND event_type='BREAKDOWN' AND CAST(event_at AS TEXT) LIKE :p AND (:w IS NULL OR work_center_id=:w)'''),{'o':o,'e':ei,'p':pk+'%','w':(rev['work_center_id'] if rev else i['proposal_work_center_id'])}).scalar() or 0)
                target=d(g['target_effectiveness_score']); actual=d(i['effectiveness_score']); st=effectiveness_status(actual,target,repeat,rev['rollback_status'] if rev else 'NOT_REQUESTED')
                fail=1 if st=='FAILED_CHANGE' else 0
                if fail: failures+=1
                wc=(rev['work_center_id'] if rev else None) or i['proposal_work_center_id']
                c.execute(text('''INSERT INTO maintenance_reliability_change_effectiveness_snapshot(effectiveness_id,implementation_id,proposal_id,organization_id,entity_id,period_key,work_center_id,target_effectiveness_score,actual_effectiveness_score,target_breakdown_reduction_pct,actual_breakdown_reduction_pct,target_downtime_reduction_hours,actual_downtime_reduction_hours,target_maintenance_cost_impact,actual_maintenance_cost_impact,effectiveness_variance,target_met,repeat_failure_count,rollback_status,pm_revision_status,failure_flag,recommendation,status,created_by) VALUES(:id,:i,:p,:o,:e,:pk,:w,:ts,:as,:tb,:ab,:td,:ad,:tc,:ac,:v,:tm,:rf,:rb,:prs,:ff,:rec,'ASSESSED',:u) ON CONFLICT(implementation_id) DO UPDATE SET target_effectiveness_score=:ts,actual_effectiveness_score=:as,target_breakdown_reduction_pct=:tb,actual_breakdown_reduction_pct=:ab,target_downtime_reduction_hours=:td,actual_downtime_reduction_hours=:ad,target_maintenance_cost_impact=:tc,actual_maintenance_cost_impact=:ac,effectiveness_variance=:v,target_met=:tm,repeat_failure_count=:rf,rollback_status=:rb,pm_revision_status=:prs,failure_flag=:ff,recommendation=:rec,created_by=:u,created_at=CURRENT_TIMESTAMP'''),{'id':str(uuid4()),'i':i['implementation_id'],'p':i['proposal_id'],'o':o,'e':ei,'pk':pk,'w':wc,'ts':float(target),'as':float(actual),'tb':float(g['target_breakdown_reduction_pct'] or 0),'ab':float(i['breakdown_reduction_pct'] or 0),'td':float(g['target_downtime_reduction_hours'] or 0),'ad':float(i['downtime_reduction_hours'] or 0),'tc':float(g['target_maintenance_cost_impact'] or 0),'ac':float(i['maintenance_cost_impact'] or 0),'v':float(actual-target),'tm':1 if score_target_met(target,actual) and repeat==0 and str(rev['rollback_status'] if rev else '').upper() not in ('REQUESTED','COMPLETED') else 0,'rf':repeat,'rb':rev['rollback_status'] if rev else 'NOT_REQUESTED','prs':rev['status'] if rev else None,'ff':fail,'rec':recommendation(st,repeat,rev['rollback_status'] if rev else 'NOT_REQUESTED'),'u':str(u.user_id)})
                if fail:
                    ftype='FAILED_CHANGE' if repeat==0 else 'REPEAT_FAILURE'
                    c.execute(text('''INSERT INTO maintenance_reliability_improvement_feedback(feedback_id,effectiveness_id,organization_id,entity_id,period_key,work_center_id,feedback_type,recommendation,rationale,priority,created_by) VALUES(:id,:ef,:o,:e,:p,:w,:t,:r,:ra,:pr,:u) ON CONFLICT(effectiveness_id,feedback_type) DO UPDATE SET recommendation=:r,rationale=:ra,priority=:pr,status='PROPOSED' '''),{'id':str(uuid4()),'ef':i['implementation_id'],'o':o,'e':ei,'p':pk,'w':wc,'t':ftype,'r':recommendation(st,repeat,rev['rollback_status'] if rev else 'NOT_REQUESTED'),'ra':f'Observed effectiveness {actual} versus target {target}; repeat failures={repeat}.','pr':'HIGH','u':str(u.user_id)})
                    feedback_created+=1
                assessed.append(actual)
        return {'period_key':pk,'assessed_count':len(assessed),'failed_change_count':failures,'feedback_created_or_refreshed':feedback_created,'causal_attribution':False}

    @app.get('/v90ew/maintenance/reliability-change/effectiveness/dashboard')
    def dashboard(request:Request,organization_id:str,entity_id:str,period_key:str):
        perm(e,request,'maintenance_reliability_change_effectiveness.view'); valid(period_key)
        with e.connect() as c:
            rows=c.execute(text('SELECT * FROM maintenance_reliability_change_effectiveness_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY created_at DESC'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
            fb=c.execute(text('SELECT * FROM maintenance_reliability_improvement_feedback WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY created_at DESC'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        by_wc={}
        for x in rows:
            k=x['work_center_id'] or 'UNSPECIFIED'; by_wc.setdefault(k,[]).append(x)
        wc=[]
        for k,v in by_wc.items(): wc.append({'work_center_id':k,'change_count':len(v),'target_met_count':sum(int(x['target_met']) for x in v),'failed_change_count':sum(int(x['failure_flag']) for x in v),'avg_effectiveness_score':float(d(sum(Decimal(str(x['actual_effectiveness_score'] or 0)) for x in v)/len(v)))})
        return {'implementation_count':len(rows),'target_met_count':sum(int(x['target_met']) for x in rows),'failed_change_count':sum(int(x['failure_flag']) for x in rows),'repeat_failure_count':sum(int(x['repeat_failure_count'] or 0) for x in rows),'rollback_requested_count':sum(1 for x in rows if str(x['rollback_status']).upper()=='REQUESTED'),'open_feedback_count':sum(1 for x in fb if str(x['status']).upper() in ('PROPOSED','OPEN')),'avg_effectiveness_score':float(d(sum(Decimal(str(x['actual_effectiveness_score'] or 0)) for x in rows)/len(rows))) if rows else 0,'by_work_center':wc,'rows':[dict(x) for x in rows],'feedback':[dict(x) for x in fb],'causal_attribution':False}

    @app.get('/v90ew/maintenance/reliability-change/effectiveness/queue')
    def queue(request:Request,organization_id:str,entity_id:str,period_key:str):
        perm(e,request,'maintenance_reliability_change_effectiveness.view'); valid(period_key)
        with e.connect() as c:
            rows=c.execute(text('SELECT * FROM maintenance_reliability_improvement_feedback WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status IN (\'PROPOSED\',\'OPEN\') ORDER BY CASE priority WHEN \'CRITICAL\' THEN 1 WHEN \'HIGH\' THEN 2 WHEN \'MEDIUM\' THEN 3 ELSE 4 END,created_at'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        return {'count':len(rows),'queue':[dict(x) for x in rows]}

    @app.post('/v90ew/maintenance/reliability-change/effectiveness/{effectiveness_id}/feedback')
    def feedback(effectiveness_id:str,body:dict,request:Request):
        u=perm(e,request,'maintenance_reliability_change_effectiveness.feedback')
        typ=str(body.get('feedback_type') or 'MANAGEMENT_REVIEW').upper(); rec=str(body.get('recommendation') or '').strip(); rat=str(body.get('rationale') or '').strip()
        if not rec or not rat: raise HTTPException(400,'recommendation and rationale are required')
        with e.begin() as c:
            x=c.execute(text('SELECT * FROM maintenance_reliability_change_effectiveness_snapshot WHERE effectiveness_id=:i'),{'i':effectiveness_id}).mappings().first()
            if not x: raise HTTPException(404,'effectiveness record not found')
            fid=str(uuid4()); c.execute(text('''INSERT INTO maintenance_reliability_improvement_feedback(feedback_id,effectiveness_id,organization_id,entity_id,period_key,work_center_id,feedback_type,recommendation,rationale,priority,created_by) VALUES(:id,:ef,:o,:e,:p,:w,:t,:r,:ra,:pr,:u) ON CONFLICT(effectiveness_id,feedback_type) DO UPDATE SET recommendation=:r,rationale=:ra,priority=:pr,status='PROPOSED',created_by=:u'''),{'id':fid,'ef':effectiveness_id,'o':x['organization_id'],'e':x['entity_id'],'p':x['period_key'],'w':x['work_center_id'],'t':typ,'r':rec,'ra':rat,'pr':str(body.get('priority') or 'MEDIUM').upper(),'u':str(u.user_id)})
        return {'effectiveness_id':effectiveness_id,'feedback_type':typ,'status':'PROPOSED'}

    @app.post('/v90ew/maintenance/reliability-change/effectiveness/feedback/{feedback_id}/governance-proposal')
    def governance_proposal(feedback_id:str,body:dict,request:Request):
        u=perm(e,request,'maintenance_reliability_change_effectiveness.feedback')
        with e.begin() as c:
            f=c.execute(text('SELECT * FROM maintenance_reliability_improvement_feedback WHERE feedback_id=:i'),{'i':feedback_id}).mappings().first()
            if not f: raise HTTPException(404,'feedback not found')
            if f['linked_governance_proposal_id']: return {'feedback_id':feedback_id,'governance_proposal_id':f['linked_governance_proposal_id'],'status':'ALREADY_LINKED'}
            pid=str(uuid4()); c.execute(text('''INSERT INTO maintenance_reliability_change_proposal(proposal_id,organization_id,entity_id,period_key,work_center_id,change_type,proposed_change,rationale,target_value,owner_user_id,due_date,status,created_by) VALUES(:i,:o,:e,:p,:w,:t,:c,:r,:v,:owner,:due,'PROPOSED',:u)'''),{'i':pid,'o':f['organization_id'],'e':f['entity_id'],'p':f['period_key'],'w':f['work_center_id'],'t':f['feedback_type'],'c':f['recommendation'],'r':f['rationale'],'v':body.get('target_value'),'owner':body.get('owner_user_id'),'due':body.get('due_date'),'u':str(u.user_id)})
            c.execute(text("UPDATE maintenance_reliability_improvement_feedback SET linked_governance_proposal_id=:p,status='LINKED' WHERE feedback_id=:i"),{'p':pid,'i':feedback_id})
        return {'feedback_id':feedback_id,'governance_proposal_id':pid,'status':'LINKED','governance_approval_required':True}

    @app.post('/v90ew/maintenance/reliability-change/{period_key}/close')
    def close(period_key:str,body:dict,request:Request):
        u=perm(e,request,'maintenance_reliability_change_effectiveness.close'); valid(period_key); o,ei=body.get('organization_id'),body.get('entity_id')
        if not o or not ei: raise HTTPException(400,'organization_id and entity_id are required')
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_reliability_change_effectiveness_close(close_id,organization_id,entity_id,period_key,closed_by) VALUES(:i,:o,:e,:p,:u) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),{'i':str(uuid4()),'o':o,'e':ei,'p':period_key,'u':str(u.user_id)})
        return {'period_key':period_key,'status':'CLOSED'}

    @app.get('/ui/maintenance-reliability-change-effectiveness')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-reliability-change-effectiveness.html')

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
def prev_period(pk):
    y,m=map(int,pk.split('-')); return f'{y-1}-12' if m==1 else f'{y:04d}-{m-1:02d}'

def register_v90ey_routes(app:FastAPI,e):
    with e.begin() as c:
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_continuous_improvement_snapshot(
            learning_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            prior_period_key TEXT, current_control_score NUMERIC NOT NULL DEFAULT 0, prior_control_score NUMERIC NOT NULL DEFAULT 0,
            control_score_delta NUMERIC NOT NULL DEFAULT 0, current_effectiveness_score NUMERIC NOT NULL DEFAULT 0,
            prior_effectiveness_score NUMERIC NOT NULL DEFAULT 0, effectiveness_delta NUMERIC NOT NULL DEFAULT 0,
            current_target_met_pct NUMERIC NOT NULL DEFAULT 0, prior_target_met_pct NUMERIC NOT NULL DEFAULT 0,
            target_met_delta NUMERIC NOT NULL DEFAULT 0, current_failed_change_count INTEGER NOT NULL DEFAULT 0,
            prior_failed_change_count INTEGER NOT NULL DEFAULT 0, recurring_failure_count INTEGER NOT NULL DEFAULT 0,
            recurring_failure_flag INTEGER NOT NULL DEFAULT 0, improvement_assessment TEXT NOT NULL DEFAULT 'NO_BASELINE',
            recommendation TEXT, status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key))'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_continuous_improvement_scope ON maintenance_reliability_continuous_improvement_snapshot(organization_id,entity_id,period_key,status,recurring_failure_flag)'))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_continuous_improvement_feedback(
            feedback_id TEXT PRIMARY KEY, learning_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            period_key TEXT NOT NULL, prior_period_key TEXT, feedback_type TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'MEDIUM',
            recommendation TEXT NOT NULL, rationale TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PROPOSED',
            linked_governance_proposal_id TEXT, owner_user_id TEXT, due_date DATE, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(learning_id,feedback_type))'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_continuous_feedback_scope ON maintenance_reliability_continuous_improvement_feedback(organization_id,entity_id,period_key,status,priority)'))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_continuous_improvement_close(
            close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'CLOSED', unresolved_feedback_count INTEGER NOT NULL DEFAULT 0,
            closed_by TEXT NOT NULL, closure_note TEXT, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key))'''))
        for p,n in [('maintenance_reliability_continuous_improvement.view','View Continuous Reliability Improvement'),('maintenance_reliability_continuous_improvement.manage','Manage Continuous Reliability Improvement'),('maintenance_reliability_continuous_improvement.feedback','Manage Continuous Improvement Feedback'),('maintenance_reliability_continuous_improvement.close','Close Continuous Improvement Period')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})

    @app.post('/v90ey/maintenance/reliability-improvement/learning/snapshot')
    def snapshot(body:dict,request:Request):
        u=perm(e,request,'maintenance_reliability_continuous_improvement.manage')
        o,ei,pk=body.get('organization_id'),body.get('entity_id'),body.get('period_key'); pp=body.get('prior_period_key') or prev_period(pk or '2000-02')
        if not o or not ei or not pk: raise HTTPException(400,'organization_id, entity_id and period_key are required')
        valid(pk); valid(pp)
        with e.begin() as c:
            if c.execute(text('SELECT 1 FROM maintenance_reliability_continuous_improvement_close WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':pk}).first(): raise HTTPException(409,'period is closed')
            cur=c.execute(text('SELECT * FROM maintenance_reliability_executive_control_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':pk}).mappings().first()
            old=c.execute(text('SELECT * FROM maintenance_reliability_executive_control_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':pp}).mappings().first()
            ce=cur or {}; pe=old or {}
            cur_eff=d(ce.get('effectiveness_score')); old_eff=d(pe.get('effectiveness_score')); cur_cs=d(ce.get('control_score')); old_cs=d(pe.get('control_score')); cur_tm=d(ce.get('target_met_pct')); old_tm=d(pe.get('target_met_pct'))
            cur_fail=int(ce.get('failed_change_count') or 0); old_fail=int(pe.get('failed_change_count') or 0)
            # Recurrence is based on open/failed feedback in both periods, not causal attribution.
            curfb=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_improvement_feedback WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status IN ('PROPOSED','OPEN')"),{'o':o,'e':ei,'p':pk}).scalar() or 0
            oldfb=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_improvement_feedback WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status IN ('PROPOSED','OPEN')"),{'o':o,'e':ei,'p':pp}).scalar() or 0
            recurring=max(0,min(int(curfb),int(oldfb))) if curfb and oldfb else (1 if cur_fail>0 and old_fail>0 else 0)
            if not old: assessment='NO_BASELINE'; rec='Establish the first closed-period baseline and retain evidence for the next comparison.'
            elif cur_cs>old_cs and cur_eff>=old_eff and cur_fail<=old_fail: assessment='IMPROVING'; rec='Continue the effective controls and carry successful practices into the next governance review.'
            elif cur_fail>old_fail or cur_eff<old_eff or recurring: assessment='DETERIORATING'; rec='Open a management review for recurring or deteriorating reliability outcomes.'
            else: assessment='STABLE'; rec='Maintain controls and review the next period for meaningful movement.'
            rf=1 if recurring else 0
            lid=str(uuid4())
            c.execute(text('''INSERT INTO maintenance_reliability_continuous_improvement_snapshot(learning_id,organization_id,entity_id,period_key,prior_period_key,current_control_score,prior_control_score,control_score_delta,current_effectiveness_score,prior_effectiveness_score,effectiveness_delta,current_target_met_pct,prior_target_met_pct,target_met_delta,current_failed_change_count,prior_failed_change_count,recurring_failure_count,recurring_failure_flag,improvement_assessment,recommendation,status,created_by) VALUES(:id,:o,:e,:p,:pp,:cc,:pc,:cd,:ce,:pe,:ed,:ct,:pt,:td,:cf,:pf,:rf,:rff,:a,:r,'OPEN',:u) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET prior_period_key=:pp,current_control_score=:cc,prior_control_score=:pc,control_score_delta=:cd,current_effectiveness_score=:ce,prior_effectiveness_score=:pe,effectiveness_delta=:ed,current_target_met_pct=:ct,prior_target_met_pct=:pt,target_met_delta=:td,current_failed_change_count=:cf,prior_failed_change_count=:pf,recurring_failure_count=:rf,recurring_failure_flag=:rff,improvement_assessment=:a,recommendation=:r,created_by=:u,created_at=CURRENT_TIMESTAMP'''),{'id':lid,'o':o,'e':ei,'p':pk,'pp':pp,'cc':float(cur_cs),'pc':float(old_cs),'cd':float(cur_cs-old_cs),'ce':float(cur_eff),'pe':float(old_eff),'ed':float(cur_eff-old_eff),'ct':float(cur_tm),'pt':float(old_tm),'td':float(cur_tm-old_tm),'cf':cur_fail,'pf':old_fail,'rf':recurring,'rff':rf,'a':assessment,'r':rec,'u':str(u.user_id)})
            if assessment in ('DETERIORATING','STABLE') and (cur_fail>0 or recurring):
                typ='RECURRING_FAILURE' if recurring else 'PERFORMANCE_DETERIORATION'; pr='CRITICAL' if recurring else 'HIGH'
                c.execute(text('''INSERT INTO maintenance_reliability_continuous_improvement_feedback(feedback_id,learning_id,organization_id,entity_id,period_key,prior_period_key,feedback_type,priority,recommendation,rationale,created_by) VALUES(:id,:l,:o,:e,:p,:pp,:t,:pr,:r,:ra,:u) ON CONFLICT(learning_id,feedback_type) DO UPDATE SET priority=:pr,recommendation=:r,rationale=:ra,status='PROPOSED',created_by=:u'''),{'id':str(uuid4()),'l':lid,'o':o,'e':ei,'p':pk,'pp':pp,'t':typ,'pr':pr,'r':rec,'ra':f'Current vs prior: control {cur_cs} vs {old_cs}; effectiveness {cur_eff} vs {old_eff}; failed changes {cur_fail} vs {old_fail}.','u':str(u.user_id)})
        return {'learning_id':lid,'period_key':pk,'prior_period_key':pp,'assessment':assessment,'control_score_delta':float(cur_cs-old_cs),'effectiveness_delta':float(cur_eff-old_eff),'target_met_delta':float(cur_tm-old_tm),'recurring_failure_count':recurring,'causal_attribution':False}

    @app.get('/v90ey/maintenance/reliability-improvement/dashboard')
    def dashboard(request:Request,organization_id:str,entity_id:str,period_key:str):
        perm(e,request,'maintenance_reliability_continuous_improvement.view'); valid(period_key)
        with e.connect() as c:
            s=c.execute(text('SELECT * FROM maintenance_reliability_continuous_improvement_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().first()
            fb=c.execute(text('SELECT * FROM maintenance_reliability_continuous_improvement_feedback WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY CASE priority WHEN \'CRITICAL\' THEN 1 WHEN \'HIGH\' THEN 2 ELSE 3 END,created_at DESC'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
            hist=c.execute(text('SELECT period_key,improvement_assessment,control_score_delta,effectiveness_delta,target_met_delta,recurring_failure_flag FROM maintenance_reliability_continuous_improvement_snapshot WHERE organization_id=:o AND entity_id=:e ORDER BY period_key'),{'o':organization_id,'e':entity_id}).mappings().all()
        return {'snapshot':dict(s) if s else None,'feedback':[dict(x) for x in fb],'history':[dict(x) for x in hist],'open_feedback_count':sum(1 for x in fb if str(x['status']).upper() in ('PROPOSED','OPEN')),'causal_attribution':False}

    @app.get('/v90ey/maintenance/reliability-improvement/feedback')
    def feedback_queue(request:Request,organization_id:str,entity_id:str,period_key:str):
        perm(e,request,'maintenance_reliability_continuous_improvement.view'); valid(period_key)
        with e.connect() as c: rows=c.execute(text("SELECT * FROM maintenance_reliability_continuous_improvement_feedback WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status IN ('PROPOSED','OPEN') ORDER BY CASE priority WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 ELSE 3 END,created_at"),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        return {'count':len(rows),'queue':[dict(x) for x in rows]}

    @app.post('/v90ey/maintenance/reliability-improvement/feedback/{feedback_id}/governance-proposal')
    def to_governance(feedback_id:str,body:dict,request:Request):
        u=perm(e,request,'maintenance_reliability_continuous_improvement.feedback')
        with e.begin() as c:
            f=c.execute(text('SELECT * FROM maintenance_reliability_continuous_improvement_feedback WHERE feedback_id=:i'),{'i':feedback_id}).mappings().first()
            if not f: raise HTTPException(404,'feedback not found')
            if f['linked_governance_proposal_id']: return {'feedback_id':feedback_id,'governance_proposal_id':f['linked_governance_proposal_id'],'status':'ALREADY_LINKED'}
            pid=str(uuid4()); c.execute(text('''INSERT INTO maintenance_reliability_change_proposal(proposal_id,organization_id,entity_id,period_key,work_center_id,change_type,proposed_change,rationale,target_value,owner_user_id,due_date,status,created_by) VALUES(:i,:o,:e,:p,NULL,:t,:c,:r,:v,:owner,:due,'PROPOSED',:u)'''),{'i':pid,'o':f['organization_id'],'e':f['entity_id'],'p':f['period_key'],'t':f['feedback_type'],'c':f['recommendation'],'r':f['rationale'],'v':body.get('target_value'),'owner':body.get('owner_user_id'),'due':body.get('due_date'),'u':str(u.user_id)})
            c.execute(text("UPDATE maintenance_reliability_continuous_improvement_feedback SET linked_governance_proposal_id=:p,status='LINKED' WHERE feedback_id=:i"),{'p':pid,'i':feedback_id})
        return {'feedback_id':feedback_id,'governance_proposal_id':pid,'status':'LINKED','governance_approval_required':True}

    @app.post('/v90ey/maintenance/reliability-improvement/{period_key}/close')
    def close(period_key:str,body:dict,request:Request):
        u=perm(e,request,'maintenance_reliability_continuous_improvement.close'); valid(period_key); o,ei=body.get('organization_id'),body.get('entity_id')
        if not o or not ei: raise HTTPException(400,'organization_id and entity_id are required')
        with e.begin() as c:
            unresolved=int(c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_continuous_improvement_feedback WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status IN ('PROPOSED','OPEN')"),{'o':o,'e':ei,'p':period_key}).scalar() or 0)
            if unresolved and not body.get('force'): raise HTTPException(409,f'{unresolved} unresolved feedback item(s); resolve/link or use force=true')
            c.execute(text('''INSERT INTO maintenance_reliability_continuous_improvement_close(close_id,organization_id,entity_id,period_key,status,unresolved_feedback_count,closed_by,closure_note) VALUES(:i,:o,:e,:p,'CLOSED',:x,:u,:n) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET status='CLOSED',unresolved_feedback_count=:x,closed_by=:u,closure_note=:n,closed_at=CURRENT_TIMESTAMP'''),{'i':str(uuid4()),'o':o,'e':ei,'p':period_key,'x':unresolved,'u':str(u.user_id),'n':body.get('closure_note')})
        return {'period_key':period_key,'status':'CLOSED','unresolved_feedback_count':unresolved,'forced':bool(body.get('force'))}

    @app.get('/ui/maintenance-reliability-improvement')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-reliability-improvement.html')

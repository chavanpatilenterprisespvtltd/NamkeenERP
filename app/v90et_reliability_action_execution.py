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

def register_v90et_routes(app: FastAPI,e):
    with e.begin() as c:
        for p,n in [('maintenance_reliability_action_execution.view','View Reliability Action Execution'),('maintenance_reliability_action_execution.manage','Manage Reliability Action Execution'),('maintenance_reliability_action_execution.execute','Execute Reliability Actions'),('maintenance_reliability_action_execution.close','Close Reliability Action Execution')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':p})
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_action_execution(execution_id TEXT PRIMARY KEY,action_id TEXT NOT NULL,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_key TEXT NOT NULL,work_center_id TEXT,action_type TEXT NOT NULL,recommendation TEXT NOT NULL,owner_user_id TEXT,due_date DATE,status TEXT NOT NULL DEFAULT 'OPEN',execution_note TEXT,executed_by TEXT,executed_at TIMESTAMP,baseline_period_key TEXT,baseline_breakdown_orders INTEGER NOT NULL DEFAULT 0,baseline_breakdown_hours NUMERIC NOT NULL DEFAULT 0,baseline_maintenance_cost NUMERIC NOT NULL DEFAULT 0,current_breakdown_orders INTEGER NOT NULL DEFAULT 0,current_breakdown_hours NUMERIC NOT NULL DEFAULT 0,current_maintenance_cost NUMERIC NOT NULL DEFAULT 0,breakdown_reduction_pct NUMERIC NOT NULL DEFAULT 0,downtime_reduction_hours NUMERIC NOT NULL DEFAULT 0,maintenance_cost_impact NUMERIC NOT NULL DEFAULT 0,effectiveness_score NUMERIC NOT NULL DEFAULT 0,benefit_status TEXT NOT NULL DEFAULT 'NOT_ASSESSED',created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(action_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_benefit_snapshot(benefit_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_key TEXT NOT NULL,baseline_period_key TEXT NOT NULL,work_center_id TEXT,breakdown_orders_baseline INTEGER NOT NULL DEFAULT 0,breakdown_orders_current INTEGER NOT NULL DEFAULT 0,breakdown_hours_baseline NUMERIC NOT NULL DEFAULT 0,breakdown_hours_current NUMERIC NOT NULL DEFAULT 0,maintenance_cost_baseline NUMERIC NOT NULL DEFAULT 0,maintenance_cost_current NUMERIC NOT NULL DEFAULT 0,breakdown_reduction_pct NUMERIC NOT NULL DEFAULT 0,downtime_reduction_hours NUMERIC NOT NULL DEFAULT 0,maintenance_cost_impact NUMERIC NOT NULL DEFAULT 0,effectiveness_score NUMERIC NOT NULL DEFAULT 0,assessment TEXT NOT NULL DEFAULT 'NO_IMPROVEMENT_OBSERVED',status TEXT NOT NULL DEFAULT 'OPEN',created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,period_key,baseline_period_key,work_center_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_action_execution_close(close_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_key TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'CLOSED',closed_by TEXT NOT NULL,closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,period_key))'''))

    @app.post('/v90et/maintenance/reliability-actions/execute')
    def execute(body:dict,request:Request):
        u=perm(e,request,'maintenance_reliability_action_execution.execute')
        for k in ('action_id','organization_id','entity_id','period_key'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        o,ei,pk=body['organization_id'],body['entity_id'],body['period_key']; valid(pk)
        status=str(body.get('status') or 'IN_PROGRESS').upper()
        if status not in ('IN_PROGRESS','COMPLETED','CANCELLED'): raise HTTPException(400,'status must be IN_PROGRESS, COMPLETED or CANCELLED')
        with e.begin() as c:
            if c.execute(text('SELECT 1 FROM maintenance_reliability_action_execution_close WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':pk}).first(): raise HTTPException(409,'period is closed')
            a=c.execute(text('SELECT * FROM maintenance_reliability_action WHERE action_id=:i AND organization_id=:o AND entity_id=:e AND period_key=:p'),{'i':body['action_id'],'o':o,'e':ei,'p':pk}).mappings().first()
            if not a: raise HTTPException(404,'reliability action not found')
            if str(a['status']).upper()!='APPROVED': raise HTTPException(409,'only approved reliability actions can be executed')
            eid=str(uuid4()); owner=body.get('owner_user_id'); due=body.get('due_date'); note=body.get('execution_note')
            c.execute(text('''INSERT INTO maintenance_reliability_action_execution(execution_id,action_id,organization_id,entity_id,period_key,work_center_id,action_type,recommendation,owner_user_id,due_date,status,execution_note,executed_by,executed_at,created_by) VALUES(:i,:a,:o,:e,:p,:w,:t,:r,:owner,:due,:s,:n,:u,CASE WHEN :s='COMPLETED' THEN CURRENT_TIMESTAMP ELSE NULL END,:u) ON CONFLICT(action_id) DO UPDATE SET owner_user_id=:owner,due_date=:due,status=:s,execution_note=:n,executed_by=CASE WHEN :s='COMPLETED' THEN :u ELSE maintenance_reliability_action_execution.executed_by END,executed_at=CASE WHEN :s='COMPLETED' THEN CURRENT_TIMESTAMP ELSE maintenance_reliability_action_execution.executed_at END'''),{'i':eid,'a':body['action_id'],'o':o,'e':ei,'p':pk,'w':a['work_center_id'],'t':a['action_type'],'r':a['recommendation'],'owner':owner,'due':due,'s':status,'n':note,'u':str(u.user_id)})
        return {'action_id':body['action_id'],'status':status}

    @app.post('/v90et/maintenance/reliability-actions/benefit')
    def benefit(body:dict,request:Request):
        u=perm(e,request,'maintenance_reliability_action_execution.manage')
        for k in ('organization_id','entity_id','period_key','baseline_period_key'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        o,ei,pk,bpk=body['organization_id'],body['entity_id'],body['period_key'],body['baseline_period_key']; valid(pk); valid(bpk)
        wc=body.get('work_center_id'); clause=' AND work_center_id=:w' if wc else ''; params={'o':o,'e':ei,'w':wc}
        with e.connect() as c:
            if c.execute(text('SELECT 1 FROM maintenance_reliability_action_execution_close WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':pk}).first(): raise HTTPException(409,'period is closed')
            def metrics(period):
                q=period+'%'; p={**params,'p':q}
                br=c.execute(text(f'''SELECT COUNT(*) orders,COALESCE(SUM(duration_minutes),0)/60.0 hours FROM maintenance_event WHERE organization_id=:o AND entity_id=:e AND event_type='BREAKDOWN' AND CAST(event_at AS TEXT) LIKE :p{clause}'''),p).mappings().first()
                sp=c.execute(text(f'''SELECT COALESCE(SUM(total_cost),0) cost FROM maintenance_spare_usage WHERE organization_id=:o AND entity_id=:e AND CAST(created_at AS TEXT) LIKE :p{clause}'''),p).scalar() or 0
                la=c.execute(text(f'''SELECT COALESCE(SUM(total_cost),0) cost FROM maintenance_labour_charge WHERE organization_id=:o AND entity_id=:e AND CAST(charge_date AS TEXT) LIKE :p{clause}'''),p).scalar() or 0
                return int(br['orders'] or 0),d(br['hours']),d(Decimal(str(sp))+Decimal(str(la)))
            bo,bh,bc=metrics(bpk); co,ch,cc=metrics(pk)
        reduction=d((Decimal(bo-co)/Decimal(bo))*100) if bo else d(0); downtime=d(bh-ch); cost_impact=d(bc-cc)
        # Composite effectiveness is a transparent observational score, not causal attribution.
        score=d(max(0,min(100,reduction*Decimal('.50') + (downtime/max(Decimal('1'),bh)*100)*Decimal('.30') + (cost_impact/max(Decimal('1'),bc)*100)*Decimal('.20'))))
        assessment='IMPROVEMENT_OBSERVED' if score>=60 else ('PARTIAL_IMPROVEMENT' if score>=25 else 'NO_IMPROVEMENT_OBSERVED')
        with e.begin() as c:
            bid=str(uuid4()); c.execute(text('''INSERT INTO maintenance_reliability_benefit_snapshot(benefit_id,organization_id,entity_id,period_key,baseline_period_key,work_center_id,breakdown_orders_baseline,breakdown_orders_current,breakdown_hours_baseline,breakdown_hours_current,maintenance_cost_baseline,maintenance_cost_current,breakdown_reduction_pct,downtime_reduction_hours,maintenance_cost_impact,effectiveness_score,assessment,status,created_by) VALUES(:i,:o,:e,:p,:bp,:w,:bo,:co,:bh,:ch,:bc,:cc,:br,:dr,:ci,:es,:a,'OPEN',:u) ON CONFLICT(organization_id,entity_id,period_key,baseline_period_key,work_center_id) DO UPDATE SET breakdown_orders_baseline=:bo,breakdown_orders_current=:co,breakdown_hours_baseline=:bh,breakdown_hours_current=:ch,maintenance_cost_baseline=:bc,maintenance_cost_current=:cc,breakdown_reduction_pct=:br,downtime_reduction_hours=:dr,maintenance_cost_impact=:ci,effectiveness_score=:es,assessment=:a,status='OPEN',created_by=:u,created_at=CURRENT_TIMESTAMP'''),{'i':bid,'o':o,'e':ei,'p':pk,'bp':bpk,'w':wc,'bo':bo,'co':co,'bh':float(bh),'ch':float(ch),'bc':float(bc),'cc':float(cc),'br':float(reduction),'dr':float(downtime),'ci':float(cost_impact),'es':float(score),'a':assessment,'u':str(u.user_id)})
            c.execute(text('''UPDATE maintenance_reliability_action_execution SET baseline_period_key=:bp,baseline_breakdown_orders=:bo,baseline_breakdown_hours=:bh,baseline_maintenance_cost=:bc,current_breakdown_orders=:co,current_breakdown_hours=:ch,current_maintenance_cost=:cc,breakdown_reduction_pct=:br,downtime_reduction_hours=:dr,maintenance_cost_impact=:ci,effectiveness_score=:es,benefit_status=:a WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='COMPLETED' AND (work_center_id=:w OR (:w IS NULL AND work_center_id IS NULL))'''),{'bp':bpk,'bo':bo,'bh':float(bh),'bc':float(bc),'co':co,'ch':float(ch),'cc':float(cc),'br':float(reduction),'dr':float(downtime),'ci':float(cost_impact),'es':float(score),'a':assessment,'o':o,'e':ei,'p':pk,'w':wc})
        return {'period_key':pk,'baseline_period_key':bpk,'work_center_id':wc,'effectiveness_score':float(score),'assessment':assessment,'breakdown_reduction_pct':float(reduction),'downtime_reduction_hours':float(downtime),'maintenance_cost_impact':float(cost_impact),'causal_attribution':False}

    @app.get('/v90et/maintenance/reliability-actions/dashboard')
    def dashboard(request:Request,organization_id:str,entity_id:str,period_key:str):
        perm(e,request,'maintenance_reliability_action_execution.view')
        with e.connect() as c:
            actions=c.execute(text('SELECT * FROM maintenance_reliability_action WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY created_at DESC'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
            execs=c.execute(text('SELECT * FROM maintenance_reliability_action_execution WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY created_at DESC'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
            benefits=c.execute(text('SELECT * FROM maintenance_reliability_benefit_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY effectiveness_score DESC'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        return {'action_count':len(actions),'approved_count':sum(str(x['status']).upper()=='APPROVED' for x in actions),'execution_count':len(execs),'completed_count':sum(str(x['status']).upper()=='COMPLETED' for x in execs),'benefit_count':len(benefits),'avg_effectiveness_score':float(d(sum(Decimal(str(x['effectiveness_score'] or 0)) for x in benefits)/len(benefits))) if benefits else 0,'rows':[dict(x) for x in benefits],'actions':[dict(x) for x in actions],'executions':[dict(x) for x in execs],'causal_attribution':False}

    @app.get('/v90et/maintenance/reliability-actions/benefits')
    def benefits(request:Request,organization_id:str,entity_id:str,period_key:str,work_center_id:str|None=None):
        perm(e,request,'maintenance_reliability_action_execution.view'); clause=''; params={'o':organization_id,'e':entity_id,'p':period_key}
        if work_center_id: clause=' AND work_center_id=:w'; params['w']=work_center_id
        with e.connect() as c: rows=c.execute(text('SELECT * FROM maintenance_reliability_benefit_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'+clause+' ORDER BY effectiveness_score DESC'),params).mappings().all()
        return {'count':len(rows),'causal_attribution':False,'rows':[dict(x) for x in rows]}

    @app.post('/v90et/maintenance/reliability-actions/{period_key}/close')
    def close(period_key:str,body:dict,request:Request):
        u=perm(e,request,'maintenance_reliability_action_execution.close'); valid(period_key)
        o,ei=body.get('organization_id'),body.get('entity_id')
        if not o or not ei: raise HTTPException(400,'organization_id and entity_id are required')
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_reliability_action_execution_close(close_id,organization_id,entity_id,period_key,closed_by) VALUES(:i,:o,:e,:p,:u) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),{'i':str(uuid4()),'o':o,'e':ei,'p':period_key,'u':str(u.user_id)})
            c.execute(text('UPDATE maintenance_reliability_benefit_snapshot SET status=\'CLOSED\' WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':period_key})
        return {'period_key':period_key,'status':'CLOSED'}

    @app.get('/ui/maintenance-reliability-actions')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-reliability-actions.html')

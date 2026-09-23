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

def metrics(c,o,ei,period,wc=None):
    q=period+'%'; clause=' AND work_center_id=:w' if wc else ''; p={'o':o,'e':ei,'p':q,'w':wc}
    br=c.execute(text(f"SELECT COUNT(*) orders,COALESCE(SUM(duration_minutes),0)/60.0 hours FROM maintenance_event WHERE organization_id=:o AND entity_id=:e AND event_type='BREAKDOWN' AND CAST(event_at AS TEXT) LIKE :p{clause}"),p).mappings().first()
    sp=c.execute(text(f"SELECT COALESCE(SUM(total_cost),0) FROM maintenance_spare_usage WHERE organization_id=:o AND entity_id=:e AND CAST(created_at AS TEXT) LIKE :p{clause}"),p).scalar() or 0
    la=c.execute(text(f"SELECT COALESCE(SUM(total_cost),0) FROM maintenance_labour_charge WHERE organization_id=:o AND entity_id=:e AND CAST(charge_date AS TEXT) LIKE :p{clause}"),p).scalar() or 0
    return int(br['orders'] or 0),d(br['hours']),d(Decimal(str(sp))+Decimal(str(la)))

def benefit(bo,bh,bc,co,ch,cc):
    reduction=d((Decimal(bo-co)/Decimal(bo))*100) if bo else d(0)
    downtime=d(bh-ch); cost=d(bc-cc)
    score=d(max(0,min(100,reduction*Decimal('.50')+(downtime/max(Decimal('1'),bh)*100)*Decimal('.30')+(cost/max(Decimal('1'),bc)*100)*Decimal('.20'))))
    status='IMPROVEMENT_OBSERVED' if score>=60 else ('PARTIAL_IMPROVEMENT' if score>=25 else 'NO_IMPROVEMENT_OBSERVED')
    return reduction,downtime,cost,score,status

def register_v90ev_routes(app:FastAPI,e):
    with e.begin() as c:
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_change_implementation(implementation_id TEXT PRIMARY KEY,proposal_id TEXT NOT NULL,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_key TEXT NOT NULL,change_type TEXT NOT NULL,implementation_status TEXT NOT NULL DEFAULT 'REQUESTED',owner_user_id TEXT,due_date DATE,effective_from DATE,implementation_note TEXT,evidence_note TEXT,implemented_by TEXT,implemented_at TIMESTAMP,baseline_breakdown_orders INTEGER NOT NULL DEFAULT 0,current_breakdown_orders INTEGER NOT NULL DEFAULT 0,baseline_breakdown_hours NUMERIC NOT NULL DEFAULT 0,current_breakdown_hours NUMERIC NOT NULL DEFAULT 0,baseline_maintenance_cost NUMERIC NOT NULL DEFAULT 0,current_maintenance_cost NUMERIC NOT NULL DEFAULT 0,breakdown_reduction_pct NUMERIC NOT NULL DEFAULT 0,downtime_reduction_hours NUMERIC NOT NULL DEFAULT 0,maintenance_cost_impact NUMERIC NOT NULL DEFAULT 0,effectiveness_score NUMERIC NOT NULL DEFAULT 0,benefit_status TEXT NOT NULL DEFAULT 'NOT_ASSESSED',rollback_note TEXT,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(proposal_id))'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_change_implementation_scope ON maintenance_reliability_change_implementation(organization_id,entity_id,period_key,implementation_status,owner_user_id)'))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_plan_change_revision(revision_id TEXT PRIMARY KEY,implementation_id TEXT NOT NULL,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_key TEXT NOT NULL,plan_id TEXT,work_center_id TEXT,proposed_frequency_type TEXT,proposed_frequency_value NUMERIC,proposed_next_due_date DATE,change_reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'PROPOSED',approved_by TEXT,approved_at TIMESTAMP,implemented_by TEXT,implemented_at TIMESTAMP,rollback_status TEXT NOT NULL DEFAULT 'NOT_REQUESTED',rollback_note TEXT,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(implementation_id))'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_plan_change_revision_scope ON maintenance_reliability_plan_change_revision(organization_id,entity_id,period_key,status,work_center_id)'))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_change_implementation_close(close_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_key TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'CLOSED',closed_by TEXT NOT NULL,closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,period_key))'''))
        for p,n in [('maintenance_reliability_change_implementation.view','View Reliability Change Implementation'),('maintenance_reliability_change_implementation.manage','Manage Reliability Change Implementation'),('maintenance_reliability_change_implementation.implement','Implement Reliability Changes'),('maintenance_reliability_change_implementation.close','Close Reliability Change Implementation')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})

    @app.post('/v90ev/maintenance/reliability-change/requests')
    def request_change(body:dict,request:Request):
        u=perm(e,request,'maintenance_reliability_change_implementation.manage')
        for k in ('proposal_id','organization_id','entity_id','period_key'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        o,ei,pk=body['organization_id'],body['entity_id'],body['period_key']; valid(pk)
        with e.begin() as c:
            if c.execute(text('SELECT 1 FROM maintenance_reliability_change_implementation_close WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':pk}).first(): raise HTTPException(409,'period is closed')
            p=c.execute(text("SELECT * FROM maintenance_reliability_change_proposal WHERE proposal_id=:i AND organization_id=:o AND entity_id=:e AND period_key=:p"),{'i':body['proposal_id'],'o':o,'e':ei,'p':pk}).mappings().first()
            if not p: raise HTTPException(404,'change proposal not found')
            if str(p['status']).upper()!='APPROVED': raise HTTPException(409,'only approved governance proposals can be implemented')
            iid=str(uuid4())
            c.execute(text('''INSERT INTO maintenance_reliability_change_implementation(implementation_id,proposal_id,organization_id,entity_id,period_key,change_type,implementation_status,owner_user_id,due_date,effective_from,implementation_note,created_by) VALUES(:i,:p,:o,:e,:pk,:t,'REQUESTED',:owner,:due,:ef,:n,:u) ON CONFLICT(proposal_id) DO UPDATE SET owner_user_id=:owner,due_date=:due,effective_from=:ef,implementation_note=:n,implementation_status='REQUESTED' '''),{'i':iid,'p':body['proposal_id'],'o':o,'e':ei,'pk':pk,'t':p['change_type'],'owner':body.get('owner_user_id') or p['owner_user_id'],'due':body.get('due_date') or p['due_date'],'ef':body.get('effective_from'),'n':body.get('implementation_note'),'u':str(u.user_id)})
        return {'proposal_id':body['proposal_id'],'status':'REQUESTED'}

    @app.post('/v90ev/maintenance/reliability-change/{implementation_id}/status')
    def status(implementation_id:str,body:dict,request:Request):
        u=perm(e,request,'maintenance_reliability_change_implementation.implement')
        s=str(body.get('implementation_status') or '').upper()
        if s not in ('IN_PROGRESS','IMPLEMENTED','CANCELLED','ROLLBACK_REQUESTED'): raise HTTPException(400,'implementation_status must be IN_PROGRESS, IMPLEMENTED, CANCELLED or ROLLBACK_REQUESTED')
        with e.begin() as c:
            r=c.execute(text('''UPDATE maintenance_reliability_change_implementation SET implementation_status=:s,implementation_note=:n,evidence_note=:ev,implemented_by=CASE WHEN :s='IMPLEMENTED' THEN :u ELSE implemented_by END,implemented_at=CASE WHEN :s='IMPLEMENTED' THEN CURRENT_TIMESTAMP ELSE implemented_at END WHERE implementation_id=:i RETURNING implementation_id,proposal_id'''),{'s':s,'n':body.get('implementation_note'),'ev':body.get('evidence_note'),'u':str(u.user_id),'i':implementation_id}).mappings().first()
            if not r: raise HTTPException(404,'implementation request not found')
        return {'implementation_id':implementation_id,'status':s}

    @app.post('/v90ev/maintenance/reliability-change/{implementation_id}/plan-revision')
    def plan_revision(implementation_id:str,body:dict,request:Request):
        u=perm(e,request,'maintenance_reliability_change_implementation.manage')
        for k in ('organization_id','entity_id','period_key','change_reason'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        valid(body['period_key']); o,ei,pk=body['organization_id'],body['entity_id'],body['period_key']
        with e.begin() as c:
            i=c.execute(text("SELECT * FROM maintenance_reliability_change_implementation WHERE implementation_id=:i AND organization_id=:o AND entity_id=:e AND period_key=:p"),{'i':implementation_id,'o':o,'e':ei,'p':pk}).mappings().first()
            if not i: raise HTTPException(404,'implementation request not found')
            if str(i['implementation_status']).upper() not in ('REQUESTED','IN_PROGRESS','IMPLEMENTED'): raise HTTPException(409,'implementation request is not eligible for plan revision')
            rid=str(uuid4()); c.execute(text('''INSERT INTO maintenance_reliability_plan_change_revision(revision_id,implementation_id,organization_id,entity_id,period_key,plan_id,work_center_id,proposed_frequency_type,proposed_frequency_value,proposed_next_due_date,change_reason,created_by) VALUES(:i,:x,:o,:e,:p,:plan,:w,:ft,:fv,:nd,:r,:u) ON CONFLICT(implementation_id) DO UPDATE SET plan_id=:plan,work_center_id=:w,proposed_frequency_type=:ft,proposed_frequency_value=:fv,proposed_next_due_date=:nd,change_reason=:r,status='PROPOSED',created_by=:u,created_at=CURRENT_TIMESTAMP'''),{'i':rid,'x':implementation_id,'o':o,'e':ei,'p':pk,'plan':body.get('plan_id'),'w':body.get('work_center_id'),'ft':body.get('proposed_frequency_type'),'fv':body.get('proposed_frequency_value'),'nd':body.get('proposed_next_due_date'),'r':body['change_reason'],'u':str(u.user_id)})
        return {'implementation_id':implementation_id,'revision_id':rid,'status':'PROPOSED','operational_plan_mutation':False}

    @app.post('/v90ev/maintenance/reliability-change/{implementation_id}/benefit')
    def realization(implementation_id:str,body:dict,request:Request):
        u=perm(e,request,'maintenance_reliability_change_implementation.manage')
        for k in ('organization_id','entity_id','period_key','baseline_period_key'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        valid(body['period_key']); valid(body['baseline_period_key']); o,ei,pk=body['organization_id'],body['entity_id'],body['period_key']
        with e.connect() as c:
            i=c.execute(text('SELECT * FROM maintenance_reliability_change_implementation WHERE implementation_id=:i AND organization_id=:o AND entity_id=:e AND period_key=:p'),{'i':implementation_id,'o':o,'e':ei,'p':pk}).mappings().first()
            if not i: raise HTTPException(404,'implementation request not found')
            if str(i['implementation_status']).upper()!='IMPLEMENTED': raise HTTPException(409,'only implemented changes can be assessed')
            bo,bh,bc=metrics(c,o,ei,body['baseline_period_key'],body.get('work_center_id')); co,ch,cc=metrics(c,o,ei,pk,body.get('work_center_id'))
        br,dh,ci,score,bs=benefit(bo,bh,bc,co,ch,cc)
        with e.begin() as c:
            c.execute(text('''UPDATE maintenance_reliability_change_implementation SET baseline_breakdown_orders=:bo,current_breakdown_orders=:co,baseline_breakdown_hours=:bh,current_breakdown_hours=:ch,baseline_maintenance_cost=:bc,current_maintenance_cost=:cc,breakdown_reduction_pct=:br,downtime_reduction_hours=:dh,maintenance_cost_impact=:ci,effectiveness_score=:es,benefit_status=:bs,evidence_note=COALESCE(:ev,evidence_note) WHERE implementation_id=:i'''),{'bo':bo,'co':co,'bh':float(bh),'ch':float(ch),'bc':float(bc),'cc':float(cc),'br':float(br),'dh':float(dh),'ci':float(ci),'es':float(score),'bs':bs,'ev':body.get('evidence_note'),'i':implementation_id})
        return {'implementation_id':implementation_id,'effectiveness_score':float(score),'benefit_status':bs,'breakdown_reduction_pct':float(br),'downtime_reduction_hours':float(dh),'maintenance_cost_impact':float(ci),'causal_attribution':False}

    @app.post('/v90ev/maintenance/reliability-change/{implementation_id}/rollback')
    def rollback(implementation_id:str,body:dict,request:Request):
        u=perm(e,request,'maintenance_reliability_change_implementation.implement')
        with e.begin() as c:
            r=c.execute(text("UPDATE maintenance_reliability_plan_change_revision SET rollback_status='REQUESTED',rollback_note=:n WHERE implementation_id=:i RETURNING revision_id"),{'n':body.get('rollback_note'),'i':implementation_id}).first()
            if not r: raise HTTPException(404,'plan revision not found')
            c.execute(text("UPDATE maintenance_reliability_change_implementation SET implementation_status='ROLLBACK_REQUESTED',rollback_note=:n WHERE implementation_id=:i"),{'n':body.get('rollback_note'),'i':implementation_id})
        return {'implementation_id':implementation_id,'status':'ROLLBACK_REQUESTED','operational_plan_mutation':False}

    @app.get('/v90ev/maintenance/reliability-change/dashboard')
    def dashboard(request:Request,organization_id:str,entity_id:str,period_key:str):
        perm(e,request,'maintenance_reliability_change_implementation.view'); valid(period_key)
        with e.connect() as c:
            rows=c.execute(text('SELECT * FROM maintenance_reliability_change_implementation WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY created_at DESC'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
            rev=c.execute(text('SELECT * FROM maintenance_reliability_plan_change_revision WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY created_at DESC'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        implemented=[x for x in rows if str(x['implementation_status']).upper()=='IMPLEMENTED']; assessed=[x for x in implemented if str(x['benefit_status']).upper()!='NOT_ASSESSED']
        return {'implementation_count':len(rows),'implemented_count':len(implemented),'assessed_count':len(assessed),'avg_effectiveness_score':float(d(sum(Decimal(str(x['effectiveness_score'] or 0)) for x in assessed)/len(assessed))) if assessed else 0,'rows':[dict(x) for x in rows],'plan_revisions':[dict(x) for x in rev],'causal_attribution':False}

    @app.post('/v90ev/maintenance/reliability-change/{period_key}/close')
    def close(period_key:str,body:dict,request:Request):
        u=perm(e,request,'maintenance_reliability_change_implementation.close'); valid(period_key); o,ei=body.get('organization_id'),body.get('entity_id')
        if not o or not ei: raise HTTPException(400,'organization_id and entity_id are required')
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_reliability_change_implementation_close(close_id,organization_id,entity_id,period_key,closed_by) VALUES(:i,:o,:e,:p,:u) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),{'i':str(uuid4()),'o':o,'e':ei,'p':period_key,'u':str(u.user_id)})
        return {'period_key':period_key,'status':'CLOSED'}

    @app.get('/ui/maintenance-reliability-change')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-reliability-change.html')

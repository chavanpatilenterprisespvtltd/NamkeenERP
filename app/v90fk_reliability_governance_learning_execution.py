from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def _perm(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def _valid(pk):
    try:
        y,m=map(int,pk.split('-'))
        if y<2000 or not 1<=m<=12: raise ValueError
    except Exception as exc: raise HTTPException(400,'period_key must be YYYY-MM') from exc

def _d(v): return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def ensure_v90fk_schema(e):
    with e.begin() as c:
        for s in [
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_governance_learning_execution(
            execution_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            recommendation_id TEXT, recommendation_type TEXT NOT NULL, finding TEXT NOT NULL, planned_improvement TEXT NOT NULL,
            owner_user_id TEXT, due_date DATE, status TEXT NOT NULL DEFAULT 'REQUESTED', execution_note TEXT,
            evidence_note TEXT, completed_by TEXT, completed_at TIMESTAMP, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_governance_learning_benefit(
            benefit_id TEXT PRIMARY KEY, execution_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            period_key TEXT NOT NULL, baseline_score NUMERIC NOT NULL DEFAULT 0, followup_score NUMERIC NOT NULL DEFAULT 0,
            score_delta NUMERIC NOT NULL DEFAULT 0, outcome TEXT NOT NULL DEFAULT 'PENDING', finding TEXT NOT NULL,
            evidence_note TEXT NOT NULL, reviewed_by TEXT, reviewed_at TIMESTAMP, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(execution_id))''',
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_governance_learning_execution_close(
            close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            execution_count INTEGER NOT NULL DEFAULT 0, open_execution_count INTEGER NOT NULL DEFAULT 0,
            completed_count INTEGER NOT NULL DEFAULT 0, effective_count INTEGER NOT NULL DEFAULT 0, learning_benefit_score NUMERIC NOT NULL DEFAULT 0,
            closed_by TEXT NOT NULL, closure_note TEXT, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key))''',
        'CREATE INDEX IF NOT EXISTS ix_rel_gov_learning_exec_scope ON maintenance_reliability_governance_learning_execution(organization_id,entity_id,period_key,status)',
        'CREATE INDEX IF NOT EXISTS ix_rel_gov_learning_benefit_scope ON maintenance_reliability_governance_learning_benefit(organization_id,entity_id,period_key,outcome)']:
            c.execute(text(s))
        for p,n in [('maintenance_reliability_governance_learning_execution.view','View Reliability Governance Learning Execution'),('maintenance_reliability_governance_learning_execution.manage','Manage Reliability Governance Learning Execution'),('maintenance_reliability_governance_learning_execution.close','Close Reliability Governance Learning Execution Period')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})

def _ensure_source(e,o,ei,p,rid):
    with e.connect() as c:
        r=c.execute(text('SELECT * FROM maintenance_reliability_governance_learning_recommendation WHERE recommendation_id=:id AND organization_id=:o AND entity_id=:e AND period_key=:p'),{'id':rid,'o':o,'e':ei,'p':p}).mappings().first()
    if not r: raise HTTPException(404,'learning recommendation not found for scope')
    if r['status'] != 'OPEN': raise HTTPException(409,'only OPEN learning recommendations can be executed')
    return r

def register_v90fk_routes(app:FastAPI,e):
    ensure_v90fk_schema(e)
    @app.post('/v90fk/maintenance/reliability-governance-learning/executions')
    def create(body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_governance_learning_execution.manage')
        o,ei,p=body.get('organization_id'),body.get('entity_id'),body.get('period_key'); rid=body.get('recommendation_id')
        if not all([o,ei,p,rid]): raise HTTPException(400,'organization_id, entity_id, period_key and recommendation_id are required')
        _valid(p); r=_ensure_source(e,o,ei,p,rid)
        eid=str(uuid4())
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_reliability_governance_learning_execution(execution_id,organization_id,entity_id,period_key,recommendation_id,recommendation_type,finding,planned_improvement,owner_user_id,due_date,created_by) VALUES(:id,:o,:e,:p,:r,:t,:f,:i,:owner,:due,:u)'''),{'id':eid,'o':o,'e':ei,'p':p,'r':rid,'t':r['recommendation_type'],'f':r['finding'],'i':r['proposed_improvement'],'owner':body.get('owner_user_id') or r['owner_user_id'],'due':body.get('due_date') or r['due_date'],'u':str(u.user_id)})
        return {'execution_id':eid,'status':'REQUESTED','source_recommendation_id':rid,'automatic_operational_mutation':False,'causal_attribution':False}
    @app.get('/v90fk/maintenance/reliability-governance-learning/executions')
    def executions(organization_id:str,period_key:str,request:Request,entity_id:str|None=None,status:str|None=None):
        _perm(e,request,'maintenance_reliability_governance_learning_execution.view'); _valid(period_key)
        q='SELECT * FROM maintenance_reliability_governance_learning_execution WHERE organization_id=:o AND period_key=:p'; par={'o':organization_id,'p':period_key}
        if entity_id: q+=' AND entity_id=:e'; par['e']=entity_id
        if status: q+=' AND status=:s'; par['s']=status.upper()
        with e.connect() as c: rows=c.execute(text(q+' ORDER BY due_date,created_at'),par).mappings().all()
        return {'organization_id':organization_id,'period_key':period_key,'executions':[dict(x) for x in rows],'automatic_operational_mutation':False,'causal_attribution':False}
    @app.post('/v90fk/maintenance/reliability-governance-learning/executions/{execution_id}/start')
    def start(execution_id:str,body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_governance_learning_execution.manage'); note=str(body.get('execution_note') or '').strip(); ev=str(body.get('evidence_note') or '').strip()
        if not note or not ev: raise HTTPException(400,'execution_note and evidence_note are required')
        with e.begin() as c:
            r=c.execute(text("UPDATE maintenance_reliability_governance_learning_execution SET status='IN_PROGRESS',execution_note=:n,evidence_note=:ev WHERE execution_id=:id AND status='REQUESTED' RETURNING execution_id"),{'n':note,'ev':ev,'id':execution_id}).first()
            if not r: raise HTTPException(404,'requested learning execution not found')
        return {'execution_id':execution_id,'status':'IN_PROGRESS','evidence_recorded':True}
    @app.post('/v90fk/maintenance/reliability-governance-learning/executions/{execution_id}/complete')
    def complete(execution_id:str,body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_governance_learning_execution.manage'); note=str(body.get('completion_note') or '').strip(); ev=str(body.get('evidence_note') or '').strip()
        if not note or not ev: raise HTTPException(400,'completion_note and evidence_note are required')
        with e.begin() as c:
            r=c.execute(text("UPDATE maintenance_reliability_governance_learning_execution SET status='COMPLETED',execution_note=COALESCE(execution_note,'') || ' | Completion: ' || :n,evidence_note=COALESCE(evidence_note,'') || ' | Completion: ' || :ev,completed_by=:u,completed_at=CURRENT_TIMESTAMP WHERE execution_id=:id AND status='IN_PROGRESS' RETURNING execution_id"),{'n':note,'ev':ev,'u':str(u.user_id),'id':execution_id}).first()
            if not r: raise HTTPException(404,'in-progress learning execution not found')
        return {'execution_id':execution_id,'status':'COMPLETED','evidence_recorded':True}
    @app.post('/v90fk/maintenance/reliability-governance-learning/executions/{execution_id}/cancel')
    def cancel(execution_id:str,body:dict,request:Request):
        _perm(e,request,'maintenance_reliability_governance_learning_execution.manage'); note=str(body.get('cancellation_note') or '').strip(); ev=str(body.get('evidence_note') or '').strip()
        if not note or not ev: raise HTTPException(400,'cancellation_note and evidence_note are required')
        with e.begin() as c:
            r=c.execute(text("UPDATE maintenance_reliability_governance_learning_execution SET status='CANCELLED',execution_note=COALESCE(execution_note,'') || ' | Cancellation: ' || :n,evidence_note=COALESCE(evidence_note,'') || ' | Cancellation: ' || :ev WHERE execution_id=:id AND status IN ('REQUESTED','IN_PROGRESS') RETURNING execution_id"),{'n':note,'ev':ev,'id':execution_id}).first()
            if not r: raise HTTPException(404,'open learning execution not found')
        return {'execution_id':execution_id,'status':'CANCELLED','evidence_recorded':True}
    @app.post('/v90fk/maintenance/reliability-governance-learning/executions/{execution_id}/benefit')
    def benefit(execution_id:str,body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_governance_learning_execution.manage')
        finding=str(body.get('finding') or '').strip(); ev=str(body.get('evidence_note') or '').strip()
        if not finding or not ev: raise HTTPException(400,'finding and evidence_note are required')
        with e.connect() as c: ex=c.execute(text('SELECT * FROM maintenance_reliability_governance_learning_execution WHERE execution_id=:id AND status=\'COMPLETED\''),{'id':execution_id}).mappings().first()
        if not ex: raise HTTPException(409,'benefit review requires a COMPLETED execution')
        baseline=_d(body.get('baseline_score')); follow=_d(body.get('followup_score')); delta=_d(follow-baseline)
        outcome=str(body.get('outcome') or ('EFFECTIVE' if delta>=2 else 'INEFFECTIVE')).upper()
        if outcome not in ('EFFECTIVE','INEFFECTIVE','NEEDS_FOLLOWUP'): raise HTTPException(400,'outcome must be EFFECTIVE, INEFFECTIVE or NEEDS_FOLLOWUP')
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_reliability_governance_learning_benefit(benefit_id,execution_id,organization_id,entity_id,period_key,baseline_score,followup_score,score_delta,outcome,finding,evidence_note,reviewed_by,reviewed_at,created_by) VALUES(:id,:x,:o,:e,:p,:b,:f,:d,:out,:fi,:ev,:u,CURRENT_TIMESTAMP,:u) ON CONFLICT(execution_id) DO UPDATE SET baseline_score=:b,followup_score=:f,score_delta=:d,outcome=:out,finding=:fi,evidence_note=:ev,reviewed_by=:u,reviewed_at=CURRENT_TIMESTAMP'''),{'id':str(uuid4()),'x':execution_id,'o':ex['organization_id'],'e':ex['entity_id'],'p':ex['period_key'],'b':float(baseline),'f':float(follow),'d':float(delta),'out':outcome,'fi':finding,'ev':ev,'u':str(u.user_id)})
        return {'execution_id':execution_id,'outcome':outcome,'score_delta':float(delta),'evidence_recorded':True,'causal_attribution':False}
    @app.get('/v90fk/maintenance/reliability-governance-learning/benefits')
    def benefits(organization_id:str,period_key:str,request:Request,entity_id:str|None=None):
        _perm(e,request,'maintenance_reliability_governance_learning_execution.view'); _valid(period_key)
        q='SELECT * FROM maintenance_reliability_governance_learning_benefit WHERE organization_id=:o AND period_key=:p'; par={'o':organization_id,'p':period_key}
        if entity_id: q+=' AND entity_id=:e'; par['e']=entity_id
        with e.connect() as c: rows=c.execute(text(q+' ORDER BY reviewed_at DESC'),par).mappings().all()
        return {'benefits':[dict(x) for x in rows],'causal_attribution':False}
    @app.post('/v90fk/maintenance/reliability-governance-learning/{period_key}/close')
    def close(period_key:str,body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_governance_learning_execution.close'); _valid(period_key); o,ei=body.get('organization_id'),body.get('entity_id')
        if not o or not ei: raise HTTPException(400,'organization_id and entity_id are required')
        with e.connect() as c:
            total=c.execute(text('SELECT COUNT(*) FROM maintenance_reliability_governance_learning_execution WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':period_key}).scalar() or 0
            op=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_governance_learning_execution WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status IN ('REQUESTED','IN_PROGRESS')"),{'o':o,'e':ei,'p':period_key}).scalar() or 0
            comp=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_governance_learning_execution WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='COMPLETED'"),{'o':o,'e':ei,'p':period_key}).scalar() or 0
            eff=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_governance_learning_benefit WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND outcome='EFFECTIVE'"),{'o':o,'e':ei,'p':period_key}).scalar() or 0
            avg=c.execute(text('SELECT AVG(score_delta) FROM maintenance_reliability_governance_learning_benefit WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':period_key}).scalar() or 0
        if op and not body.get('force'): raise HTTPException(409,f'cannot close: {op} open learning execution(s)')
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_reliability_governance_learning_execution_close(close_id,organization_id,entity_id,period_key,execution_count,open_execution_count,completed_count,effective_count,learning_benefit_score,closed_by,closure_note) VALUES(:id,:o,:e,:p,:n,:op,:co,:ef,:s,:u,:note) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET execution_count=:n,open_execution_count=:op,completed_count=:co,effective_count=:ef,learning_benefit_score=:s,closed_by=:u,closure_note=:note,closed_at=CURRENT_TIMESTAMP'''),{'id':str(uuid4()),'o':o,'e':ei,'p':period_key,'n':int(total),'op':int(op),'co':int(comp),'ef':int(eff),'s':float(_d(avg)),'u':str(u.user_id),'note':body.get('closure_note')})
        return {'organization_id':o,'entity_id':ei,'period_key':period_key,'status':'CLOSED','open_execution_count':int(op),'completed_count':int(comp),'effective_count':int(eff),'learning_benefit_score':float(_d(avg)),'forced':bool(body.get('force'))}
    @app.get('/ui/maintenance-reliability-governance-learning-execution')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-reliability-governance-learning-execution.html')

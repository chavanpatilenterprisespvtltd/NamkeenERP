from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from datetime import date
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

def _d(v): return Decimal(str(v or 0)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)

def _prior(pk):
    y,m=map(int,pk.split('-')); return f'{y-1:04d}-12' if m==1 else f'{y:04d}-{m-1:02d}'

def ensure_v90fj_schema(e):
    with e.begin() as c:
        stmts=[
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_governance_learning_snapshot(
            snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            prior_period_key TEXT, current_score NUMERIC NOT NULL DEFAULT 0, prior_score NUMERIC NOT NULL DEFAULT 0,
            score_delta NUMERIC NOT NULL DEFAULT 0, current_resolution_rate NUMERIC NOT NULL DEFAULT 0,
            prior_resolution_rate NUMERIC NOT NULL DEFAULT 0, resolution_delta NUMERIC NOT NULL DEFAULT 0,
            current_effectiveness_rate NUMERIC NOT NULL DEFAULT 0, prior_effectiveness_rate NUMERIC NOT NULL DEFAULT 0,
            effectiveness_delta NUMERIC NOT NULL DEFAULT 0, overdue_escalation_count INTEGER NOT NULL DEFAULT 0,
            recurring_escalation_count INTEGER NOT NULL DEFAULT 0, assessment TEXT NOT NULL DEFAULT 'NO_BASELINE',
            recommendation TEXT, status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id,period_key))''',
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_governance_learning_recommendation(
            recommendation_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            recommendation_type TEXT NOT NULL, finding TEXT NOT NULL, proposed_improvement TEXT NOT NULL,
            evidence_note TEXT NOT NULL, owner_user_id TEXT, due_date DATE, status TEXT NOT NULL DEFAULT 'OPEN',
            resolved_by TEXT, resolved_at TIMESTAMP, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_governance_learning_close(
            close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            recommendation_count INTEGER NOT NULL DEFAULT 0, open_recommendation_count INTEGER NOT NULL DEFAULT 0,
            learning_score NUMERIC NOT NULL DEFAULT 0, closed_by TEXT NOT NULL, closure_note TEXT,
            closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id,period_key))''',
        'CREATE INDEX IF NOT EXISTS ix_rel_gov_learning_scope ON maintenance_reliability_governance_learning_snapshot(organization_id,entity_id,period_key,status)',
        'CREATE INDEX IF NOT EXISTS ix_rel_gov_learning_rec ON maintenance_reliability_governance_learning_recommendation(organization_id,entity_id,period_key,status)']
        for s in stmts: c.execute(text(s))
        for p,n in [('maintenance_reliability_governance_learning.view','View Reliability Governance Learning'),('maintenance_reliability_governance_learning.manage','Manage Reliability Governance Learning Recommendations'),('maintenance_reliability_governance_learning.close','Close Reliability Governance Learning Period')]:
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"),{'p':p,'n':n})

def _snapshot(e,o,ei,p,u):
    prior=_prior(p)
    with e.connect() as c:
        cur=c.execute(text("SELECT * FROM maintenance_reliability_executive_governance_effectiveness_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':p}).mappings().first()
        prev=c.execute(text("SELECT * FROM maintenance_reliability_executive_governance_effectiveness_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':prior}).mappings().first()
        esc=c.execute(text("SELECT escalation_id,action_id,status,due_date FROM maintenance_reliability_executive_governance_escalation WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':p}).mappings().all()
        recurring=c.execute(text('''SELECT COUNT(*) FROM maintenance_reliability_executive_governance_escalation x WHERE x.organization_id=:o AND x.entity_id=:e AND x.period_key=:p AND EXISTS (SELECT 1 FROM maintenance_reliability_executive_governance_escalation y WHERE y.organization_id=x.organization_id AND y.entity_id=x.entity_id AND y.action_id=x.action_id AND y.period_key=:pp)'''),{'o':o,'e':ei,'p':p,'pp':prior}).scalar() or 0
    if not cur:
        raise HTTPException(409,'V90.fi effectiveness snapshot is required before learning snapshot')
    cs=_d(cur['governance_effectiveness_score']); ps=_d(prev['governance_effectiveness_score']) if prev else Decimal('0')
    cr=_d(cur['resolution_rate']); pr=_d(prev['resolution_rate']) if prev else Decimal('0')
    ce=_d(cur['effectiveness_rate']); pe=_d(prev['effectiveness_rate']) if prev else Decimal('0')
    overdue=sum(1 for x in esc if x['status']=='OPEN' and x['due_date'] and str(x['due_date'])<date.today().isoformat())
    sd=_d(cs-ps); rd=_d(cr-pr); ed=_d(ce-pe)
    assessment='IMPROVING' if prev and sd>=2 and rd>=2 and ed>=2 else ('DETERIORATING' if prev and (sd<=-2 or rd<=-2 or ed<=-2 or overdue) else ('STABLE' if prev else 'NO_BASELINE'))
    rec=('Sustain current controls and document reusable practices.' if assessment=='IMPROVING' else ('Review recurring/overdue escalations and assign corrective governance actions.' if assessment=='DETERIORATING' else ('Continue monitoring cross-period governance outcomes.' if assessment=='STABLE' else 'Establish a prior-period baseline before drawing trend conclusions.')))
    vals={'id':str(uuid4()),'o':o,'e':ei,'p':p,'pp':prior,'cs':float(cs),'ps':float(ps),'sd':float(sd),'cr':float(cr),'pr':float(pr),'rd':float(rd),'ce':float(ce),'pe':float(pe),'ed':float(ed),'ov':overdue,'rc':int(recurring),'a':assessment,'r':rec,'u':str(u.user_id)}
    with e.begin() as c:
        c.execute(text('''INSERT INTO maintenance_reliability_governance_learning_snapshot(snapshot_id,organization_id,entity_id,period_key,prior_period_key,current_score,prior_score,score_delta,current_resolution_rate,prior_resolution_rate,resolution_delta,current_effectiveness_rate,prior_effectiveness_rate,effectiveness_delta,overdue_escalation_count,recurring_escalation_count,assessment,recommendation,status,created_by) VALUES(:id,:o,:e,:p,:pp,:cs,:ps,:sd,:cr,:pr,:rd,:ce,:pe,:ed,:ov,:rc,:a,:r,'OPEN',:u) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET prior_period_key=:pp,current_score=:cs,prior_score=:ps,score_delta=:sd,current_resolution_rate=:cr,prior_resolution_rate=:pr,resolution_delta=:rd,current_effectiveness_rate=:ce,prior_effectiveness_rate=:pe,effectiveness_delta=:ed,overdue_escalation_count=:ov,recurring_escalation_count=:rc,assessment=:a,recommendation=:r,status='OPEN',created_by=:u,created_at=CURRENT_TIMESTAMP'''),vals)
        row=c.execute(text('SELECT * FROM maintenance_reliability_governance_learning_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':p}).mappings().first()
    return dict(row)

def register_v90fj_routes(app:FastAPI,e):
    ensure_v90fj_schema(e)
    @app.post('/v90fj/maintenance/reliability-governance-learning/snapshot')
    def snapshot(body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_governance_learning.manage'); o,ei,p=body.get('organization_id'),body.get('entity_id'),body.get('period_key')
        if not all([o,ei,p]): raise HTTPException(400,'organization_id, entity_id and period_key are required')
        _valid(p); return {'snapshot':_snapshot(e,o,ei,p,u),'automatic_operational_mutation':False,'causal_attribution':False}
    @app.get('/v90fj/maintenance/reliability-governance-learning/dashboard')
    def dashboard(organization_id:str,period_key:str,request:Request,entity_id:str|None=None):
        _perm(e,request,'maintenance_reliability_governance_learning.view'); _valid(period_key)
        with e.connect() as c:
            q='SELECT * FROM maintenance_reliability_governance_learning_snapshot WHERE organization_id=:o AND period_key=:p'; par={'o':organization_id,'p':period_key}
            if entity_id: q+=' AND entity_id=:e'; par['e']=entity_id
            rows=c.execute(text(q+' ORDER BY current_score ASC,entity_id'),par).mappings().all()
            rq='SELECT * FROM maintenance_reliability_governance_learning_recommendation WHERE organization_id=:o AND period_key=:p AND status=\'OPEN\' ORDER BY due_date'; recs=c.execute(text(rq),{'o':organization_id,'p':period_key}).mappings().all()
        return {'organization_id':organization_id,'period_key':period_key,'entity_count':len(rows),'average_score':float(_d(sum((_d(x['current_score']) for x in rows),Decimal('0'))/len(rows))) if rows else 0,'rows':[dict(x) for x in rows],'open_recommendations':[dict(x) for x in recs],'automatic_operational_mutation':False,'causal_attribution':False}
    @app.get('/v90fj/maintenance/reliability-governance-learning/trend')
    def trend(organization_id:str,period_key:str,request:Request,entity_id:str|None=None):
        _perm(e,request,'maintenance_reliability_governance_learning.view'); _valid(period_key)
        with e.connect() as c:
            q='SELECT * FROM maintenance_reliability_governance_learning_snapshot WHERE organization_id=:o AND period_key<=:p'; par={'o':organization_id,'p':period_key}
            if entity_id: q+=' AND entity_id=:e'; par['e']=entity_id
            rows=c.execute(text(q+' ORDER BY period_key ASC,entity_id'),par).mappings().all()
        return {'organization_id':organization_id,'through_period':period_key,'trend':[dict(x) for x in rows],'automatic_operational_mutation':False,'causal_attribution':False}
    @app.get('/v90fj/maintenance/reliability-governance-learning/recommendations')
    def recommendations(organization_id:str,period_key:str,request:Request,entity_id:str|None=None,status:str='OPEN'):
        _perm(e,request,'maintenance_reliability_governance_learning.view'); _valid(period_key)
        q='SELECT * FROM maintenance_reliability_governance_learning_recommendation WHERE organization_id=:o AND period_key=:p AND status=:s'; par={'o':organization_id,'p':period_key,'s':status.upper()}
        if entity_id: q+=' AND entity_id=:e'; par['e']=entity_id
        with e.connect() as c: rows=c.execute(text(q+' ORDER BY due_date'),par).mappings().all()
        return {'recommendations':[dict(x) for x in rows]}
    @app.post('/v90fj/maintenance/reliability-governance-learning/recommendations')
    def create_recommendation(body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_governance_learning.manage'); o,ei,p=body.get('organization_id'),body.get('entity_id'),body.get('period_key'); typ=str(body.get('recommendation_type') or '').upper(); finding=str(body.get('finding') or '').strip(); prop=str(body.get('proposed_improvement') or '').strip(); ev=str(body.get('evidence_note') or '').strip()
        if not all([o,ei,p,typ,finding,prop,ev]): raise HTTPException(400,'organization_id, entity_id, period_key, recommendation_type, finding, proposed_improvement and evidence_note are required')
        _valid(p); rid=str(uuid4())
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_reliability_governance_learning_recommendation(recommendation_id,organization_id,entity_id,period_key,recommendation_type,finding,proposed_improvement,evidence_note,owner_user_id,due_date,created_by) VALUES(:id,:o,:e,:p,:t,:f,:i,:v,:owner,:due,:u)'''),{'id':rid,'o':o,'e':ei,'p':p,'t':typ,'f':finding,'i':prop,'v':ev,'owner':body.get('owner_user_id'),'due':body.get('due_date'),'u':str(u.user_id)})
        return {'recommendation_id':rid,'status':'OPEN','automatic_operational_mutation':False}
    @app.post('/v90fj/maintenance/reliability-governance-learning/recommendations/{recommendation_id}/resolve')
    def resolve(recommendation_id:str,body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_governance_learning.manage'); note=str(body.get('resolution_note') or '').strip(); ev=str(body.get('evidence_note') or '').strip()
        if not note or not ev: raise HTTPException(400,'resolution_note and evidence_note are required')
        with e.begin() as c:
            r=c.execute(text("UPDATE maintenance_reliability_governance_learning_recommendation SET status='RESOLVED',evidence_note=evidence_note || ' | Resolution: ' || :ev, proposed_improvement=proposed_improvement || ' | Resolution: ' || :n,resolved_by=:u,resolved_at=CURRENT_TIMESTAMP WHERE recommendation_id=:id AND status='OPEN' RETURNING recommendation_id"),{'ev':ev,'n':note,'u':str(u.user_id),'id':recommendation_id}).first()
            if not r: raise HTTPException(404,'open learning recommendation not found')
        return {'recommendation_id':recommendation_id,'status':'RESOLVED','evidence_recorded':True}
    @app.post('/v90fj/maintenance/reliability-governance-learning/{period_key}/close')
    def close(period_key:str,body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_governance_learning.close'); _valid(period_key); o,ei=body.get('organization_id'),body.get('entity_id')
        if not o or not ei: raise HTTPException(400,'organization_id and entity_id are required')
        with e.connect() as c:
            score=c.execute(text('SELECT current_score FROM maintenance_reliability_governance_learning_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':period_key}).scalar() or 0
            total=c.execute(text('SELECT COUNT(*) FROM maintenance_reliability_governance_learning_recommendation WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':period_key}).scalar() or 0
            op=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_governance_learning_recommendation WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='OPEN'"),{'o':o,'e':ei,'p':period_key}).scalar() or 0
        if op and not body.get('force'): raise HTTPException(409,f'cannot close: {op} open learning recommendation(s)')
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_reliability_governance_learning_close(close_id,organization_id,entity_id,period_key,recommendation_count,open_recommendation_count,learning_score,closed_by,closure_note) VALUES(:id,:o,:e,:p,:n,:op,:s,:u,:note) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET recommendation_count=:n,open_recommendation_count=:op,learning_score=:s,closed_by=:u,closure_note=:note,closed_at=CURRENT_TIMESTAMP'''),{'id':str(uuid4()),'o':o,'e':ei,'p':period_key,'n':int(total),'op':int(op),'s':float(score),'u':str(u.user_id),'note':body.get('closure_note')})
            c.execute(text("UPDATE maintenance_reliability_governance_learning_snapshot SET status='CLOSED' WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':period_key})
        return {'organization_id':o,'entity_id':ei,'period_key':period_key,'status':'CLOSED','open_recommendation_count':int(op),'forced':bool(body.get('force'))}
    @app.get('/ui/maintenance-reliability-governance-learning')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-reliability-governance-learning.html')

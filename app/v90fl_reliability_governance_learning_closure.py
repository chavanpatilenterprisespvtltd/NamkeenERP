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

def _d(v): return Decimal(str(v or 0)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)

def ensure_v90fl_schema(e):
    with e.begin() as c:
        for s in [
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_governance_learning_closure(
            closure_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            execution_count INTEGER NOT NULL DEFAULT 0, completed_count INTEGER NOT NULL DEFAULT 0,
            benefit_review_count INTEGER NOT NULL DEFAULT 0, effective_count INTEGER NOT NULL DEFAULT 0,
            ineffective_count INTEGER NOT NULL DEFAULT 0, followup_count INTEGER NOT NULL DEFAULT 0,
            average_score_delta NUMERIC NOT NULL DEFAULT 0, closure_assessment TEXT NOT NULL DEFAULT 'INCOMPLETE',
            closure_note TEXT NOT NULL, evidence_note TEXT NOT NULL, closed_by TEXT NOT NULL,
            closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(organization_id,entity_id,period_key))''',
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_governance_learning_knowledge(
            knowledge_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            source_execution_id TEXT, source_benefit_id TEXT, knowledge_type TEXT NOT NULL, title TEXT NOT NULL,
            lesson TEXT NOT NULL, standard_practice TEXT NOT NULL, evidence_note TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PROPOSED', owner_user_id TEXT, due_date DATE,
            approved_by TEXT, approved_at TIMESTAMP, resolved_by TEXT, resolved_at TIMESTAMP,
            created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        'CREATE INDEX IF NOT EXISTS ix_rel_gov_learning_closure_scope ON maintenance_reliability_governance_learning_closure(organization_id,entity_id,period_key)',
        'CREATE INDEX IF NOT EXISTS ix_rel_gov_learning_knowledge_scope ON maintenance_reliability_governance_learning_knowledge(organization_id,entity_id,period_key,status)']:
            c.execute(text(s))
        for p,n in [('maintenance_reliability_governance_learning_closure.view','View Reliability Governance Learning Closure'),('maintenance_reliability_governance_learning_closure.manage','Manage Reliability Governance Learning Closure'),('maintenance_reliability_governance_learning_closure.close','Close Reliability Governance Learning Closure Period')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})

def register_v90fl_routes(app:FastAPI,e):
    ensure_v90fl_schema(e)
    @app.post('/v90fl/maintenance/reliability-governance-learning/closure')
    def closure(body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_governance_learning_closure.close')
        o,ei,p=body.get('organization_id'),body.get('entity_id'),body.get('period_key')
        note=str(body.get('closure_note') or '').strip(); ev=str(body.get('evidence_note') or '').strip()
        if not all([o,ei,p,note,ev]): raise HTTPException(400,'organization_id, entity_id, period_key, closure_note and evidence_note are required')
        _valid(p)
        with e.connect() as c:
            n=c.execute(text('SELECT COUNT(*) FROM maintenance_reliability_governance_learning_execution WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':p}).scalar() or 0
            comp=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_governance_learning_execution WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='COMPLETED'"),{'o':o,'e':ei,'p':p}).scalar() or 0
            br=c.execute(text('SELECT COUNT(*) FROM maintenance_reliability_governance_learning_benefit WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':p}).scalar() or 0
            eff=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_governance_learning_benefit WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND outcome='EFFECTIVE'"),{'o':o,'e':ei,'p':p}).scalar() or 0
            ineff=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_governance_learning_benefit WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND outcome='INEFFECTIVE'"),{'o':o,'e':ei,'p':p}).scalar() or 0
            follow=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_governance_learning_benefit WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND outcome='NEEDS_FOLLOWUP'"),{'o':o,'e':ei,'p':p}).scalar() or 0
            avg=c.execute(text('SELECT AVG(score_delta) FROM maintenance_reliability_governance_learning_benefit WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':p}).scalar() or 0
            openx=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_governance_learning_execution WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status IN ('REQUESTED','IN_PROGRESS')"),{'o':o,'e':ei,'p':p}).scalar() or 0
        if openx and not body.get('force'): raise HTTPException(409,f'cannot close: {openx} open execution(s)')
        assessment='COMPLETE_EFFECTIVE' if n and comp==n and br==comp and eff==br else ('COMPLETE_MIXED' if n and comp==n and br==comp else ('INCOMPLETE' if n else 'NO_EXECUTIONS'))
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_reliability_governance_learning_closure(closure_id,organization_id,entity_id,period_key,execution_count,completed_count,benefit_review_count,effective_count,ineffective_count,followup_count,average_score_delta,closure_assessment,closure_note,evidence_note,closed_by) VALUES(:id,:o,:e,:p,:n,:co,:br,:ef,:ine,:fu,:avg,:a,:note,:ev,:u) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET execution_count=:n,completed_count=:co,benefit_review_count=:br,effective_count=:ef,ineffective_count=:ine,followup_count=:fu,average_score_delta=:avg,closure_assessment=:a,closure_note=:note,evidence_note=:ev,closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),{'id':str(uuid4()),'o':o,'e':ei,'p':p,'n':int(n),'co':int(comp),'br':int(br),'ef':int(eff),'ine':int(ineff),'fu':int(follow),'avg':float(_d(avg)),'a':assessment,'note':note,'ev':ev,'u':str(u.user_id)})
        return {'organization_id':o,'entity_id':ei,'period_key':p,'closure_assessment':assessment,'execution_count':int(n),'completed_count':int(comp),'benefit_review_count':int(br),'effective_count':int(eff),'average_score_delta':float(_d(avg)),'forced':bool(body.get('force')),'automatic_operational_mutation':False,'causal_attribution':False}
    @app.get('/v90fl/maintenance/reliability-governance-learning/closure')
    def get_closure(organization_id:str,period_key:str,request:Request,entity_id:str|None=None):
        _perm(e,request,'maintenance_reliability_governance_learning_closure.view'); _valid(period_key)
        q='SELECT * FROM maintenance_reliability_governance_learning_closure WHERE organization_id=:o AND period_key=:p'; par={'o':organization_id,'p':period_key}
        if entity_id: q+=' AND entity_id=:e'; par['e']=entity_id
        with e.connect() as c: rows=c.execute(text(q+' ORDER BY entity_id'),par).mappings().all()
        return {'closures':[dict(x) for x in rows],'automatic_operational_mutation':False,'causal_attribution':False}
    @app.post('/v90fl/maintenance/reliability-governance-learning/knowledge')
    def knowledge(body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_governance_learning_closure.manage')
        o,ei,p=body.get('organization_id'),body.get('entity_id'),body.get('period_key'); title=str(body.get('title') or '').strip(); lesson=str(body.get('lesson') or '').strip(); practice=str(body.get('standard_practice') or '').strip(); ev=str(body.get('evidence_note') or '').strip(); typ=str(body.get('knowledge_type') or '').upper()
        if not all([o,ei,p,title,lesson,practice,ev,typ]): raise HTTPException(400,'organization_id, entity_id, period_key, knowledge_type, title, lesson, standard_practice and evidence_note are required')
        _valid(p); kid=str(uuid4())
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_reliability_governance_learning_knowledge(knowledge_id,organization_id,entity_id,period_key,source_execution_id,source_benefit_id,knowledge_type,title,lesson,standard_practice,evidence_note,owner_user_id,due_date,created_by) VALUES(:id,:o,:e,:p,:x,:b,:t,:ti,:l,:s,:ev,:owner,:due,:u)'''),{'id':kid,'o':o,'e':ei,'p':p,'x':body.get('source_execution_id'),'b':body.get('source_benefit_id'),'t':typ,'ti':title,'l':lesson,'s':practice,'ev':ev,'owner':body.get('owner_user_id'),'due':body.get('due_date'),'u':str(u.user_id)})
        return {'knowledge_id':kid,'status':'PROPOSED','automatic_operational_mutation':False}
    @app.get('/v90fl/maintenance/reliability-governance-learning/knowledge')
    def list_knowledge(organization_id:str,period_key:str,request:Request,entity_id:str|None=None,status:str|None=None):
        _perm(e,request,'maintenance_reliability_governance_learning_closure.view'); _valid(period_key)
        q='SELECT * FROM maintenance_reliability_governance_learning_knowledge WHERE organization_id=:o AND period_key=:p'; par={'o':organization_id,'p':period_key}
        if entity_id: q+=' AND entity_id=:e'; par['e']=entity_id
        if status: q+=' AND status=:s'; par['s']=status.upper()
        with e.connect() as c: rows=c.execute(text(q+' ORDER BY created_at DESC'),par).mappings().all()
        return {'knowledge':[dict(x) for x in rows]}
    @app.post('/v90fl/maintenance/reliability-governance-learning/knowledge/{knowledge_id}/approve')
    def approve(knowledge_id:str,body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_governance_learning_closure.manage'); note=str(body.get('approval_note') or '').strip(); ev=str(body.get('evidence_note') or '').strip()
        if not note or not ev: raise HTTPException(400,'approval_note and evidence_note are required')
        with e.begin() as c:
            r=c.execute(text("UPDATE maintenance_reliability_governance_learning_knowledge SET status='APPROVED',evidence_note=evidence_note || ' | Approval: ' || :ev,standard_practice=standard_practice || ' | Approval: ' || :n,approved_by=:u,approved_at=CURRENT_TIMESTAMP WHERE knowledge_id=:id AND status='PROPOSED' RETURNING knowledge_id"),{'ev':ev,'n':note,'u':str(u.user_id),'id':knowledge_id}).first()
            if not r: raise HTTPException(404,'proposed knowledge record not found')
        return {'knowledge_id':knowledge_id,'status':'APPROVED','evidence_recorded':True}
    @app.post('/v90fl/maintenance/reliability-governance-learning/knowledge/{knowledge_id}/retire')
    def retire(knowledge_id:str,body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_governance_learning_closure.manage'); note=str(body.get('retirement_note') or '').strip(); ev=str(body.get('evidence_note') or '').strip()
        if not note or not ev: raise HTTPException(400,'retirement_note and evidence_note are required')
        with e.begin() as c:
            r=c.execute(text("UPDATE maintenance_reliability_governance_learning_knowledge SET status='RETIRED',evidence_note=evidence_note || ' | Retirement: ' || :ev,resolved_by=:u,resolved_at=CURRENT_TIMESTAMP WHERE knowledge_id=:id AND status='APPROVED' RETURNING knowledge_id"),{'ev':ev,'u':str(u.user_id),'id':knowledge_id}).first()
            if not r: raise HTTPException(404,'approved knowledge record not found')
        return {'knowledge_id':knowledge_id,'status':'RETIRED','evidence_recorded':True}
    @app.get('/ui/maintenance-reliability-governance-learning-closure')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-reliability-governance-learning-closure.html')

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

def ensure_v90fg_schema(e):
    with e.begin() as c:
        stmts=[
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_effectiveness_snapshot(
            snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            action_count INTEGER NOT NULL DEFAULT 0, approved_action_count INTEGER NOT NULL DEFAULT 0,
            completed_action_count INTEGER NOT NULL DEFAULT 0, overdue_action_count INTEGER NOT NULL DEFAULT 0,
            assessed_action_count INTEGER NOT NULL DEFAULT 0, effective_action_count INTEGER NOT NULL DEFAULT 0,
            ineffective_action_count INTEGER NOT NULL DEFAULT 0, total_breakdown_reduction_pct NUMERIC NOT NULL DEFAULT 0,
            downtime_reduction_hours NUMERIC NOT NULL DEFAULT 0, maintenance_cost_impact NUMERIC NOT NULL DEFAULT 0,
            action_completion_pct NUMERIC NOT NULL DEFAULT 0, benefit_assessment_pct NUMERIC NOT NULL DEFAULT 0,
            effectiveness_pct NUMERIC NOT NULL DEFAULT 0, executive_action_score NUMERIC NOT NULL DEFAULT 0,
            assessment TEXT NOT NULL DEFAULT 'NO_BASELINE', status TEXT NOT NULL DEFAULT 'OPEN', recommendation TEXT,
            created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key))''',
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_effectiveness_review(
            review_id TEXT PRIMARY KEY, action_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            period_key TEXT NOT NULL, assessment TEXT NOT NULL, review_note TEXT NOT NULL, evidence_note TEXT NOT NULL,
            reviewed_by TEXT NOT NULL, reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(action_id))''',
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_effectiveness_close(
            close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            action_count INTEGER NOT NULL DEFAULT 0, unassessed_action_count INTEGER NOT NULL DEFAULT 0,
            closed_by TEXT NOT NULL, closure_note TEXT, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key))''',
        'CREATE INDEX IF NOT EXISTS ix_reliability_exec_effectiveness_scope ON maintenance_reliability_executive_effectiveness_snapshot(organization_id,entity_id,period_key,status)',
        'CREATE INDEX IF NOT EXISTS ix_reliability_exec_effectiveness_review ON maintenance_reliability_executive_effectiveness_review(organization_id,entity_id,period_key,assessment)']
        for s in stmts: c.execute(text(s))
        for p,n in [('maintenance_reliability_effectiveness.view','View Reliability Executive Action Effectiveness'),('maintenance_reliability_effectiveness.manage','Review Reliability Executive Action Benefits'),('maintenance_reliability_effectiveness.close','Close Reliability Executive Effectiveness Period')]:
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"),{'p':p,'n':n})

def _snapshot(e,o,ei,p,u):
    with e.connect() as c:
        actions=c.execute(text("SELECT * FROM maintenance_reliability_executive_action WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':p}).mappings().all()
        ex=c.execute(text("SELECT * FROM maintenance_reliability_action_execution WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':p}).mappings().all()
        reviews=c.execute(text("SELECT action_id,assessment FROM maintenance_reliability_executive_effectiveness_review WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':p}).mappings().all()
        ben=c.execute(text("SELECT COALESCE(SUM(downtime_reduction_hours),0),COALESCE(SUM(maintenance_cost_impact),0),COALESCE(AVG(effectiveness_score),0) FROM maintenance_reliability_benefit_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':p}).first()
    amap={r['action_id']:r for r in reviews}; byaction={r['action_id']:r for r in ex}
    total=len(actions); approved=sum(1 for a in actions if a['status']=='APPROVED'); completed=sum(1 for a in actions if a['status']=='COMPLETED')
    overdue=sum(1 for a in actions if a['status'] in ('PROPOSED','APPROVED','DEFERRED') and a['due_date'] is not None and str(a['due_date']) < __import__('datetime').date.today().isoformat())
    assessed=sum(1 for a in actions if a['action_id'] in amap); effective=sum(1 for r in reviews if r['assessment']=='EFFECTIVE'); ineffective=sum(1 for r in reviews if r['assessment']=='INEFFECTIVE')
    completion=_d(completed*100/total if total else 100); assess_pct=_d(assessed*100/total if total else 100); eff_pct=_d(effective*100/assessed if assessed else 0)
    benefit_score=_d(ben[2] if ben else 0)
    score=max(Decimal('0'),min(Decimal('100'),completion*Decimal('.35')+assess_pct*Decimal('.20')+eff_pct*Decimal('.20')+benefit_score*Decimal('.25')))
    assessment='EFFECTIVE' if score>=85 and (not assessed or ineffective==0) else ('WATCH' if score>=70 else ('AT_RISK' if total else 'NO_BASELINE'))
    rec='Continue monitoring realized benefits and close completed actions with evidence.' if assessment=='EFFECTIVE' else ('Review unassessed or ineffective actions and verify benefit evidence.' if assessment!='NO_BASELINE' else 'Generate and execute executive actions before assessing effectiveness.')
    vals={'id':str(uuid4()),'o':o,'e':ei,'p':p,'ac':total,'ap':approved,'cc':completed,'ov':overdue,'as':assessed,'ef':effective,'in':ineffective,'dr':0,'dh':float(_d(ben[0] if ben else 0)),'mc':float(_d(ben[1] if ben else 0)),'cp':float(completion),'bp':float(assess_pct),'ep':float(eff_pct),'es':float(score),'a':assessment,'r':rec,'u':str(u.user_id)}
    with e.begin() as c:
        c.execute(text('''INSERT INTO maintenance_reliability_executive_effectiveness_snapshot(snapshot_id,organization_id,entity_id,period_key,action_count,approved_action_count,completed_action_count,overdue_action_count,assessed_action_count,effective_action_count,ineffective_action_count,total_breakdown_reduction_pct,downtime_reduction_hours,maintenance_cost_impact,action_completion_pct,benefit_assessment_pct,effectiveness_pct,executive_action_score,assessment,status,recommendation,created_by) VALUES(:id,:o,:e,:p,:ac,:ap,:cc,:ov,:as,:ef,:in,:dr,:dh,:mc,:cp,:bp,:ep,:es,:a,'OPEN',:r,:u) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET action_count=:ac,approved_action_count=:ap,completed_action_count=:cc,overdue_action_count=:ov,assessed_action_count=:as,effective_action_count=:ef,ineffective_action_count=:in,total_breakdown_reduction_pct=:dr,downtime_reduction_hours=:dh,maintenance_cost_impact=:mc,action_completion_pct=:cp,benefit_assessment_pct=:bp,effectiveness_pct=:ep,executive_action_score=:es,assessment=:a,status='OPEN',recommendation=:r,created_by=:u,created_at=CURRENT_TIMESTAMP'''),vals)
        row=c.execute(text('SELECT * FROM maintenance_reliability_executive_effectiveness_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':p}).mappings().first()
    return dict(row)

def register_v90fg_routes(app:FastAPI,e):
    ensure_v90fg_schema(e)
    @app.post('/v90fg/maintenance/reliability-effectiveness/snapshot')
    def snapshot(body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_effectiveness.manage'); o,ei,p=body.get('organization_id'),body.get('entity_id'),body.get('period_key')
        if not o or not ei or not p: raise HTTPException(400,'organization_id, entity_id and period_key are required')
        _valid(p); return {'snapshot':_snapshot(e,o,ei,p,u),'automatic_operational_mutation':False,'causal_attribution':False}
    @app.get('/v90fg/maintenance/reliability-effectiveness/dashboard')
    def dashboard(organization_id:str,period_key:str,request:Request,entity_id:str|None=None):
        _perm(e,request,'maintenance_reliability_effectiveness.view'); _valid(period_key)
        with e.connect() as c:
            q='SELECT * FROM maintenance_reliability_executive_effectiveness_snapshot WHERE organization_id=:o AND period_key=:p'; par={'o':organization_id,'p':period_key}
            if entity_id: q+=' AND entity_id=:e'; par['e']=entity_id
            rows=c.execute(text(q+' ORDER BY executive_action_score ASC,entity_id'),par).mappings().all()
            reviews=c.execute(text("SELECT * FROM maintenance_reliability_executive_effectiveness_review WHERE organization_id=:o AND period_key=:p ORDER BY reviewed_at DESC"),{'o':organization_id,'p':period_key}).mappings().all()
        return {'organization_id':organization_id,'period_key':period_key,'entity_count':len(rows),'average_action_score':float(_d(sum((_d(r['executive_action_score']) for r in rows),Decimal('0'))/len(rows))) if rows else 0,'rows':[dict(r) for r in rows],'reviews':[dict(r) for r in reviews],'automatic_operational_mutation':False,'causal_attribution':False}
    @app.get('/v90fg/maintenance/reliability-effectiveness/actions')
    def actions(organization_id:str,period_key:str,request:Request,entity_id:str|None=None):
        _perm(e,request,'maintenance_reliability_effectiveness.view'); _valid(period_key)
        with e.connect() as c:
            q='''SELECT a.*, r.assessment AS benefit_assessment, r.review_note, r.evidence_note FROM maintenance_reliability_executive_action a LEFT JOIN maintenance_reliability_executive_effectiveness_review r ON r.action_id=a.action_id WHERE a.organization_id=:o AND a.period_key=:p'''; par={'o':organization_id,'p':period_key}
            if entity_id: q+=' AND a.entity_id=:e'; par['e']=entity_id
            rows=c.execute(text(q+' ORDER BY CASE a.priority WHEN \'CRITICAL\' THEN 1 WHEN \'HIGH\' THEN 2 WHEN \'MEDIUM\' THEN 3 ELSE 4 END,a.created_at DESC'),par).mappings().all()
        return {'count':len(rows),'actions':[dict(r) for r in rows]}
    @app.post('/v90fg/maintenance/reliability-effectiveness/actions/{action_id}/review')
    def review(action_id:str,body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_effectiveness.manage'); assessment=str(body.get('assessment') or '').upper()
        if assessment not in {'EFFECTIVE','INEFFECTIVE','NOT_ASSESSED'}: raise HTTPException(400,'assessment must be EFFECTIVE, INEFFECTIVE or NOT_ASSESSED')
        note=str(body.get('review_note') or '').strip(); evidence=str(body.get('evidence_note') or '').strip()
        if not note or not evidence: raise HTTPException(400,'review_note and evidence_note are required')
        with e.begin() as c:
            a=c.execute(text("SELECT organization_id,entity_id,period_key,status FROM maintenance_reliability_executive_action WHERE action_id=:i"),{'i':action_id}).mappings().first()
            if not a: raise HTTPException(404,'executive action not found')
            if a['status']!='COMPLETED': raise HTTPException(409,'only COMPLETED executive actions can be effectiveness-reviewed')
            c.execute(text('''INSERT INTO maintenance_reliability_executive_effectiveness_review(review_id,action_id,organization_id,entity_id,period_key,assessment,review_note,evidence_note,reviewed_by) VALUES(:i,:a,:o,:e,:p,:s,:n,:ev,:u) ON CONFLICT(action_id) DO UPDATE SET assessment=:s,review_note=:n,evidence_note=:ev,reviewed_by=:u,reviewed_at=CURRENT_TIMESTAMP'''),{'i':str(uuid4()),'a':action_id,'o':a['organization_id'],'e':a['entity_id'],'p':a['period_key'],'s':assessment,'n':note,'ev':evidence,'u':str(u.user_id)})
        return {'action_id':action_id,'assessment':assessment,'evidence_recorded':True,'automatic_operational_mutation':False,'causal_attribution':False}
    @app.post('/v90fg/maintenance/reliability-effectiveness/{period_key}/close')
    def close(period_key:str,body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_effectiveness.close'); _valid(period_key); o,ei=body.get('organization_id'),body.get('entity_id')
        if not o or not ei: raise HTTPException(400,'organization_id and entity_id are required')
        with e.begin() as c:
            total=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_executive_action WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':period_key}).scalar() or 0
            unass=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_executive_action a LEFT JOIN maintenance_reliability_executive_effectiveness_review r ON r.action_id=a.action_id WHERE a.organization_id=:o AND a.entity_id=:e AND a.period_key=:p AND a.status='COMPLETED' AND r.action_id IS NULL"),{'o':o,'e':ei,'p':period_key}).scalar() or 0
            if unass and not body.get('force'): raise HTTPException(409,f'{unass} completed action(s) lack effectiveness review; review or force=true')
            c.execute(text('''INSERT INTO maintenance_reliability_executive_effectiveness_close(close_id,organization_id,entity_id,period_key,action_count,unassessed_action_count,closed_by,closure_note) VALUES(:i,:o,:e,:p,:t,:u,:by,:n) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET action_count=:t,unassessed_action_count=:u,closed_by=:by,closure_note=:n,closed_at=CURRENT_TIMESTAMP'''),{'i':str(uuid4()),'o':o,'e':ei,'p':period_key,'t':int(total),'u':int(unass),'by':str(u.user_id),'n':body.get('closure_note')})
        return {'organization_id':o,'entity_id':ei,'period_key':period_key,'status':'CLOSED','action_count':int(total),'unassessed_action_count':int(unass),'forced':bool(body.get('force'))}
    @app.get('/ui/maintenance-reliability-effectiveness')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-reliability-effectiveness.html')

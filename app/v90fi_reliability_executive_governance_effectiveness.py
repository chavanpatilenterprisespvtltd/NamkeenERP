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

def ensure_v90fi_schema(e):
    with e.begin() as c:
        stmts=[
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_governance_effectiveness_snapshot(
            snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            escalation_count INTEGER NOT NULL DEFAULT 0, resolved_escalation_count INTEGER NOT NULL DEFAULT 0,
            overdue_escalation_count INTEGER NOT NULL DEFAULT 0, evidence_complete_count INTEGER NOT NULL DEFAULT 0,
            evidence_gap_count INTEGER NOT NULL DEFAULT 0, action_count INTEGER NOT NULL DEFAULT 0,
            completed_action_count INTEGER NOT NULL DEFAULT 0, effective_action_count INTEGER NOT NULL DEFAULT 0,
            ineffective_action_count INTEGER NOT NULL DEFAULT 0, resolution_rate NUMERIC NOT NULL DEFAULT 0,
            effectiveness_rate NUMERIC NOT NULL DEFAULT 0, governance_effectiveness_score NUMERIC NOT NULL DEFAULT 0,
            assessment TEXT NOT NULL DEFAULT 'NO_BASELINE', status TEXT NOT NULL DEFAULT 'OPEN', recommendation TEXT,
            created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key))''',
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_governance_effectiveness_action(
            review_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            escalation_id TEXT, action_id TEXT, outcome TEXT NOT NULL, finding TEXT NOT NULL, evidence_note TEXT NOT NULL,
            owner_user_id TEXT, due_date DATE, status TEXT NOT NULL DEFAULT 'OPEN', resolved_by TEXT, resolved_at TIMESTAMP,
            created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        '''CREATE TABLE IF NOT EXISTS maintenance_reliability_executive_governance_effectiveness_close(
            close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
            governance_effectiveness_score NUMERIC NOT NULL DEFAULT 0, open_review_count INTEGER NOT NULL DEFAULT 0,
            closed_by TEXT NOT NULL, closure_note TEXT, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key))''',
        'CREATE INDEX IF NOT EXISTS ix_rel_exec_gov_eff_scope ON maintenance_reliability_executive_governance_effectiveness_snapshot(organization_id,entity_id,period_key,status)',
        'CREATE INDEX IF NOT EXISTS ix_rel_exec_gov_eff_review ON maintenance_reliability_executive_governance_effectiveness_action(organization_id,entity_id,period_key,status)']
        for s in stmts: c.execute(text(s))
        for p,n in [('maintenance_reliability_governance_effectiveness.view','View Reliability Executive Governance Effectiveness'),('maintenance_reliability_governance_effectiveness.manage','Manage Reliability Executive Governance Reviews'),('maintenance_reliability_governance_effectiveness.close','Close Reliability Executive Governance Effectiveness Period')]:
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"),{'p':p,'n':n})

def _snapshot(e,o,ei,p,u):
    with e.connect() as c:
        esc=c.execute(text("SELECT * FROM maintenance_reliability_executive_governance_escalation WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':p}).mappings().all()
        acts=c.execute(text("SELECT action_id,status FROM maintenance_reliability_executive_action WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':p}).mappings().all()
        reviews=c.execute(text("SELECT outcome,evidence_note,status FROM maintenance_reliability_executive_governance_effectiveness_action WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':p}).mappings().all()
    resolved=sum(1 for x in esc if x['status']=='RESOLVED'); overdue=sum(1 for x in esc if x['status']=='OPEN' and x['due_date'] and str(x['due_date']) < __import__('datetime').date.today().isoformat())
    complete=sum(1 for x in acts if x['status']=='COMPLETED'); effective=sum(1 for x in reviews if x['outcome']=='EFFECTIVE'); ineffective=sum(1 for x in reviews if x['outcome']=='INEFFECTIVE')
    evidence_ok=sum(1 for x in reviews if (x['evidence_note'] or '').strip()); gaps=len(reviews)-evidence_ok
    rr=_d((Decimal(resolved)*100/Decimal(len(esc))) if esc else 0); er=_d((Decimal(effective)*100/Decimal(effective+ineffective)) if effective+ineffective else 0)
    score=max(Decimal('0'),min(Decimal('100'),_d(rr*Decimal('.45')+er*Decimal('.35')+Decimal('100')-Decimal(min(overdue,5))*Decimal('10')-Decimal(min(gaps,5))*Decimal('5'))))
    assessment='EFFECTIVE' if score>=90 and not overdue and not gaps else ('WATCH' if score>=75 else ('AT_RISK' if esc or acts else 'NO_BASELINE'))
    rec='Maintain governance controls and evidence discipline.' if assessment=='EFFECTIVE' else ('Resolve overdue escalations and evidence gaps.' if assessment!='NO_BASELINE' else 'Establish executive governance reviews before measuring effectiveness.')
    vals={'id':str(uuid4()),'o':o,'e':ei,'p':p,'ec':len(esc),'rc':resolved,'ov':overdue,'eo':evidence_ok,'eg':gaps,'ac':len(acts),'cc':complete,'ef':effective,'ine':ineffective,'rr':float(rr),'er':float(er),'gs':float(score),'a':assessment,'r':rec,'u':str(u.user_id)}
    with e.begin() as c:
        c.execute(text('''INSERT INTO maintenance_reliability_executive_governance_effectiveness_snapshot(snapshot_id,organization_id,entity_id,period_key,escalation_count,resolved_escalation_count,overdue_escalation_count,evidence_complete_count,evidence_gap_count,action_count,completed_action_count,effective_action_count,ineffective_action_count,resolution_rate,effectiveness_rate,governance_effectiveness_score,assessment,status,recommendation,created_by) VALUES(:id,:o,:e,:p,:ec,:rc,:ov,:eo,:eg,:ac,:cc,:ef,:ine,:rr,:er,:gs,:a,'OPEN',:r,:u) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET escalation_count=:ec,resolved_escalation_count=:rc,overdue_escalation_count=:ov,evidence_complete_count=:eo,evidence_gap_count=:eg,action_count=:ac,completed_action_count=:cc,effective_action_count=:ef,ineffective_action_count=:ine,resolution_rate=:rr,effectiveness_rate=:er,governance_effectiveness_score=:gs,assessment=:a,status='OPEN',recommendation=:r,created_by=:u,created_at=CURRENT_TIMESTAMP'''),vals)
        row=c.execute(text('SELECT * FROM maintenance_reliability_executive_governance_effectiveness_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':p}).mappings().first()
    return dict(row)

def register_v90fi_routes(app:FastAPI,e):
    ensure_v90fi_schema(e)
    @app.post('/v90fi/maintenance/reliability-governance-effectiveness/snapshot')
    def snapshot(body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_governance_effectiveness.manage'); o,ei,p=body.get('organization_id'),body.get('entity_id'),body.get('period_key')
        if not o or not ei or not p: raise HTTPException(400,'organization_id, entity_id and period_key are required')
        _valid(p); return {'snapshot':_snapshot(e,o,ei,p,u),'automatic_operational_mutation':False,'causal_attribution':False}
    @app.get('/v90fi/maintenance/reliability-governance-effectiveness/dashboard')
    def dashboard(organization_id:str,period_key:str,request:Request,entity_id:str|None=None):
        _perm(e,request,'maintenance_reliability_governance_effectiveness.view'); _valid(period_key)
        with e.connect() as c:
            q='SELECT * FROM maintenance_reliability_executive_governance_effectiveness_snapshot WHERE organization_id=:o AND period_key=:p'; par={'o':organization_id,'p':period_key}
            if entity_id: q+=' AND entity_id=:e'; par['e']=entity_id
            rows=c.execute(text(q+' ORDER BY governance_effectiveness_score ASC,entity_id'),par).mappings().all()
            rev=c.execute(text("SELECT * FROM maintenance_reliability_executive_governance_effectiveness_action WHERE organization_id=:o AND period_key=:p AND status='OPEN' ORDER BY due_date"),{'o':organization_id,'p':period_key}).mappings().all()
        return {'organization_id':organization_id,'period_key':period_key,'entity_count':len(rows),'average_score':float(_d(sum((_d(r['governance_effectiveness_score']) for r in rows),Decimal('0'))/len(rows))) if rows else 0,'rows':[dict(r) for r in rows],'open_reviews':[dict(x) for x in rev],'automatic_operational_mutation':False,'causal_attribution':False}
    @app.post('/v90fi/maintenance/reliability-governance-effectiveness/reviews')
    def review(body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_governance_effectiveness.manage'); o,ei,p=body.get('organization_id'),body.get('entity_id'),body.get('period_key'); outcome=str(body.get('outcome') or '').upper(); finding=str(body.get('finding') or '').strip(); ev=str(body.get('evidence_note') or '').strip()
        if not all([o,ei,p,finding,ev]): raise HTTPException(400,'organization_id, entity_id, period_key, finding and evidence_note are required')
        _valid(p)
        if outcome not in ('EFFECTIVE','INEFFECTIVE','NEEDS_FOLLOWUP'): raise HTTPException(400,'outcome must be EFFECTIVE, INEFFECTIVE or NEEDS_FOLLOWUP')
        rid=str(uuid4())
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_reliability_executive_governance_effectiveness_action(review_id,organization_id,entity_id,period_key,escalation_id,action_id,outcome,finding,evidence_note,owner_user_id,due_date,created_by) VALUES(:id,:o,:e,:p,:x,:a,:out,:f,:ev,:owner,:due,:u)'''),{'id':rid,'o':o,'e':ei,'p':p,'x':body.get('escalation_id'),'a':body.get('action_id'),'out':outcome,'f':finding,'ev':ev,'owner':body.get('owner_user_id'),'due':body.get('due_date'),'u':str(u.user_id)})
        return {'review_id':rid,'status':'OPEN','evidence_recorded':True,'automatic_operational_mutation':False}
    @app.post('/v90fi/maintenance/reliability-governance-effectiveness/reviews/{review_id}/resolve')
    def resolve(review_id:str,body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_governance_effectiveness.manage')
        note=str(body.get('resolution_note') or '').strip(); ev=str(body.get('evidence_note') or '').strip()
        if not note or not ev: raise HTTPException(400,'resolution_note and evidence_note are required')
        with e.begin() as c:
            r=c.execute(text("UPDATE maintenance_reliability_executive_governance_effectiveness_action SET status='RESOLVED',evidence_note=:ev,finding=COALESCE(finding,'') || ' | Resolution: ' || :n,resolved_by=:u,resolved_at=CURRENT_TIMESTAMP WHERE review_id=:id AND status='OPEN' RETURNING review_id"),{'ev':ev,'n':note,'u':str(u.user_id),'id':review_id}).first()
            if not r: raise HTTPException(404,'open governance review not found')
        return {'review_id':review_id,'status':'RESOLVED','evidence_recorded':True}
    @app.post('/v90fi/maintenance/reliability-governance-effectiveness/{period_key}/close')
    def close(period_key:str,body:dict,request:Request):
        u=_perm(e,request,'maintenance_reliability_governance_effectiveness.close'); _valid(period_key); o,ei=body.get('organization_id'),body.get('entity_id')
        if not o or not ei: raise HTTPException(400,'organization_id and entity_id are required')
        with e.connect() as c:
            score=c.execute(text('SELECT governance_effectiveness_score FROM maintenance_reliability_executive_governance_effectiveness_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':period_key}).scalar() or 0
            openr=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_executive_governance_effectiveness_action WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='OPEN'"),{'o':o,'e':ei,'p':period_key}).scalar() or 0
        if openr and not body.get('force'): raise HTTPException(409,f'cannot close: {openr} open governance review(s)')
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_reliability_executive_governance_effectiveness_close(close_id,organization_id,entity_id,period_key,governance_effectiveness_score,open_review_count,closed_by,closure_note) VALUES(:id,:o,:e,:p,:s,:r,:u,:n) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET governance_effectiveness_score=:s,open_review_count=:r,closed_by=:u,closure_note=:n,closed_at=CURRENT_TIMESTAMP'''),{'id':str(uuid4()),'o':o,'e':ei,'p':period_key,'s':float(score),'r':int(openr),'u':str(u.user_id),'n':body.get('closure_note')})
            c.execute(text("UPDATE maintenance_reliability_executive_governance_effectiveness_snapshot SET status='CLOSED' WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':period_key})
        return {'organization_id':o,'entity_id':ei,'period_key':period_key,'status':'CLOSED','open_review_count':int(openr),'forced':bool(body.get('force'))}
    @app.get('/ui/maintenance-reliability-governance-effectiveness')
    def ui(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-reliability-governance-effectiveness.html')

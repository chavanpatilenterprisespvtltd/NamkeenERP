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
 return u.user_id
def valid(pk):
 try:
  y,m=map(int,pk.split('-'))
  if y<2000 or not 1<=m<=12: raise ValueError
 except Exception: raise HTTPException(400,'period_key must be YYYY-MM')

def register_v90eu_routes(app:FastAPI,e):
 with e.begin() as c:
  for p,n in [('maintenance_reliability_governance.view','View Reliability Governance'),('maintenance_reliability_governance.manage','Manage Reliability Governance'),('maintenance_reliability_governance.approve','Approve Reliability Governance Actions'),('maintenance_reliability_governance.close','Close Reliability Governance')]:
   c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
  c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_governance_snapshot(governance_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_key TEXT NOT NULL,target_effectiveness_score NUMERIC NOT NULL DEFAULT 60,realized_effectiveness_score NUMERIC NOT NULL DEFAULT 0,target_breakdown_reduction_pct NUMERIC NOT NULL DEFAULT 0,realized_breakdown_reduction_pct NUMERIC NOT NULL DEFAULT 0,target_downtime_reduction_hours NUMERIC NOT NULL DEFAULT 0,realized_downtime_reduction_hours NUMERIC NOT NULL DEFAULT 0,target_maintenance_cost_impact NUMERIC NOT NULL DEFAULT 0,realized_maintenance_cost_impact NUMERIC NOT NULL DEFAULT 0,approved_actions INTEGER NOT NULL DEFAULT 0,completed_actions INTEGER NOT NULL DEFAULT 0,overdue_actions INTEGER NOT NULL DEFAULT 0,open_change_proposals INTEGER NOT NULL DEFAULT 0,governance_score NUMERIC NOT NULL DEFAULT 0,assessment TEXT NOT NULL DEFAULT 'REVIEW_REQUIRED',recommendation TEXT,status TEXT NOT NULL DEFAULT 'OPEN',created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,period_key))'''))
  c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_change_proposal(proposal_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_key TEXT NOT NULL,execution_id TEXT,action_id TEXT,work_center_id TEXT,change_type TEXT NOT NULL,proposed_change TEXT NOT NULL,rationale TEXT NOT NULL,target_value NUMERIC,owner_user_id TEXT,due_date DATE,status TEXT NOT NULL DEFAULT 'PROPOSED',decision_note TEXT,approved_by TEXT,approved_at TIMESTAMP,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
  c.execute(text('CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_change_proposal_scope ON maintenance_reliability_change_proposal(organization_id,entity_id,period_key,status,work_center_id)'))
  c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_governance_close(close_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_key TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'CLOSED',closed_by TEXT NOT NULL,closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,period_key))'''))

 @app.post('/v90eu/maintenance/reliability-governance/snapshot')
 def snapshot(body:dict,request:Request):
  uid=perm(e,request,'maintenance_reliability_governance.manage')
  for k in ('organization_id','entity_id','period_key'):
   if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
  o,ei,pk=body['organization_id'],body['entity_id'],body['period_key']; valid(pk)
  ts=d(body.get('target_effectiveness_score',60)); tb=d(body.get('target_breakdown_reduction_pct',0)); td=d(body.get('target_downtime_reduction_hours',0)); tc=d(body.get('target_maintenance_cost_impact',0))
  with e.connect() as c:
   if c.execute(text('SELECT 1 FROM maintenance_reliability_governance_close WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':pk}).first(): raise HTTPException(409,'period is closed')
   ex=c.execute(text('SELECT * FROM maintenance_reliability_action_execution WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':pk}).mappings().all()
   approved=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_action WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='APPROVED'"),{'o':o,'e':ei,'p':pk}).scalar() or 0
   props=c.execute(text("SELECT COUNT(*) FROM maintenance_reliability_change_proposal WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND status='PROPOSED'"),{'o':o,'e':ei,'p':pk}).scalar() or 0
  completed=[x for x in ex if str(x['status']).upper()=='COMPLETED']; overdue=sum(1 for x in ex if str(x['status']).upper() not in ('COMPLETED','CANCELLED') and x['due_date'] and str(x['due_date']) < pk+'-01')
  realized=d(sum(d(x['effectiveness_score']) for x in completed)/len(completed)) if completed else d(0); br=d(sum(d(x['breakdown_reduction_pct']) for x in completed)/len(completed)) if completed else d(0); dh=d(sum(d(x['downtime_reduction_hours']) for x in completed)); ci=d(sum(d(x['maintenance_cost_impact']) for x in completed))
  comps=[d(realized/ts*100) if ts else d(0),d(br/tb*100) if tb else d(100),d(dh/td*100) if td else d(100),d(ci/tc*100) if tc else d(100)]; gs=d(max(0,min(100,sum(comps)/4)))
  assessment='TARGET_MET' if gs>=80 and overdue==0 else ('ON_TRACK' if gs>=60 else 'REVIEW_REQUIRED'); rec='Close successful actions and document evidence.' if assessment=='TARGET_MET' else ('Escalate overdue owners and review proposed operational changes.' if overdue else 'Review benefit gaps and prioritize the highest-impact reliability actions.')
  with e.begin() as c:
   c.execute(text('''INSERT INTO maintenance_reliability_governance_snapshot(governance_id,organization_id,entity_id,period_key,target_effectiveness_score,realized_effectiveness_score,target_breakdown_reduction_pct,realized_breakdown_reduction_pct,target_downtime_reduction_hours,realized_downtime_reduction_hours,target_maintenance_cost_impact,realized_maintenance_cost_impact,approved_actions,completed_actions,overdue_actions,open_change_proposals,governance_score,assessment,recommendation,status,created_by) VALUES(:i,:o,:e,:p,:ts,:rs,:tb,:rb,:td,:rd,:tc,:rc,:aa,:ca,:oa,:cp,:gs,:a,:r,'OPEN',:u) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET target_effectiveness_score=:ts,realized_effectiveness_score=:rs,target_breakdown_reduction_pct=:tb,realized_breakdown_reduction_pct=:rb,target_downtime_reduction_hours=:td,realized_downtime_reduction_hours=:rd,target_maintenance_cost_impact=:tc,realized_maintenance_cost_impact=:rc,approved_actions=:aa,completed_actions=:ca,overdue_actions=:oa,open_change_proposals=:cp,governance_score=:gs,assessment=:a,recommendation=:r,status='OPEN',created_by=:u,created_at=CURRENT_TIMESTAMP'''),{'i':str(uuid4()),'o':o,'e':ei,'p':pk,'ts':float(ts),'rs':float(realized),'tb':float(tb),'rb':float(br),'td':float(td),'rd':float(dh),'tc':float(tc),'rc':float(ci),'aa':int(approved),'ca':len(completed),'oa':overdue,'cp':int(props),'gs':float(gs),'a':assessment,'r':rec,'u':uid})
  return {'period_key':pk,'governance_score':float(gs),'assessment':assessment,'approved_actions':int(approved),'completed_actions':len(completed),'overdue_actions':overdue,'open_change_proposals':int(props),'causal_attribution':False}

 @app.get('/v90eu/maintenance/reliability-governance/dashboard')
 def dashboard(request:Request,organization_id:str,entity_id:str,period_key:str):
  perm(e,request,'maintenance_reliability_governance.view'); valid(period_key)
  with e.connect() as c:
   g=c.execute(text('SELECT * FROM maintenance_reliability_governance_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().first(); p=c.execute(text('SELECT * FROM maintenance_reliability_change_proposal WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY created_at DESC'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all(); x=c.execute(text('SELECT * FROM maintenance_reliability_action_execution WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY created_at DESC'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
  return {'snapshot':dict(g) if g else None,'proposals':[dict(r) for r in p],'executions':[dict(r) for r in x],'causal_attribution':False}

 @app.post('/v90eu/maintenance/reliability-governance/change-proposals')
 def propose(body:dict,request:Request):
  uid=perm(e,request,'maintenance_reliability_governance.manage')
  for k in ('organization_id','entity_id','period_key','change_type','proposed_change','rationale'):
   if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
  valid(body['period_key']); o,ei,pk=body['organization_id'],body['entity_id'],body['period_key']
  with e.begin() as c:
   if c.execute(text('SELECT 1 FROM maintenance_reliability_governance_close WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':pk}).first(): raise HTTPException(409,'period is closed')
   pid=str(uuid4()); c.execute(text('''INSERT INTO maintenance_reliability_change_proposal(proposal_id,organization_id,entity_id,period_key,execution_id,action_id,work_center_id,change_type,proposed_change,rationale,target_value,owner_user_id,due_date,created_by) VALUES(:i,:o,:e,:p,:x,:a,:w,:t,:c,:r,:v,:owner,:due,:u)'''),{'i':pid,'o':o,'e':ei,'p':pk,'x':body.get('execution_id'),'a':body.get('action_id'),'w':body.get('work_center_id'),'t':body['change_type'],'c':body['proposed_change'],'r':body['rationale'],'v':body.get('target_value'),'owner':body.get('owner_user_id'),'due':body.get('due_date'),'u':uid})
  return {'proposal_id':pid,'status':'PROPOSED'}

 @app.post('/v90eu/maintenance/reliability-governance/change-proposals/{proposal_id}/approve')
 def approve(proposal_id:str,body:dict,request:Request):
  uid=perm(e,request,'maintenance_reliability_governance.approve')
  with e.begin() as c:
   r=c.execute(text("UPDATE maintenance_reliability_change_proposal SET status='APPROVED',approved_by=:u,approved_at=CURRENT_TIMESTAMP,decision_note=:n WHERE proposal_id=:i AND status='PROPOSED' RETURNING proposal_id"),{'u':uid,'n':body.get('decision_note'),'i':proposal_id}).first()
   if not r: raise HTTPException(404,'proposed change not found')
  return {'proposal_id':proposal_id,'status':'APPROVED'}

 @app.post('/v90eu/maintenance/reliability-governance/change-proposals/{proposal_id}/reject')
 def reject(proposal_id:str,body:dict,request:Request):
  uid=perm(e,request,'maintenance_reliability_governance.approve')
  with e.begin() as c:
   r=c.execute(text("UPDATE maintenance_reliability_change_proposal SET status='REJECTED',approved_by=:u,approved_at=CURRENT_TIMESTAMP,decision_note=:n WHERE proposal_id=:i AND status='PROPOSED' RETURNING proposal_id"),{'u':uid,'n':body.get('decision_note'),'i':proposal_id}).first()
   if not r: raise HTTPException(404,'proposed change not found')
  return {'proposal_id':proposal_id,'status':'REJECTED'}

 @app.post('/v90eu/maintenance/reliability-governance/{period_key}/close')
 def close(period_key:str,body:dict,request:Request):
  uid=perm(e,request,'maintenance_reliability_governance.close'); valid(period_key); o,ei=body.get('organization_id'),body.get('entity_id')
  if not o or not ei: raise HTTPException(400,'organization_id and entity_id are required')
  with e.begin() as c:
   c.execute(text('''INSERT INTO maintenance_reliability_governance_close(close_id,organization_id,entity_id,period_key,closed_by) VALUES(:i,:o,:e,:p,:u) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),{'i':str(uuid4()),'o':o,'e':ei,'p':period_key,'u':uid}); c.execute(text("UPDATE maintenance_reliability_governance_snapshot SET status='CLOSED' WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':period_key})
  return {'period_key':period_key,'status':'CLOSED'}

 @app.get('/ui/maintenance-reliability-governance')
 def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-reliability-governance.html')

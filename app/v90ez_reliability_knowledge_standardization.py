from __future__ import annotations
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def perm(e,r,p):
 u=authenticate(r); ps=permissions_for_user(e,u.user_id)
 if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
 return u

def register_v90ez_routes(app:FastAPI,e):
 with e.begin() as c:
  c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_knowledge_record(knowledge_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_key TEXT NOT NULL,source_type TEXT NOT NULL,source_id TEXT,work_center_id TEXT,knowledge_type TEXT NOT NULL,title TEXT NOT NULL,finding TEXT NOT NULL,evidence_note TEXT,effectiveness_score NUMERIC NOT NULL DEFAULT 0,recurrence_count INTEGER NOT NULL DEFAULT 0,recommendation TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'PROPOSED',approved_by TEXT,approved_at TIMESTAMP,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,source_type,source_id,knowledge_type))'''))
  c.execute(text('CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_knowledge_scope ON maintenance_reliability_knowledge_record(organization_id,entity_id,status,knowledge_type,work_center_id)'))
  c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_standard_recommendation(standard_id TEXT PRIMARY KEY,knowledge_id TEXT NOT NULL,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,work_center_id TEXT,standard_type TEXT NOT NULL,standard_text TEXT NOT NULL,rationale TEXT NOT NULL,version_no INTEGER NOT NULL DEFAULT 1,status TEXT NOT NULL DEFAULT 'PROPOSED',approved_by TEXT,approved_at TIMESTAMP,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(knowledge_id))'''))
  c.execute(text('CREATE INDEX IF NOT EXISTS ix_maintenance_reliability_standard_scope ON maintenance_reliability_standard_recommendation(organization_id,entity_id,status,standard_type,work_center_id)'))
  for p,n in [('maintenance_reliability_knowledge.view','View Reliability Knowledge'),('maintenance_reliability_knowledge.manage','Manage Reliability Knowledge'),('maintenance_reliability_knowledge.approve','Approve Reliability Standards')]:
   c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
 @app.post('/v90ez/maintenance/reliability-knowledge/generate')
 def generate(body:dict,request:Request):
  u=perm(e,request,'maintenance_reliability_knowledge.manage'); o=body.get('organization_id'); ei=body.get('entity_id'); pk=body.get('period_key')
  if not o or not ei or not pk: raise HTTPException(400,'organization_id, entity_id and period_key are required')
  with e.begin() as c:
   rows=c.execute(text("SELECT * FROM maintenance_reliability_continuous_improvement_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':o,'e':ei,'p':pk}).mappings().all()
   if not rows: raise HTTPException(404,'continuous-improvement learning snapshot not found')
   made=[]
   for x in rows:
    ktype='SUCCESSFUL_PRACTICE' if x['improvement_assessment']=='IMPROVING' and float(x['effectiveness_delta'] or 0)>=0 else ('RECURRING_FAILURE' if int(x['recurring_failure_flag'] or 0) else 'IMPROVEMENT_LESSON')
    rec=str(x['recommendation'] or 'Review reliability outcomes and retain evidence for governance review.')
    title='Reliability practice from '+pk
    finding=f"Assessment={x['improvement_assessment']}; control delta={x['control_score_delta']}; effectiveness delta={x['effectiveness_delta']}; recurring failure={x['recurring_failure_flag']}."
    kid=str(uuid4())
    c.execute(text('''INSERT INTO maintenance_reliability_knowledge_record(knowledge_id,organization_id,entity_id,period_key,source_type,source_id,knowledge_type,title,finding,evidence_note,effectiveness_score,recurrence_count,recommendation,created_by) VALUES(:id,:o,:e,:p,'CONTINUOUS_IMPROVEMENT',:sid,:k,:t,:f,:ev,:s,:r,:rec,:u) ON CONFLICT(organization_id,entity_id,source_type,source_id,knowledge_type) DO UPDATE SET finding=:f,evidence_note=:ev,effectiveness_score=:s,recurrence_count=:r,recommendation=:rec,status='PROPOSED',created_by=:u'''),{'id':kid,'o':o,'e':ei,'p':pk,'sid':x['learning_id'],'k':ktype,'t':title,'f':finding,'ev':'Derived from closed-loop reliability learning; observational, not causal.','s':float(x['current_effectiveness_score'] or 0),'r':int(x['recurring_failure_count'] or 0),'rec':rec,'u':str(u.user_id)})
    made=c.execute(text("SELECT knowledge_id,knowledge_type,title,status FROM maintenance_reliability_knowledge_record WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY created_at DESC"),{'o':o,'e':ei,'p':pk}).mappings().all()
  return {'period_key':pk,'count':len(made),'knowledge':[dict(x) for x in made],'causal_attribution':False}
 @app.post('/v90ez/maintenance/reliability-knowledge/{knowledge_id}/standard')
 def standard(knowledge_id:str,body:dict,request:Request):
  u=perm(e,request,'maintenance_reliability_knowledge.manage')
  with e.begin() as c:
   k=c.execute(text('SELECT * FROM maintenance_reliability_knowledge_record WHERE knowledge_id=:i'),{'i':knowledge_id}).mappings().first()
   if not k: raise HTTPException(404,'knowledge record not found')
   sid=str(uuid4()); st=body.get('standard_text') or k['recommendation']; typ=body.get('standard_type') or 'RELIABILITY_PRACTICE'
   c.execute(text('''INSERT INTO maintenance_reliability_standard_recommendation(standard_id,knowledge_id,organization_id,entity_id,work_center_id,standard_type,standard_text,rationale,created_by) VALUES(:id,:k,:o,:e,:w,:t,:s,:r,:u) ON CONFLICT(knowledge_id) DO UPDATE SET standard_text=:s,rationale=:r,status='PROPOSED',created_by=:u'''),{'id':sid,'k':knowledge_id,'o':k['organization_id'],'e':k['entity_id'],'w':k['work_center_id'],'t':typ,'s':st,'r':k['finding'],'u':str(u.user_id)})
  return {'knowledge_id':knowledge_id,'standard_id':sid,'status':'PROPOSED','approval_required':True}
 @app.post('/v90ez/maintenance/reliability-knowledge/standards/{standard_id}/approve')
 def approve(standard_id:str,request:Request):
  u=perm(e,request,'maintenance_reliability_knowledge.approve')
  with e.begin() as c:
   r=c.execute(text('SELECT * FROM maintenance_reliability_standard_recommendation WHERE standard_id=:i'),{'i':standard_id}).mappings().first()
   if not r: raise HTTPException(404,'standard not found')
   c.execute(text("UPDATE maintenance_reliability_standard_recommendation SET status='APPROVED',approved_by=:u,approved_at=CURRENT_TIMESTAMP WHERE standard_id=:i"),{'u':str(u.user_id),'i':standard_id})
  return {'standard_id':standard_id,'status':'APPROVED','operational_mutation':False}
 @app.get('/v90ez/maintenance/reliability-knowledge/dashboard')
 def dashboard(request:Request,organization_id:str,entity_id:str):
  perm(e,request,'maintenance_reliability_knowledge.view')
  with e.connect() as c:
   k=c.execute(text('SELECT * FROM maintenance_reliability_knowledge_record WHERE organization_id=:o AND entity_id=:e ORDER BY created_at DESC'),{'o':organization_id,'e':entity_id}).mappings().all(); s=c.execute(text('SELECT * FROM maintenance_reliability_standard_recommendation WHERE organization_id=:o AND entity_id=:e ORDER BY created_at DESC'),{'o':organization_id,'e':entity_id}).mappings().all()
  return {'knowledge':[dict(x) for x in k],'standards':[dict(x) for x in s],'approved_standard_count':sum(1 for x in s if x['status']=='APPROVED'),'causal_attribution':False}
 @app.get('/ui/maintenance-reliability-knowledge')
 def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-reliability-knowledge.html')

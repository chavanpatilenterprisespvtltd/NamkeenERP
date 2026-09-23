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

def register_v90eq_routes(app: FastAPI,e):
 with e.begin() as c:
  for p,n in [('maintenance_queue.view','View Maintenance Priority Queue'),('maintenance_queue.manage','Calculate Maintenance Priority Queue'),('maintenance_queue.close','Close Maintenance Priority Queue')]:
   c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
  c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_priority_snapshot(
 snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL,
 work_center_id TEXT, risk_score NUMERIC NOT NULL DEFAULT 0, risk_level TEXT NOT NULL DEFAULT 'LOW',
 breakdown_hours NUMERIC NOT NULL DEFAULT 0, breakdown_orders INTEGER NOT NULL DEFAULT 0,
 maintenance_cost NUMERIC NOT NULL DEFAULT 0, production_cost_impact NUMERIC NOT NULL DEFAULT 0,
 priority_score NUMERIC NOT NULL DEFAULT 0, priority_level TEXT NOT NULL DEFAULT 'LOW',
 recommended_response_hours INTEGER NOT NULL DEFAULT 72, recommended_action TEXT NOT NULL DEFAULT 'MONITOR',
 queue_rank INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
  c.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ux_maintenance_priority_key ON maintenance_priority_snapshot(organization_id,entity_id,period_key,work_center_id)'))
  c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_priority_close(close_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_key TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'CLOSED',closed_by TEXT NOT NULL,closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,period_key))'''))
  c.execute(text('CREATE INDEX IF NOT EXISTS ix_maintenance_priority_queue ON maintenance_priority_snapshot(organization_id,entity_id,period_key,priority_score DESC,queue_rank)'))
 @app.post('/v90eq/maintenance/queue/snapshot')
 def snapshot(body:dict,request:Request):
  u=perm(e,request,'maintenance_queue.manage')
  for k in ('organization_id','entity_id','period_key'):
   if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
  o,ei,p=body['organization_id'],body['entity_id'],body['period_key']; wc=body.get('work_center_id')
  with e.connect() as c:
   if c.execute(text('SELECT 1 FROM maintenance_priority_close WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':p}).first(): raise HTTPException(409,'period is closed')
   clause=' AND work_center_id=:w' if wc else ''
   params={'o':o,'e':ei,'p':p+'%','w':wc}
   risks=c.execute(text(f'''SELECT work_center_id,risk_score,risk_level,breakdown_hours,breakdown_orders FROM maintenance_risk_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key LIKE :p{clause}'''),params).mappings().all()
   costs=c.execute(text(f'''SELECT work_center_id,COALESCE(SUM(total_cost),0) cost FROM maintenance_spare_usage WHERE organization_id=:o AND entity_id=:e AND CAST(created_at AS TEXT) LIKE :p{clause} GROUP BY work_center_id'''),params).mappings().all()
   labour=c.execute(text(f'''SELECT work_center_id,COALESCE(SUM(total_cost),0) cost FROM maintenance_labour_charge WHERE organization_id=:o AND entity_id=:e AND CAST(charge_date AS TEXT) LIKE :p{clause} GROUP BY work_center_id'''),params).mappings().all()
  cm={r['work_center_id']:Decimal(str(r['cost'] or 0)) for r in costs}; lm={r['work_center_id']:Decimal(str(r['cost'] or 0)) for r in labour}
  rows=[]
  for r in risks:
   risk=Decimal(str(r['risk_score'] or 0)); hrs=Decimal(str(r['breakdown_hours'] or 0)); bd=int(r['breakdown_orders'] or 0); cost=cm.get(r['work_center_id'],Decimal(0))+lm.get(r['work_center_id'],Decimal(0))
   score=d(min(100,risk*Decimal('.60')+min(100,hrs*Decimal('5'))*Decimal('.20')+min(100,cost/Decimal('1000'))*Decimal('.15')+min(100,bd*Decimal('5'))*Decimal('.05')))
   if score>=80: level,resp,action='CRITICAL',4,'IMMEDIATE_INSPECTION'
   elif score>=60: level,resp,action='HIGH',24,'PRIORITIZE_MAINTENANCE'
   elif score>=35: level,resp,action='MEDIUM',48,'SCHEDULE_INSPECTION'
   else: level,resp,action='LOW',72,'MONITOR'
   rows.append((r,score,level,resp,action,cost))
  rows.sort(key=lambda x:(x[1],str(x[0]['work_center_id'])),reverse=True)
  with e.begin() as c:
   for rank,(r,score,level,resp,action,cost) in enumerate(rows,1):
    sid=str(uuid4()); c.execute(text('''INSERT INTO maintenance_priority_snapshot(snapshot_id,organization_id,entity_id,period_key,work_center_id,risk_score,risk_level,breakdown_hours,breakdown_orders,maintenance_cost,production_cost_impact,priority_score,priority_level,recommended_response_hours,recommended_action,queue_rank,status,created_by) VALUES(:i,:o,:e,:p,:w,:rs,:rl,:bh,:bo,:mc,0,:ps,:pl,:rh,:a,:q,'OPEN',:u) ON CONFLICT(organization_id,entity_id,period_key,work_center_id) DO UPDATE SET risk_score=:rs,risk_level=:rl,breakdown_hours=:bh,breakdown_orders=:bo,maintenance_cost=:mc,priority_score=:ps,priority_level=:pl,recommended_response_hours=:rh,recommended_action=:a,queue_rank=:q,status='OPEN',created_by=:u,created_at=CURRENT_TIMESTAMP'''),{'i':sid,'o':o,'e':ei,'p':p,'w':r['work_center_id'],'rs':float(risk),'rl':r['risk_level'],'bh':float(r['breakdown_hours'] or 0),'bo':int(r['breakdown_orders'] or 0),'mc':float(cost),'ps':float(score),'pl':level,'rh':resp,'a':action,'q':rank,'u':str(u.user_id)})
  return {'period_key':p,'count':len(rows),'queue':[{'work_center_id':r['work_center_id'],'priority_score':float(score),'priority_level':level,'recommended_response_hours':resp,'recommended_action':action,'queue_rank':i+1} for i,(r,score,level,resp,action,cost) in enumerate(rows)]}
 @app.get('/v90eq/maintenance/queue/dashboard')
 def dashboard(request:Request,organization_id:str,entity_id:str,period_key:str):
  perm(e,request,'maintenance_queue.view')
  with e.connect() as c: rows=c.execute(text('SELECT * FROM maintenance_priority_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY queue_rank'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
  return {'count':len(rows),'critical_count':sum(r['priority_level']=='CRITICAL' for r in rows),'high_count':sum(r['priority_level']=='HIGH' for r in rows),'rows':[dict(r) for r in rows]}
 @app.get('/v90eq/maintenance/queue')
 def queue(request:Request,organization_id:str,entity_id:str,period_key:str,limit:int=50):
  perm(e,request,'maintenance_queue.view'); limit=max(1,min(200,limit))
  with e.connect() as c: rows=c.execute(text('SELECT * FROM maintenance_priority_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY queue_rank LIMIT :l'),{'o':organization_id,'e':entity_id,'p':period_key,'l':limit}).mappings().all()
  return {'count':len(rows),'queue':[dict(r) for r in rows]}
 @app.post('/v90eq/maintenance/queue/{period_key}/close')
 def close(period_key:str,body:dict,request:Request):
  u=perm(e,request,'maintenance_queue.close'); o,ei=body.get('organization_id'),body.get('entity_id')
  if not o or not ei: raise HTTPException(400,'organization_id and entity_id are required')
  with e.begin() as c:
   c.execute(text('''INSERT INTO maintenance_priority_close(close_id,organization_id,entity_id,period_key,closed_by) VALUES(:i,:o,:e,:p,:u) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),{'i':str(uuid4()),'o':o,'e':ei,'p':period_key,'u':str(u.user_id)})
   c.execute(text('UPDATE maintenance_priority_snapshot SET status=\'CLOSED\' WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':ei,'p':period_key})
  return {'period_key':period_key,'status':'CLOSED'}
 @app.get('/ui/maintenance-queue')
 def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-queue.html')

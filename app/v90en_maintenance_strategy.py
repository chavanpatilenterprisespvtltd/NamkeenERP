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
def prev(pk):
 y,m=map(int,pk.split('-')); m-=1
 if m==0:y-=1;m=12
 return f'{y:04d}-{m:02d}'
def valid(pk):
 try:
  y,m=map(int,pk.split('-'))
  if not 1<=m<=12: raise ValueError
 except Exception: raise HTTPException(400,'period_key must be YYYY-MM')

def register_v90en_routes(app:FastAPI,e):
 with e.begin() as c:
  for p,n in [('maintenance_strategy.view','View Maintenance Strategy'),('maintenance_strategy.manage','Calculate Maintenance Strategy'),('maintenance_strategy.close','Close Maintenance Strategy')]:
   c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
  c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_strategy_snapshot(
 snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL, baseline_period_key TEXT NOT NULL, work_center_id TEXT,
 pm_orders INTEGER NOT NULL DEFAULT 0, breakdown_orders INTEGER NOT NULL DEFAULT 0, breakdown_hours NUMERIC NOT NULL DEFAULT 0, repeat_breakdown_orders INTEGER NOT NULL DEFAULT 0,
 observed_pm_interval_days NUMERIC NOT NULL DEFAULT 0, recommended_pm_interval_days NUMERIC NOT NULL DEFAULT 0, interval_change_pct NUMERIC NOT NULL DEFAULT 0,
 breakdown_reduction_pct NUMERIC NOT NULL DEFAULT 0, cost_change_pct NUMERIC NOT NULL DEFAULT 0, oee_improvement_pct NUMERIC NOT NULL DEFAULT 0, strategy_score NUMERIC NOT NULL DEFAULT 0,
 recommendation TEXT NOT NULL DEFAULT 'REVIEW', confidence TEXT NOT NULL DEFAULT 'LOW', status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
  c.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ux_maintenance_strategy_key ON maintenance_strategy_snapshot(organization_id,entity_id,period_key,work_center_id)'))
  c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_strategy_close(close_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_key TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'CLOSED',closed_by TEXT NOT NULL,closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,period_key))'''))
  c.execute(text('CREATE INDEX IF NOT EXISTS ix_maintenance_strategy_scope ON maintenance_strategy_snapshot(organization_id,entity_id,period_key,work_center_id,status)'))
 @app.post('/v90en/maintenance/strategy/snapshot')
 def snapshot(body:dict,request:Request):
  u=perm(e,request,'maintenance_strategy.manage')
  for k in ('organization_id','entity_id','period_key'):
   if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
  o,eid,pk=body['organization_id'],body['entity_id'],body['period_key']; base=body.get('baseline_period_key') or prev(pk); w=body.get('work_center_id'); valid(pk); valid(base)
  with e.connect() as c:
   if c.execute(text('SELECT 1 FROM maintenance_strategy_close WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':eid,'p':pk}).first(): raise HTTPException(409,'period is closed')
   q={'o':o,'e':eid,'p':pk,'w':w}
   wc=' AND work_center_id=:w' if w else ''
   orders=c.execute(text(f'''SELECT COUNT(*) total, SUM(CASE WHEN order_type='PREVENTIVE' THEN 1 ELSE 0 END) pm, SUM(CASE WHEN order_type='BREAKDOWN' THEN 1 ELSE 0 END) bd FROM maintenance_order WHERE organization_id=:o AND entity_id=:e AND substr(scheduled_date,1,7)=:p{wc}'''),q).mappings().one()
   hours=c.execute(text(f'''SELECT COALESCE(SUM(duration_minutes),0)/60.0 FROM maintenance_event WHERE organization_id=:o AND entity_id=:e AND event_type='BREAKDOWN' AND substr(event_at,1,7)=:p{wc}'''),q).scalar_one()
   # Repeat breakdown = work-centre/month breakdown orders beyond first; this is an operational indicator, not causal proof.
   rep=c.execute(text(f'''SELECT COALESCE(SUM(x.n-1),0) FROM (SELECT work_center_id, COUNT(*) n FROM maintenance_order WHERE organization_id=:o AND entity_id=:e AND order_type='BREAKDOWN' AND substr(scheduled_date,1,7)=:p{wc} GROUP BY work_center_id) x'''),q).scalar_one()
   # Observed PM interval uses active plan frequency when available; otherwise infer average gap between preventive orders.
   interval=c.execute(text(f'''SELECT AVG(frequency_value) FROM maintenance_plan WHERE organization_id=:o AND entity_id=:e AND active=1{(' AND work_center_id=:w' if w else '')} AND frequency_type IN ('DAYS','DAY','DAILY')'''),q).scalar_one()
   pm=int(orders['pm'] or 0); bd=int(orders['bd'] or 0); bh=d(hours); rep=int(rep or 0); observed=d(interval)
   if observed<=0:
    observed=d(c.execute(text(f'''SELECT COALESCE(AVG(gap),0) FROM (SELECT CAST(julianday(scheduled_date)-julianday(LAG(scheduled_date) OVER (ORDER BY scheduled_date)) AS NUMERIC) gap FROM maintenance_order WHERE organization_id=:o AND entity_id=:e AND order_type='PREVENTIVE' AND substr(scheduled_date,1,7)=:p{wc}) z WHERE gap IS NOT NULL'''),q).scalar_one())
   # Compare V90.em ROI snapshot to derive observed strategy signal.
   roi=c.execute(text('''SELECT COALESCE(AVG(breakdown_hours_reduction_pct),0) br,COALESCE(AVG(preventive_roi_pct),0) roi,COALESCE(AVG(oee_improvement_pct),0) oi,COALESCE(AVG(current_maintenance_cost),0) cc,COALESCE(AVG(baseline_maintenance_cost),0) bc FROM maintenance_roi_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND ((work_center_id=:w) OR (work_center_id IS NULL AND :w IS NULL))'''),q).mappings().one()
  br=d(roi['br']); ro=d(roi['roi']); oi=d(roi['oi']); cc=d(roi['cc']); bc=d(roi['bc']); costchg=d((cc-bc)/bc*100) if bc else d(0)
  # Recommend modest interval movement only when there is enough signal; never silently changes the maintenance plan.
  if pm==0: rec='ADD_PREVENTIVE_COVERAGE'; interval_rec=observed
  elif bd>=3 or rep>=2 or br<0: rec='INCREASE_PM_FREQUENCY'; interval_rec=d(observed*Decimal('0.8')) if observed>0 else d(0)
  elif br>=20 and ro>0 and oi>=0: rec='CONSIDER_LONGER_PM_INTERVAL'; interval_rec=d(observed*Decimal('1.2')) if observed>0 else d(0)
  else: rec='MAINTAIN_AND_REVIEW'; interval_rec=observed
  change=d((interval_rec-observed)/observed*100) if observed else d(0)
  score=d(max(0,min(100,max(0,br)*Decimal('.45')+max(0,ro)*Decimal('.30')+max(0,oi)*Decimal('.15')+max(0,Decimal(50)-max(0,costchg))*Decimal('.10'))))
  conf='HIGH' if pm>=3 and bd>=1 else ('MEDIUM' if pm>=1 or bd>=1 else 'LOW')
  status='OPTIMIZED' if score>=70 else ('IMPROVING' if score>=40 else 'REVIEW')
  sid=str(uuid4())
  with e.begin() as c:
   c.execute(text('''INSERT INTO maintenance_strategy_snapshot(snapshot_id,organization_id,entity_id,period_key,baseline_period_key,work_center_id,pm_orders,breakdown_orders,breakdown_hours,repeat_breakdown_orders,observed_pm_interval_days,recommended_pm_interval_days,interval_change_pct,breakdown_reduction_pct,cost_change_pct,oee_improvement_pct,strategy_score,recommendation,confidence,status,created_by) VALUES(:i,:o,:e,:p,:b,:w,:pm,:bd,:bh,:rep,:obs,:recint,:chg,:br,:cc,:oi,:sc,:rec,:conf,:st,:u) ON CONFLICT(organization_id,entity_id,period_key,work_center_id) DO UPDATE SET baseline_period_key=:b,pm_orders=:pm,breakdown_orders=:bd,breakdown_hours=:bh,repeat_breakdown_orders=:rep,observed_pm_interval_days=:obs,recommended_pm_interval_days=:recint,interval_change_pct=:chg,breakdown_reduction_pct=:br,cost_change_pct=:cc,oee_improvement_pct=:oi,strategy_score=:sc,recommendation=:rec,confidence=:conf,status=:st,created_by=:u,created_at=CURRENT_TIMESTAMP'''),{'i':sid,'o':o,'e':eid,'p':pk,'b':base,'w':w,'pm':pm,'bd':bd,'bh':float(bh),'rep':rep,'obs':float(observed),'recint':float(interval_rec),'chg':float(change),'br':float(br),'cc':float(costchg),'oi':float(oi),'sc':float(score),'rec':rec,'conf':conf,'st':status,'u':str(u.user_id)})
   rid=c.execute(text('SELECT snapshot_id FROM maintenance_strategy_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND ((work_center_id=:w) OR (work_center_id IS NULL AND :w IS NULL))'),q).scalar_one()
  return {'snapshot_id':rid,'period_key':pk,'baseline_period_key':base,'pm_orders':pm,'breakdown_orders':bd,'breakdown_hours':float(bh),'repeat_breakdown_orders':rep,'observed_pm_interval_days':float(observed),'recommended_pm_interval_days':float(interval_rec),'interval_change_pct':float(change),'breakdown_reduction_pct':float(br),'cost_change_pct':float(costchg),'oee_improvement_pct':float(oi),'strategy_score':float(score),'recommendation':rec,'confidence':conf,'status':status}
 @app.get('/v90en/maintenance/strategy/dashboard')
 def dashboard(request:Request,organization_id:str,entity_id:str,period_key:str):
  perm(e,request,'maintenance_strategy.view')
  with e.connect() as c: rows=c.execute(text('SELECT * FROM maintenance_strategy_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY strategy_score DESC,work_center_id'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
  return {'count':len(rows),'rows':[dict(r) for r in rows],'average_strategy_score':float(d(sum((d(r['strategy_score']) for r in rows),Decimal(0))/len(rows))) if rows else 0.0}
 @app.get('/v90en/maintenance/strategy/recommendations')
 def recommendations(request:Request,organization_id:str,entity_id:str,period_key:str):
  perm(e,request,'maintenance_strategy.view')
  with e.connect() as c: rows=c.execute(text('SELECT work_center_id,recommendation,confidence,strategy_score,observed_pm_interval_days,recommended_pm_interval_days,repeat_breakdown_orders FROM maintenance_strategy_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY strategy_score DESC'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
  return {'count':len(rows),'recommendations':[dict(r) for r in rows]}
 @app.post('/v90en/maintenance/strategy/{period_key}/close')
 def close(period_key:str,body:dict,request:Request):
  u=perm(e,request,'maintenance_strategy.close')
  for k in ('organization_id','entity_id'):
   if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
  with e.begin() as c:
   c.execute(text('INSERT INTO maintenance_strategy_close(close_id,organization_id,entity_id,period_key,closed_by) VALUES(:i,:o,:e,:p,:u) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET status=\'CLOSED\',closed_by=:u,closed_at=CURRENT_TIMESTAMP'),{'i':str(uuid4()),'o':body['organization_id'],'e':body['entity_id'],'p':period_key,'u':str(u.user_id)})
   c.execute(text("UPDATE maintenance_strategy_snapshot SET status='CLOSED' WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':body['organization_id'],'e':body['entity_id'],'p':period_key})
  return {'period_key':period_key,'status':'CLOSED'}
 @app.get('/ui/maintenance-strategy')
 def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-strategy.html')

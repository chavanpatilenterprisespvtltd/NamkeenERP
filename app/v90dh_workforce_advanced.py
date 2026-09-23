from __future__ import annotations
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

def register_v90dh_routes(app: FastAPI, e):
 with e.begin() as c:
  for p,n in [('workforce_advanced.view','View Advanced Workforce'),('workforce_advanced.manage','Manage Advanced Workforce'),('workforce_advanced.approve','Approve Labour Costing')]:
   c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
  c.execute(text('''CREATE TABLE IF NOT EXISTS hr_user_employee_map(map_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,employee_id TEXT NOT NULL,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,active BOOLEAN NOT NULL DEFAULT TRUE,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(user_id,employee_id))'''))
  c.execute(text('''CREATE TABLE IF NOT EXISTS hr_shift_roster(roster_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,employee_id TEXT NOT NULL,shift_id TEXT NOT NULL,work_date DATE NOT NULL,status TEXT NOT NULL DEFAULT 'PLANNED',created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(employee_id,work_date))'''))
  c.execute(text('''CREATE TABLE IF NOT EXISTS hr_calendar(calendar_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,calendar_date DATE NOT NULL,day_type TEXT NOT NULL,paid BOOLEAN NOT NULL DEFAULT TRUE,notes TEXT,UNIQUE(organization_id,entity_id,calendar_date))'''))
  c.execute(text('''CREATE TABLE IF NOT EXISTS hr_labour_variance(variance_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,batch_id TEXT NOT NULL,work_date DATE NOT NULL,standard_hours NUMERIC NOT NULL,actual_hours NUMERIC NOT NULL,standard_cost NUMERIC NOT NULL,actual_cost NUMERIC NOT NULL,hours_variance NUMERIC NOT NULL,cost_variance NUMERIC NOT NULL,status TEXT NOT NULL DEFAULT 'PENDING',approved BOOLEAN NOT NULL DEFAULT FALSE,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
  c.execute(text('CREATE INDEX IF NOT EXISTS ix_hr_roster_scope ON hr_shift_roster(organization_id,entity_id,work_date,employee_id)'))
  c.execute(text('CREATE INDEX IF NOT EXISTS ix_hr_variance_batch ON hr_labour_variance(organization_id,entity_id,batch_id,work_date)'))

 @app.post('/v90dh/hr/user-employee-map')
 def map_employee(b:dict,request:Request):
  u=_perm(e,request,'workforce_advanced.manage')
  for k in ('user_id','employee_id','organization_id','entity_id'):
   if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
  i=str(uuid4())
  with e.begin() as c: c.execute(text('''INSERT INTO hr_user_employee_map(map_id,user_id,employee_id,organization_id,entity_id) VALUES(:i,:u,:emp,:o,:e) ON CONFLICT(user_id,employee_id) DO UPDATE SET active=TRUE'''),{'i':i,'u':b['user_id'],'emp':b['employee_id'],'o':b['organization_id'],'e':b['entity_id']})
  return {'map_id':i,'status':'ACTIVE'}

 @app.post('/v90dh/hr/roster')
 def roster(b:dict,request:Request):
  u=_perm(e,request,'workforce_advanced.manage')
  req=('organization_id','entity_id','employee_id','shift_id','work_date')
  if any(not str(b.get(k) or '').strip() for k in req): raise HTTPException(400,'required fields missing')
  i=str(uuid4())
  with e.begin() as c: c.execute(text('''INSERT INTO hr_shift_roster(roster_id,organization_id,entity_id,employee_id,shift_id,work_date,status,created_by) VALUES(:i,:o,:e,:emp,:s,:d,:st,:u) ON CONFLICT(employee_id,work_date) DO UPDATE SET shift_id=:s,status=:st'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'emp':b['employee_id'],'s':b['shift_id'],'d':b['work_date'],'st':b.get('status','PLANNED'),'u':str(u.user_id)})
  return {'roster_id':i,'status':b.get('status','PLANNED')}

 @app.post('/v90dh/hr/calendar')
 def calendar(b:dict,request:Request):
  u=_perm(e,request,'workforce_advanced.manage')
  req=('organization_id','entity_id','calendar_date','day_type')
  if any(not str(b.get(k) or '').strip() for k in req): raise HTTPException(400,'required fields missing')
  i=str(uuid4())
  with e.begin() as c: c.execute(text('''INSERT INTO hr_calendar(calendar_id,organization_id,entity_id,calendar_date,day_type,paid,notes) VALUES(:i,:o,:e,:d,:t,:p,:n) ON CONFLICT(organization_id,entity_id,calendar_date) DO UPDATE SET day_type=:t,paid=:p,notes=:n'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'d':b['calendar_date'],'t':b['day_type'],'p':bool(b.get('paid',True)),'n':b.get('notes')})
  return {'calendar_id':i,'status':'ACTIVE'}

 @app.post('/v90dh/hr/overtime')
 def overtime(b:dict,request:Request):
  u=_perm(e,request,'workforce_advanced.manage')
  for k in ('attendance_id','overtime_hours'):
   if b.get(k) in (None,''): raise HTTPException(400,f'{k} is required')
  with e.begin() as c:
   row=c.execute(text('SELECT employee_id,organization_id,entity_id FROM hr_attendance WHERE attendance_id=:i'),{'i':b['attendance_id']}).mappings().first()
   if not row: raise HTTPException(404,'attendance not found')
   rate=float(c.execute(text('SELECT hourly_cost FROM hr_employee WHERE employee_id=:i'),{'i':row['employee_id']}).scalar() or 0)
  hrs=float(b['overtime_hours']); mult=float(b.get('multiplier') or 1.5)
  return {'attendance_id':b['attendance_id'],'overtime_hours':hrs,'overtime_rate':rate*mult,'overtime_cost':hrs*rate*mult}

 @app.post('/v90dh/hr/labour-variance')
 def variance(b:dict,request:Request):
  u=_perm(e,request,'workforce_advanced.manage')
  req=('organization_id','entity_id','batch_id','work_date','standard_hours','actual_hours','standard_cost','actual_cost')
  if any(b.get(k) in (None,'') for k in req): raise HTTPException(400,'required fields missing')
  i=str(uuid4()); sh=float(b['standard_hours']); ah=float(b['actual_hours']); sc=float(b['standard_cost']); ac=float(b['actual_cost'])
  with e.begin() as c: c.execute(text('''INSERT INTO hr_labour_variance(variance_id,organization_id,entity_id,batch_id,work_date,standard_hours,actual_hours,standard_cost,actual_cost,hours_variance,cost_variance,created_by) VALUES(:i,:o,:e,:b,:d,:sh,:ah,:sc,:ac,:hv,:cv,:u)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'b':b['batch_id'],'d':b['work_date'],'sh':sh,'ah':ah,'sc':sc,'ac':ac,'hv':ah-sh,'cv':ac-sc,'u':str(u.user_id)})
  return {'variance_id':i,'hours_variance':ah-sh,'cost_variance':ac-sc,'status':'PENDING'}

 @app.post('/v90dh/hr/labour-variance/{variance_id}/approve')
 def approve(variance_id:str,request:Request):
  _perm(e,request,'workforce_advanced.approve')
  with e.begin() as c:
   n=c.execute(text("UPDATE hr_labour_variance SET approved=TRUE,status='APPROVED' WHERE variance_id=:i"),{'i':variance_id}).rowcount
   if not n: raise HTTPException(404,'variance not found')
  return {'variance_id':variance_id,'status':'APPROVED'}

 @app.get('/v90dh/hr/dashboard')
 def dashboard(request:Request,organization_id:str,entity_id:str):
  _perm(e,request,'workforce_advanced.view')
  with e.connect() as c:
   ot=c.execute(text("SELECT COALESCE(SUM(actual_hours-standard_hours),0) FROM hr_labour_variance WHERE organization_id=:o AND entity_id=:e"),{'o':organization_id,'e':entity_id}).scalar()
   cv=c.execute(text("SELECT COALESCE(SUM(cost_variance),0) FROM hr_labour_variance WHERE organization_id=:o AND entity_id=:e"),{'o':organization_id,'e':entity_id}).scalar()
   pending=c.execute(text("SELECT COUNT(*) FROM hr_labour_variance WHERE organization_id=:o AND entity_id=:e AND approved=FALSE"),{'o':organization_id,'e':entity_id}).scalar()
   roster=c.execute(text("SELECT COUNT(*) FROM hr_shift_roster WHERE organization_id=:o AND entity_id=:e AND work_date=CURRENT_DATE AND status='PLANNED'"),{'o':organization_id,'e':entity_id}).scalar()
  return {'overtime_hours':float(ot or 0),'labour_cost_variance':float(cv or 0),'pending_variances':int(pending),'today_roster':int(roster)}

 @app.get('/ui/hr-workforce-advanced')
 def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'hr-workforce-advanced.html')

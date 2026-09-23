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

def register_v90dg_routes(app: FastAPI, e):
    with e.begin() as c:
        for p,n in [('hr.view','View Workforce'),('hr.manage','Manage Workforce'),('hr.attendance','Manage Attendance'),('hr.allocate','Allocate Labour')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_employee(employee_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,employee_code TEXT NOT NULL,employee_name TEXT NOT NULL,department TEXT,designation TEXT,join_date DATE,employment_status TEXT NOT NULL DEFAULT 'ACTIVE',hourly_cost NUMERIC NOT NULL DEFAULT 0,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_shift(shift_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,shift_code TEXT NOT NULL,shift_name TEXT NOT NULL,start_time TEXT NOT NULL,end_time TEXT NOT NULL,standard_hours NUMERIC NOT NULL DEFAULT 8,active BOOLEAN NOT NULL DEFAULT TRUE,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_attendance(attendance_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,employee_id TEXT NOT NULL,work_date DATE NOT NULL,shift_id TEXT,punch_in TIMESTAMP,punch_out TIMESTAMP,status TEXT NOT NULL DEFAULT 'PRESENT',hours NUMERIC NOT NULL DEFAULT 0,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_labour_allocation(allocation_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,employee_id TEXT NOT NULL,batch_id TEXT NOT NULL,work_date DATE NOT NULL,hours NUMERIC NOT NULL,rate NUMERIC NOT NULL DEFAULT 0,cost NUMERIC NOT NULL DEFAULT 0,approved BOOLEAN NOT NULL DEFAULT FALSE,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE INDEX IF NOT EXISTS ix_hr_attendance_emp_date ON hr_attendance(organization_id,entity_id,employee_id,work_date)'''))
        c.execute(text('''CREATE INDEX IF NOT EXISTS ix_hr_allocation_batch ON hr_labour_allocation(organization_id,entity_id,batch_id,work_date)'''))

    @app.post('/v90dg/hr/employees')
    def employee(b:dict,request:Request):
        u=_perm(e,request,'hr.manage')
        for k in ('organization_id','entity_id','employee_code','employee_name'):
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with e.begin() as c:c.execute(text('''INSERT INTO hr_employee(employee_id,organization_id,entity_id,employee_code,employee_name,department,designation,join_date,employment_status,hourly_cost,created_by) VALUES(:i,:o,:e,:c,:n,:d,:g,:j,:s,:r,:u)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'c':b['employee_code'],'n':b['employee_name'],'d':b.get('department'),'g':b.get('designation'),'j':b.get('join_date'),'s':b.get('employment_status','ACTIVE'),'r':float(b.get('hourly_cost') or 0),'u':str(u.user_id)})
        return {'employee_id':i,'status':'ACTIVE'}

    @app.post('/v90dg/hr/shifts')
    def shift(b:dict,request:Request):
        u=_perm(e,request,'hr.manage')
        for k in ('organization_id','entity_id','shift_code','shift_name','start_time','end_time'):
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with e.begin() as c:c.execute(text('''INSERT INTO hr_shift(shift_id,organization_id,entity_id,shift_code,shift_name,start_time,end_time,standard_hours,active,created_by) VALUES(:i,:o,:e,:c,:n,:s,:x,:h,:a,:u)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'c':b['shift_code'],'n':b['shift_name'],'s':b['start_time'],'x':b['end_time'],'h':float(b.get('standard_hours') or 8),'a':bool(b.get('active',True)),'u':str(u.user_id)})
        return {'shift_id':i,'status':'ACTIVE'}

    @app.post('/v90dg/hr/attendance')
    def attendance(b:dict,request:Request):
        u=_perm(e,request,'hr.attendance')
        for k in ('organization_id','entity_id','employee_id','work_date'):
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4()); hours=float(b.get('hours') or 0)
        with e.begin() as c:c.execute(text('''INSERT INTO hr_attendance(attendance_id,organization_id,entity_id,employee_id,work_date,shift_id,punch_in,punch_out,status,hours,created_by) VALUES(:i,:o,:e,:emp,:d,:s,:pin,:pout,:st,:h,:u)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'emp':b['employee_id'],'d':b['work_date'],'s':b.get('shift_id'),'pin':b.get('punch_in'),'pout':b.get('punch_out'),'st':b.get('status','PRESENT'),'h':hours,'u':str(u.user_id)})
        return {'attendance_id':i,'hours':hours,'status':b.get('status','PRESENT')}

    @app.post('/v90dg/hr/labour-allocations')
    def allocation(b:dict,request:Request):
        u=_perm(e,request,'hr.allocate')
        for k in ('organization_id','entity_id','employee_id','batch_id','work_date','hours'):
            if b.get(k) in (None,''): raise HTTPException(400,f'{k} is required')
        i=str(uuid4()); hours=float(b['hours']); rate=float(b.get('rate') or 0)
        with e.begin() as c:
            if not rate:
                rate=float(c.execute(text('SELECT hourly_cost FROM hr_employee WHERE employee_id=:i AND organization_id=:o AND entity_id=:e'),{'i':b['employee_id'],'o':b['organization_id'],'e':b['entity_id']}).scalar() or 0)
            cost=hours*rate
            c.execute(text('''INSERT INTO hr_labour_allocation(allocation_id,organization_id,entity_id,employee_id,batch_id,work_date,hours,rate,cost,created_by) VALUES(:i,:o,:e,:emp,:b,:d,:h,:r,:c,:u)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'emp':b['employee_id'],'b':b['batch_id'],'d':b['work_date'],'h':hours,'r':rate,'c':cost,'u':str(u.user_id)})
        return {'allocation_id':i,'cost':cost,'status':'PENDING_APPROVAL'}

    @app.post('/v90dg/hr/labour-allocations/{allocation_id}/approve')
    def approve(allocation_id:str,request:Request):
        _perm(e,request,'hr.allocate')
        with e.begin() as c:
            n=c.execute(text("UPDATE hr_labour_allocation SET approved=TRUE WHERE allocation_id=:i"),{'i':allocation_id}).rowcount
            if not n: raise HTTPException(404,'allocation not found')
        return {'allocation_id':allocation_id,'status':'APPROVED'}

    @app.get('/v90dg/hr/dashboard')
    def dashboard(request:Request,organization_id:str,entity_id:str):
        _perm(e,request,'hr.view')
        with e.connect() as c:
            employees=c.execute(text("SELECT COUNT(*) FROM hr_employee WHERE organization_id=:o AND entity_id=:e AND employment_status='ACTIVE'"),{'o':organization_id,'e':entity_id}).scalar_one()
            present=c.execute(text("SELECT COUNT(*) FROM hr_attendance WHERE organization_id=:o AND entity_id=:e AND status='PRESENT' AND work_date=CURRENT_DATE"),{'o':organization_id,'e':entity_id}).scalar_one()
            pending=c.execute(text("SELECT COUNT(*) FROM hr_labour_allocation WHERE organization_id=:o AND entity_id=:e AND approved=FALSE"),{'o':organization_id,'e':entity_id}).scalar_one()
            cost=c.execute(text("SELECT COALESCE(SUM(cost),0) FROM hr_labour_allocation WHERE organization_id=:o AND entity_id=:e"),{'o':organization_id,'e':entity_id}).scalar_one()
        return {'active_employees':int(employees),'present_today':int(present),'pending_labour_approvals':int(pending),'allocated_labour_cost':float(cost or 0)}

    @app.get('/ui/hr-workforce')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'hr-workforce.html')

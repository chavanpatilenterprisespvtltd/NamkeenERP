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

def register_v90dc_routes(app: FastAPI, e):
    with e.begin() as c:
        for p,n in [('maintenance.view','View Maintenance'),('maintenance.manage','Manage Maintenance'),('maintenance.approve','Approve Maintenance')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_plan(plan_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,work_center_id TEXT NOT NULL,plan_name TEXT NOT NULL,frequency_type TEXT NOT NULL,frequency_value NUMERIC NOT NULL DEFAULT 1,last_service_date DATE,next_due_date DATE,running_hours_threshold NUMERIC,active BOOLEAN NOT NULL DEFAULT TRUE,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_order(order_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,work_center_id TEXT NOT NULL,plan_id TEXT,order_type TEXT NOT NULL DEFAULT 'PREVENTIVE',status TEXT NOT NULL DEFAULT 'OPEN',scheduled_date DATE,downtime_hours NUMERIC NOT NULL DEFAULT 0,description TEXT,approved_by TEXT,approved_at TIMESTAMP,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_event(event_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,work_center_id TEXT NOT NULL,event_type TEXT NOT NULL,event_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,duration_minutes NUMERIC NOT NULL DEFAULT 0,reason TEXT,maintenance_order_id TEXT,created_by TEXT NOT NULL)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_spare_usage(usage_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,work_center_id TEXT NOT NULL,maintenance_order_id TEXT,material_id TEXT NOT NULL,quantity NUMERIC NOT NULL DEFAULT 0,unit_cost NUMERIC NOT NULL DEFAULT 0,total_cost NUMERIC NOT NULL DEFAULT 0,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_maint_order_scope ON maintenance_order(organization_id,entity_id,work_center_id,scheduled_date,status)'))
    @app.post('/v90dc/maintenance/plans')
    def plan(b:dict,request:Request):
        u=_perm(e,request,'maintenance.manage')
        for k in ('organization_id','entity_id','work_center_id','plan_name','frequency_type'):
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with e.begin() as c:c.execute(text('''INSERT INTO maintenance_plan(plan_id,organization_id,entity_id,work_center_id,plan_name,frequency_type,frequency_value,last_service_date,next_due_date,running_hours_threshold,active,created_by) VALUES(:i,:o,:e,:w,:n,:f,:v,:l,:d,:h,:a,:u)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'w':b['work_center_id'],'n':b['plan_name'],'f':b['frequency_type'],'v':float(b.get('frequency_value') or 1),'l':b.get('last_service_date'),'d':b.get('next_due_date'),'h':b.get('running_hours_threshold'),'a':bool(b.get('active',True)),'u':str(u.user_id)})
        return {'plan_id':i,'status':'CREATED'}
    @app.post('/v90dc/maintenance/orders')
    def order(b:dict,request:Request):
        u=_perm(e,request,'maintenance.manage')
        for k in ('organization_id','entity_id','work_center_id'):
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with e.begin() as c:c.execute(text('''INSERT INTO maintenance_order(order_id,organization_id,entity_id,work_center_id,plan_id,order_type,status,scheduled_date,downtime_hours,description,created_by) VALUES(:i,:o,:e,:w,:p,:t,'OPEN',:d,:h,:x,:u)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'w':b['work_center_id'],'p':b.get('plan_id'),'t':b.get('order_type','PREVENTIVE'),'d':b.get('scheduled_date'),'h':float(b.get('downtime_hours') or 0),'x':b.get('description'),'u':str(u.user_id)})
        return {'order_id':i,'status':'OPEN'}
    @app.post('/v90dc/maintenance/orders/{oid}/approve')
    def approve(oid:str,request:Request):
        u=_perm(e,request,'maintenance.approve')
        with e.begin() as c:
            r=c.execute(text("UPDATE maintenance_order SET status='APPROVED',approved_by=:u,approved_at=CURRENT_TIMESTAMP WHERE order_id=:i AND status='OPEN' RETURNING order_id"),{'i':oid,'u':str(u.user_id)}).first()
            if not r: raise HTTPException(404,'open maintenance order not found')
        return {'order_id':oid,'status':'APPROVED'}
    @app.post('/v90dc/maintenance/events')
    def event(b:dict,request:Request):
        u=_perm(e,request,'maintenance.manage')
        for k in ('organization_id','entity_id','work_center_id','event_type'):
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with e.begin() as c:c.execute(text('''INSERT INTO maintenance_event(event_id,organization_id,entity_id,work_center_id,event_type,event_at,duration_minutes,reason,maintenance_order_id,created_by) VALUES(:i,:o,:e,:w,:t,COALESCE(:at,CURRENT_TIMESTAMP),:m,:r,:mo,:u)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'w':b['work_center_id'],'t':b['event_type'],'at':b.get('event_at'),'m':float(b.get('duration_minutes') or 0),'r':b.get('reason'),'mo':b.get('maintenance_order_id'),'u':str(u.user_id)})
        return {'event_id':i,'status':'RECORDED'}
    @app.post('/v90dc/maintenance/spares')
    def spare(b:dict,request:Request):
        u=_perm(e,request,'maintenance.manage')
        for k in ('organization_id','entity_id','work_center_id','material_id'):
            if not str(b.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4()); q=float(b.get('quantity') or 0); cost=float(b.get('unit_cost') or 0)
        with e.begin() as c:c.execute(text('''INSERT INTO maintenance_spare_usage(usage_id,organization_id,entity_id,work_center_id,maintenance_order_id,material_id,quantity,unit_cost,total_cost,created_by) VALUES(:i,:o,:e,:w,:m,:x,:q,:c,:t,:u)'''),{'i':i,'o':b['organization_id'],'e':b['entity_id'],'w':b['work_center_id'],'m':b.get('maintenance_order_id'),'x':b['material_id'],'q':q,'c':cost,'t':q*cost,'u':str(u.user_id)})
        return {'usage_id':i,'total_cost':q*cost}
    @app.get('/v90dc/maintenance/dashboard')
    def dashboard(request:Request,organization_id:str,entity_id:str):
        _perm(e,request,'maintenance.view')
        with e.connect() as c:
            due=c.execute(text("SELECT COUNT(*) n FROM maintenance_plan WHERE organization_id=:o AND entity_id=:e AND active=TRUE AND next_due_date IS NOT NULL AND next_due_date<=CURRENT_DATE"),{'o':organization_id,'e':entity_id}).scalar_one()
            cost=c.execute(text('SELECT COALESCE(SUM(total_cost),0) FROM maintenance_spare_usage WHERE organization_id=:o AND entity_id=:e'),{'o':organization_id,'e':entity_id}).scalar_one()
            ev=c.execute(text("SELECT COALESCE(SUM(duration_minutes),0) FROM maintenance_event WHERE organization_id=:o AND entity_id=:e AND event_type='BREAKDOWN'"),{'o':organization_id,'e':entity_id}).scalar_one()
            orders=c.execute(text("SELECT status,COUNT(*) n FROM maintenance_order WHERE organization_id=:o AND entity_id=:e GROUP BY status"),{'o':organization_id,'e':entity_id}).mappings().all()
        return {'due_plans':int(due or 0),'maintenance_cost':float(cost or 0),'breakdown_minutes':float(ev or 0),'orders':[dict(x) for x in orders]}
    @app.get('/ui/maintenance')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance.html')

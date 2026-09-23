from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def _money(v): return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
def _perm(engine, request, p):
    u=authenticate(request); ps=permissions_for_user(engine,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def register_v90dq_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for p,n in [('workforce_planning.view','View Workforce Planning'),('workforce_planning.manage','Manage Workforce Planning'),('workforce_planning.post','Post Workforce Planning'),('workforce_planning.close','Close Workforce Planning')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_shift_roster(roster_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,employee_id TEXT NOT NULL,work_date DATE NOT NULL,shift_code TEXT NOT NULL,planned_hours NUMERIC NOT NULL DEFAULT 0,department_id TEXT,status TEXT NOT NULL DEFAULT 'PLANNED',created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,employee_id,work_date))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_attendance_exception(exception_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,employee_id TEXT NOT NULL,work_date DATE NOT NULL,exception_type TEXT NOT NULL,expected_value NUMERIC NOT NULL DEFAULT 0,actual_value NUMERIC NOT NULL DEFAULT 0,variance_hours NUMERIC NOT NULL DEFAULT 0,reason TEXT,status TEXT NOT NULL DEFAULT 'OPEN',resolved_by TEXT,resolved_at TIMESTAMP,created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_workforce_plan(plan_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,plan_date DATE NOT NULL,department_id TEXT,required_hours NUMERIC NOT NULL DEFAULT 0,planned_hours NUMERIC NOT NULL DEFAULT 0,required_headcount INTEGER NOT NULL DEFAULT 0,planned_headcount INTEGER NOT NULL DEFAULT 0,labour_cost_budget NUMERIC NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'DRAFT',created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,plan_date,department_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_labour_cost_forecast(forecast_id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,entity_id TEXT NOT NULL,period_id TEXT NOT NULL,department_id TEXT,planned_hours NUMERIC NOT NULL DEFAULT 0,forecast_hours NUMERIC NOT NULL DEFAULT 0,planned_cost NUMERIC NOT NULL DEFAULT 0,forecast_cost NUMERIC NOT NULL DEFAULT 0,variance_cost NUMERIC NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'READY',created_by TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,UNIQUE(organization_id,entity_id,period_id,department_id))'''))

    @app.post('/v90dq/workforce/roster')
    def roster(body:dict, request:Request):
        u=_perm(engine,request,'workforce_planning.manage')
        for k in ('organization_id','entity_id','employee_id','work_date','shift_code'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        h=_money(body.get('planned_hours'))
        if h<0: raise HTTPException(400,'planned_hours must be non-negative')
        i=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_shift_roster(roster_id,organization_id,entity_id,employee_id,work_date,shift_code,planned_hours,department_id,created_by) VALUES(:i,:o,:e,:emp,:d,:s,:h,:dep,:u) ON CONFLICT(organization_id,entity_id,employee_id,work_date) DO UPDATE SET shift_code=:s,planned_hours=:h,department_id=:dep,status='PLANNED' '''),{'i':i,'o':body['organization_id'],'e':body['entity_id'],'emp':body['employee_id'],'d':body['work_date'],'s':body['shift_code'],'h':float(h),'dep':body.get('department_id'),'u':str(u.user_id)})
        return {'roster_id':i,'status':'PLANNED'}

    @app.post('/v90dq/workforce/plans')
    def plan(body:dict, request:Request):
        u=_perm(engine,request,'workforce_planning.manage')
        for k in ('organization_id','entity_id','plan_date'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        rh=_money(body.get('required_hours')); ph=_money(body.get('planned_hours')); budget=_money(body.get('labour_cost_budget'))
        if min(rh,ph,budget)<0: raise HTTPException(400,'planning values must be non-negative')
        i=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_workforce_plan(plan_id,organization_id,entity_id,plan_date,department_id,required_hours,planned_hours,required_headcount,planned_headcount,labour_cost_budget,status,created_by) VALUES(:i,:o,:e,:d,:dep,:rh,:ph,:rc,:pc,:b,'DRAFT',:u) ON CONFLICT(organization_id,entity_id,plan_date,department_id) DO UPDATE SET required_hours=:rh,planned_hours=:ph,required_headcount=:rc,planned_headcount=:pc,labour_cost_budget=:b,status='DRAFT' '''),{'i':i,'o':body['organization_id'],'e':body['entity_id'],'d':body['plan_date'],'dep':body.get('department_id'),'rh':float(rh),'ph':float(ph),'rc':int(body.get('required_headcount') or 0),'pc':int(body.get('planned_headcount') or 0),'b':float(budget),'u':str(u.user_id)})
        return {'plan_id':i,'status':'DRAFT'}

    @app.post('/v90dq/workforce/exceptions')
    def exception(body:dict, request:Request):
        u=_perm(engine,request,'workforce_planning.post')
        for k in ('organization_id','entity_id','employee_id','work_date','exception_type'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        exp=_money(body.get('expected_value')); act=_money(body.get('actual_value')); var=_money(exp-act)
        i=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_attendance_exception(exception_id,organization_id,entity_id,employee_id,work_date,exception_type,expected_value,actual_value,variance_hours,reason,created_by) VALUES(:i,:o,:e,:emp,:d,:t,:x,:a,:v,:r,:u)'''),{'i':i,'o':body['organization_id'],'e':body['entity_id'],'emp':body['employee_id'],'d':body['work_date'],'t':str(body['exception_type']).upper(),'x':float(exp),'a':float(act),'v':float(var),'r':body.get('reason'),'u':str(u.user_id)})
        return {'exception_id':i,'variance_hours':float(var),'status':'OPEN'}

    @app.post('/v90dq/workforce/exceptions/{exception_id}/resolve')
    def resolve(exception_id:str, request:Request):
        u=_perm(engine,request,'workforce_planning.manage')
        with engine.begin() as c:
            if not c.execute(text('SELECT 1 FROM hr_attendance_exception WHERE exception_id=:i'),{'i':exception_id}).scalar(): raise HTTPException(404,'exception not found')
            c.execute(text("UPDATE hr_attendance_exception SET status='RESOLVED',resolved_by=:u,resolved_at=CURRENT_TIMESTAMP WHERE exception_id=:i"),{'i':exception_id,'u':str(u.user_id)})
        return {'exception_id':exception_id,'status':'RESOLVED'}

    @app.post('/v90dq/workforce/forecast')
    def forecast(body:dict, request:Request):
        u=_perm(engine,request,'workforce_planning.post')
        for k in ('organization_id','entity_id','period_id'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        ph=_money(body.get('planned_hours')); fh=_money(body.get('forecast_hours')); pc=_money(body.get('planned_cost')); fc=_money(body.get('forecast_cost')); var=_money(fc-pc)
        i=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_labour_cost_forecast(forecast_id,organization_id,entity_id,period_id,department_id,planned_hours,forecast_hours,planned_cost,forecast_cost,variance_cost,created_by) VALUES(:i,:o,:e,:p,:d,:ph,:fh,:pc,:fc,:v,:u) ON CONFLICT(organization_id,entity_id,period_id,department_id) DO UPDATE SET planned_hours=:ph,forecast_hours=:fh,planned_cost=:pc,forecast_cost=:fc,variance_cost=:v,status='READY' '''),{'i':i,'o':body['organization_id'],'e':body['entity_id'],'p':body['period_id'],'d':body.get('department_id'),'ph':float(ph),'fh':float(fh),'pc':float(pc),'fc':float(fc),'v':float(var),'u':str(u.user_id)})
        return {'forecast_id':i,'variance_cost':float(var),'status':'READY'}

    @app.get('/v90dq/workforce/mis')
    def mis(request:Request, organization_id:str, entity_id:str, period_id:str|None=None):
        _perm(engine,request,'workforce_planning.view')
        with engine.connect() as c:
            params={'o':organization_id,'e':entity_id}; q='SELECT * FROM hr_labour_cost_forecast WHERE organization_id=:o AND entity_id=:e'
            if period_id: q+=' AND period_id=:p'; params['p']=period_id
            q+=' ORDER BY created_at DESC'; rows=c.execute(text(q),params).mappings().all()
            open_ex=c.execute(text("SELECT COUNT(*) FROM hr_attendance_exception WHERE organization_id=:o AND entity_id=:e AND status='OPEN'"),{'o':organization_id,'e':entity_id}).scalar()
            gaps=c.execute(text('SELECT COALESCE(SUM(required_hours-planned_hours),0) FROM hr_workforce_plan WHERE organization_id=:o AND entity_id=:e'),{'o':organization_id,'e':entity_id}).scalar()
        return {'rows':[dict(x) for x in rows],'open_attendance_exceptions':int(open_ex or 0),'planned_hour_gap':float(_money(gaps))}

    @app.get('/v90dq/workforce/dashboard')
    def dashboard(request:Request, organization_id:str, entity_id:str):
        _perm(engine,request,'workforce_planning.view')
        with engine.connect() as c:
            p=c.execute(text('''SELECT COALESCE(SUM(required_hours),0) rh,COALESCE(SUM(planned_hours),0) ph,COALESCE(SUM(required_headcount),0) rc,COALESCE(SUM(planned_headcount),0) pc,COALESCE(SUM(labour_cost_budget),0) budget FROM hr_workforce_plan WHERE organization_id=:o AND entity_id=:e'''),{'o':organization_id,'e':entity_id}).mappings().first()
            f=c.execute(text('''SELECT COALESCE(SUM(planned_cost),0) pc,COALESCE(SUM(forecast_cost),0) fc,COALESCE(SUM(variance_cost),0) v FROM hr_labour_cost_forecast WHERE organization_id=:o AND entity_id=:e'''),{'o':organization_id,'e':entity_id}).mappings().first()
            ex=c.execute(text("SELECT COUNT(*) FROM hr_attendance_exception WHERE organization_id=:o AND entity_id=:e AND status='OPEN'"),{'o':organization_id,'e':entity_id}).scalar()
        return {'required_hours':float(_money(p['rh'])),'planned_hours':float(_money(p['ph'])),'hour_gap':float(_money(_money(p['rh'])-_money(p['ph']))),'required_headcount':int(p['rc'] or 0),'planned_headcount':int(p['pc'] or 0),'labour_budget':float(_money(p['budget'])),'planned_cost':float(_money(f['pc'])),'forecast_cost':float(_money(f['fc'])),'forecast_variance':float(_money(f['v'])),'open_attendance_exceptions':int(ex or 0)}

    @app.get('/ui/workforce-planning')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'workforce-planning.html')

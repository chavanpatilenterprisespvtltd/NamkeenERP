from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def _num(v): return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
def _perm(engine, request, p):
    u=authenticate(request); ps=permissions_for_user(engine,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def register_v90dr_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for p,n in [('workforce_capacity.view','View Workforce Capacity'),('workforce_capacity.manage','Manage Workforce Capacity'),('workforce_capacity.post','Post Workforce Capacity')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
    @app.post('/v90dr/workforce/skills')
    def skill(body:dict, request:Request):
        u=_perm(engine,request,'workforce_capacity.manage')
        for k in ('organization_id','entity_id','skill_code','skill_name'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_skill_master(skill_id,organization_id,entity_id,skill_code,skill_name,department_id,required_level,created_by) VALUES(:i,:o,:e,:c,:n,:d,:l,:u) ON CONFLICT(organization_id,entity_id,skill_code) DO UPDATE SET skill_name=:n,department_id=:d,required_level=:l,active=TRUE'''),{'i':i,'o':body['organization_id'],'e':body['entity_id'],'c':body['skill_code'],'n':body['skill_name'],'d':body.get('department_id'),'l':max(1,int(body.get('required_level') or 1)),'u':str(u.user_id)})
        return {'skill_id':i,'status':'ACTIVE'}
    @app.post('/v90dr/workforce/employee-skills')
    def employee_skill(body:dict, request:Request):
        u=_perm(engine,request,'workforce_capacity.manage')
        for k in ('organization_id','entity_id','employee_id','skill_id'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        level=int(body.get('skill_level') or 1)
        if level<1: raise HTTPException(400,'skill_level must be positive')
        i=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_employee_skill(employee_skill_id,organization_id,entity_id,employee_id,skill_id,skill_level,valid_from,valid_to,created_by) VALUES(:i,:o,:e,:emp,:s,:l,:vf,:vt,:u) ON CONFLICT(organization_id,entity_id,employee_id,skill_id) DO UPDATE SET skill_level=:l,valid_from=:vf,valid_to=:vt,status='ACTIVE' '''),{'i':i,'o':body['organization_id'],'e':body['entity_id'],'emp':body['employee_id'],'s':body['skill_id'],'l':level,'vf':body.get('valid_from'),'vt':body.get('valid_to'),'u':str(u.user_id)})
        return {'employee_skill_id':i,'status':'ACTIVE'}
    @app.post('/v90dr/workforce/capacity')
    def capacity(body:dict, request:Request):
        u=_perm(engine,request,'workforce_capacity.post')
        for k in ('organization_id','entity_id','plan_date'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        rh=_num(body.get('required_hours')); ah=_num(body.get('available_hours')); gap=_num(rh-ah)
        if rh<0 or ah<0: raise HTTPException(400,'hours must be non-negative')
        i=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_workforce_capacity_plan(capacity_plan_id,organization_id,entity_id,plan_date,department_id,shift_code,required_headcount,available_headcount,required_hours,available_hours,capacity_gap_hours,skill_gap_count,created_by) VALUES(:i,:o,:e,:d,:dep,:s,:rc,:ac,:rh,:ah,:g,:sg,:u) ON CONFLICT(organization_id,entity_id,plan_date,department_id,shift_code) DO UPDATE SET required_headcount=:rc,available_headcount=:ac,required_hours=:rh,available_hours=:ah,capacity_gap_hours=:g,skill_gap_count=:sg,status='DRAFT' '''),{'i':i,'o':body['organization_id'],'e':body['entity_id'],'d':body['plan_date'],'dep':body.get('department_id'),'s':body.get('shift_code'),'rc':int(body.get('required_headcount') or 0),'ac':int(body.get('available_headcount') or 0),'rh':float(rh),'ah':float(ah),'g':float(gap),'sg':max(0,int(body.get('skill_gap_count') or 0)),'u':str(u.user_id)})
        return {'capacity_plan_id':i,'capacity_gap_hours':float(gap),'status':'DRAFT'}
    @app.post('/v90dr/workforce/availability')
    def availability(body:dict, request:Request):
        u=_perm(engine,request,'workforce_capacity.post')
        for k in ('organization_id','entity_id','forecast_date'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        ah=_num(body.get('available_hours')); absence=_num(body.get('expected_absence_hours')); ot=_num(body.get('expected_overtime_hours')); net=_num(ah-absence+ot)
        conf=_num(body.get('confidence'))
        if min(ah,absence,ot)<0 or conf<0 or conf>100: raise HTTPException(400,'invalid availability forecast values')
        i=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_labour_availability_forecast(availability_id,organization_id,entity_id,forecast_date,department_id,available_headcount,available_hours,expected_absence_hours,expected_overtime_hours,net_available_hours,confidence,created_by) VALUES(:i,:o,:e,:d,:dep,:hc,:ah,:ab,:ot,:net,:cf,:u) ON CONFLICT(organization_id,entity_id,forecast_date,department_id) DO UPDATE SET available_headcount=:hc,available_hours=:ah,expected_absence_hours=:ab,expected_overtime_hours=:ot,net_available_hours=:net,confidence=:cf,status='FORECAST' '''),{'i':i,'o':body['organization_id'],'e':body['entity_id'],'d':body['forecast_date'],'dep':body.get('department_id'),'hc':int(body.get('available_headcount') or 0),'ah':float(ah),'ab':float(absence),'ot':float(ot),'net':float(net),'cf':float(conf),'u':str(u.user_id)})
        return {'availability_id':i,'net_available_hours':float(net),'status':'FORECAST'}
    @app.get('/v90dr/workforce/dashboard')
    def dashboard(request:Request, organization_id:str, entity_id:str):
        _perm(engine,request,'workforce_capacity.view')
        with engine.connect() as c:
            x=c.execute(text('''SELECT COALESCE(SUM(required_hours),0) rh,COALESCE(SUM(available_hours),0) ah,COALESCE(SUM(capacity_gap_hours),0) gap,COALESCE(SUM(skill_gap_count),0) sg FROM hr_workforce_capacity_plan WHERE organization_id=:o AND entity_id=:e'''),{'o':organization_id,'e':entity_id}).mappings().first()
            y=c.execute(text('''SELECT COALESCE(SUM(net_available_hours),0) net,COALESCE(SUM(expected_absence_hours),0) absence,COALESCE(SUM(expected_overtime_hours),0) ot FROM hr_labour_availability_forecast WHERE organization_id=:o AND entity_id=:e'''),{'o':organization_id,'e':entity_id}).mappings().first()
        return {'required_hours':float(_num(x['rh'])),'available_hours':float(_num(x['ah'])),'capacity_gap_hours':float(_num(x['gap'])),'skill_gap_count':int(x['sg'] or 0),'forecast_net_available_hours':float(_num(y['net'])),'expected_absence_hours':float(_num(y['absence'])),'expected_overtime_hours':float(_num(y['ot']))}
    @app.get('/ui/workforce-capacity')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'workforce-capacity.html')

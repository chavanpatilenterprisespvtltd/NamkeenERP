from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def _n(v): return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
def _perm(engine, request, p):
    u=authenticate(request); ps=permissions_for_user(engine,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def register_v90ds_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for p,n in [('workforce_optimization.view','View Workforce Optimization'),('workforce_optimization.manage','Manage Workforce Optimization'),('workforce_optimization.post','Post Workforce Optimization')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
    @app.post('/v90ds/workforce/training-courses')
    def course(body:dict, request:Request):
        u=_perm(engine,request,'workforce_optimization.manage')
        for k in ('organization_id','entity_id','course_code','course_name'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        h=_n(body.get('duration_hours'))
        if h<0: raise HTTPException(400,'duration_hours must be non-negative')
        i=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_training_course(training_id,organization_id,entity_id,course_code,course_name,skill_id,provider,duration_hours,mandatory,created_by) VALUES(:i,:o,:e,:c,:n,:s,:p,:h,:m,:u) ON CONFLICT(organization_id,entity_id,course_code) DO UPDATE SET course_name=:n,skill_id=:s,provider=:p,duration_hours=:h,mandatory=:m,active=TRUE'''),{'i':i,'o':body['organization_id'],'e':body['entity_id'],'c':body['course_code'],'n':body['course_name'],'s':body.get('skill_id'),'p':body.get('provider'),'h':float(h),'m':bool(body.get('mandatory',False)),'u':str(u.user_id)})
        return {'training_id':i,'status':'ACTIVE'}
    @app.post('/v90ds/workforce/training')
    def training(body:dict, request:Request):
        u=_perm(engine,request,'workforce_optimization.post')
        for k in ('organization_id','entity_id','employee_id','training_id'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_employee_training(employee_training_id,organization_id,entity_id,employee_id,training_id,scheduled_date,completed_date,status,score,created_by) VALUES(:i,:o,:e,:emp,:t,:sd,:cd,:s,:sc,:u) ON CONFLICT(organization_id,entity_id,employee_id,training_id,scheduled_date) DO UPDATE SET completed_date=:cd,status=:s,score=:sc'''),{'i':i,'o':body['organization_id'],'e':body['entity_id'],'emp':body['employee_id'],'t':body['training_id'],'sd':body.get('scheduled_date'),'cd':body.get('completed_date'),'s':str(body.get('status') or 'PLANNED').upper(),'sc':float(_n(body['score'])) if body.get('score') is not None else None,'u':str(u.user_id)})
        return {'employee_training_id':i,'status':str(body.get('status') or 'PLANNED').upper()}
    @app.post('/v90ds/workforce/certifications')
    def certification(body:dict, request:Request):
        u=_perm(engine,request,'workforce_optimization.manage')
        for k in ('organization_id','entity_id','employee_id','certification_code','certification_name'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_employee_certification(certification_id,organization_id,entity_id,employee_id,certification_code,certification_name,issued_date,expiry_date,status,skill_id,created_by) VALUES(:i,:o,:e,:emp,:c,:n,:id,:ed,:s,:sk,:u)'''),{'i':i,'o':body['organization_id'],'e':body['entity_id'],'emp':body['employee_id'],'c':body['certification_code'],'n':body['certification_name'],'id':body.get('issued_date'),'ed':body.get('expiry_date'),'s':str(body.get('status') or 'ACTIVE').upper(),'sk':body.get('skill_id'),'u':str(u.user_id)})
        return {'certification_id':i,'status':str(body.get('status') or 'ACTIVE').upper()}
    @app.post('/v90ds/workforce/skill-gaps')
    def gap(body:dict, request:Request):
        u=_perm(engine,request,'workforce_optimization.post')
        for k in ('organization_id','entity_id','plan_date','skill_id'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        req=max(0,int(body.get('required_count') or 0)); avail=max(0,int(body.get('available_count') or 0)); g=max(0,req-avail)
        priority=str(body.get('priority') or ('HIGH' if g else 'LOW')).upper()
        i=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_skill_gap_plan(gap_plan_id,organization_id,entity_id,plan_date,department_id,skill_id,required_level,available_count,required_count,gap_count,priority,training_recommended,created_by) VALUES(:i,:o,:e,:d,:dep,:s,:l,:a,:r,:g,:p,:tr,:u) ON CONFLICT(organization_id,entity_id,plan_date,department_id,skill_id) DO UPDATE SET required_level=:l,available_count=:a,required_count=:r,gap_count=:g,priority=:p,training_recommended=:tr,status='OPEN' '''),{'i':i,'o':body['organization_id'],'e':body['entity_id'],'d':body['plan_date'],'dep':body.get('department_id'),'s':body['skill_id'],'l':max(1,int(body.get('required_level') or 1)),'a':avail,'r':req,'g':g,'p':priority,'tr':bool(body.get('training_recommended',True)),'u':str(u.user_id)})
        return {'gap_plan_id':i,'gap_count':g,'priority':priority,'status':'OPEN'}
    @app.post('/v90ds/workforce/optimize')
    def optimize(body:dict, request:Request):
        u=_perm(engine,request,'workforce_optimization.post')
        for k in ('organization_id','entity_id','plan_date'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        ch=_n(body.get('current_hours')); oh=_n(body.get('optimized_hours')); cc=_n(body.get('current_cost')); oc=_n(body.get('optimized_cost'))
        if min(ch,oh,cc,oc)<0: raise HTTPException(400,'optimization values must be non-negative')
        sh=_n(ch-oh); sc=_n(cc-oc); util=_n((oh/ch)*100) if ch else Decimal('0')
        i=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_workforce_optimization(optimization_id,organization_id,entity_id,plan_date,department_id,current_hours,optimized_hours,current_cost,optimized_cost,saving_hours,saving_cost,utilization_pct,created_by) VALUES(:i,:o,:e,:d,:dep,:ch,:oh,:cc,:oc,:sh,:sc,:u,:by) ON CONFLICT(organization_id,entity_id,plan_date,department_id) DO UPDATE SET current_hours=:ch,optimized_hours=:oh,current_cost=:cc,optimized_cost=:oc,saving_hours=:sh,saving_cost=:sc,utilization_pct=:u,status='DRAFT' '''),{'i':i,'o':body['organization_id'],'e':body['entity_id'],'d':body['plan_date'],'dep':body.get('department_id'),'ch':float(ch),'oh':float(oh),'cc':float(cc),'oc':float(oc),'sh':float(sh),'sc':float(sc),'u':float(util),'by':str(u.user_id)})
        return {'optimization_id':i,'saving_hours':float(sh),'saving_cost':float(sc),'utilization_pct':float(util),'status':'DRAFT'}
    @app.get('/v90ds/workforce/dashboard')
    def dashboard(request:Request, organization_id:str, entity_id:str):
        _perm(engine,request,'workforce_optimization.view')
        with engine.connect() as c:
            g=c.execute(text('''SELECT COALESCE(SUM(gap_count),0) gaps,COUNT(*) plans FROM hr_skill_gap_plan WHERE organization_id=:o AND entity_id=:e AND status='OPEN' '''),{'o':organization_id,'e':entity_id}).mappings().first()
            o=c.execute(text('''SELECT COALESCE(SUM(saving_hours),0) sh,COALESCE(SUM(saving_cost),0) sc,COALESCE(AVG(utilization_pct),0) util FROM hr_workforce_optimization WHERE organization_id=:o AND entity_id=:e'''),{'o':organization_id,'e':entity_id}).mappings().first()
            t=c.execute(text("SELECT COUNT(*) FROM hr_employee_training WHERE organization_id=:o AND entity_id=:e AND status='COMPLETED'"),{'o':organization_id,'e':entity_id}).scalar()
            cert=c.execute(text("SELECT COUNT(*) FROM hr_employee_certification WHERE organization_id=:o AND entity_id=:e AND status='ACTIVE' AND (expiry_date IS NULL OR expiry_date>=CURRENT_DATE)"),{'o':organization_id,'e':entity_id}).scalar()
        return {'open_skill_gap_count':int(g['gaps'] or 0),'skill_gap_plans':int(g['plans'] or 0),'training_completed':int(t or 0),'active_certifications':int(cert or 0),'potential_saving_hours':float(_n(o['sh'])),'potential_saving_cost':float(_n(o['sc'])),'avg_utilization_pct':float(_n(o['util']))}
    @app.get('/ui/workforce-optimization')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'workforce-optimization.html')

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

def register_v90dp_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for p,n in [('workforce_performance.view','View Workforce Performance'),('workforce_performance.manage','Manage Workforce Performance'),('workforce_performance.post','Post Workforce Performance'),('workforce_performance.close','Close Workforce Performance')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_shift_attendance(
            attendance_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, employee_id TEXT NOT NULL,
            work_date DATE NOT NULL, shift_code TEXT, scheduled_hours NUMERIC NOT NULL DEFAULT 0, worked_hours NUMERIC NOT NULL DEFAULT 0,
            overtime_hours NUMERIC NOT NULL DEFAULT 0, absent BOOLEAN NOT NULL DEFAULT FALSE, status TEXT NOT NULL DEFAULT 'POSTED',
            created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,employee_id,work_date))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_workforce_incentive_rule(
            rule_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, rule_name TEXT NOT NULL,
            basis TEXT NOT NULL DEFAULT 'OUTPUT', threshold NUMERIC NOT NULL DEFAULT 0, rate NUMERIC NOT NULL DEFAULT 0,
            max_amount NUMERIC, active BOOLEAN NOT NULL DEFAULT TRUE, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,rule_name))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_workforce_incentive(
            incentive_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_id TEXT NOT NULL,
            employee_id TEXT NOT NULL, production_batch_id TEXT, basis_value NUMERIC NOT NULL DEFAULT 0, incentive_amount NUMERIC NOT NULL DEFAULT 0,
            rule_id TEXT, status TEXT NOT NULL DEFAULT 'CALCULATED', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_workforce_performance_snapshot(
            snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_id TEXT NOT NULL,
            employee_id TEXT NOT NULL, attendance_days INTEGER NOT NULL DEFAULT 0, scheduled_hours NUMERIC NOT NULL DEFAULT 0,
            worked_hours NUMERIC NOT NULL DEFAULT 0, overtime_hours NUMERIC NOT NULL DEFAULT 0, output_qty NUMERIC NOT NULL DEFAULT 0,
            labour_cost NUMERIC NOT NULL DEFAULT 0, output_per_hour NUMERIC NOT NULL DEFAULT 0, labour_cost_per_unit NUMERIC NOT NULL DEFAULT 0,
            attendance_rate NUMERIC NOT NULL DEFAULT 0, productivity_index NUMERIC NOT NULL DEFAULT 0, incentive_amount NUMERIC NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'READY', generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_id,employee_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_workforce_performance_close(
            close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'CLOSED', closed_by TEXT NOT NULL, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_id))'''))

    @app.post('/v90dp/workforce/attendance')
    def attendance(body:dict, request:Request):
        u=_perm(engine,request,'workforce_performance.post')
        for k in ('organization_id','entity_id','employee_id','work_date'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        i=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_shift_attendance(attendance_id,organization_id,entity_id,employee_id,work_date,shift_code,scheduled_hours,worked_hours,overtime_hours,absent,created_by)
            VALUES(:i,:o,:e,:emp,:d,:s,:sh,:wh,:ot,:a,:u) ON CONFLICT(organization_id,entity_id,employee_id,work_date) DO UPDATE SET shift_code=:s,scheduled_hours=:sh,worked_hours=:wh,overtime_hours=:ot,absent=:a,status='POSTED' ''').params(),{}) if False else None
            c.execute(text('''INSERT INTO hr_shift_attendance(attendance_id,organization_id,entity_id,employee_id,work_date,shift_code,scheduled_hours,worked_hours,overtime_hours,absent,created_by)
            VALUES(:i,:o,:e,:emp,:d,:s,:sh,:wh,:ot,:a,:u) ON CONFLICT(organization_id,entity_id,employee_id,work_date) DO UPDATE SET shift_code=:s,scheduled_hours=:sh,worked_hours=:wh,overtime_hours=:ot,absent=:a,status='POSTED' '''),{'i':i,'o':body['organization_id'],'e':body['entity_id'],'emp':body['employee_id'],'d':body['work_date'],'s':body.get('shift_code'),'sh':float(_money(body.get('scheduled_hours'))),'wh':float(_money(body.get('worked_hours'))),'ot':float(_money(body.get('overtime_hours'))),'a':bool(body.get('absent',False)),'u':str(u.user_id)})
        return {'attendance_id':i,'status':'POSTED'}

    @app.post('/v90dp/workforce/incentive-rules')
    def rule(body:dict, request:Request):
        u=_perm(engine,request,'workforce_performance.manage')
        for k in ('organization_id','entity_id','rule_name'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        rate=_money(body.get('rate')); threshold=_money(body.get('threshold'))
        if rate<0 or threshold<0: raise HTTPException(400,'threshold and rate must be non-negative')
        i=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_workforce_incentive_rule(rule_id,organization_id,entity_id,rule_name,basis,threshold,rate,max_amount,active,created_by) VALUES(:i,:o,:e,:n,:b,:t,:r,:m,:a,:u)
            ON CONFLICT(organization_id,entity_id,rule_name) DO UPDATE SET basis=:b,threshold=:t,rate=:r,max_amount=:m,active=:a'''),{'i':i,'o':body['organization_id'],'e':body['entity_id'],'n':body['rule_name'],'b':str(body.get('basis') or 'OUTPUT').upper(),'t':float(threshold),'r':float(rate),'m':float(_money(body['max_amount'])) if body.get('max_amount') is not None else None,'a':bool(body.get('active',True)),'u':str(u.user_id)})
        return {'rule_id':i,'status':'SAVED'}

    @app.post('/v90dp/workforce/incentives/calculate')
    def calculate(body:dict, request:Request):
        u=_perm(engine,request,'workforce_performance.post')
        for k in ('organization_id','entity_id','period_id','employee_id'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        basis=_money(body.get('basis_value')); amount=Decimal('0')
        with engine.begin() as c:
            r=c.execute(text('''SELECT * FROM hr_workforce_incentive_rule WHERE organization_id=:o AND entity_id=:e AND active=TRUE AND threshold<=:b ORDER BY threshold DESC LIMIT 1'''),{'o':body['organization_id'],'e':body['entity_id'],'b':float(basis)}).mappings().first()
            if r:
                amount=_money(basis*_money(r['rate']))
                if r['max_amount'] is not None: amount=min(amount,_money(r['max_amount']))
            i=str(uuid4()); c.execute(text('''INSERT INTO hr_workforce_incentive(incentive_id,organization_id,entity_id,period_id,employee_id,production_batch_id,basis_value,incentive_amount,rule_id,created_by) VALUES(:i,:o,:e,:p,:emp,:b,:v,:a,:r,:u)'''),{'i':i,'o':body['organization_id'],'e':body['entity_id'],'p':body['period_id'],'emp':body['employee_id'],'b':body.get('production_batch_id'),'v':float(basis),'a':float(amount),'r':r['rule_id'] if r else None,'u':str(u.user_id)})
        return {'incentive_id':i,'incentive_amount':float(amount),'status':'CALCULATED'}

    @app.post('/v90dp/workforce/snapshot')
    def snapshot(body:dict, request:Request):
        u=_perm(engine,request,'workforce_performance.post')
        org,ent,period,emp=[body.get(k) for k in ('organization_id','entity_id','period_id','employee_id')]
        if not all(str(x or '').strip() for x in (org,ent,period,emp)): raise HTTPException(400,'organization_id, entity_id, period_id and employee_id are required')
        with engine.begin() as c:
            a=c.execute(text('''SELECT COUNT(*) days,COALESCE(SUM(scheduled_hours),0) sh,COALESCE(SUM(worked_hours),0) wh,COALESCE(SUM(overtime_hours),0) ot,COALESCE(SUM(CASE WHEN absent THEN 1 ELSE 0 END),0) abs FROM hr_shift_attendance WHERE organization_id=:o AND entity_id=:e AND employee_id=:emp AND work_date IN (SELECT start_date FROM hr_payroll_period WHERE period_id=:p)'''),{'o':org,'e':ent,'emp':emp,'p':period}).mappings().first()
            # Attendance date-range is supplied optionally for deployments whose period master differs.
            if not a or not a['days']:
                a=c.execute(text('''SELECT COUNT(*) days,COALESCE(SUM(scheduled_hours),0) sh,COALESCE(SUM(worked_hours),0) wh,COALESCE(SUM(overtime_hours),0) ot,COALESCE(SUM(CASE WHEN absent THEN 1 ELSE 0 END),0) abs FROM hr_shift_attendance WHERE organization_id=:o AND entity_id=:e AND employee_id=:emp'''),{'o':org,'e':ent,'emp':emp}).mappings().first()
            p=c.execute(text('''SELECT COALESCE(SUM(output_qty),0) outq,COALESCE(SUM(labour_cost),0) cost FROM hr_production_labour_capture WHERE organization_id=:o AND entity_id=:e AND employee_id=:emp'''),{'o':org,'e':ent,'emp':emp}).mappings().first()
            inc=c.execute(text('SELECT COALESCE(SUM(incentive_amount),0) FROM hr_workforce_incentive WHERE organization_id=:o AND entity_id=:e AND period_id=:p AND employee_id=:emp'),{'o':org,'e':ent,'p':period,'emp':emp}).scalar()
            days=int(a['days'] or 0); sh=_money(a['sh']); wh=_money(a['wh']); ot=_money(a['ot']); outq=_money(p['outq']); cost=_money(p['cost']); incentive=_money(inc)
            oph=_money(outq/wh) if wh else Decimal('0'); cpu=_money(cost/outq) if outq else Decimal('0'); ar=_money((days-int(a['abs'] or 0))*100/days) if days else Decimal('0'); idx=_money(oph*100) if oph else Decimal('0')
            i=str(uuid4()); c.execute(text('''INSERT INTO hr_workforce_performance_snapshot(snapshot_id,organization_id,entity_id,period_id,employee_id,attendance_days,scheduled_hours,worked_hours,overtime_hours,output_qty,labour_cost,output_per_hour,labour_cost_per_unit,attendance_rate,productivity_index,incentive_amount) VALUES(:i,:o,:e,:p,:emp,:d,:sh,:wh,:ot,:q,:c,:oph,:cpu,:ar,:idx,:inc) ON CONFLICT(organization_id,entity_id,period_id,employee_id) DO UPDATE SET attendance_days=:d,scheduled_hours=:sh,worked_hours=:wh,overtime_hours=:ot,output_qty=:q,labour_cost=:c,output_per_hour=:oph,labour_cost_per_unit=:cpu,attendance_rate=:ar,productivity_index=:idx,incentive_amount=:inc,status='READY',generated_at=CURRENT_TIMESTAMP'''),{'i':i,'o':org,'e':ent,'p':period,'emp':emp,'d':days,'sh':float(sh),'wh':float(wh),'ot':float(ot),'q':float(outq),'c':float(cost),'oph':float(oph),'cpu':float(cpu),'ar':float(ar),'idx':float(idx),'inc':float(incentive)})
        return {'employee_id':emp,'period_id':period,'attendance_rate':float(ar),'worked_hours':float(wh),'overtime_hours':float(ot),'output_qty':float(outq),'output_per_hour':float(oph),'labour_cost_per_unit':float(cpu),'productivity_index':float(idx),'incentive_amount':float(incentive),'status':'READY'}

    @app.get('/v90dp/workforce/mis')
    def mis(request:Request, organization_id:str, entity_id:str, period_id:str|None=None):
        _perm(engine,request,'workforce_performance.view')
        with engine.connect() as c:
            q='SELECT * FROM hr_workforce_performance_snapshot WHERE organization_id=:o AND entity_id=:e'; params={'o':organization_id,'e':entity_id}
            if period_id: q+=' AND period_id=:p'; params['p']=period_id
            q+=' ORDER BY generated_at DESC'; rows=c.execute(text(q),params).mappings().all()
        return {'rows':[dict(x) for x in rows]}

    @app.post('/v90dp/workforce/close')
    def close(body:dict, request:Request):
        u=_perm(engine,request,'workforce_performance.close'); org,ent,period=body.get('organization_id'),body.get('entity_id'),body.get('period_id')
        if not all(str(x or '').strip() for x in (org,ent,period)): raise HTTPException(400,'organization_id, entity_id and period_id are required')
        with engine.begin() as c:
            if not c.execute(text('SELECT 1 FROM hr_workforce_performance_snapshot WHERE organization_id=:o AND entity_id=:e AND period_id=:p LIMIT 1'),{'o':org,'e':ent,'p':period}).scalar(): raise HTTPException(409,'no workforce snapshot exists for period')
            i=str(uuid4()); c.execute(text('''INSERT INTO hr_workforce_performance_close(close_id,organization_id,entity_id,period_id,closed_by) VALUES(:i,:o,:e,:p,:u) ON CONFLICT(organization_id,entity_id,period_id) DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),{'i':i,'o':org,'e':ent,'p':period,'u':str(u.user_id)})
        return {'period_id':period,'status':'CLOSED'}

    @app.get('/v90dp/workforce/dashboard')
    def dashboard(request:Request, organization_id:str, entity_id:str):
        _perm(engine,request,'workforce_performance.view')
        with engine.connect() as c:
            r=c.execute(text('''SELECT COUNT(*) employees,COALESCE(SUM(worked_hours),0) hours,COALESCE(SUM(overtime_hours),0) ot,COALESCE(SUM(output_qty),0) output,COALESCE(SUM(labour_cost),0) cost,COALESCE(SUM(incentive_amount),0) incentives,COALESCE(AVG(attendance_rate),0) attendance,COALESCE(AVG(productivity_index),0) productivity FROM hr_workforce_performance_snapshot WHERE organization_id=:o AND entity_id=:e'''),{'o':organization_id,'e':entity_id}).mappings().first()
        h=_money(r['hours']); out=_money(r['output']); cost=_money(r['cost'])
        return {'employees':int(r['employees'] or 0),'worked_hours':float(h),'overtime_hours':float(_money(r['ot'])),'output_qty':float(out),'labour_cost':float(cost),'incentives':float(_money(r['incentives'])),'avg_attendance_rate':float(_money(r['attendance'])),'avg_productivity_index':float(_money(r['productivity'])),'output_per_hour':float(_money(out/h) if h else 0),'labour_cost_per_unit':float(_money(cost/out) if out else 0)}

    @app.get('/ui/workforce-performance')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'workforce-performance.html')

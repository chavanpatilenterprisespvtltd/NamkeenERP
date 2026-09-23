from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
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

def _d(v): return Decimal(str(v or 0)).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)

def _ensure(e):
    with e.begin() as c:
        for p,n in [('machine_oee.view','View Machine OEE'),('machine_oee.manage','Manage Machine OEE'),('machine_oee.approve','Approve Machine OEE')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_machine_status(
            status_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, work_center_id TEXT NOT NULL,
            status_code TEXT NOT NULL, reason_code TEXT, event_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            event_end TIMESTAMP, duration_minutes NUMERIC NOT NULL DEFAULT 0, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_machine_run(
            run_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, work_center_id TEXT NOT NULL,
            production_order_id TEXT, product_id TEXT, shift_code TEXT, planned_qty NUMERIC NOT NULL DEFAULT 0,
            good_qty NUMERIC NOT NULL DEFAULT 0, reject_qty NUMERIC NOT NULL DEFAULT 0, ideal_cycle_minutes NUMERIC NOT NULL DEFAULT 0,
            planned_minutes NUMERIC NOT NULL DEFAULT 0, actual_run_minutes NUMERIC NOT NULL DEFAULT 0,
            downtime_minutes NUMERIC NOT NULL DEFAULT 0, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_machine_oee(
            oee_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, work_center_id TEXT NOT NULL,
            period_start DATE NOT NULL, period_end DATE NOT NULL, planned_minutes NUMERIC NOT NULL DEFAULT 0,
            run_minutes NUMERIC NOT NULL DEFAULT 0, downtime_minutes NUMERIC NOT NULL DEFAULT 0, ideal_minutes NUMERIC NOT NULL DEFAULT 0,
            good_qty NUMERIC NOT NULL DEFAULT 0, total_qty NUMERIC NOT NULL DEFAULT 0, availability_pct NUMERIC NOT NULL DEFAULT 0,
            performance_pct NUMERIC NOT NULL DEFAULT 0, quality_pct NUMERIC NOT NULL DEFAULT 0, oee_pct NUMERIC NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'CALCULATED', approved_by TEXT, approved_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,work_center_id,period_start,period_end))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_machine_oee_reason(
            reason_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, reason_code TEXT NOT NULL,
            reason_name TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'UNPLANNED_DOWNTIME', active BOOLEAN NOT NULL DEFAULT TRUE,
            UNIQUE(organization_id,entity_id,reason_code))'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_machine_oee_run ON manufacturing_machine_run(organization_id,entity_id,work_center_id,created_at)'))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_machine_oee_status ON manufacturing_machine_status(organization_id,entity_id,work_center_id,event_at)'))

def register_v90db_routes(app:FastAPI,e):
    _ensure(e)
    @app.post('/v90db/machines/reasons')
    def reason(body:dict,request:Request):
        u=_perm(e,request,'machine_oee.manage')
        for k in ('organization_id','entity_id','reason_code','reason_name'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        rid=str(uuid4())
        with e.begin() as c: c.execute(text('''INSERT INTO manufacturing_machine_oee_reason(reason_id,organization_id,entity_id,reason_code,reason_name,category,active) VALUES(:i,:o,:e,:c,:n,:g,:a) ON CONFLICT(organization_id,entity_id,reason_code) DO UPDATE SET reason_name=:n,category=:g,active=:a'''),{'i':rid,'o':body['organization_id'],'e':body['entity_id'],'c':body['reason_code'],'n':body['reason_name'],'g':body.get('category','UNPLANNED_DOWNTIME'),'a':bool(body.get('active',True))})
        return {'reason_id':rid,'status':'ACTIVE'}
    @app.post('/v90db/machines/status')
    def status(body:dict,request:Request):
        u=_perm(e,request,'machine_oee.manage')
        for k in ('organization_id','entity_id','work_center_id','status_code'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        sid=str(uuid4())
        with e.begin() as c: c.execute(text('''INSERT INTO manufacturing_machine_status(status_id,organization_id,entity_id,work_center_id,status_code,reason_code,event_at,event_end,duration_minutes,created_by) VALUES(:i,:o,:e,:w,:s,:r,COALESCE(:at,CURRENT_TIMESTAMP),:en,:m,:u)'''),{'i':sid,'o':body['organization_id'],'e':body['entity_id'],'w':body['work_center_id'],'s':body['status_code'],'r':body.get('reason_code'),'at':body.get('event_at'),'en':body.get('event_end'),'m':float(_d(body.get('duration_minutes'))),'u':str(u.user_id)})
        return {'status_id':sid,'status':'RECORDED'}
    @app.post('/v90db/machines/runs')
    def run(body:dict,request:Request):
        u=_perm(e,request,'machine_oee.manage')
        for k in ('organization_id','entity_id','work_center_id'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        rid=str(uuid4())
        with e.begin() as c: c.execute(text('''INSERT INTO manufacturing_machine_run(run_id,organization_id,entity_id,work_center_id,production_order_id,product_id,shift_code,planned_qty,good_qty,reject_qty,ideal_cycle_minutes,planned_minutes,actual_run_minutes,downtime_minutes,created_by) VALUES(:i,:o,:e,:w,:po,:p,:s,:pq,:g,:r,:ic,:pm,:rm,:dm,:u)'''),{'i':rid,'o':body['organization_id'],'e':body['entity_id'],'w':body['work_center_id'],'po':body.get('production_order_id'),'p':body.get('product_id'),'s':body.get('shift_code'),'pq':float(_d(body.get('planned_qty'))),'g':float(_d(body.get('good_qty'))),'r':float(_d(body.get('reject_qty'))),'ic':float(_d(body.get('ideal_cycle_minutes'))),'pm':float(_d(body.get('planned_minutes'))),'rm':float(_d(body.get('actual_run_minutes'))),'dm':float(_d(body.get('downtime_minutes'))),'u':str(u.user_id)})
        return {'run_id':rid,'status':'RECORDED'}
    @app.post('/v90db/machines/oee/calculate')
    def calculate(body:dict,request:Request):
        u=_perm(e,request,'machine_oee.manage')
        for k in ('organization_id','entity_id','work_center_id','period_start','period_end'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        with e.begin() as c:
            rows=c.execute(text('''SELECT COALESCE(SUM(planned_minutes),0) planned,COALESCE(SUM(actual_run_minutes),0) run,COALESCE(SUM(downtime_minutes),0) down,COALESCE(SUM(good_qty),0) good,COALESCE(SUM(good_qty+reject_qty),0) total,COALESCE(SUM(good_qty*ideal_cycle_minutes),0) ideal FROM manufacturing_machine_run WHERE organization_id=:o AND entity_id=:e AND work_center_id=:w AND DATE(created_at) BETWEEN :s AND :d'''),{'o':body['organization_id'],'e':body['entity_id'],'w':body['work_center_id'],'s':body['period_start'],'d':body['period_end']}).mappings().one()
            planned=_d(rows['planned']); run=_d(rows['run']); down=_d(rows['down']); ideal=_d(rows['ideal']); good=_d(rows['good']); total=_d(rows['total'])
            availability=(run/planned*100) if planned else Decimal(0)
            performance=(ideal/run*100) if run else Decimal(0)
            quality=(good/total*100) if total else Decimal(0)
            oee=(availability*performance*quality/10000) if availability and performance and quality else Decimal(0)
            oid=str(uuid4())
            c.execute(text('''INSERT INTO manufacturing_machine_oee(oee_id,organization_id,entity_id,work_center_id,period_start,period_end,planned_minutes,run_minutes,downtime_minutes,ideal_minutes,good_qty,total_qty,availability_pct,performance_pct,quality_pct,oee_pct) VALUES(:i,:o,:e,:w,:s,:d,:pm,:rm,:dm,:im,:g,:t,:a,:p,:q,:oee) ON CONFLICT(organization_id,entity_id,work_center_id,period_start,period_end) DO UPDATE SET planned_minutes=:pm,run_minutes=:rm,downtime_minutes=:dm,ideal_minutes=:im,good_qty=:g,total_qty=:t,availability_pct=:a,performance_pct=:p,quality_pct=:q,oee_pct=:oee,status='CALCULATED' RETURNING oee_id'''),{'i':oid,'o':body['organization_id'],'e':body['entity_id'],'w':body['work_center_id'],'s':body['period_start'],'d':body['period_end'],'pm':float(planned),'rm':float(run),'dm':float(down),'im':float(ideal),'g':float(good),'t':float(total),'a':float(availability),'p':float(performance),'q':float(quality),'oee':float(oee)})
        return {'oee_id':oid,'availability_pct':float(availability),'performance_pct':float(performance),'quality_pct':float(quality),'oee_pct':float(oee)}
    @app.post('/v90db/machines/oee/{oee_id}/approve')
    def approve(oee_id:str,request:Request):
        u=_perm(e,request,'machine_oee.approve')
        with e.begin() as c:
            r=c.execute(text("UPDATE manufacturing_machine_oee SET status='APPROVED',approved_by=:u,approved_at=CURRENT_TIMESTAMP WHERE oee_id=:i AND status='CALCULATED' RETURNING oee_id"),{'i':oee_id,'u':str(u.user_id)}).first()
            if not r: raise HTTPException(404,'calculated OEE not found')
        return {'oee_id':oee_id,'status':'APPROVED'}
    @app.get('/v90db/machines/oee')
    def dashboard(request:Request,organization_id:str,entity_id:str,period_start:str,period_end:str):
        _perm(e,request,'machine_oee.view')
        with e.connect() as c:
            rows=c.execute(text('''SELECT work_center_id,AVG(availability_pct) availability_pct,AVG(performance_pct) performance_pct,AVG(quality_pct) quality_pct,AVG(oee_pct) oee_pct,SUM(downtime_minutes) downtime_minutes,SUM(total_qty) total_qty FROM manufacturing_machine_oee WHERE organization_id=:o AND entity_id=:e AND period_start>=:s AND period_end<=:d GROUP BY work_center_id ORDER BY AVG(oee_pct) DESC'''),{'o':organization_id,'e':entity_id,'s':period_start,'d':period_end}).mappings().all()
            reasons=c.execute(text('''SELECT reason_code,COUNT(*) events,COALESCE(SUM(duration_minutes),0) downtime_minutes FROM manufacturing_machine_status WHERE organization_id=:o AND entity_id=:e AND DATE(event_at) BETWEEN :s AND :d AND reason_code IS NOT NULL GROUP BY reason_code ORDER BY downtime_minutes DESC'''),{'o':organization_id,'e':entity_id,'s':period_start,'d':period_end}).mappings().all()
        return {'machines':[dict(x) for x in rows],'downtime_reasons':[dict(x) for x in reasons]}
    @app.get('/ui/manufacturing-machine-oee')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'manufacturing-machine-oee.html')

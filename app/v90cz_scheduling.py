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
        perms=[('mfg_sched.view','View Manufacturing Scheduling'),('mfg_sched.manage','Manage Manufacturing Scheduling'),('mfg_sched.approve','Approve Manufacturing Scheduling')]
        for p,n in perms: c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_work_center(
            work_center_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            code TEXT NOT NULL, name TEXT NOT NULL, capacity_per_shift NUMERIC NOT NULL DEFAULT 0,
            shifts_per_day NUMERIC NOT NULL DEFAULT 1, efficiency_pct NUMERIC NOT NULL DEFAULT 100,
            active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,code))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_shift_calendar(
            calendar_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            work_date DATE NOT NULL, shift_code TEXT NOT NULL, available_hours NUMERIC NOT NULL DEFAULT 0,
            available BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,work_date,shift_code))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_schedule(
            schedule_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            production_order_id TEXT NOT NULL, product_id TEXT NOT NULL, work_center_id TEXT NOT NULL,
            schedule_date DATE NOT NULL, shift_code TEXT NOT NULL, planned_qty NUMERIC NOT NULL DEFAULT 0,
            required_hours NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'PLANNED',
            approved_by TEXT, approved_at TIMESTAMP, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_schedule_exception(
            exception_id TEXT PRIMARY KEY, schedule_id TEXT NOT NULL, organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL, exception_type TEXT NOT NULL, message TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'WARNING', status TEXT NOT NULL DEFAULT 'OPEN',
            resolved_by TEXT, resolved_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_mfg_sched_scope ON manufacturing_schedule(organization_id,entity_id,schedule_date,work_center_id,status)'))

def register_v90cz_routes(app:FastAPI,e):
    _ensure(e)
    @app.post('/v90cz/manufacturing/work-centers')
    def wc(body:dict,request:Request):
        u=_perm(e,request,'mfg_sched.manage')
        for k in ('organization_id','entity_id','code','name'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        wid=str(uuid4())
        with e.begin() as c: c.execute(text('''INSERT INTO manufacturing_work_center(work_center_id,organization_id,entity_id,code,name,capacity_per_shift,shifts_per_day,efficiency_pct) VALUES(:i,:o,:e,:c,:n,:cap,:s,:eff)'''),{'i':wid,'o':body['organization_id'],'e':body['entity_id'],'c':body['code'],'n':body['name'],'cap':float(_d(body.get('capacity_per_shift'))),'s':float(_d(body.get('shifts_per_day') or 1)),'eff':float(_d(body.get('efficiency_pct') or 100))})
        return {'work_center_id':wid,'status':'ACTIVE'}
    @app.get('/v90cz/manufacturing/work-centers')
    def wcl(request:Request,organization_id:str,entity_id:str):
        _perm(e,request,'mfg_sched.view')
        with e.connect() as c: rows=c.execute(text('SELECT * FROM manufacturing_work_center WHERE organization_id=:o AND entity_id=:e ORDER BY code'),{'o':organization_id,'e':entity_id}).mappings().all()
        return {'work_centers':[dict(x) for x in rows]}
    @app.post('/v90cz/manufacturing/calendar')
    def cal(body:dict,request:Request):
        _perm(e,request,'mfg_sched.manage')
        for k in ('organization_id','entity_id','work_date','shift_code'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        cid=str(uuid4())
        with e.begin() as c: c.execute(text('''INSERT INTO manufacturing_shift_calendar(calendar_id,organization_id,entity_id,work_date,shift_code,available_hours,available) VALUES(:i,:o,:e,:d,:s,:h,:a) ON CONFLICT(organization_id,entity_id,work_date,shift_code) DO UPDATE SET available_hours=:h,available=:a'''),{'i':cid,'o':body['organization_id'],'e':body['entity_id'],'d':body['work_date'],'s':body['shift_code'],'h':float(_d(body.get('available_hours'))),'a':bool(body.get('available',True))})
        return {'calendar_id':cid,'status':'RECORDED'}
    @app.post('/v90cz/manufacturing/schedule')
    def schedule(body:dict,request:Request):
        u=_perm(e,request,'mfg_sched.manage')
        for k in ('organization_id','entity_id','production_order_id','product_id','work_center_id','schedule_date','shift_code','planned_qty','required_hours'):
            if body.get(k) is None or (isinstance(body.get(k),str) and not body[k].strip()): raise HTTPException(400,f'{k} is required')
        sid=str(uuid4()); qty=_d(body['planned_qty']); hrs=_d(body['required_hours']); exceptions=[]
        with e.begin() as c:
            wc=c.execute(text('SELECT capacity_per_shift,efficiency_pct,active FROM manufacturing_work_center WHERE work_center_id=:i'),{'i':body['work_center_id']}).mappings().first()
            if not wc: raise HTTPException(404,'work center not found')
            if not wc['active']: exceptions.append(('INACTIVE_WORK_CENTER','work center is inactive','ERROR'))
            cap=_d(wc['capacity_per_shift'])*_d(wc['efficiency_pct'])/Decimal(100)
            if hrs>cap and cap>0: exceptions.append(('CAPACITY_OVERLOAD',f'required hours {hrs} exceed effective shift capacity {cap}','ERROR'))
            cal=c.execute(text('SELECT available_hours,available FROM manufacturing_shift_calendar WHERE organization_id=:o AND entity_id=:e AND work_date=:d AND shift_code=:s'),{'o':body['organization_id'],'e':body['entity_id'],'d':body['schedule_date'],'s':body['shift_code']}).mappings().first()
            if cal and (not cal['available'] or hrs>_d(cal['available_hours'])): exceptions.append(('CALENDAR_CONFLICT','scheduled hours exceed available shift calendar','ERROR'))
            conflict=c.execute(text('''SELECT COALESCE(SUM(required_hours),0) h FROM manufacturing_schedule WHERE organization_id=:o AND entity_id=:e AND work_center_id=:w AND schedule_date=:d AND shift_code=:s AND status IN ('PLANNED','APPROVED')'''),{'o':body['organization_id'],'e':body['entity_id'],'w':body['work_center_id'],'d':body['schedule_date'],'s':body['shift_code']}).scalar_one()
            if _d(conflict)+hrs>cap and cap>0: exceptions.append(('SCHEDULE_CONFLICT',f'work-center loading {_d(conflict)+hrs} exceeds capacity {cap}','ERROR'))
            c.execute(text('''INSERT INTO manufacturing_schedule(schedule_id,organization_id,entity_id,production_order_id,product_id,work_center_id,schedule_date,shift_code,planned_qty,required_hours,created_by) VALUES(:i,:o,:e,:p,:pr,:w,:d,:s,:q,:h,:u)'''),{'i':sid,'o':body['organization_id'],'e':body['entity_id'],'p':body['production_order_id'],'pr':body['product_id'],'w':body['work_center_id'],'d':body['schedule_date'],'s':body['shift_code'],'q':float(qty),'h':float(hrs),'u':str(u.user_id)})
            for typ,msg,sev in exceptions: c.execute(text('INSERT INTO manufacturing_schedule_exception(exception_id,schedule_id,organization_id,entity_id,exception_type,message,severity) VALUES(:i,:s,:o,:e,:t,:m,:v)'),{'i':str(uuid4()),'s':sid,'o':body['organization_id'],'e':body['entity_id'],'t':typ,'m':msg,'v':sev})
        return {'schedule_id':sid,'status':'PLANNED','exception_count':len(exceptions),'exceptions':[x[0] for x in exceptions]}
    @app.post('/v90cz/manufacturing/schedule/{schedule_id}/approve')
    def approve(schedule_id:str,request:Request):
        u=_perm(e,request,'mfg_sched.approve')
        with e.begin() as c:
            ex=c.execute(text("SELECT COUNT(*) FROM manufacturing_schedule_exception WHERE schedule_id=:i AND status='OPEN' AND severity='ERROR'"),{'i':schedule_id}).scalar_one()
            if ex: raise HTTPException(409,'schedule has unresolved capacity exceptions')
            r=c.execute(text("UPDATE manufacturing_schedule SET status='APPROVED',approved_by=:u,approved_at=CURRENT_TIMESTAMP WHERE schedule_id=:i AND status='PLANNED' RETURNING schedule_id"),{'i':schedule_id,'u':str(u.user_id)}).first()
            if not r: raise HTTPException(404,'planned schedule not found')
        return {'schedule_id':schedule_id,'status':'APPROVED'}
    @app.post('/v90cz/manufacturing/exception/{exception_id}/resolve')
    def resolve(exception_id:str,request:Request):
        u=_perm(e,request,'mfg_sched.manage')
        with e.begin() as c:
            r=c.execute(text("UPDATE manufacturing_schedule_exception SET status='RESOLVED',resolved_by=:u,resolved_at=CURRENT_TIMESTAMP WHERE exception_id=:i AND status='OPEN' RETURNING exception_id"),{'i':exception_id,'u':str(u.user_id)}).first()
            if not r: raise HTTPException(404,'open exception not found')
        return {'exception_id':exception_id,'status':'RESOLVED'}
    @app.get('/v90cz/manufacturing/dashboard')
    def dash(request:Request,organization_id:str,entity_id:str,start_date:str,end_date:str):
        _perm(e,request,'mfg_sched.view')
        with e.connect() as c:
            loading=c.execute(text('''SELECT work_center_id,COUNT(*) schedule_count,COALESCE(SUM(planned_qty),0) planned_qty,COALESCE(SUM(required_hours),0) required_hours FROM manufacturing_schedule WHERE organization_id=:o AND entity_id=:e AND schedule_date BETWEEN :s AND :d GROUP BY work_center_id ORDER BY required_hours DESC'''),{'o':organization_id,'e':entity_id,'s':start_date,'d':end_date}).mappings().all()
            exc=c.execute(text("SELECT exception_type,severity,COUNT(*) count FROM manufacturing_schedule_exception WHERE organization_id=:o AND entity_id=:e AND status='OPEN' GROUP BY exception_type,severity ORDER BY count DESC"),{'o':organization_id,'e':entity_id}).mappings().all()
        return {'work_center_loading':[dict(x) for x in loading],'open_exceptions':[dict(x) for x in exc]}
    @app.get('/ui/manufacturing-scheduling')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'manufacturing-scheduling.html')

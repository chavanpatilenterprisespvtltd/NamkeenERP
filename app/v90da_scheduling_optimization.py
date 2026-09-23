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
        for p,n in [('mfg_opt.view','View Production Scheduling Optimization'),('mfg_opt.manage','Manage Production Scheduling Optimization'),('mfg_opt.approve','Approve Production Scheduling Optimization')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_routing(
            routing_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, product_id TEXT NOT NULL,
            version_code TEXT NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,product_id,version_code))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_routing_operation(
            operation_id TEXT PRIMARY KEY, routing_id TEXT NOT NULL, sequence_no INTEGER NOT NULL, operation_code TEXT NOT NULL,
            operation_name TEXT NOT NULL, work_center_id TEXT NOT NULL, setup_hours NUMERIC NOT NULL DEFAULT 0,
            run_hours_per_unit NUMERIC NOT NULL DEFAULT 0, priority INTEGER NOT NULL DEFAULT 100, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(routing_id,sequence_no))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_work_center_compatibility(
            compatibility_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, product_id TEXT NOT NULL,
            work_center_id TEXT NOT NULL, setup_hours NUMERIC NOT NULL DEFAULT 0, run_hours_per_unit NUMERIC NOT NULL DEFAULT 0,
            efficiency_pct NUMERIC NOT NULL DEFAULT 100, active BOOLEAN NOT NULL DEFAULT TRUE,
            UNIQUE(organization_id,entity_id,product_id,work_center_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_optimized_schedule(
            optimized_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, production_order_id TEXT NOT NULL,
            product_id TEXT NOT NULL, operation_id TEXT NOT NULL, work_center_id TEXT NOT NULL, sequence_no INTEGER NOT NULL,
            scheduled_date DATE NOT NULL, shift_code TEXT NOT NULL, planned_qty NUMERIC NOT NULL DEFAULT 0, setup_hours NUMERIC NOT NULL DEFAULT 0,
            run_hours NUMERIC NOT NULL DEFAULT 0, total_hours NUMERIC NOT NULL DEFAULT 0, priority INTEGER NOT NULL DEFAULT 100,
            due_date DATE, status TEXT NOT NULL DEFAULT 'PROPOSED', created_by TEXT NOT NULL, approved_by TEXT, approved_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS manufacturing_optimization_exception(
            exception_id TEXT PRIMARY KEY, optimized_id TEXT NOT NULL, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            exception_type TEXT NOT NULL, message TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'WARNING', status TEXT NOT NULL DEFAULT 'OPEN',
            resolved_by TEXT, resolved_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_mfg_opt_scope ON manufacturing_optimized_schedule(organization_id,entity_id,scheduled_date,work_center_id,status)'))

def register_v90da_routes(app:FastAPI,e):
    _ensure(e)
    @app.post('/v90da/manufacturing/routings')
    def routing(body:dict,request:Request):
        _perm(e,request,'mfg_opt.manage')
        for k in ('organization_id','entity_id','product_id','version_code'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        rid=str(uuid4())
        with e.begin() as c: c.execute(text('INSERT INTO manufacturing_routing(routing_id,organization_id,entity_id,product_id,version_code) VALUES(:i,:o,:e,:p,:v)'),{'i':rid,'o':body['organization_id'],'e':body['entity_id'],'p':body['product_id'],'v':body['version_code']})
        return {'routing_id':rid,'status':'ACTIVE'}
    @app.post('/v90da/manufacturing/routings/{routing_id}/operations')
    def operation(routing_id:str,body:dict,request:Request):
        _perm(e,request,'mfg_opt.manage')
        for k in ('sequence_no','operation_code','operation_name','work_center_id'):
            if body.get(k) is None or (isinstance(body.get(k),str) and not body[k].strip()): raise HTTPException(400,f'{k} is required')
        oid=str(uuid4())
        with e.begin() as c: c.execute(text('INSERT INTO manufacturing_routing_operation(operation_id,routing_id,sequence_no,operation_code,operation_name,work_center_id,setup_hours,run_hours_per_unit,priority) VALUES(:i,:r,:s,:c,:n,:w,:sh,:rh,:p)'),{'i':oid,'r':routing_id,'s':int(body['sequence_no']),'c':body['operation_code'],'n':body['operation_name'],'w':body['work_center_id'],'sh':float(_d(body.get('setup_hours'))),'rh':float(_d(body.get('run_hours_per_unit'))),'p':int(body.get('priority') or 100)})
        return {'operation_id':oid,'status':'RECORDED'}
    @app.post('/v90da/manufacturing/compatibility')
    def compatibility(body:dict,request:Request):
        _perm(e,request,'mfg_opt.manage')
        for k in ('organization_id','entity_id','product_id','work_center_id'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        cid=str(uuid4())
        with e.begin() as c: c.execute(text('''INSERT INTO manufacturing_work_center_compatibility(compatibility_id,organization_id,entity_id,product_id,work_center_id,setup_hours,run_hours_per_unit,efficiency_pct,active) VALUES(:i,:o,:e,:p,:w,:s,:r,:f,:a) ON CONFLICT(organization_id,entity_id,product_id,work_center_id) DO UPDATE SET setup_hours=:s,run_hours_per_unit=:r,efficiency_pct=:f,active=:a'''),{'i':cid,'o':body['organization_id'],'e':body['entity_id'],'p':body['product_id'],'w':body['work_center_id'],'s':float(_d(body.get('setup_hours'))),'r':float(_d(body.get('run_hours_per_unit'))),'f':float(_d(body.get('efficiency_pct') or 100)),'a':bool(body.get('active',True))})
        return {'compatibility_id':cid,'status':'RECORDED'}
    @app.post('/v90da/manufacturing/optimize')
    def optimize(body:dict,request:Request):
        u=_perm(e,request,'mfg_opt.manage')
        for k in ('organization_id','entity_id','production_order_id','product_id','planned_qty','due_date','scheduled_date','shift_code'):
            if body.get(k) is None or (isinstance(body.get(k),str) and not body[k].strip()): raise HTTPException(400,f'{k} is required')
        qty=_d(body['planned_qty']); oid=str(uuid4()); exceptions=[]
        with e.begin() as c:
            r=c.execute(text('SELECT routing_id FROM manufacturing_routing WHERE organization_id=:o AND entity_id=:e AND product_id=:p AND active=true ORDER BY version_code DESC LIMIT 1'),{'o':body['organization_id'],'e':body['entity_id'],'p':body['product_id']}).first()
            if not r: raise HTTPException(404,'active routing not found')
            ops=c.execute(text('SELECT * FROM manufacturing_routing_operation WHERE routing_id=:r ORDER BY sequence_no'),{'r':r.routing_id}).mappings().all()
            if not ops: raise HTTPException(409,'routing has no operations')
            for op in ops:
                comp=c.execute(text('SELECT * FROM manufacturing_work_center_compatibility WHERE organization_id=:o AND entity_id=:e AND product_id=:p AND work_center_id=:w AND active=true'),{'o':body['organization_id'],'e':body['entity_id'],'p':body['product_id'],'w':op['work_center_id']}).mappings().first()
                setup=_d(comp['setup_hours'] if comp else op['setup_hours']); run_per=_d(comp['run_hours_per_unit'] if comp else op['run_hours_per_unit']); eff=_d(comp['efficiency_pct'] if comp else 100)
                if eff<=0: exceptions.append(('INVALID_EFFICIENCY','work center efficiency must be positive','ERROR')); continue
                run=(qty*run_per)/(eff/Decimal(100)); total=setup+run
                cap=c.execute(text('SELECT capacity_per_shift,efficiency_pct,active FROM manufacturing_work_center WHERE work_center_id=:w'),{'w':op['work_center_id']}).mappings().first()
                if not cap: exceptions.append(('WORK_CENTER_NOT_FOUND',f'work center {op["work_center_id"]} not found','ERROR'))
                elif not cap['active']: exceptions.append(('INACTIVE_WORK_CENTER','work center is inactive','ERROR'))
                elif _d(cap['capacity_per_shift'])*_d(cap['efficiency_pct'])/100 < total: exceptions.append(('FINITE_CAPACITY_OVERLOAD',f'operation {op["operation_code"]} requires {total} hours','ERROR'))
                sid=str(uuid4()); c.execute(text('''INSERT INTO manufacturing_optimized_schedule(optimized_id,organization_id,entity_id,production_order_id,product_id,operation_id,work_center_id,sequence_no,scheduled_date,shift_code,planned_qty,setup_hours,run_hours,total_hours,priority,due_date,created_by) VALUES(:i,:o,:e,:po,:p,:op,:w,:s,:d,:sh,:q,:st,:rh,:th,:pr,:due,:u)'''),{'i':sid,'o':body['organization_id'],'e':body['entity_id'],'po':body['production_order_id'],'p':body['product_id'],'op':op['operation_id'],'w':op['work_center_id'],'s':op['sequence_no'],'d':body['scheduled_date'],'sh':body['shift_code'],'q':float(qty),'st':float(setup),'rh':float(run),'th':float(total),'pr':op['priority'],'due':body['due_date'],'u':str(u.user_id)})
                for typ,msg,sev in exceptions[-1:]:
                    if typ in ('INVALID_EFFICIENCY','WORK_CENTER_NOT_FOUND','INACTIVE_WORK_CENTER','FINITE_CAPACITY_OVERLOAD'):
                        c.execute(text('INSERT INTO manufacturing_optimization_exception(exception_id,optimized_id,organization_id,entity_id,exception_type,message,severity) VALUES(:i,:s,:o,:e,:t,:m,:v)'),{'i':str(uuid4()),'s':sid,'o':body['organization_id'],'e':body['entity_id'],'t':typ,'m':msg,'v':sev})
            # Due-date rule: proposals scheduled after due date are exceptions.
            if str(body['scheduled_date'])>str(body['due_date']):
                exceptions.append(('DUE_DATE_MISS','scheduled date is after production due date','ERROR'))
        return {'status':'PROPOSED','operation_count':len(ops),'exception_count':len(exceptions),'exceptions':[x[0] for x in exceptions]}
    @app.post('/v90da/manufacturing/optimized/{optimized_id}/approve')
    def approve(optimized_id:str,request:Request):
        u=_perm(e,request,'mfg_opt.approve')
        with e.begin() as c:
            ex=c.execute(text("SELECT COUNT(*) FROM manufacturing_optimization_exception WHERE optimized_id=:i AND status='OPEN' AND severity='ERROR'"),{'i':optimized_id}).scalar_one()
            if ex: raise HTTPException(409,'optimized operation has unresolved exceptions')
            r=c.execute(text("UPDATE manufacturing_optimized_schedule SET status='APPROVED',approved_by=:u,approved_at=CURRENT_TIMESTAMP WHERE optimized_id=:i AND status='PROPOSED' RETURNING optimized_id"),{'i':optimized_id,'u':str(u.user_id)}).first()
            if not r: raise HTTPException(404,'proposed operation not found')
        return {'optimized_id':optimized_id,'status':'APPROVED'}
    @app.post('/v90da/manufacturing/exception/{exception_id}/resolve')
    def resolve(exception_id:str,request:Request):
        u=_perm(e,request,'mfg_opt.manage')
        with e.begin() as c:
            r=c.execute(text("UPDATE manufacturing_optimization_exception SET status='RESOLVED',resolved_by=:u,resolved_at=CURRENT_TIMESTAMP WHERE exception_id=:i AND status='OPEN' RETURNING exception_id"),{'i':exception_id,'u':str(u.user_id)}).first()
            if not r: raise HTTPException(404,'open exception not found')
        return {'exception_id':exception_id,'status':'RESOLVED'}
    @app.get('/v90da/manufacturing/optimization')
    def listing(request:Request,organization_id:str,entity_id:str,start_date:str,end_date:str):
        _perm(e,request,'mfg_opt.view')
        with e.connect() as c:
            rows=c.execute(text('''SELECT work_center_id,COUNT(*) operation_count,COALESCE(SUM(total_hours),0) total_hours,COALESCE(SUM(planned_qty),0) planned_qty,MIN(scheduled_date) first_date,MAX(due_date) latest_due_date FROM manufacturing_optimized_schedule WHERE organization_id=:o AND entity_id=:e AND scheduled_date BETWEEN :s AND :d GROUP BY work_center_id ORDER BY total_hours DESC'''),{'o':organization_id,'e':entity_id,'s':start_date,'d':end_date}).mappings().all()
            ex=c.execute(text("SELECT exception_type,severity,COUNT(*) count FROM manufacturing_optimization_exception WHERE organization_id=:o AND entity_id=:e AND status='OPEN' GROUP BY exception_type,severity ORDER BY count DESC"),{'o':organization_id,'e':entity_id}).mappings().all()
        return {'work_center_loading':[dict(x) for x in rows],'open_exceptions':[dict(x) for x in ex]}
    @app.get('/ui/manufacturing-scheduling-optimization')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'manufacturing-scheduling-optimization.html')

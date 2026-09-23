from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user


def _perm(engine, request, permission):
    u = authenticate(request)
    ps = permissions_for_user(engine, u.user_id)
    if permission not in ps and 'admin.users' not in ps:
        raise HTTPException(403, 'permission denied')
    return u


def _money(v):
    return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def register_v90do_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for p, n in [
            ('labour_productivity.view','View Labour Productivity'),
            ('labour_productivity.manage','Manage Labour Productivity'),
            ('labour_productivity.post','Post Labour Cost Capture'),
            ('labour_productivity.close','Close Labour Productivity MIS')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'), {'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_labour_productivity_target(
            target_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            department_id TEXT, target_name TEXT NOT NULL, target_basis TEXT NOT NULL DEFAULT 'OUTPUT_PER_HOUR',
            target_value NUMERIC NOT NULL, uom TEXT, active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,target_name,department_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_production_labour_capture(
            capture_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            run_id TEXT NOT NULL, production_batch_id TEXT NOT NULL, employee_id TEXT, department_id TEXT,
            work_date DATE NOT NULL, labour_hours NUMERIC NOT NULL, labour_cost NUMERIC NOT NULL,
            output_qty NUMERIC NOT NULL DEFAULT 0, output_uom TEXT, downtime_hours NUMERIC NOT NULL DEFAULT 0,
            overtime_hours NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'POSTED',
            created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_labour_productivity_snapshot(
            snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            period_id TEXT NOT NULL, run_id TEXT NOT NULL, labour_hours NUMERIC NOT NULL,
            labour_cost NUMERIC NOT NULL, output_qty NUMERIC NOT NULL, productive_hours NUMERIC NOT NULL,
            downtime_hours NUMERIC NOT NULL, overtime_hours NUMERIC NOT NULL, cost_per_hour NUMERIC NOT NULL,
            output_per_hour NUMERIC NOT NULL, labour_cost_per_unit NUMERIC NOT NULL,
            productivity_index NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'READY',
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_id,run_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS hr_labour_productivity_close(
            close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            period_id TEXT NOT NULL, run_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'CLOSED',
            closed_by TEXT NOT NULL, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_id))'''))

    def _run(c, run_id):
        r = c.execute(text('SELECT * FROM hr_payroll_run WHERE run_id=:r'), {'r':run_id}).mappings().first()
        if not r:
            raise HTTPException(404, 'payroll run not found')
        return r

    @app.post('/v90do/labour/targets')
    def target(body: dict, request: Request):
        u = _perm(engine, request, 'labour_productivity.manage')
        for k in ('organization_id','entity_id','target_name','target_value'):
            if body.get(k) in (None,''):
                raise HTTPException(400, f'{k} is required')
        value = _money(body['target_value'])
        if value <= 0:
            raise HTTPException(400, 'target_value must be positive')
        i = str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO hr_labour_productivity_target(target_id,organization_id,entity_id,department_id,target_name,target_basis,target_value,uom,active,created_by)
                VALUES(:i,:o,:e,:d,:n,:b,:v,:u,:a,:c)
                ON CONFLICT(organization_id,entity_id,target_name,department_id) DO UPDATE SET target_basis=:b,target_value=:v,uom=:u,active=:a'''),
                {'i':i,'o':body['organization_id'],'e':body['entity_id'],'d':body.get('department_id'),
                 'n':body['target_name'],'b':str(body.get('target_basis') or 'OUTPUT_PER_HOUR').upper(),
                 'v':float(value),'u':body.get('uom'),'a':bool(body.get('active',True)),'c':str(u.user_id)})
        return {'target_id':i,'status':'SAVED','target_value':float(value)}

    @app.post('/v90do/labour/runs/{run_id}/capture')
    def capture(run_id: str, body: dict, request: Request):
        u = _perm(engine, request, 'labour_productivity.post')
        for k in ('production_batch_id','work_date','labour_hours','labour_cost'):
            if body.get(k) in (None,''):
                raise HTTPException(400, f'{k} is required')
        hours = _money(body['labour_hours']); cost = _money(body['labour_cost'])
        if hours <= 0 or cost < 0:
            raise HTTPException(400, 'labour_hours must be positive and labour_cost non-negative')
        with engine.begin() as c:
            run = _run(c, run_id)
            if not run['approved']:
                raise HTTPException(409, 'payroll run must be approved')
            i = str(uuid4())
            c.execute(text('''INSERT INTO hr_production_labour_capture(capture_id,organization_id,entity_id,run_id,production_batch_id,employee_id,department_id,work_date,labour_hours,labour_cost,output_qty,output_uom,downtime_hours,overtime_hours,created_by)
                VALUES(:i,:o,:e,:r,:b,:emp,:d,:wd,:h,:c,:q,:uom,:down,:ot,:by)'''),
                {'i':i,'o':run['organization_id'],'e':run['entity_id'],'r':run_id,'b':body['production_batch_id'],
                 'emp':body.get('employee_id'),'d':body.get('department_id'),'wd':body['work_date'],'h':float(hours),'c':float(cost),
                 'q':float(_money(body.get('output_qty'))),'uom':body.get('output_uom'),'down':float(_money(body.get('downtime_hours'))),
                 'ot':float(_money(body.get('overtime_hours'))),'by':str(u.user_id)})
        return {'capture_id':i,'run_id':run_id,'status':'POSTED'}

    @app.post('/v90do/labour/runs/{run_id}/snapshot')
    def snapshot(run_id: str, request: Request):
        u = _perm(engine, request, 'labour_productivity.view')
        with engine.begin() as c:
            run = _run(c, run_id)
            r = c.execute(text('''SELECT COALESCE(SUM(labour_hours),0) hours, COALESCE(SUM(labour_cost),0) cost,
                COALESCE(SUM(output_qty),0) output, COALESCE(SUM(downtime_hours),0) downtime,
                COALESCE(SUM(overtime_hours),0) overtime
                FROM hr_production_labour_capture WHERE run_id=:r'''), {'r':run_id}).mappings().first()
            hours=_money(r['hours']); cost=_money(r['cost']); output=_money(r['output']); downtime=_money(r['downtime']); overtime=_money(r['overtime'])
            productive=max(hours-downtime, Decimal('0'))
            cph=_money(cost/hours) if hours else Decimal('0')
            oph=_money(output/productive) if productive else Decimal('0')
            cpu=_money(cost/output) if output else Decimal('0')
            target=c.execute(text('''SELECT target_value FROM hr_labour_productivity_target WHERE organization_id=:o AND entity_id=:e AND target_basis='OUTPUT_PER_HOUR' AND active=TRUE ORDER BY created_at DESC LIMIT 1'''), {'o':run['organization_id'],'e':run['entity_id']}).scalar()
            index=_money(oph/_money(target)*100) if target and _money(target)>0 else Decimal('0')
            i=str(uuid4())
            c.execute(text('''INSERT INTO hr_labour_productivity_snapshot(snapshot_id,organization_id,entity_id,period_id,run_id,labour_hours,labour_cost,output_qty,productive_hours,downtime_hours,overtime_hours,cost_per_hour,output_per_hour,labour_cost_per_unit,productivity_index,status)
                VALUES(:i,:o,:e,:p,:r,:h,:c,:q,:ph,:d,:ot,:cph,:oph,:cpu,:idx,'READY')
                ON CONFLICT(organization_id,entity_id,period_id,run_id) DO UPDATE SET labour_hours=:h,labour_cost=:c,output_qty=:q,productive_hours=:ph,downtime_hours=:d,overtime_hours=:ot,cost_per_hour=:cph,output_per_hour=:oph,labour_cost_per_unit=:cpu,productivity_index=:idx,status='READY',generated_at=CURRENT_TIMESTAMP'''),
                {'i':i,'o':run['organization_id'],'e':run['entity_id'],'p':run['period_id'],'r':run_id,'h':float(hours),'c':float(cost),'q':float(output),'ph':float(productive),'d':float(downtime),'ot':float(overtime),'cph':float(cph),'oph':float(oph),'cpu':float(cpu),'idx':float(index)})
        return {'run_id':run_id,'labour_hours':float(hours),'productive_hours':float(productive),'labour_cost':float(cost),'output_qty':float(output),'cost_per_hour':float(cph),'output_per_hour':float(oph),'labour_cost_per_unit':float(cpu),'productivity_index':float(index),'status':'READY'}

    @app.get('/v90do/labour/mis')
    def mis(request: Request, organization_id: str, entity_id: str, period_id: str | None = None):
        _perm(engine, request, 'labour_productivity.view')
        with engine.connect() as c:
            q='''SELECT period_id,run_id,labour_hours,labour_cost,output_qty,productive_hours,downtime_hours,overtime_hours,cost_per_hour,output_per_hour,labour_cost_per_unit,productivity_index,status,generated_at FROM hr_labour_productivity_snapshot WHERE organization_id=:o AND entity_id=:e'''
            params={'o':organization_id,'e':entity_id}
            if period_id: q+=' AND period_id=:p'; params['p']=period_id
            q+=' ORDER BY generated_at DESC'
            rows=c.execute(text(q),params).mappings().all()
        return {'organization_id':organization_id,'entity_id':entity_id,'rows':[dict(x) for x in rows]}

    @app.post('/v90do/labour/runs/{run_id}/close')
    def close(run_id: str, request: Request):
        u=_perm(engine, request, 'labour_productivity.close')
        with engine.begin() as c:
            run=_run(c,run_id)
            snap=c.execute(text("SELECT status FROM hr_labour_productivity_snapshot WHERE run_id=:r"),{'r':run_id}).scalar()
            if snap!='READY': raise HTTPException(409,'labour productivity snapshot must be READY before close')
            i=str(uuid4())
            c.execute(text('''INSERT INTO hr_labour_productivity_close(close_id,organization_id,entity_id,period_id,run_id,status,closed_by)
                VALUES(:i,:o,:e,:p,:r,'CLOSED',:u)
                ON CONFLICT(organization_id,entity_id,period_id) DO UPDATE SET run_id=:r,status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),
                {'i':i,'o':run['organization_id'],'e':run['entity_id'],'p':run['period_id'],'r':run_id,'u':str(u.user_id)})
        return {'run_id':run_id,'period_id':run['period_id'],'status':'CLOSED'}

    @app.get('/v90do/labour/dashboard')
    def dashboard(request: Request, organization_id: str, entity_id: str):
        _perm(engine, request, 'labour_productivity.view')
        with engine.connect() as c:
            r=c.execute(text('''SELECT COUNT(*) runs,COALESCE(SUM(labour_hours),0) hours,COALESCE(SUM(labour_cost),0) cost,
                COALESCE(SUM(output_qty),0) output,COALESCE(SUM(downtime_hours),0) downtime,COALESCE(AVG(productivity_index),0) idx
                FROM hr_labour_productivity_snapshot WHERE organization_id=:o AND entity_id=:e'''),{'o':organization_id,'e':entity_id}).mappings().first()
            closed=c.execute(text("SELECT COUNT(*) FROM hr_labour_productivity_close WHERE organization_id=:o AND entity_id=:e AND status='CLOSED'"),{'o':organization_id,'e':entity_id}).scalar()
        hours=_money(r['hours']); cost=_money(r['cost']); output=_money(r['output'])
        return {'runs':int(r['runs'] or 0),'labour_hours':float(hours),'labour_cost':float(cost),'output_qty':float(output),
                'cost_per_hour':float(_money(cost/hours) if hours else 0),'output_per_hour':float(_money(output/hours) if hours else 0),
                'downtime_hours':float(_money(r['downtime'])),'avg_productivity_index':float(_money(r['idx'])),'closed_periods':int(closed or 0)}

    @app.get('/ui/labour-productivity')
    def page():
        return FileResponse(Path(__file__).resolve().parents[1]/'web'/'labour-productivity.html')

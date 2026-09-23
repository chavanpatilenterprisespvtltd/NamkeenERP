from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed

MONEY=Decimal('0.01')
def money(v): return float(Decimal(str(v or 0)).quantize(MONEY, rounding=ROUND_HALF_UP))
def parse_date(v):
    if not v: return date.today()
    try: return datetime.fromisoformat(str(v).replace('Z','+00:00')).date()
    except ValueError as exc: raise HTTPException(422,'invalid date; use ISO-8601') from exc

def require(engine, request, entity_id, location_id=None, write=False):
    u=authenticate(request); p='mfg_workforce.edit' if write else 'mfg_workforce.view'
    if p not in permissions_for_user(engine,u.user_id) and 'admin.users' not in permissions_for_user(engine,u.user_id): raise HTTPException(403,'permission denied')
    try: assert_entity_location_allowed(engine,u.user_id,str(entity_id),str(location_id) if location_id else None)
    except PermissionError as exc: raise HTTPException(403,str(exc)) from exc
    return u

def register_v90gp_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for p,n in [('mfg_workforce.view','View manufacturing and workforce integration'),('mfg_workforce.edit','Manage manufacturing and workforce integration actions and snapshots')]:
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"),{'p':p,'n':n})
        for role in ('manager','super_admin','mis','production_manager','hr_manager'):
            for p in ('mfg_workforce.view','mfg_workforce.edit'):
                c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,:p) ON CONFLICT(role_id,permission_id) DO NOTHING"),{'r':role,'p':p})
        c.execute(text('''CREATE TABLE IF NOT EXISTS erp_manufacturing_workforce_snapshot(
            snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
            from_date TEXT NOT NULL, to_date TEXT NOT NULL, batch_count INTEGER NOT NULL DEFAULT 0, completed_batch_count INTEGER NOT NULL DEFAULT 0,
            planned_qty NUMERIC NOT NULL DEFAULT 0, captured_output_qty NUMERIC NOT NULL DEFAULT 0, labour_hours NUMERIC NOT NULL DEFAULT 0,
            productive_hours NUMERIC NOT NULL DEFAULT 0, downtime_hours NUMERIC NOT NULL DEFAULT 0, overtime_hours NUMERIC NOT NULL DEFAULT 0,
            labour_cost NUMERIC NOT NULL DEFAULT 0, output_per_hour NUMERIC NOT NULL DEFAULT 0, labour_cost_per_unit NUMERIC NOT NULL DEFAULT 0,
            workforce_coverage_pct NUMERIC NOT NULL DEFAULT 0, productivity_index NUMERIC NOT NULL DEFAULT 0,
            created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,location_id,from_date,to_date))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS erp_manufacturing_workforce_actions(
            action_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, location_id TEXT NULL,
            batch_id TEXT NULL, action_type TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'MEDIUM', reason TEXT NOT NULL,
            owner_user_id TEXT NULL, due_date TEXT NULL, status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, closed_at TIMESTAMP NULL)'''))

    def calc(o,e,l,fd,td):
        with engine.connect() as c:
            params={'o':o,'e':e,'fd':fd.isoformat(),'td':td.isoformat()}
            loc=' AND location_id=:l' if l else ''
            if l: params['l']=l
            b=c.execute(text(f'''SELECT COUNT(*) batch_count, SUM(CASE WHEN status='COMPLETED' THEN 1 ELSE 0 END) completed,
                COALESCE(SUM(planned_qty),0) planned FROM production_batch WHERE organization_id=:o AND entity_id=:e
                AND date(created_at) BETWEEN :fd AND :td{loc}'''),params).mappings().one()
            q=c.execute(text(f'''SELECT COALESCE(SUM(labour_hours),0) hours,COALESCE(SUM(labour_cost),0) cost,
                COALESCE(SUM(output_qty),0) output,COALESCE(SUM(downtime_hours),0) downtime,COALESCE(SUM(overtime_hours),0) overtime
                FROM hr_production_labour_capture WHERE organization_id=:o AND entity_id=:e AND work_date BETWEEN :fd AND :td'''),params).mappings().one()
            linked=c.execute(text(f'''SELECT COUNT(DISTINCT production_batch_id) FROM hr_production_labour_capture
                WHERE organization_id=:o AND entity_id=:e AND work_date BETWEEN :fd AND :td'''),params).scalar() or 0
        hours=Decimal(str(q['hours'] or 0)); cost=Decimal(str(q['cost'] or 0)); output=Decimal(str(q['output'] or 0)); downtime=Decimal(str(q['downtime'] or 0)); planned=Decimal(str(b['planned'] or 0)); productive=max(hours-downtime,Decimal(0))
        oph=(output/productive) if productive else Decimal(0); cpu=(cost/output) if output else Decimal(0)
        coverage=(Decimal(linked)/Decimal(b['batch_count'] or 1)*100) if b['batch_count'] else Decimal(0)
        index=min(Decimal(100),coverage) * (Decimal(1) if productive else Decimal(0))
        return {'batch_count':int(b['batch_count'] or 0),'completed_batch_count':int(b['completed'] or 0),'planned_qty':money(planned),'captured_output_qty':money(output),'labour_hours':money(hours),'productive_hours':money(productive),'downtime_hours':money(downtime),'overtime_hours':money(q['overtime']),'labour_cost':money(cost),'output_per_hour':money(oph),'labour_cost_per_unit':money(cpu),'workforce_coverage_pct':money(coverage),'productivity_index':money(index)}

    @app.get('/v90gp/manufacturing-workforce')
    def dashboard(request:Request,organization_id:UUID,entity_id:UUID,location_id:UUID|None=None,from_date:str|None=None,to_date:str|None=None):
        fd=parse_date(from_date); td=parse_date(to_date)
        if td<fd: raise HTTPException(422,'to_date must be on or after from_date')
        require(engine,request,entity_id,location_id)
        return {'from_date':fd.isoformat(),'to_date':td.isoformat(),**calc(str(organization_id),str(entity_id),str(location_id) if location_id else None,fd,td)}

    @app.post('/v90gp/manufacturing-workforce/snapshots')
    def snapshot(body:dict,request:Request):
        u=require(engine,request,body['entity_id'],body.get('location_id'),True); fd=parse_date(body.get('from_date')); td=parse_date(body.get('to_date'))
        if td<fd: raise HTTPException(422,'to_date must be on or after from_date')
        o,e,l=str(body['organization_id']),str(body['entity_id']),str(body['location_id']) if body.get('location_id') else None; d=calc(o,e,l,fd,td); sid=str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO erp_manufacturing_workforce_snapshot(snapshot_id,organization_id,entity_id,location_id,from_date,to_date,batch_count,completed_batch_count,planned_qty,captured_output_qty,labour_hours,productive_hours,downtime_hours,overtime_hours,labour_cost,output_per_hour,labour_cost_per_unit,workforce_coverage_pct,productivity_index,created_by)
                VALUES(:i,:o,:e,:l,:fd,:td,:batch_count,:completed_batch_count,:planned_qty,:captured_output_qty,:labour_hours,:productive_hours,:downtime_hours,:overtime_hours,:labour_cost,:output_per_hour,:labour_cost_per_unit,:workforce_coverage_pct,:productivity_index,:u)
                ON CONFLICT(organization_id,entity_id,location_id,from_date,to_date) DO UPDATE SET batch_count=:batch_count,completed_batch_count=:completed_batch_count,planned_qty=:planned_qty,captured_output_qty=:captured_output_qty,labour_hours=:labour_hours,productive_hours=:productive_hours,downtime_hours=:downtime_hours,overtime_hours=:overtime_hours,labour_cost=:labour_cost,output_per_hour=:output_per_hour,labour_cost_per_unit=:labour_cost_per_unit,workforce_coverage_pct=:workforce_coverage_pct,productivity_index=:productivity_index,created_by=:u,created_at=CURRENT_TIMESTAMP'''),{'i':sid,'o':o,'e':e,'l':l,'fd':fd.isoformat(),'td':td.isoformat(),'u':str(u.user_id),**{k:v for k,v in d.items()}})
        return {'snapshot_id':sid,**d}

    @app.get('/v90gp/manufacturing-workforce/actions')
    def actions(request:Request,organization_id:UUID,entity_id:UUID,location_id:UUID|None=None,status:str='OPEN'):
        require(engine,request,entity_id,location_id)
        with engine.connect() as c:
            q='SELECT * FROM erp_manufacturing_workforce_actions WHERE organization_id=:o AND entity_id=:e AND status=:s'; p={'o':str(organization_id),'e':str(entity_id),'s':status}
            if location_id: q+=' AND location_id=:l'; p['l']=str(location_id)
            q+=' ORDER BY priority,created_at DESC'; rows=c.execute(text(q),p).mappings().all()
        return {'actions':[dict(x) for x in rows]}

    @app.post('/v90gp/manufacturing-workforce/actions')
    def action(body:dict,request:Request):
        u=require(engine,request,body['entity_id'],body.get('location_id'),True)
        if not body.get('action_type') or not body.get('reason'): raise HTTPException(400,'action_type and reason are required')
        aid=str(uuid4())
        with engine.begin() as c: c.execute(text('''INSERT INTO erp_manufacturing_workforce_actions(action_id,organization_id,entity_id,location_id,batch_id,action_type,priority,reason,owner_user_id,due_date,created_by) VALUES(:i,:o,:e,:l,:b,:t,:p,:r,:ow,:d,:u)'''),{'i':aid,'o':str(body['organization_id']),'e':str(body['entity_id']),'l':str(body['location_id']) if body.get('location_id') else None,'b':body.get('batch_id'),'t':str(body['action_type']).upper(),'p':str(body.get('priority') or 'MEDIUM').upper(),'r':str(body['reason']),'ow':body.get('owner_user_id'),'d':body.get('due_date'),'u':str(u.user_id)})
        return {'action_id':aid,'status':'OPEN'}

    @app.get('/ui/manufacturing-workforce')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'manufacturing-workforce.html')

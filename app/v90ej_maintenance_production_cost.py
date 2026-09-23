from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def _d(v):
    return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def _perm(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def register_v90ej_routes(app:FastAPI,e):
    with e.begin() as c:
        for p,n in [
            ('maintenance_production_cost.view','View Maintenance Production Cost Integration'),
            ('maintenance_production_cost.manage','Manage Maintenance Production Cost Integration'),
            ('maintenance_production_cost.close','Close Maintenance Production Cost Integration'),
        ]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_production_cost_allocation(
            allocation_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            period_key TEXT NOT NULL,
            work_center_id TEXT NOT NULL,
            maintenance_labour_cost NUMERIC NOT NULL DEFAULT 0,
            maintenance_breakdown_hours NUMERIC NOT NULL DEFAULT 0,
            production_qty NUMERIC NOT NULL DEFAULT 0,
            allocation_basis TEXT NOT NULL,
            allocated_cost NUMERIC NOT NULL DEFAULT 0,
            cost_per_unit NUMERIC NOT NULL DEFAULT 0,
            source_charge_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'OPEN',
            created_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key,work_center_id)
        )'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_production_cost_line(
            line_id TEXT PRIMARY KEY,
            allocation_id TEXT NOT NULL,
            batch_id TEXT,
            product_id TEXT,
            work_center_id TEXT NOT NULL,
            period_key TEXT NOT NULL,
            base_cost NUMERIC NOT NULL DEFAULT 0,
            allocated_maintenance_cost NUMERIC NOT NULL DEFAULT 0,
            revised_overhead_cost NUMERIC NOT NULL DEFAULT 0,
            revised_total_cost NUMERIC NOT NULL DEFAULT 0,
            production_qty NUMERIC NOT NULL DEFAULT 0,
            cost_per_unit NUMERIC NOT NULL DEFAULT 0,
            created_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(allocation_id,batch_id)
        )'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_production_cost_close(
            close_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            period_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'CLOSED',
            closed_by TEXT NOT NULL,
            closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key)
        )'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_mpc_alloc_scope ON maintenance_production_cost_allocation(organization_id,entity_id,period_key,work_center_id,status)'))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_mpc_line_scope ON maintenance_production_cost_line(allocation_id,work_center_id,period_key)'))

    @app.post('/v90ej/maintenance/production-cost/allocate')
    def allocate(body:dict,request:Request):
        u=_perm(e,request,'maintenance_production_cost.manage')
        for k in ('organization_id','entity_id','period_key','work_center_id'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        basis=str(body.get('allocation_basis') or 'PRODUCTION_QTY').upper()
        if basis not in {'PRODUCTION_QTY','SCHEDULED_HOURS','EQUAL'}: raise HTTPException(400,'allocation_basis must be PRODUCTION_QTY, SCHEDULED_HOURS or EQUAL')
        o,eid,w,pk=body['organization_id'],body['entity_id'],body['work_center_id'],body['period_key']
        with e.connect() as c:
            closed=c.execute(text('SELECT 1 FROM maintenance_production_cost_close WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':eid,'p':pk}).first()
            if closed: raise HTTPException(409,'period is closed')
            q=c.execute(text('''SELECT COALESCE(SUM(total_cost),0) maintenance_cost,COALESCE(SUM(regular_hours+overtime_hours),0) labour_hours,COUNT(*) n
                FROM maintenance_labour_charge WHERE organization_id=:o AND entity_id=:e AND work_center_id=:w AND substr(charge_date,1,7)=substr(:p,1,7)'''),{'o':o,'e':eid,'w':w,'p':pk}).mappings().first()
            down=c.execute(text('''SELECT COALESCE(SUM(duration_minutes),0) mins FROM maintenance_event
                WHERE organization_id=:o AND entity_id=:e AND work_center_id=:w AND event_type='BREAKDOWN' AND substr(event_at,1,7)=substr(:p,1,7)'''),{'o':o,'e':eid,'w':w,'p':pk}).scalar_one()
            prod=c.execute(text('''SELECT COALESCE(SUM(planned_qty),0) qty,COALESCE(SUM(required_hours),0) hrs,COUNT(*) n
                FROM manufacturing_schedule WHERE organization_id=:o AND entity_id=:e AND work_center_id=:w AND substr(schedule_date,1,7)=substr(:p,1,7) AND status IN ('PLANNED','APPROVED')'''),{'o':o,'e':eid,'w':w,'p':pk}).mappings().first()
            batches=c.execute(text('''SELECT DISTINCT bc.batch_id,bc.product_id,bc.good_qty qty,bc.total_cost base_cost,bc.overhead_cost
                FROM manufacturing_batch_cost bc
                JOIN manufacturing_schedule ms ON ms.organization_id=bc.organization_id AND ms.entity_id=bc.entity_id AND ms.product_id=bc.product_id
                WHERE bc.organization_id=:o AND bc.entity_id=:e AND bc.period_key=:p AND ms.work_center_id=:w
                  AND substr(ms.schedule_date,1,7)=substr(:p,1,7) AND ms.status IN ('PLANNED','APPROVED')'''),{'o':o,'e':eid,'p':pk,'w':w}).mappings().all()
        maint=_d(q['maintenance_cost']); qty=_d(prod['qty']); hrs=_d(prod['hrs'])
        if maint <= 0: raise HTTPException(400,'no maintenance labour cost found for work center and period')
        if basis=='PRODUCTION_QTY' and qty<=0: raise HTTPException(400,'production quantity required for PRODUCTION_QTY allocation')
        if basis=='SCHEDULED_HOURS' and hrs<=0: raise HTTPException(400,'scheduled hours required for SCHEDULED_HOURS allocation')
        alloc_id=str(uuid4())
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_production_cost_allocation(
                allocation_id,organization_id,entity_id,period_key,work_center_id,maintenance_labour_cost,
                maintenance_breakdown_hours,production_qty,allocation_basis,allocated_cost,cost_per_unit,source_charge_count,created_by)
                VALUES(:i,:o,:e,:p,:w,:mc,:bh,:q,:b,:ac,:cpu,:n,:u)
                ON CONFLICT(organization_id,entity_id,period_key,work_center_id) DO UPDATE SET
                maintenance_labour_cost=:mc,maintenance_breakdown_hours=:bh,production_qty=:q,allocation_basis=:b,allocated_cost=:ac,cost_per_unit=:cpu,source_charge_count=:n,status='OPEN',created_by=:u,created_at=CURRENT_TIMESTAMP'''),
                {'i':alloc_id,'o':o,'e':eid,'p':pk,'w':w,'mc':float(maint),'bh':float(Decimal(str(down or 0))/Decimal('60')),'q':float(qty),'b':basis,'ac':float(maint),'cpu':float(_d(maint/qty if qty else 0)),'n':int(q['n'] or 0),'u':str(u.user_id)})
            current=c.execute(text('SELECT allocation_id FROM maintenance_production_cost_allocation WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND work_center_id=:w'),{'o':o,'e':eid,'p':pk,'w':w}).scalar_one()
            # Rebuild lines for deterministic/idempotent allocation against batches present in period.
            c.execute(text('DELETE FROM maintenance_production_cost_line WHERE allocation_id=:a'),{'a':current})
            if batches:
                total_basis=Decimal('0')
                rows=[]
                for b in batches:
                    if basis=='PRODUCTION_QTY': basis_value=_d(b['qty'])
                    elif basis=='SCHEDULED_HOURS': basis_value=hrs/Decimal(str(len(batches))) if batches else Decimal('0')
                    else: basis_value=Decimal('1')
                    rows.append((b,basis_value)); total_basis += basis_value
                for b,bv in rows:
                    share=(bv/total_basis) if total_basis else Decimal('0')
                    alloc_cost=_d(maint*share)
                    base=_d(b['base_cost'])
                    revised_overhead=_d(_d(b['overhead_cost'])+alloc_cost)
                    revised_total=_d(base+alloc_cost)
                    unit=_d(revised_total/_d(b['qty'])) if _d(b['qty']) else Decimal('0')
                    c.execute(text('''INSERT INTO maintenance_production_cost_line(line_id,allocation_id,batch_id,product_id,work_center_id,period_key,base_cost,allocated_maintenance_cost,revised_overhead_cost,revised_total_cost,production_qty,cost_per_unit,created_by)
                        VALUES(:i,:a,:b,:pr,:w,:p,:bc,:ac,:ro,:rt,:q,:cpu,:u)'''),{'i':str(uuid4()),'a':current,'b':b['batch_id'],'pr':b['product_id'],'w':w,'p':pk,'bc':float(base),'ac':float(alloc_cost),'ro':float(revised_overhead),'rt':float(revised_total),'q':float(_d(b['qty'])),'cpu':float(unit),'u':str(u.user_id)})
            c.execute(text('''UPDATE maintenance_production_cost_allocation SET allocated_cost=:ac,cost_per_unit=:cpu WHERE allocation_id=:i'''),{'ac':float(maint),'cpu':float(_d(maint/qty if qty else 0)),'i':current})
        return {'allocation_id':str(current),'maintenance_labour_cost':float(maint),'breakdown_hours':float(Decimal(str(down or 0))/Decimal('60')),'production_qty':float(qty),'allocated_cost':float(maint),'cost_per_unit':float(_d(maint/qty if qty else 0)),'status':'OPEN'}

    @app.get('/v90ej/maintenance/production-cost/dashboard')
    def dashboard(request:Request,organization_id:str,entity_id:str,period_key:str):
        _perm(e,request,'maintenance_production_cost.view')
        with e.connect() as c:
            a=c.execute(text('''SELECT COALESCE(SUM(maintenance_labour_cost),0) maintenance_labour_cost,
                COALESCE(SUM(maintenance_breakdown_hours),0) breakdown_hours,
                COALESCE(SUM(production_qty),0) production_qty,
                COALESCE(SUM(allocated_cost),0) allocated_cost,
                COALESCE(SUM(cost_per_unit),0) work_center_cpu,
                COUNT(*) work_centers
                FROM maintenance_production_cost_allocation WHERE organization_id=:o AND entity_id=:e AND period_key=:p'''),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().first()
            lines=c.execute(text('''SELECT l.work_center_id,COUNT(*) batch_lines,COALESCE(SUM(allocated_maintenance_cost),0) maintenance_cost,COALESCE(SUM(revised_total_cost),0) revised_total_cost
                FROM maintenance_production_cost_line l JOIN maintenance_production_cost_allocation a ON a.allocation_id=l.allocation_id
                WHERE a.organization_id=:o AND a.entity_id=:e AND a.period_key=:p GROUP BY l.work_center_id ORDER BY maintenance_cost DESC'''),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        r=dict(a)
        r['maintenance_cost_pct_of_allocated']=float(_d((Decimal(str(a['maintenance_labour_cost'] or 0))/Decimal(str(a['allocated_cost'] or 0))*100) if a['allocated_cost'] else 0))
        r['lines']=[dict(x) for x in lines]
        return r

    @app.get('/v90ej/maintenance/production-cost/lines')
    def lines(request:Request,organization_id:str,entity_id:str,period_key:str):
        _perm(e,request,'maintenance_production_cost.view')
        with e.connect() as c:
            rows=c.execute(text('''SELECT l.*,a.allocation_basis,a.maintenance_labour_cost FROM maintenance_production_cost_line l
                JOIN maintenance_production_cost_allocation a ON a.allocation_id=l.allocation_id
                WHERE a.organization_id=:o AND a.entity_id=:e AND a.period_key=:p ORDER BY l.work_center_id,l.product_id,l.batch_id'''),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        return {'lines':[dict(x) for x in rows]}

    @app.post('/v90ej/maintenance/production-cost/{period_key}/close')
    def close(period_key:str,body:dict,request:Request):
        u=_perm(e,request,'maintenance_production_cost.close')
        for k in ('organization_id','entity_id'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_production_cost_close(close_id,organization_id,entity_id,period_key,closed_by)
                VALUES(:i,:o,:e,:p,:u)
                ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),{'i':str(uuid4()),'o':body['organization_id'],'e':body['entity_id'],'p':period_key,'u':str(u.user_id)})
            c.execute(text('''UPDATE maintenance_production_cost_allocation SET status='CLOSED' WHERE organization_id=:o AND entity_id=:e AND period_key=:p'''),{'o':body['organization_id'],'e':body['entity_id'],'p':period_key})
        return {'period_key':period_key,'status':'CLOSED'}

    @app.get('/ui/maintenance-production-cost')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-production-cost.html')

from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def _d(v): return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
def _perm(e,r,p):
    u=authenticate(r); ps=permissions_for_user(e,u.user_id)
    if p not in ps and 'admin.users' not in ps: raise HTTPException(403,'permission denied')
    return u

def _month_start(pk):
    try:
        y,m=map(int,pk.split('-')); return f'{y:04d}-{m:02d}-01'
    except Exception: raise HTTPException(400,'period_key must be YYYY-MM')
def _prev(pk):
    y,m=map(int,pk.split('-')); m-=1
    if m==0: y-=1; m=12
    return f'{y:04d}-{m:02d}'

def register_v90el_routes(app: FastAPI, e):
    with e.begin() as c:
        for p,n in [('maintenance_effectiveness.view','View Maintenance Effectiveness'),('maintenance_effectiveness.manage','Calculate Maintenance Effectiveness'),('maintenance_effectiveness.close','Close Maintenance Effectiveness')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_effectiveness_snapshot(
            snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL, baseline_period_key TEXT NOT NULL, work_center_id TEXT,
            current_maintenance_cost NUMERIC NOT NULL DEFAULT 0, baseline_maintenance_cost NUMERIC NOT NULL DEFAULT 0, current_breakdown_hours NUMERIC NOT NULL DEFAULT 0, baseline_breakdown_hours NUMERIC NOT NULL DEFAULT 0,
            breakdown_hours_reduction NUMERIC NOT NULL DEFAULT 0, breakdown_hours_reduction_pct NUMERIC NOT NULL DEFAULT 0, maintenance_cost_reduction NUMERIC NOT NULL DEFAULT 0, maintenance_cost_reduction_pct NUMERIC NOT NULL DEFAULT 0,
            preventive_orders INTEGER NOT NULL DEFAULT 0, breakdown_orders INTEGER NOT NULL DEFAULT 0, preventive_mix_pct NUMERIC NOT NULL DEFAULT 0, effectiveness_score NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key,work_center_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_effectiveness_close(
            close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'CLOSED', closed_by TEXT NOT NULL, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key))'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_maintenance_effectiveness_scope ON maintenance_effectiveness_snapshot(organization_id,entity_id,period_key,work_center_id,status)'))
    @app.post('/v90el/maintenance/effectiveness/snapshot')
    def snapshot(body:dict,request:Request):
        u=_perm(e,request,'maintenance_effectiveness.manage')
        for k in ('organization_id','entity_id','period_key'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        o,eid,pk=body['organization_id'],body['entity_id'],body['period_key']; base=body.get('baseline_period_key') or _prev(pk); w=body.get('work_center_id')
        _month_start(pk); _month_start(base)
        with e.connect() as c:
            if c.execute(text('SELECT 1 FROM maintenance_effectiveness_close WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':eid,'p':pk}).first(): raise HTTPException(409,'period is closed')
            def metrics(period):
                q={'o':o,'e':eid,'p':period,'w':w}
                wc=' AND work_center_id=:w' if w else ''
                lab=c.execute(text(f'''SELECT COALESCE(SUM(total_cost),0) cost FROM maintenance_labour_charge WHERE organization_id=:o AND entity_id=:e AND substr(charge_date,1,7)=:p{wc}'''),q).scalar_one()
                sp=c.execute(text(f'''SELECT COALESCE(SUM(total_cost),0) cost FROM maintenance_spare_usage WHERE organization_id=:o AND entity_id=:e{wc} AND maintenance_order_id IN (SELECT order_id FROM maintenance_order WHERE organization_id=:o AND entity_id=:e AND substr(scheduled_date,1,7)=:p)'''),q).scalar_one()
                br=c.execute(text(f'''SELECT COALESCE(SUM(duration_minutes),0) mins FROM maintenance_event WHERE organization_id=:o AND entity_id=:e AND event_type='BREAKDOWN' AND substr(event_at,1,7)=:p{wc}'''),q).scalar_one()
                orders=c.execute(text(f'''SELECT COALESCE(SUM(CASE WHEN order_type='PREVENTIVE' THEN 1 ELSE 0 END),0) pm,
                    COALESCE(SUM(CASE WHEN order_type='BREAKDOWN' THEN 1 ELSE 0 END),0) bd FROM maintenance_order WHERE organization_id=:o AND entity_id=:e AND substr(scheduled_date,1,7)=:p{wc}'''),q).mappings().one()
                return _d(lab),_d(sp),_d(Decimal(str(br or 0))/60),int(orders['pm'] or 0),int(orders['bd'] or 0)
            cl,cs,ch,cp,cb=metrics(pk); bl,bs,bh,bp,bb=metrics(base)
        cc=_d(cl+cs); bc=_d(bl+bs)
        hours_reduction=_d(bh-ch); cost_reduction=_d(bc-cc)
        hours_pct=_d(hours_reduction/bh*100) if bh else Decimal('0')
        cost_pct=_d(cost_reduction/bc*100) if bc else Decimal('0')
        pm_mix=_d(Decimal(cp)/(Decimal(cp+cb))*100) if cp+cb else Decimal('0')
        effectiveness=_d(max(Decimal('0'),min(Decimal('100'),(max(Decimal('0'),hours_pct)+max(Decimal('0'),cost_pct))/2)))
        status='IMPROVING' if effectiveness>=60 else ('STABLE' if effectiveness>=0 else 'DETERIORATING')
        sid=str(uuid4())
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_effectiveness_snapshot(snapshot_id,organization_id,entity_id,period_key,baseline_period_key,work_center_id,
                current_maintenance_cost,baseline_maintenance_cost,current_breakdown_hours,baseline_breakdown_hours,breakdown_hours_reduction,breakdown_hours_reduction_pct,
                maintenance_cost_reduction,maintenance_cost_reduction_pct,preventive_orders,breakdown_orders,preventive_mix_pct,effectiveness_score,status,created_by)
                VALUES(:i,:o,:e,:p,:b,:w,:cc,:bc,:ch,:bh,:hr,:hp,:cr,:cp,:po,:bo,:pm,:sc,:st,:u)
                ON CONFLICT(organization_id,entity_id,period_key,work_center_id) DO UPDATE SET baseline_period_key=:b,current_maintenance_cost=:cc,baseline_maintenance_cost=:bc,current_breakdown_hours=:ch,baseline_breakdown_hours=:bh,breakdown_hours_reduction=:hr,breakdown_hours_reduction_pct=:hp,maintenance_cost_reduction=:cr,maintenance_cost_reduction_pct=:cp,preventive_orders=:po,breakdown_orders=:bo,preventive_mix_pct=:pm,effectiveness_score=:sc,status=:st,created_by=:u,created_at=CURRENT_TIMESTAMP'''),{'i':sid,'o':o,'e':eid,'p':pk,'b':base,'w':w,'cc':float(cc),'bc':float(bc),'ch':float(ch),'bh':float(bh),'hr':float(hours_reduction),'hp':float(hours_pct),'cr':float(cost_reduction),'cp':float(cost_pct),'po':cp,'bo':cb,'pm':float(pm_mix),'sc':float(effectiveness),'st':status,'u':str(u.user_id)})
            row=c.execute(text('SELECT snapshot_id FROM maintenance_effectiveness_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND ((work_center_id=:w) OR (work_center_id IS NULL AND :w IS NULL))'),{'o':o,'e':eid,'p':pk,'w':w}).scalar_one()
        return {'snapshot_id':row,'period_key':pk,'baseline_period_key':base,'effectiveness_score':float(effectiveness),'status':status,'breakdown_hours_reduction_pct':float(hours_pct),'maintenance_cost_reduction_pct':float(cost_pct),'preventive_mix_pct':float(pm_mix)}

    @app.get('/v90el/maintenance/effectiveness/dashboard')
    def dashboard(request:Request,organization_id:str,entity_id:str,period_key:str):
        _perm(e,request,'maintenance_effectiveness.view')
        with e.connect() as c:
            rows=c.execute(text('''SELECT * FROM maintenance_effectiveness_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY effectiveness_score DESC,work_center_id'''),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        return {'count':len(rows),'rows':[dict(x) for x in rows],'average_effectiveness_score':float(_d(sum((_d(x['effectiveness_score']) for x in rows),Decimal('0'))/len(rows))) if rows else 0.0}

    @app.get('/v90el/maintenance/effectiveness/trend')
    def trend(request:Request,organization_id:str,entity_id:str,period_key:str,months:int=6):
        _perm(e,request,'maintenance_effectiveness.view'); months=max(1,min(24,months))
        y,m=map(int,period_key.split('-')); keys=[]
        for _ in range(months):
            keys.append(f'{y:04d}-{m:02d}'); m-=1
            if m==0:y-=1;m=12
        with e.connect() as c:
            rows=c.execute(text('''SELECT period_key,COUNT(*) snapshot_count,COALESCE(AVG(effectiveness_score),0) effectiveness_score,COALESCE(SUM(breakdown_hours_reduction),0) breakdown_hours_reduction,COALESCE(SUM(maintenance_cost_reduction),0) maintenance_cost_reduction FROM maintenance_effectiveness_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key IN (SELECT value FROM json_each(:ks)) GROUP BY period_key ORDER BY period_key'''),{'o':organization_id,'e':entity_id,'ks':'["'+'","'.join(keys)+'"]'}).mappings().all()
        return {'periods':[dict(x) for x in rows]}

    @app.post('/v90el/maintenance/effectiveness/{period_key}/close')
    def close(period_key:str,body:dict,request:Request):
        u=_perm(e,request,'maintenance_effectiveness.close')
        for k in ('organization_id','entity_id'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_effectiveness_close(close_id,organization_id,entity_id,period_key,closed_by) VALUES(:i,:o,:e,:p,:u) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),{'i':str(uuid4()),'o':body['organization_id'],'e':body['entity_id'],'p':period_key,'u':str(u.user_id)})
            c.execute(text("UPDATE maintenance_effectiveness_snapshot SET status='CLOSED' WHERE organization_id=:o AND entity_id=:e AND period_key=:p"),{'o':body['organization_id'],'e':body['entity_id'],'p':period_key})
        return {'period_key':period_key,'status':'CLOSED'}
    @app.get('/ui/maintenance-effectiveness')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-effectiveness.html')

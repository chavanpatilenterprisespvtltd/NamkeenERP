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

def _prev(pk):
    y,m=map(int,pk.split('-')); m-=1
    if m==0:y-=1;m=12
    return f'{y:04d}-{m:02d}'

def _validate_period(pk):
    try:
        y,m=map(int,pk.split('-'))
        if not (1<=m<=12): raise ValueError
    except Exception: raise HTTPException(400,'period_key must be YYYY-MM')

def register_v90em_routes(app: FastAPI, e):
    with e.begin() as c:
        for p,n in [('maintenance_roi.view','View Maintenance ROI'),('maintenance_roi.manage','Calculate Maintenance ROI'),('maintenance_roi.close','Close Maintenance ROI')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'),{'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_roi_snapshot(
            snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL, baseline_period_key TEXT NOT NULL, work_center_id TEXT,
            current_preventive_cost NUMERIC NOT NULL DEFAULT 0, current_breakdown_cost NUMERIC NOT NULL DEFAULT 0, baseline_preventive_cost NUMERIC NOT NULL DEFAULT 0, baseline_breakdown_cost NUMERIC NOT NULL DEFAULT 0,
            current_maintenance_cost NUMERIC NOT NULL DEFAULT 0, baseline_maintenance_cost NUMERIC NOT NULL DEFAULT 0, avoided_breakdown_cost NUMERIC NOT NULL DEFAULT 0, preventive_cost_change NUMERIC NOT NULL DEFAULT 0,
            net_reliability_benefit NUMERIC NOT NULL DEFAULT 0, preventive_roi_pct NUMERIC NOT NULL DEFAULT 0, breakdown_hours_avoided NUMERIC NOT NULL DEFAULT 0, breakdown_hours_reduction_pct NUMERIC NOT NULL DEFAULT 0,
            oee_improvement_pct NUMERIC NOT NULL DEFAULT 0, optimization_score NUMERIC NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key,work_center_id))'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_roi_close(
            close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'CLOSED', closed_by TEXT NOT NULL, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key))'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_maintenance_roi_scope ON maintenance_roi_snapshot(organization_id,entity_id,period_key,work_center_id,status)'))

    @app.post('/v90em/maintenance/roi/snapshot')
    def snapshot(body:dict,request:Request):
        u=_perm(e,request,'maintenance_roi.manage')
        for k in ('organization_id','entity_id','period_key'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        o,eid,pk=body['organization_id'],body['entity_id'],body['period_key']; base=body.get('baseline_period_key') or _prev(pk); w=body.get('work_center_id')
        _validate_period(pk); _validate_period(base)
        with e.connect() as c:
            if c.execute(text('SELECT 1 FROM maintenance_roi_close WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':o,'e':eid,'p':pk}).first(): raise HTTPException(409,'period is closed')
            def metrics(period):
                q={'o':o,'e':eid,'p':period,'w':w}
                wc_lab=' AND ml.work_center_id=:w' if w else ''
                wc_sp=' AND su.work_center_id=:w' if w else ''
                wc_ev=' AND maintenance_event.work_center_id=:w' if w else ''
                r=c.execute(text(f'''SELECT
                    COALESCE(SUM(CASE WHEN mo.order_type='PREVENTIVE' THEN ml.total_cost ELSE 0 END),0) pm_labour,
                    COALESCE(SUM(CASE WHEN mo.order_type='BREAKDOWN' THEN ml.total_cost ELSE 0 END),0) bd_labour
                    FROM maintenance_labour_charge ml JOIN maintenance_order mo ON mo.order_id=ml.maintenance_order_id
                    WHERE ml.organization_id=:o AND ml.entity_id=:e AND substr(ml.charge_date,1,7)=:p{wc_lab}'''),q).mappings().one()
                sp=c.execute(text(f'''SELECT
                    COALESCE(SUM(CASE WHEN mo.order_type='PREVENTIVE' THEN su.total_cost ELSE 0 END),0) pm_spare,
                    COALESCE(SUM(CASE WHEN mo.order_type='BREAKDOWN' THEN su.total_cost ELSE 0 END),0) bd_spare
                    FROM maintenance_spare_usage su JOIN maintenance_order mo ON mo.order_id=su.maintenance_order_id
                    WHERE su.organization_id=:o AND su.entity_id=:e AND substr(mo.scheduled_date,1,7)=:p{wc_sp}'''),q).mappings().one()
                down=c.execute(text(f'''SELECT COALESCE(SUM(duration_minutes),0) mins FROM maintenance_event WHERE organization_id=:o AND entity_id=:e AND event_type='BREAKDOWN' AND substr(event_at,1,7)=:p{wc_ev}'''),q).scalar_one()
                oee=c.execute(text(f'''SELECT COALESCE(AVG(oee_pct),0) oee FROM manufacturing_machine_oee WHERE organization_id=:o AND entity_id=:e AND period_start>=:s AND period_start<:n{(' AND work_center_id=:w' if w else '')}'''),{'o':o,'e':eid,'s':f'{period}-01','n':f'{_prev(period)}-01' if period.endswith('-01') else f'{period}-32','w':w}).scalar_one()
                pm=_d(Decimal(str(r['pm_labour'] or 0))+Decimal(str(sp['pm_spare'] or 0))); bd=_d(Decimal(str(r['bd_labour'] or 0))+Decimal(str(sp['bd_spare'] or 0))); total=_d(pm+bd); hours=_d(Decimal(str(down or 0))/Decimal('60'))
                return pm,bd,total,hours,_d(oee)
            cp,cb,ct,ch,co=metrics(pk); bp,bb,bt,bh,bo=metrics(base)
        avoided=_d(max(Decimal('0'),bb-cb))
        pm_change=_d(cp-bp)
        net=_d(avoided-pm_change)
        roi=_d(net/cp*100) if cp>0 else Decimal('0')
        hours=_d(max(Decimal('0'),bh-ch)); hp=_d(hours/bh*100) if bh else Decimal('0')
        oi=_d(co-bo)
        score=_d(max(Decimal('0'),min(Decimal('100'), max(Decimal('0'),hp)*Decimal('0.5') + max(Decimal('0'),roi)*Decimal('0.3') + max(Decimal('0'),oi)*Decimal('0.2'))))
        status='OPTIMIZED' if score>=70 else ('IMPROVING' if score>=40 else 'REVIEW')
        sid=str(uuid4())
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_roi_snapshot(snapshot_id,organization_id,entity_id,period_key,baseline_period_key,work_center_id,current_preventive_cost,current_breakdown_cost,baseline_preventive_cost,baseline_breakdown_cost,current_maintenance_cost,baseline_maintenance_cost,avoided_breakdown_cost,preventive_cost_change,net_reliability_benefit,preventive_roi_pct,breakdown_hours_avoided,breakdown_hours_reduction_pct,oee_improvement_pct,optimization_score,status,created_by)
                VALUES(:i,:o,:e,:p,:b,:w,:cp,:cb,:bp,:bb,:ct,:bt,:ab,:pc,:nb,:roi,:ha,:hp,:oi,:sc,:st,:u)
                ON CONFLICT(organization_id,entity_id,period_key,work_center_id) DO UPDATE SET baseline_period_key=:b,current_preventive_cost=:cp,current_breakdown_cost=:cb,baseline_preventive_cost=:bp,baseline_breakdown_cost=:bb,current_maintenance_cost=:ct,baseline_maintenance_cost=:bt,avoided_breakdown_cost=:ab,preventive_cost_change=:pc,net_reliability_benefit=:nb,preventive_roi_pct=:roi,breakdown_hours_avoided=:ha,breakdown_hours_reduction_pct=:hp,oee_improvement_pct=:oi,optimization_score=:sc,status=:st,created_by=:u,created_at=CURRENT_TIMESTAMP'''),{'i':sid,'o':o,'e':eid,'p':pk,'b':base,'w':w,'cp':float(cp),'cb':float(cb),'bp':float(bp),'bb':float(bb),'ct':float(ct),'bt':float(bt),'ab':float(avoided),'pc':float(pm_change),'nb':float(net),'roi':float(roi),'ha':float(hours),'hp':float(hp),'oi':float(oi),'sc':float(score),'st':status,'u':str(u.user_id)})
            row=c.execute(text('SELECT snapshot_id FROM maintenance_roi_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND ((work_center_id=:w) OR (work_center_id IS NULL AND :w IS NULL))'),{'o':o,'e':eid,'p':pk,'w':w}).scalar_one()
        return {'snapshot_id':row,'period_key':pk,'baseline_period_key':base,'avoided_breakdown_cost':float(avoided),'preventive_cost_change':float(pm_change),'net_reliability_benefit':float(net),'preventive_roi_pct':float(roi),'breakdown_hours_avoided':float(hours),'breakdown_hours_reduction_pct':float(hp),'oee_improvement_pct':float(oi),'optimization_score':float(score),'status':status}

    @app.get('/v90em/maintenance/roi/dashboard')
    def dashboard(request:Request,organization_id:str,entity_id:str,period_key:str):
        _perm(e,request,'maintenance_roi.view')
        with e.connect() as c:
            rows=c.execute(text('SELECT * FROM maintenance_roi_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY optimization_score DESC,work_center_id'),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        return {'count':len(rows),'rows':[dict(x) for x in rows],'average_optimization_score':float(_d(sum((_d(x['optimization_score']) for x in rows),Decimal('0'))/len(rows))) if rows else 0.0}

    @app.get('/v90em/maintenance/roi/compare')
    def compare(request:Request,organization_id:str,entity_id:str,period_key:str):
        _perm(e,request,'maintenance_roi.view')
        with e.connect() as c:
            r=c.execute(text('''SELECT COALESCE(SUM(current_preventive_cost),0) current_preventive_cost,COALESCE(SUM(current_breakdown_cost),0) current_breakdown_cost,COALESCE(SUM(avoided_breakdown_cost),0) avoided_breakdown_cost,COALESCE(SUM(net_reliability_benefit),0) net_reliability_benefit,COALESCE(AVG(preventive_roi_pct),0) preventive_roi_pct,COALESCE(SUM(breakdown_hours_avoided),0) breakdown_hours_avoided,COALESCE(AVG(oee_improvement_pct),0) oee_improvement_pct,COALESCE(AVG(optimization_score),0) optimization_score FROM maintenance_roi_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'''),{'o':organization_id,'e':entity_id,'p':period_key}).mappings().one()
        return dict(r)

    @app.post('/v90em/maintenance/roi/{period_key}/close')
    def close(period_key:str,body:dict,request:Request):
        u=_perm(e,request,'maintenance_roi.close')
        for k in ('organization_id','entity_id'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_roi_close(close_id,organization_id,entity_id,period_key,closed_by) VALUES(:i,:o,:e,:p,:u) ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''),{'i':str(uuid4()),'o':body['organization_id'],'e':body['entity_id'],'p':period_key,'u':str(u.user_id)})
            c.execute(text('UPDATE maintenance_roi_snapshot SET status=\'CLOSED\' WHERE organization_id=:o AND entity_id=:e AND period_key=:p'),{'o':body['organization_id'],'e':body['entity_id'],'p':period_key})
        return {'period_key':period_key,'status':'CLOSED'}

    @app.get('/ui/maintenance-roi')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-roi.html')

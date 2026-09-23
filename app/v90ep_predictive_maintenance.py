from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user

def d(v):
    return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def perm(e, r, p):
    u = authenticate(r); ps = permissions_for_user(e, u.user_id)
    if p not in ps and 'admin.users' not in ps:
        raise HTTPException(403, 'permission denied')
    return u

def prev(pk):
    y, m = map(int, pk.split('-')); m -= 1
    if m == 0: y -= 1; m = 12
    return f'{y:04d}-{m:02d}'

def valid(pk):
    try:
        y, m = map(int, pk.split('-'))
        if y < 2000 or not 1 <= m <= 12: raise ValueError
    except Exception:
        raise HTTPException(400, 'period_key must be YYYY-MM')

def register_v90ep_routes(app: FastAPI, e):
    with e.begin() as c:
        for p, n in [('maintenance_risk.view','View Predictive Maintenance Risk'),('maintenance_risk.manage','Calculate Predictive Maintenance Risk'),('maintenance_risk.close','Close Predictive Maintenance Risk')]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'), {'p':p,'n':n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_risk_snapshot(
 snapshot_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL, baseline_period_key TEXT NOT NULL, work_center_id TEXT,
 breakdown_orders INTEGER NOT NULL DEFAULT 0, repeat_breakdown_orders INTEGER NOT NULL DEFAULT 0, breakdown_hours NUMERIC NOT NULL DEFAULT 0,
 pm_orders INTEGER NOT NULL DEFAULT 0, prior_breakdown_orders INTEGER NOT NULL DEFAULT 0, prior_breakdown_hours NUMERIC NOT NULL DEFAULT 0,
 failure_rate_per_100_orders NUMERIC NOT NULL DEFAULT 0, breakdown_growth_pct NUMERIC NOT NULL DEFAULT 0, repeat_failure_ratio_pct NUMERIC NOT NULL DEFAULT 0,
 risk_score NUMERIC NOT NULL DEFAULT 0, risk_level TEXT NOT NULL DEFAULT 'LOW', warning_signal TEXT NOT NULL DEFAULT 'NONE', recommended_action TEXT NOT NULL DEFAULT 'MONITOR',
 confidence TEXT NOT NULL DEFAULT 'LOW', status TEXT NOT NULL DEFAULT 'OPEN', created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'''))
        c.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ux_maintenance_risk_key ON maintenance_risk_snapshot(organization_id,entity_id,period_key,work_center_id)'))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_risk_close(
 close_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, entity_id TEXT NOT NULL, period_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'CLOSED', closed_by TEXT NOT NULL, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(organization_id,entity_id,period_key))'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_maintenance_risk_scope ON maintenance_risk_snapshot(organization_id,entity_id,period_key,work_center_id,risk_level,status)'))

    @app.post('/v90ep/maintenance/risk/snapshot')
    def snapshot(body: dict, request: Request):
        u = perm(e, request, 'maintenance_risk.manage')
        for k in ('organization_id','entity_id','period_key'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400, f'{k} is required')
        o, eid, pk = body['organization_id'], body['entity_id'], body['period_key']; base = body.get('baseline_period_key') or prev(pk); w = body.get('work_center_id')
        valid(pk); valid(base)
        q = {'o':o,'e':eid,'p':pk,'b':base,'w':w}
        wc = ' AND work_center_id=:w' if w else ''
        wcp = ' AND work_center_id=:w' if w else ''
        with e.connect() as c:
            if c.execute(text('SELECT 1 FROM maintenance_risk_close WHERE organization_id=:o AND entity_id=:e AND period_key=:p'), q).first():
                raise HTTPException(409, 'period is closed')
            cur = c.execute(text(f'''SELECT
                COALESCE(SUM(CASE WHEN order_type='BREAKDOWN' THEN 1 ELSE 0 END),0) bd,
                COALESCE(SUM(CASE WHEN order_type='PREVENTIVE' THEN 1 ELSE 0 END),0) pm
                FROM maintenance_order WHERE organization_id=:o AND entity_id=:e AND CAST(scheduled_date AS TEXT) LIKE :p_like{wc}'''), {**q,'p_like':pk+'%' }).mappings().one()
            prior = c.execute(text(f'''SELECT COALESCE(SUM(CASE WHEN order_type='BREAKDOWN' THEN 1 ELSE 0 END),0) bd
                FROM maintenance_order WHERE organization_id=:o AND entity_id=:e AND CAST(scheduled_date AS TEXT) LIKE :b_like{wc}'''), {**q,'b_like':base+'%'}).mappings().one()
            hrs = c.execute(text(f'''SELECT COALESCE(SUM(duration_minutes),0)/60.0 FROM maintenance_event
                WHERE organization_id=:o AND entity_id=:e AND event_type='BREAKDOWN' AND CAST(event_at AS TEXT) LIKE :p_like{wc}'''), {**q,'p_like':pk+'%'}).scalar_one()
            phrs = c.execute(text(f'''SELECT COALESCE(SUM(duration_minutes),0)/60.0 FROM maintenance_event
                WHERE organization_id=:o AND entity_id=:e AND event_type='BREAKDOWN' AND CAST(event_at AS TEXT) LIKE :b_like{wc}'''), {**q,'b_like':base+'%'}).scalar_one()
            rep = c.execute(text(f'''SELECT COALESCE(SUM(x.n-1),0) FROM (SELECT work_center_id,COUNT(*) n FROM maintenance_order
                WHERE organization_id=:o AND entity_id=:e AND order_type='BREAKDOWN' AND CAST(scheduled_date AS TEXT) LIKE :p_like{wc} GROUP BY work_center_id) x'''), {**q,'p_like':pk+'%'}).scalar_one()
        bd, pm, pbd = int(cur['bd'] or 0), int(cur['pm'] or 0), int(prior['bd'] or 0)
        bh, pbh, rep = d(hrs), d(phrs), int(rep or 0)
        growth = d((Decimal(bd)-Decimal(pbd))/Decimal(pbd)*100) if pbd else d(100 if bd else 0)
        total_orders = bd + pm
        rate = d(Decimal(bd)/Decimal(total_orders)*100) if total_orders else d(0)
        repeat_ratio = d(Decimal(rep)/Decimal(bd)*100) if bd else d(0)
        hour_growth = d((bh-pbh)/pbh*100) if pbh else d(100 if bh else 0)
        score = d(min(100, max(0, Decimal('0.35')*max(0,growth) + Decimal('0.30')*max(0,hour_growth) + Decimal('0.20')*repeat_ratio + Decimal('0.15')*rate)))
        if score >= 70: level, signal, action = 'CRITICAL','HIGH_FAILURE_RISK','PRIORITIZE_IMMEDIATE_INSPECTION'
        elif score >= 40: level, signal, action = 'HIGH','ELEVATED_FAILURE_RISK','INCREASE_PM_ATTENTION'
        elif score >= 20: level, signal, action = 'MEDIUM','WATCH_FAILURE_TREND','REVIEW_PM_PLAN'
        else: level, signal, action = 'LOW','NONE','MONITOR'
        conf = 'HIGH' if total_orders >= 5 else ('MEDIUM' if total_orders >= 2 else 'LOW')
        sid = str(uuid4())
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_risk_snapshot(snapshot_id,organization_id,entity_id,period_key,baseline_period_key,work_center_id,breakdown_orders,repeat_breakdown_orders,breakdown_hours,pm_orders,prior_breakdown_orders,prior_breakdown_hours,failure_rate_per_100_orders,breakdown_growth_pct,repeat_failure_ratio_pct,risk_score,risk_level,warning_signal,recommended_action,confidence,status,created_by)
            VALUES(:i,:o,:e,:p,:b,:w,:bd,:rep,:bh,:pm,:pbd,:pbh,:rate,:growth,:rr,:score,:level,:signal,:action,:conf,'OPEN',:u)
            ON CONFLICT(organization_id,entity_id,period_key,work_center_id) DO UPDATE SET baseline_period_key=:b,breakdown_orders=:bd,repeat_breakdown_orders=:rep,breakdown_hours=:bh,pm_orders=:pm,prior_breakdown_orders=:pbd,prior_breakdown_hours=:pbh,failure_rate_per_100_orders=:rate,breakdown_growth_pct=:growth,repeat_failure_ratio_pct=:rr,risk_score=:score,risk_level=:level,warning_signal=:signal,recommended_action=:action,confidence=:conf,status='OPEN',created_by=:u,created_at=CURRENT_TIMESTAMP'''), {'i':sid,'o':o,'e':eid,'p':pk,'b':base,'w':w,'bd':bd,'rep':rep,'bh':float(bh),'pm':pm,'pbd':pbd,'pbh':float(pbh),'rate':float(rate),'growth':float(growth),'rr':float(repeat_ratio),'score':float(score),'level':level,'signal':signal,'action':action,'conf':conf,'u':str(u.user_id)})
            rid = c.execute(text('SELECT snapshot_id FROM maintenance_risk_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND ((work_center_id=:w) OR (work_center_id IS NULL AND :w IS NULL))'), q).scalar_one()
        return {'snapshot_id':rid,'period_key':pk,'baseline_period_key':base,'work_center_id':w,'breakdown_orders':bd,'repeat_breakdown_orders':rep,'breakdown_hours':float(bh),'pm_orders':pm,'prior_breakdown_orders':pbd,'prior_breakdown_hours':float(pbh),'failure_rate_per_100_orders':float(rate),'breakdown_growth_pct':float(growth),'repeat_failure_ratio_pct':float(repeat_ratio),'risk_score':float(score),'risk_level':level,'warning_signal':signal,'recommended_action':action,'confidence':conf,'status':'OPEN'}

    @app.get('/v90ep/maintenance/risk/dashboard')
    def dashboard(request: Request, organization_id: str, entity_id: str, period_key: str):
        perm(e, request, 'maintenance_risk.view')
        with e.connect() as c:
            rows = c.execute(text('SELECT * FROM maintenance_risk_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY risk_score DESC,work_center_id'), {'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        return {'count':len(rows),'rows':[dict(r) for r in rows],'critical_count':sum(r['risk_level']=='CRITICAL' for r in rows),'high_count':sum(r['risk_level']=='HIGH' for r in rows)}

    @app.get('/v90ep/maintenance/risk/ranking')
    def ranking(request: Request, organization_id: str, entity_id: str, period_key: str):
        perm(e, request, 'maintenance_risk.view')
        with e.connect() as c:
            rows = c.execute(text('''SELECT work_center_id,risk_score,risk_level,warning_signal,recommended_action,confidence,breakdown_orders,breakdown_hours,repeat_breakdown_orders
                FROM maintenance_risk_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p ORDER BY risk_score DESC,work_center_id'''), {'o':organization_id,'e':entity_id,'p':period_key}).mappings().all()
        return {'count':len(rows),'ranking':[dict(r) for r in rows]}

    @app.get('/v90ep/maintenance/risk/trend')
    def trend(request: Request, organization_id: str, entity_id: str, work_center_id: str | None = None, limit: int = 12):
        perm(e, request, 'maintenance_risk.view')
        limit = max(1,min(36,limit)); params={'o':organization_id,'e':entity_id,'limit':limit}
        clause = ''
        if work_center_id:
            clause=' AND work_center_id=:w'; params['w']=work_center_id
        with e.connect() as c:
            rows=c.execute(text(f'''SELECT period_key,work_center_id,risk_score,risk_level,breakdown_orders,breakdown_hours,repeat_breakdown_orders
                FROM maintenance_risk_snapshot WHERE organization_id=:o AND entity_id=:e{clause} ORDER BY period_key DESC,risk_score DESC LIMIT :limit'''),params).mappings().all()
        return {'count':len(rows),'trend':[dict(r) for r in rows]}

    @app.post('/v90ep/maintenance/risk/{period_key}/close')
    def close(period_key: str, body: dict, request: Request):
        u=perm(e,request,'maintenance_risk.close'); valid(period_key)
        for k in ('organization_id','entity_id'):
            if not str(body.get(k) or '').strip(): raise HTTPException(400,f'{k} is required')
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_risk_close(close_id,organization_id,entity_id,period_key,closed_by) VALUES(:i,:o,:e,:p,:u)
            ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''), {'i':str(uuid4()),'o':body['organization_id'],'e':body['entity_id'],'p':period_key,'u':str(u.user_id)})
            c.execute(text("UPDATE maintenance_risk_snapshot SET status='CLOSED' WHERE organization_id=:o AND entity_id=:e AND period_key=:p"), {'o':body['organization_id'],'e':body['entity_id'],'p':period_key})
        return {'period_key':period_key,'status':'CLOSED'}

    @app.get('/ui/maintenance-risk')
    def page(): return FileResponse(Path(__file__).resolve().parents[1]/'web'/'maintenance-risk.html')

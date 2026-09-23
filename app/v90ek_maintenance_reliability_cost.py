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

def _perm(e, r, p):
    u = authenticate(r)
    ps = permissions_for_user(e, u.user_id)
    if p not in ps and 'admin.users' not in ps:
        raise HTTPException(403, 'permission denied')
    return u

def register_v90ek_routes(app: FastAPI, e):
    with e.begin() as c:
        for p, n in [
            ('maintenance_reliability.view', 'View Maintenance Reliability Cost'),
            ('maintenance_reliability.manage', 'Manage Maintenance Reliability Cost'),
            ('maintenance_reliability.close', 'Close Maintenance Reliability Cost'),
        ]:
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'), {'p': p, 'n': n})
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_cost_snapshot(
            snapshot_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            period_key TEXT NOT NULL,
            work_center_id TEXT,
            preventive_labour_cost NUMERIC NOT NULL DEFAULT 0,
            breakdown_labour_cost NUMERIC NOT NULL DEFAULT 0,
            maintenance_labour_cost NUMERIC NOT NULL DEFAULT 0,
            preventive_spare_cost NUMERIC NOT NULL DEFAULT 0,
            breakdown_spare_cost NUMERIC NOT NULL DEFAULT 0,
            maintenance_spare_cost NUMERIC NOT NULL DEFAULT 0,
            total_maintenance_cost NUMERIC NOT NULL DEFAULT 0,
            breakdown_hours NUMERIC NOT NULL DEFAULT 0,
            production_qty NUMERIC NOT NULL DEFAULT 0,
            production_labour_cost NUMERIC NOT NULL DEFAULT 0,
            production_total_cost NUMERIC NOT NULL DEFAULT 0,
            oee_pct NUMERIC NOT NULL DEFAULT 0,
            maintenance_cost_per_unit NUMERIC NOT NULL DEFAULT 0,
            downtime_cost_per_hour NUMERIC NOT NULL DEFAULT 0,
            maintenance_cost_pct_of_production NUMERIC NOT NULL DEFAULT 0,
            reliability_score NUMERIC NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'OPEN',
            created_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key,work_center_id)
        )'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_reliability_cost_close(
            close_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            period_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'CLOSED',
            closed_by TEXT NOT NULL,
            closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_key)
        )'''))
        c.execute(text('CREATE INDEX IF NOT EXISTS ix_mrc_snapshot_scope ON maintenance_reliability_cost_snapshot(organization_id,entity_id,period_key,work_center_id,status)'))

    @app.post('/v90ek/maintenance/reliability-cost/snapshot')
    def snapshot(body: dict, request: Request):
        u = _perm(e, request, 'maintenance_reliability.manage')
        for k in ('organization_id', 'entity_id', 'period_key'):
            if not str(body.get(k) or '').strip():
                raise HTTPException(400, f'{k} is required')
        o, eid, pk = body['organization_id'], body['entity_id'], body['period_key']
        w = body.get('work_center_id')
        with e.connect() as c:
            closed = c.execute(text('SELECT 1 FROM maintenance_reliability_cost_close WHERE organization_id=:o AND entity_id=:e AND period_key=:p'), {'o': o, 'e': eid, 'p': pk}).first()
            if closed:
                raise HTTPException(409, 'period is closed')
            params = {'o': o, 'e': eid, 'p': pk, 'w': w}
            wc_filter = ' AND {alias}.work_center_id=:w' if w else ''
            charge = c.execute(text(f'''SELECT
                COALESCE(SUM(CASE WHEN mo.order_type='PREVENTIVE' THEN ml.total_cost ELSE 0 END),0) preventive_labour,
                COALESCE(SUM(CASE WHEN mo.order_type='BREAKDOWN' THEN ml.total_cost ELSE 0 END),0) breakdown_labour,
                COALESCE(SUM(ml.total_cost),0) total_labour
                FROM maintenance_labour_charge ml
                JOIN maintenance_order mo ON mo.order_id=ml.maintenance_order_id
                WHERE ml.organization_id=:o AND ml.entity_id=:e AND CAST(ml.charge_date AS TEXT) LIKE substr(:p,1,7) || '%'{wc_filter.format(alias='ml')}'''), params).mappings().one()
            spare = c.execute(text(f'''SELECT
                COALESCE(SUM(CASE WHEN mo.order_type='PREVENTIVE' THEN ms.total_cost ELSE 0 END),0) preventive_spare,
                COALESCE(SUM(CASE WHEN mo.order_type='BREAKDOWN' THEN ms.total_cost ELSE 0 END),0) breakdown_spare,
                COALESCE(SUM(ms.total_cost),0) total_spare
                FROM maintenance_spare_usage ms
                LEFT JOIN maintenance_order mo ON mo.order_id=ms.maintenance_order_id
                WHERE ms.organization_id=:o AND ms.entity_id=:e{wc_filter.format(alias='ms')}
                  AND (mo.scheduled_date IS NULL OR CAST(mo.scheduled_date AS TEXT) LIKE substr(:p,1,7) || '%')'''), params).mappings().one()
            down = c.execute(text(f'''SELECT COALESCE(SUM(duration_minutes),0) mins
                FROM maintenance_event WHERE organization_id=:o AND entity_id=:e
                AND event_type='BREAKDOWN' AND CAST(event_at AS TEXT) LIKE substr(:p,1,7) || '%'{wc_filter.format(alias='maintenance_event')}'''), params).scalar_one()
            prod = c.execute(text(f'''SELECT COALESCE(SUM(planned_qty),0) qty,
                COALESCE(SUM(labor_cost),0) labor_cost,COALESCE(SUM(total_cost),0) total_cost
                FROM manufacturing_batch_cost
                WHERE organization_id=:o AND entity_id=:e AND period_key=:p
                  AND (:w IS NULL OR batch_id IN (
                      SELECT DISTINCT bc.batch_id FROM manufacturing_batch_cost bc
                      JOIN manufacturing_schedule ms ON ms.organization_id=bc.organization_id AND ms.entity_id=bc.entity_id AND ms.product_id=bc.product_id
                      WHERE ms.organization_id=:o AND ms.entity_id=:e AND ms.work_center_id=:w AND ms.status IN ('PLANNED','APPROVED')
                  ))'''), params).mappings().one()
            oee = c.execute(text('''SELECT COALESCE(AVG(oee_pct),0) FROM manufacturing_machine_oee
                WHERE organization_id=:o AND entity_id=:e AND period_start>=:s AND period_end<=:d
                AND (:w IS NULL OR work_center_id=:w)'''), {'o': o, 'e': eid, 's': f'{pk}-01', 'd': f'{pk}-31', 'w': w}).scalar_one()
        pl = _d(charge['preventive_labour']); bl = _d(charge['breakdown_labour']); tl = _d(charge['total_labour'])
        ps = _d(spare['preventive_spare']); bs = _d(spare['breakdown_spare']); ts = _d(spare['total_spare'])
        total = _d(tl + ts)
        dh = _d(Decimal(str(down or 0)) / Decimal('60'))
        qty = _d(prod['qty']); prod_lab = _d(prod['labor_cost']); prod_total = _d(prod['total_cost']); oee_pct = _d(oee)
        cpu = _d(total / qty) if qty else Decimal('0')
        dch = _d(total / dh) if dh else Decimal('0')
        pct = _d(total / prod_total * 100) if prod_total else Decimal('0')
        reliability = _d(max(Decimal('0'), min(Decimal('100'), oee_pct - (pct / Decimal('2')) - (dh * Decimal('0.5')))))
        sid = str(uuid4())
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_reliability_cost_snapshot(
                snapshot_id,organization_id,entity_id,period_key,work_center_id,
                preventive_labour_cost,breakdown_labour_cost,maintenance_labour_cost,
                preventive_spare_cost,breakdown_spare_cost,maintenance_spare_cost,total_maintenance_cost,
                breakdown_hours,production_qty,production_labour_cost,production_total_cost,oee_pct,
                maintenance_cost_per_unit,downtime_cost_per_hour,maintenance_cost_pct_of_production,reliability_score,created_by)
                VALUES(:i,:o,:e,:p,:w,:pl,:bl,:tl,:ps,:bs,:ts,:tc,:dh,:q,:pc,:pt,:oee,:cpu,:dch,:pct,:rs,:u)
                ON CONFLICT(organization_id,entity_id,period_key,work_center_id) DO UPDATE SET
                preventive_labour_cost=:pl,breakdown_labour_cost=:bl,maintenance_labour_cost=:tl,
                preventive_spare_cost=:ps,breakdown_spare_cost=:bs,maintenance_spare_cost=:ts,total_maintenance_cost=:tc,
                breakdown_hours=:dh,production_qty=:q,production_labour_cost=:pc,production_total_cost=:pt,oee_pct=:oee,
                maintenance_cost_per_unit=:cpu,downtime_cost_per_hour=:dch,maintenance_cost_pct_of_production=:pct,
                reliability_score=:rs,status='OPEN',created_by=:u,created_at=CURRENT_TIMESTAMP'''),
                {'i': sid, 'o': o, 'e': eid, 'p': pk, 'w': w, 'pl': float(pl), 'bl': float(bl), 'tl': float(tl), 'ps': float(ps), 'bs': float(bs), 'ts': float(ts), 'tc': float(total), 'dh': float(dh), 'q': float(qty), 'pc': float(prod_lab), 'pt': float(prod_total), 'oee': float(oee_pct), 'cpu': float(cpu), 'dch': float(dch), 'pct': float(pct), 'rs': float(reliability), 'u': str(u.user_id)})
            row = c.execute(text('SELECT snapshot_id FROM maintenance_reliability_cost_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p AND ((work_center_id=:w) OR (work_center_id IS NULL AND :w IS NULL))'), params).scalar_one()
        return {'snapshot_id': row, 'preventive_maintenance_cost': float(_d(pl + ps)), 'breakdown_maintenance_cost': float(_d(bl + bs)), 'maintenance_cost': float(total), 'breakdown_hours': float(dh), 'production_qty': float(qty), 'maintenance_cost_per_unit': float(cpu), 'maintenance_cost_pct_of_production': float(pct), 'oee_pct': float(oee_pct), 'reliability_score': float(reliability), 'status': 'OPEN'}

    @app.get('/v90ek/maintenance/reliability-cost/dashboard')
    def dashboard(request: Request, organization_id: str, entity_id: str, period_key: str):
        _perm(e, request, 'maintenance_reliability.view')
        with e.connect() as c:
            rows = c.execute(text('''SELECT * FROM maintenance_reliability_cost_snapshot
                WHERE organization_id=:o AND entity_id=:e AND period_key=:p
                ORDER BY total_maintenance_cost DESC,work_center_id'''), {'o': organization_id, 'e': entity_id, 'p': period_key}).mappings().all()
        return {'snapshots': [dict(r) for r in rows], 'count': len(rows)}

    @app.get('/v90ek/maintenance/reliability-cost/compare')
    def compare(request: Request, organization_id: str, entity_id: str, period_key: str):
        _perm(e, request, 'maintenance_reliability.view')
        with e.connect() as c:
            r = c.execute(text('''SELECT COALESCE(SUM(preventive_labour_cost+preventive_spare_cost),0) preventive_cost,
                COALESCE(SUM(breakdown_labour_cost+breakdown_spare_cost),0) breakdown_cost,
                COALESCE(SUM(total_maintenance_cost),0) total_cost,
                COALESCE(SUM(breakdown_hours),0) breakdown_hours,
                COALESCE(AVG(oee_pct),0) avg_oee_pct,
                COALESCE(AVG(reliability_score),0) avg_reliability_score,
                COALESCE(SUM(production_qty),0) production_qty
                FROM maintenance_reliability_cost_snapshot WHERE organization_id=:o AND entity_id=:e AND period_key=:p'''), {'o': organization_id, 'e': entity_id, 'p': period_key}).mappings().one()
        return dict(r)

    @app.post('/v90ek/maintenance/reliability-cost/{period_key}/close')
    def close(period_key: str, body: dict, request: Request):
        u = _perm(e, request, 'maintenance_reliability.close')
        for k in ('organization_id', 'entity_id'):
            if not str(body.get(k) or '').strip():
                raise HTTPException(400, f'{k} is required')
        with e.begin() as c:
            c.execute(text('''INSERT INTO maintenance_reliability_cost_close(close_id,organization_id,entity_id,period_key,closed_by)
                VALUES(:i,:o,:e,:p,:u)
                ON CONFLICT(organization_id,entity_id,period_key) DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''), {'i': str(uuid4()), 'o': body['organization_id'], 'e': body['entity_id'], 'p': period_key, 'u': str(u.user_id)})
            c.execute(text('''UPDATE maintenance_reliability_cost_snapshot SET status='CLOSED' WHERE organization_id=:o AND entity_id=:e AND period_key=:p'''), {'o': body['organization_id'], 'e': body['entity_id'], 'p': period_key})
        return {'period_key': period_key, 'status': 'CLOSED'}

    @app.get('/ui/maintenance-reliability-cost')
    def page():
        return FileResponse(Path(__file__).resolve().parents[1] / 'web' / 'maintenance-reliability-cost.html')

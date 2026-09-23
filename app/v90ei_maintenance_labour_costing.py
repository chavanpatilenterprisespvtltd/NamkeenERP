from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from .auth import authenticate
from .identity import permissions_for_user


def _n(v):
    return Decimal(str(v or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _perm(engine, request, permission):
    u = authenticate(request)
    ps = permissions_for_user(engine, u.user_id)
    if permission not in ps and 'admin.users' not in ps:
        raise HTTPException(403, 'permission denied')
    return u


def register_v90ei_routes(app: FastAPI, engine):
    with engine.begin() as c:
        for pid, name in [
            ('maintenance_labour.view', 'View Maintenance Labour Costing'),
            ('maintenance_labour.manage', 'Manage Maintenance Labour Costing'),
            ('maintenance_labour.close', 'Close Maintenance Labour Costing'),
        ]:
            c.execute(text('''INSERT INTO erp_permissions(permission_id,permission_name)
                              VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'''), {'p': pid, 'n': name})
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_labour_rate(
            rate_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            work_center_id TEXT,
            employee_id TEXT,
            labour_category TEXT,
            regular_rate NUMERIC NOT NULL DEFAULT 0,
            overtime_rate NUMERIC NOT NULL DEFAULT 0,
            burden_pct NUMERIC NOT NULL DEFAULT 0,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            effective_from DATE,
            effective_to DATE,
            created_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_labour_charge(
            charge_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            maintenance_order_id TEXT NOT NULL,
            work_center_id TEXT NOT NULL,
            employee_id TEXT,
            labour_category TEXT,
            charge_date DATE NOT NULL,
            regular_hours NUMERIC NOT NULL DEFAULT 0,
            overtime_hours NUMERIC NOT NULL DEFAULT 0,
            regular_rate NUMERIC NOT NULL DEFAULT 0,
            overtime_rate NUMERIC NOT NULL DEFAULT 0,
            burden_pct NUMERIC NOT NULL DEFAULT 0,
            regular_cost NUMERIC NOT NULL DEFAULT 0,
            overtime_cost NUMERIC NOT NULL DEFAULT 0,
            burden_cost NUMERIC NOT NULL DEFAULT 0,
            total_cost NUMERIC NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'OPEN',
            created_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )'''))
        c.execute(text('''CREATE TABLE IF NOT EXISTS maintenance_labour_close(
            close_id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            period_start DATE NOT NULL,
            period_end DATE NOT NULL,
            status TEXT NOT NULL DEFAULT 'CLOSED',
            closed_by TEXT NOT NULL,
            closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_id,entity_id,period_start,period_end)
        )'''))
        c.execute(text('''CREATE INDEX IF NOT EXISTS ix_maintenance_labour_charge_scope
                          ON maintenance_labour_charge(organization_id,entity_id,maintenance_order_id,charge_date,status)'''))
        c.execute(text('''CREATE INDEX IF NOT EXISTS ix_maintenance_labour_rate_scope
                          ON maintenance_labour_rate(organization_id,entity_id,work_center_id,employee_id,active,effective_from)'''))

    @app.post('/v90ei/maintenance/labour-rates')
    def create_rate(body: dict, request: Request):
        u = _perm(engine, request, 'maintenance_labour.manage')
        for k in ('organization_id', 'entity_id'):
            if not str(body.get(k) or '').strip():
                raise HTTPException(400, f'{k} is required')
        if not body.get('work_center_id') and not body.get('employee_id') and not body.get('labour_category'):
            raise HTTPException(400, 'work_center_id, employee_id or labour_category is required')
        rid = str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO maintenance_labour_rate(
                rate_id,organization_id,entity_id,work_center_id,employee_id,labour_category,
                regular_rate,overtime_rate,burden_pct,active,effective_from,effective_to,created_by)
                VALUES(:id,:o,:e,:w,:emp,:cat,:rr,:otr,:bp,:a,:ef,:et,:u)'''), {
                    'id': rid, 'o': body['organization_id'], 'e': body['entity_id'],
                    'w': body.get('work_center_id'), 'emp': body.get('employee_id'),
                    'cat': body.get('labour_category'), 'rr': float(body.get('regular_rate') or 0),
                    'otr': float(body.get('overtime_rate') or body.get('regular_rate') or 0),
                    'bp': float(body.get('burden_pct') or 0), 'a': bool(body.get('active', True)),
                    'ef': body.get('effective_from'), 'et': body.get('effective_to'), 'u': str(u.user_id),
                })
        return {'rate_id': rid, 'status': 'CREATED'}

    @app.post('/v90ei/maintenance/labour-charges')
    def create_charge(body: dict, request: Request):
        u = _perm(engine, request, 'maintenance_labour.manage')
        for k in ('organization_id', 'entity_id', 'maintenance_order_id', 'work_center_id', 'charge_date'):
            if not str(body.get(k) or '').strip():
                raise HTTPException(400, f'{k} is required')
        regular_hours = _n(body.get('regular_hours'))
        overtime_hours = _n(body.get('overtime_hours'))
        if regular_hours < 0 or overtime_hours < 0:
            raise HTTPException(400, 'hours cannot be negative')
        with engine.connect() as c:
            order = c.execute(text('''SELECT order_id,status FROM maintenance_order
                                      WHERE order_id=:id AND organization_id=:o AND entity_id=:e AND work_center_id=:w'''), {
                'id': body['maintenance_order_id'], 'o': body['organization_id'], 'e': body['entity_id'], 'w': body['work_center_id']
            }).mappings().first()
            if not order:
                raise HTTPException(404, 'maintenance order not found')
            rate = None
            if body.get('rate_id'):
                rate = c.execute(text('''SELECT * FROM maintenance_labour_rate WHERE rate_id=:id AND organization_id=:o AND entity_id=:e AND active=TRUE'''), {
                    'id': body['rate_id'], 'o': body['organization_id'], 'e': body['entity_id']
                }).mappings().first()
            if not rate:
                rate = c.execute(text('''SELECT * FROM maintenance_labour_rate
                    WHERE organization_id=:o AND entity_id=:e AND active=TRUE
                      AND (work_center_id=:w OR work_center_id IS NULL)
                      AND (employee_id=:emp OR employee_id IS NULL)
                      AND (labour_category=:cat OR labour_category IS NULL)
                      AND (effective_from IS NULL OR effective_from<=:d)
                      AND (effective_to IS NULL OR effective_to>=:d)
                    ORDER BY CASE WHEN employee_id IS NOT NULL THEN 0 ELSE 1 END,
                             CASE WHEN work_center_id IS NOT NULL THEN 0 ELSE 1 END,
                             CASE WHEN labour_category IS NOT NULL THEN 0 ELSE 1 END,
                             effective_from DESC'''), {
                    'o': body['organization_id'], 'e': body['entity_id'], 'w': body['work_center_id'],
                    'emp': body.get('employee_id'), 'cat': body.get('labour_category'), 'd': body['charge_date']
                }).mappings().first()
        regular_rate = _n(body.get('regular_rate') if body.get('regular_rate') is not None else (rate['regular_rate'] if rate else 0))
        overtime_rate = _n(body.get('overtime_rate') if body.get('overtime_rate') is not None else (rate['overtime_rate'] if rate else regular_rate))
        burden_pct = _n(body.get('burden_pct') if body.get('burden_pct') is not None else (rate['burden_pct'] if rate else 0))
        regular_cost = _n(regular_hours * regular_rate)
        overtime_cost = _n(overtime_hours * overtime_rate)
        burden_cost = _n((regular_cost + overtime_cost) * burden_pct / Decimal('100'))
        total_cost = _n(regular_cost + overtime_cost + burden_cost)
        cid = str(uuid4())
        with engine.begin() as c:
            c.execute(text('''INSERT INTO maintenance_labour_charge(
                charge_id,organization_id,entity_id,maintenance_order_id,work_center_id,employee_id,labour_category,
                charge_date,regular_hours,overtime_hours,regular_rate,overtime_rate,burden_pct,regular_cost,overtime_cost,burden_cost,total_cost,created_by)
                VALUES(:id,:o,:e,:mo,:w,:emp,:cat,:d,:rh,:oh,:rr,:orate,:bp,:rc,:oc,:bc,:tc,:u)'''), {
                'id': cid, 'o': body['organization_id'], 'e': body['entity_id'], 'mo': body['maintenance_order_id'],
                'w': body['work_center_id'], 'emp': body.get('employee_id'), 'cat': body.get('labour_category'),
                'd': body['charge_date'], 'rh': float(regular_hours), 'oh': float(overtime_hours),
                'rr': float(regular_rate), 'orate': float(overtime_rate), 'bp': float(burden_pct),
                'rc': float(regular_cost), 'oc': float(overtime_cost), 'bc': float(burden_cost), 'tc': float(total_cost), 'u': str(u.user_id),
            })
        return {'charge_id': cid, 'regular_cost': float(regular_cost), 'overtime_cost': float(overtime_cost), 'burden_cost': float(burden_cost), 'total_cost': float(total_cost), 'status': 'OPEN'}

    @app.get('/v90ei/maintenance/labour/dashboard')
    def dashboard(request: Request, organization_id: str, entity_id: str, period_start: str | None = None, period_end: str | None = None):
        _perm(engine, request, 'maintenance_labour.view')
        where = 'organization_id=:o AND entity_id=:e'
        params = {'o': organization_id, 'e': entity_id}
        if period_start:
            where += ' AND charge_date>=:ps'; params['ps'] = period_start
        if period_end:
            where += ' AND charge_date<=:pe'; params['pe'] = period_end
        with engine.connect() as c:
            x = c.execute(text(f'''SELECT COUNT(*) charges,
                COALESCE(SUM(regular_hours),0) regular_hours,
                COALESCE(SUM(overtime_hours),0) overtime_hours,
                COALESCE(SUM(regular_cost),0) regular_cost,
                COALESCE(SUM(overtime_cost),0) overtime_cost,
                COALESCE(SUM(burden_cost),0) burden_cost,
                COALESCE(SUM(total_cost),0) total_cost
                FROM maintenance_labour_charge WHERE {where}'''), params).mappings().first()
            by_order = c.execute(text(f'''SELECT maintenance_order_id,work_center_id,
                COALESCE(SUM(total_cost),0) total_cost,
                COALESCE(SUM(regular_hours+overtime_hours),0) total_hours,
                COALESCE(SUM(overtime_hours),0) overtime_hours
                FROM maintenance_labour_charge WHERE {where}
                GROUP BY maintenance_order_id,work_center_id ORDER BY total_cost DESC'''), params).mappings().all()
        result = {k: (int(x[k] or 0) if k == 'charges' else float(x[k] or 0)) for k in x}
        result['overtime_share_pct'] = float(_n((Decimal(str(x['overtime_hours'] or 0)) / Decimal(str((x['regular_hours'] or 0) + (x['overtime_hours'] or 0))) * 100) if (x['regular_hours'] or 0) + (x['overtime_hours'] or 0) else 0))
        result['by_order'] = [dict(r) for r in by_order]
        return result

    @app.post('/v90ei/maintenance/labour/{period_start}/{period_end}/close')
    def close(period_start: str, period_end: str, body: dict, request: Request):
        u = _perm(engine, request, 'maintenance_labour.close')
        for k in ('organization_id', 'entity_id'):
            if not str(body.get(k) or '').strip():
                raise HTTPException(400, f'{k} is required')
        with engine.begin() as c:
            c.execute(text('''INSERT INTO maintenance_labour_close(close_id,organization_id,entity_id,period_start,period_end,closed_by)
                VALUES(:id,:o,:e,:ps,:pe,:u)
                ON CONFLICT(organization_id,entity_id,period_start,period_end)
                DO UPDATE SET status='CLOSED',closed_by=:u,closed_at=CURRENT_TIMESTAMP'''), {
                    'id': str(uuid4()), 'o': body['organization_id'], 'e': body['entity_id'],
                    'ps': period_start, 'pe': period_end, 'u': str(u.user_id)
                })
            c.execute(text('''UPDATE maintenance_labour_charge SET status='CLOSED'
                              WHERE organization_id=:o AND entity_id=:e AND charge_date BETWEEN :ps AND :pe'''), {
                'o': body['organization_id'], 'e': body['entity_id'], 'ps': period_start, 'pe': period_end
            })
        return {'period_start': period_start, 'period_end': period_end, 'status': 'CLOSED'}

    @app.get('/ui/maintenance-labour')
    def page():
        return FileResponse(Path(__file__).resolve().parents[1] / 'web' / 'maintenance-labour.html')

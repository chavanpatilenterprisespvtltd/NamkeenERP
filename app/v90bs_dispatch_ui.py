from __future__ import annotations
import json
from pathlib import Path
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import Engine, inspect, text
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed

WEB_ROOT = Path(__file__).resolve().parents[1] / 'web'


def _has(engine: Engine, table: str) -> bool:
    return inspect(engine).has_table(table)


def _require(engine: Engine, request: Request, entity_id: UUID, location_id: UUID, write: bool = False):
    user = authenticate(request)
    perms = permissions_for_user(engine, user.user_id)
    if write:
        needed = ('dispatch_mis.edit', 'pod.edit')
    else:
        needed = ('dispatch_mis.view',)
    if not any(p in perms for p in needed):
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, str(entity_id), str(location_id))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def ensure_v90bs_schema(engine: Engine) -> None:
    ddl = '''
    CREATE TABLE IF NOT EXISTS ui_dispatch_preferences (
        preference_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        screen_key TEXT NOT NULL,
        filters TEXT NOT NULL DEFAULT '{}',
        columns TEXT NOT NULL DEFAULT '[]',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, screen_key)
    )'''
    with engine.begin() as c:
        c.execute(text(ddl))
        perms = {
            'dispatch_ui.view': 'View dispatch operational UI',
            'dispatch_ui.manage': 'Manage dispatch operational UI preferences',
        }
        for pid, name in perms.items():
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {'p': pid, 'n': name})
        for role in ('super_admin', 'manager', 'mis', 'salesperson', 'dispatch', 'warehouse', 'accounts'):
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'dispatch_ui.view') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r': role})
        for role in ('super_admin', 'manager', 'mis'):
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'dispatch_ui.manage') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r': role})


def register_v90bs_routes(app: FastAPI, engine: Engine) -> None:
    ensure_v90bs_schema(engine)

    @app.get('/v90bs/dispatch/summary')
    def summary(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID):
        _require(engine, request, entity_id, location_id)
        p = {'o': str(organization_id), 'e': str(entity_id), 'l': str(location_id)}
        out = {'dispatches': 0, 'draft': 0, 'posted': 0, 'assigned': 0, 'delivered': 0, 'open_backorders': 0, 'pending_pod': 0, 'dispatched_qty': 0.0}
        with engine.connect() as c:
            if _has(engine, 'dispatches'):
                row = c.execute(text("SELECT COUNT(*) dispatches, SUM(CASE WHEN status='DRAFT' THEN 1 ELSE 0 END) draft, SUM(CASE WHEN status='POSTED' THEN 1 ELSE 0 END) posted FROM dispatches WHERE organization_id=:o AND entity_id=:e AND location_id=:l"), p).mappings().one()
                out.update({k: int(row[k] or 0) for k in ('dispatches','draft','posted')})
            if _has(engine, 'dispatch_delivery_assignments'):
                out['assigned'] = int(c.execute(text("SELECT COUNT(*) FROM dispatch_delivery_assignments a JOIN dispatches d ON d.dispatch_id=a.dispatch_id WHERE d.organization_id=:o AND d.entity_id=:e AND d.location_id=:l"), p).scalar_one() or 0)
            if _has(engine, 'dispatch_pod'):
                out['delivered'] = int(c.execute(text("SELECT COUNT(*) FROM dispatch_pod WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND status='DELIVERED'"), p).scalar_one() or 0)
                out['pending_pod'] = int(c.execute(text("SELECT COUNT(*) FROM dispatch_pod WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND status='PENDING'"), p).scalar_one() or 0)
            if _has(engine, 'sales_order_backorders'):
                out['open_backorders'] = int(c.execute(text("SELECT COUNT(*) FROM sales_order_backorders WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND status='OPEN'"), p).scalar_one() or 0)
            if _has(engine, 'dispatch_lines') and _has(engine, 'dispatches'):
                out['dispatched_qty'] = float(c.execute(text("SELECT COALESCE(SUM(dl.dispatched_qty),0) FROM dispatch_lines dl JOIN dispatches d ON d.dispatch_id=dl.dispatch_id WHERE d.organization_id=:o AND d.entity_id=:e AND d.location_id=:l AND d.status='POSTED'"), p).scalar_one() or 0)
        return {'counts': out}

    @app.get('/v90bs/dispatch/queue')
    def queue(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, status: str | None = None, limit: int = 100):
        _require(engine, request, entity_id, location_id)
        if not _has(engine, 'dispatches'):
            return {'items': [], 'count': 0}
        q = '''SELECT d.dispatch_id,d.dispatch_no,d.sales_order_id,d.warehouse_id,d.status,d.vehicle_no,d.transporter,d.eway_bill_no,d.created_at,d.posted_at,
                       COALESCE(SUM(dl.dispatched_qty),0) dispatched_qty
                FROM dispatches d LEFT JOIN dispatch_lines dl ON dl.dispatch_id=d.dispatch_id
                WHERE d.organization_id=:o AND d.entity_id=:e AND d.location_id=:l'''
        p = {'o': str(organization_id), 'e': str(entity_id), 'l': str(location_id)}
        if status:
            q += ' AND d.status=:s'; p['s'] = status.upper()
        q += ' GROUP BY d.dispatch_id ORDER BY d.created_at DESC LIMIT :lim'; p['lim'] = max(1, min(limit, 200))
        with engine.connect() as c:
            rows = [dict(r) for r in c.execute(text(q), p).mappings().all()]
            for r in rows:
                if _has(engine, 'dispatch_delivery_assignments'):
                    a = c.execute(text('SELECT transporter_name,vehicle_no,driver_name,eway_bill_no,status FROM dispatch_delivery_assignments WHERE dispatch_id=:d'), {'d': r['dispatch_id']}).mappings().first()
                    r['assignment'] = dict(a) if a else None
                if _has(engine, 'dispatch_pod'):
                    pod = c.execute(text('SELECT status,pod_reference,received_by,received_at,captured_at FROM dispatch_pod WHERE dispatch_id=:d ORDER BY captured_at DESC LIMIT 1'), {'d': r['dispatch_id']}).mappings().first()
                    r['pod'] = dict(pod) if pod else None
        return {'items': rows, 'count': len(rows)}

    @app.get('/v90bs/dispatch/backorders')
    def backorders(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, status: str = 'OPEN', limit: int = 100):
        _require(engine, request, entity_id, location_id)
        if not _has(engine, 'sales_order_backorders'):
            return {'items': [], 'count': 0}
        p = {'o': str(organization_id), 'e': str(entity_id), 'l': str(location_id), 's': status.upper(), 'lim': max(1, min(limit, 200))}
        with engine.connect() as c:
            rows = [dict(r) for r in c.execute(text("SELECT * FROM sales_order_backorders WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND status=:s ORDER BY created_at DESC LIMIT :lim"), p).mappings().all()]
        return {'items': rows, 'count': len(rows)}

    @app.get('/v90bs/dispatch/transporters')
    def transporters(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID):
        _require(engine, request, entity_id, location_id)
        if not _has(engine, 'transporters'):
            return {'items': []}
        with engine.connect() as c:
            rows = [dict(r) for r in c.execute(text('SELECT transporter_id,transporter_code,transporter_name,phone,gstin,active FROM transporters WHERE organization_id=:o AND entity_id=:e AND active=1 ORDER BY transporter_name'), {'o':str(organization_id),'e':str(entity_id)}).mappings().all()]
        return {'items': rows}

    @app.get('/v90bs/preferences/{screen_key}')
    def get_preferences(screen_key: str, request: Request):
        user = authenticate(request)
        with engine.connect() as c:
            row = c.execute(text('SELECT filters,columns FROM ui_dispatch_preferences WHERE user_id=:u AND screen_key=:s'), {'u': user.user_id, 's': screen_key}).mappings().first()
        if not row:
            return {'screen_key': screen_key, 'filters': {}, 'columns': []}
        return {'screen_key': screen_key, 'filters': json.loads(row['filters'] or '{}'), 'columns': json.loads(row['columns'] or '[]')}

    @app.put('/v90bs/preferences/{screen_key}')
    def put_preferences(screen_key: str, payload: dict, request: Request):
        user = authenticate(request)
        perms = permissions_for_user(engine, user.user_id)
        if 'dispatch_ui.manage' not in perms and 'transaction_ui.manage' not in perms:
            raise HTTPException(403, 'permission denied')
        filters, columns = payload.get('filters', {}), payload.get('columns', [])
        if not isinstance(filters, dict) or not isinstance(columns, list) or len(columns) > 60:
            raise HTTPException(400, 'invalid preference payload')
        with engine.begin() as c:
            c.execute(text('INSERT INTO ui_dispatch_preferences(preference_id,user_id,screen_key,filters,columns) VALUES(:i,:u,:s,:f,:c) ON CONFLICT(user_id,screen_key) DO UPDATE SET filters=excluded.filters,columns=excluded.columns,updated_at=CURRENT_TIMESTAMP'), {'i': uuid4().hex, 'u': str(user.user_id), 's': screen_key, 'f': json.dumps(filters), 'c': json.dumps(columns)})
        return {'screen_key': screen_key, 'filters': filters, 'columns': columns}

    @app.get('/ui/dispatch')
    def dispatch_page():
        return FileResponse(WEB_ROOT / 'dispatch.html')

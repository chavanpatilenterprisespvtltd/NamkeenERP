from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import Engine, inspect, text

from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed

WEB_ROOT = Path(__file__).resolve().parents[1] / 'web'


def _safe_table(engine: Engine, table: str) -> bool:
    return inspect(engine).has_table(table)


def _require(engine: Engine, request: Request, entity_id: UUID, location_id: UUID, write: bool = False):
    user = authenticate(request)
    perms = permissions_for_user(engine, user.user_id)
    needed = 'sales.edit' if write else 'sales.view'
    alt = 'inventory.edit' if write else 'inventory.view'
    if needed not in perms and alt not in perms:
        raise HTTPException(403, 'permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, str(entity_id), str(location_id))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return user


def ensure_v90bp_schema(engine: Engine) -> None:
    ddl = {
        'postgresql': '''
        CREATE TABLE IF NOT EXISTS ui_packing_sales_preferences (
            preference_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id TEXT NOT NULL,
            screen_key TEXT NOT NULL,
            filters JSONB NOT NULL DEFAULT '{}'::jsonb,
            columns JSONB NOT NULL DEFAULT '[]'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(user_id, screen_key)
        )
        ''',
        'sqlite': '''
        CREATE TABLE IF NOT EXISTS ui_packing_sales_preferences (
            preference_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            screen_key TEXT NOT NULL,
            filters TEXT NOT NULL DEFAULT '{}',
            columns TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, screen_key)
        )
        '''
    }
    with engine.begin() as c:
        c.execute(text(ddl[engine.dialect.name]))
        perms = {
            'packing_sales_ui.view': 'View packing and sales UI screens',
            'packing_sales_ui.manage': 'Manage packing and sales UI preferences',
        }
        for pid, name in perms.items():
            c.execute(text('INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING'), {'p': pid, 'n': name})
        for role in ('manager', 'super_admin', 'mis', 'packing', 'warehouse', 'dispatch', 'salesperson', 'quality', 'production'):
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'packing_sales_ui.view') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r': role})
        for role in ('manager', 'super_admin', 'mis'):
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'packing_sales_ui.manage') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r': role})


def register_v90bp_routes(app: FastAPI, engine: Engine) -> None:
    ensure_v90bp_schema(engine)

    @app.get('/v90bp/packing/summary')
    def packing_summary(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID):
        _require(engine, request, entity_id, location_id)
        p = {'o': str(organization_id), 'e': str(entity_id), 'l': str(location_id)}
        counts = {}
        for table, key, where in [
            ('packing_run', 'packing_runs', 'organization_id=:o AND entity_id=:e AND location_id=:l'),
            ('packed_fg_lot', 'packed_fg_lots', 'organization_id=:o AND entity_id=:e AND location_id=:l'),
            ('packing_qc_inspection', 'qc_inspections', 'organization_id=:o AND entity_id=:e AND location_id=:l'),
        ]:
            counts[key] = 0
            if _safe_table(engine, table):
                with engine.connect() as c:
                    counts[key] = int(c.execute(text(f'SELECT COUNT(*) FROM {table} WHERE {where}'), p).scalar_one() or 0)
        counts['open_packing_runs'] = 0
        counts['qc_holds'] = 0
        if _safe_table(engine, 'packing_run'):
            with engine.connect() as c:
                counts['open_packing_runs'] = int(c.execute(text("SELECT COUNT(*) FROM packing_run WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND status NOT IN ('COMPLETED','CANCELLED')"), p).scalar_one() or 0)
        if _safe_table(engine, 'packing_qc_inspection'):
            with engine.connect() as c:
                counts['qc_holds'] = int(c.execute(text("SELECT COUNT(*) FROM packing_qc_inspection WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND overall_status='HOLD'"), p).scalar_one() or 0)
        return {'counts': counts}

    @app.get('/v90bp/packing/runs')
    def packing_runs(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, status: str | None = None, limit: int = 100):
        _require(engine, request, entity_id, location_id)
        if not _safe_table(engine, 'packing_run'):
            return {'items': [], 'count': 0}
        q = 'SELECT packing_run_id,run_no,source_fg_lot_id,sku_id,source_qty,packed_qty,status,started_at,completed_at,created_at FROM packing_run WHERE organization_id=:o AND entity_id=:e AND location_id=:l'
        p = {'o': str(organization_id), 'e': str(entity_id), 'l': str(location_id)}
        if status:
            q += ' AND status=:s'; p['s'] = status.upper()
        q += ' ORDER BY created_at DESC LIMIT :lim'; p['lim'] = max(1, min(limit, 200))
        with engine.connect() as c:
            rows = [dict(r) for r in c.execute(text(q), p).mappings().all()]
        return {'items': rows, 'count': len(rows)}

    @app.get('/v90bp/packing/lots')
    def packed_lots(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, status: str | None = None, limit: int = 100):
        _require(engine, request, entity_id, location_id)
        if not _safe_table(engine, 'packed_fg_lot'):
            return {'items': [], 'count': 0}
        q = 'SELECT packed_fg_lot_id,lot_code,sku_id,pack_count,net_qty,available_qty,uom,mfg_date,expiry_date,status,qc_status,packing_run_id,created_at FROM packed_fg_lot WHERE organization_id=:o AND entity_id=:e AND location_id=:l'
        p = {'o': str(organization_id), 'e': str(entity_id), 'l': str(location_id)}
        if status:
            q += ' AND status=:s'; p['s'] = status.upper()
        q += ' ORDER BY created_at DESC LIMIT :lim'; p['lim'] = max(1, min(limit, 200))
        with engine.connect() as c:
            rows = [dict(r) for r in c.execute(text(q), p).mappings().all()]
        return {'items': rows, 'count': len(rows)}

    @app.get('/v90bp/packing/qc')
    def packing_qc(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, status: str | None = None, limit: int = 100):
        _require(engine, request, entity_id, location_id)
        if not _safe_table(engine, 'packing_qc_inspection'):
            return {'items': [], 'count': 0}
        q = 'SELECT inspection_id,packing_run_id,packed_fg_lot_id,overall_status,seal_status,label_status,nitrogen_status,visual_status,net_weight_target,net_weight_actual,hold_reason,created_at,released_at FROM packing_qc_inspection WHERE organization_id=:o AND entity_id=:e AND location_id=:l'
        p = {'o': str(organization_id), 'e': str(entity_id), 'l': str(location_id)}
        if status:
            q += ' AND overall_status=:s'; p['s'] = status.upper()
        q += ' ORDER BY created_at DESC LIMIT :lim'; p['lim'] = max(1, min(limit, 200))
        with engine.connect() as c:
            rows = [dict(r) for r in c.execute(text(q), p).mappings().all()]
        return {'items': rows, 'count': len(rows)}

    @app.get('/v90bp/sales/summary')
    def sales_summary(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID):
        _require(engine, request, entity_id, location_id)
        p = {'o': str(organization_id), 'e': str(entity_id), 'l': str(location_id)}
        counts = {'orders': 0, 'draft': 0, 'submitted': 0, 'approved': 0, 'on_hold': 0, 'grand_total': 0.0}
        if _safe_table(engine, 'sales_orders'):
            with engine.connect() as c:
                row = c.execute(text("SELECT COUNT(*) AS orders, COALESCE(SUM(CASE WHEN status='DRAFT' THEN 1 ELSE 0 END),0) AS draft, COALESCE(SUM(CASE WHEN status='SUBMITTED' THEN 1 ELSE 0 END),0) AS submitted, COALESCE(SUM(CASE WHEN status='APPROVED' THEN 1 ELSE 0 END),0) AS approved, COALESCE(SUM(CASE WHEN status='HOLD' THEN 1 ELSE 0 END),0) AS on_hold, COALESCE(SUM(grand_total),0) AS grand_total FROM sales_orders WHERE organization_id=:o AND entity_id=:e AND location_id=:l"), p).mappings().one()
            counts.update({k: float(row[k]) if k == 'grand_total' else int(row[k] or 0) for k in counts})
        return {'counts': counts}

    @app.get('/v90bp/sales/orders')
    def sales_orders(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, status: str | None = None, limit: int = 100):
        _require(engine, request, entity_id, location_id)
        if not _safe_table(engine, 'sales_orders'):
            return {'items': [], 'count': 0}
        q = 'SELECT sales_order_id,order_no,customer_id,warehouse_id,status,pricing_status,credit_status,stock_status,subtotal,discount_total,taxable_value,gst_total,grand_total,created_at,submitted_at,approved_at,hold_reason FROM sales_orders WHERE organization_id=:o AND entity_id=:e AND location_id=:l'
        p = {'o': str(organization_id), 'e': str(entity_id), 'l': str(location_id)}
        if status:
            q += ' AND status=:s'; p['s'] = status.upper()
        q += ' ORDER BY created_at DESC LIMIT :lim'; p['lim'] = max(1, min(limit, 200))
        with engine.connect() as c:
            rows = [dict(r) for r in c.execute(text(q), p).mappings().all()]
        return {'items': rows, 'count': len(rows)}

    @app.get('/v90bp/sales/customers')
    def customers(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, q: str = '', limit: int = 100):
        _require(engine, request, entity_id, location_id)
        if not _safe_table(engine, 'master_record'):
            return {'items': [], 'count': 0}
        sql = "SELECT master_id,version_no,active,data FROM master_record WHERE organization_id=:o AND master_type='CUSTOMER' AND (entity_id=:e OR entity_id IS NULL)"
        p = {'o': str(organization_id), 'e': str(entity_id)}
        sql += ' ORDER BY active DESC, version_no DESC LIMIT :lim'; p['lim'] = max(1, min(limit, 200))
        with engine.connect() as c:
            rows = c.execute(text(sql), p).mappings().all()
        items=[]
        for r in rows:
            data=r['data'] if isinstance(r['data'], dict) else json.loads(r['data'] or '{}')
            hay=' '.join(str(data.get(k,'')) for k in ('code','name','legal_name','display_name','phone','email')).lower()
            if q and q.lower() not in hay:
                continue
            items.append({'customer_id': str(r['master_id']), 'version_no': r['version_no'], 'active': bool(r['active']), **data})
        return {'items': items[:max(1,min(limit,200))], 'count': len(items[:max(1,min(limit,200))])}

    @app.get('/v90bp/preferences/{screen_key}')
    def get_preferences(screen_key: str, request: Request):
        user = authenticate(request)
        with engine.connect() as c:
            row = c.execute(text('SELECT filters,columns FROM ui_packing_sales_preferences WHERE user_id=:u AND screen_key=:s'), {'u': user.user_id, 's': screen_key}).mappings().first()
        if not row:
            return {'screen_key': screen_key, 'filters': {}, 'columns': []}
        filters = row['filters'] if isinstance(row['filters'], dict) else json.loads(row['filters'] or '{}')
        columns = row['columns'] if isinstance(row['columns'], list) else json.loads(row['columns'] or '[]')
        return {'screen_key': screen_key, 'filters': filters, 'columns': columns}

    @app.put('/v90bp/preferences/{screen_key}')
    def put_preferences(screen_key: str, payload: dict[str, Any], request: Request):
        user = authenticate(request)
        if 'packing_sales_ui.manage' not in permissions_for_user(engine, user.user_id) and 'transaction_ui.manage' not in permissions_for_user(engine, user.user_id):
            raise HTTPException(403, 'permission denied')
        filters, columns = payload.get('filters', {}), payload.get('columns', [])
        if not isinstance(filters, dict) or not isinstance(columns, list) or len(columns) > 60:
            raise HTTPException(400, 'invalid preference payload')
        if engine.dialect.name == 'postgresql':
            sql = '''INSERT INTO ui_packing_sales_preferences(preference_id,user_id,screen_key,filters,columns) VALUES(gen_random_uuid(),:u,:s,CAST(:f AS jsonb),CAST(:c AS jsonb)) ON CONFLICT(user_id,screen_key) DO UPDATE SET filters=EXCLUDED.filters,columns=EXCLUDED.columns,updated_at=now()'''
            params = {'u': user.user_id, 's': screen_key, 'f': json.dumps(filters), 'c': json.dumps(columns)}
        else:
            sql = '''INSERT INTO ui_packing_sales_preferences(preference_id,user_id,screen_key,filters,columns) VALUES(:id,:u,:s,:f,:c) ON CONFLICT(user_id,screen_key) DO UPDATE SET filters=excluded.filters,columns=excluded.columns,updated_at=CURRENT_TIMESTAMP'''
            params = {'id': uuid4().hex, 'u': user.user_id, 's': screen_key, 'f': json.dumps(filters), 'c': json.dumps(columns)}
        with engine.begin() as c:
            c.execute(text(sql), params)
        return {'screen_key': screen_key, 'filters': filters, 'columns': columns}

    @app.get('/ui/packing')
    def packing_page(): return FileResponse(WEB_ROOT / 'packing.html')

    @app.get('/ui/sales')
    def sales_page(): return FileResponse(WEB_ROOT / 'sales.html')

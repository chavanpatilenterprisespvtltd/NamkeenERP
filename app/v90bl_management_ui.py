from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import Engine, text, inspect
from .auth import authenticate
from .identity import permissions_for_user, roles_for_user
from .release import load_release_info

WEB_ROOT = Path(__file__).resolve().parents[1] / 'web'

def _require(engine: Engine, request: Request, permission: str):
    user = authenticate(request)
    if permission not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, 'permission denied')
    return user

def _table_exists(engine: Engine, name: str) -> bool:
    return inspect(engine).has_table(name)

def _count(conn, table: str, where: str = '', params: dict | None = None) -> int:
    if not _table_exists(conn.engine, table): return 0
    sql = f'SELECT COUNT(*) FROM {table}' + (f' WHERE {where}' if where else '')
    return int(conn.execute(text(sql), params or {}).scalar_one() or 0)

def ensure_management_ui_schema(engine: Engine) -> None:
    ddl = {
      'postgresql': """CREATE TABLE IF NOT EXISTS ui_notification_reads (user_id TEXT NOT NULL, notification_id TEXT NOT NULL, read_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(user_id,notification_id));""",
      'sqlite': """CREATE TABLE IF NOT EXISTS ui_notification_reads (user_id TEXT NOT NULL, notification_id TEXT NOT NULL, read_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(user_id,notification_id));""",
    }
    with engine.begin() as c:
        c.execute(text(ddl[engine.dialect.name]))
        perms = {'management.ui.view':'View management UI','management.ui.manage':'Manage management UI preferences'}
        for p,n in perms.items():
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {'p':p,'n':n})
        for role in ('manager','super_admin','mis'):
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'management.ui.view') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role})
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'management.ui.manage') ON CONFLICT(role_id,permission_id) DO NOTHING"), {'r':role})

def register_v90bl_routes(app: FastAPI, engine: Engine) -> None:
    ensure_management_ui_schema(engine)

    @app.get('/v90bl/management-summary')
    def management_summary(request: Request):
        user = _require(engine, request, 'management.ui.view')
        with engine.connect() as c:
            def safe(table, where=''):
                return _count(c, table, where)
            return {
                'release': load_release_info().version,
                'role': (roles_for_user(engine,user.user_id) or [user.role])[0],
                'metrics': {
                    'sales_orders': safe('sales_orders'),
                    'open_sales_orders': safe('sales_orders', "status IN ('APPROVED','PARTIALLY_DISPATCHED','OPEN')"),
                    'pending_dispatch': safe('dispatch_shipments', "status IN ('READY','PENDING','DISPATCHED')"),
                    'production_batches': safe('production_batches'),
                    'inventory_lots': safe('inventory_lots'),
                    'pending_approvals': safe('approval_requests', "status='PENDING'"),
                    'pending_notifications': safe('notifications', "status IN ('PENDING','SCHEDULED')"),
                    'open_returns': safe('sales_returns', "status NOT IN ('CLOSED','CANCELLED')"),
                },
                'generated_at': datetime.now(timezone.utc).isoformat(),
            }

    @app.get('/v90bl/approval-inbox')
    def approval_inbox(request: Request, status: str='PENDING', limit: int=25):
        user = _require(engine, request, 'management.ui.view')
        limit = max(1,min(limit,100)); status = status.upper()
        if not _table_exists(engine,'approval_requests'): return {'approvals':[]}
        with engine.connect() as c:
            rows = c.execute(text('''SELECT ar.approval_request_id, ar.subject_type, ar.subject_id, ar.status, ar.requested_by, ar.requested_at, aw.workflow_code, aw.workflow_name FROM approval_requests ar JOIN approval_workflows aw ON aw.workflow_id=ar.workflow_id WHERE ar.status=:s ORDER BY ar.requested_at ASC LIMIT :lim'''), {'s':status,'lim':limit}).mappings().all()
        return {'approvals':[dict(r) for r in rows], 'count':len(rows), 'user_id':user.user_id}

    @app.get('/v90bl/notification-center')
    def notification_center(request: Request, status: str|None=None, limit: int=50):
        user = _require(engine, request, 'management.ui.view')
        limit=max(1,min(limit,100))
        if not _table_exists(engine,'notifications'): return {'notifications':[],'unread':0}
        sql='''SELECT n.notification_id,n.channel,n.subject,n.body,n.status,n.related_type,n.related_id,n.created_at, CASE WHEN r.user_id IS NULL THEN 0 ELSE 1 END AS is_read FROM notifications n LEFT JOIN ui_notification_reads r ON r.notification_id=n.notification_id AND r.user_id=:u WHERE (n.recipient_user_id=:u OR n.recipient_user_id IS NULL)'''
        params={'u':user.user_id}
        if status: sql += ' AND n.status=:s'; params['s']=status.upper()
        sql += ' ORDER BY n.created_at DESC LIMIT :lim'; params['lim']=limit
        with engine.connect() as c:
            rows=[dict(r) for r in c.execute(text(sql),params).mappings().all()]
        return {'notifications':rows,'unread':sum(1 for r in rows if not r['is_read'])}

    @app.post('/v90bl/notifications/{notification_id}/read')
    def mark_read(notification_id: str, request: Request):
        user = _require(engine, request, 'management.ui.view')
        if not _table_exists(engine,'notifications'):
            return {'notification_id':notification_id,'status':'READ'}
        with engine.begin() as c:
            exists=c.execute(text('SELECT 1 FROM notifications WHERE notification_id=:i AND (recipient_user_id=:u OR recipient_user_id IS NULL)'), {'i':notification_id,'u':user.user_id}).scalar()
            if not exists: raise HTTPException(404,'notification not found')
            c.execute(text('INSERT INTO ui_notification_reads(user_id,notification_id) VALUES(:u,:i) ON CONFLICT(user_id,notification_id) DO UPDATE SET read_at=CURRENT_TIMESTAMP'), {'u':user.user_id,'i':notification_id})
        return {'notification_id':notification_id,'status':'READ'}

    @app.get('/ui/management')
    def management_page(): return FileResponse(WEB_ROOT/'management.html')
    @app.get('/ui/approvals')
    def approvals_page(): return FileResponse(WEB_ROOT/'management.html')
    @app.get('/ui/notifications')
    def notifications_page(): return FileResponse(WEB_ROOT/'management.html')

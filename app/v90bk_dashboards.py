from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import Engine, text

from .auth import authenticate
from .identity import permissions_for_user, roles_for_user
from .release import load_release_info


def _require(engine: Engine, request: Request, permission: str):
    user = authenticate(request)
    if permission not in permissions_for_user(engine, user.user_id):
        raise HTTPException(status_code=403, detail="permission denied")
    return user


WEB_SCREENS = [
    ("management", "Management Dashboard", "/ui/management", ["manager", "super_admin", "mis"]),
    ("approval_inbox", "Approval Inbox", "/ui/approvals", ["manager", "super_admin"]),
    ("notifications", "Notifications Center", "/ui/notifications", ["manager", "super_admin", "mis"]),
    ("product_master", "Product Master", "/ui/products", ["manager", "super_admin", "mis"]),
    ("procurement", "Procurement", "/ui/procurement", ["manager", "super_admin"]),
    ("inventory", "Inventory", "/ui/inventory", ["manager", "super_admin", "warehouse", "production"]),
    ("production", "Production", "/ui/production", ["manager", "super_admin", "production"]),
    ("packing", "Packing", "/ui/packing", ["manager", "super_admin", "production"]),
    ("sales", "Sales", "/ui/sales", ["manager", "super_admin", "salesperson", "mis"]),
    ("collections", "Payments & Collections", "/ui/collections", ["manager", "super_admin", "salesperson"]),
    ("dispatch", "Dispatch", "/ui/dispatch", ["manager", "super_admin", "dispatch", "warehouse"]),
    ("returns", "Sales Returns", "/ui/returns", ["manager", "super_admin", "warehouse"]),
    ("receivables", "Receivables", "/ui/receivables", ["manager", "super_admin", "mis"]),
    ("factory_home", "Factory Home", "/ui/factory", ["manager", "super_admin", "production", "quality", "warehouse", "dispatch"]),
    ("salesperson_home", "Salesperson Home", "/ui/salesperson", ["salesperson", "manager", "super_admin"]),
]

ROLE_WIDGETS = {
    "manager": ["kpi_sales", "kpi_collection", "kpi_inventory", "kpi_production", "alerts_approvals"],
    "super_admin": ["kpi_sales", "kpi_collection", "kpi_inventory", "kpi_production", "alerts_approvals", "security_status"],
    "mis": ["kpi_sales", "kpi_collection", "kpi_inventory", "kpi_production", "alerts_returns"],
    "production": ["production_today", "yield_today", "qc_holds", "rework_open"],
    "quality": ["qc_holds", "returns_damage", "expiry_exposure"],
    "warehouse": ["stock_value", "slow_moving", "dispatch_queue", "recall_alerts"],
    "dispatch": ["dispatch_queue", "backorders", "pod_pending", "transporter_activity"],
    "salesperson": ["orders_today", "collections_due", "customer_followups", "incentive_accrual"],
    "operator": ["production_today", "qc_holds"],
}


def ensure_dashboard_schema(engine: Engine) -> None:
    ddl = {
        "postgresql": """
        CREATE TABLE IF NOT EXISTS ui_screen_catalog (
            screen_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            route TEXT NOT NULL,
            role_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS ui_dashboard_preferences (
            preference_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id TEXT NOT NULL,
            dashboard_key TEXT NOT NULL,
            widgets JSONB NOT NULL DEFAULT '[]'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(user_id, dashboard_key)
        );
        """,
        "sqlite": """
        CREATE TABLE IF NOT EXISTS ui_screen_catalog (
            screen_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            route TEXT NOT NULL,
            role_ids TEXT NOT NULL DEFAULT '[]',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS ui_dashboard_preferences (
            preference_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            dashboard_key TEXT NOT NULL,
            widgets TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, dashboard_key)
        );
        """,
    }
    with engine.begin() as conn:
        conn.execute(text(ddl[engine.dialect.name].split(";")[0]))
        # SQLite executes one statement at a time; Postgres accepts the first only above.
        if engine.dialect.name == "postgresql":
            conn.execute(text(ddl["postgresql"].split(";")[1] + ";"))
        else:
            conn.execute(text(ddl["sqlite"].split(";")[1]))
        conn.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {"p":"screen.view","n":"View role-specific ERP screens"})
        conn.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {"p":"dashboard.manage","n":"Manage personal dashboard layout"})
        for role in ROLE_WIDGETS:
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'screen.view') ON CONFLICT(role_id,permission_id) DO NOTHING"), {"r": role})
        for role in ("manager", "super_admin", "mis"):
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'dashboard.manage') ON CONFLICT(role_id,permission_id) DO NOTHING"), {"r": role})
        for sid, title, route, roles in WEB_SCREENS:
            role_json = json.dumps(roles, separators=(",", ":"))
            if engine.dialect.name == "postgresql":
                conn.execute(text("INSERT INTO ui_screen_catalog(screen_id,title,route,role_ids) VALUES(:id,:t,:r,CAST(:roles AS jsonb)) ON CONFLICT(screen_id) DO UPDATE SET title=EXCLUDED.title,route=EXCLUDED.route,role_ids=EXCLUDED.role_ids"), {"id": sid, "t": title, "r": route, "roles": role_json})
            else:
                conn.execute(text("INSERT INTO ui_screen_catalog(screen_id,title,route,role_ids) VALUES(:id,:t,:r,:roles) ON CONFLICT(screen_id) DO UPDATE SET title=excluded.title,route=excluded.route,role_ids=excluded.role_ids"), {"id": sid, "t": title, "r": route, "roles": role_json})


def register_v90bk_routes(app: FastAPI, engine: Engine) -> None:
    ensure_dashboard_schema(engine)

    @app.get("/v90bk/screens")
    def screens(request: Request):
        user = _require(engine, request, "screen.view")
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT screen_id,title,route,role_ids,active FROM ui_screen_catalog WHERE active=1 ORDER BY screen_id")).mappings().all()
        roles_for_current_user = roles_for_user(engine, user.user_id)
        role = roles_for_current_user[0] if roles_for_current_user else user.role
        result = []
        for r in rows:
            roles = r["role_ids"] if isinstance(r["role_ids"], list) else json.loads(r["role_ids"] or "[]")
            if role in roles:
                result.append({"screen_id": r["screen_id"], "title": r["title"], "route": r["route"]})
        return {"role": role, "screens": result}

    @app.get("/v90bk/dashboard")
    def dashboard(request: Request, dashboard_key: str = "home"):
        user = _require(engine, request, "screen.view")
        role_list = roles_for_user(engine, user.user_id)
        role = role_list[0] if role_list else user.role
        with engine.connect() as conn:
            pref = conn.execute(text("SELECT widgets FROM ui_dashboard_preferences WHERE user_id=:u AND dashboard_key=:d"), {"u": user.user_id, "d": dashboard_key}).scalar()
        widgets = json.loads(pref) if pref else ROLE_WIDGETS.get(role, ROLE_WIDGETS["operator"])
        return {"dashboard_key": dashboard_key, "role": role, "widgets": widgets, "release": load_release_info().version}

    @app.put("/v90bk/dashboard")
    def update_dashboard(payload: dict[str, Any], request: Request):
        user = _require(engine, request, "dashboard.manage")
        dashboard_key = str(payload.get("dashboard_key", "home")).strip() or "home"
        widgets = payload.get("widgets")
        if not isinstance(widgets, list) or len(widgets) > 25 or not all(isinstance(w, str) and w.strip() for w in widgets):
            raise HTTPException(status_code=400, detail="widgets must be a list of non-empty strings (max 25)")
        with engine.begin() as conn:
            if engine.dialect.name == "postgresql":
                conn.execute(text("INSERT INTO ui_dashboard_preferences(preference_id,user_id,dashboard_key,widgets) VALUES(gen_random_uuid(),:u,:d,CAST(:w AS jsonb)) ON CONFLICT(user_id,dashboard_key) DO UPDATE SET widgets=EXCLUDED.widgets,updated_at=now()"), {"u": user.user_id, "d": dashboard_key, "w": json.dumps(widgets)})
            else:
                conn.execute(text("INSERT INTO ui_dashboard_preferences(preference_id,user_id,dashboard_key,widgets) VALUES(:id,:u,:d,:w) ON CONFLICT(user_id,dashboard_key) DO UPDATE SET widgets=excluded.widgets,updated_at=CURRENT_TIMESTAMP"), {"id": __import__('uuid').uuid4().hex, "u": user.user_id, "d": dashboard_key, "w": json.dumps(widgets)})
        return {"dashboard_key": dashboard_key, "widgets": widgets, "updated_by": user.username, "updated_at": datetime.now(timezone.utc).isoformat()}

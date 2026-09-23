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

WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


def _require(engine: Engine, request: Request, entity_id: UUID | None = None, location_id: UUID | None = None, write: bool = False):
    user = authenticate(request)
    permission = "inventory_ui.manage" if write else "inventory_ui.view"
    if permission not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, "permission denied")
    if entity_id:
        try:
            assert_entity_location_allowed(engine, user.user_id, str(entity_id), str(location_id) if location_id else None)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
    return user


def _safe_table(engine: Engine, table: str) -> bool:
    return inspect(engine).has_table(table)


def ensure_inventory_ui_schema(engine: Engine) -> None:
    if engine.dialect.name == "postgresql":
        ddl = """
        CREATE TABLE IF NOT EXISTS ui_inventory_preferences (
            preference_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id TEXT NOT NULL,
            screen_key TEXT NOT NULL,
            filters JSONB NOT NULL DEFAULT '{}'::jsonb,
            columns JSONB NOT NULL DEFAULT '[]'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(user_id, screen_key)
        )
        """
    else:
        ddl = """
        CREATE TABLE IF NOT EXISTS ui_inventory_preferences (
            preference_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            screen_key TEXT NOT NULL,
            filters TEXT NOT NULL DEFAULT '{}',
            columns TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, screen_key)
        )
        """
    with engine.begin() as conn:
        conn.execute(text(ddl))
        perms = {
            "inventory_ui.view": "View GRN, QC and inventory UI screens",
            "inventory_ui.manage": "Manage GRN, QC and inventory UI preferences",
        }
        for pid, name in perms.items():
            conn.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {"p": pid, "n": name})
        for role in ("manager", "super_admin", "mis", "purchase", "warehouse", "quality", "production", "dispatch"):
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'inventory_ui.view') ON CONFLICT(role_id,permission_id) DO NOTHING"), {"r": role})
        for role in ("manager", "super_admin", "purchase", "warehouse", "quality"):
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'inventory_ui.manage') ON CONFLICT(role_id,permission_id) DO NOTHING"), {"r": role})


def _counts(engine: Engine, organization_id: UUID, entity_id: UUID, location_id: UUID) -> dict[str, int]:
    out: dict[str, int] = {}
    if _safe_table(engine, "inventory_grn"):
        with engine.connect() as c:
            out["grn"] = int(c.execute(text("SELECT COUNT(*) FROM inventory_grn WHERE organization_id=:o AND entity_id=:e AND location_id=:l"), {"o": str(organization_id), "e": str(entity_id), "l": str(location_id)}).scalar_one() or 0)
    else:
        out["grn"] = 0
    if _safe_table(engine, "inventory_grn_line"):
        with engine.connect() as c:
            out["grn_lines_pending_qc"] = int(c.execute(text("SELECT COUNT(*) FROM inventory_grn_line gl JOIN inventory_grn g ON g.grn_id=gl.grn_id WHERE g.organization_id=:o AND g.entity_id=:e AND g.location_id=:l AND gl.qc_status='PENDING'"), {"o": str(organization_id), "e": str(entity_id), "l": str(location_id)}).scalar_one() or 0)
    else:
        out["grn_lines_pending_qc"] = 0
    if _safe_table(engine, "inventory_lot"):
        with engine.connect() as c:
            out["lots"] = int(c.execute(text("SELECT COUNT(*) FROM inventory_lot WHERE organization_id=:o AND entity_id=:e AND location_id=:l"), {"o": str(organization_id), "e": str(entity_id), "l": str(location_id)}).scalar_one() or 0)
            out["quarantine_lots"] = int(c.execute(text("SELECT COUNT(*) FROM inventory_lot WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND status='QUARANTINE'"), {"o": str(organization_id), "e": str(entity_id), "l": str(location_id)}).scalar_one() or 0)
            out["expired_lots"] = int(c.execute(text("SELECT COUNT(*) FROM inventory_lot WHERE organization_id=:o AND entity_id=:e AND location_id=:l AND expiry_date IS NOT NULL AND expiry_date < CURRENT_DATE"), {"o": str(organization_id), "e": str(entity_id), "l": str(location_id)}).scalar_one() or 0)
    else:
        out.update({"lots": 0, "quarantine_lots": 0, "expired_lots": 0})
    if _safe_table(engine, "inventory_transfer"):
        with engine.connect() as c:
            out["open_transfers"] = int(c.execute(text("SELECT COUNT(*) FROM inventory_transfer WHERE organization_id=:o AND entity_id=:e AND (from_location_id=:l OR to_location_id=:l) AND status='DRAFT'"), {"o": str(organization_id), "e": str(entity_id), "l": str(location_id)}).scalar_one() or 0)
    else:
        out["open_transfers"] = 0
    return out


def register_v90bn_routes(app: FastAPI, engine: Engine) -> None:
    ensure_inventory_ui_schema(engine)

    @app.get("/v90bn/inventory/summary")
    def inventory_summary(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID):
        _require(engine, request, entity_id, location_id)
        return {"counts": _counts(engine, organization_id, entity_id, location_id)}

    @app.get("/v90bn/grn")
    def grn_list(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, status: str | None = None, limit: int = 100):
        _require(engine, request, entity_id, location_id)
        if not _safe_table(engine, "inventory_grn"):
            return {"items": [], "count": 0}
        sql = "SELECT grn_id,grn_no,supplier_id,received_at,status,warehouse_id,po_id,notes FROM inventory_grn WHERE organization_id=:o AND entity_id=:e AND location_id=:l"
        p: dict[str, Any] = {"o": str(organization_id), "e": str(entity_id), "l": str(location_id)}
        if status:
            sql += " AND status=:s"; p["s"] = status.upper()
        sql += " ORDER BY received_at DESC, created_at DESC LIMIT :lim"; p["lim"] = max(1, min(limit, 200))
        with engine.connect() as c:
            rows = [dict(x) for x in c.execute(text(sql), p).mappings().all()]
        return {"items": rows, "count": len(rows)}

    @app.get("/v90bn/qc")
    def qc_list(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, status: str | None = None, limit: int = 100):
        _require(engine, request, entity_id, location_id)
        if not _safe_table(engine, "inventory_qc_result"):
            return {"items": [], "count": 0}
        sql = """SELECT q.qc_id,q.inspection_no,q.status,q.tested_qty,q.accepted_qty,q.rejected_qty,q.reason,q.remarks,q.inspected_at,
                         g.grn_no,gl.line_no,gl.item_master_id
                  FROM inventory_qc_result q
                  JOIN inventory_grn g ON g.grn_id=q.grn_id
                  JOIN inventory_grn_line gl ON gl.grn_line_id=q.grn_line_id
                  WHERE g.organization_id=:o AND g.entity_id=:e AND g.location_id=:l"""
        p: dict[str, Any] = {"o": str(organization_id), "e": str(entity_id), "l": str(location_id)}
        if status:
            sql += " AND q.status=:s"; p["s"] = status.upper()
        sql += " ORDER BY q.inspected_at DESC LIMIT :lim"; p["lim"] = max(1, min(limit, 200))
        with engine.connect() as c:
            rows = [dict(x) for x in c.execute(text(sql), p).mappings().all()]
        return {"items": rows, "count": len(rows)}

    @app.get("/v90bn/lots")
    def lots_list(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, warehouse_id: UUID | None = None, qc_status: str | None = None, limit: int = 100):
        _require(engine, request, entity_id, location_id)
        if not _safe_table(engine, "inventory_lot"):
            return {"items": [], "count": 0}
        sql = "SELECT lot_id,lot_code,item_master_id,warehouse_id,received_qty,accepted_qty,available_qty,uom,qc_status,status,mfg_date,expiry_date,supplier_lot_no,created_at FROM inventory_lot WHERE organization_id=:o AND entity_id=:e AND location_id=:l"
        p: dict[str, Any] = {"o": str(organization_id), "e": str(entity_id), "l": str(location_id)}
        if warehouse_id:
            sql += " AND warehouse_id=:w"; p["w"] = str(warehouse_id)
        if qc_status:
            sql += " AND qc_status=:q"; p["q"] = qc_status.upper()
        sql += " ORDER BY CASE WHEN expiry_date IS NULL THEN 1 ELSE 0 END, expiry_date, created_at LIMIT :lim"; p["lim"] = max(1, min(limit, 200))
        with engine.connect() as c:
            rows = [dict(x) for x in c.execute(text(sql), p).mappings().all()]
        return {"items": rows, "count": len(rows)}

    @app.get("/v90bn/ledger")
    def ledger_list(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, warehouse_id: UUID | None = None, movement_type: str | None = None, limit: int = 200):
        _require(engine, request, entity_id, location_id)
        if not _safe_table(engine, "inventory_stock_ledger"):
            return {"items": [], "count": 0}
        sql = "SELECT movement_id,warehouse_id,item_master_id,lot_id,movement_type,quantity,uom,reference_type,reference_id,status,created_by,created_at FROM inventory_stock_ledger WHERE organization_id=:o AND entity_id=:e AND location_id=:l"
        p: dict[str, Any] = {"o": str(organization_id), "e": str(entity_id), "l": str(location_id)}
        if warehouse_id:
            sql += " AND warehouse_id=:w"; p["w"] = str(warehouse_id)
        if movement_type:
            sql += " AND movement_type=:m"; p["m"] = movement_type.upper()
        sql += " ORDER BY created_at DESC LIMIT :lim"; p["lim"] = max(1, min(limit, 500))
        with engine.connect() as c:
            rows = [dict(x) for x in c.execute(text(sql), p).mappings().all()]
        return {"items": rows, "count": len(rows)}

    @app.get("/v90bn/transfers")
    def transfers_list(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, status: str | None = None, limit: int = 100):
        _require(engine, request, entity_id, location_id)
        if not _safe_table(engine, "inventory_transfer"):
            return {"items": [], "count": 0}
        sql = "SELECT transfer_id,from_location_id,from_warehouse_id,to_location_id,to_warehouse_id,status,notes,created_by,created_at,posted_at FROM inventory_transfer WHERE organization_id=:o AND entity_id=:e AND (from_location_id=:l OR to_location_id=:l)"
        p: dict[str, Any] = {"o": str(organization_id), "e": str(entity_id), "l": str(location_id)}
        if status:
            sql += " AND status=:s"; p["s"] = status.upper()
        sql += " ORDER BY created_at DESC LIMIT :lim"; p["lim"] = max(1, min(limit, 200))
        with engine.connect() as c:
            rows = [dict(x) for x in c.execute(text(sql), p).mappings().all()]
        return {"items": rows, "count": len(rows)}

    @app.get("/v90bn/preferences/{screen_key}")
    def preferences(screen_key: str, request: Request):
        user = _require(engine, request)
        with engine.connect() as c:
            row = c.execute(text("SELECT filters,columns FROM ui_inventory_preferences WHERE user_id=:u AND screen_key=:s"), {"u": str(user.user_id), "s": screen_key}).mappings().first()
        if not row:
            return {"screen_key": screen_key, "filters": {}, "columns": []}
        filters = row["filters"] if isinstance(row["filters"], dict) else json.loads(row["filters"] or "{}")
        columns = row["columns"] if isinstance(row["columns"], list) else json.loads(row["columns"] or "[]")
        return {"screen_key": screen_key, "filters": filters, "columns": columns}

    @app.put("/v90bn/preferences/{screen_key}")
    def save_preferences(screen_key: str, payload: dict[str, Any], request: Request):
        user = _require(engine, request, write=True)
        filters = payload.get("filters", {})
        columns = payload.get("columns", [])
        if not isinstance(filters, dict) or not isinstance(columns, list) or len(columns) > 50:
            raise HTTPException(400, "invalid preference payload")
        if engine.dialect.name == "postgresql":
            sql = """INSERT INTO ui_inventory_preferences(preference_id,user_id,screen_key,filters,columns)
                     VALUES(gen_random_uuid(),:u,:s,CAST(:f AS jsonb),CAST(:c AS jsonb))
                     ON CONFLICT(user_id,screen_key) DO UPDATE SET filters=EXCLUDED.filters,columns=EXCLUDED.columns,updated_at=now()"""
            params = {"u": str(user.user_id), "s": screen_key, "f": json.dumps(filters), "c": json.dumps(columns)}
        else:
            sql = """INSERT INTO ui_inventory_preferences(preference_id,user_id,screen_key,filters,columns)
                     VALUES(:id,:u,:s,:f,:c)
                     ON CONFLICT(user_id,screen_key) DO UPDATE SET filters=excluded.filters,columns=excluded.columns,updated_at=CURRENT_TIMESTAMP"""
            params = {"id": uuid4().hex, "u": str(user.user_id), "s": screen_key, "f": json.dumps(filters), "c": json.dumps(columns)}
        with engine.begin() as c:
            c.execute(text(sql), params)
        return {"screen_key": screen_key, "filters": filters, "columns": columns}

    @app.get("/ui/grn")
    def grn_page():
        return FileResponse(WEB_ROOT / "grn.html")

    @app.get("/ui/qc")
    def qc_page():
        return FileResponse(WEB_ROOT / "qc.html")

    @app.get("/ui/inventory")
    def inventory_page():
        return FileResponse(WEB_ROOT / "inventory.html")

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import Engine, text

from .auth import authenticate
from .identity import permissions_for_user
from .release import load_release_info

WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


def _require(engine: Engine, request: Request, permission: str):
    user = authenticate(request)
    if permission not in permissions_for_user(engine, user.user_id):
        raise HTTPException(status_code=403, detail="permission denied")
    return user


def ensure_ui_schema(engine: Engine) -> None:
    ddl = {
        "postgresql": """
        CREATE TABLE IF NOT EXISTS ui_build_registry (
            build_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            target VARCHAR(20) NOT NULL,
            build_version VARCHAR(64) NOT NULL,
            release_version VARCHAR(32) NOT NULL,
            artifact VARCHAR(255),
            commit_sha VARCHAR(80),
            status VARCHAR(24) NOT NULL,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        "sqlite": """
        CREATE TABLE IF NOT EXISTS ui_build_registry (
            build_id TEXT PRIMARY KEY,
            target TEXT NOT NULL,
            build_version TEXT NOT NULL,
            release_version TEXT NOT NULL,
            artifact TEXT,
            commit_sha TEXT,
            status TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    }
    with engine.begin() as conn:
        conn.execute(text(ddl[engine.dialect.name]))
        conn.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {"p":"ui.view","n":"View Web/Android integration status"})
        conn.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {"p":"ui.manage","n":"Register Web/Android build artifacts"})
        for role in ("manager","super_admin","operator","production","quality","warehouse","dispatch","salesperson","mis"):
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'ui.view') ON CONFLICT(role_id,permission_id) DO NOTHING"), {"r":role})
        for role in ("manager","super_admin"):
            conn.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'ui.manage') ON CONFLICT(role_id,permission_id) DO NOTHING"), {"r":role})


def register_v90bj_routes(app: FastAPI, engine: Engine) -> None:
    ensure_ui_schema(engine)

    @app.get("/web")
    def web_root():
        return FileResponse(WEB_ROOT / "index.html")

    @app.get("/web/assets/{asset_path:path}")
    def web_asset(asset_path: str):
        candidate = (WEB_ROOT / "assets" / asset_path).resolve()
        if WEB_ROOT / "assets" not in candidate.parents:
            raise HTTPException(status_code=404, detail="asset not found")
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail="asset not found")
        return FileResponse(candidate)

    @app.get("/v90bj/ui-manifest")
    def ui_manifest(request: Request):
        _require(engine, request, "ui.view")
        release = load_release_info()
        return {
            "release": release.version,
            "web": {"entry": "/web", "status": "ready"},
            "android": {
                "application_id": "com.namkeen.erp",
                "build_variant": "debug",
                "api_base_url": "${API_BASE_URL}",
                "offline_sync": "/v90bb",
                "barcode_scan": "/v90ba",
            },
        }

    @app.post("/v90bj/build-registry")
    def register_build(payload: dict[str, Any], request: Request):
        user = _require(engine, request, "ui.manage")
        target = str(payload.get("target", "")).upper()
        if target not in {"WEB", "ANDROID"}:
            raise HTTPException(status_code=400, detail="target must be WEB or ANDROID")
        status = str(payload.get("status", "BUILT")).upper()
        build_version = str(payload.get("build_version", "")).strip()
        if not build_version:
            raise HTTPException(status_code=400, detail="build_version required")
        release = load_release_info()
        build_id = __import__("uuid").uuid4()
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO ui_build_registry
                (build_id, target, build_version, release_version, artifact, commit_sha, status, metadata_json)
                VALUES (:id,:target,:build_version,:release_version,:artifact,:commit_sha,:status,:metadata)
            """), {
                "id": str(build_id), "target": target, "build_version": build_version,
                "release_version": release.version, "artifact": payload.get("artifact"),
                "commit_sha": payload.get("commit_sha"), "status": status,
                "metadata": __import__("json").dumps(payload.get("metadata", {}), separators=(",", ":")),
            })
        return {"build_id": str(build_id), "registered_by": user.username, "target": target, "status": status}

    @app.get("/v90bj/build-registry")
    def list_builds(request: Request, target: str | None = None, limit: int = 25):
        _require(engine, request, "ui.view")
        ensure_ui_schema(engine)
        limit = max(1, min(limit, 100))
        with engine.connect() as conn:
            if target:
                rows = conn.execute(text("SELECT * FROM ui_build_registry WHERE target=:t ORDER BY created_at DESC LIMIT :lim"), {"t": target.upper(), "lim": limit}).mappings().all()
            else:
                rows = conn.execute(text("SELECT * FROM ui_build_registry ORDER BY created_at DESC LIMIT :lim"), {"lim": limit}).mappings().all()
        return {"builds": [dict(row) for row in rows]}

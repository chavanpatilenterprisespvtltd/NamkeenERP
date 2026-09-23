from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import Engine, text, inspect

from .auth import authenticate
from .identity import permissions_for_user, roles_for_user
from .release import load_release_info

WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


def _require(engine: Engine, request: Request, write: bool = False):
    user = authenticate(request)
    permission = "transaction_ui.manage" if write else "transaction_ui.view"
    if permission not in permissions_for_user(engine, user.user_id):
        raise HTTPException(403, "permission denied")
    return user


def ensure_transaction_ui_schema(engine: Engine) -> None:
    ddl = {
        "postgresql": """
        CREATE TABLE IF NOT EXISTS ui_transaction_preferences (
            preference_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id TEXT NOT NULL,
            screen_key TEXT NOT NULL,
            filters JSONB NOT NULL DEFAULT '{}'::jsonb,
            columns JSONB NOT NULL DEFAULT '[]'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(user_id, screen_key)
        );
        """,
        "sqlite": """
        CREATE TABLE IF NOT EXISTS ui_transaction_preferences (
            preference_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            screen_key TEXT NOT NULL,
            filters TEXT NOT NULL DEFAULT '{}',
            columns TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, screen_key)
        );
        """,
    }
    with engine.begin() as c:
        c.execute(text(ddl[engine.dialect.name]))
        perms = {
            "transaction_ui.view": "View transactional ERP UI screens",
            "transaction_ui.manage": "Manage transactional ERP UI preferences",
        }
        for pid, name in perms.items():
            c.execute(text("INSERT INTO erp_permissions(permission_id,permission_name) VALUES(:p,:n) ON CONFLICT(permission_id) DO NOTHING"), {"p": pid, "n": name})
        for role in ("manager", "super_admin", "mis", "purchase", "warehouse", "production", "quality", "dispatch", "salesperson"):
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'transaction_ui.view') ON CONFLICT(role_id,permission_id) DO NOTHING"), {"r": role})
        for role in ("manager", "super_admin", "mis"):
            c.execute(text("INSERT INTO erp_role_permissions(role_id,permission_id) VALUES(:r,'transaction_ui.manage') ON CONFLICT(role_id,permission_id) DO NOTHING"), {"r": role})


def _safe_table(engine: Engine, table: str) -> bool:
    return inspect(engine).has_table(table)


def _master_rows(engine: Engine, organization_id: UUID, entity_id: UUID | None, master_type: str, q: str, limit: int):
    if not _safe_table(engine, "master_record"):
        return []
    sql = """SELECT master_id, entity_id, version_no, active, data FROM master_record
             WHERE organization_id=:o AND master_type=:t"""
    p: dict[str, Any] = {"o": str(organization_id), "t": master_type}
    if entity_id:
        sql += " AND (entity_id=:e OR entity_id IS NULL)"
        p["e"] = str(entity_id)
    if q:
        sql += " AND lower(CAST(data AS TEXT)) LIKE :q"
        p["q"] = f"%{q.lower()}%"
    sql += " ORDER BY active DESC, version_no DESC LIMIT :lim"
    p["lim"] = max(1, min(limit, 200))
    with engine.connect() as c:
        rows = c.execute(text(sql), p).mappings().all()
    result=[]
    for r in rows:
        data = r.get("data") or {}
        if isinstance(data, str):
            try: data=json.loads(data)
            except Exception: data={}
        result.append({**data, "master_id": str(r["master_id"]), "entity_id": str(r["entity_id"]) if r["entity_id"] else None, "version_no": r["version_no"], "active": bool(r["active"])})
    return result


def register_v90bm_routes(app: FastAPI, engine: Engine) -> None:
    ensure_transaction_ui_schema(engine)

    @app.get("/v90bm/products")
    def products(request: Request, organization_id: UUID, entity_id: UUID | None = None, q: str = "", limit: int = 50):
        _require(engine, request)
        items=[]
        for typ, label in (("PRODUCT", "products"), ("VARIANT", "variants"), ("PACK_SIZE", "pack_sizes"), ("SKU", "skus"), ("UOM_CONVERSION", "uom_conversions")):
            items.append((label, _master_rows(engine, organization_id, entity_id, typ, q, limit)))
        return {"release": load_release_info().version, "items": dict(items), "role": (roles_for_user(engine, authenticate(request).user_id) or [authenticate(request).role])[0]}

    @app.get("/v90bm/recipes")
    def recipes(request: Request, organization_id: UUID, entity_id: UUID, status: str | None = None, q: str = "", limit: int = 50):
        _require(engine, request)
        if not _safe_table(engine, "recipe"):
            return {"recipes": [], "count": 0}
        sql="SELECT recipe_id,recipe_code,recipe_name,version_no,status,yield_qty,yield_uom,expected_loss_pct,created_at FROM recipe WHERE organization_id=:o AND entity_id=:e"
        p={"o":str(organization_id),"e":str(entity_id)}
        if status:
            sql += " AND status=:s"; p["s"]=status.upper()
        if q:
            sql += " AND (lower(recipe_code) LIKE :q OR lower(recipe_name) LIKE :q)"; p["q"]=f"%{q.lower()}%"
        sql += " ORDER BY recipe_code,version_no DESC LIMIT :lim"; p["lim"]=max(1,min(limit,200))
        with engine.connect() as c:
            rows=[dict(x) for x in c.execute(text(sql),p).mappings().all()]
        return {"recipes":rows,"count":len(rows)}

    @app.get("/v90bm/procurement")
    def procurement(request: Request, organization_id: UUID, entity_id: UUID, location_id: UUID, limit: int = 50):
        _require(engine, request)
        counts={}
        for table,key in (("procurement_requisition","requisitions"),("procurement_quote","quotes"),("procurement_po","purchase_orders"),("procurement_grn_prep","grn_preparation")):
            counts[key]=0
            if _safe_table(engine,table):
                with engine.connect() as c:
                    counts[key]=int(c.execute(text(f"SELECT COUNT(*) FROM {table} WHERE organization_id=:o AND entity_id=:e"),{"o":str(organization_id),"e":str(entity_id)}).scalar_one() or 0)
        pos=[]
        if _safe_table(engine,"procurement_po"):
            with engine.connect() as c:
                pos=[dict(x) for x in c.execute(text("SELECT po_id,po_no,po_date,expected_date,status,supplier_id FROM procurement_po WHERE organization_id=:o AND entity_id=:e AND location_id=:l ORDER BY created_at DESC LIMIT :lim"),{"o":str(organization_id),"e":str(entity_id),"l":str(location_id),"lim":max(1,min(limit,100))}).mappings().all()]
        return {"counts":counts,"purchase_orders":pos}

    @app.get("/v90bm/preferences/{screen_key}")
    def get_preferences(screen_key: str, request: Request):
        user=_require(engine,request)
        with engine.connect() as c:
            row=c.execute(text("SELECT filters,columns FROM ui_transaction_preferences WHERE user_id=:u AND screen_key=:s"),{"u":user.user_id,"s":screen_key}).mappings().first()
        if not row:
            return {"screen_key":screen_key,"filters":{},"columns":[]}
        filters=row["filters"] if isinstance(row["filters"],dict) else json.loads(row["filters"] or "{}")
        cols=row["columns"] if isinstance(row["columns"],list) else json.loads(row["columns"] or "[]")
        return {"screen_key":screen_key,"filters":filters,"columns":cols}

    @app.put("/v90bm/preferences/{screen_key}")
    def put_preferences(screen_key: str, payload: dict[str,Any], request: Request):
        user=_require(engine,request,True)
        filters=payload.get("filters",{})
        columns=payload.get("columns",[])
        if not isinstance(filters,dict) or not isinstance(columns,list) or len(columns)>50:
            raise HTTPException(400,"invalid preference payload")
        if engine.dialect.name == "postgresql":
            sql="""INSERT INTO ui_transaction_preferences(preference_id,user_id,screen_key,filters,columns) VALUES(gen_random_uuid(),:u,:s,CAST(:f AS jsonb),CAST(:c AS jsonb)) ON CONFLICT(user_id,screen_key) DO UPDATE SET filters=EXCLUDED.filters,columns=EXCLUDED.columns,updated_at=now()"""
            params={"u":user.user_id,"s":screen_key,"f":json.dumps(filters),"c":json.dumps(columns)}
        else:
            sql="""INSERT INTO ui_transaction_preferences(preference_id,user_id,screen_key,filters,columns) VALUES(:id,:u,:s,:f,:c) ON CONFLICT(user_id,screen_key) DO UPDATE SET filters=excluded.filters,columns=excluded.columns,updated_at=CURRENT_TIMESTAMP"""
            params={"id":uuid4().hex,"u":user.user_id,"s":screen_key,"f":json.dumps(filters),"c":json.dumps(columns)}
        with engine.begin() as c: c.execute(text(sql),params)
        return {"screen_key":screen_key,"filters":filters,"columns":columns}

    @app.get("/ui/products")
    def products_page(): return FileResponse(WEB_ROOT/"products.html")
    @app.get("/ui/recipes")
    def recipes_page(): return FileResponse(WEB_ROOT/"recipes.html")
    @app.get("/ui/procurement")
    def procurement_page(): return FileResponse(WEB_ROOT/"procurement.html")

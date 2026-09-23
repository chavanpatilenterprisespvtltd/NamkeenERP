from __future__ import annotations
from pathlib import Path
from uuid import UUID
import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.v77.persistent_master import Base
from app.v82.lookups import LOOKUP_TYPES, lookup, lookup_relationships

DB_URL = os.getenv("DATABASE_URL", "sqlite:///./v82_lookup.db")
connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
engine = create_engine(DB_URL, connect_args=connect_args, pool_pre_ping=True)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
app = FastAPI(title="Namkeen ERP v82 Lookup APIs", version="82.0")
static_dir = Path(__file__).parent / "static"
app.mount("/v82/static", StaticFiles(directory=static_dir), name="v82-static")

@app.get("/v82", response_class=HTMLResponse)
def ui() -> str:
    return (static_dir / "index.html").read_text(encoding="utf-8")

@app.get("/v82/lookup-types")
def lookup_types():
    return {"items": sorted(LOOKUP_TYPES)}

@app.get("/v82/lookups/{kind}")
def lookup_api(kind: str, organization_id: UUID, q: str = Query(""), parent_id: UUID | None = None,
               entity_id: UUID | None = None, limit: int = Query(100, ge=1, le=200)):
    try:
        return {"items": lookup(SessionLocal, organization_id=organization_id, kind=kind, q=q, parent_id=parent_id, entity_id=entity_id, limit=limit)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

@app.get("/v82/relationships")
def relationships(organization_id: UUID, sku_id: UUID | None = None, warehouse_id: UUID | None = None,
                  product_id: UUID | None = None, variant_id: UUID | None = None, pack_size_id: UUID | None = None,
                  tax_profile_id: UUID | None = None):
    return lookup_relationships(SessionLocal, organization_id=organization_id, sku_id=sku_id, warehouse_id=warehouse_id,
                                product_id=product_id, variant_id=variant_id, pack_size_id=pack_size_id,
                                tax_profile_id=tax_profile_id)

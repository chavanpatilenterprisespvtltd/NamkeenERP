from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class DatabaseConfig:
    url: str
    pool_size: int = 5
    max_overflow: int = 5
    pool_pre_ping: bool = True


def load_database_config(env: Optional[dict[str, str]] = None) -> DatabaseConfig:
    source = env or os.environ
    url = source.get("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return DatabaseConfig(
        url=url,
        pool_size=int(source.get("DB_POOL_SIZE", "5")),
        max_overflow=int(source.get("DB_MAX_OVERFLOW", "5")),
        pool_pre_ping=source.get("DB_POOL_PRE_PING", "true").lower() not in {"0", "false", "no"},
    )


def create_db_engine(config: DatabaseConfig | None = None) -> Engine:
    cfg = config or load_database_config()
    kwargs = {"pool_pre_ping": cfg.pool_pre_ping}
    if cfg.url.startswith("sqlite"):
        kwargs.update({"connect_args": {"check_same_thread": False}})
        if cfg.url in {"sqlite+pysqlite:///:memory:", "sqlite:///:memory:"}:
            kwargs["poolclass"] = StaticPool
    else:
        kwargs.update({"pool_size": cfg.pool_size, "max_overflow": cfg.max_overflow})
    return create_engine(cfg.url, **kwargs)


def database_ping(engine: Engine) -> tuple[bool, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as exc:  # pragma: no cover - error path is tested via fake engine
        return False, type(exc).__name__

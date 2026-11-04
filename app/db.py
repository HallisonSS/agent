import logging
from pathlib import Path
from typing import Any

from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from app.config import get_settings

log = logging.getLogger("agent.db")
_pool: AsyncConnectionPool | None = None
_SCHEMA_LOCK = 727274


def conninfo() -> str:
    s = get_settings()
    return make_conninfo(
        host=s.postgres_host,
        port=s.postgres_port,
        dbname=s.postgres_db,
        user=s.postgres_user,
        password=s.postgres_password,
    )


async def get_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        pool = AsyncConnectionPool(
            conninfo=conninfo(),
            min_size=1,
            max_size=5,
            open=False,
            kwargs={"row_factory": dict_row, "autocommit": True},
        )
        await pool.open(wait=True, timeout=30)
        _pool = pool
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def ensure_schema() -> None:
    """Reaplica o init.sql (idempotente). Cobre o caso do volume já existir
    e o Postgres NÃO executar o initdb.d de novo."""
    sql = Path(get_settings().schema_path).read_text(encoding="utf-8")
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(f"SELECT pg_advisory_lock({_SCHEMA_LOCK})")
        try:
            await conn.execute(sql)
        finally:
            await conn.execute(f"SELECT pg_advisory_unlock({_SCHEMA_LOCK})")
    log.info("schema ok")


async def fetch_all(query: str, params: Any = None) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(query, params)
        return await cur.fetchall()


async def fetch_one(query: str, params: Any = None) -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(query, params)
        return await cur.fetchone()


async def execute(query: str, params: Any = None) -> None:
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(query, params)


async def audit(actor: str, event_type: str, ref: str | None = None, payload: dict | None = None) -> None:
    try:
        await execute(
            "INSERT INTO audit_log (actor, event_type, ref, payload) VALUES (%s, %s, %s, %s)",
            (actor, event_type, ref, Jsonb(payload or {})),
        )
    except Exception:  # auditoria nunca derruba o fluxo principal
        log.exception("falha ao gravar auditoria")


def jsonb(obj: Any) -> Jsonb:
    return Jsonb(obj)

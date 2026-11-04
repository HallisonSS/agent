"""Memória 3 - PERMANENTE (Postgres): fatos, incidentes, decisões, preferências."""
import re

from app.config import get_settings
from app.db import fetch_all, fetch_one, jsonb

KINDS = {"note", "fact", "incident", "decision", "preference", "chat_summary"}


def _or_query(text: str) -> str:
    tokens = re.findall(r"\w{2,}", text or "", flags=re.UNICODE)[:12]
    return " or ".join(tokens)


async def save(
    content: str,
    kind: str = "note",
    title: str | None = None,
    tags: list[str] | None = None,
    importance: int = 3,
    source: str = "api",
    metadata: dict | None = None,
) -> int:
    if kind not in KINDS:
        kind = "note"
    importance = max(1, min(5, int(importance)))
    row = await fetch_one(
        """INSERT INTO memories (kind, title, content, tags, importance, source, metadata)
           VALUES (%s, %s, %s, %s::text[], %s, %s, %s) RETURNING id""",
        (kind, title, content, tags or [], importance, source, jsonb(metadata or {})),
    )
    return int(row["id"])  # type: ignore[index]


async def search(
    query: str,
    limit: int | None = None,
    kind: str | None = None,
    tags: list[str] | None = None,
) -> list[dict]:
    limit = limit or get_settings().perm_memory_top_k
    return await fetch_all(
        """SELECT id, kind, title, content, tags, importance, created_at,
                  ts_rank(tsv, websearch_to_tsquery('portuguese', %(q)s)) AS rank
           FROM memories
           WHERE (tsv @@ websearch_to_tsquery('portuguese', %(q)s) OR tags && %(tags)s::text[])
             AND (%(kind)s::text IS NULL OR kind = %(kind)s::text)
           ORDER BY rank DESC, importance DESC, created_at DESC
           LIMIT %(limit)s""",
        {"q": _or_query(query), "tags": tags or [], "kind": kind, "limit": limit},
    )


async def recent(limit: int = 20, kind: str | None = None) -> list[dict]:
    return await fetch_all(
        """SELECT id, kind, title, content, tags, importance, created_at FROM memories
           WHERE (%(kind)s::text IS NULL OR kind = %(kind)s::text)
           ORDER BY created_at DESC LIMIT %(limit)s""",
        {"kind": kind, "limit": limit},
    )

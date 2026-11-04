"""Junta as 3 memórias:
  1) CURTA     - Redis (sessão, eventos recentes)
  2) TEMPO REAL - estado vivo consultado na hora + LLM (Ollama/OpenAI)
  3) PERMANENTE - Postgres (full-text em português)
"""
import asyncio
import logging

from app.config import get_settings
from app.db import fetch_one
from app.memory import permanent
from app.memory.short_term import ShortTermMemory
from app.redis_client import get_redis

log = logging.getLogger("agent.memory")
_mgr: "MemoryManager | None" = None


class MemoryManager:
    def __init__(self) -> None:
        self.s = get_settings()
        self.short = ShortTermMemory(get_redis())

    async def live_snapshot(self) -> dict:
        """Memória de tempo real: o que está acontecendo AGORA."""
        r = get_redis()
        names = {
            "alerts": self.s.alerts_stream,
            "actions": self.s.actions_stream,
            "decisions": self.s.decisions_stream,
        }
        lens = await asyncio.gather(*(r.xlen(v) for v in names.values()), return_exceptions=True)
        streams = {k: (v if isinstance(v, int) else None) for k, v in zip(names.keys(), lens)}
        pending = None
        try:
            row = await fetch_one("SELECT count(*) AS n FROM approvals WHERE status = 'pending'")
            pending = int(row["n"]) if row else 0
        except Exception:  # noqa: BLE001
            log.warning("snapshot: falha ao consultar approvals")
        return {"streams_len": streams, "approvals_pending": pending}

    async def build_context(self, session_id: str | None, query: str) -> dict:
        perm, live, events = await asyncio.gather(
            permanent.search(query),
            self.live_snapshot(),
            self.short.recent_events(10),
            return_exceptions=True,
        )
        return {
            "permanent": perm if isinstance(perm, list) else [],
            "live": live if isinstance(live, dict) else {},
            "recent_events": events if isinstance(events, list) else [],
        }


def get_memory() -> MemoryManager:
    global _mgr
    if _mgr is None:
        _mgr = MemoryManager()
    return _mgr

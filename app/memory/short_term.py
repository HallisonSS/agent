"""Memória 1 - CURTA (Redis): conversa por sessão, eventos recentes, dedup."""
import json
import time

from redis.asyncio import Redis

from app.config import get_settings


class ShortTermMemory:
    def __init__(self, r: Redis):
        self.r = r
        self.s = get_settings()

    def _key(self, session_id: str) -> str:
        return f"agent:session:{session_id}"

    async def add_turn(self, session_id: str, role: str, content: str) -> None:
        key = self._key(session_id)
        entry = json.dumps({"role": role, "content": content, "ts": int(time.time())}, ensure_ascii=False)
        async with self.r.pipeline(transaction=False) as p:
            p.rpush(key, entry)
            p.ltrim(key, -self.s.short_memory_max_turns * 2, -1)
            p.expire(key, self.s.short_memory_ttl)
            await p.execute()

    async def history(self, session_id: str) -> list[dict]:
        raw = await self.r.lrange(self._key(session_id), -self.s.short_memory_max_turns * 2, -1)
        out = []
        for item in raw:
            d = json.loads(item)
            out.append({"role": d["role"], "content": d["content"]})
        return out

    async def clear(self, session_id: str) -> None:
        await self.r.delete(self._key(session_id))

    async def push_event(self, kind: str, data: dict) -> None:
        entry = json.dumps({"kind": kind, "ts": int(time.time()), **data}, ensure_ascii=False, default=str)
        async with self.r.pipeline(transaction=False) as p:
            p.lpush("agent:recent_events", entry)
            p.ltrim("agent:recent_events", 0, self.s.recent_events_max - 1)
            p.expire("agent:recent_events", self.s.short_memory_ttl)
            await p.execute()

    async def recent_events(self, n: int = 10) -> list[dict]:
        raw = await self.r.lrange("agent:recent_events", 0, n - 1)
        return [json.loads(x) for x in raw]

    async def first_time(self, key: str, ttl: int | None = None) -> bool:
        """True só na 1ª vez dentro do TTL (anti-tempestade de alertas/LLM)."""
        ok = await self.r.set(f"agent:dedup:{key}", "1", nx=True, ex=ttl or self.s.dedup_ttl)
        return bool(ok)

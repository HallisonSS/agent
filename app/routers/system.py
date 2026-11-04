from fastapi import APIRouter, Depends, HTTPException

from app.config import get_settings
from app.db import fetch_one
from app.ia import provider
from app.memory.manager import get_memory
from app.redis_client import get_redis
from app.security.auth import require_key

public = APIRouter(tags=["system"])
router = APIRouter(tags=["system"], dependencies=[Depends(require_key)])


@public.get("/health")
async def health():
    try:
        await get_redis().ping()
        await fetch_one("SELECT 1 AS ok")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"unhealthy: {type(e).__name__}") from e
    return {"status": "ok"}


@router.get("/status")
async def status():
    s = get_settings()
    snap = await get_memory().live_snapshot()
    return {"live": snap, "llm": provider.status(), "executor_mode": s.executor_mode}


@router.post("/llm/ping")
async def llm_ping():
    try:
        res = await provider.chat([{"role": "user", "content": "Responda apenas: OK"}])
    except provider.LLMError as e:
        raise HTTPException(502, str(e)) from e
    return {"provider": res.provider, "model": res.model, "reply": res.text.strip()[:200]}

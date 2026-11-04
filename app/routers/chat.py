from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.db import audit
from app.ia import prompts, provider
from app.memory import permanent
from app.memory.manager import get_memory
from app.security.auth import require_key

router = APIRouter(tags=["chat"], dependencies=[Depends(require_key)])


class ChatRequest(BaseModel):
    session_id: str = "default"
    message: str = Field(min_length=1, max_length=8000)
    use_memory: bool = True
    remember: bool = False  # grava a mensagem na memória permanente


class MemoryIn(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    kind: str = "note"
    title: str | None = None
    tags: list[str] = Field(default_factory=list)
    importance: int = 3


@router.post("/chat")
async def chat(req: ChatRequest):
    mem = get_memory()
    history = await mem.short.history(req.session_id)
    ctx = await mem.build_context(req.session_id, req.message) if req.use_memory else None
    messages = prompts.chat_messages(ctx, history, req.message)
    try:
        res = await provider.chat(messages)
    except provider.LLMError as e:
        raise HTTPException(502, f"LLM indisponível: {e}") from e
    reply = res.text.strip()
    await mem.short.add_turn(req.session_id, "user", req.message)
    await mem.short.add_turn(req.session_id, "assistant", reply)
    if req.remember:
        await permanent.save(req.message, kind="note", source=f"chat:{req.session_id}")
    await audit("api", "chat", req.session_id, {"provider": res.provider, "model": res.model})
    return {
        "reply": reply,
        "provider": res.provider,
        "model": res.model,
        "memory_used": {
            "short_term_turns": len(history),
            "permanent_hits": len(ctx["permanent"]) if ctx else 0,
            "live_snapshot": bool(ctx and ctx["live"]),
        },
    }


@router.delete("/chat/{session_id}")
async def clear_session(session_id: str):
    await get_memory().short.clear(session_id)
    return {"cleared": True}


@router.post("/memory")
async def save_memory(m: MemoryIn):
    mid = await permanent.save(m.content, m.kind, m.title, m.tags, m.importance, source="api")
    return {"id": mid}


@router.get("/memory/search")
async def search_memory(q: str = Query(min_length=1), limit: int = 5, kind: str | None = None):
    return await permanent.search(q, limit=min(limit, 50), kind=kind)

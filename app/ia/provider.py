"""Provedor de LLM único: troca entre Ollama e OpenAI só pelo .env."""
import logging
from dataclasses import dataclass

import httpx

from app.config import Settings, get_settings

log = logging.getLogger("agent.llm")


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str


def openai_ready(s: Settings) -> bool:
    return bool(s.openai_api_key.strip())


def provider_order(s: Settings | None = None) -> list[str]:
    s = s or get_settings()
    p = s.llm_provider.strip().lower()
    ready = openai_ready(s)
    if p == "openai":
        order = ["openai"] + (["ollama"] if s.llm_fallback else [])
    elif p == "ollama":
        order = ["ollama"] + (["openai"] if s.llm_fallback and ready else [])
    else:  # auto: OpenAI se houver chave, senão Ollama
        order = (["openai"] if ready else []) + ["ollama"]
    if not ready and "openai" in order:
        order.remove("openai")  # sem chave, pula automaticamente
    return order


def status() -> dict:
    s = get_settings()
    return {
        "configured": s.llm_provider,
        "order": provider_order(s),
        "openai_key_present": openai_ready(s),
        "ollama_url": s.ollama_url,
        "ollama_model": s.ollama_model,
        "openai_model": s.openai_model,
        "fallback": s.llm_fallback,
    }


async def _ollama(s: Settings, messages: list[dict], json_mode: bool) -> tuple[str, str]:
    payload: dict = {"model": s.ollama_model, "messages": messages, "stream": False}
    if json_mode:
        payload["format"] = "json"
    async with httpx.AsyncClient(timeout=s.llm_timeout) as c:
        r = await c.post(f"{s.ollama_url.rstrip('/')}/api/chat", json=payload)
        r.raise_for_status()
        return r.json()["message"]["content"], s.ollama_model


async def _openai(s: Settings, messages: list[dict], json_mode: bool) -> tuple[str, str]:
    payload: dict = {"model": s.openai_model, "messages": messages}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {s.openai_api_key.strip()}"}
    async with httpx.AsyncClient(timeout=s.llm_timeout) as c:
        r = await c.post(f"{s.openai_base_url.rstrip('/')}/chat/completions", json=payload, headers=headers)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"], s.openai_model


_BACKENDS = {"ollama": _ollama, "openai": _openai}


async def chat(messages: list[dict], json_mode: bool = False) -> LLMResult:
    s = get_settings()
    order = provider_order(s)
    if not order:
        raise LLMError("nenhum provedor LLM disponível (OPENAI_API_KEY ausente e fallback desligado)")
    errors: list[str] = []
    for name in order:
        try:
            text, model = await _BACKENDS[name](s, messages, json_mode)
            return LLMResult(text=text, provider=name, model=model)
        except Exception as e:  # noqa: BLE001
            msg = f"{name}: {type(e).__name__}: {e}"
            log.warning("LLM falhou -> %s", msg)
            errors.append(msg)
    raise LLMError(" | ".join(errors))

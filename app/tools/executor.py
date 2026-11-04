"""Executor SEGURO: só roda ações da whitelist (CATALOG). Nada de shell livre."""
import asyncio
import logging
import re
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.db import fetch_one
from app.redis_client import get_redis

log = logging.getLogger("agent.executor")
_SERVICE_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")


@dataclass(frozen=True)
class ActionSpec:
    name: str
    description: str
    requires_approval: bool = False
    required: tuple[str, ...] = ()
    host: bool = False  # precisa rodar no HOST (fora do container)


CATALOG: dict[str, ActionSpec] = {
    s.name: s
    for s in [
        ActionSpec("notify", "apenas registrar/avisar. params: message", False, ("message",)),
        ActionSpec("http_check", "GET em URL de host permitido. params: url", False, ("url",)),
        ActionSpec("tcp_check", "testa porta TCP. params: host, port", False, ("host", "port")),
        ActionSpec("redis_info", "memória/chaves do Redis do agent", False),
        ActionSpec("db_stats", "conexões e tamanho do Postgres do agent", False),
        ActionSpec("check_service_status", "status de serviço systemd no host. params: service", False, ("service",), True),
        ActionSpec("service_logs", "últimas linhas do journal de um serviço no host. params: service, lines (opcional, até 999)", False, ("service",), True),
        ActionSpec("disk_usage", "uso de disco do host (df -h)", False, (), True),
        ActionSpec("restart_service", "reinicia serviço systemd no host. params: service", True, ("service",), True),
        ActionSpec("ufw_allow", "libera porta no UFW do host. params: port (1-65535), proto (tcp|udp)", True, ("port", "proto"), True),
    ]
}


def get_spec(name: str) -> ActionSpec | None:
    return CATALOG.get(name)


def catalog_text() -> str:
    return "\n".join(
        f"- {s.name}: {s.description} (aprovação humana: {'sim' if s.requires_approval else 'não'})"
        for s in CATALOG.values()
    )


def validate(name: str, params: dict) -> ActionSpec:
    spec = CATALOG.get(name)
    if not spec:
        raise ValueError(f"ação não permitida: {name}")
    missing = [k for k in spec.required if k not in params or params[k] in (None, "")]
    if missing:
        raise ValueError(f"params ausentes para {name}: {', '.join(missing)}")
    if "service" in spec.required and not _SERVICE_RE.match(str(params["service"])):
        raise ValueError("nome de serviço inválido")
    if name == "service_logs" and params.get("lines") not in (None, ""):
        if not re.fullmatch(r"\d{1,3}", str(params["lines"])):
            raise ValueError("lines deve ter de 1 a 3 dígitos")
    if name == "ufw_allow":
        if not re.fullmatch(r"\d{1,5}", str(params["port"])) or not 1 <= int(params["port"]) <= 65535:
            raise ValueError("port inválida (1-65535)")
        if str(params["proto"]).lower() not in ("tcp", "udp"):
            raise ValueError("proto deve ser tcp ou udp")
    return spec


def _host_allowed(host: str) -> bool:
    allowed = {h.strip().lower() for h in get_settings().check_allowed_hosts.split(",") if h.strip()}
    return host.lower() in allowed


async def _notify(params: dict) -> dict:
    return {"ok": True, "output": str(params.get("message", ""))}


async def _http_check(params: dict) -> dict:
    url = str(params["url"])
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname or not _host_allowed(u.hostname):
        return {"ok": False, "output": "host não permitido (veja CHECK_ALLOWED_HOSTS)"}
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=5, follow_redirects=False) as c:
        resp = await c.get(url)
    ms = round((time.monotonic() - t0) * 1000)
    return {"ok": resp.status_code < 500, "output": f"HTTP {resp.status_code} em {ms} ms"}


async def _tcp_check(params: dict) -> dict:
    host, port = str(params["host"]), int(params["port"])
    if not _host_allowed(host):
        return {"ok": False, "output": "host não permitido (veja CHECK_ALLOWED_HOSTS)"}
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=3)
        w.close()
        await w.wait_closed()
        return {"ok": True, "output": f"{host}:{port} aberto"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "output": f"{host}:{port} falhou: {type(e).__name__}"}


async def _redis_info(params: dict) -> dict:
    r = get_redis()
    mem = await r.info("memory")
    return {"ok": True, "output": f"used_memory={mem.get('used_memory_human')} keys={await r.dbsize()}"}


async def _db_stats(params: dict) -> dict:
    row = await fetch_one(
        "SELECT (SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()) AS conns, "
        "pg_size_pretty(pg_database_size(current_database())) AS size"
    )
    return {"ok": True, "output": f"conexões={row['conns']} tamanho={row['size']}"}  # type: ignore[index]


async def _host_action(name: str, params: dict, meta: dict | None = None) -> dict:
    """Ações de host NÃO rodam no container. Em modo live viram mensagem no
    host_exec_stream; o host_runner (executor/) executa via assist-safe-run e
    devolve o resultado em host_result_stream."""
    s = get_settings()
    if s.executor_mode.lower() != "live":
        return {"ok": True, "mode": "dry-run", "output": f"[dry-run] {name} {params}"}
    fields = {"action": name}
    for k in ("service", "lines", "port", "proto"):
        if params.get(k) not in (None, ""):
            fields[k] = str(params[k])
    approval_id = (meta or {}).get("approval_id")
    if approval_id:
        fields["approval_id"] = str(approval_id)
    await get_redis().xadd(s.host_exec_stream, fields, maxlen=s.stream_maxlen, approximate=True)
    return {"ok": True, "mode": "live", "output": f"{name} enviado ao executor do host ({s.host_exec_stream})"}


_HANDLERS = {
    "notify": _notify,
    "http_check": _http_check,
    "tcp_check": _tcp_check,
    "redis_info": _redis_info,
    "db_stats": _db_stats,
}


async def run(name: str, params: dict, meta: dict | None = None) -> dict:
    try:
        spec = validate(name, params)
        if spec.host:
            return await _host_action(name, params, meta)
        return await _HANDLERS[name](params)
    except Exception as e:  # noqa: BLE001
        log.exception("ação %s falhou", name)
        return {"ok": False, "output": f"{type(e).__name__}: {e}"}

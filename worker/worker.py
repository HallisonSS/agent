"""agent-worker: consome alerts_stream e actions_stream (Redis Streams),
decide (regra -> LLM), grava no Postgres e executa ações da whitelist."""
import asyncio
import hashlib
import json
import logging
import re
import signal
import socket
from pathlib import Path

from redis.exceptions import ResponseError

from app.config import get_settings
from app.db import audit, close_pool, ensure_schema, fetch_one, execute, jsonb
from app.ia import prompts, provider
from app.memory import permanent
from app.memory.manager import get_memory
from app.redis_client import close_redis, get_redis
from app.tools import executor
from worker import policies

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("agent.worker")

S = get_settings()
HEARTBEAT = Path("/tmp/worker.alive")
SEVERITIES = {"info", "warning", "critical"}
WATCHED = (S.alerts_stream, S.actions_stream, S.host_result_stream)


def beat() -> None:
    HEARTBEAT.touch()


def _loads(raw: str | None, default):
    try:
        return json.loads(raw) if raw else default
    except json.JSONDecodeError:
        return default


def parse_json_block(text: str) -> dict:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        d = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            return {}
        try:
            d = json.loads(m.group(0))
        except json.JSONDecodeError:
            return {}
    return d if isinstance(d, dict) else {}


def normalize_decision(raw: dict, alertname: str, labels_sev: str) -> dict:
    summary = str(raw.get("summary") or alertname)[:500]
    severity = str(raw.get("severity") or labels_sev or "warning").lower()
    if severity not in SEVERITIES:
        severity = "warning"
    action = str(raw.get("action") or "notify")
    params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
    try:
        executor.validate(action, params)
    except ValueError:
        action, params = "notify", {"message": summary}
    spec = executor.CATALOG[action]
    return {
        "summary": summary,
        "severity": severity,
        "action": action,
        "params": params,
        "requires_approval": bool(spec.requires_approval or raw.get("requires_approval")),
        "reason": str(raw.get("reason") or "")[:500],
    }


async def decide(alert: dict) -> dict:
    labels, ann = alert["labels"], alert["annotations"]
    alertname = labels.get("alertname", "unknown")
    sev = str(labels.get("severity", "")).lower()

    fixed = policies.match(alertname, sev)
    if fixed:
        return {**fixed, "requires_approval": False, "reason": "regra fixa", "llm_provider": None, "llm_model": None}

    query = " ".join(str(x) for x in (alertname, labels.get("job"), labels.get("instance"), ann.get("summary")) if x)
    ctx = await get_memory().build_context("alerts", query)
    msgs = prompts.decision_messages(
        {"labels": labels, "annotations": ann, "startsAt": alert.get("startsAt")}, ctx, executor.catalog_text()
    )
    try:
        res = await provider.chat(msgs, json_mode=True)
        d = normalize_decision(parse_json_block(res.text), alertname, sev)
        return {**d, "source": "llm", "llm_provider": res.provider, "llm_model": res.model}
    except provider.LLMError as e:
        log.warning("LLM indisponível, usando notify: %s", e)
        msg = ann.get("summary") or alertname
        return {
            "summary": str(msg)[:500],
            "severity": sev if sev in SEVERITIES else "warning",
            "action": "notify",
            "params": {"message": f"LLM indisponível; alerta {alertname} apenas registrado"},
            "requires_approval": False,
            "reason": "fallback sem LLM",
            "source": "fallback",
            "llm_provider": None,
            "llm_model": None,
        }


async def handle_alert(fields: dict) -> None:
    r = get_redis()
    labels = _loads(fields.get("labels"), {})
    ann = _loads(fields.get("annotations"), {})
    status = fields.get("status", "")
    alertname = labels.get("alertname", "unknown")
    fp = fields.get("fingerprint") or hashlib.sha1(json.dumps(labels, sort_keys=True).encode()).hexdigest()[:16]

    mem = get_memory()
    await mem.short.push_event("alert", {"alertname": alertname, "status": status, "instance": labels.get("instance")})
    await audit("worker", "alert_received", fp, {"status": status, "labels": labels})

    if status == "resolved":
        return
    if not await mem.short.first_time(f"{fp}:{status}"):
        await audit("worker", "alert_deduplicated", fp, {"alertname": alertname})
        return

    alert = {"labels": labels, "annotations": ann, "startsAt": fields.get("startsAt")}
    d = await decide(alert)
    row = await fetch_one(
        """INSERT INTO decisions (fingerprint, alertname, severity, summary, action, params,
                                  requires_approval, source, llm_provider, llm_model)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (fp, alertname, d["severity"], d["summary"], d["action"], jsonb(d["params"]),
         d["requires_approval"], d["source"], d.get("llm_provider"), d.get("llm_model")),
    )
    decision_id = int(row["id"])  # type: ignore[index]
    await r.xadd(
        S.decisions_stream,
        {"decision_id": str(decision_id), "alertname": alertname, "severity": d["severity"],
         "action": d["action"], "summary": d["summary"], "source": d["source"]},
        maxlen=S.stream_maxlen, approximate=True,
    )
    await audit("worker", "decision", str(decision_id), {k: d[k] for k in ("action", "params", "source", "reason")})

    if d["severity"] in ("warning", "critical"):
        await permanent.save(
            f"{d['summary']} -> ação: {d['action']} ({d['reason']})",
            kind="incident", title=alertname, tags=[alertname, d["severity"]],
            importance=4 if d["severity"] == "critical" else 3, source="worker",
            metadata={"decision_id": decision_id, "instance": labels.get("instance")},
        )

    if d["requires_approval"]:
        ap = await fetch_one(
            "INSERT INTO approvals (requested_by, action, params, reason, decision_id) VALUES (%s,%s,%s,%s,%s) RETURNING id",
            ("worker", d["action"], jsonb(d["params"]), d["reason"], decision_id),
        )
        await audit("worker", "approval_requested", str(ap["id"]), {"action": d["action"]})  # type: ignore[index]
        return

    await r.xadd(
        S.actions_stream,
        {"action": d["action"], "params": json.dumps(d["params"], ensure_ascii=False),
         "requested_by": "worker", "decision_id": str(decision_id)},
        maxlen=S.stream_maxlen, approximate=True,
    )


async def handle_action(fields: dict) -> None:
    action = fields.get("action", "")
    params = _loads(fields.get("params"), {})
    approval_id = fields.get("approval_id")
    result = await executor.run(action, params, {"approval_id": approval_id})
    await audit("worker", "action_executed", action,
                {"params": params, "result": result, "requested_by": fields.get("requested_by"),
                 "approval_id": approval_id})
    # ação de host em modo live: o status final só chega com o resultado do host_runner
    waiting_host = result.get("mode") == "live"
    if approval_id and not waiting_host:
        await execute("UPDATE approvals SET status = %s WHERE id = %s",
                      ("executed" if result.get("ok") else "failed", int(approval_id)))
    if action != "notify":
        await get_memory().short.push_event("action", {"action": action, "ok": result.get("ok")})
    log.info("ação %s -> %s", action, result)


async def handle_host_result(fields: dict) -> None:
    """Resultado devolvido pelo host_runner (assist-safe-run)."""
    action = fields.get("action", "")
    target = fields.get("service") or fields.get("port") or ""
    try:
        rc = int(fields.get("rc", "1"))
    except ValueError:
        rc = 1
    ok = rc == 0
    out = (fields.get("out") or "")[:1500]
    approval_id = fields.get("approval_id")
    await audit("host-runner", "host_action_result", f"{action}:{target}",
                {"rc": rc, "ok": ok, "output": out, "approval_id": approval_id, "exec_id": fields.get("id")})
    if approval_id:
        await execute("UPDATE approvals SET status = %s WHERE id = %s",
                      ("executed" if ok else "failed", int(approval_id)))
    await get_memory().short.push_event("host_result", {"action": action, "target": target, "ok": ok})
    if action in ("restart_service", "ufw_allow") or not ok:
        await permanent.save(
            f"{action} {target} -> {'ok' if ok else 'FALHOU rc=' + str(rc)}. {out[:300]}",
            kind="incident", title=f"host:{action}", tags=[action, "host"],
            importance=2 if ok else 4, source="host-runner",
        )
    log.info("resultado do host: %s %s rc=%s", action, target, rc)


async def dispatch(stream: str, fields: dict) -> None:
    if stream == S.alerts_stream:
        await handle_alert(fields)
    elif stream == S.actions_stream:
        await handle_action(fields)
    elif stream == S.host_result_stream:
        await handle_host_result(fields)


async def ensure_groups() -> None:
    r = get_redis()
    for stream in WATCHED:
        try:
            await r.xgroup_create(stream, S.worker_group, id="0", mkstream=True)
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    r = get_redis()
    await r.ping()
    await ensure_schema()
    await ensure_groups()
    consumer = S.worker_consumer or socket.gethostname()
    log.info("worker pronto: group=%s consumer=%s llm=%s", S.worker_group, consumer, provider.provider_order())

    streams_ids = lambda sid: {st: sid for st in WATCHED}  # noqa: E731
    backlog_done = False  # 1ª fase: reprocessa pendentes ("0"); depois só novas (">")
    while not stop.is_set():
        beat()
        try:
            if backlog_done:
                resp = await r.xreadgroup(S.worker_group, consumer, streams_ids(">"), count=10, block=5000)
            else:
                resp = await r.xreadgroup(S.worker_group, consumer, streams_ids("0"), count=10)
                if not resp or all(not msgs for _, msgs in resp):
                    backlog_done = True
                    continue
        except ResponseError as e:
            if "NOGROUP" in str(e):
                await ensure_groups()
                continue
            raise
        except Exception:  # noqa: BLE001
            log.exception("erro lendo streams; tentando de novo em 3s")
            await asyncio.sleep(3)
            continue

        for stream, msgs in resp or []:
            for msg_id, fields in msgs:
                try:
                    await dispatch(stream, fields)
                except Exception as e:  # noqa: BLE001
                    log.exception("erro em %s/%s -> DLQ", stream, msg_id)
                    await r.xadd(S.dlq_stream, {"stream": stream, "id": msg_id,
                                                "error": f"{type(e).__name__}: {e}"[:500],
                                                "fields": json.dumps(fields, ensure_ascii=False)[:2000]},
                                 maxlen=1000, approximate=True)
                finally:
                    await r.xack(stream, S.worker_group, msg_id)
                beat()

    log.info("encerrando worker")
    await close_pool()
    await close_redis()


if __name__ == "__main__":
    asyncio.run(main())

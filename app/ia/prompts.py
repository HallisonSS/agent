import json

SYSTEM = (
    "Você é o AGENT, um assistente SRE que cuida de servidores, redes e containers. "
    "Responda em português do Brasil, de forma objetiva e técnica. "
    "Nunca invente dados: use apenas o contexto fornecido. Se não souber, diga que não sabe."
)

DECISION_SYSTEM = (
    SYSTEM
    + " Você analisa alertas do Alertmanager e escolhe UMA ação da lista permitida. "
    "Responda SOMENTE com um objeto JSON, sem texto extra."
)


def render_context(ctx: dict | None) -> str:
    if not ctx:
        return ""
    parts: list[str] = []
    live = ctx.get("live") or {}
    if live:
        parts.append("## Estado em tempo real\n" + json.dumps(live, ensure_ascii=False, default=str))
    ev = ctx.get("recent_events") or []
    if ev:
        lines = [json.dumps(e, ensure_ascii=False, default=str) for e in ev[:10]]
        parts.append("## Eventos recentes (memória curta)\n" + "\n".join(lines))
    perm = ctx.get("permanent") or []
    if perm:
        lines = [f"- [{m['kind']}] {m.get('title') or ''}: {m['content']}" for m in perm]
        parts.append("## Memória permanente relevante\n" + "\n".join(lines))
    return "\n\n".join(parts)


def chat_messages(ctx: dict | None, history: list[dict], user_message: str) -> list[dict]:
    msgs: list[dict] = [{"role": "system", "content": SYSTEM}]
    block = render_context(ctx)
    if block:
        msgs.append({"role": "system", "content": block})
    msgs.extend(history)
    msgs.append({"role": "user", "content": user_message})
    return msgs


def decision_messages(alert: dict, ctx: dict | None, catalog_text: str) -> list[dict]:
    user = (
        "Alerta recebido:\n"
        + json.dumps(alert, ensure_ascii=False, default=str)
        + "\n\nAções permitidas:\n"
        + catalog_text
        + "\n\nResponda JSON com as chaves: "
        '{"summary": str, "severity": "info|warning|critical", "action": str, '
        '"params": object, "requires_approval": bool, "reason": str}. '
        'Se não houver ação segura, use action "notify" com params {"message": "..."}.'
    )
    msgs = [{"role": "system", "content": DECISION_SYSTEM}]
    block = render_context(ctx)
    if block:
        msgs.append({"role": "system", "content": block})
    msgs.append({"role": "user", "content": user})
    return msgs

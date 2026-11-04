"""Regras determinísticas (rodam ANTES do LLM). Edite à vontade."""

# alertname -> decisão fixa, sem consultar LLM
RULES: dict[str, dict] = {
    "Watchdog": {"action": "notify", "params": {"message": "Watchdog ok"}, "summary": "heartbeat do Alertmanager"},
}

# severidade que nunca precisa de LLM
NO_LLM_SEVERITIES = {"none"}


def match(alertname: str, severity: str) -> dict | None:
    if alertname in RULES:
        return {**RULES[alertname], "severity": severity or "info", "source": "policy"}
    if severity in NO_LLM_SEVERITIES:
        return {
            "action": "notify",
            "params": {"message": f"{alertname}: sem ação"},
            "summary": alertname,
            "severity": severity,
            "source": "policy",
        }
    return None

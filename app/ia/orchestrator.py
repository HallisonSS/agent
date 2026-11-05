
# app/ia/orchestrator.py
RULES = {
    "security": ("ssh", "ufw", "fail2ban", "ip ", "bloquear", "tentativas", "auth.log"),
    "monitor":  ("cpu", "ram", "disco", "container", "serviço", "porta"),
}

def route(text: str, llm_local) -> str:
    t = text.lower()
    for agent, kws in RULES.items():
        if any(k in t for k in kws):
            return agent
    # fallback: classificação barata no modelo local
    ans = llm_local(f"Responda só 'security' ou 'monitor': {text}")
    return ans.strip().lower() if ans.strip().lower() in RULES else "monitor"

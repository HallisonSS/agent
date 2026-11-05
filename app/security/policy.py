def decide(plan, failures: dict[str,int]) -> str:
    if plan.action == "none":
        return "ignore"
    # o LLM só sugere; a regra determinística confirma
    if plan.action == "ban" and failures.get(plan.ip, 0) >= 5:
        return "auto"            # baixo risco, reversível (fail2ban expira)
    if plan.action == "deny":
        return "approval"        # regra permanente no ufw: humano aprova
    return "approval"

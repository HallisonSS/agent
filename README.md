# AGENT — API + Worker + Postgres + Redis + orchestration + Agent-security-monitor

## Subir
```bash
cd agent
./setup.sh            # cria .env com senhas aleatórias e sobe (use sudo se o docker pedir)
# ou manual:
cp .env.example .env  # edite as 3 variáveis obrigatórias
docker compose up -d --build
```

## Testar
```bash
source .env
curl -s localhost:${API_PORT:-8000}/health
curl -s -H "X-API-Key: $API_KEY" -X POST localhost:${API_PORT:-8000}/llm/ping
curl -s -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' \
  -d '{"session_id":"t1","message":"quem é você?"}' localhost:${API_PORT:-8000}/chat
docker compose logs -f agent-worker
```

## Acessar o banco (comando correto)
```bash
docker compose exec postgres psql -U assist -d assistdb
```

## Alertmanager (webhook)
```yaml
receivers:
  - name: agent
    webhook_configs:
      - url: http://IP_DO_AGENT:8000/alerts
        send_resolved: true
        http_config:
          authorization: { type: Bearer, credentials: "<API_KEY do .env>" }
```

## Ollama no host
O container alcança o host por `host.docker.internal`. O Ollama precisa escutar fora de 127.0.0.1:
```bash
sudo systemctl edit ollama     # adicione:  [Service]  Environment="OLLAMA_HOST=0.0.0.0:11434"
sudo systemctl restart ollama
ollama list                    # o modelo de OLLAMA_MODEL precisa existir (ollama pull ...)
```

## Reset total do banco (só se quiser apagar tudo)
`docker compose down -v`

## Executor do host (pasta `executor/`)
Ações que mexem no servidor (reiniciar serviço, UFW, logs, disco) NÃO rodam no container.
Fluxo: `agent-worker` -> Redis `host_exec_stream` -> `host_runner.py` (host, usuário `assistbot`)
-> `sudo assist-safe-run` -> resultado em `host_result_stream` -> worker grava na auditoria/aprovação.

```bash
sudo ./executor/install.sh          # cria assistbot, wrapper, sudoers, runner e serviço systemd
sudoedit /etc/assist/allowed-services   # serviços que o agente pode consultar/reiniciar
# no .env:  EXECUTOR_MODE=live   e depois:
docker compose up -d
```

Ações do catálogo: `check_service_status`, `service_logs`, `disk_usage` (sem aprovação);
`restart_service`, `ufw_allow` (exigem aprovação em `/admin/approvals/decide`).

Testes:
```bash
sudo -u assistbot sudo -n /usr/local/bin/assist-safe-run disk            # deve funcionar
sudo -u assistbot sudo -n /usr/bin/systemctl restart ssh                 # deve NEGAR (sudoers só libera o wrapper)
sudo -u assistbot sudo -n /usr/local/bin/assist-safe-run restart ssh     # deve NEGAR (fora da lista)
journalctl -t assist-safe-run -n 10      # auditoria no host
journalctl -u assist-runner -f           # log do runner
```
Em `EXECUTOR_MODE=dry-run` (padrão) nada chega ao host: o worker só registra "[dry-run]".

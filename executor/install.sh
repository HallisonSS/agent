#!/usr/bin/env bash
# Instala o executor no HOST. Rode com:  sudo ./executor/install.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "rode com sudo"; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$HERE/../.env"
[[ -f "$ENV_FILE" ]] || { echo "crie o .env primeiro (./setup.sh)"; exit 1; }

get() { grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- || true; }
REDIS_PASSWORD="$(get REDIS_PASSWORD)"; REDIS_PORT="$(get REDIS_HOST_PORT)"
[[ -n "$REDIS_PASSWORD" ]] || { echo "REDIS_PASSWORD vazio no .env"; exit 1; }

echo ">> dependência: python3-redis"
dpkg -s python3-redis >/dev/null 2>&1 || apt-get install -y python3-redis

echo ">> usuário de sistema assistbot (sem login, SEM grupo sudo)"
id assistbot >/dev/null 2>&1 || adduser --system --group --home /var/lib/assistbot --shell /usr/sbin/nologin assistbot

echo ">> wrapper + lista de serviços"
install -o root -g root -m 0755 "$HERE/assist-safe-run" /usr/local/bin/assist-safe-run
install -d -o root -g root -m 0755 /etc/assist
[[ -f /etc/assist/allowed-services ]] || install -o root -g root -m 0644 "$HERE/allowed-services" /etc/assist/allowed-services

echo ">> sudoers (só o wrapper)"
TMP="$(mktemp)"; echo "assistbot ALL=(root) NOPASSWD: /usr/local/bin/assist-safe-run" > "$TMP"
visudo -cf "$TMP"
install -o root -g root -m 0440 "$TMP" /etc/sudoers.d/assistbot; rm -f "$TMP"

echo ">> runner + serviço"
install -d -o root -g root -m 0755 /opt/assist
install -o root -g root -m 0755 "$HERE/host_runner.py" /opt/assist/host_runner.py
umask 027
printf 'REDIS_HOST=127.0.0.1\nREDIS_PORT=%s\nREDIS_PASSWORD=%s\nHOST_EXEC_STREAM=%s\nHOST_RESULT_STREAM=%s\n' \
  "${REDIS_PORT:-6380}" "$REDIS_PASSWORD" "$(get HOST_EXEC_STREAM || true)" "$(get HOST_RESULT_STREAM || true)" > /etc/assist/runner.env
sed -i 's/^HOST_EXEC_STREAM=$/HOST_EXEC_STREAM=host_exec_stream/; s/^HOST_RESULT_STREAM=$/HOST_RESULT_STREAM=host_result_stream/' /etc/assist/runner.env
chown root:assistbot /etc/assist/runner.env; chmod 640 /etc/assist/runner.env
install -o root -g root -m 0644 "$HERE/assist-runner.service" /etc/systemd/system/assist-runner.service
systemctl daemon-reload
systemctl enable --now assist-runner
sleep 2; systemctl --no-pager status assist-runner | head -n 8 || true

cat <<MSG

Pronto. Falta:
  1) conferir /etc/assist/allowed-services (serviços que o agente pode mexer)
  2) no .env do agent:  EXECUTOR_MODE=live   e depois  docker compose up -d
Testes do wrapper:
  sudo -u assistbot sudo -n /usr/local/bin/assist-safe-run disk
  sudo -u assistbot sudo -n /usr/bin/systemctl restart ssh       # deve NEGAR
MSG

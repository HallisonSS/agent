#!/usr/bin/env bash
# Gera o .env com senhas aleatórias (não sobrescreve se já existir) e sobe o stack.
set -euo pipefail
cd "$(dirname "$0")"

rand() { openssl rand -hex 24 2>/dev/null || python3 -c "import secrets;print(secrets.token_hex(24))"; }

if [ ! -f .env ]; then
  cp .env.example .env
  sed -i "s|CHANGE_ME_PG|$(rand)|; s|CHANGE_ME_REDIS|$(rand)|; s|CHANGE_ME_API_KEY|$(rand)|" .env
  chmod 600 .env
  echo ">> .env criado com senhas aleatórias. Revise LLM_PROVIDER, OLLAMA_* e OPENAI_API_KEY."
else
  echo ">> .env já existe, mantido."
fi

if ! docker info >/dev/null 2>&1; then
  echo "!! sem permissão no Docker. Use: sudo ./setup.sh   (ou: sudo usermod -aG docker \$USER && newgrp docker)"
  exit 1
fi

docker compose config -q
docker compose up -d --build
docker compose ps

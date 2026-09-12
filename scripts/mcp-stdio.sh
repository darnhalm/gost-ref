#!/usr/bin/env bash
# Запускает MCP-сервер gost-ref по stdio, сам разбираясь с зависимостями.
# Это команда из .mcp.json: клиенту достаточно склонировать репозиторий.
#
# Порядок поиска интерпретатора:
#   1. .venv-mcp в корне репозитория — если уже создан;
#   2. системный python3 — если MCP SDK в нём уже стоит;
#   3. иначе создаётся .venv-mcp и ставится requirements.txt.
#
# Ставится всё внутрь репозитория, в систему ничего не пишется. Каталог
# .venv-mcp в .gitignore. Ядро gost_ref зависимостей не имеет — они нужны
# только самой MCP-обвязке.

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VENV="$ROOT/.venv-mcp"

# Диагностику пишем в stderr: stdout занят протоколом MCP, любая посторонняя
# строка там ломает handshake.
log() { printf 'gost-ref: %s\n' "$*" >&2; }

if [ -x "$VENV/bin/python" ]; then
  PY="$VENV/bin/python"
elif python3 -c 'import mcp' >/dev/null 2>&1; then
  PY=python3
else
  log "ставлю MCP SDK в $VENV (один раз, минуту)"
  python3 -m venv "$VENV" >&2
  "$VENV/bin/pip" install --quiet --disable-pip-version-check -r "$ROOT/requirements.txt" >&2
  PY="$VENV/bin/python"
  log "готово"
fi

exec "$PY" "$ROOT/server.py" "$@"

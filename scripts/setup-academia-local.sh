#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
RUNTIME_ROOT=${CODEX_RUNTIME_ROOT:-/Users/darnhalm/.codex/skill-runtimes}
VENV=${TELEGRAM_LOCAL_VENV:-$RUNTIME_ROOT/telegram-bot-venv}
DOWNLOADER=${ACADEMIA_DOWNLOADER_DIR:-$RUNTIME_ROOT/academiadl-py}
ACADEMIA_DL_COMMIT=${ACADEMIA_DL_COMMIT:-ec5da4de8e1cbdfec2dd1df55d68cd02a99a7f49}

if [ ! -d "$DOWNLOADER/.git" ]; then
  git clone https://github.com/coflyn/academiadl-py.git "$DOWNLOADER"
fi
git -C "$DOWNLOADER" fetch --quiet origin "$ACADEMIA_DL_COMMIT"
git -C "$DOWNLOADER" checkout --quiet "$ACADEMIA_DL_COMMIT"

python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install -r "$REPO_ROOT/requirements.telegram.txt" \
  -r "$DOWNLOADER/requirements.txt"
"$VENV/bin/python" -m playwright install chromium

echo "Academia local runtime is ready: $VENV"

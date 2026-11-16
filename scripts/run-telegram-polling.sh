#!/usr/bin/env bash
set -euo pipefail

SERVICE=${KEYCHAIN_SERVICE:-gost-ref Telegram Bot}
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
LOCAL_VENV=${TELEGRAM_LOCAL_VENV:-/Users/darnhalm/.codex/skill-runtimes/telegram-bot-venv}
if [ -z "${PYTHON:-}" ] && [ -x "$LOCAL_VENV/bin/python" ]; then
  PYTHON="$LOCAL_VENV/bin/python"
fi
PYTHON=${PYTHON:-python3}

export TELEGRAM_BOT_TOKEN
TELEGRAM_BOT_TOKEN=$(security find-generic-password -a bot-token -s "$SERVICE" -w)
export GOST_REF_API_KEY
if ! GOST_REF_API_KEY=$(security find-generic-password -a gost-api-key -s "$SERVICE" -w 2>/dev/null); then
  GOST_REF_API_KEY=$(yc lockbox payload get --name gost-ref-api-key --format json \
    | python3 -c 'import json,sys;print(next(x["text_value"] for x in json.load(sys.stdin)["entries"] if x["key"]=="api-key"))')
fi
export TELEGRAM_WEBHOOK_SECRET=local-polling

# The local fallback temporarily removes Telegram's webhook. Remember the
# existing cloud endpoint so a normal stop (Ctrl+C/SIGTERM) returns the bot to
# Yandex Serverless automatically.
TELEGRAM_GATEWAY_NAME=${TELEGRAM_GATEWAY_NAME:-gost-ref-telegram}
TELEGRAM_CONFIG_SECRET=${TELEGRAM_CONFIG_SECRET:-gost-ref-telegram-runtime}
if [ -z "${TELEGRAM_RESTORE_WEBHOOK_URL:-}" ]; then
  GATEWAY_DOMAIN=$(yc serverless api-gateway get \
    --name "$TELEGRAM_GATEWAY_NAME" --format json 2>/dev/null \
    | python3 -c 'import json,sys;print(json.load(sys.stdin).get("domain", ""))' \
    || true)
  if [ -n "$GATEWAY_DOMAIN" ]; then
    export TELEGRAM_RESTORE_WEBHOOK_URL="https://$GATEWAY_DOMAIN/telegram/webhook"
  fi
fi
if [ -z "${TELEGRAM_RESTORE_WEBHOOK_SECRET:-}" ]; then
  TELEGRAM_RESTORE_WEBHOOK_SECRET=$(yc lockbox payload get \
    --name "$TELEGRAM_CONFIG_SECRET" --format json 2>/dev/null \
    | python3 -c 'import json,sys;print(next((x.get("text_value", "") for x in json.load(sys.stdin).get("entries", []) if x.get("key") == "webhook-secret"), ""))' \
    || true)
  export TELEGRAM_RESTORE_WEBHOOK_SECRET
fi

if [ -z "${GOST_REF_URL:-}" ]; then
  GOST_CONTAINER_ID=$(yc serverless container get --name gost-ref --format json \
    | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
  export GOST_REF_URL="https://$GOST_CONTAINER_ID.containers.yandexcloud.net"
fi
export TELEGRAM_ALLOWED_USER_IDS=${TELEGRAM_ALLOWED_USER_IDS:-492719286}
export ACADEMIA_DOWNLOAD_ENABLED=${ACADEMIA_DOWNLOAD_ENABLED:-1}
export ACADEMIA_DOWNLOADER_DIR=${ACADEMIA_DOWNLOADER_DIR:-/Users/darnhalm/.codex/skill-runtimes/academiadl-py}
export ACADEMIA_OUTPUT_DIR=${ACADEMIA_OUTPUT_DIR:-/Users/darnhalm/Downloads/Academia}

exec "$PYTHON" "$REPO_ROOT/telegram_polling.py"

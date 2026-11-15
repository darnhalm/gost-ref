#!/usr/bin/env bash
set -euo pipefail

SERVICE=${KEYCHAIN_SERVICE:-gost-ref Telegram Bot}
PYTHON=${PYTHON:-python3}
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

export TELEGRAM_BOT_TOKEN
TELEGRAM_BOT_TOKEN=$(security find-generic-password -a bot-token -s "$SERVICE" -w)
export GOST_REF_API_KEY
if ! GOST_REF_API_KEY=$(security find-generic-password -a gost-api-key -s "$SERVICE" -w 2>/dev/null); then
  GOST_REF_API_KEY=$(yc lockbox payload get --name gost-ref-api-key --format json \
    | python3 -c 'import json,sys;print(next(x["text_value"] for x in json.load(sys.stdin)["entries"] if x["key"]=="api-key"))')
fi
export TELEGRAM_WEBHOOK_SECRET=local-polling

if [ -z "${GOST_REF_URL:-}" ]; then
  GOST_CONTAINER_ID=$(yc serverless container get --name gost-ref --format json \
    | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
  export GOST_REF_URL="https://$GOST_CONTAINER_ID.containers.yandexcloud.net"
fi
export TELEGRAM_ALLOWED_USER_IDS=${TELEGRAM_ALLOWED_USER_IDS:-492719286}

exec "$PYTHON" "$REPO_ROOT/telegram_polling.py"

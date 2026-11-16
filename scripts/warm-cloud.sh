#!/usr/bin/env bash
# Wake the Yandex Serverless containers before an interactive search session.

set -euo pipefail

GOST_CONTAINER=${GOST_CONTAINER:-gost-ref}
TELEGRAM_GATEWAY=${TELEGRAM_GATEWAY_NAME:-gost-ref-telegram}

die() { printf '\nОшибка: %s\n' "$*" >&2; exit 1; }
warm() {
  local label=$1 url=$2
  printf '%s... ' "$label"
  if curl -fsS --max-time 40 "$url" | grep -q '"status":"ok"'; then
    echo "готов"
  else
    echo "не ответил"
    return 1
  fi
}

command -v yc >/dev/null || die "не найден yc"
command -v curl >/dev/null || die "не найден curl"
command -v python3 >/dev/null || die "не найден python3"

GOST_ID=$(yc serverless container get --name "$GOST_CONTAINER" --format json \
  | python3 -c 'import json,sys;print(json.load(sys.stdin).get("id", ""))')
[ -n "$GOST_ID" ] || die "не найден контейнер $GOST_CONTAINER"
GATEWAY_DOMAIN=$(yc serverless api-gateway get --name "$TELEGRAM_GATEWAY" --format json \
  | python3 -c 'import json,sys;print(json.load(sys.stdin).get("domain", ""))')
[ -n "$GATEWAY_DOMAIN" ] || die "не найден API Gateway $TELEGRAM_GATEWAY"

FAILED=0
warm "MCP ГОСТ" "https://$GOST_ID.containers.yandexcloud.net/health" || FAILED=1
warm "Telegram-бот" "https://$GATEWAY_DOMAIN/health" || FAILED=1

if [ "$FAILED" -eq 0 ]; then
  echo "Облачный поиск прогрет."
else
  die "один из сервисов не ответил"
fi

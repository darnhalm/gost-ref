#!/usr/bin/env bash
# Stop the optional local polling fallback and restore the cloud webhook.

set -euo pipefail

SERVICE=${KEYCHAIN_SERVICE:-gost-ref Telegram Bot}
GATEWAY=${TELEGRAM_GATEWAY_NAME:-gost-ref-telegram}
CONFIG_SECRET=${TELEGRAM_CONFIG_SECRET:-gost-ref-telegram-runtime}

die() { printf '\nОшибка: %s\n' "$*" >&2; exit 1; }

command -v yc >/dev/null || die "не найден yc"
command -v python3 >/dev/null || die "не найден python3"
command -v curl >/dev/null || die "не найден curl"

PIDS=$(pgrep -f '/telegram_polling.py$' || true)
if [ -n "$PIDS" ]; then
  printf 'Останавливаю локальный резерв...\n'
  while IFS= read -r pid; do
    [ -n "$pid" ] && kill -TERM "$pid" 2>/dev/null || true
  done <<EOF
$PIDS
EOF
  for _ in $(seq 1 20); do
    pgrep -f '/telegram_polling.py$' >/dev/null || break
    sleep 1
  done
fi

BOT_TOKEN=$(security find-generic-password -a bot-token -s "$SERVICE" -w 2>/dev/null) \
  || die "токен Telegram не найден в Keychain"
GATEWAY_DOMAIN=$(yc serverless api-gateway get --name "$GATEWAY" --format json \
  | python3 -c 'import json,sys;print(json.load(sys.stdin).get("domain", ""))')
[ -n "$GATEWAY_DOMAIN" ] || die "API Gateway не вернул домен"
WEBHOOK_URL="https://$GATEWAY_DOMAIN/telegram/webhook"
WEBHOOK_SECRET=$(yc lockbox payload get --name "$CONFIG_SECRET" --format json \
  | python3 -c 'import json,sys;print(next((x.get("text_value", "") for x in json.load(sys.stdin).get("entries", []) if x.get("key") == "webhook-secret"), ""))')
[ -n "$WEBHOOK_SECRET" ] || die "webhook-secret не найден в Lockbox"

WEBHOOK_RESPONSE=$(curl -fsS --max-time 30 -X POST \
  "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" \
  --data-urlencode "url=$WEBHOOK_URL" \
  --data-urlencode "secret_token=$WEBHOOK_SECRET" \
  --data-urlencode 'allowed_updates=["message","callback_query"]')
printf '%s' "$WEBHOOK_RESPONSE" | python3 -c \
  'import json,sys;data=json.load(sys.stdin);data.get("ok") or sys.exit("Telegram rejected setWebhook")'
WEBHOOK_INFO=$(curl -fsS --max-time 30 \
  "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo")
WEBHOOK_URL="$WEBHOOK_URL" python3 -c \
  'import json,os,sys;data=json.load(sys.stdin).get("result",{});data.get("url")==os.environ["WEBHOOK_URL"] or sys.exit("Telegram webhook verification failed")' \
  <<<"$WEBHOOK_INFO"
echo "Облачный режим включён."

unset BOT_TOKEN WEBHOOK_SECRET WEBHOOK_RESPONSE WEBHOOK_INFO

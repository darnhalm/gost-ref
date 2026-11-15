#!/usr/bin/env bash
# Creates or updates the private Telegram catalog bot in Yandex Cloud.
# First deployment:
#   TELEGRAM_BOT_TOKEN=... TELEGRAM_ALLOWED_USER_IDS=123456 ./scripts/yc-telegram-bot.sh
# If the numeric ID is unknown, omit it, deploy, send /id to the bot, then
# rerun with TELEGRAM_ALLOWED_USER_IDS. Secrets are sent to Lockbox via stdin.

set -euo pipefail

CONTAINER=${CONTAINER:-gost-ref-telegram}
REGISTRY=${REGISTRY:-gost-ref}
SA=${SA:-gost-ref-telegram-sa}
BOT_SECRET=${BOT_SECRET:-gost-ref-telegram}
GOST_SECRET=${GOST_SECRET:-gost-ref-api-key}
GOST_CONTAINER=${GOST_CONTAINER:-gost-ref}
TAG=${TAG:-latest}

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\nОшибка: %s\n' "$*" >&2; exit 1; }
jget() { python3 -c 'import sys,json;d=json.load(sys.stdin);[d:=d.get(k,{}) for k in sys.argv[1].split(".")];print(d if isinstance(d,str) else "")' "$1"; }

GRANT_FAILED=0
grant() {
  local what=$1; shift
  local out
  if out=$("$@" 2>&1); then return 0; fi
  if printf '%s' "$out" | grep -qi "already exists\|уже существует"; then return 0; fi
  printf '  НЕ ВЫДАНО (%s): %s\n' "$what" "$(printf '%s' "$out" | tail -2)" >&2
  GRANT_FAILED=1
}

command -v yc >/dev/null || die "не найден yc"
command -v python3 >/dev/null || die "не найден python3"
command -v curl >/dev/null || die "не найден curl"

FOLDER_ID=$(yc config get folder-id 2>/dev/null || true)
[ -n "$FOLDER_ID" ] || die "не задан folder-id в yc"
REGISTRY_ID=$(yc container registry get --name "$REGISTRY" --format json | jget id)
[ -n "$REGISTRY_ID" ] || die "не найден реестр $REGISTRY"
GOST_CONTAINER_ID=$(yc serverless container get --name "$GOST_CONTAINER" --format json | jget id)
[ -n "$GOST_CONTAINER_ID" ] || die "не найден основной контейнер $GOST_CONTAINER"
GOST_URL="https://$GOST_CONTAINER_ID.containers.yandexcloud.net"

if ! yc serverless container get --name "$CONTAINER" >/dev/null 2>&1; then
  say "Создаю контейнер $CONTAINER"
  yc serverless container create --name "$CONTAINER" >/dev/null
fi
CONTAINER_ID=$(yc serverless container get --name "$CONTAINER" --format json | jget id)
BOT_URL="https://$CONTAINER_ID.containers.yandexcloud.net"

if ! yc iam service-account get --name "$SA" >/dev/null 2>&1; then
  say "Создаю сервисный аккаунт $SA"
  yc iam service-account create --name "$SA" >/dev/null
fi
SA_ID=$(yc iam service-account get --name "$SA" --format json | jget id)
grant "images.puller" yc container registry add-access-binding --id "$REGISTRY_ID" \
  --role container-registry.images.puller --service-account-id "$SA_ID"

GOST_SECRET_JSON=$(yc lockbox secret get --name "$GOST_SECRET" --format json 2>/dev/null) \
  || die "не найден секрет $GOST_SECRET"
GOST_SECRET_ID=$(printf '%s' "$GOST_SECRET_JSON" | jget id)
GOST_PAYLOAD=$(yc lockbox payload get --id "$GOST_SECRET_ID" --format json)
GOST_API_KEY=$(printf '%s' "$GOST_PAYLOAD" | python3 -c \
  'import json,sys;print(next((x.get("text_value","") for x in json.load(sys.stdin).get("entries",[]) if x.get("key")=="api-key"),""))')
[ -n "$GOST_API_KEY" ] || die "в $GOST_SECRET нет api-key"

BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}
WEBHOOK_SECRET=${TELEGRAM_WEBHOOK_SECRET:-}
ALLOWED_IDS=${TELEGRAM_ALLOWED_USER_IDS:-}
UPDATE_SECRET=no

current_value() {
  printf '%s' "$CURRENT_PAYLOAD" | python3 -c \
    'import json,sys;key=sys.argv[1];print(next((x.get("text_value","") for x in json.load(sys.stdin).get("entries",[]) if x.get("key")==key),""))' "$1"
}

if yc lockbox secret get --name "$BOT_SECRET" >/dev/null 2>&1; then
  CURRENT_PAYLOAD=$(yc lockbox payload get --name "$BOT_SECRET" --format json)
  [ -n "$BOT_TOKEN" ] || BOT_TOKEN=$(current_value bot-token)
  [ -n "$WEBHOOK_SECRET" ] || WEBHOOK_SECRET=$(current_value webhook-secret)
  [ -n "$ALLOWED_IDS" ] || ALLOWED_IDS=$(current_value allowed-user-ids)
  BOT_GOST_KEY=$(current_value gost-api-key)
  if [ -n "${TELEGRAM_BOT_TOKEN:-}${TELEGRAM_WEBHOOK_SECRET:-}${TELEGRAM_ALLOWED_USER_IDS:-}" ]; then
    UPDATE_SECRET=yes
  fi
  [ "$BOT_GOST_KEY" = "$GOST_API_KEY" ] || UPDATE_SECRET=yes
else
  UPDATE_SECRET=yes
fi

if [ -z "$BOT_TOKEN" ]; then
  if [ -r /dev/tty ]; then
    printf 'Telegram bot token: ' >/dev/tty
    IFS= read -r -s BOT_TOKEN </dev/tty
    printf '\n' >/dev/tty
  else
    die "задайте TELEGRAM_BOT_TOKEN"
  fi
fi
[ -n "$BOT_TOKEN" ] || die "пустой Telegram bot token"
[ -n "$WEBHOOK_SECRET" ] || WEBHOOK_SECRET=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')
BOT_INFO=$(curl -fsS -m 30 "https://api.telegram.org/bot${BOT_TOKEN}/getMe") \
  || die "Telegram не принял токен бота"
BOT_NAME=$(printf '%s' "$BOT_INFO" | python3 -c \
  'import json,sys;data=json.load(sys.stdin);data.get("ok") or sys.exit(1);print(data.get("result",{}).get("username",""))')
[ -n "$BOT_NAME" ] || die "Telegram не вернул username бота"

if [ "$UPDATE_SECRET" = yes ]; then
  BOT_TOKEN="$BOT_TOKEN" WEBHOOK_SECRET="$WEBHOOK_SECRET" ALLOWED_IDS="$ALLOWED_IDS" GOST_API_KEY="$GOST_API_KEY" \
    python3 -c 'import json,os,sys;entries=[{"key":"bot-token","text_value":os.environ["BOT_TOKEN"]},{"key":"webhook-secret","text_value":os.environ["WEBHOOK_SECRET"]},{"key":"gost-api-key","text_value":os.environ["GOST_API_KEY"]}];allowed=os.environ.get("ALLOWED_IDS","").strip();entries += ([{"key":"allowed-user-ids","text_value":allowed}] if allowed else []);json.dump(entries,sys.stdout)' \
    | if yc lockbox secret get --name "$BOT_SECRET" >/dev/null 2>&1; then
        yc lockbox secret add-version --name "$BOT_SECRET" \
          --description 'update Telegram bot configuration' --payload - >/dev/null
      else
        yc lockbox secret create --name "$BOT_SECRET" --payload - >/dev/null
      fi
fi

BOT_SECRET_JSON=$(yc lockbox secret get --name "$BOT_SECRET" --format json)
BOT_SECRET_ID=$(printf '%s' "$BOT_SECRET_JSON" | jget id)
BOT_VERSION_ID=$(printf '%s' "$BOT_SECRET_JSON" | jget current_version.id)
grant "Telegram secret" yc lockbox secret add-access-binding --id "$BOT_SECRET_ID" \
  --role lockbox.payloadViewer --service-account-id "$SA_ID"

DEPLOY_ARGS=(
  --container-name "$CONTAINER"
  --image "cr.yandex/$REGISTRY_ID/gost-ref-telegram:$TAG"
  --service-account-id "$SA_ID"
  --cores 1 --memory 256MB
  --concurrency 8
  --execution-timeout 120s
  --zone-instances-limit 1
  --zone-requests-limit 8
  --secret "environment-variable=TELEGRAM_BOT_TOKEN,id=$BOT_SECRET_ID,version-id=$BOT_VERSION_ID,key=bot-token"
  --secret "environment-variable=TELEGRAM_WEBHOOK_SECRET,id=$BOT_SECRET_ID,version-id=$BOT_VERSION_ID,key=webhook-secret"
  --secret "environment-variable=GOST_REF_API_KEY,id=$BOT_SECRET_ID,version-id=$BOT_VERSION_ID,key=gost-api-key"
  --metadata-options aws-v1-http-endpoint=disabled,gce-http-endpoint=disabled
  --environment "GOST_REF_URL=$GOST_URL"
  --environment TELEGRAM_RATE_LIMIT=10
  --environment TELEGRAM_RATE_WINDOW=60
)
if [ -n "$ALLOWED_IDS" ]; then
  DEPLOY_ARGS+=(--secret "environment-variable=TELEGRAM_ALLOWED_USER_IDS,id=$BOT_SECRET_ID,version-id=$BOT_VERSION_ID,key=allowed-user-ids")
else
  DEPLOY_ARGS+=(--environment TELEGRAM_ALLOWED_USER_IDS=)
fi

say "Выкладываю $CONTAINER"
yc serverless container revision deploy "${DEPLOY_ARGS[@]}" >/dev/null
grant "публичный webhook" yc serverless container allow-unauthenticated-invoke "$CONTAINER"

printf 'Проверяю health... '
HEALTH_OK=no
for _ in $(seq 1 12); do
  if curl -fsS -m 20 "$BOT_URL/health" 2>/dev/null | grep -q '"status":"ok"'; then
    HEALTH_OK=yes
    echo "отвечает"
    break
  fi
  sleep 5
done
[ "$HEALTH_OK" = yes ] || die "контейнер не ответил на health"

WEBHOOK_RESPONSE=$(curl -fsS -m 30 -X POST \
  "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" \
  --data-urlencode "url=$BOT_URL/telegram/webhook" \
  --data-urlencode "secret_token=$WEBHOOK_SECRET" \
  --data-urlencode 'allowed_updates=["message","callback_query"]')
printf '%s' "$WEBHOOK_RESPONSE" | python3 -c \
  'import json,sys;data=json.load(sys.stdin);data.get("ok") or sys.exit("Telegram rejected setWebhook");print("Telegram webhook: настроен")'

unset BOT_TOKEN WEBHOOK_SECRET BOT_INFO CURRENT_PAYLOAD GOST_PAYLOAD GOST_API_KEY BOT_GOST_KEY 2>/dev/null || true

[ "$GRANT_FAILED" = 0 ] || die "часть прав не выдана — см. сообщения выше"
printf '\nГотово: https://t.me/%s\nWebhook: %s/telegram/webhook\n' "$BOT_NAME" "$BOT_URL"
if [ -z "$ALLOWED_IDS" ]; then
  cat <<'NEXT'

Белый список пока пуст. Отправьте боту /id, затем повторите:
  TELEGRAM_ALLOWED_USER_IDS=<ваш-id> ./scripts/yc-telegram-bot.sh
NEXT
fi

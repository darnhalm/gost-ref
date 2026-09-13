#!/usr/bin/env bash
# Заводит ВТОРОЙ контейнер gost-ref — без авторизации, для клиентов, которые
# не умеют передавать заголовок с токеном (ChatGPT).
#
#   ./scripts/yc-open-container.sh
#
# Основной контейнер (gost-ref) при этом не трогается и остаётся закрытым
# токеном. Образ используется тот же, собранный CI.
#
# Что это значит по-честному: адрес будет открыт для всех, кто его знает.
# Сервер ничего вашего не отдаёт — форматирует переданные ему поля и ходит
# в открытые библиографические базы; чтение файлов в удалённом режиме
# отключено, сервис метаданных отключён. Единственная плата — ваши
# вычисления, и она ограничена лимитами ниже.

set -euo pipefail

CONTAINER=${CONTAINER:-gost-ref-open}
REGISTRY=${REGISTRY:-gost-ref}
SA=${SA:-gost-ref-sa}
TAG=${TAG:-latest}

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\nОшибка: %s\n' "$*" >&2; exit 1; }
jget() { python3 -c 'import sys,json;d=json.load(sys.stdin);
[d:=d.get(k,{}) for k in sys.argv[1].split(".")];print(d if isinstance(d,str) else "")' "$1"; }

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

REGISTRY_ID=$(yc container registry get --name "$REGISTRY" --format json 2>/dev/null | jget id)
[ -n "$REGISTRY_ID" ] || die "не найден реестр $REGISTRY — сначала ./scripts/yc-bootstrap.sh"
SA_ID=$(yc iam service-account get --name "$SA" --format json 2>/dev/null | jget id)
[ -n "$SA_ID" ] || die "не найден сервисный аккаунт $SA"

if ! yc serverless container get --name "$CONTAINER" >/dev/null 2>&1; then
  say "Создаю контейнер $CONTAINER"
  yc serverless container create --name "$CONTAINER" >/dev/null
fi
CONTAINER_ID=$(yc serverless container get --name "$CONTAINER" --format json | jget id)
URL="https://$CONTAINER_ID.containers.yandexcloud.net"

# Лимиты жёстче, чем у закрытого контейнера: сюда может постучаться кто угодно.
say "Выкладываю ревизию без авторизации"
yc serverless container revision deploy \
  --container-name "$CONTAINER" \
  --image "cr.yandex/$REGISTRY_ID/gost-ref:$TAG" \
  --service-account-id "$SA_ID" \
  --cores 1 --memory 512MB \
  --concurrency 8 \
  --execution-timeout 120s \
  --zone-instances-limit 1 \
  --zone-requests-limit 8 \
  --metadata-options aws-v1-http-endpoint=disabled,gce-http-endpoint=disabled \
  --environment GOST_REF_TRANSPORT=streamable-http \
  --environment GOST_REF_MCP_PATH=/mcp \
  --environment GOST_REF_ALLOW_ANONYMOUS=1 \
  --environment GOST_REF_LOOKUP_TIMEOUT=10 \
  --environment GOST_REF_MAX_ITEMS=100 \
  >/dev/null

say "Открываю публичный вызов"
grant "публичный вызов" yc serverless container allow-unauthenticated-invoke "$CONTAINER"

printf '\nПроверяю health... '
for _ in $(seq 1 10); do
  if curl -fsS -m 20 "$URL/health" 2>/dev/null | grep -q '"status":"ok"'; then
    echo "отвечает"; break
  fi
  sleep 5
done

printf 'Проверяю MCP без токена... '
CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 60 -X POST "$URL/mcp" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}')
[ "$CODE" = "200" ] || die "ожидал 200, получил $CODE"
echo "отвечает"

if [ "$GRANT_FAILED" = "1" ]; then
  printf '\n\033[1mВНИМАНИЕ: часть прав не выдана — см. строки «НЕ ВЫДАНО» выше.\033[0m\n'
fi

cat <<INFO

Готово. Адрес для ChatGPT:

  $URL/mcp

Авторизация при добавлении коннектора — No Authentication.

Закрыть этот контейнер, когда он больше не нужен:
  yc serverless container deny-unauthenticated-invoke $CONTAINER

Удалить совсем:
  yc serverless container delete $CONTAINER

Обновить после пересборки образа — запустить этот скрипт ещё раз.
INFO

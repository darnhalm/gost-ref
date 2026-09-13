#!/usr/bin/env bash
# Выкладывает новую ревизию контейнера из образа, собранного GitHub Actions.
#
#   ./scripts/deploy-revision.sh
#
# Все идентификаторы берутся из облака, руками ничего подставлять не надо.
# Образ собирает и пушит CI; выкладка делается отсюда, потому что у
# сервисного аккаунта деплоя DeployRevision отвечает PERMISSION_DENIED при
# всех выданных ролях, а причина пока не установлена. Ваших прав хватает.
#
# Служебный сервис метаданных для ревизии отключён. Через него изнутри
# контейнера можно получить IAM-токен сервисного аккаунта ревизии — это
# единственный путь, по которому дыра в коде сервера превратилась бы в
# доступ к реестру и секрету. Серверу метаданные не нужны: токен приезжает
# переменной окружения при выкладке, а в облачные API он не ходит.

set -euo pipefail

CONTAINER=${CONTAINER:-gost-ref}
REGISTRY=${REGISTRY:-gost-ref}
SA=${SA:-gost-ref-sa}
SECRET=${SECRET:-gost-ref-api-key}
TAG=${TAG:-latest}

die() { printf '\nОшибка: %s\n' "$*" >&2; exit 1; }
jget() { python3 -c 'import sys,json;d=json.load(sys.stdin);
[d:=d.get(k,{}) for k in sys.argv[1].split(".")];print(d if isinstance(d,str) else "")' "$1"; }

command -v yc >/dev/null || die "не найден yc"
command -v python3 >/dev/null || die "не найден python3"

REGISTRY_ID=$(yc container registry get --name "$REGISTRY" --format json 2>/dev/null | jget id)
[ -n "$REGISTRY_ID" ] || die "не найден реестр $REGISTRY"
SA_ID=$(yc iam service-account get --name "$SA" --format json 2>/dev/null | jget id)
[ -n "$SA_ID" ] || die "не найден сервисный аккаунт $SA"

SECRET_JSON=$(yc lockbox secret get --name "$SECRET" --format json 2>/dev/null)
SECRET_ID=$(printf '%s' "$SECRET_JSON" | jget id)
VERSION_ID=$(printf '%s' "$SECRET_JSON" | jget current_version.id)
[ -n "$SECRET_ID" ] || die "не найден секрет $SECRET"

CONTAINER_JSON=$(yc serverless container get --name "$CONTAINER" --format json 2>/dev/null)
CONTAINER_ID=$(printf '%s' "$CONTAINER_JSON" | jget id)
[ -n "$CONTAINER_ID" ] || die "не найден контейнер $CONTAINER"
URL="https://$CONTAINER_ID.containers.yandexcloud.net"

printf '\nВыкладываю %s из cr.yandex/%s/gost-ref:%s\n\n' "$CONTAINER" "$REGISTRY_ID" "$TAG"

yc serverless container revision deploy \
  --container-name "$CONTAINER" \
  --image "cr.yandex/$REGISTRY_ID/gost-ref:$TAG" \
  --service-account-id "$SA_ID" \
  --cores 1 --memory 512MB \
  --concurrency 16 \
  --execution-timeout 120s \
  --zone-instances-limit 2 \
  --zone-requests-limit 20 \
  --secret "environment-variable=GOST_REF_API_KEY,id=$SECRET_ID,version-id=$VERSION_ID,key=api-key" \
  --metadata-options aws-v1-http-endpoint=disabled,gce-http-endpoint=disabled \
  --environment GOST_REF_TRANSPORT=streamable-http \
  --environment GOST_REF_MCP_PATH=/mcp \
  --environment GOST_REF_LOOKUP_TIMEOUT=10 \
  --environment GOST_REF_MAX_ITEMS=200 \
  >/dev/null

printf '\nПроверяю health... '
for _ in $(seq 1 10); do
  if curl -fsS -m 20 "$URL/health" 2>/dev/null | grep -q '"status":"ok"'; then
    echo "отвечает"
    printf '\nMCP: %s/mcp\n' "$URL"
    exit 0
  fi
  sleep 5
done
echo "НЕ отвечает"
die "ревизия выложена, но сервер не ответил. Логи: yc logging read --folder-id \$(yc config get folder-id) --filter 'resource_id=\"$CONTAINER_ID\"'"

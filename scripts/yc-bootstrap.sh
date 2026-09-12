#!/usr/bin/env bash
# Заводит инфраструктуру gost-ref в Yandex Cloud: реестр, контейнер, два
# сервисных аккаунта, секрет Lockbox и публичный вызов. Образ не собирает —
# первую ревизию выкладывает GitHub Actions, локальный Docker не нужен.
#
#   yc config set folder-id <ваш folder-id>
#   ./scripts/yc-bootstrap.sh
#
# Скрипт идемпотентен: повторный запуск ничего не ломает и не пересоздаёт.
# Всё, что он создаёт, можно переименовать переменными окружения:
#   CONTAINER=gost-ref REGISTRY=gost-ref SA=gost-ref-sa DEPLOYER=gost-ref-deployer

set -euo pipefail

CONTAINER=${CONTAINER:-gost-ref}
REGISTRY=${REGISTRY:-gost-ref}
SA=${SA:-gost-ref-sa}
DEPLOYER=${DEPLOYER:-gost-ref-deployer}
SECRET=${SECRET:-gost-ref-api-key}

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\nОшибка: %s\n' "$*" >&2; exit 1; }
jget() { python3 -c 'import sys,json;d=json.load(sys.stdin);
[d:=d.get(k,{}) for k in sys.argv[1].split(".")];print(d if isinstance(d,str) else "")' "$1"; }

command -v yc >/dev/null || die "не найден yc. Установка: https://yandex.cloud/ru/docs/cli/quickstart"
command -v python3 >/dev/null || die "не найден python3 — он нужен для разбора ответов yc"

FOLDER_ID=$(yc config get folder-id 2>/dev/null || true)
[ -n "$FOLDER_ID" ] || die "не задан каталог. Выполните: yc config set folder-id <folder-id>"
say "Каталог: $FOLDER_ID"

# --------------------------------------------------------------------------
# Реестр образов
# --------------------------------------------------------------------------
if ! yc container registry get --name "$REGISTRY" >/dev/null 2>&1; then
  say "Создаю реестр $REGISTRY"
  yc container registry create --name "$REGISTRY" >/dev/null
fi
REGISTRY_ID=$(yc container registry get --name "$REGISTRY" --format json | jget id)
echo "реестр: $REGISTRY_ID"

# --------------------------------------------------------------------------
# Контейнер (пока без ревизий — первую выложит GitHub Actions)
# --------------------------------------------------------------------------
if ! yc serverless container get --name "$CONTAINER" >/dev/null 2>&1; then
  say "Создаю контейнер $CONTAINER"
  yc serverless container create --name "$CONTAINER" >/dev/null
fi
CONTAINER_ID=$(yc serverless container get --name "$CONTAINER" --format json | jget id)
echo "контейнер: $CONTAINER_ID"

# --------------------------------------------------------------------------
# Сервисный аккаунт ревизии: только тянуть образ и читать секрет
# --------------------------------------------------------------------------
if ! yc iam service-account get --name "$SA" >/dev/null 2>&1; then
  say "Создаю сервисный аккаунт ревизии $SA"
  yc iam service-account create --name "$SA" >/dev/null
fi
SA_ID=$(yc iam service-account get --name "$SA" --format json | jget id)
yc container registry add-access-binding --id "$REGISTRY_ID" \
  --role container-registry.images.puller --service-account-id "$SA_ID" >/dev/null 2>&1 || true
echo "аккаунт ревизии: $SA_ID"

# --------------------------------------------------------------------------
# Сервисный аккаунт деплоя: пушить образ и выкладывать ревизии
# --------------------------------------------------------------------------
if ! yc iam service-account get --name "$DEPLOYER" >/dev/null 2>&1; then
  say "Создаю сервисный аккаунт деплоя $DEPLOYER"
  yc iam service-account create --name "$DEPLOYER" >/dev/null
fi
DEPLOYER_ID=$(yc iam service-account get --name "$DEPLOYER" --format json | jget id)
for role in container-registry.images.pusher serverless-containers.editor iam.serviceAccounts.user; do
  yc resource-manager folder add-access-binding "$FOLDER_ID" \
    --role "$role" --service-account-id "$DEPLOYER_ID" >/dev/null 2>&1 || true
done
echo "аккаунт деплоя: $DEPLOYER_ID"

# --------------------------------------------------------------------------
# Токен доступа в Lockbox. Существующий секрет не трогаем: перевыпуск ключа
# оборвал бы всех уже подключённых клиентов.
# --------------------------------------------------------------------------
if yc lockbox secret get --name "$SECRET" >/dev/null 2>&1; then
  say "Секрет $SECRET уже есть — оставляю как есть"
  NEW_KEY=""
else
  say "Создаю секрет $SECRET"
  NEW_KEY=$(python3 -c 'import secrets;print(secrets.token_hex(32))')
  yc lockbox secret create --name "$SECRET" \
    --payload "[{'key':'api-key','text_value':'$NEW_KEY'}]" >/dev/null
fi
SECRET_JSON=$(yc lockbox secret get --name "$SECRET" --format json)
SECRET_ID=$(printf '%s' "$SECRET_JSON" | jget id)
VERSION_ID=$(printf '%s' "$SECRET_JSON" | jget current_version.id)
yc lockbox secret add-access-binding --id "$SECRET_ID" \
  --role lockbox.payloadViewer --service-account-id "$SA_ID" >/dev/null 2>&1 || true
echo "секрет: $SECRET_ID (версия $VERSION_ID)"

# --------------------------------------------------------------------------
# Публичный вызов. Доступ закрывает Bearer-токен самого сервера: приватный
# контейнер требует IAM-токен в том же заголовке Authorization, а два разных
# Bearer в одном запросе не уживаются.
# --------------------------------------------------------------------------
say "Открываю публичный вызов"
yc serverless container allow-unauthenticated-invoke "$CONTAINER" >/dev/null 2>&1 || true

# --------------------------------------------------------------------------
say "Готово. Значения для GitHub → Settings → Secrets and variables → Actions"
cat <<INFO

Repository variables:
  YC_FOLDER_ID          $FOLDER_ID
  YC_REGISTRY_ID        $REGISTRY_ID
  YC_CONTAINER_NAME     $CONTAINER
  YC_REVISION_SA_ID     $SA_ID
  YC_LOCKBOX_SECRET_ID  $SECRET_ID
  YC_LOCKBOX_VERSION_ID $VERSION_ID

Repository secret:
  YC_SA_ID              $DEPLOYER_ID

Адрес будущего сервера:
  https://$CONTAINER_ID.containers.yandexcloud.net/mcp
  https://$CONTAINER_ID.containers.yandexcloud.net/health
INFO

if [ -n "$NEW_KEY" ]; then
  cat <<KEY

Токен доступа (показан один раз, лежит в Lockbox — можно достать оттуда):
  $NEW_KEY

Подключение клиента после первой выкладки:
  claude mcp add --transport http gost-ref \\
    https://$CONTAINER_ID.containers.yandexcloud.net/mcp \\
    --header "Authorization: Bearer $NEW_KEY"
KEY
fi

cat <<'NEXT'

Осталось связать GitHub с аккаунтом деплоя, чтобы Actions получал IAM-токен
без долгоживущего ключа: в консоли Yandex Cloud — Identity and Access
Management → Federations → Workload Identity, федерация с issuer
https://token.actions.githubusercontent.com, затем федеративный доступ для
аккаунта деплоя с subject вида

  repo:<владелец>/gost-ref:ref:refs/heads/main

Если этот путь окажется неудобным, есть простая замена: создать
авторизованный ключ (yc iam key create --service-account-name gost-ref-deployer
--output key.json), положить его содержимое в секрет YC_SA_JSON_CREDENTIALS и
заменить в .github/workflows/deploy.yml обе строки yc-sa-id на
yc-sa-json-credentials. Ключ долгоживущий — в репозиторий его не коммитить.

Потом: Actions → deploy → Run workflow. Первая ревизия соберётся и выложится
сама, после чего /health должен ответить.
NEXT

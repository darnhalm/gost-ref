# Удалённый MCP-сервер gost-ref

Тот же `server.py`, тот же пакет `gost_ref`. Меняется только способ запуска:
вместо stdio — HTTP-транспорт `streamable-http` MCP SDK.

```
локально   python server.py                              → stdio
удалённо   python server.py --transport streamable-http  → http://HOST:PORT/mcp
```

Ядро остаётся детерминированным и не зависит от режима: инструменты — чистые
функции над переданными полями, между запросами ничего не хранится. Поэтому
контейнер можно убивать в любой момент и держать несколько экземпляров.

## Локальный запуск

```bash
# stdio, как раньше — для Claude Code и локальных MCP-клиентов
python server.py

# HTTP на своей машине: ключ обязателен даже локально
GOST_REF_API_KEY=dev-secret python server.py --transport streamable-http --port 8080

# без ключа — только явным флагом и только для разработки
python server.py --transport streamable-http --allow-anonymous

curl -s localhost:8080/health
# {"status":"ok","service":"gost-ref"}
```

## Docker

```bash
docker build -t gost-ref .

docker run --rm -p 8080:8080 \
  -e PORT=8080 \
  -e GOST_REF_API_KEY="$(openssl rand -hex 32)" \
  gost-ref

# проверка
curl -s localhost:8080/health
curl -s -X POST localhost:8080/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "Authorization: Bearer $GOST_REF_API_KEY" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Образ запускается не от root, работает на файловой системе только для чтения
(`docker run --read-only` проверен) и ничего не пишет на диск.

## Yandex Cloud Serverless Containers

Платформа передаёт порт в `PORT` — сервер его читает, ничего дополнительно
настраивать не нужно. Эндпоинт ревизии: `https://<container-id>.containers.yandexcloud.net`.

### Быстрый путь: один скрипт

`scripts/yc-bootstrap.sh` заводит всё перечисленное ниже за один запуск и
печатает значения для переменных репозитория. Образ он не собирает — первую
ревизию выложит GitHub Actions, локальный Docker не нужен. Повторный запуск
безопасен: существующее не пересоздаётся, токен в Lockbox не перевыпускается.

```bash
yc config set folder-id <folder-id>
./scripts/yc-bootstrap.sh
```

Ниже — то же самое по шагам, если нужно понимать или менять детали.

### Первая выкладка руками

```bash
yc config set folder-id <folder-id>

# 1. Реестр и контейнер
yc container registry create --name gost-ref
REGISTRY_ID=$(yc container registry get --name gost-ref --format json | jq -r .id)
yc serverless container create --name gost-ref
CONTAINER_ID=$(yc serverless container get --name gost-ref --format json | jq -r .id)

# 2. Сервисный аккаунт ревизии: ему нужно только тянуть образ
yc iam service-account create --name gost-ref-sa
SA_ID=$(yc iam service-account get --name gost-ref-sa --format json | jq -r .id)
yc container registry add-access-binding --id "$REGISTRY_ID" \
  --role container-registry.images.puller --service-account-id "$SA_ID"

# 3. Токен доступа — в Lockbox, не в образ и не в репозиторий
API_KEY=$(openssl rand -hex 32)
yc lockbox secret create --name gost-ref-api-key \
  --payload "[{'key':'api-key','text_value':'$API_KEY'}]"
SECRET_ID=$(yc lockbox secret get --name gost-ref-api-key --format json | jq -r .id)
VERSION_ID=$(yc lockbox secret get --name gost-ref-api-key --format json | jq -r .current_version.id)
yc lockbox secret add-access-binding --id "$SECRET_ID" \
  --role lockbox.payloadViewer --service-account-id "$SA_ID"

# 4. Сборка и публикация образа
docker build -t "cr.yandex/$REGISTRY_ID/gost-ref:v1" .
yc container registry configure-docker
docker push "cr.yandex/$REGISTRY_ID/gost-ref:v1"

# 5. Ревизия
yc serverless container revision deploy \
  --container-name gost-ref \
  --image "cr.yandex/$REGISTRY_ID/gost-ref:v1" \
  --service-account-id "$SA_ID" \
  --cores 1 --memory 512MB \
  --concurrency 16 \
  --execution-timeout 120s \
  --secret "environment-variable=GOST_REF_API_KEY,id=$SECRET_ID,version-id=$VERSION_ID,key=api-key" \
  --environment GOST_REF_TRANSPORT=streamable-http \
  --environment GOST_REF_MCP_PATH=/mcp \
  --environment GOST_REF_LOOKUP_TIMEOUT=10 \
  --environment GOST_REF_MAX_ITEMS=200

# 6. Публичный вызов: снаружи контейнер открыт, доступ закрывает Bearer-токен
yc serverless container allow-unauthenticated-invoke gost-ref

echo "MCP URL: https://$CONTAINER_ID.containers.yandexcloud.net/mcp"
curl -s "https://$CONTAINER_ID.containers.yandexcloud.net/health"
```

**Почему `allow-unauthenticated-invoke`, а не IAM Яндекса.** Приватный контейнер
требует в заголовке `Authorization: Bearer <IAM-токен>`, а этот заголовок нужен
самому MCP: два разных Bearer в одном запросе не уживаются, да и IAM-токен живёт
12 часов и его пришлось бы обновлять руками в конфиге клиента. Поэтому доступ
закрывает постоянный токен сервера. Если нужен именно IAM Яндекса — запускайте
сервер с `--allow-anonymous` и не открывайте контейнер публично; клиенту тогда
придётся подставлять свежий IAM-токен.

### Обновление через GitHub Actions

`.github/workflows/deploy.yml` на каждый push в `main`, затрагивающий код или
образ: прогоняет тесты, собирает образ, пушит в Container Registry и выкладывает
новую ревизию. Авторизация — Workload Identity Federation (обмен GitHub-токена
на IAM), долгоживущий ключ в секретах репозитория не нужен.

Связать сервисный аккаунт деплоя с репозиторием:

```bash
yc iam workload-identity federation create \
  --name github --issuer https://token.actions.githubusercontent.com \
  --audiences https://github.com/<owner>
# затем привязать subject вида repo:<owner>/gost-ref:ref:refs/heads/main
# к сервисному аккаунту деплоя (роли: container-registry.images.pusher,
# serverless-containers.editor, iam.serviceAccounts.user)
```

Переменные репозитория (`vars`): `YC_FOLDER_ID`, `YC_REGISTRY_ID`,
`YC_CONTAINER_NAME`, `YC_REVISION_SA_ID`, `YC_LOCKBOX_SECRET_ID`,
`YC_LOCKBOX_VERSION_ID`. Секрет (`secrets`): `YC_SA_ID`.

## Тот же образ на других платформах

Образ ничем к Яндексу не привязан: слушает `$PORT` на `0.0.0.0`, читает
конфигурацию из окружения, ничего не пишет на диск.

| Платформа | Что учесть |
|---|---|
| Google Cloud Run | `gcloud run deploy gost-ref --source . --port 8080 --set-secrets GOST_REF_API_KEY=gost-ref-key:latest --timeout 120`. Работает без правок. |
| Railway | Docker-образ, `PORT` подставляется сам. Работает без правок. |
| Render | Web Service из Dockerfile, `PORT` подставляется сам; health check — `/health`. |
| Fly.io | `fly launch --dockerfile`; в `fly.toml` задать `internal_port = 8080`. Масштабирование до нуля включается отдельно. |
| Azure Container Apps | Ingress на 8080, секрет — из Key Vault. Работает без правок. |
| AWS App Runner | Порт указывается в конфигурации сервиса; `PORT` App Runner не передаёт, поэтому либо укажите 8080, либо задайте `PORT` переменной окружения. |

## Подключение клиента

```bash
claude mcp add --transport http gost-ref \
  https://<container-id>.containers.yandexcloud.net/mcp \
  --header "Authorization: Bearer <GOST_REF_API_KEY>"
```

Клиенты, которые не дают задать заголовок (веб-интерфейс claude.ai для
собственных коннекторов), требуют OAuth — для них перед сервером ставится
шлюз, терминирующий OAuth. Сам сервер намеренно не публикует метаданные
OAuth: увидев их, некоторые клиенты перестают отправлять настроенный
заголовок и пытаются пройти неподдерживаемый поток авторизации.

## Переменные окружения

| Переменная | По умолчанию | Зачем |
|---|---|---|
| `PORT` | 8080 | порт HTTP; подставляет платформа |
| `HOST` | 0.0.0.0 | интерфейс |
| `GOST_REF_TRANSPORT` | stdio | `streamable-http` для удалённого режима |
| `GOST_REF_MCP_PATH` | /mcp | путь MCP-эндпоинта |
| `GOST_REF_API_KEY` | — | токен доступа; без него HTTP не стартует |
| `GOST_REF_ALLOW_ANONYMOUS` | — | `1` — разрешить HTTP без токена (разработка) |
| `GOST_REF_PDF_DIR` | — | каталог, из которого `read_pdf_metadata` читает файлы; без него инструмент в HTTP-режиме отвечает отказом |
| `GOST_REF_PDF_MAX_BYTES` | 67108864 | потолок размера PDF |
| `GOST_REF_LOOKUP_TIMEOUT` | 20 (в образе 10) | таймаут одного запроса к внешней базе |
| `GOST_REF_MAX_ITEMS` | 0 (в образе 200) | потолок числа описаний в `build_bibliography`; 0 — без ограничения |
| `GOST_REF_JSON_RESPONSE` | — | `1` — отвечать обычным JSON вместо SSE |
| `GOST_REF_LOG_LEVEL` | INFO | уровень логов |

## Холодный старт

Замерено на образе выше: импорт `mcp` и `gost_ref` — 1,1 с, до первого ответа
`/health` — около 1,7 с вместе с запуском контейнера, память под нагрузкой —
42 МиБ. Корпуса `eval/` в образ не попадают, при старте ничего не читается с
диска и не запрашивается по сети: внешние базы работают только внутри вызова
`lookup_metadata`.

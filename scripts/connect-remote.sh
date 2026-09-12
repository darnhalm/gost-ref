#!/usr/bin/env bash
# Подключает развёрнутый удалённый сервер gost-ref к Claude Code один раз —
# на уровне пользователя, то есть во всех проектах и во всех новых чатах.
#
#   ./scripts/connect-remote.sh
#
# Адрес контейнера и токен берутся из Yandex Cloud, руками ничего вводить не
# надо. Токен нигде не сохраняется, кроме конфигурации самого клиента.

set -euo pipefail

CONTAINER=${CONTAINER:-gost-ref}
SECRET=${SECRET:-gost-ref-api-key}
NAME=${NAME:-gost-ref}
SCOPE=${SCOPE:-user}

die() { printf '\nОшибка: %s\n' "$*" >&2; exit 1; }

command -v yc >/dev/null || die "не найден yc"
command -v python3 >/dev/null || die "не найден python3"

URL=$(yc serverless container get --name "$CONTAINER" --format json 2>/dev/null |
  python3 -c 'import sys,json
d=json.load(sys.stdin)
print((d.get("url") or ("https://%s.containers.yandexcloud.net" % d.get("id",""))).rstrip("/"))')
[ -n "$URL" ] || die "не найден контейнер $CONTAINER — сначала ./scripts/yc-bootstrap.sh"

TOKEN=$(yc lockbox payload get --name "$SECRET" --format json 2>/dev/null |
  python3 -c 'import sys,json
d=json.load(sys.stdin)
print(next((e.get("text_value","") for e in d.get("entries") or [] if e.get("key")=="api-key"), ""))')
[ -n "$TOKEN" ] || die "не удалось прочитать ключ api-key из секрета $SECRET"

printf '\nСервер: %s/mcp\n' "$URL"

printf 'Проверяю health... '
if curl -fsS -m 20 "$URL/health" | grep -q '"status":"ok"'; then
  echo "отвечает"
else
  echo "НЕ отвечает"
  die "ревизия ещё не выложена. Actions → deploy → Run workflow, затем повторите."
fi

if ! command -v claude >/dev/null; then
  cat <<MANUAL

Claude Code не найден. Команда для подключения вручную:

  claude mcp add --transport http $NAME --scope $SCOPE $URL/mcp \\
    --header "Authorization: Bearer $TOKEN"

Для других клиентов: тот же адрес и тот же заголовок Authorization.
MANUAL
  exit 0
fi

claude mcp remove "$NAME" --scope "$SCOPE" >/dev/null 2>&1 || true
claude mcp add --transport http "$NAME" --scope "$SCOPE" "$URL/mcp" \
  --header "Authorization: Bearer $TOKEN"

cat <<DONE

Подключено на уровне «$SCOPE» — сервер доступен во всех проектах и во всех
новых чатах, повторять не нужно. Проверка: claude mcp list

Осталось сохранить навык, если он ещё не сохранён: попросите Claude прочитать
skill/SKILL.md и сохранить как навык. MCP отдаёт инструменты, но не порядок
работы с ними — порядок описан в навыке и в AGENTS.md.
DONE

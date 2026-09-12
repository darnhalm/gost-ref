#!/usr/bin/env bash
# Связывает GitHub Actions с сервисным аккаунтом деплоя через Workload
# Identity Federation: Actions получает IAM-токен в обмен на свой OIDC-токен,
# долгоживущий ключ в секретах репозитория не нужен.
#
#   ./scripts/yc-github-federation.sh
#
# Владелец и имя репозитория берутся из origin, аккаунт деплоя — из bootstrap.
# Скрипт идемпотентен: существующие федерация и привязки не дублируются.
# Переопределить: DEPLOYER=имя FEDERATION=имя ./scripts/yc-github-federation.sh

set -euo pipefail

DEPLOYER=${DEPLOYER:-gost-ref-deployer}

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\nОшибка: %s\n' "$*" >&2; exit 1; }

command -v yc >/dev/null || die "не найден yc"
command -v python3 >/dev/null || die "не найден python3"
command -v git >/dev/null || die "не найден git"

# --------------------------------------------------------------------------
# Владелец и репозиторий из origin: и https, и ssh
# --------------------------------------------------------------------------
ORIGIN=$(git config --get remote.origin.url) || die "нет remote origin"
SLUG=$(printf '%s' "$ORIGIN" | sed -E 's#^git@[^:]+:##; s#^https?://[^/]+/##; s#\.git$##')
OWNER=${SLUG%%/*}
REPO=${SLUG##*/}
[ -n "$OWNER" ] && [ -n "$REPO" ] || die "не разобрал origin: $ORIGIN"
FEDERATION=${FEDERATION:-github-$REPO}
say "Репозиторий: $OWNER/$REPO"

SA_ID=$(yc iam service-account get --name "$DEPLOYER" --format json |
  python3 -c 'import sys,json;print(json.load(sys.stdin).get("id",""))')
[ -n "$SA_ID" ] || die "не найден сервисный аккаунт $DEPLOYER — сначала ./scripts/yc-bootstrap.sh"
echo "аккаунт деплоя: $SA_ID"

# --------------------------------------------------------------------------
# Федерация
# --------------------------------------------------------------------------
find_federation() {
  yc iam workload-identity oidc federation list --format json 2>/dev/null |
    python3 -c 'import sys,json
items=json.load(sys.stdin) or []
print(next((i["id"] for i in items if i.get("name")==sys.argv[1]), ""))' "$FEDERATION"
}

FED_ID=$(find_federation)
if [ -z "$FED_ID" ]; then
  say "Создаю федерацию $FEDERATION"
  yc iam workload-identity oidc federation create \
    --name "$FEDERATION" \
    --issuer "https://token.actions.githubusercontent.com" \
    --audiences "https://github.com/$OWNER" \
    --jwks-url "https://token.actions.githubusercontent.com/.well-known/jwks" >/dev/null
  FED_ID=$(find_federation)
fi
[ -n "$FED_ID" ] || die "федерация не создалась"
echo "федерация: $FED_ID"

# --------------------------------------------------------------------------
# Привязки. Subject привязан к ветке, поэтому заводим две: текущую ветку —
# чтобы запустить деплой вручную и проверить сервер до мержа, и main — для
# обычной работы после него.
# --------------------------------------------------------------------------
BRANCH=$(git branch --show-current 2>/dev/null || echo main)
EXISTING=$(yc iam workload-identity federated-credential list \
  --service-account-id "$SA_ID" --format json 2>/dev/null |
  python3 -c 'import sys,json
items=json.load(sys.stdin) or []
print("\n".join(i.get("external_subject_id","") for i in items))' || true)

for ref in "$BRANCH" main; do
  [ -n "$ref" ] || continue
  SUBJECT="repo:$OWNER/$REPO:ref:refs/heads/$ref"
  if printf '%s\n' "$EXISTING" | grep -Fxq "$SUBJECT"; then
    echo "привязка уже есть: $SUBJECT"
    continue
  fi
  say "Привязываю ветку $ref"
  yc iam workload-identity federated-credential create \
    --service-account-id "$SA_ID" \
    --federation-id "$FED_ID" \
    --external-subject-id "$SUBJECT" >/dev/null
  echo "$SUBJECT"
  EXISTING="$EXISTING
$SUBJECT"
done

say "Готово"
cat <<NEXT

Проверьте, что в GitHub → Settings → Secrets and variables → Actions лежит
секрет YC_SA_ID со значением $SA_ID, а во вкладке Variables — значения,
напечатанные bootstrap-скриптом.

Затем: Actions → deploy → Run workflow, ветка $BRANCH.
Первая ревизия соберётся и выложится сама.
NEXT

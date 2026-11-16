#!/usr/bin/env bash
# Interactive control panel for cloud and local search modes.

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SERVICE=${KEYCHAIN_SERVICE:-gost-ref Telegram Bot}
GATEWAY=${TELEGRAM_GATEWAY_NAME:-gost-ref-telegram}

pause_menu() {
  printf '\n'
  read -r -p "Нажмите Enter, чтобы вернуться в меню..." _
}

show_status() {
  printf '\nСостояние поиска\n'
  if pgrep -f '/telegram_polling.py$' >/dev/null 2>&1; then
    echo "• Telegram: локальный резерв работает на этом Mac"
    echo "• Облачный webhook временно отключён"
    return
  fi

  echo "• Локальный резерв Telegram не запущен"
  if ! command -v security >/dev/null || ! command -v yc >/dev/null || ! command -v curl >/dev/null; then
    echo "• Облачный webhook: не удалось проверить зависимости"
    return
  fi

  local token gateway_domain expected_url info
  token=$(security find-generic-password -a bot-token -s "$SERVICE" -w 2>/dev/null) || {
    echo "• Облачный webhook: токен не найден в Keychain"
    return
  }
  gateway_domain=$(yc serverless api-gateway get --name "$GATEWAY" --format json 2>/dev/null \
    | python3 -c 'import json,sys;print(json.load(sys.stdin).get("domain", ""))')
  expected_url="https://$gateway_domain/telegram/webhook"
  info=$(curl -fsS --max-time 30 "https://api.telegram.org/bot${token}/getWebhookInfo") || {
    echo "• Облачный webhook: Telegram API не ответил"
    unset token
    return
  }
  EXPECTED_URL="$expected_url" python3 -c '
import json, os, sys
d = json.load(sys.stdin).get("result", {})
url = d.get("url", "")
pending = d.get("pending_update_count", 0)
if url == os.environ.get("EXPECTED_URL"):
    print(f"• Telegram: облачный webhook включён; сообщений в очереди: {pending}")
elif url:
    print(f"• Telegram: настроен другой webhook; сообщений в очереди: {pending}")
else:
    print(f"• Telegram: webhook отсутствует; сообщений в очереди: {pending}")
' <<<"$info"
  unset token info
}

while true; do
  clear
  cat <<'MENU'
УПРАВЛЕНИЕ ПОИСКОМ

1 — Прогреть облачный поиск
2 — Запустить локальный резерв Telegram
3 — Аварийно восстановить облачный Telegram
4 — Проверить текущее состояние
0 — Закрыть

Прогрев не переключает режим. При запуске локального резерва
Telegram переключается на Mac автоматически, а Ctrl+C автоматически
возвращает облачный webhook. Пункт 3 нужен только после аварийного сбоя.
MENU
  printf '\n'
  read -r -p "Выберите действие: " choice

  case "$choice" in
    1)
      "$ROOT/scripts/warm-cloud.sh"
      pause_menu
      ;;
    2)
      if pgrep -f '/telegram_polling.py$' >/dev/null 2>&1; then
        echo "Локальный резерв уже запущен."
        pause_menu
        continue
      fi
      echo "Запускаю локальный резерв. Для остановки нажмите Ctrl+C."
      echo "После остановки облачный webhook будет восстановлен автоматически."
      printf '\n'
      "$ROOT/scripts/run-telegram-polling.sh"
      pause_menu
      ;;
    3)
      "$ROOT/scripts/telegram-cloud-mode.sh"
      pause_menu
      ;;
    4)
      show_status
      pause_menu
      ;;
    0)
      exit 0
      ;;
    *)
      echo "Введите 0, 1, 2, 3 или 4."
      pause_menu
      ;;
  esac
done

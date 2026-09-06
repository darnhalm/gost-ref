#!/usr/bin/env bash
# Проверка полноты репозитория перед пушем.
# Блокирует пуш, если тесты падают или в комплекте чего-то не хватает.
# Отсутствие pytest пуш НЕ блокирует — тесты просто пропускаются.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
fail=0

if python3 -c "import pytest" 2>/dev/null; then
  out=$(python3 -m pytest -q 2>&1)
  count=$(printf '%s\n' "$out" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' | head -1)
  if [ -z "$count" ]; then
    echo "x тесты не проходят:"; printf '%s\n' "$out" | tail -5; fail=1
  else
    echo "v тесты: $count passed"
    grep -q "$count passed" INSTALL.md \
      && echo "v INSTALL.md: число тестов совпадает" \
      || { echo "x INSTALL.md не указывает \"$count passed\" — обнови число тестов"; fail=1; }
  fi
else
  echo "~ pytest не установлен — тесты пропущены (pip install pytest для полной проверки)"
fi

if [ ! -f skill/SKILL.md ]; then
  echo "x нет skill/SKILL.md"; fail=1
elif ! grep -q "git clone -q https://github.com/darnhalm/gost-ref.git" skill/SKILL.md; then
  echo "x skill/SKILL.md без строки самонастройки-клона"; fail=1
else
  echo "v skill/SKILL.md на месте"
fi

[ -f AGENTS.md ] && echo "v AGENTS.md на месте" || { echo "x нет AGENTS.md"; fail=1; }

echo "- напоминание: если менял навык, обнови skill/SKILL.md под актуальную версию"

if [ "$fail" -ne 0 ]; then echo "PREFLIGHT: НЕ ПРОШЁЛ — пуш заблокирован"; exit 1; fi
echo "PREFLIGHT: ок"

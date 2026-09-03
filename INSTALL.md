# Установка за две минуты

1. Распакуйте архив, например в `~/gost-ref`.
2. Установите:

```bash
cd ~/gost-ref
pip install -e ".[all]"
python3 -m pytest tests/ -q     # должно быть 42 passed
```

3. Подключите MCP-сервер. В `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "gost-ref": {
      "command": "python3",
      "args": ["/Users/<вы>/gost-ref/server.py"]
    }
  }
}
```

Путь должен быть полным. После правки конфига перезапустите приложение.

4. Проверка без MCP:

```bash
gost-ref reformat -s 7.0.100 "Иванов И.И. Заглавие. М., 2020. 100 с."
```

Навык (SKILL.md) ищет пакет в `~/gost-ref`. Если распаковали в другое место —
поправьте путь в первой команде навыка.

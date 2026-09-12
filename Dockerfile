# gost-ref — remote MCP (streamable-http) для serverless-контейнеров.
# Ядро `gost_ref` — чистая стандартная библиотека; в образ ставится только
# MCP SDK и pypdf. Тесты, eval-корпуса и git в образ не попадают (.dockerignore).

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Зависимости отдельным слоем: код меняется часто, версии — редко.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Код. Сначала пакет, затем обвязка — по той же причине.
COPY gost_ref/ ./gost_ref/
COPY references/ ./references/
COPY skill/ ./skill/
COPY server.py AGENTS.md README.md LICENSE ./

# Запуск не от root. Каталог для PDF отдаётся пользователю: файлы в нём
# временные и живут ровно столько, сколько живёт контейнер.
RUN useradd --system --uid 10001 --create-home --home-dir /home/gostref gostref \
    && mkdir -p /tmp/gost-ref-pdf \
    && chown gostref:gostref /tmp/gost-ref-pdf
USER gostref

# PORT платформа переопределяет своим значением.
ENV PORT=8080 \
    HOST=0.0.0.0 \
    GOST_REF_TRANSPORT=streamable-http \
    GOST_REF_MCP_PATH=/mcp \
    GOST_REF_LOOKUP_TIMEOUT=10 \
    GOST_REF_MAX_ITEMS=200

EXPOSE 8080

# GOST_REF_API_KEY не задаётся в образе: секрет приходит из окружения
# платформы. Без него сервер откажется стартовать по HTTP.
CMD ["python", "server.py", "--transport", "streamable-http"]

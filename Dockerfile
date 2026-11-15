# gost-ref — remote MCP (streamable-http) для serverless-контейнеров.
# Ядро `gost_ref` — чистая стандартная библиотека; в образ ставится только
# MCP SDK и pypdf. Тесты, eval-корпуса и git в образ не попадают (.dockerignore).

ARG TARGETARCH

FROM debian:bookworm-slim AS anna-client

ARG TARGETARCH
ARG ANNA_MCP_VERSION=0.8.2

# Клиент каталога зафиксирован по версии и SHA-256. В финальный образ
# попадают только бинарник и его лицензия, без curl и архива.
RUN ANNA_ARCH="${TARGETARCH:-amd64}" \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && case "$ANNA_ARCH" in \
         amd64) ANNA_SHA="c83f018cffcc2b4603ab32901e76f4b1287e88c361c27f6156dce2a921a7cff3" ;; \
         arm64) ANNA_SHA="0a135dba5764573a34b78ebf9ff50b89638307fef4c4dacf6bba2a9cd5c4a8ad" ;; \
         *) echo "unsupported annas-mcp architecture: $ANNA_ARCH" >&2; exit 1 ;; \
       esac \
    && ARCHIVE="annas-mcp_${ANNA_MCP_VERSION}_linux_${ANNA_ARCH}.tar.gz" \
    && curl -fL --retry 3 --connect-timeout 15 \
       -o "/tmp/$ARCHIVE" \
       "https://github.com/SokolskyNikita/annas-mcp/releases/download/v${ANNA_MCP_VERSION}/$ARCHIVE" \
    && echo "$ANNA_SHA  /tmp/$ARCHIVE" | sha256sum -c - \
    && mkdir -p /tmp/anna /out/licenses \
    && tar -xzf "/tmp/$ARCHIVE" -C /tmp/anna \
    && install -m 0755 "/tmp/anna/annas-mcp_${ANNA_MCP_VERSION}_linux_${ANNA_ARCH}/annas-mcp" /out/annas-mcp \
    && install -m 0644 "/tmp/anna/annas-mcp_${ANNA_MCP_VERSION}_linux_${ANNA_ARCH}/LICENSE" /out/licenses/LICENSE \
    && /out/annas-mcp --version | grep -qx "v${ANNA_MCP_VERSION}"


FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY --from=anna-client /out/annas-mcp /usr/local/bin/annas-mcp
COPY --from=anna-client /out/licenses/LICENSE /usr/share/licenses/annas-mcp/LICENSE

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
    && chown -R gostref:gostref /app /tmp/gost-ref-pdf \
    && chmod -R u=rwX,go=rX /app
USER gostref

# PORT платформа переопределяет своим значением.
ENV PORT=8080 \
    HOST=0.0.0.0 \
    GOST_REF_TRANSPORT=streamable-http \
    GOST_REF_MCP_PATH=/mcp \
    GOST_REF_LOOKUP_TIMEOUT=10 \
    GOST_REF_CATALOG_TIMEOUT=60 \
    ANNAS_MCP_PATH=/usr/local/bin/annas-mcp \
    ANNAS_MCP_CACHE_DIR=/tmp/annas-mcp-cache \
    GOST_REF_MAX_ITEMS=200

EXPOSE 8080

# GOST_REF_API_KEY и ANNAS_SECRET_KEY не задаются в образе: оба
# приходят из Lockbox в окружение ревизии.
CMD ["python", "server.py", "--transport", "streamable-http"]

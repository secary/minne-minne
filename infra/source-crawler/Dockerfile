FROM ghcr.io/astral-sh/uv:0.11.5 AS uv

FROM python:3.12-slim-bookworm AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

FROM python:3.12-slim-bookworm
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MINNE_RAW_DIR=/app/knowledge/raw
WORKDIR /app
RUN groupadd --gid 1000 crawler \
    && useradd --uid 1000 --gid crawler --no-create-home crawler \
    && mkdir -p /app/knowledge/raw \
    && chown crawler:crawler /app/knowledge/raw
COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini ./
COPY backend ./backend
COPY --chmod=755 infra/source-crawler/entrypoint.sh /usr/local/bin/source-crawler
USER crawler
ENTRYPOINT ["/usr/local/bin/source-crawler"]
CMD ["python", "-m", "backend.app.worker.main", "--once"]

FROM python:3.12-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv==0.11.27

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --system --gid 10001 chakravyuh \
    && useradd --system --uid 10001 --gid chakravyuh --home-dir /nonexistent chakravyuh

WORKDIR /app
COPY --from=builder --chown=chakravyuh:chakravyuh /app/.venv /app/.venv
COPY --from=builder --chown=chakravyuh:chakravyuh /app/src /app/src
COPY --from=builder --chown=chakravyuh:chakravyuh /app/alembic.ini /app/alembic.ini
COPY --from=builder --chown=chakravyuh:chakravyuh /app/migrations /app/migrations

USER chakravyuh
EXPOSE 8000

CMD ["uvicorn", "chakravyuh.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

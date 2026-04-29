FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV CLI_AGENT_PROXY_HOST=0.0.0.0
ENV CLI_AGENT_PROXY_PORT=9000
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.8.20 /uv /uvx /bin/

COPY pyproject.toml uv.lock README.md /app/
COPY src /app/src

RUN uv sync --frozen --no-dev

RUN groupadd --system app && useradd --system --gid app --home-dir /app app \
    && chown -R app:app /app

USER app

EXPOSE 9000

CMD ["uv", "run", "uvicorn", "aviary.main:app", "--host", "0.0.0.0", "--port", "9000"]

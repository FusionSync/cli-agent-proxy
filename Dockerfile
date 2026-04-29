FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV CLI_AGENT_PROXY_HOST=0.0.0.0
ENV CLI_AGENT_PROXY_PORT=9000

COPY pyproject.toml README.md /app/
COPY src /app/src

RUN pip install --no-cache-dir .

EXPOSE 9000

CMD ["uvicorn", "cli_agent_proxy.main:app", "--host", "0.0.0.0", "--port", "9000"]

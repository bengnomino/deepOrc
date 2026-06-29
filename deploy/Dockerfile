FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY orchestrator ./orchestrator
COPY gateway_agent ./gateway_agent
COPY alembic ./alembic
COPY alembic.ini ./

RUN pip install --no-cache-dir ".[postgres]"

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && orchestrator"]

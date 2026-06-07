FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY agreed ./agreed

RUN pip install --no-cache-dir -e ".[full,postgres]"

EXPOSE 8080

CMD ["sh", "-c", "uvicorn agreed.api.server:app --host 0.0.0.0 --port ${PORT}"]

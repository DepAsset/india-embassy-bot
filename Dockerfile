FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Run the bot as a dedicated non-root user in production.
RUN groupadd --system appuser \
    && useradd --system --gid appuser --home-dir /app --shell /usr/sbin/nologin appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY core ./core
COPY access ./access
COPY approval ./approval
COPY embassy ./embassy
COPY migration ./migration
COPY verification ./verification
COPY data ./data
COPY .env.example ./.env.example

RUN chown -R appuser:appuser /app
USER appuser

CMD ["python", "-m", "app"]

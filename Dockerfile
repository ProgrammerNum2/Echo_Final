FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/bot.db

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot
COPY README.md .

RUN useradd --create-home --uid 10001 app && mkdir /data && chown -R app:app /app /data
USER app
VOLUME /data

CMD ["python", "-m", "bot"]

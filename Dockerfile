FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-hin \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot
COPY assets ./assets
COPY data ./data
COPY docs ./docs

RUN useradd --create-home --uid 10001 botuser \
    && mkdir -p /app/source_storage /app/logs \
    && chown -R botuser:botuser /app
USER botuser

CMD ["python", "-m", "bot.main"]

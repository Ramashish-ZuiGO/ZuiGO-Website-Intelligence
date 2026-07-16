FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --requirement requirements.txt

COPY app ./app

RUN addgroup --system app && adduser --system --ingroup app app
USER app

CMD ["celery", "--app", "app.celery_app:celery_app", "worker", "--loglevel=info"]

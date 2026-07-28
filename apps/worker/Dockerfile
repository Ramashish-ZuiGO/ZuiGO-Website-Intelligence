FROM node:24.4.1-bookworm-slim AS lighthouse

RUN npm install --global --omit=dev lighthouse@13.3.0

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY apps/worker/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --requirement requirements.txt
# Browser compatibility reports Playwright engines, not branded browser versions.
RUN python -m playwright install --with-deps chromium firefox webkit

COPY --from=lighthouse /usr/local/bin/node /usr/local/bin/node
COPY --from=lighthouse /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/lighthouse/cli/index.js /usr/local/bin/lighthouse

RUN addgroup --system app && adduser --system --ingroup app app \
    && chown -R app:app /ms-playwright

COPY apps/api/app ./app
COPY apps/worker/worker_app ./worker_app

USER app

CMD ["sh", "-c", "exec celery --app worker_app.celery_app:celery_app worker --loglevel=\"${LOG_LEVEL:-INFO}\""]

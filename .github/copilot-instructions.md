# ZuiGO Website Intelligence

## Approved stack

- Next.js 16, TypeScript, App Router, Tailwind CSS
- FastAPI on Python 3.13
- PostgreSQL, Redis, Celery
- Docker Compose
- Node.js 24 and npm

## Service boundaries

- `apps/web`: browser UI only; run locally with npm.
- `apps/api`: HTTP API in the `app` Python package, settings, middleware, and routes.
- `apps/worker`: Celery configuration and background tasks in the `worker_app` Python package.
- `infrastructure`: infrastructure-specific assets.
- `scripts`: development and operations helpers.
- `tests`: API, worker, and future cross-service tests.

Keep `/health` compatible. Put future business endpoints under `/api/v1`. Use migrations
for every future database schema change.

## Commands

- Frontend: `npm.cmd run dev`, `npm.cmd run lint`, `npm.cmd run build`
- Python setup: `python -m pip install -r requirements-dev.txt`
- Python lint: `python -m ruff check .`
- Python format: `python -m ruff format .`
- API tests: `python -m pytest tests/api`
- Worker tests: `python -m pytest tests/worker`
- Docker: `docker compose up --build -d`, `docker compose down`
- Worker logs: `docker compose logs worker`
- Worker ping: `docker compose exec worker celery --app worker_app.celery_app:celery_app inspect ping`

## Engineering rules

- Never commit `.env`, `.env.local`, credentials, tokens, or other secrets.
- Do not redesign or replace the approved stack.
- Do not add unnecessary dependencies or features outside the assigned task.
- Do not create Git commits unless explicitly requested.
- Run relevant linting, formatting checks, tests, and builds after modifications.
- Preserve existing API contracts unless a task explicitly authorizes a breaking change.
- Keep AI-generated findings grounded in verified technical data.

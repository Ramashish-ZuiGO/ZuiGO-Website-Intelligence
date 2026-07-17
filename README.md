# ZuiGO Website Intelligence

Monorepo foundation for the ZuiGO Website Intelligence platform.

## Prerequisites

- Node.js 24
- npm 11
- Python 3.13 for local Python tooling
- Docker Desktop with Docker Compose

## Configuration

Create the Docker Compose environment file:

```powershell
Copy-Item .env.example .env
```

Replace `POSTGRES_PASSWORD` in `.env` with a local secret. PostgreSQL connection settings
are supplied as individual variables, and the API constructs its database URL internally.
The `.env` file is ignored by Git.

Backend configuration belongs in the repository-root `.env`:

- `APP_ENV`: `development`, `test`, or `production`; defaults to `development`.
- `LOG_LEVEL`: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`; defaults to `INFO`.
- `POSTGRES_USER`: PostgreSQL role and database URL user.
- `POSTGRES_PASSWORD`: required PostgreSQL secret; no default.
- `POSTGRES_DB`: PostgreSQL database name.
- `POSTGRES_HOST`: PostgreSQL host used to construct `DATABASE_URL`.
- `POSTGRES_PORT`: PostgreSQL port used to construct `DATABASE_URL`.
- `REDIS_URL`: required Redis URL used by the API and as Celery's broker and result backend.
- `BACKEND_CORS_ORIGINS`: comma-separated HTTP origins allowed to call the API.

`DATABASE_URL` is derived once by the typed API settings from the PostgreSQL fields above and
is shared by SQLAlchemy and Alembic. Do not add a second password-bearing URL to `.env`.

Create the frontend environment file:

```powershell
Copy-Item apps/web/.env.local.example apps/web/.env.local
```

Next.js loads `apps/web/.env.local`; it does not automatically load the repository-root
`.env`. `NEXT_PUBLIC_API_URL` is the browser-visible API base URL. Do not place secrets in
frontend variables or in any variable beginning with `NEXT_PUBLIC_`.

Install the pinned Python development tools and service dependencies:

```powershell
python -m pip install -r requirements-dev.txt
```

Runtime dependencies remain pinned in each service's `requirements.txt`. Shared development
tools are pinned separately in `requirements-dev.txt`; no additional dependency manager is
required.

For a runtime-only Python installation, install the relevant service requirements directly:

```powershell
python -m pip install -r apps/api/requirements.txt
python -m pip install -r apps/worker/requirements.txt
```

Install the frontend dependencies from its committed lock file:

```powershell
npm.cmd --prefix apps/web ci
```

Use `npm ci` for reproducible frontend installations. Run `npm install` only when intentionally
changing dependencies and updating `apps/web/package-lock.json`.

## Run locally

Start PostgreSQL, Redis, the FastAPI API, and the Celery worker:

```powershell
docker compose up --build -d
```

Start the frontend in a separate terminal:

```powershell
npm.cmd run dev
```

Open `http://localhost:3000`. The API health endpoint is available at `http://localhost:8000/health`.

Stop the services:

```powershell
docker compose down
```

To also remove local database and Redis data, explicitly run `docker compose down --volumes`.

## Database migrations

Run Alembic commands from the repository root. The configuration uses the existing typed API
settings and the PostgreSQL values from `.env`.

```powershell
# Create an empty migration
python -m alembic -c apps/api/alembic.ini revision -m "describe_change"

# Create a migration by comparing models with the current database
python -m alembic -c apps/api/alembic.ini revision --autogenerate -m "describe_change"

# Upgrade to the latest migration
python -m alembic -c apps/api/alembic.ini upgrade head

# Downgrade one migration
python -m alembic -c apps/api/alembic.ini downgrade -1

# Show the database's current revision
python -m alembic -c apps/api/alembic.ini current

# Show migration history
python -m alembic -c apps/api/alembic.ini history
```

## Useful commands

```powershell
npm.cmd run lint
npm.cmd run build
python -m ruff check .
python -m ruff format --check .
python -m pytest tests/api
python -m pytest tests/worker
docker compose ps
docker compose logs worker
docker compose exec worker celery --app worker_app.celery_app:celery_app inspect ping
```

## Repository layout

- `apps/web`: Next.js 16 frontend, run locally with npm
- `apps/api`: FastAPI service in the `app` Python package, run in Docker
- `apps/worker`: Celery worker in the `worker_app` Python package, run in Docker
- `infrastructure`: future infrastructure-specific assets
- `scripts`: future development and operations scripts
- `tests/api`: FastAPI settings, health, and CORS tests
- `tests/worker`: Celery task tests

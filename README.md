# ZuiGO Website Intelligence

Monorepo foundation for the ZuiGO Website Intelligence platform.

## Prerequisites

- Node.js 20.9 or newer (Node.js 24 recommended)
- npm
- Docker Desktop with Docker Compose

## Configuration

Copy `.env.example` to `.env`, then replace `POSTGRES_PASSWORD` with a local secret. The `.env` file is ignored by Git.

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

## Useful commands

```powershell
npm.cmd run lint
npm.cmd run build
docker compose ps
docker compose logs worker
```

## Repository layout

- `apps/web`: Next.js 16 frontend, run locally with npm
- `apps/api`: FastAPI service, run in Docker
- `apps/worker`: Celery worker, run in Docker
- `infrastructure`: future infrastructure-specific assets
- `scripts`: future development and operations scripts
- `tests`: future cross-service tests

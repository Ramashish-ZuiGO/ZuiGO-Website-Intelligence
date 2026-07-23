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
- `AI_PROVIDER`: worker interpretation provider; `disabled` (default) or `ollama`.
- `AI_MODEL`: local Ollama model name when Ollama is enabled.
- `AI_BASE_URL`: Ollama API URL reachable from the worker container.
- `AI_TIMEOUT_SECONDS`: bounded provider request timeout from 1 through 600 seconds.
- `BROWSER_LAUNCH_TIMEOUT_MS`: Chromium launch deadline; defaults to 20000.
- `NAVIGATION_TIMEOUT_MS`: main-document navigation deadline; defaults to 45000.
- `DOM_READINESS_TIMEOUT_MS`: optional full-load wait after DOM readiness; defaults to 15000.
- `PAGE_STABILIZATION_MS`: bounded post-DOM stabilization window; defaults to 2000.
- `EVIDENCE_COLLECTION_TIMEOUT_MS`: page evaluation deadline; defaults to 20000.
- `LIGHTHOUSE_TIMEOUT_SECONDS`: Lighthouse process deadline; defaults to 120.
- `ANALYSIS_JOB_TIMEOUT_SECONDS`: complete analysis deadline; defaults to 300.
- `ANALYSIS_MAX_ATTEMPTS`: maximum attempts for retryable stages; defaults to 2 and cannot exceed 3.
- `ANALYSIS_RETRY_BACKOFF_SECONDS`: bounded delay between retryable attempts; defaults to 1.
- `W3C_VALIDATION_ENABLED`: enables optional external Nu HTML validation; defaults to `true`.
- `W3C_VALIDATION_ENDPOINT`: Nu-compatible JSON validation endpoint.
- `W3C_TIMEOUT_SECONDS`: validator request timeout; defaults to 20.
- `POLICY_PAGE_TIMEOUT_SECONDS`: same-site privacy-page request timeout; defaults to 15.
- `DIAGNOSTIC_MAX_RESOURCES`: bounded first-party cache sample; defaults to 20.
- `DIAGNOSTIC_EVIDENCE_LIMIT`: maximum stored messages per diagnostic; defaults to 20.
- `RESPONSIVE_VIEWPORTS`: bounded `name:widthxheight` Chromium viewport list.

`DATABASE_URL` is derived once by the typed API settings from the PostgreSQL fields above and
is shared by SQLAlchemy and Alembic. Do not add a second password-bearing URL to `.env`.

Completed reports qualify diagnostic evidence rather than treating every numeric result as
fully verified. An HTML-only cache score is explicitly provisional, CSP is classified from
`absent` through `strong`, and 24 by 24 CSS-pixel tap-target observations distinguish spacing
exceptions from confirmed usability failures. Reports also retain bounded validator messages,
copyright evidence, confidence-based Next.js indicators, Lighthouse execution context, and
failed/manual audit summaries. Time to Interactive is labelled legacy/supplementary, and the
Lighthouse accessibility section always calls out the need for manual testing.

### Safe website discovery and coverage

Website discovery is a separate bounded worker job. It starts with the submitted URL,
robots sitemap declarations, `/sitemap.xml`, sitemap indexes, homepage/internal HTML links,
canonical links, and bounded rendered-DOM links retained by a prior homepage analysis. It
does not run Lighthouse on discovered pages, click controls, submit forms, authenticate, or
cross into unrelated domains.

Default boundaries are 500 discovered URLs, 50 fetched HTML pages, depth 3, 500 links per
page, 20 sitemap files, five redirects, a 15-second request timeout, a 180-second overall
deadline, and 2 MB per response. The matching `DISCOVERY_*` environment variables in
`.env.example` configure these limits. Subdomains remain recorded but excluded from crawling
unless explicitly enabled after their relationship has been verified.

robots.txt is fetched with the existing public-URL/SSRF protections. Disallowed pages are
excluded from analysis coverage. A missing robots file permits crawling; a fetch or parse
failure records `unknown` rather than inventing permission. XML, sitemap-index, namespaced,
and bounded gzip sitemap inputs are supported. Loops, external sitemap URLs, unsafe
redirects, oversized responses, state-changing paths, and configured limits are recorded
without discarding successful partial discovery.

Coverage is not a quality score:

`analyzed coverage = analyzed eligible pages / total eligible pages × 100`

The API and UI always show the numerator and denominator. Analyzed means an eligible page
with a completed, partial, or failed analysis attempt; pending pages remain in the
denominator. Excluded, skipped, external, destructive, and robots-disallowed pages do not.
When there are no eligible pages, the percentage is unavailable.

Discovery endpoints are:

- `POST /api/v1/websites/{website_id}/discovery-runs`
- `GET /api/v1/discovery-runs/{run_id}`
- `GET /api/v1/websites/{website_id}/pages`
- `GET /api/v1/websites/{website_id}/coverage`
- `GET /api/v1/website-pages/{page_id}`

Page listing supports bounded pagination, URL/title search, and eligibility, page-type,
discovery-source, robots, and latest-analysis-status filters. Discovery remains
single-engine lightweight HTTP collection; full page-level audits and browser/viewport
matrices are intentionally deferred.

Create the frontend environment file:

```powershell
Copy-Item apps/web/.env.local.example apps/web/.env.local
```

Next.js loads `apps/web/.env.local`; it does not automatically load the repository-root
`.env`. `NEXT_PUBLIC_API_URL` is the browser-visible API base URL. The example uses
`http://127.0.0.1:8000` to avoid Windows resolving `localhost` to IPv6 while Docker Desktop
publishes the API through its IPv4 forwarding path. Do not place secrets in
frontend variables or in any variable beginning with `NEXT_PUBLIC_`.

### Optional local AI interpretation

AI is optional. With `AI_PROVIDER=disabled`, each completed audit receives a deterministic,
evidence-grounded interpretation. To use an existing local Ollama installation, configure:

```dotenv
AI_PROVIDER=ollama
AI_MODEL=<configured-local-model>
AI_BASE_URL=http://host.docker.internal:11434
AI_TIMEOUT_SECONDS=120
```

Install and start Ollama on the host and install the selected model yourself. The application
does not download models, expose Ollama publicly, or require Ollama to start. If the worker
cannot reach Ollama, the model is missing, the request times out, or output fails validation,
the verified technical audit remains completed and the deterministic fallback is stored.
Every generated recommendation must cite a persisted finding code; prompts and raw provider
responses are not stored or logged.

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

## Pre-commit checks

Install the pinned development dependencies and Git hook:

```powershell
python -m pip install -r requirements-dev.txt
python -m pre_commit install
```

Run every configured check manually:

```powershell
python -m pre_commit run --all-files
```

Update third-party hook revisions intentionally with:

```powershell
python -m pre_commit autoupdate
```

For a genuine emergency only, bypass the hook with `git commit --no-verify`. Do not use
`--no-verify` to avoid fixing ordinary lint, formatting, test, or repository-hygiene failures.

## Continuous integration

GitHub Actions runs Python quality checks, frontend lint and production builds, and Docker image
builds for pushes and pull requests targeting `main`. The workflow can also be started manually
from GitHub. CI uses safe dummy Docker values and does not deploy or require cloud credentials.

## Run locally

Start PostgreSQL, Redis, the FastAPI API, and the Celery worker:

```powershell
docker compose up --build -d
```

Start the frontend in a separate terminal:

```powershell
npm.cmd run dev
```

Open `http://localhost:3000`. The API health endpoint is available at
`http://127.0.0.1:8000/health`.

Stop the services:

```powershell
docker compose down
```

To also remove local database and Redis data, explicitly run `docker compose down --volumes`.

## Logging

API and worker logs use a consistent structured text format with a UTC timestamp, level,
service, logger, and message. Set `LOG_LEVEL` in the root `.env` to `DEBUG`, `INFO`, `WARNING`,
`ERROR`, or `CRITICAL`. Request and response bodies, credentials, cookies, authorization
headers, and environment values are not logged. Health requests are logged only at DEBUG.

```powershell
docker compose logs api --tail 50
docker compose logs worker --tail 50
```

### Analysis troubleshooting

Playwright navigates to `domcontentloaded` and then allows a bounded stabilization window; it
does not require `networkidle`, because analytics and other third-party connections may remain
open. Lighthouse receives a fresh temporary home and debugging port for every attempt. Both
audits have explicit deadlines and at most `ANALYSIS_MAX_ATTEMPTS` attempts. Do not increase
timeouts or retries without confirming the worker has adequate memory and inspecting the safe
stage logs first.

Stable failure codes include `BROWSER_LAUNCH_FAILED`, `NAVIGATION_TIMEOUT`,
`MAIN_DOCUMENT_FAILED`, `PAGE_CRASHED`, `PLAYWRIGHT_COLLECTION_FAILED`,
`LIGHTHOUSE_START_FAILED`, `LIGHTHOUSE_TIMEOUT`, `LIGHTHOUSE_INVALID_OUTPUT`,
`LIGHTHOUSE_PROCESS_FAILED`, `ANALYSIS_DEADLINE_EXCEEDED`, and
`INTERNAL_ANALYSIS_ERROR`. A mandatory Playwright or Lighthouse failure leaves the run failed;
missing measurements are never fabricated. Interpretation provider failures continue to use
the existing deterministic fallback. An unexpected interpretation persistence failure does not
discard an otherwise completed technical audit, and the report exposes the interpretation as
unavailable.

## API errors

API errors use one response envelope and include the request ID returned in the
`X-Request-ID` response header:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Safe user-facing message",
    "details": null,
    "request_id": "request-id"
  }
}
```

Frontend code should branch on the stable `error.code`, display `error.message`, and retain
`error.request_id` for troubleshooting. Clients may send `X-Request-ID`; absent or invalid IDs
are replaced by the API. Validation errors include safe field-level information in `details`.

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

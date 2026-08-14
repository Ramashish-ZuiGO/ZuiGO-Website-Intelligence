# Production Operations — ZuiGO WebIQ

Operational contract for running ZuiGO WebIQ in production: deployment,
liveness/readiness, worker restarts, concurrency policy, backup/restore, and
troubleshooting. Product behaviour is specified in `PRODUCT_MASTER_SPEC.md`;
implementation rules live in `AGENTS.md` and `CLAUDE.md`.

## 1. Runtime shape

| Component  | Role                                                            |
| ---------- | --------------------------------------------------------------- |
| Next.js    | Customer UI. `NEXT_PUBLIC_API_URL` is inlined at **build** time. |
| FastAPI    | API and canonical business logic. Stateless.                     |
| Celery     | Background analysis execution. Stateful only in Postgres/Redis.  |
| PostgreSQL | Canonical state **and artifact bytes**. The only durable store.  |
| Redis      | Celery broker/result backend. Not a system of record.            |

Analysis stages run as a strict Celery `chain`, so **one task per run is active
at a time**. Worker concurrency is therefore the cap on concurrent analyses.

## 2. Environment variables

Copy `.env.example` to `.env` (git-ignored; never commit it).

**Required — the API/worker must not start without these:**

- `POSTGRES_PASSWORD` — no default, deliberately.
- `REDIS_URL`
- `POSTGRES_USER` / `POSTGRES_DB` / `POSTGRES_HOST` / `POSTGRES_PORT`
- `BACKEND_CORS_ORIGINS` — exact origins, comma-separated. **Never `*`.**
- `NEXT_PUBLIC_API_URL` (frontend build) — the production build **fails** if
  unset rather than silently shipping a `127.0.0.1` API URL to customers.

**Production-relevant:**

- `APP_ENV=production`, `LOG_LEVEL=INFO`
- `CELERY_WORKER_CONCURRENCY` (see §6)
- `CELERY_BROKER_VISIBILITY_TIMEOUT_SECONDS` (see §7)
- `WORKER_STOP_GRACE_PERIOD` (see §5)
- `READINESS_TIMEOUT_SECONDS`, `DB_CONNECT_TIMEOUT_SECONDS`, `DB_POOL_SIZE`,
  `DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE_SECONDS`

**Optional — must never block startup:** `AI_PROVIDER` and related LLM
settings. Deterministic analysis without an LLM is a supported product mode, so
LLM credentials are never a startup or readiness requirement. `CRUX_API_KEY`
and `W3C_VALIDATION_*` are likewise optional enrichment.

## 3. Liveness vs readiness

| Endpoint  | Question answered                        | Dependency I/O |
| --------- | ---------------------------------------- | -------------- |
| `/health` | Is the process alive?                    | None           |
| `/ready`  | Can this instance accept production work? | Postgres+Redis |

`/ready` returns `200` with `{"status":"ready",...}` or **`503`** with
`{"status":"not_ready","dependencies":{...}}`. Probes are bounded by
`READINESS_TIMEOUT_SECONDS` (connect *and* statement timeout) and use a
dedicated `NullPool` connection so they never consume the request pool. No
credentials, host names, or exception text appear in the response.

Point load balancers and deploy gates at **`/ready`**; use `/health` only for
process-restart liveness probes.

## 4. Deployment procedure

Migrations are **not** applied automatically at startup — that is deliberate.
Automatic per-container migration would let multiple replicas race
`alembic upgrade` concurrently. Run it exactly once, before rolling out code.

Compose images have **no source mounts** — always rebuild before deploying.

```bash
docker compose build api worker
```

Then, in order:

1. Verify required variables are present in `.env`.
2. Start/verify dependencies: `docker compose up -d postgres redis`
   (both have healthchecks; `api`/`worker` wait on `service_healthy`).
3. **Run migrations once:** `docker compose run --rm api alembic upgrade head`
4. Confirm schema is current: `docker compose run --rm api alembic current`
   must report the single head (`alembic heads` shows exactly one).
5. Start the API: `docker compose up -d api`
6. Start the worker: `docker compose up -d worker` (see §5 first).
7. Build and start the frontend with `NEXT_PUBLIC_API_URL` set.
8. Verify liveness: `curl -fsS http://<api>/health`
9. Verify readiness: `curl -fsS http://<api>/ready` → `"status":"ready"`
10. Verify the worker: `celery -A worker_app.celery_app:celery_app inspect ping`
11. Submit one controlled smoke analysis against a site you own.
12. Verify artifact generation and download (PDF/HTML/JSON) for that run.

**Rollback:** redeploy the previous image tag. Migrations are forward-only in
practice — do not auto-downgrade a schema that newer rows depend on. If a
release must be rolled back after a migration, restore from backup (§8).

## 5. Planned restarts and worker drain

Celery performs a **warm shutdown** on `SIGTERM`: it stops accepting new work
and lets running tasks finish. Docker's default 10s stop timeout would
`SIGKILL` a browser stage mid-flight on every restart, so the worker service
sets `stop_grace_period` (`WORKER_STOP_GRACE_PERIOD`, default `1800s`).

This is an **upper bound only** — the worker exits as soon as its running tasks
complete. Restart the worker when idle whenever possible:

```bash
docker compose exec worker celery -A worker_app.celery_app:celery_app inspect active
```

If that reports no active tasks, restart is instant and lossless. If a stage is
mid-flight, `docker compose up -d worker` waits for it to drain.

**Never recreate, stop or `docker kill` a busy worker casually** — always check
`inspect active` first. A hard kill strands its `acks_late` message for the full
visibility timeout (§7) and interrupts customer analyses that were minutes from
completing. Recovery from a genuine hard kill is the product's own path — stale
detection at 900s, then an explicit resume, which reuses the same execution/run
at `attempt+1` and never duplicates canonical records.

## 6. Concurrency policy

**Recommended production policy:** `CELERY_WORKER_CONCURRENCY=2` on a shared
host; at most `3` on a dedicated worker host. Scale out by adding worker hosts,
not by raising concurrency on one host.

Rationale: one host saturates — and starves the API and Postgres — at roughly
four concurrent browser-heavy runs. Because stages are chained, concurrency is
literally "max concurrent analyses". `worker_prefetch_multiplier=1` ensures a
worker reserves only what it can start, so a queued analysis is never held
hostage by a busy worker.

Excess submissions queue in Redis rather than being rejected; they start as
slots free up. Watch backlog with §9.

## 7. Stage exclusivity and the broker visibility timeout

### Stage exclusivity (the correctness guarantee)

**Invariant: for one `(execution_id, attempt, stage)`, at most one delivery may
perform side effects.**

Celery task ids do not provide this. A broker redelivery, a worker reconnect or
a prefetch race can deliver the identical stage message while the first delivery
is still running — observed in production as the same browser stage executing
concurrently in two worker processes.

Every real-analysis stage therefore enters through a shared guard that claims
ownership of `(execution, attempt, stage)` inside the execution row under
`SELECT ... FOR UPDATE`. **PostgreSQL is the coordination authority — not
Redis** — so exclusivity survives any broker misbehaviour. A delivery that does
not win the claim raises Celery's `Ignore`: the message is acked, no stage work
runs, no progress or completion is written, and the chain is not advanced (only
the genuine owner advances it).

Ownership is scoped to `attempt` and is released **only** by the attempt bump
that resume performs — never by a timer, never by hand. Consequences:

- A duplicate arriving while the owner is alive is refused.
- If the owning worker dies, the claim persists, the execution goes stale at
  900s, and resume bumps the attempt, which supersedes the stale claim. Attempt
  N+1 always proceeds; there are no locks to delete manually.
- There is no expiry window during which two deliveries could both believe they
  own the stage. Recovery takes the stale→resume path rather than allowing an
  unsafe concurrent takeover — correctness over shaving minutes.

### Visibility timeout (defence in depth)

`CELERY_BROKER_VISIBILITY_TIMEOUT_SECONDS` (default `21600`) must stay above the
longest possible stage runtime and can never be configured below Celery's 3600s
default (validated floor). It **reduces pointless redelivery of still-running
stages; it does not provide exclusivity** — the ownership claim above does, and
would still hold if this value were misset. Never lower it to "speed up"
recovery: broker redelivery is not the recovery mechanism, stale→resume is.

## 8. Backup and restore

**Postgres is the only durable store that matters.** Report artifacts
(PDF/HTML/JSON/technical appendix/page inventory) are stored as bytes in the
`report_artifacts` table, not on a container filesystem — so a single database
backup captures state *and* artifacts consistently, with no risk of a DB
snapshot disagreeing with a separate artifact store.

Minimum requirement:

- **Back up:** the entire Postgres database (`pg_dump -Fc` or a volume/PITR
  snapshot). Nothing else in the stack holds unrecoverable state.
- **Do not** rely on the `redis_data` volume: Redis holds in-flight queue state
  only. Losing it can interrupt running analyses, which the stale→resume path
  recovers; it never loses a completed report.
- **Retention:** keep enough history to cover the reporting period customers can
  request, since historical report snapshots are immutable and cannot be
  regenerated identically from a re-analysis.
- **Size:** artifact bytes dominate. Track `pg_total_relation_size` of
  `report_artifacts` when sizing backup storage.
- **Restore verification:** restore into a scratch database, run
  `alembic current` (must match the deployed head), then confirm a known report
  downloads with a matching `checksum_sha256`. A restore is only verified once
  an artifact checksum matches — not merely because the restore command exited 0.

Container recreation is safe: `postgres_data` mounts `/var/lib/postgresql`,
which contains `PGDATA` (`/var/lib/postgresql/18/docker`) for the
`postgres:18-alpine` image.

## 9. Operational visibility

Application state is the source of truth; do not expose Celery control surfaces
publicly.

```bash
# Worker alive / registered
docker compose exec worker celery -A worker_app.celery_app:celery_app inspect ping

# Active tasks (and their run/execution ids, encoded in the task id)
docker compose exec worker celery -A worker_app.celery_app:celery_app inspect active

# Queue backlog (messages waiting for a free slot)
docker compose exec redis redis-cli llen celery
```

Running, stale, and resumable executions are already exposed by the product API
per execution (`stale`, `last_progress_update`, `retry_available`,
`resume_available`). For a fleet-wide view:

```sql
-- Real analyses with no progress heartbeat for 15+ minutes (the same 900s
-- threshold the API uses for `stale`). journey_updated_at is a key inside the
-- structured_output JSON, not a column.
SELECT id, status, attempt,
       structured_output->>'journey_updated_at' AS last_progress_update
FROM agent_executions
WHERE status IN ('running', 'pending')
  AND structured_input ? 'discovery_run_id'
  AND (structured_output->>'journey_updated_at')::timestamptz
      < now() - interval '15 minutes'
ORDER BY last_progress_update;
```

Task ids are deterministic — `real-analysis:{execution_id}:attempt:{n}:{stage}`
— so a task id read from `inspect active` links directly back to its execution.

## 10. Tracing a request

Structured logs carry a `request_id` (also returned as the `X-Request-ID`
header and inside every error envelope). Trace:

`request_id` (API log) → `workflow_execution_id` in the response →
`real-analysis:{execution_id}:attempt:{n}:{stage}` task id in worker logs →
stage rows → report/artifact records.

Unexpected exceptions return a sanitized generic 500 with the request id
preserved; stack traces go to server logs only. Never log secrets, tokens, or
raw credentials.

## 11. Security boundaries

- CORS: exact origins only, never `*`.
- SSRF protections in `public_url_safety.py` are locked — never weaken.
- **Network boundary (enforced by contract test):** PostgreSQL and Redis must
  never publish ports. They carry no `ports:` mapping and are reachable only on
  the internal Compose network; services address them by service name
  (`POSTGRES_HOST=postgres`, `REDIS_URL=redis://redis:6379/0`). The image-level
  `5432/tcp` / `6379/tcp` shown by `docker ps` is an `EXPOSE` declaration, not a
  host publication — a published port would appear as `0.0.0.0:5432->5432/tcp`.
  Only the API may be published, and in production it belongs behind a reverse
  proxy terminating TLS. Never add `--bind 0.0.0.0` or `--protected-mode no` to
  Redis. If a developer needs host access locally, bind to loopback explicitly
  (`127.0.0.1:5432:5432`) in a local override file rather than editing the
  committed service definition.
- `.env` and `apps/web/.env.local` are git-ignored; `.env.example` holds
  placeholders only.
- Artifact filenames are sanitized and artifact ids are deterministic
  (`uuid5`); historical report snapshots are immutable and must never be
  mutated or migrated.

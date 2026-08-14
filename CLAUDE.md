# CLAUDE.md — ZuiGO WebIQ (Website Intelligence)

Guidance for Claude Code sessions in this repository. `AGENTS.md` holds the
permanent implementation rules (execution identity, migration/ORM consistency);
`docs/` holds product specs (`PRODUCT_MASTER_SPEC.md`, `REPORT_DELIVERY.md`,
`SCORING_METHODOLOGY.md`, `MULTI_AGENT_ARCHITECTURE.md`). Read those before
changing the areas they govern.

## What this is

Website-intelligence platform: submit a public URL → SSRF-validated discovery →
eligible-page scheduling → Playwright/Lighthouse/axe analysis → 8-agent
workflow → deterministic scoring → findings → immutable report snapshot →
client artifacts (PDF/HTML/JSON/Technical Appendix/Page Inventory) → history →
reanalysis → baseline-vs-current comparison.

Customer-facing product name: **ZuiGO WebIQ**. Internal identifiers (template
ids, package names, DB schema) keep their historical names — do not rename them
for branding.

## Stack & layout

- `apps/api` — FastAPI + SQLAlchemy + Alembic (Postgres). Routes in
  `app/api/routes/`, canonical logic in `app/services/`.
- `apps/worker` — Celery worker (Redis broker). Uses SQLAlchemy Core tables in
  `worker_app/db.py` that MUST stay column-compatible with the API models and
  migrations (including server defaults — tests build schema from these).
- `apps/web` — Next.js frontend. Often owned by a separate agent ("Antigravity")
  in parallel sessions: avoid editing `apps/web/**` unless the task explicitly
  assigns frontend work, and expect `tests/test_frontend_*` contract tests to
  read its source.
- `tests/` — pytest (`pyproject.toml` sets `pythonpath = ["apps/api",
  "apps/worker"]`). Docker Compose runs postgres/redis/api/worker; **images have
  no source mounts — rebuild `api`/`worker` images before any live acceptance
  run** or you are testing stale code.

## Commands

```bash
# backend tests (from repo root; pytest picks up pythonpath from pyproject)
python -m pytest -q
python -m ruff check apps/api apps/worker tests
python -m ruff format --check apps/api apps/worker tests

# frontend gates
npm --prefix apps/web run lint && npm --prefix apps/web run typecheck && npm --prefix apps/web run build

# live stack (rebuild first!)
docker compose build api worker && docker compose up -d api worker
docker compose exec -T api alembic upgrade head   # migrations are NOT auto-applied
curl -s http://localhost:8000/health
```

Ruff excludes `apps/web`, `.agent`, `.agents`, `.claude` (AI tooling dirs — do
not "fix" their lint noise).

## Locked invariants — do not change without explicit instruction

1. **Exactly 8 runtime agents** (discovery, accessibility, performance,
   site-diagnostics, evidence-validation, repository-intelligence, remediation,
   report).
2. **Scoring formulas locked**: `FORMULA_VERSION == "1.0.0"`,
   `PRIORITY_FORMULA_VERSION == "1.0.0"`, category weights fixed
   (tests enforce).
3. **SSRF protections** (`public_url_safety.py`) — never weaken.
4. **Immutable historical snapshots**: never mutate or migrate old
   `ReportSnapshot` payloads. Renderers must read defensively (`.get`
   fallbacks). The download route serves the frozen stored artifact when
   `report.template_version != TEMPLATE_VERSION` (version-aware guard in
   `routes/report_delivery.py`) — bump `TEMPLATE_VERSION` whenever renderer
   output changes meaningfully.
5. **Browser UAT truth contract (LOCKED)**: customer scope is exactly Google
   Chrome (latest-2-stable @ UAT date; Win 10/11, macOS 13+, Android 12+),
   Microsoft Edge (latest-2-stable; Win 10/11), Apple Safari (16.4+; macOS 13+,
   iOS 16+). Machine states: `VERIFIED / PARTIALLY_VERIFIED / NOT_VERIFIED /
   UNAVAILABLE_IN_CURRENT_ENVIRONMENT / NOT_TESTED`. **Chromium is never Chrome
   or Edge proof; WebKit is never Safari proof; Firefox is not customer UAT and
   is not scheduled by the standard workflow** (engines chromium+webkit run as
   internal engineering signals only; branded page counts stay 0 until real
   branded evidence exists). See `BRANDED_BROWSER_SCOPE` in
   `services/browser_compatibility.py`.
6. **Comparison direction**: baseline/previous → current, enforced by a
   chronology guard (`COMPARISON_CHRONOLOGY_INVALID`). `regressions` is an
   intentional aggregate bucket (its entries also live in `new`/`persistent`);
   customer-facing surfaces must render each finding once.
7. **No fabricated evidence, ever**: unavailable evidence is typed
   unavailable/not-comparable, never passed/resolved/improved.

## Canonical report model (snapshot payload)

Single source of truth for every artifact. Key blocks added at template 2.1.0:

- `product_name` ("ZuiGO WebIQ"), `finding_totals`
  (`total_unique_findings` / `top_finding_count` / `occurrence_count` /
  `affected_page_count` / `severity_totals`), and `completion`
  (`analysis_status`, machine-readable `limitation_reasons` with
  `kind: required|optional|optional_infrastructure|not_applicable`, independent
  `browser_uat` status).
- Artifact hierarchy: Executive Summary = prioritized subset; **client
  PDF/HTML contain a Complete Findings Register with ALL unique findings**;
  Technical Appendix holds ALL occurrences. No unique finding may disappear
  because it isn't Top-5/Top-10 (tests prove 179/179 at scale).
- Finding identity: 7-dimension grouping key (rule/title/category/**scope**/
  observed-signature/browser-signature/resource-kind) in
  `_group_detailed_findings`; comparison uses a compatible fingerprint.
  Grouping merges occurrences across pages (unique finding vs occurrence
  contract) and escalates severity to the worst.
- Sanitizer gotcha: customer-visible text must not contain the sanitizer's own
  trigger phrases (e.g. "private reasoning") or it renders as
  `[PRIVATE REASONING OMITTED]`; client renderers also drop placeholder
  strings and raw UUID values.
- A frozen snapshot never claims its own report agent is "running" (remapped
  to completed at freeze).

## Concurrency & reliability facts (hard-won)

- Same-site concurrent runs are isolated via the run-scoped
  `discovery_run_pages` membership table.
  `website_pages.last_discovery_run_id` is a last-writer-wins pointer —
  **never use it alone to select "this run's pages"** (it caused a 0-eligible
  race). Page-analysis/browser/report selection goes through membership (with
  legacy-pointer fallback for pre-migration data).
- Celery stage tasks are `acks_late`; redelivered tasks for terminal/cancelled
  executions are skipped via `_skip_terminal_stage`. Task ids are deterministic
  (`real-analysis:{exec_id}:attempt:{n}[:stage]`) — target these for surgical
  revocation.
- Stale detection: `real_execution_is_stale` (900s of no `journey_updated_at`
  progress on a running real execution). Resume via
  `POST /workflow-executions/{id}/resume` reuses the same execution/run
  (attempt+1) — never duplicates canonical records.
- Report/comparison/reanalysis/start are idempotency-keyed with fingerprint
  conflict detection; artifact ids are `uuid5(report_id, ...)` so retries can't
  duplicate artifacts.
- Local capacity: one worker host saturates (and starves the API/DB) at ~4+
  concurrent browser-heavy runs. Don't launch parallel same-site acceptance
  runs; recover by stopping only the worker, cancelling extras via the product
  `/cancel` lifecycle, then restarting (terminal-skip prevents re-deadlock).
- Firefox engine cannot launch in the worker container
  (`CanCreateUserNamespace EPERM`) — environmental, reported as
  "unavailable", not a bug to fix.

## Working conventions

- Typed errors everywhere: raise service-specific error classes
  (`ReportDeliveryError`, `AnalysisComparisonError`, `ApplicationError`) with
  stable codes; unexpected exceptions return generic 500s (tracebacks go to
  logs only, keyed by request id).
- Batch queries on list endpoints (`IN` prefetch); avoid `db.get(...)` inside
  per-row loops.
- New behavior needs deterministic local tests (no public sites in automated
  tests). When renderer output changes, update the artifact/regression tests
  that pin the old wording — and check the demo/presentation suites too.
- PDF text extraction escapes parentheses — avoid parens in PDF section
  headers that tests grep for.
- Windows dev host: shell is Git Bash/PowerShell; `datetime.now(UTC)`
  timestamps in fixtures are microsecond-ordered by creation order.
- Do not commit/push unless explicitly instructed. Frontend contract tests
  (`tests/test_frontend_*`) fail transiently while the frontend agent edits
  `apps/web` — attribute before "fixing".

# PERMANENT IMPLEMENTATION RULES — ADDED AFTER TASK 018

## 1. EXECUTION IDENTITY AND RE-RUN SAFETY

Any manually repeatable analysis, scan, discovery, audit, report generation,
or background job must have its own execution UUID.

Do not use only a parent resource ID or discovery_run_id as the uniqueness
boundary.

Every repeatable workflow must support:

- multiple executions against the same parent record
- historical result preservation
- latest-result pointers
- safe task retries
- idempotency for the same execution ID
- no IntegrityError during normal re-runs

Add explicit tests for running the same operation twice.

## 2. MIGRATION AND ORM CONSISTENCY

For every database change:

- SQLAlchemy models and Alembic migrations must define matching columns,
  foreign keys, indexes, uniqueness constraints and ON DELETE behavior
- verify upgrade
- verify downgrade
- verify re-upgrade
- verify the live PostgreSQL schema, not only SQLite tests
- verify Alembic current and heads
- do not mark database work complete when PostgreSQL verification is blocked

Uncommitted migrations may be corrected directly. Released migrations must
not be rewritten.

## 3. SAFE WORKFLOW SELECTION

Later-stage processing may run only when prerequisite stages succeeded.

Examples:

- Lighthouse must not run when Level 1 analysis failed or was skipped
- AI interpretation must not run without sufficient grounded evidence
- reporting must distinguish completed, partial, failed and unavailable data

Do not silently treat missing data as successful data.

## 4. NETWORK AND REDIRECT SAFETY

For any external URL processing:

- validate every redirect before following it
- disable uncontrolled automatic redirects where necessary
- validate DNS/IP safety on every hop
- reject private, loopback, link-local and unsafe addresses
- enforce approved-origin rules
- use bounded redirects, timeouts, response sizes and concurrency
- test using mocks and local fixtures only

## 5. GENERATED FILES

Do not commit generated caches or machine-local build files.

Examples:

- *.tsbuildinfo
- .next/
- coverage output
- Python caches
- temporary logs
- local environment files

Confirm relevant generated files are listed in .gitignore.

## 6. COMPLETE VERIFICATION

Before declaring a task complete, run all applicable checks:

Backend:
- full Python test suite
- Ruff lint
- Ruff format check

Frontend:
- lint
- TypeScript type-check
- frontend tests when configured
- production build

Database:
- Alembic heads and current
- upgrade
- downgrade
- re-upgrade
- PostgreSQL constraint and index verification

Repository:
- git diff --check
- git status --short

A missing test framework may be reported as N/A, but lint, type-check and
production build must still run.

## 7. GIT AND LINE ENDINGS

- Start every task from a clean committed branch
- Do not commit or push unless explicitly instructed
- LF/CRLF conversion warnings alone are not failures
- actual trailing whitespace or malformed files must be fixed
- pre-commit hooks may modify files; re-stage and rerun the commit afterward

## 8. FINAL HANDOFF

Do not output internal thought logs, repeated code or full terminal logs.

Return no more than 20 lines containing:

- task completed: yes/no
- main implementation
- migration/head
- tests and total count
- Ruff result
- frontend verification
- database verification
- git diff result
- git status
- remaining risks
- confirmation that nothing was committed or pushed

## PERMANENT PRODUCT REQUIREMENTS — ADDED BEFORE TASK 017

Product design and behavior must follow the 12 permanent requirements documented in
[PRODUCT_MASTER_SPEC.md](docs/PRODUCT_MASTER_SPEC.md). Key areas for agent attention:

- Every finding must be attributed to a specific page (no anonymous findings).
- Every issue must include what, why, severity, evidence, responsible area/role, remediation, and verification.
- Scores use x/100 format; confidence is separate from score.
- UI explanations must be keyboard accessible and screen-reader friendly.
- Standard profiles differ by website category; never apply one universal threshold.
- Performance reporting distinguishes field vs laboratory data.
- Never claim complete accessibility compliance from automated checks alone.
- Never claim browser support for untested browsers.
- Coverage must show numerator and denominator explicitly.
- Preserve historical analyses; never fabricate evidence.

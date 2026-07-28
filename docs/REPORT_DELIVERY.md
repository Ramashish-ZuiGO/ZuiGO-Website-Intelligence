# Report Delivery

## Customer journey

The supported journey is:

1. Add or select a website in a project.
2. Start full analysis with a scoped idempotency key.
3. Collect the existing persisted analysis evidence.
4. Run `full_website_analysis@1.0.0`.
5. Track stage, agents, coverage, elapsed time, unavailable capabilities, and recovery state.
6. Review evidence-grounded results.
7. Generate an immutable report.
8. Download HTML, PDF, or JSON and revisit historical reports.

`POST /api/v1/projects/{project_id}/websites/{website_id}/analysis/start`
validates ownership and returns both the analysis-run UUID and workflow-execution
UUID. The same project/workflow/key and input reuses the execution and does not
dispatch twice. A different key creates independent history.

## Snapshot and evidence rules

`ReportExecution` pins project, website, analysis run, workflow execution, score
execution, report/template versions, an input fingerprint, status, coverage,
confidence, unavailable sections, provider metadata, timestamps, and
partial/failure details. Its one `ReportSnapshot`, ordered `ReportSection`
records, and three `ReportArtifact` records are immutable after completion.

The twelve sections are Executive Summary; Overall and Category Scores;
Performance; Accessibility; Site-Wide Diagnostics; Security and Technical
Findings; Content and SEO Findings; Priority Action Plan; Remediation Guidance;
Evidence Coverage and Limitations; Methodology and Formula Versions; and
Multi-Agent Execution Summary.

Each factual value is drawn from retained analysis results, findings, diagnostics,
score executions, action items, or agent executions and stores evidence
references. A missing source produces `unavailable` or `incomplete`; it does not
produce a passed result or a zero finding claim. Private chain-of-thought is not
a model field.

## Report Agent and deterministic fallback

The existing `report_agent` uses the existing `report_generation` tool. It may
consume validated evidence and persisted scoring snapshots but cannot calculate
or alter metrics, scores, confidence, or formulas. An approved LLM is optional
and limited to grounded narrative. When unavailable, deterministic local
generation still creates the complete snapshot and exports with its limitations
recorded.

## Exports and security

HTML uses semantic landmarks, headings, table captions, keyboard-visible focus,
and safely escaped values. PDF includes a table of contents, generated timestamp,
and page numbers. JSON uses a stable versioned schema and deterministic key
ordering. All formats use deterministic section order, stable safe filenames,
SHA-256 checksums, and database-backed locations. Downloads set an attachment
filename, checksum, `nosniff`, and immutable private-cache headers.

Exports contain no credentials, provider secrets, private reasoning, or internal
filesystem paths. Evidence references identify retained database records rather
than copying raw secret-bearing reports.

## APIs

- `POST /api/v1/projects/{project_id}/websites/{website_id}/analysis/start`
- `GET /api/v1/workflow-executions/{execution_id}/progress`
- `POST /api/v1/analysis-runs/{run_id}/reports/generate`
- `GET /api/v1/analysis-runs/{run_id}/reports`
- `GET /api/v1/websites/{website_id}/reports/history`
- `GET /api/v1/reports/{report_id}`
- `GET /api/v1/reports/{report_id}/status`
- `GET /api/v1/reports/{report_id}/artifacts`
- `GET /api/v1/reports/{report_id}/download/{format}`

List APIs support bounded pagination and filters. Missing resources,
idempotency conflicts, non-terminal workflows, scope mismatches, and unsupported
formats use deterministic 404, 409, and 422 responses.

## Limitations

Reports describe only persisted evidence and execution state. Automated
accessibility evidence cannot prove complete compliance. Laboratory performance
evidence is not field evidence. Canonical/indexability signals do not prove
search-engine indexing. No competitor, industry, global-site, or ranking claim is
made. Overall Score Formula v1.0.0 and Priority Formula v1.0.0 are unchanged.

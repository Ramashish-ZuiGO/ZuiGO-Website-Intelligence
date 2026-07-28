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

The sixteen sections are Executive Summary; Overall and Category Scores;
Performance; Accessibility; Site-Wide Diagnostics; Internal Link Graph;
Canonical and Indexability; Security and Technical Findings; Content and SEO
Findings; Page-Level Findings; Repeated and Template Problems; Priority Action
Plan; Remediation Guidance; Evidence Coverage and Confidence; Multi-Agent
Execution Summary; and Methodology, Versions and Limitations.

Each factual value is drawn from retained analysis results, findings, diagnostics,
score executions, action items, or agent executions and stores evidence
references. A missing source produces `unavailable` or `incomplete`; it does not
produce a passed result or a zero finding claim. Private chain-of-thought is not
a model field.

## Finding-detail and occurrence contract

Every finding includes its title, plain-language and technical explanations,
category, severity, confidence, affected pages, uncapped exact occurrences,
evidence references and provider/version provenance, detecting agent, validating
agent where applicable, likely cause, technical impact, business impact,
remediation, responsible role, effort band, verification procedure, related
findings, limitations, evidence state, and scope.

Each occurrence identifies the normalized URL, response status when retained,
page title/type/section, selector/resource/location, observed and expected values,
evidence timestamp, provider/version, artifact reference, and scope. Missing
fields remain unavailable. The report never invents an occurrence or truncates a
finding to a presentation-row limit.

Business-impact text is included only when persisted Action Plan evidence
supports it. Otherwise the report explicitly says impact is unquantified.
Likewise, deterministic repeated or template classification does not prove
source-template ownership.

## Agent attribution and navigation

Every section records agents involved, actual tools used, execution status,
evidence produced, unavailable tools/providers, and deterministic fallback
behavior. The existing eight agents remain unchanged and visible. The report
stores no prompts or private reasoning.

The interactive viewer filters findings by severity, category, detecting or
validating agent, page/URL, scope, evidence availability, and full-text search.
Executive risks, score contributions, related findings, and Action Plan rows link
directly to the retained finding evidence.

## Report Agent and deterministic fallback

The existing `report_agent` uses the existing `report_generation` tool. It may
consume validated evidence and persisted scoring snapshots but cannot calculate
or alter metrics, scores, confidence, or formulas. An approved LLM is optional
and limited to grounded narrative. When unavailable, deterministic local
generation still creates the complete snapshot and exports with its limitations
recorded.

## Exports and security

HTML uses a branded cover, semantic landmarks, headings, table captions,
keyboard-visible focus, text status, readable finding/occurrence tables, and
safely escaped values. PDF includes project/website identity, score and coverage,
table of contents, section order, generated timestamp, document metadata,
headers, footers, and page numbers. JSON uses a stable versioned schema and
deterministic key ordering. All formats use deterministic section order, stable
safe filenames, SHA-256 checksums, and database-backed locations. Downloads set
an attachment filename, checksum, `nosniff`, and immutable private-cache headers.

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

## Local demonstration workflow

From `apps/api`, run:

```powershell
python -m app.services.report_demo --output-dir ../../.local-reports/task-029-demo
```

The local synthetic fixture covers all eight agents, multiple severity levels,
page and template findings, score-to-finding links, unavailable field evidence,
the Action Plan, and HTML/PDF/JSON exports. It uses no crawl, public API, LLM, or
remote provider. Generated files and their checksum manifest are ignored and
must not be committed.

## Limitations

Reports describe only persisted evidence and execution state. Automated
accessibility evidence cannot prove complete compliance. Laboratory performance
evidence is not field evidence. Canonical/indexability signals do not prove
search-engine indexing. No competitor, industry, global-site, or ranking claim is
made. Overall Score Formula v1.0.0 and Priority Formula v1.0.0 are unchanged.
Presentation formatting cannot add evidence or replace interactive inspection of
the original persisted records.

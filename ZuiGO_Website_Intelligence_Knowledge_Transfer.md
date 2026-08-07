# ZuiGO Website Intelligence
## Full Knowledge Transfer for Claude

**Document version:** 1.0
**Prepared on:** 5 August 2026
**Primary repository:** `C:\Users\Ramashish\Documents\ZuiGO-Website-Intelligence`
**GitHub repository:** `https://github.com/Ramashish-ZuiGO/ZuiGO-Website-Intelligence`
**Current working branch:** `task-031-reanalysis-comparison`
**Stable branch:** `main`

---

# 1. Purpose

This document transfers the complete working context of the **ZuiGO Website Intelligence** project to Claude.

Use it together with:

- `AGENTS.md`
- `README.md`
- the current Git branch
- the current working-tree diff
- migrations, tests, workflows, and project documentation

It explains what the product is, what is complete, what is in progress, what was fixed, what remains, and how to continue without damaging existing work.

Claude must not treat this as a new project or restart implementation from scratch.

---

# 2. Immediate Safety Instructions

Before editing anything, run:

```powershell
git branch --show-current
git status --short
git diff --stat
git diff --check
```

Then read:

```text
AGENTS.md
README.md
ZuiGO_Website_Intelligence_Knowledge_Transfer.md
```

## Non-negotiable safety rules

Do not:

- reset the repository
- restore files
- clean untracked files
- stash the working tree
- switch branches
- checkout files from another branch
- rewrite current work from scratch
- use `git reset --hard`
- use `git clean`
- use `git restore`
- use `docker compose down -v`
- delete database volumes
- commit without explicit approval
- push without explicit approval
- merge without explicit approval
- skip hooks
- use `--no-verify`
- modify scoring formulas
- add a ninth runtime agent
- silently substitute demo evidence for a failed real analysis
- claim completion without evidence

The working tree contains substantial uncommitted Task 031 work.

The last reported state was approximately:

```text
Branch: task-031-reanalysis-comparison
43 modified files
15 untracked files
0 staged files
Nothing committed or pushed
```

Verify the exact current state because it may have changed.

---

# 3. Product Vision

ZuiGO Website Intelligence is a multi-agent website analysis and reporting platform.

A user enters a public website URL and receives:

- website discovery
- page classification
- page analysis
- browser-engine compatibility testing
- performance analysis
- accessibility analysis
- SEO and content analysis
- security and technical diagnostics
- evidence-backed findings
- prioritised remediation actions
- executive and technical reports
- reanalysis
- before/after comparison
- exportable evidence

The product must become a real commercial-grade product, not a technical demo.

Target flow:

```text
Enter website URL
→ validate safely
→ discover internal URLs
→ classify pages/documents/media
→ select eligible HTML pages
→ analyse pages
→ test browsers
→ validate evidence
→ calculate scores
→ generate findings
→ generate Action Plan
→ generate reports and exports
→ allow reanalysis and comparison
```

---

# 4. Main Product Routes

```text
/                         → real website-analysis product
/presentation             → separate prepared reference/demo experience
/analysis-runs/{id}       → real progress and report
/analysis-runs/{id}/compare/{baselineId}
                          → before/after comparison
```

The prepared `/presentation` route must remain separate and explicit.

A failed real analysis must never silently display prepared demo data.

---

# 5. Fixed Architecture

- **Frontend:** Next.js + TypeScript + App Router
- **Backend:** FastAPI
- **Database:** PostgreSQL
- **Queue/state:** Redis
- **Workers:** Celery
- **Browser automation:** Playwright
- **Performance evidence:** Lighthouse and browser timing
- **Accessibility:** axe
- **Reporting:** deterministic HTML, PDF, JSON, CSV
- **Containerisation:** Docker Compose
- **Testing:** Pytest, Ruff, frontend lint, type-check, production build

Original baseline:

```text
Next.js + FastAPI + PostgreSQL + Playwright + Lighthouse + LLM
```

Redis and Celery were added later.

Do not replace the architecture unless explicitly approved.

---

# 6. Exactly Eight Runtime Agents

Agent IDs must remain unchanged:

1. `discovery_agent`
2. `performance_agent`
3. `accessibility_agent`
4. `site_diagnostics_agent`
5. `repository_intelligence_agent`
6. `evidence_validation_agent`
7. `remediation_agent`
8. `report_agent`

Customer-facing names:

1. Discovery Agent
2. Performance Agent
3. Accessibility Agent
4. Site Diagnostics Agent
5. Repository Intelligence Agent
6. Evidence Validation Agent
7. Remediation Agent
8. Report Agent

Do not add a ninth autonomous runtime agent.

Temporary audit subagents are allowed only for repository review; they must not become product runtime agents.

Repository Intelligence may report:

```text
Not applicable — no repository connected
```

That must not block website analysis.

---

# 7. Existing Tool Registry

Existing tools include:

1. `website_discovery`
2. `url_normalization`
3. `playwright_analysis`
4. `lighthouse_analysis`
5. `crux_field_evidence`
6. `browser_timing`
7. `axe_accessibility`
8. `accessibility_aggregation`
9. `site_diagnostics`
10. `repository_scanning`
11. `remediation_generation`
12. `report_generation`
13. `evidence_retrieval`
14. `approved_llm_completion`

Raw tool IDs must not appear in normal customer-facing views.

They may appear only in collapsed Technical Details or technical exports.

---

# 8. Existing Workflows

1. `full_website_analysis`
2. `repository_remediation`
3. `reanalysis`

The orchestrator supports:

- Celery dispatch
- retries
- timeouts
- cancellation
- checkpoints
- resume
- persisted task IDs
- exactly-once dispatch controls
- safe terminal states

---

# 9. Locked Scoring Rules

Do not change:

- **Overall Score Formula v1.0.0**
- **Priority Formula v1.0.0**

Historical reports must preserve the formula version used at the time.

Keep these separate:

- formula determinism
- website page coverage
- browser coverage
- evidence completeness
- report confidence

They are not the same measurement.

---

# 10. Completed Work

## Tasks 001–025

Completed foundation and capabilities include:

- monorepo foundation
- FastAPI backend
- Next.js frontend
- PostgreSQL
- Docker Compose
- Redis
- Celery
- project and website records
- discovery
- page analysis
- performance analysis
- accessibility analysis
- diagnostics
- scoring
- findings
- remediation
- reports
- exports
- CI and testing

## Task 025 — Site-Wide Diagnostics

Completed:

- migration `0015`
- 31 diagnostic rules
- 86 metrics synchronised backend/frontend
- detailed diagnostics
- APIs
- frontend diagnostics panels
- report integration

## Task 026 — Reusable Multi-Agent Platform

Completed:

- exactly eight agents
- fourteen tools
- three workflows
- deterministic orchestrator
- Celery execution
- retries
- timeouts
- cancellation
- checkpoints
- resume
- frontend agent visibility

## Task 027 — Explainable Scoring Intelligence

Completed:

- migration `0017`
- five score models
- formulas preserved
- extensive tests
- commit `eb606e2`

## Task 028 — End-to-End Analysis and Report Delivery

Completed:

- migration `0018`
- HTML export
- PDF export
- JSON export
- report history
- report UI
- commit `cafc6f2`

## Task 029 — Report Depth and Presentation

Completed:

- deeper report content
- presentation improvements
- commit `e5a2d80`

## Task 030 — Presentation Mode

Initial branch:

```text
task-030-presentation-mode
```

Initial commit:

```text
99bc7f03ff64ee581c444b1c4bb74b8ca67bc14c
```

The first version was too technical and too long.

## Task 030 Rescue

Introduced:

- business-oriented report
- Page Inventory
- browser matrix
- exact URL evidence
- maximum five examples in normal view
- progressive disclosure
- separate Technical Appendix
- concise 15-page main PDF
- 4-page technical appendix in the prepared dataset
- eight report tabs
- friendly agent descriptions

## Task 030B — Real Website Analysis Flow

Completed:

- `/` became the real product
- URL form
- URL normalisation
- SSRF protection
- project and website creation
- independent analysis runs
- real crawling
- real eight-agent workflow
- Chromium, Firefox, WebKit evidence
- progress UI
- report generation
- five report exports
- separate `/presentation` route

Commit:

```text
f8d5d4ae28bd096f50a3dc886adfda4500774e94
```

This is merged into `main`.

## CI Dependency Fix

Clean CI exposed missing dependencies:

- `reportlab`
- `axe-playwright-python`
- `pypdf`

Fixed in commit:

```text
e865acbca530b6d9951af5ab2484fb0bbffabea1
```

The CI workflow explicitly installs API, worker, and development requirements.

---

# 11. Current Task — Task 031

Task 031 is:

```text
Reanalysis and Before/After Comparison
```

Current branch:

```text
task-031-reanalysis-comparison
```

Task 031 is not yet committed or pushed.

## Task 031 goals

- reanalyse a completed website
- create an independent new run
- preserve the original baseline
- compare baseline/current
- show improved, regressed, unchanged, resolved, persistent, and new findings
- compare scores
- compare page coverage
- compare browser compatibility
- compare Action Plan progress
- export comparison HTML, PDF, JSON

## Migration

```text
20260730_0019_analysis_comparisons.py
```

It stores immutable reanalysis relationships and comparison persistence.

## Comparison route

```text
/analysis-runs/[analysisRunId]/compare/[baselineRunId]
```

The original `[currentRunId]` route conflicted with `[analysisRunId]`. That was fixed.

## Baseline rules

- baseline must never be mutated
- reanalysis creates a separate run
- unrelated websites cannot be compared
- finding identity must not depend only on database IDs
- lower coverage cannot create false resolved findings
- browser comparison requires comparable page-engine evidence

## Comparison states

- Improved
- Regressed
- Unchanged
- Resolved
- Persistent
- New
- Inconclusive
- Not comparable

---

# 12. Major Task 031 Corrections Already Implemented

## 12.1 Progress and Count Consistency

A prior UI displayed impossible values such as:

```text
Visited: 1
Successfully analysed: 13
```

Current invariant:

```text
successful <= visited <= scheduled <= eligible <= discovered
```

Separate counts:

- discovered
- normalized
- eligible
- scheduled
- visited
- successfully analysed
- failed
- skipped
- incomplete
- not scheduled
- browser tested

## 12.2 Workflow Dispatch and Progress

Fixed:

- exactly-once dispatch
- persisted Celery task IDs
- queued/running/partial/failed/completed states
- deterministic weighted progress
- stale-run detection
- safe retry/resume
- safe terminal states

Weighted stages use a deterministic model such as:

```text
5 / 15 / 20 / 20 / 10 / 15 / 7 / 8
```

## 12.3 Page Limit

Default maximum pages:

```text
50
```

Rules:

- <=50 eligible HTML pages: analyse all
- >50: critical pages + deterministic representative selection
- report excluded/not-scheduled pages
- sampled coverage must never look like full-site coverage

Planned profiles:

```text
Quick Scan       → up to 10 pages
Standard Scan    → up to 50 pages
Deep Scan        → up to 200 pages
Complete Scan    → every eligible page with warning
```

## 12.4 HTML, Document, and Media Classification

A major bug treated PDFs, images, and videos as failed HTML pages.

For Fluid Controls, ten “failed pages” were actually:

- 4 PDFs
- 4 JPGs
- 2 MP4s

Current resource categories:

- eligible HTML page
- document
- image
- video
- other media
- external URL
- duplicate
- canonical duplicate
- redirect
- unsafe
- blocked
- unsupported
- failed classification

Only eligible HTML pages count toward website-page coverage.

Documents/media belong in separate inventories.

## 12.5 Browser Coverage

A previous hidden constant limited browser testing to one page:

```text
REAL_BROWSER_PAGE_SAMPLE_LIMIT = 1
```

Correct rule:

```text
Every scheduled browser-eligible HTML page must be attempted by every available browser engine.
```

A page-analysis failure must not automatically prevent browser navigation.

Engines:

- Chromium
- Firefox
- WebKit

Firefox may be unavailable in Docker because of Linux non-root user-namespace restrictions.

Required UI text:

```text
Unavailable in this environment
```

## 12.6 Coverage Measurements

Separate:

### Discovery completeness

- Complete
- Partial
- Failed
- Inconclusive

### Analysed-page coverage

```text
successfully analysed eligible HTML pages / eligible scheduled HTML pages
```

### Browser coverage

Pages tested by selected engines.

### Evidence completeness

Required evidence groups collected.

### Full-site confidence

Whether discovery supports a full-site claim.

If discovery is partial:

```text
1 of 1 discovered eligible pages analysed.
Website discovery was incomplete, so full-site coverage is not established.
```

## 12.7 Gzip Discovery Bug

ZuiGO initially appeared as a one-page website.

Root cause:

- gzip-compressed HTML
- gzip-compressed `robots.txt`
- gzip-compressed sitemap content

Bodies were parsed without decompression.

Fixed fresh discovery:

```text
ZuiGO:
30 normalized URLs
24 eligible HTML pages

Sarvam:
292 normalized URLs
71 eligible HTML pages
```

Each URL retains its discovery source.

## 12.8 Polling Recovery

A failed request to:

```text
GET /api/v1/websites/{website_id}/metric-interpretations
```

triggered unhandled `Failed to fetch` errors and the Next.js red issue badge.

Fixed:

- independent resource polling
- 2/4/8/15-second bounded backoff
- last successful data retained
- successful timestamp retained
- local warnings for optional endpoints
- global warning only for essential failures
- comparison readiness no longer depends only on baseline ID
- report state is preserved after one failed request

## 12.9 Information Help System

Added:

- reusable information icon
- tooltip
- accessible dialog/popover
- central explanation registry
- keyboard access
- Escape-to-close
- focus restoration
- hydration-safe portal

Explanations may include:

- meaning
- included data
- excluded data
- calculation/determination
- interpretation
- limitation
- example
- evidence location

The help content must not repeat the visible label.

## 12.10 Runtime Help Crash

Sarvam project page crashed with:

```text
Invalid explanation for Eligible Pages:
Calculation or determination details are required for this concept.
```

Root cause:

- content-quality assertion executed during React render

Fixed architecture:

- registry validation runs in tests/build
- runtime uses safe retrieval
- invalid optional help hides the icon safely
- malformed help cannot crash the page
- no `console.error` for optional help metadata

## 12.11 Hydration Errors

Invalid structure existed such as:

```html
<p>
  <MetricInfoButton>
    <dialog>
      <div>
        <h2>
```

Fixed:

- semantic wrappers changed to `<div>` where needed
- dialog uses hydration-safe portal
- Escape behavior preserved
- focus restoration preserved
- invalid nesting tests added

## 12.12 Findings and Occurrence Accuracy

The report previously grouped unrelated security findings into a generic repeated issue.

Current identity includes:

- rule/finding signature
- category
- observed condition
- browser
- resource type
- affected URL

Security findings remain separate:

- CSP missing
- HSTS missing
- referrer policy missing
- frame protection missing
- permissions policy missing
- MIME protection missing

The system separates:

- unique findings
- total occurrences
- affected pages

Occurrence evidence retains:

- actual page URL
- final URL
- status
- browser
- selector/resource
- observed result
- expected result

## 12.13 Report Confidence

Separate:

- formula determinism
- page coverage
- browser coverage
- evidence completeness
- report confidence

Example:

```text
Formula determinism: 100%
Evidence completeness: 93.75%
Page coverage: 100%
Browser coverage: 66.7%
Report confidence: 66%
```

## 12.14 Policy and Accessibility Corrections

Fixed:

- Terms PDF is not automatically called a Privacy Policy
- uncertain policy evidence is shown as manual verification required
- accessibility zero values display as `0`
- “49 inapplicable” means automated rule results, not pages
- page/rule/finding/occurrence units are explicit

## 12.15 Friendly Labels

Normal UI hides:

- snake_case agent IDs
- raw rule codes
- raw category codes
- UUIDs
- internal paths
- provider metadata
- raw execution metadata

Example:

```text
CSP_MISSING
```

becomes:

```text
Content Security Policy missing
```

## 12.16 Responsive Containment

Added or improved:

- `overflow-x-auto`
- URL wrapping
- selector wrapping
- `min-w-0`
- safe table width
- responsive grids
- technical table containment
- HTML export containment
- PDF appendix containment

A complete visual redesign is still required in Task 032.

---

# 13. Latest Verification Status

Latest known technical verification:

```text
Focused tests: 71 passed
Full suite: 505 passed
Expected Windows symlink skip: 1
Ruff check: passed
Ruff format check: passed
Frontend lint: passed
Frontend type-check: passed
Frontend production build: passed
git diff --check: passed
```

Rerun appropriate verification after any new change.

---

# 14. Manual Verification Still Required

Task 031 is not ready to commit until browser-level verification passes on at least one reachable multi-page website.

Check:

- no red Next.js issue badge
- no hydration errors
- no runtime help crash
- multiple pages discovered
- discovery completeness is accurate
- partial discovery never claims full-site 100%
- documents/media are separate
- Chromium/WebKit coverage is accurate
- Firefox is honestly unavailable when blocked
- information icons open correctly
- help content is specific
- long URLs stay contained
- tables stay contained
- report history finishes loading
- comparison readiness is accurate
- exports open
- report banner matches actual state

Fluid Controls was not usable for final verification because Windows itself could not reach it.

Observed:

```powershell
Invoke-WebRequest https://fluidcontrols.com/
```

returned:

```text
Unable to connect to the remote server
```

Use another reachable multi-page website.

---

# 15. Environmental Limitation

## Firefox in Docker

Firefox may fail because the Docker host blocks the required non-root user namespace.

Required UI treatment:

```text
Firefox — Unavailable in this environment
```

Do not mark compatibility success/failure without evidence.

---

# 16. Data-Noise Problem to Improve

The user wants only relevant website intelligence.

The product must not collect or display unnecessary noise.

Potential noise sources:

- duplicate URLs
- tracking-query variants
- session URLs
- archive pages
- tag pages
- search-result pages
- repeated navigation text
- repeated footer text
- cookie banners
- duplicate content
- hidden template content
- redirects stored separately
- PDFs/images/videos treated as HTML
- social links
- email/phone links
- external websites
- empty pages
- soft-404 pages
- irrelevant assets
- repeated component text
- uncontrolled raw HTML/text storage

Relevant evidence includes:

- submitted URL
- normalized URL
- final URL
- canonical URL
- page title
- meta description
- headings
- meaningful main content
- internal links
- structured data
- response status
- content type
- performance evidence
- accessibility evidence
- browser evidence
- security headers
- diagnostics
- provenance
- timestamps
- limitations

The product must distinguish:

- observed fact
- calculated value
- inference
- recommendation
- unavailable evidence

Never present an inference as a confirmed fact.

---

# 17. Noise-Free Scraping Target

Target capabilities:

- URL normalization
- fragment removal
- default-port removal
- safe trailing-slash policy
- tracking-parameter removal
- meaningful-query preservation
- canonical URL identity
- duplicate-content fingerprints
- page-template detection
- main-content extraction
- boilerplate removal
- repeated paragraph removal
- cookie-banner filtering
- page-type classification
- soft-404 detection
- empty-page detection
- document/media separation
- crawl-depth controls
- include/exclude patterns
- domain/subdomain scope
- deterministic page importance
- deterministic page selection
- loop prevention
- sitemap parsing
- robots parsing
- gzip/Brotli decompression
- JavaScript-rendered link discovery
- source attribution
- extraction confidence
- exclusion reasons
- duplicate reasons

Preserve auditability when filtering noise.

---

# 18. Page Importance and Scan Profiles

## Quick Scan

- up to 10 eligible HTML pages
- critical pages first

## Standard Scan

- up to 50 eligible HTML pages
- default

## Deep Scan

- up to 200 eligible HTML pages

## Complete Scan

- every eligible HTML page
- explicit time/resource warning

Page-importance signals may include:

- homepage
- sitemap priority
- navigation presence
- internal-link count
- page depth
- semantic page type
- commercial importance
- policy importance
- uniqueness
- canonical status

Do not rely only on English path names.

---

# 19. Mandatory Next Task — Task 032

Task 032 is mandatory after Task 031 is committed and merged.

```text
Professional Report Organisation, Frontend Redesign, and PDF Redesign
```

The current frontend is too basic.

The current report is too long and technically dense.

The current PDF is messy.

The web report and PDF must become professional and client-presentable.

---

# 20. Task 032 Report Architecture

## Two report modes

1. Executive View
2. Technical View

Executive View is default.

Technical View exposes complete evidence.

Both use the same persisted source of truth.

## Executive View must answer within 30 seconds

1. What website was analysed?
2. How much was analysed?
3. What is the overall condition?
4. What are the biggest problems?
5. What should be fixed first?
6. What limitations affect the conclusion?

## Executive View should show

- website
- analysis date
- report status
- overall score
- report confidence
- discovery completeness
- page coverage
- browser coverage
- evidence completeness
- discovered URLs
- normalized URLs
- eligible HTML pages
- analysed pages
- failed pages
- documents
- media assets
- five category scores
- top five findings
- top five actions
- limitations

## Progressive disclosure

### Level 1 — Executive

- summary
- key scores
- top findings
- top actions
- major limitations

### Level 2 — Detailed Analysis

- performance
- accessibility
- SEO
- security
- technical quality
- browser compatibility
- page results

### Level 3 — Complete Evidence

- all occurrences
- exact URLs
- selectors
- raw measurements
- rule IDs
- agent execution
- provenance
- technical appendix
- JSON

Do not remove major evidence; organise it.

---

# 21. Task 032 Frontend Requirements

Planned components:

- `ReportHeader`
- `ScoreCard`
- `CoverageSummary`
- `CategoryScoreGrid`
- `FindingCard`
- `FindingsExplorer`
- `ActionPlanCard`
- `BrowserMatrix`
- `PageInventoryTable`
- `LimitationsPanel`
- `TechnicalDetails`
- `ReportNavigation`
- `ExportMenu`
- `StatusBadge`
- `SectionHeading`
- `MetricLabel`
- `InfoButton`

## Findings Explorer

Required:

- search
- severity filter
- category filter
- page filter
- browser filter
- status filter
- priority sort
- affected-page sort
- occurrence sort
- pagination
- collapsed cards
- view all affected pages
- open/copy URL
- complete evidence expansion

Default:

```text
20 findings per page
```

Do not render hundreds of findings fully expanded.

## Page Inventory

Show:

- URL
- title
- page type
- eligibility
- analysis status
- HTTP status
- final URL
- browser state
- findings count
- exclusion reason
- failure reason

Add search, filters, sorting, pagination, expandable details.

## Browser Matrix

Rows:

- analysed pages

Columns:

- Chromium
- Firefox
- WebKit

States:

- Compatible
- Partial
- Incompatible
- Inconclusive
- Unavailable
- Not tested

## Navigation

Sticky report navigation:

- Overview
- Coverage
- Scores
- Top Findings
- Action Plan
- Browser Compatibility
- Pages
- All Findings
- Agents
- Technical Details
- Exports

Mobile should use compact dropdown or horizontal navigation.

---

# 22. Mandatory PDF Redesign

The main PDF is a release blocker.

## Main PDF target

```text
15–20 pages
```

## Main PDF structure

1. Cover page
2. Contents
3. Executive Summary
4. Website Coverage
5. Browser Coverage
6. Overall and Category Scores
7. Top Five Findings
8. Top Five Actions
9. Browser Compatibility Summary
10. Page-Level Summary
11. Limitations
12. Methodology
13. Export/reference information

## Technical Appendix

Separate document containing:

- complete occurrences
- exact URLs
- selectors
- raw measurements
- rule codes
- provenance
- browser evidence
- Page Inventory
- agent execution details
- technical tables

## PDF defects to fix

- tables outside the page
- URLs not wrapping
- selectors not wrapping
- rows clipped across pages
- poor page breaks
- repeated content
- raw internal codes
- weak heading hierarchy
- too much detail in main report
- inconsistent spacing/fonts/alignment
- blank pages
- missing repeated table headers
- technical data dominating business content

## Required PDF behaviour

- professional cover
- page numbers
- headers/footers
- contents
- repeated table headers
- controlled page breaks
- landscape only where needed
- URL/selector wrapping
- no clipped rows
- maximum five examples in main PDF
- complete evidence in Technical Appendix
- no major content loss

The MVP is not complete until the web report and PDF are professional.

---

# 23. Information Icon Requirements

Add information icons where clarification is needed:

- major headings
- scores
- confidence
- website coverage
- browser coverage
- evidence completeness
- discovered/normalized/eligible/scheduled counts
- severity
- priority
- occurrences
- browser states
- agent status
- technical terms
- comparison classifications

Do not add icons beside obvious labels such as URL, Date, Search, Download, Back, Next, Previous.

## Content quality

Information must explain:

- meaning
- inclusion
- exclusion
- calculation/determination
- interpretation
- limitation
- evidence location

It must not repeat the visible label.

Concepts must remain distinct:

- Website Coverage
- Browser Coverage
- Evidence Completeness
- Formula Determinism
- Report Confidence
- Eligible HTML Pages
- Occurrences
- Accessibility Inapplicable Rules
- Partial Browser Result
- Browser Unavailable

---

# 24. Security Requirements

Preserve and improve:

- SSRF protection
- localhost blocking
- loopback blocking
- private-network blocking
- link-local blocking
- cloud metadata blocking
- DNS rebinding protection
- redirect revalidation
- HTTP/HTTPS-only
- safe file handling
- output escaping
- XSS protection
- SQL injection protection
- safe filenames
- safe artifact paths
- secret filtering
- sensitive-log filtering
- response-size limits
- decompression-size limits
- crawl-duration limits
- URL-count limits
- rate limiting
- resource cleanup
- container permission safety
- dependency hygiene

Do not bypass robots restrictions, authentication, access controls, CAPTCHAs, or rate limits.

---

# 25. Testing Rules

Automated tests must not crawl public websites.

Use local test servers, fixtures, synthetic local websites, controlled evidence.

Public sites are for manual verification only.

## Backend

```powershell
python -m pytest tests/ -v
python -m ruff check .
python -m ruff format --check .
```

## Frontend

```powershell
npm run lint
npm run typecheck
npm run build
```

## Docker/Celery

```powershell
docker compose build api worker
docker compose up -d postgres redis api worker
docker compose ps
docker compose exec worker celery -A worker_app.celery_app inspect ping
```

## Git

```powershell
git diff --check
git status --short
```

Use focused tests during implementation and full verification before commit/release.

---

# 26. Local Development Environment

Primary environment:

```text
Windows
PowerShell
VS Code
Docker Desktop
Python virtual environment
```

Project root:

```text
C:\Users\Ramashish\Documents\ZuiGO-Website-Intelligence
```

Frontend:

```text
http://localhost:3000
```

API docs:

```text
http://localhost:8000/docs
```

Use `localhost` consistently.

## Startup

```powershell
docker compose up -d postgres redis api worker
docker compose exec api python -m alembic upgrade head
docker compose ps
docker compose exec worker celery -A worker_app.celery_app inspect ping
```

Then:

```powershell
Remove-Item apps\web\.next -Recurse -Force -ErrorAction SilentlyContinue
npm run dev
```

If ports 3000/3001 are occupied:

```powershell
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
Where-Object { $_.LocalPort -in 3000,3001 } |
ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
}
```

---

# 27. Git History That Matters

Task 030 initial:

```text
99bc7f03ff64ee581c444b1c4bb74b8ca67bc14c
```

Task 030B real analysis:

```text
f8d5d4ae28bd096f50a3dc886adfda4500774e94
```

CI dependency fix:

```text
e865acbca530b6d9951af5ab2484fb0bbffabea1
```

Task 031 is not committed.

Do not assume Task 031 files exist on `main`.

---

# 28. Product Readiness

Estimated status before final Task 031 verification and Task 032:

```text
Client-presentable MVP: approximately 85–90%
```

Remaining blockers:

- final Task 031 manual verification
- report organisation
- frontend redesign
- PDF redesign
- noise-free data extraction audit
- release hardening
- multi-site regression testing
- release documentation
- showcase preparation

Future SaaS capabilities may include auth, organisations, permissions, quotas, billing, cloud deployment, monitoring, backups, tenant isolation, retention/deletion controls.

Do not let those distract from stabilising the MVP.

---

# 29. Required Work Order

1. Audit current dirty Task 031 tree.
2. Complete manual verification on a reachable multi-page website.
3. Commit/push Task 031 only after approval.
4. Merge Task 031 into `main`.
5. Create Task 032 branch.
6. Redesign frontend/report/PDF.
7. Audit and implement noise-free scraping after approval.
8. Final release hardening.
9. Multi-site verification.
10. Documentation, release tag, showcase preparation.

---

# 30. What Claude Should Do First

Begin with an audit-only checkpoint.

Report:

1. Current branch
2. Exact Git status
3. Summary of uncommitted work
4. Main Task 031 files
5. Whether migration `0019` exists
6. Whether information-help registry exists
7. Whether gzip discovery fix exists
8. Whether safe explanation retrieval exists
9. Whether tests pass
10. Remaining manual blockers
11. Risks of modifying the dirty tree
12. Confirmation nothing was changed

Do not immediately rewrite the project.

---

# 31. Product Quality Principles

## Evidence before claims

Every result must trace to persisted evidence.

## No silent assumptions

Unknown stays unknown.

## No false coverage

Analysing all discovered pages does not prove discovery was complete.

## No false browser support

Unavailable engine execution is not compatibility success/failure.

## No noisy data dump

Business users see clear findings/actions first.

## Complete evidence remains available

Technical evidence stays in detailed views/exports.

## No silent demo fallback

Real failure remains visible.

## No hidden scope

Page limits and exclusions are explicit.

## No invalid confidence

Confidence reflects missing pages, browsers, and evidence.

## No frontend crash from optional help metadata

The report remains usable.

## No major content removal

Use progressive disclosure.

---

# 32. Definition of MVP Completion

The MVP is complete only when:

- real website analysis works
- discovery is accurate
- page classification is accurate
- page limits are clear
- eligible pages are analysed according to scope
- browser coverage is honest
- evidence is traceable
- findings are accurate
- Action Plan is useful
- reanalysis works
- comparison works
- web report is professional
- PDF is professional
- Technical Appendix is complete
- information icons are useful
- UI is responsive
- no hydration errors exist
- no red Next.js issue badge exists
- full tests pass
- CI passes
- Docker services are healthy
- multi-site verification passes
- docs are updated
- release is tagged
- showcase flow is ready

---

# 33. Final Non-Negotiable Rules

1. Preserve exactly eight runtime agents.
2. Preserve Overall Score Formula v1.0.0.
3. Preserve Priority Formula v1.0.0.
4. Do not destroy the dirty Task 031 tree.
5. Do not commit generated reports/screenshots.
6. Do not use public websites in automated tests.
7. Do not silently substitute demo evidence.
8. Do not present partial discovery as full-site coverage.
9. Do not count PDFs/images/videos as eligible HTML pages.
10. Do not expose raw internal IDs in Executive View.
11. Do not let optional help metadata crash the UI.
12. Do not remove major report evidence.
13. Do not consider the MVP complete until the frontend and PDF are professional.
14. Do not commit/push without approval.
15. Do not claim completion without verification.

---

# 34. Suggested Claude Handoff Message

```text
Read AGENTS.md and ZuiGO_Website_Intelligence_Knowledge_Transfer.md first.

This repository contains substantial uncommitted Task 031 work.

Begin in audit-only mode.

Do not reset, restore, clean, stash, switch branches, commit, push, or rewrite
existing work.

Inspect the current branch, Git status, diff, migration 0019, Task 031
comparison implementation, discovery completeness model, information-help
registry, gzip decompression fix, safe explanation retrieval, browser coverage,
report generation, and current tests.

Return a checkpoint report before editing anything.
```

---

# 35. Closing Summary

ZuiGO Website Intelligence already has a strong technical foundation and real multi-agent analysis capability.

The project is not starting from zero.

The current priorities are:

1. safely finish Task 031
2. preserve correctness
3. reduce noisy data
4. improve discovery accuracy
5. organise the web report
6. redesign the frontend
7. redesign the PDF
8. complete release hardening
9. make the project client-presentable

Claude must continue from the existing architecture and working tree rather than replacing it.

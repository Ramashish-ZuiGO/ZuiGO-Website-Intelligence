# ZuiGO Website Intelligence
## MVP Implementation Action Plan for Claude

**Document version:** 1.0
**Prepared for:** Claude working inside the ZuiGO Website Intelligence repository
**Project root:** `C:\Users\Ramashish\Documents\ZuiGO-Website-Intelligence`
**Primary objective:** Finish a reliable, accurate, readable, client-presentable MVP without damaging existing work.

---

# 1. How Claude Must Use This Document

This is an implementation plan, not a suggestion list.

Claude should:

1. Read `AGENTS.md`.
2. Read `ZuiGO_Website_Intelligence_Knowledge_Transfer.md`.
3. Read `README.md`.
4. Inspect the current branch, working tree, migrations, tests, Docker services, frontend, backend, worker, report generation, and exports.
5. Use this action plan as the ordered MVP delivery checklist.
6. Make safe implementation decisions autonomously where the exact internal solution is not prescribed.
7. Preserve all working functionality and existing uncommitted work.
8. Report evidence for every claimed completion.

Claude should not restart the project, replace the architecture, or treat this repository as a blank codebase.

---

# 2. First Safety Check

Before modifying any file, run:

```powershell
git branch --show-current
git status --short
git diff --stat
git diff --check
```

Then record:

- current branch
- modified files
- untracked files
- staged files
- migration status
- Docker status
- current test status

## Prohibited actions

Do not run:

```text
git reset
git restore
git clean
git stash
git checkout -- <file>
git switch
git checkout <branch>
docker compose down -v
```

Do not:

- discard current work
- delete untracked files
- remove database volumes
- rewrite working modules without need
- commit
- push
- merge
- skip hooks
- use `--no-verify`
- add a ninth runtime agent
- change the locked scoring formulas
- replace failed real evidence with demo evidence

If the current working tree differs from the last known state, preserve it and continue from the real current state.

---

# 3. Fixed Architecture and Non-Negotiable Product Rules

Preserve:

- Next.js frontend
- FastAPI backend
- PostgreSQL
- Redis
- Celery
- Playwright
- Lighthouse
- axe accessibility
- deterministic evidence-grounded reporting
- Docker Compose

Preserve exactly eight runtime agents:

1. `discovery_agent`
2. `performance_agent`
3. `accessibility_agent`
4. `site_diagnostics_agent`
5. `repository_intelligence_agent`
6. `evidence_validation_agent`
7. `remediation_agent`
8. `report_agent`

Preserve:

- Overall Score Formula v1.0.0
- Priority Formula v1.0.0

Do not add another runtime agent.

Temporary audit subagents are allowed only for analysis and must not become product runtime agents.

---

# 4. What Counts as the MVP

The MVP is complete only when a user can:

1. Enter a public website URL.
2. Start analysis without selecting an arbitrary page limit.
3. See correct live progress.
4. Get honest discovery status.
5. Analyse all discoverable, public, in-scope, eligible HTML pages.
6. See separate inventories for HTML pages, documents, images, videos, external URLs, redirects, blocked URLs, and failed resources.
7. Receive accurate performance, accessibility, SEO, browser, security, and technical findings.
8. Receive a useful Action Plan.
9. Open a readable Executive View.
10. Open a detailed Technical View.
11. Download a professional Executive PDF.
12. Download a separate Technical Appendix.
13. Download structured HTML, JSON, and Page Inventory exports.
14. Reanalyse the same website.
15. Compare baseline and current results accurately.
16. Trust that all claims are based on retained evidence.
17. Understand limitations without repeated warnings or contradictory values.

The MVP is not complete if the system technically runs but the report is confusing, repetitive, contradictory, empty, or visually broken.

---

# 5. Uploaded Reports Must Be Used as Failing Acceptance Fixtures

Inspect these files when available:

```text
ZuiGO Website Intelligence Analysis.pdf
zuigo.ai-c745c04f.presentation(1).pdf
zuigo.ai-c745c04f.pdf
zuigo.ai-c745c04f.technical-appendix(1).pdf
zuigo.ai-c745c04f.html
zuigo.ai-c745c04f(1).json
zuigo.ai-c745c04f.page-inventory(1).json
```

Do not commit generated reports or screenshots.

Use them to reproduce and verify defects.

Confirmed issues visible in the current reports include:

- repeated discovery warnings
- repeated coverage metrics
- duplicate visible findings
- contradictory evidence denominators
- accessibility shown as 100/100 while evidence is unavailable
- 24 affected pages while only 23 eligible pages are reported
- Firefox shown as `0/23` instead of unavailable
- empty Action Plan despite many findings
- agent status repeated multiple times
- extracted homepage content shown before the actual analysis summary
- raw technical details exposed in the main report
- browser-print PDF containing localhost URLs and interactive controls
- main technical PDF expanding to hundreds of pages
- confusing discovery count such as 765 discovered versus 29 normalized
- crawl-depth warning shown repeatedly
- partial and incomplete statuses not explained clearly

These files are failing fixtures. The final implementation should be compared directly against them.

---

# 6. Delivery Priorities

## P0 — Blocks correctness or trust

- discovery-state correctness
- crawl completion and false partial discovery
- unique URL counting
- evidence consistency
- browser-state correctness
- finding deduplication
- non-empty Action Plan
- report contradictions
- no frontend crashes
- no false completion claims

## P1 — Required for client-ready MVP

- removal of Maximum Pages control
- automatic full-site discovery
- noise-free extraction
- Executive View
- Technical View
- professional PDF
- separate Technical Appendix
- responsive layout
- readable Page Inventory
- professional progress states
- reliable exports
- reanalysis comparison preservation

## P2 — Final MVP hardening

- performance optimization
- security regression
- multi-site manual testing
- release documentation
- CI verification
- stable release tag

## Explicitly post-MVP

Do not delay this MVP for:

- billing
- subscriptions
- payment gateway
- enterprise SSO
- organization management
- team permissions
- full multi-tenant SaaS isolation
- usage-based invoicing
- large-scale cloud orchestration
- marketplace integrations

Design current code so these can be added later, but do not implement them unless required for current correctness or safety.

---

# 7. Phase 0 — Establish a Safe Baseline

## Required actions

- [ ] Confirm current branch.
- [ ] Record exact Git state.
- [ ] Confirm Task 031 migration exists and is applied.
- [ ] Confirm current database revision.
- [ ] Confirm API, PostgreSQL, Redis, and worker status.
- [ ] Confirm Celery worker responds.
- [ ] Run focused smoke tests for discovery, reports, and comparison.
- [ ] Identify current failing tests before changing code.
- [ ] Create a written implementation map of the relevant files.

## Expected output before implementation

Claude should identify:

- discovery entry points
- crawler implementation
- URL normalization implementation
- progress/status schemas
- report view-model construction
- frontend report route
- PDF generator
- HTML generator
- comparison service
- action-generation service
- browser aggregation logic
- evidence completeness calculation
- finding identity logic

Do not make broad edits until these paths are understood.

---

# 8. Phase 1 — Correct Discovery State Semantics

## Problem

The UI may display:

```text
Website discovery was inconclusive. Full-site coverage is not established.
```

while discovery is still queued or running.

This is misleading.

## Required domain model

Keep these separate:

```text
stage_status
discovery_completeness
```

`stage_status` may be:

```text
queued
pending
initializing
running
completed
failed
cancelled
```

`discovery_completeness` must remain null during active states.

After a terminal result, it may be:

```text
complete
partial
inconclusive
failed
```

## Required messages

### Queued, pending, or initializing

```text
Website discovery is waiting to start.
```

### Running

```text
Website discovery is in progress. Full-site coverage will be evaluated after completion.
```

### Completed and complete

```text
Website discovery completed. Full-site coverage was established.
```

### Completed and partial

```text
Website discovery completed with partial coverage. Some website areas may not have been discovered.
```

### Completed and inconclusive

```text
Website discovery was inconclusive. Full-site coverage could not be established.
```

### Failed

Show the exact retained reason, such as:

- DNS failure
- connection failure
- timeout
- robots restriction
- blocked crawler
- authentication requirement
- sitemap failure
- redirect failure
- response-size protection
- decompression protection
- crawl safety limit
- cancellation

## Implementation requirements

Audit and fix:

- database enum/defaults
- ORM defaults
- API schemas
- serializers
- progress responses
- polling responses
- frontend type definitions
- conditional rendering
- fallback values
- report mappers
- export mappers

Never infer `inconclusive` from:

- null
- undefined
- zero URLs
- missing fields
- progress below 100%
- default fallbacks
- active analysis state

## Acceptance criteria

- [ ] Active discovery never shows a terminal warning.
- [ ] Running with zero URLs is still shown as running.
- [ ] `inconclusive` appears only after a terminal result.
- [ ] Polling and recovery still work.
- [ ] Existing persisted evidence remains authoritative.

---

# 9. Phase 2 — Remove the User Page Limit and Implement Automatic Full-Site Discovery

## Product decision

Remove the normal user-facing Maximum Pages control.

The standard flow should be:

```text
Website URL
Start Full-Site Analysis
```

The user should not need to guess how many pages the website contains.

## Full-site definition

Analyse every discoverable, public, in-scope, eligible HTML page found through:

- submitted root URL
- robots.txt
- sitemap files
- sitemap indexes
- nested sitemaps
- HTML links
- navigation
- footer links
- redirects
- canonical relationships
- rendered JavaScript links where needed
- new internal links discovered during crawling

Full-site does not mean:

- authenticated pages
- private pages
- CAPTCHA-protected pages
- blocked areas
- unsafe URLs
- unsupported protocols
- external websites
- genuinely undiscoverable pages
- infinite generated URL spaces

## Internal safety controls must remain

Keep:

- SSRF protection
- private-network blocking
- DNS rebinding protection
- redirect revalidation
- request timeout
- job timeout
- response-size limits
- decompression-size limits
- crawl-loop prevention
- URL explosion prevention
- bounded retries
- rate control
- cancellation
- checkpoint and resume
- bounded concurrency

These are safety controls, not business page limits.

## Advanced settings

The normal user should not see a page-count slider.

Advanced settings may include:

- include subdomains
- obey robots.txt
- include paths
- exclude paths
- selected browser engines
- technical scope controls
- administrator-only safety settings

Claude may decide the best safe internal architecture, but the user experience must remain automatic full-site analysis.

---

# 10. Phase 3 — Fix Crawl-Depth Behaviour

## Current issue

The report repeatedly shows:

```text
The HTML crawl-depth limit was reached.
```

This may be caused by actual incomplete crawling or by incorrect depth semantics.

## Required investigation

Inspect:

- queue/frontier implementation
- recursion depth
- URL path depth
- sitemap depth
- redirect depth
- rendered link discovery
- duplicate links
- canonical URLs
- fragment links
- query variants
- template links
- employee verification URLs
- pagination
- environment defaults
- configuration defaults
- database-stored scope values

## Desired behaviour

Use a frontier-based crawl:

1. normalize candidate
2. validate scope and safety
3. deduplicate canonical identity
4. classify resource
5. fetch or schedule
6. extract new in-scope links
7. continue until the valid frontier is exhausted

Depth may remain as metadata or a safety signal, but it must not falsely stop an ordinary finite website.

## Required partial-discovery evidence

When discovery is genuinely partial because of a limit, persist:

- exact limit type
- exact limit value
- number of remaining unique candidates
- sample unprocessed URLs
- whether retry/resume can continue
- whether the limit was safety-related
- whether discovered pages remain usable

Do not mark discovery partial because repeated duplicate links were encountered at deeper traversal levels.

## Claude judgment area

The exact crawler design may be changed if needed.

Desired outcome:

- complete finite websites should finish without arbitrary depth failure
- infinite or dangerous URL spaces must still terminate safely
- any incomplete discovery must be honest and explainable

---

# 11. Phase 4 — Correct URL Counting and Discovery Metrics

## Current issue

A result like:

```text
Discovered: 765
Normalized: 29
Duplicate-normalized: 736
Eligible: 23
```

suggests repeated link occurrences may be counted as discovered pages.

## Required metrics

Track separately:

- `raw_link_occurrence_count`
- `unique_raw_candidate_count`
- `unique_normalized_url_count`
- `canonical_page_count`
- `eligible_html_page_count`
- `document_count`
- `image_count`
- `video_count`
- `other_media_count`
- `external_url_count`
- `redirect_count`
- `blocked_count`
- `unsafe_count`
- `inaccessible_count`
- `excluded_count`
- `duplicate_variant_count`
- `failed_classification_count`

## Rules

- “Discovered URLs” must mean unique discovered candidate URLs.
- Repeated links belong in raw link occurrences.
- The same navigation link repeated across 20 pages is one unique URL.
- Fragments should not create separate page identities.
- Tracking parameters should not create separate page identities.
- Meaningful query parameters must be preserved.
- Redirect sources and final canonical pages must remain distinguishable.
- Link graph edge count must never be presented as page count.

## Required invariants

```text
successful <= visited <= scheduled <= eligible <= canonical unique candidates
```

Also validate:

```text
unique affected eligible pages <= eligible page inventory
```

The report must fail validation in tests if these relationships are impossible.

---

# 12. Phase 5 — Noise-Free Website Data Extraction

## Goal

Collect only information useful for website analysis.

Do not create an uncontrolled copy of the website.

## Remove or separate noise

- tracking parameters
- fragments
- session identifiers
- repeated navigation
- repeated footer text
- cookie banners
- repeated template blocks
- duplicate paragraphs
- empty sections
- hidden irrelevant elements
- soft-404 pages
- unsupported assets
- social media URLs
- email links
- telephone links
- external booking links
- repeated canonical variants
- redirects represented as independent final pages
- infinite pagination
- calendar URL explosions
- search-result pages with no useful value
- duplicate tag/archive pages

## Retain useful evidence

For each HTML page retain:

- submitted URL
- normalized URL
- final URL
- canonical URL
- page title
- meta description
- page type
- language
- headings
- meaningful main content
- primary calls to action
- structured data
- important internal links
- HTTP status
- content type
- discovery source
- response timing
- accessibility evidence
- performance evidence
- SEO evidence
- security evidence
- browser evidence
- diagnostics
- extraction confidence
- evidence provenance
- timestamps
- limitations

## Template families

Repeated employee, product, service, blog, category, or verification pages should be grouped by template when appropriate.

Executive reporting should summarize the template-level problem once.

Technical evidence must still preserve every affected URL.

## Claude judgment area

Choose the best practical extraction strategy for this codebase.

Desired outcome:

- low noise
- high evidence traceability
- no loss of important content
- no repeated boilerplate dominating analysis
- deterministic behaviour suitable for testing

---

# 13. Phase 6 — Browser Accuracy and Availability

## Current issues

The report may show:

- Firefox `0/23`
- `0% tested`
- pages marked partially compatible because Firefox was unavailable
- zero-issue compatibility findings
- `None%`
- timing differences presented as compatibility failures

## Required browser states

```text
compatible
partial
incompatible
inconclusive
unavailable
not_tested
```

## Rules

- unavailable is not compatible
- unavailable is not incompatible
- unavailable alone must not make the page partial
- issue count zero must not produce a compatibility finding
- normal timing variation is not a compatibility defect
- partial requires retained approved evidence
- browser findings must identify engine, viewport, page, observation, expected behaviour, and evidence

## Required wording

When Chromium and WebKit pass and Firefox is unavailable:

```text
Compatible on tested engines. Firefox was unavailable in this environment.
```

Do not show:

```text
Partially compatible
```

unless an available tested engine has a real issue.

## UI requirement

Display Firefox as:

```text
Unavailable in this environment
```

Do not present it as `0% compatibility`.

---

# 14. Phase 7 — Create One Canonical Report Data Model

## Problem

Different sections currently calculate the same values independently, producing contradictions.

## Required architecture

Create one canonical report view model or equivalent domain service.

Example concept:

```text
ExecutiveReportViewModel
```

The exact name is Claude’s decision.

The frontend, HTML export, Executive PDF, Presentation PDF, and summary endpoints should use the same canonical values.

## The canonical model must own

- website identity
- analysis status
- discovery status
- discovery completeness
- unique discovery counts
- page funnel
- browser coverage
- evidence completeness
- score confidence
- report confidence
- category scores
- category availability
- finding totals
- occurrence totals
- affected-page totals
- top findings
- Action Plan
- limitations
- agent summary
- export metadata

## Required validations

- no contradictory denominators
- no impossible page counts
- unavailable evidence cannot be passed
- unavailable browser cannot be partial or failed
- identical finding identity cannot appear twice
- Action Plan cannot be empty when actionable findings exist
- identical limitation should not repeat in Executive View
- all totals must reconcile with inventories

## Known contradictions to fix

- `5/5 required groups` versus `13/16`
- Accessibility `100/100` versus unavailable accessibility evidence
- 24 affected pages versus 23 eligible pages
- Remediation completed versus empty Action Plan
- Report available versus Report Agent partial without explanation
- Technical Quality 100 despite unavailable evidence
- score confidence mixed with report confidence
- full-site coverage mixed with analysed-page coverage

Do not change the locked formulas.

Fix evidence inclusion, mapping, confidence, and presentation.

---

# 15. Phase 8 — Semantic Deduplication

## Duplicate limitation control

Give each limitation a stable semantic identity, such as:

```text
discovery_partial
crawl_depth_limit
firefox_unavailable
accessibility_unavailable
evidence_incomplete
report_confidence_reduced
```

## Rules

- show each important limitation once in Executive View
- explain full detail once in Evidence Limitations
- other sections should reference it, not repeat the same sentence
- no identical warning sentence should appear more than once in Executive View
- no identical metric card in adjacent sections
- no repeated agent status blocks
- no repeated evidence reference lists in the main report

## Finding deduplication

Finding identity should include appropriate dimensions:

- rule signature
- category
- observed condition
- canonical resource
- browser
- viewport
- template family
- remediation identity

Do not merge unrelated findings.

Do not duplicate the same finding because it belongs to multiple report sections.

When two findings share the same visible title but represent different conditions, create clear distinct titles based on evidence.

---

# 16. Phase 9 — Build a Useful Deterministic Action Plan

## Current issue

The report may contain many findings but an empty Action Plan.

This is unacceptable for the MVP.

## Required behaviour

When actionable findings exist, generate a deterministic evidence-grounded Action Plan even when an external LLM is unavailable.

## Each action should include

- plain-language action
- related findings
- why it matters
- affected scope
- priority
- estimated effort
- recommended owner type
- implementation guidance
- verification method
- dependencies
- limitation

## Required groups

- Top five actions
- Quick wins
- Strategic fixes

## Rules

- do not generate unsupported claims
- do not invent quantified business impact
- do not leave the Action Plan empty
- do not repeat one recommendation for every occurrence
- group template-level and site-wide fixes intelligently
- retain full affected URLs in detailed evidence

## Claude judgment area

Claude should choose the best deterministic remediation mapping architecture.

Desired outcome:

- useful without external LLM
- evidence-grounded
- concise in Executive View
- complete in Technical View

---

# 17. Phase 10 — Redesign the “View Analysis” Experience

## Executive View must be the default

The first screen after clicking View Analysis should answer:

1. What was analysed?
2. Did analysis complete?
3. Was full-site discovery established?
4. What is the overall score?
5. How confident is the report?
6. What are the biggest problems?
7. What should be fixed first?
8. What limitations matter?

## Required section order

1. Report Header
2. Executive Summary
3. Coverage and Confidence
4. Category Scores
5. Top Five Findings
6. Top Five Actions
7. Browser Compatibility Summary
8. Important Page Groups
9. Evidence Limitations
10. Export and Reanalysis Controls

## Executive Summary metrics

Show each once:

- overall score
- report confidence
- discovery completeness
- unique discovered URLs
- eligible HTML pages
- analysed pages
- browser coverage
- evidence completeness
- high-priority findings

## Move out of the top section

Do not show Extracted Content before the report.

Move extracted page content to:

- Page Details
- Page Inventory row expansion
- Technical View

## Coverage design

Show a compact funnel or table:

```text
Unique candidates
→ normalized
→ canonical
→ eligible HTML
→ scheduled
→ visited
→ analysed
```

Do not repeat the same metrics in several large card groups.

## Executive View must not show

- UUIDs
- evidence IDs
- tool IDs
- provider IDs
- raw payloads
- database structures
- raw link graph edges
- internal task metadata
- full page inventory
- complete agent execution payloads

## Responsive requirements

- no horizontal overflow
- tables must be scrollable or transformed on mobile
- long URLs must wrap safely
- cards must resize
- navigation must work on desktop and mobile
- no hydration errors
- no optional-help crash
- no red Next.js issue badge

---

# 18. Phase 11 — Technical View and Page Inventory

## Technical View should contain

- all findings
- all occurrences
- Page Inventory
- Browser Matrix
- extracted page content
- complete agent execution
- methodology
- evidence provenance
- raw measurements
- reanalysis comparison details
- technical limitations

## Page Inventory requirements

Columns should include:

- URL
- title
- page type
- classification
- eligibility
- scheduled
- visited
- analysed
- HTTP status
- final URL
- browser status
- finding count
- exclusion reason
- failure reason

Add:

- search
- filter
- sort
- pagination
- row expansion
- copy URL
- open URL

The full Page Inventory must not dominate Executive View.

Show only summary and top affected pages in Executive View.

---

# 19. Phase 12 — Professional PDF and Export Redesign

## Current problem

The current main PDF behaves like a browser printout and may expose:

- localhost URLs
- interactive controls
- filters
- accordions
- buttons
- split tables
- repeated metrics
- duplicated warnings
- empty sections
- raw technical data

Another PDF may expand to hundreds of pages because raw technical content is dumped into the main report.

## Required export separation

1. Executive PDF
2. Technical Appendix PDF
3. HTML Report
4. JSON Evidence Export
5. Page Inventory Export
6. Comparison Export

## Executive PDF target

Approximately 15–20 pages.

Recommended structure:

1. Cover
2. Table of contents
3. Executive summary
4. Coverage and confidence
5. Category scores
6. Top findings
7. Action Plan
8. Browser summary
9. Page summary
10. Limitations
11. Methodology
12. Export/reference details

## Executive PDF requirements

- professional cover
- clean typography
- consistent spacing
- page numbers
- header/footer
- controlled page breaks
- wrapped URLs
- repeated table headers
- no clipped rows
- no empty final page
- no interactive controls
- no localhost URL
- no raw IDs
- maximum five examples per finding
- no repeated warning sentences
- no raw link graph

## Technical Appendix requirements

Retain:

- all occurrences
- exact URLs
- selectors
- raw measurements
- rule identifiers
- evidence references
- browser evidence
- Page Inventory
- agent execution
- provenance
- detailed methodology

Technical Appendix may be longer, but it must remain organized and readable.

Do not dump hundreds of duplicate link edges as prose.

Use compact structured tables, grouped evidence, JSON references, or summaries with full machine-readable export.

## HTML export

HTML export should use the same canonical report model and visual hierarchy.

## JSON export

JSON should retain complete evidence and stable schema.

## Comparison exports

Comparison HTML, PDF, and JSON must remain functional and use the same corrected metrics.

---

# 20. Phase 13 — Multi-Agent and Worker Optimization

Keep exactly eight runtime agents.

Run independent work in parallel where safe:

- discovery branches
- page analysis
- Chromium
- Firefox
- WebKit
- accessibility
- performance
- diagnostics
- evidence validation
- remediation preparation
- report preparation

## Required controls

- bounded concurrency
- idempotent dispatch
- persisted task IDs
- cancellation
- retries
- checkpoints
- resume
- browser cleanup
- database connection control
- deterministic progress
- safe terminal states

## Prevent

- duplicate Celery tasks
- duplicate browser work
- repeated page fetching
- repeated parsing
- task storms
- worker memory exhaustion
- browser process leaks
- database connection exhaustion
- repeated report generation loops

## Claude judgment area

Claude may change internal parallelization where required.

Desired outcome:

- faster analysis
- no duplicate work
- stable resource use
- accurate progress
- safe recovery

---

# 21. Phase 14 — Security Hardening Required for MVP

Preserve and test:

- SSRF protection
- localhost blocking
- loopback blocking
- private-network blocking
- link-local blocking
- cloud metadata blocking
- DNS rebinding protection
- redirect revalidation
- HTTP/HTTPS-only protocols
- unsafe file handling protection
- output escaping
- XSS protection
- SQL injection protection
- command injection protection
- safe filenames
- safe artifact paths
- secret filtering
- sensitive-log filtering
- response-size limits
- decompression-size limits
- crawl-duration limits
- URL explosion protection
- browser cleanup
- container permission safety
- dependency hygiene

Do not bypass:

- robots restrictions
- authentication
- access controls
- CAPTCHAs
- private content
- rate limits

Security controls must produce honest partial or blocked states, not fake successful evidence.

---

# 22. Phase 15 — Automated Tests

Automated tests must use local fixtures and local test servers.

Do not crawl public websites in automated tests.

## Discovery state tests

- [ ] queued
- [ ] pending
- [ ] initializing
- [ ] running with zero URLs
- [ ] running with some URLs
- [ ] completed complete
- [ ] completed partial
- [ ] completed inconclusive
- [ ] failed with retained reason
- [ ] null completeness
- [ ] missing completeness
- [ ] no active-state inconclusive warning

## Crawl tests

- [ ] sitemap
- [ ] sitemap index
- [ ] nested sitemap
- [ ] gzip
- [ ] Brotli
- [ ] relative links
- [ ] rendered links
- [ ] redirects
- [ ] canonical handling
- [ ] cyclic links
- [ ] deep finite website
- [ ] query explosion
- [ ] pagination protection
- [ ] fragment deduplication
- [ ] tracking-parameter removal
- [ ] meaningful-query retention
- [ ] frontier exhaustion
- [ ] honest partial result
- [ ] no false depth warning

## Count tests

- [ ] raw link occurrences
- [ ] unique candidates
- [ ] normalized URLs
- [ ] canonical pages
- [ ] eligible HTML pages
- [ ] documents
- [ ] images
- [ ] videos
- [ ] external URLs
- [ ] redirects
- [ ] blocked URLs
- [ ] duplicate variants
- [ ] impossible count invariants fail

## Browser tests

- [ ] unavailable engine
- [ ] compatible tested engines
- [ ] partial with real evidence
- [ ] no zero-issue finding
- [ ] no `None%`
- [ ] unavailable does not create partial page status
- [ ] viewport and engine evidence retained

## Report consistency tests

- [ ] one canonical evidence denominator
- [ ] category availability consistent
- [ ] affected-page totals reconcile
- [ ] missing evidence is not passed
- [ ] report confidence is separate from formula determinism
- [ ] discovery completeness is separate from analysed-page coverage
- [ ] duplicate sentence prevention
- [ ] duplicate limitation prevention
- [ ] duplicate finding prevention
- [ ] non-empty Action Plan when actionable findings exist
- [ ] exactly eight runtime agents
- [ ] scoring formulas unchanged

## Frontend tests

- [ ] queued discovery message
- [ ] running discovery message
- [ ] complete discovery message
- [ ] partial discovery message
- [ ] failed discovery message
- [ ] no optional-help crash
- [ ] no invalid nesting
- [ ] no hydration mismatch
- [ ] long URL containment
- [ ] responsive tables
- [ ] Executive View excludes raw IDs
- [ ] Technical View retains evidence
- [ ] Page Inventory pagination
- [ ] Browser Matrix states

## Export tests

- [ ] Executive PDF bounded page count
- [ ] no localhost URL
- [ ] no interactive controls
- [ ] no empty final page
- [ ] URL wrapping
- [ ] repeated table headers
- [ ] Technical Appendix retains evidence
- [ ] HTML and PDF metrics match
- [ ] JSON schema remains stable
- [ ] comparison exports remain functional

---

# 23. Phase 16 — Manual Verification

Use public websites only for manual verification.

Test at least:

1. one small multi-page website
2. one medium website
3. one site with sitemap indexes, documents, media, or deep paths

## Verify for each site

- [ ] URL validation succeeds
- [ ] discovery state transitions correctly
- [ ] no early inconclusive warning
- [ ] unique page counts are believable
- [ ] no arbitrary page slider exists
- [ ] all discovered eligible HTML pages are scheduled
- [ ] documents and media are separate
- [ ] no false full-site claim
- [ ] browser availability is honest
- [ ] findings are understandable
- [ ] duplicate findings are absent
- [ ] Action Plan is populated
- [ ] no red Next.js issue badge
- [ ] no hydration error
- [ ] no horizontal overflow
- [ ] Executive View is understandable
- [ ] Technical View is usable
- [ ] Executive PDF is professional
- [ ] Technical Appendix is organized
- [ ] HTML export opens
- [ ] JSON export opens
- [ ] Page Inventory opens
- [ ] reanalysis works
- [ ] comparison works

## ZuiGO regression

Regenerate the ZuiGO report and compare it against the uploaded failing fixtures.

Confirm:

- repeated warning sentences are removed
- duplicate findings are removed
- evidence denominator is consistent
- Accessibility availability is honest
- affected-page count is valid
- Firefox is unavailable, not failed
- Action Plan is populated
- Extracted Content is moved out of the top
- no localhost URL appears in PDF
- Executive PDF stays within target length
- Technical Appendix contains complete evidence

---

# 24. Required Verification Commands

Run focused tests during implementation.

At the end run:

```powershell
python -m pytest tests/ -v
python -m ruff check .
python -m ruff format --check .

npm run lint
npm run typecheck
npm run build

docker compose build api worker
docker compose up -d postgres redis api worker
docker compose exec api python -m alembic upgrade head
docker compose ps
docker compose exec worker celery -A worker_app.celery_app inspect ping

git diff --check
git status --short
```

Do not claim completion if any required verification fails.

After two failed repair attempts on the same issue:

- stop repeated speculative edits
- identify the blocker
- preserve the working tree
- report exact evidence
- propose the safest next move

---

# 25. Claude Decision Areas

The following implementation details are intentionally not prescribed.

Claude should inspect the current architecture and choose the safest professional solution.

## Crawler architecture

Desired outcome:

- frontier exhaustion for finite sites
- safe termination for infinite spaces
- accurate partial-discovery evidence

## Main-content extraction

Desired outcome:

- remove noise
- preserve meaningful content
- retain provenance
- deterministic tests

## Canonical report model

Desired outcome:

- one source of customer-facing truth
- no contradictions
- shared across UI and exports

## Action Plan generation

Desired outcome:

- useful without external LLM
- evidence-grounded
- grouped intelligently
- never empty when actionable findings exist

## Parallelization

Desired outcome:

- faster analysis
- bounded resource use
- no duplicate work
- safe recovery

## PDF generation library and layout approach

Desired outcome:

- professional Executive PDF
- readable Technical Appendix
- no browser-print artifacts
- maintainable templates

Claude may refactor these areas when necessary, but should avoid unrelated rewrites.

---

# 26. Definition of Done

The MVP is done only when all of the following are true.

## Discovery

- [ ] active discovery messages are correct
- [ ] no false inconclusive warning
- [ ] full-site discovery is automatic
- [ ] no user page-count slider
- [ ] finite sites are not stopped by an arbitrary depth limit
- [ ] safety limits remain
- [ ] incomplete discovery is explained precisely

## Data quality

- [ ] unique URL counts are accurate
- [ ] repeated links are not counted as pages
- [ ] documents and media are separate
- [ ] extraction noise is reduced
- [ ] provenance remains available

## Accuracy

- [ ] findings are evidence-grounded
- [ ] unavailable evidence is not passed
- [ ] browser states are correct
- [ ] counts reconcile
- [ ] formulas remain unchanged
- [ ] comparison remains accurate

## Reporting

- [ ] one canonical report model exists
- [ ] no contradictory metrics
- [ ] no repeated warning sentences
- [ ] no duplicate visible findings
- [ ] Action Plan is useful
- [ ] Executive View is readable
- [ ] Technical View preserves evidence
- [ ] Page Inventory is searchable and paginated

## Exports

- [ ] Executive PDF is professional
- [ ] Technical Appendix is separate
- [ ] no localhost URLs
- [ ] no interactive controls
- [ ] no hundreds-page raw dump in the main report
- [ ] HTML, JSON, Page Inventory, and comparison exports work

## Engineering

- [ ] exactly eight agents remain
- [ ] security protections remain
- [ ] full test suite passes
- [ ] Ruff passes
- [ ] lint passes
- [ ] type-check passes
- [ ] build passes
- [ ] Docker services are healthy
- [ ] Celery responds
- [ ] no hydration errors
- [ ] no red Next.js issue badge
- [ ] no horizontal overflow

## Release

- [ ] final diff reviewed
- [ ] documentation updated
- [ ] no generated reports committed
- [ ] no unrelated changes
- [ ] commit and push performed only after explicit approval
- [ ] merge performed only after explicit approval
- [ ] stable release tag created only after final approval

---

# 27. Required Final Report from Claude

Do not give a vague completion message.

Return:

1. Overall completion status
2. Exact Git branch and status
3. Root causes found
4. Main files changed
5. Discovery-state changes
6. Full-site crawling changes
7. Crawl-depth resolution
8. URL counting changes
9. Noise-reduction changes
10. Browser-state corrections
11. Report consistency changes
12. Duplicate sentence and finding removal
13. Action Plan behaviour
14. Executive View changes
15. Technical View changes
16. Executive PDF page count
17. Technical Appendix result
18. Focused tests
19. Full verification results
20. Manual sites tested
21. Remaining genuine limitations
22. Confirmation that nothing was committed or pushed

Every completion claim must include evidence.

---

# 28. Execution Order Summary

Follow this order unless a dependency requires a small adjustment:

```text
1. Preserve and inspect current work
2. Fix discovery state semantics
3. Remove Maximum Pages control
4. Fix crawl-depth/frontier behaviour
5. Correct unique URL counting
6. Reduce scraping noise
7. Correct browser availability and findings
8. Build canonical report model
9. Deduplicate limitations and findings
10. Generate deterministic Action Plan
11. Redesign Executive View
12. Build Technical View and Page Inventory
13. Redesign Executive PDF and Technical Appendix
14. Optimize agents and workers
15. Run security regression
16. Add deterministic tests
17. Run full verification
18. Run multi-site manual verification
19. Compare regenerated ZuiGO reports against failing fixtures
20. Report exact results
```

Do not commit or push until the user explicitly approves the completed implementation.

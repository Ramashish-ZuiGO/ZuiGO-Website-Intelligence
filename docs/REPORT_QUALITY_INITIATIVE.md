# Report Quality & Production-Readiness Initiative — Plan

**Status: Audit in progress, started 2026-08-16.** This document is the
single source of truth for this initiative and is written to be portable —
any competent engineer or any LLM (not just Claude) should be able to resume
work from this file alone, combined with the existing repo docs it
references (`CLAUDE.md`, `docs/PRODUCT_MASTER_SPEC.md`,
`docs/SCORING_METHODOLOGY.md`, `docs/DEVICE_OS_BROWSER_QA_PLAN.md`). Update
this file every time a module below moves from planning to a decision to
implementation. Do not let decisions live only in chat history.

## 1. Why this document exists

The user has handed over ownership of the entire report-generation system
("i am giving this project to u, have to improve everything") and wants a
full, evidence-based audit of every report section for real gaps/blockers —
not assumptions — before any further implementation. This product **is
deployed live**, so every claim the report makes must be correct, cited, and
explainable in plain language; nothing may be fabricated. The user wants:

- A module-by-module plan (one module per report section/concern), discussed
  and approved one at a time before implementation — same working style as
  the Device/OS/Browser QA initiative (`docs/DEVICE_OS_BROWSER_QA_PLAN.md`),
  which this document deliberately mirrors in structure.
- Real DB-backed, logged, traceable results everywhere.
- Feedback collection as a real feature, not an afterthought.
- Production-level, simple, usable, deployable — not over-engineered.
- This document kept continuously up to date so ownership can transfer to a
  different session or a different LLM entirely with zero context loss.

**Do NOT implement a module without discussing it with the user first.**
This mirrors the explicit process the user set for the QA initiative and was
re-stated explicitly for this one.

## 2. Required reading before touching this initiative

- `CLAUDE.md` — locked invariants (exactly 8 agents, scoring formulas,
  SSRF protections, immutable snapshots, Browser UAT truth contract,
  comparison direction, no fabricated evidence).
- `docs/PRODUCT_MASTER_SPEC.md`, `docs/SCORING_METHODOLOGY.md`,
  `docs/REPORT_DELIVERY.md`, `docs/MULTI_AGENT_ARCHITECTURE.md`.
- `docs/DEVICE_OS_BROWSER_QA_PLAN.md` — the Browser UAT / Tier 0 system this
  initiative's first two confirmed bugs (below) were found in. Fully shipped
  as of 2026-08-16 except the iPad Simulator known gap.
- The canonical report snapshot is built in one function:
  `apps/api/app/services/report_delivery.py`'s `_build_sections`. Every
  artifact (JSON/PDF/HTML/Technical Appendix) reads from the SAME snapshot
  payload it returns — this is the correct place to look for how any
  section's data actually gets built.

## 3. Confirmed findings so far (real, code-verified — not assumptions)

### Finding 1 — FIXED 2026-08-16: Tier 0 evidence silently disappeared across executions

**What was wrong:** `fetch_latest_tier0_page_results` /
`fetch_latest_tier0_structural_results` in
`apps/api/app/services/browser_uat_tier0.py` selected only the SINGLE most
recent Tier 0 execution for an analysis run. Since Lane A/B (automatic
desktop Chrome/Edge/Safari, via GitHub Actions) and Lane C (manual Android
CLI) are always separate executions, ingesting a later, narrower Android-only
result made the earlier, still-valid desktop Chrome/Edge/Safari evidence
disappear entirely — the customer-facing Browser Compatibility matrix
reverted those rows to "Not verified in current environment" even though
real evidence for them still existed in the database.

**How found:** User reported the frontend "Browser UAT & Responsive" tab
looked like everything failed, with a screenshot. Investigated live via the
API and confirmed only 1 of 6 real browser/platform combinations was
surfacing.

**Fix:** New `_usable_tier0_executions`/`_merged_usable_page_results` in
`browser_uat_tier0.py` merge evidence across ALL usable executions for an
analysis run, deduplicated by `(browser_channel, platform, url)` — the
freshest execution wins per combination, but older executions still
contribute combinations the newer one doesn't cover. 4 tests updated/added,
full suite 1105 passed/1 skipped. Live-verified: a freshly generated report
now shows Chrome/Edge/Safari as `PARTIALLY_VERIFIED` (not `NOT_VERIFIED`),
and the live results API now returns all 6 real browser/platform
combinations for the fluidcontrols.com analysis run, each showing genuine
real findings (consistent overlapping-element and undersized-tap-target
issues at both desktop and mobile viewports — real evidence, not a display
bug).

**Important caveat about seeing this fix live:** Report snapshots are
immutable by design (locked invariant, CLAUDE.md #4) — an already-generated
report will NOT retroactively show the fix. Only a newly-generated report
reflects it. The user's already-open `analysis-runs/{id}` page was showing
an older snapshot generated before this fix, which is why the top summary
cards still looked wrong even after the fix landed — not a remaining bug,
expected behavior of the immutability guarantee.

### Finding 2 — NOT YET FIXED: "performance" section embeds a stale, inconsistent duplicate of the Browser UAT matrix

**What's wrong:** `apps/api/app/services/report_delivery.py` builds the
CORRECT, fresh `browser_compatibility.browser_uat.matrix` at the report's
TOP level (variable `browser`, built ~line 800/1021, using
`apply_tier0_evidence`/`_build_browser_uat_matrix` against LIVE current Tier
0 evidence at report-generation time). But the **"performance" section's own
content ALSO embeds a full `browser_compatibility` object** (a DIFFERENT
local variable, literally named `browser_compatibility`, built at ~line 2192
as `browser_artifact.artifact_metadata if browser_artifact else {}`) — this
is a snapshot of an `AgentArtifact.artifact_metadata` blob captured ONCE
during the original 8-agent workflow execution, which ALSO happens to
contain its own `browser_uat` sub-key. Confirmed via a real generated
report: the top-level one correctly showed `PARTIALLY_VERIFIED` for all 3
browsers; the "performance" section's embedded copy simultaneously showed
`NOT_VERIFIED` for all 3 — two contradictory answers to the same question in
the same report.

**Not yet investigated:** whether any renderer (frontend, PDF, HTML)
actually displays this embedded duplicate anywhere a customer would see it
(if genuinely unused/dead, it's a cleanup item, not a customer-facing bug —
audit agent findings pending), and the full blast radius of what else in
that `artifact_metadata` blob might be similarly stale.

**Status:** Flagged, not fixed — first-pass audit into this and 9 other
areas is running now (see §4).

## 4. First-pass audit — in progress (1 of 4 batches landed)

Launched 2026-08-16, real code-based investigation (not guesses), covering
every report section plus cross-cutting production-readiness concerns. Four
parallel batches; results filled in below as each lands.

### Batch: Pages / Action Plan / Evidence & Limitations — DONE

**Pages tab.** Real evidence: `PageAnalysisRun`/`WebsitePage` via the
run-scoped membership table (not the last-writer-wins pointer). Counts
(`eligible_pages`, `successfully_analysed_pages`, `failed_pages`) computed
by real filtering (`report_delivery.py:947-953,1053`). Page selection
(`page_selection.py:24-56`) is deterministic critical-first sampling, no
randomness. Minor: `evidence_coverage` per page is a coarse 100/50/0
heuristic (`report_delivery.py:937-943`), not a real percentage — labeled,
not fabricated. `detected_content_type` is honestly `None` with an
explanatory string (`887-892`), not fabricated.

**Action Plan.** `generate_actions()` only creates an item when real
`evidence` exists; otherwise honestly counted as `insufficient_evidence`/
`unsupported_finding` (`action_generation.py:630,634-635`). Real gaps found:
(1) priority scoring's `estimated_score_impact`/`implementation_effort`/
`business_impact` inputs are **static per-finding-code constants** from
`FINDING_TO_ACTION_MAP`, not measured per-site (`action_generation.py:
881-884`, `priority.py:96-109`) — only severity/affected-page-count/
confidence are real per-instance evidence, and this isn't disclosed to the
customer; (2) Tier 0 action priority is computed with
`affected_page_count=1` hardcoded (`action_generation.py:1191`) even before
the group's real count is reconciled at line 1159 — stored priority may not
match the group's final count; (3) any finding whose `finding_code` isn't in
`FINDING_TO_ACTION_MAP` silently never becomes an action item even though it
appears in the Findings Register (`action_generation.py:627-631`) — a real,
undisclosed Pages↔Action-Plan asymmetry, not a bug but not surfaced either.

**Evidence & Limitations.** `_completion_semantics`
(`report_delivery.py:524-630`) correctly populates the `kind` taxonomy from
real signals. Real gaps: (1) `deduplicate_limitations`'s
`SemanticLimitation` (`canonical_report_metrics.py:61-66`) has NO `kind`
field — two parallel limitation representations exist; if any renderer
consumes the deduped list instead of `limitation_reasons`, the `kind`
taxonomy is silently lost for that surface (which renderer uses which list
is not yet verified); (2) `_assign_limitation_id`'s fallback
`f"other_{hash(message) & 0xFFFF:04x}"` (line 94) uses Python's `hash()` on
strings, which is not stable across runs unless `PYTHONHASHSEED` is fixed —
an unmatched limitation could get a different opaque ID on different report
generations for the SAME analysis; (3) `check_invariants`
(`canonical_report_metrics.py:189-230`) only checks the
score-100-with-unavailable-evidence violation for the `accessibility`
category (`219-221`) — the same silent-completeness risk is NOT checked for
`performance`/`best_practices`/`seo`/`technical_quality`, so a false
"100% and complete" claim in those categories wouldn't be caught.

**Auth/tenant isolation — CONFIRMED, critical for "deployed live":** zero
matches for `current_user`/`get_current_user`/`Depends(oauth`/`require_auth`/
JWT anywhere in `apps/api/app`. All route dependencies are DB-session only
(e.g. `apps/api/app/api/routes/websites.py:16`). No `User`/`tenant_id`/
`owner_id`/`user_id` fields anywhere in `apps/api/app/models/`. This is the
single most consequential finding for a live deployment and should be
treated as its own top-priority module, not folded into a report-content
module.

### Batch: Overview / Executive Summary / Cross-cutting infra — DONE

**Executive Summary.** Genuinely computed, no hardcoding found.
`overall_score`, `strongest_areas`/`weakest_areas`, `serious_findings`,
`agent_summary` all trace to real DB-queried entities (`ScoreExecution`,
`AnalysisFinding`, `AgentRun`, `ActionItem`) with `_evidence(...)` refs
attached (`report_delivery.py:2355-2472`). Degrades honestly to
"unavailable" rather than fabricating when data is missing
(`2358,2580-2584`). Clean.

**Feedback collection — CONFIRMED: does not exist.** No feedback/rating/
thumbs/survey/NPS mechanism anywhere in `apps/api/app/models/`,
`apps/api/app/api/routes/`, or `apps/web`. The only "rating" hit is a
Lighthouse performance-score field (`models/performance.py:48`), unrelated.
The only "feedback" mention in the whole repo is an internal QA-process
planning note (`docs/DEVICE_OS_BROWSER_QA_PLAN.md:1094`), not a
customer-facing feature. This needs to be built from scratch — its own
module.

**Logging/traceability — CONFIRMED: sharp, near-total gap in `apps/api`.**
All 29 files in `apps/api/app/services/` — including `report_delivery.py`,
`workflow_execution.py`, `public_url_safety.py`, `browser_uat_tier0.py`,
`scoring_formula.py` — have **zero** logging calls. Only 4 files in all of
`apps/api` use logging at all, and one of those (`middleware/
request_logging.py`) is just a generic per-HTTP-request line with no
business detail. The locked stage-exclusivity/workflow-execution
correctness guarantee (CLAUDE.md) has NO service-level log trail. Worker
side is uneven: `worker_app/tasks/analysis.py` has 17 calls (mostly
following the `snake_case_event key=%s` convention, but 3 convention-
violating f-string error logs at lines 423/438/529); `real_analysis.py` and
`agent_platform.py` — the MAIN orchestration entry points — have **zero**
logger calls at all.

**Production readiness, beyond auth — CONFIRMED gap: no rate limiting or
request-size limiting anywhere.** `apps/api/app/main.py` registers only
CORS + `RequestLoggingMiddleware` — no rate-limit/throttle/body-size-limit
middleware exists (grep for `RateLimit`/`slowapi`/`throttl` found nothing
relevant). `docs/PRODUCTION_OPERATIONS.md`'s own "Security boundaries"
section lists CORS/SSRF/network-isolation but never mentions rate limiting.
Combined with the zero-auth finding: an anonymous caller can trigger
unlimited real Playwright/Lighthouse analysis runs against arbitrary public
URLs, each expensive, with nothing bounding volume. Secrets handling itself
is reasonable (`SecretStr`, strict CORS validation, no wildcards) — this is
specifically about missing abuse protection, not secret leakage.

### Batch: Findings / Performance / Accessibility — DONE

**Findings (Complete Findings Register).** Mature, no TODOs/stubs found.
Merges 5 independent streams (`AnalysisFinding`, `SiteDiagnosticFinding`,
`AccessibilityFinding`, browser-engine rows, Tier0 structural results) via
the 7-key `_group_detailed_findings` signature. Good traceability — every
payload carries real `evidence_references`. One untested structural risk:
`MERGE_ACROSS_PAGES_FINDING_CODES` is a hand-maintained whitelist; any
finding code that SHOULD merge across pages but isn't in that set instead
splits by per-page observed-value text, silently inflating unique-finding
counts. Not confirmed as currently firing — worth a coverage check.

**Performance section — Finding 2 (the stale duplicate) reassessed, lower
severity than initially thought.** Traced every consumer: the frontend
Performance tab hits a completely separate LIVE endpoint
(`/analysis-runs/{id}/performance`) and never reads the report snapshot at
all; the Technical Appendix PDF correctly reads the root-level
`browser_compatibility` key, not the section's copy. **The stale duplicate
is currently unused by every renderer checked** (PDF, HTML, frontend). It
IS, however, present verbatim in the raw JSON export artifact a customer
can download — a second, contradictory "truth" sitting in a
customer-downloadable file even though nothing currently surfaces it in the
UI. Lower priority than initially assumed, but still a real latent risk
(and a "single source of truth" violation) worth cleaning up.

**Accessibility section.** Good traceability, real evidence sources. One
real gap: `ManualReviewChecklist` rows ARE captured per-item in the DB
during audit ingestion (`accessibility_service.py:129,174-223`), but
`_build_sections` never queries that table — the report only emits a flat
`"manual_review_required": True` boolean with zero actual checklist
content, discarding real captured data the customer never sees.

### Batch: SEO & Content / Security & Technical / Browser UAT — DONE

**Major cross-cutting finding: `AnalysisFinding` is never populated in
production.** Grepping the entire repo, `AnalysisFinding(` is only ever
constructed inside `tests/` — no worker or service module writes to that
table in real runs; `report_delivery.py`/`action_generation.py` only READ
it. This means every section that partially depends on `AnalysisFinding`
(SEO & Content's `content_findings` half, Security & Technical's
analysis-finding half, Action Plan's main per-page loop) silently gets
`[]` from that source in every real analysis, always — not a bug that
sometimes fires, a code path that NEVER fires today. Not fabrication (empty
lists are honest), but a substantial, previously-invisible gap: an entire
intended evidence pipeline (the one implied by the product's own agent
architecture) contributes nothing to real reports.

**Security & Technical — confirmed customer-facing mislabeling.** Because
`AnalysisFinding` is always empty, `security_technical` is populated ONLY by
browser cross-engine compatibility rows. Real, evidence-backed
security-header findings (missing HSTS/CSP/X-Frame-Options — genuinely
computed from `page.security_observations` in
`site_diagnostics_service.py:2320-2350`) get classified under
`rule_id="repeated_issue_pattern"` → `category=REPEATED_PATTERN` →
routed instead into "Repeated and Template Problems", never into "Security
& Technical". **A tab literally titled "Security and Technical Findings" can
show zero security findings even when real ones exist elsewhere in the same
report.** `"zero_findings_means_clean": False` correctly avoids a false
"clean" claim, but a customer reading only that tab misses real findings.

**SEO & Content.** `internal_link_graph`/`canonical_indexability` are
genuinely evidence-backed and traceable (site_diagnostics-sourced), no
issues found. `content_seo`'s `AnalysisFinding`-sourced half is always empty
per the finding above — the section is entirely carried by the
diagnostics-sourced half in real reports.

**Browser UAT & Responsive — 2 more hardcoded fields found**, beyond the
already-documented `interaction_failures`/`accessibility_differences`
(`browser_compatibility.py:901-902`, confirmed still hardcoded empty): (1)
same lines — reconfirmed unchanged; (2) NEW —
`"screenshot_artifact_reference": None` (line 904) is always `None`; no
screenshot is ever actually captured/stored despite the field existing in
every payload. Rest of the Tier0/`BRANDED_BROWSER_SCOPE` merge logic is
honest (real states only promoted from real evidence). iPad Simulator gap
already documented, not re-flagged.

## Audit summary — all 4 batches complete, 2026-08-16

Full findings list, roughly by severity:

1. **Zero auth/tenant isolation** anywhere in the API — critical for "live."
2. **`AnalysisFinding` never populated in production** — an entire intended
   evidence pipeline silently contributes nothing to real reports.
3. **"Security & Technical" tab structurally misses real security findings**
   (misclassified into a different section) — direct customer-facing
   mislabeling on a section customers would specifically check for security
   issues.
4. **No feedback collection mechanism exists at all.**
5. **Near-total logging/traceability gap** in `apps/api/app/services/` (29
   files, zero logging) — the locked stage-exclusivity correctness guarantee
   has no service-level log trail; worker's main orchestration entry points
   (`real_analysis.py`, `agent_platform.py`) also have zero logger calls.
6. **No rate limiting or request-size limiting** — combined with #1, an
   anonymous caller can trigger unlimited expensive real analysis runs.
7. Accessibility's real per-item manual-review checklist data is captured in
   the DB but never surfaced in the report (flat boolean instead).
8. Action Plan priority scoring uses static per-finding-code constants for
   2 of 3 inputs, undisclosed to the customer; Tier0 action priority
   computed with a hardcoded `affected_page_count=1` before reconciliation.
9. Findings whose codes aren't in `FINDING_TO_ACTION_MAP` never become
   action items even though they appear in the Findings Register.
10. `check_invariants`' false-100%-complete guard only covers the
    accessibility category, not performance/SEO/best-practices/technical.
11. Two more hardcoded-empty Browser UAT fields
    (`interaction_failures`/`accessibility_differences`/
    `screenshot_artifact_reference`) beyond what was already known.
12. Performance section's stale duplicate `browser_compatibility` blob
    (Finding 2, §3) — unused by current renderers, but present in the
    downloadable raw JSON; a latent single-source-of-truth violation.
13. `_assign_limitation_id`'s fallback uses Python's non-guaranteed-stable
    `hash()` — an unmatched limitation could get a different opaque ID
    across report generations for the same analysis.
14. `SemanticLimitation`'s deduped list has no `kind` field, separate from
    `_completion_semantics`' `limitation_reasons` — a renderer consuming the
    wrong list would silently lose the required/optional/etc. taxonomy
    (which renderer uses which list not yet independently verified).
15. `_group_detailed_findings`' cross-page merge whitelist
    (`MERGE_ACROSS_PAGES_FINDING_CODES`) is hand-maintained; any code that
    should merge but isn't listed could inflate unique-finding counts
    (not confirmed as currently firing).

## 4.5 Cross-check against a pre-existing planning document (2026-08-16)

The user had a prior planning document
(`ZuiGO_WebIQ_Phase6_Sitewide_Intelligence_Overhaul_Autonomous_Claude.md`,
authored ~5 days before this initiative started, targeting a sweeping
"autonomous mode" rewrite) plus 12 PDF screenshots of every report tab
against a real `fluidcontrols.com` run from that time. The user was
explicit this document is NOT a command to implement as-written — it may
be partially outdated by since-then work, and needed cross-checking against
real current code/data before trusting any of it. Verified findings below,
not assumptions.

**Confirmed FIXED since that document was written** (verified against a
real report generated 2026-08-16, not assumed):
- The document's headline claim — "Findings tab shows 6, embedded report
  shows 220 unique findings, same analysis run" — does NOT reproduce today.
  Checked `total_unique_findings` (223), `page_level_findings.finding_count`
  (223), and `executive_summary.verified_finding_count` (223): all
  reconcile. `top_finding_count: 5` is correctly labeled as a subset, not
  falsely presented as complete.
- "Action Plan capped at 5, hiding a bigger complete register" — the same
  report genuinely generated only 4 real action items, internally
  consistent (`action_count` matches the actual `actions` array length) —
  not evidence of an artificial cap.
- "Chrome/Edge/Safari permanently show Not verified, recommend BrowserStack
  integration" — superseded by this same day's work: real GitHub-Actions +
  real-device branded-browser evidence (built and live-verified earlier in
  this session) already achieves genuine VERIFIED/PARTIALLY_VERIFIED
  states for free. **Do not pursue BrowserStack** — it would duplicate
  working infrastructure.

**Confirmed STILL REAL, independently corroborated:**
- Accessibility's "Manual review required: 10" / "expanded: 0 items" split
  — checked today's real report directly: `incomplete_count: 10` exists as
  a bare number with no corresponding list of those 10 items anywhere in
  the payload. This independently confirms Finding 7 above (M6) via a
  completely different method (product observation 5 days ago vs. direct
  JSON inspection today) — strong signal this is real, not stale.
- Security & Technical showing vague, not-genuinely-informative labels
  instead of real findings — matches Finding 3 above (M3) closely.

**Not yet verified — real, open questions, not yet checked against current
code, added as audit candidates below rather than assumed true or false:**
- Site-wide vs. homepage-only evidence per domain (SEO/content, links,
  downloads, performance) — the document's biggest architectural claim.
  **The user separately confirmed this as a standing requirement regardless
  of the document's fate — see constraint #8 in §6.**
- The Performance tab's raw internal keys (`LAB_FCP` etc.) and epoch
  timestamps (`1786697643944`) — the report SNAPSHOT contains no lab-metric
  data at all (checked, confirmed absent), consistent with an earlier
  finding that the frontend Performance tab hits a separate LIVE endpoint,
  not the snapshot — that live endpoint's actual output is unverified.
- Pages tab: dead "View finding detail" buttons, raw UUIDs as primary
  labels, unreadable long-decimal percentages.
- HTML/W3C Nu Checker integration, CrUX API integration — likely genuinely
  absent, not yet confirmed.
- General UI responsiveness/overflow at narrow widths, a contextual-help
  glossary system — frontend concerns, not yet checked.

**Deliberately NOT carried over:** the document's own "autonomous mode, do
not stop, work through all 40+ items as one mega-task" operating style —
this initiative continues the discussed-module-by-module process the user
has used throughout instead.

## 5. Module plan

Proposed modules, grouped by priority tier. **Nothing here is approved for
implementation yet** — per the user's explicit process, each module is
discussed and approved individually before work starts, same discipline as
`docs/DEVICE_OS_BROWSER_QA_PLAN.md`. Order within a tier is not yet
prioritized against each other; that's part of the discussion.

### Tier 1 — production-deployment blockers (independent of report content)

- **M1: Authentication & tenant isolation.** Currently zero. Scope
  decision needed: how much is actually required for this deployment
  (single-operator tool vs. multi-tenant SaaS?) before designing anything.
- **M2: Abuse protection.** Rate limiting + request-size limiting on the
  public analyze-website endpoint. Directly compounds with M1 — an
  anonymous, unlimited caller can trigger real expensive analysis runs.

### Tier 2 — customer-facing correctness (the report says something wrong or misleading)

- **M15: Site-wide vs. homepage-only evidence audit — SHIPPED 2026-08-17,
  see full writeup below.**
- **M3: Security & Technical section mislabeling.** Real security-header
  findings are misclassified away from the section titled "Security and
  Technical Findings." Smallest, most surgical fix in this tier — likely a
  rule-classification correction, not a redesign.
- **M4: `AnalysisFinding` pipeline is dead in production.** Bigger
  question: was this table meant to be actively written by a specific
  agent that was never wired up, or is it now redundant now that
  `SiteDiagnosticFinding`/`AccessibilityFinding` cover real findings some
  other way? Needs understanding intent before deciding whether to wire it
  up or formally retire it — a decide-first, then-implement module.
- **M5: Performance section's stale duplicate `browser_compatibility`.**
  Confirmed unused by current renderers but present in the downloadable
  JSON — cleanup, not urgent, but a real single-source-of-truth violation.

### Tier 3 — real data being captured but not surfaced (completeness gaps)

- **M6: Accessibility manual-review checklist.** Real per-item data exists
  in the DB, never reaches the report.
- **M7: Action Plan priority-scoring transparency.** Static per-finding-code
  constants driving 2 of 3 priority inputs, undisclosed to the customer;
  plus the Tier0 hardcoded `affected_page_count=1` timing bug.
- **M8: Findings without a matching action code.** Decide: extend
  `FINDING_TO_ACTION_MAP` coverage, or explicitly disclose the gap.
- **M9: `check_invariants` false-100%-complete guard.** Extend beyond
  accessibility to all score categories.
- **M10: Two more hardcoded-empty Browser UAT fields**
  (`interaction_failures`/`accessibility_differences` — already known;
  `screenshot_artifact_reference` — newly found). Decide: implement real
  detection, or formally document as a known limitation like the iPad gap.
- **M16: Performance live-endpoint raw-label/epoch-timestamp audit.** From
  the historical-doc cross-check (§4.5) — the report snapshot has no lab
  metrics, so this data comes from a separate live endpoint
  (`/analysis-runs/{id}/performance`) not yet audited. Confirm whether raw
  internal keys (`LAB_FCP` etc.) and epoch timestamps still reach the
  customer, and whether Field/Lab/Timing data is duplicated across tabs.
- **M17: Pages tab UI functionality audit.** From §4.5 — confirm whether
  "View finding detail" buttons are genuinely non-functional and whether
  raw UUIDs/unreadable long-decimal percentages still appear as primary
  labels. Frontend-facing; likely needs an Antigravity handoff once
  confirmed real.

### Tier 4 — infrastructure (enables correctness/traceability everywhere else)

- **M11: Logging & traceability.** Near-total gap in `apps/api/app/services/`
  — the locked stage-exclusivity guarantee has no log trail. Foundational
  for the "everything logged and traceable" requirement; likely worth doing
  early since it makes every other module's future debugging easier.
- **M12: Feedback collection.** Does not exist. New feature, needs its own
  design discussion (what feedback, on what — a report? a finding? an
  action item? general NPS?).
- **M13: Limitation-ID stability & dual-representation cleanup.** The
  `hash()`-based fallback ID and the two parallel limitation
  representations (`SemanticLimitation` vs. `limitation_reasons`).
- **M14: `MERGE_ACROSS_PAGES_FINDING_CODES` coverage audit.** Confirm
  whether any real finding code is currently mis-splitting across pages.
- **M18: HTML/W3C Nu Checker integration.** From the historical doc — likely
  genuinely absent today (not yet confirmed), a real new capability rather
  than a fix. Doc's own correction worth keeping regardless of the rest:
  there is no official universal W3C numeric score; any implementation
  must expose real validator results (errors/warnings/line/column) and
  keep a clearly-separate `ZuiGO HTML Quality Score` labeled as such, never
  as "official W3C scoring."
- **M19: CrUX API integration.** From the historical doc — likely genuinely
  absent today (not yet confirmed). Needs a Google Cloud API key
  (external dependency) if pursued; URL-level vs. origin-level-fallback
  semantics need explicit, truthful labeling per Google's own current
  documentation, never substituting Lighthouse lab data into a field-data
  surface.

Each module, once discussed, gets a decision-log entry below (mirroring the
QA initiative's format) before implementation starts.

### M1 — SHIPPED 2026-08-16

**Scope decided first, before any code:** current usage is internal-only
(just the user/team, no external customers yet). Given that, chose a
minimal shared-credential gate now over building the full multi-tenant
accounts/RBAC system the product spec describes as a later phase — stops
the immediate abuse risk fast without over-building for a scale this
product isn't at yet.

**What shipped:** one admin username/password (bcrypt-hashed, no plaintext
ever stored), `POST /api/v1/auth/login` issuing a signed JWT
(`apps/api/app/services/auth.py`), and `require_bearer_auth` applied ONCE
at the router level (`apps/api/app/api/router.py`) to every `/api/v1/*`
route except login itself — so a newly added route can never accidentally
ship unprotected. `/health` stays open. No new DB table (stateless
verification, matching the "keep it simple" scope decision) — this
generalizes cleanly to a real user table later without discarding the JWT
mechanism.

**Real security detail that shaped the design:** the frontend calls the API
directly from the browser (no server-side proxy — confirmed by reading
`apps/web/src/lib/api.ts`), and Next.js `NEXT_PUBLIC_*` env vars are baked
into the public JS bundle. A static shared secret embedded that way would
be visible to anyone via devtools — not real protection. This is why the
design is a real login (password verified server-side, short-lived signed
token issued per session) rather than a baked-in client constant.

**Test-suite blast radius handled centrally:** ~20 existing test files
already build their own `TestClient`/`dependency_overrides[get_db]`
fixtures; rather than editing all of them, a new `tests/conftest.py`
autouse fixture bypasses auth by default for every test (mirroring how a
real caller would carry a valid token), and `tests/api/test_auth.py`'s 17
tests explicitly undo that bypass to exercise the real mechanism end to
end (login success/failure, protected-route rejection for missing/invalid/
expired tokens, health and login staying unprotected).

**Live-verified against the real docker stack**, not just unit tests: real
login with the real admin credential returns a working token; an
unauthenticated request to a real protected route returns real `401
AUTHENTICATION_REQUIRED`; the same request with the token succeeds; a wrong
password returns real `401 INVALID_CREDENTIALS`.

**Known, expected, immediate consequence:** the `apps/web` frontend had no
login screen yet, so every existing page got 401s and silently showed
empty/no-data states (confirmed live: the homepage's "Recent analyses" list
read "No analysis has been submitted yet" despite real analyses existing).
A handoff spec was sent to Antigravity the same day.

**Frontend login screen — Antigravity built it, verified here through 2 real
bug-fix rounds, not just trusted from green checks:**
- `apps/web/src/lib/auth.ts` (token storage + `login()`),
  `apps/web/src/lib/api.ts` (attaches `Authorization` header, redirects to
  `/login` on 401), `apps/web/src/components/auth/AuthGuard.tsx` (route
  gate), `apps/web/src/app/login/page.tsx`.
- **Round 1 bug found via live testing** (not caught by lint/typecheck/
  build/pytest, which all passed): `AuthGuard` called `router.replace()`
  synchronously in the render body instead of inside a `useEffect` — a
  React anti-pattern that broke the login form's submit handler entirely
  (confirmed: zero `POST /api/v1/auth/login` requests ever fired when
  clicking Sign in) and caused a `ReferenceError: location is not defined`
  during `npm run build`'s static-page generation. Root-caused via the
  browser console's own React warning, fixed by moving the redirect into
  `useEffect`.
- **Round 2 bug found via live testing**, again invisible to automated
  checks: the round-1 fix used `useSyncExternalStore` with a
  `getServerSnapshot` returning `null` (correct for avoiding a hydration
  mismatch), but the `useEffect` fired its redirect decision from that
  transient null-token render — before React re-synced to the real
  client-side token — meaning a genuinely logged-in user got bounced back
  to `/login` on every hard page reload. Reproduced directly: real token
  confirmed present in `localStorage` via `javascript_tool`, yet
  `window.location.pathname` was `/login` after a fresh navigation. Fixed
  by replacing `useSyncExternalStore` entirely with an explicit
  `useState`-based "checked" flag that only decides to redirect after
  genuinely reading the token client-side in an effect.
- **Real, unrelated build-tooling bug found and fixed along the way**: the
  root-level `package.json`/`package-lock.json` (added earlier this session
  for the unrelated Android Lane C CLI, see the QA initiative doc) made
  Turbopack infer the wrong monorepo workspace root, breaking
  `apps/web`'s own dependency resolution (`Can't resolve 'tailwindcss'`).
  Fixed with an explicit `turbopack.root` in `apps/web/next.config.ts`.
- **Real `.env`/Docker Compose gotcha hit and fixed during manual
  credential rotation**: `ADMIN_PASSWORD_HASH` must be a bcrypt HASH, not
  the plaintext password (user initially set it to the plaintext value by
  mistake). Separately, bcrypt hashes contain literal `$` characters, which
  Docker Compose's `.env` parser can misinterpret as variable references
  if a `$` happens to be followed by letters (e.g. `$LjfI...` looked like a
  reference to a variable named `LjfI`, silently corrupting the value,
  confirmed via real "variable is not set" warnings on `docker compose up`)
  — fixed by escaping every literal `$` as `$$`. Worth remembering for any
  future secret rotation, not just this one incident.
- **Final live verification, all real, not assumed**: login with real
  rotated credentials → real `200`; hard reload while authenticated → stays
  on the real page with real data (the exact scenario that was broken);
  logged-out access → redirects to `/login`; a fresh real
  `POST /api/v1/auth/login` confirmed in the network log, not leftover
  browser state.

**Tests:** 17 new (`test_auth.py`) + 3 existing `test_config.py` tests
updated for the 3 new required settings + 5 new
(`test_frontend_auth_contract.py`, Antigravity-authored, verified against
the real frontend code). Full suite: 1127 passed, 1 skipped. `ruff check`/
`ruff format --check` both clean. Frontend: lint 0 errors, typecheck clean,
production build clean (the `ReferenceError` confirmed gone).

**Explicitly deferred, not part of this module:** full multi-tenant
accounts, organizations, RBAC, password reset/registration flows — all
remain future work once real external customers are onboarded.

### M15 — SHIPPED 2026-08-17

**The real, most severe finding of the whole audit.** Lighthouse
(Performance) and axe-core (Accessibility) only ever ran against the
homepage — one page — for every real analysis, regardless of site size.
This wasn't an occasional bug: `AnalysisResult.analysis_run_id` has a
database-level unique constraint, meaning the schema itself only allowed
one Lighthouse/Playwright result per analysis run. A "Level 2" deep-analysis
tier existed in the worker code specifically to extend Lighthouse to more
pages, but both real production call sites
(`report_delivery.py`/`analysis_comparison.py`) hardcoded
`max_lighthouse_pages: 0`, confirmed by an existing test that literally
asserted this — Level 2 never ran on any page, ever, in the real flow. Worse:
the "page coverage" numbers the report actually showed (e.g. "150/174 pages
analyzed," "100% — all required evidence complete") were computed from the
cheap Level-1 crawl only, not from Lighthouse/axe-core depth — so a report
could genuinely claim full completeness while Performance/Accessibility
evidence came from exactly 1 page, with no disclosure anywhere.

**Investigated before writing any code, not assumed:** traced the real
mechanism precisely — `AccessibilityAudit` and `PerformanceSnapshot` both
turned out to be already multi-page-capable by design (their REAL unique
constraints are `(execution_id, website_id, url, ...)`, not
`analysis_run_id` alone — confirmed by reading the models directly). This
meant **no schema migration was needed at all**; the tables were built for
this and simply never got more than one page's worth of data written.

**Real architectural subtlety found and handled correctly:** the Level-2
page-analysis phase runs BEFORE the main report-generating `AnalysisRun`
exists (it's a genuinely earlier, independent pipeline stage) — so it can't
tag evidence with `analysis_run_id` the way the homepage flow does. Instead,
it uses `execution_id` (the page-analysis execution's own id, which it does
have), and `report_delivery.py` was extended to look up evidence by EITHER
`analysis_run_id == run.id` (the homepage's own evidence) OR
`execution_id == page_execution_id` (the Level-2 pages' evidence) — both
genuinely this run's real evidence, just written by two different pipeline
stages.

**What shipped:**
1. Un-hardcoded `max_lighthouse_pages` at both real call sites, replacing
   `0` with a new shared constant `DEFAULT_MAX_LIGHTHOUSE_PAGES = 10`
   (`app/services/page_selection.py`) — restoring the code's own
   already-calibrated default that had been silently disabled.
2. Wired real evidence collection (`process_axe_results`,
   `process_lighthouse_accessibility`, `collect_lighthouse_evidence`) into
   the Level-2 loop (`worker_app/tasks/page_analysis.py`), each
   independently guarded so one evidence type failing never blocks the
   others or the page's own findings/score.
3. `report_delivery.py`'s accessibility section now merges homepage +
   Level-2 pages' real `AccessibilityAudit` rows.
4. `report_delivery.py`'s findings pipeline now merges homepage +
   Level-2 pages' real `AnalysisFinding` rows (reusing the existing,
   already-correct URL-keyed `_analysis_finding_payload` adapter directly —
   no new adapter needed) — these flow into both the Performance section
   and the Complete Findings Register.
5. **Honest, separate disclosure**: new `deep_evidence_pages_analysed` /
   `deep_evidence_coverage_percentage` / `deep_evidence_scope` fields in
   `page_coverage`, and a new `DEEP_EVIDENCE_COVERAGE_LIMITED` limitation
   reason — classified `optional_infrastructure` (same treatment as Branded
   Browser UAT's own carve-out), a deliberate design decision: this is a
   cost-bounded sampling decision, not a quality defect, so it's fully
   visible for transparency but does NOT collapse the single blended
   `report_confidence` score — including it in that blend would make nearly
   every real report's confidence collapse to ~6% (10/174) regardless of
   actual quality, which would be a disproportionate, confusing regression
   in service of "honesty" that doesn't actually serve the customer.
6. `select_level2_pages`'s existing priority ordering (homepage,
   navigation, contact, about, product, service first) means the bounded
   sample is the most valuable pages, not arbitrary ones — matches the
   product's own "genuinely sampled... must be explicit... which pages and
   why" standard from the historical planning doc reviewed in §4.5.

**Tests:** one comprehensive, real-DB-backed integration test
(`test_deep_evidence_covers_l2_pages_not_just_the_homepage`,
`tests/api/test_report_delivery.py`) seeding a realistic 10-eligible-page
site with 3 Level-2 pages (synthetic per-page `AnalysisRun` +
`AnalysisResult` + `AnalysisFinding`, plus real `AccessibilityAudit` rows),
proving: real 3/10 (30%) deep-evidence coverage is computed and disclosed
correctly; the limitation reason is present with the correct
`optional_infrastructure` classification; `deep_evidence_coverage_percent`
is visible in `confidence_components` but does NOT drag down overall
`confidence_percent`; accessibility audit/violation counts reflect all 3
L2 pages, not just one; real per-page performance findings from all 3 L2
pages reach the Complete Findings Register. Full suite: 1128 passed, 1
skipped. `ruff check`/`ruff format --check` both clean.

**Live-verified against the real docker stack** (images rebuilt first):
regenerated a report for the real `fluidcontrols.com` analysis run that
predates this fix — confirmed no crash, and confirmed HONEST zero-state
behavior (`deep_evidence_pages_analysed: 0`, `0.0%`, the limitation reason
correctly present) rather than fabricating data for old runs that never had
real Level-2 evidence — exactly the "no fabricated evidence" discipline
this whole initiative is about.

**Fully live-verified 2026-08-17** (user: "go ahead with live run"): a
brand-new real analysis run against `fluidcontrols.com`
(execution `9a32683e-d516-4f79-ac5a-94585d612b7b`, run
`927405cb-1f0a-4ead-8044-1c3b079e01a1`) ran the real Level-2 loop end-to-end
and generated a fresh report (`d553f218-bc24-4319-b11f-11e6d7e53dba`).
Confirmed directly from the generated payload, not assumed:
- `deep_evidence_pages_analysed: 10`, `deep_evidence_coverage_percentage:
  5.7` (10/174) — present in `confidence_components` but top-level
  `confidence_percent` stayed at 50, not collapsed toward ~6%, proving the
  `optional_infrastructure` exclusion works live, not just in the test.
- Accessibility `audit_count` was 22 (vs. 1 before this fix, homepage-only).
- Performance and Accessibility findings both carry real per-page
  `affected_pages[].final_url` values spanning **10 distinct real URLs**
  (homepage + 9 product/category pages), not just the homepage — the actual
  defect M15 set out to fix, confirmed with real evidence from real
  Lighthouse/axe-core runs, not by construction.

**Real infrastructure bug this run surfaced (unrelated to M15's own code,
fixed separately)**: the first attempt at this live run failed immediately
at the `setup` stage (0% progress, all 8 agents still `queued`, stale after
900s). Root cause: M1's auth commit (`2d1aead`) added
`ADMIN_USERNAME`/`ADMIN_PASSWORD_HASH`/`JWT_SECRET_KEY` as *required*
`Settings` fields, but only the `api` service's `docker-compose.yml` block
was updated with them — the `worker` service, which imports the same shared
`app.config.Settings`, was never given these vars. Every worker container
had been crash-looping on startup (`pydantic.ValidationError`) since that
commit, silently failing every Celery task with no report-facing error,
until this live run's setup stage went stale waiting for a worker that could
never boot. Fixed in `docker-compose.yml` (commit `7f905bb`, committed
separately from M15's still-uncommitted changes) by adding the three vars to
the worker's `environment:` block, matching the `api` service's pattern.
After `docker compose up -d worker` recreated the container, it booted
clean and picked the originally-queued Celery messages back up on its own —
no manual resume needed.

**Explicitly out of scope for this module** (from the original §4.5
cross-check, still genuinely unverified): SEO/Content and Security/
Technical were already independently confirmed genuinely site-wide by
earlier audit work (no fix needed there) — Performance/Accessibility were
the real, severe gap. The Performance live endpoint's raw-label/epoch-
timestamp formatting (M16) and the Pages tab's dead-button/raw-UUID claims
(M17) remain separate, unverified, un-fixed items.

## 6. Non-negotiable constraints for this initiative

Inherited from `CLAUDE.md`, restated here for portability:

1. Exactly 8 runtime agents — never add a 9th.
2. Scoring formulas locked (`FORMULA_VERSION == "1.0.0"`,
   `PRIORITY_FORMULA_VERSION == "1.0.0"`, fixed category weights).
3. SSRF protections (`public_url_safety.py`) — never weaken.
4. Immutable historical snapshots — never mutate or migrate old
   `ReportSnapshot` payloads. This is WHY Finding 1's fix doesn't
   retroactively update already-generated reports (see above) — expected,
   not a gap to "fix" by breaking the invariant.
5. Browser UAT truth contract — see `docs/DEVICE_OS_BROWSER_QA_PLAN.md`.
6. Comparison direction (baseline → current) via the chronology guard.
7. **No fabricated evidence, ever** — unavailable evidence is typed
   unavailable/not-comparable, never passed/resolved/improved. This is the
   central discipline for this entire initiative given the "deployed live"
   context — every number, badge, and claim in the report must be traceable
   to a real evidence source, or explicitly marked unavailable.
8. **Every analysis must be site-wide, never homepage-limited** (user's
   explicit instruction, 2026-08-16). For every domain where the product
   claims "website analysis" (performance, accessibility, SEO/content,
   links, security/technical, findings, action plan), the default behavior
   must use ALL successfully analysed eligible pages, not just the
   homepage. Homepage-only evidence may exist as a page-level DETAIL, but
   must never be presented as if it were site-wide evidence. If a domain
   is genuinely sampled for cost/runtime reasons, that sampling must be
   explicit (policy, sampled pages, why those pages) — never silent. This
   applies to every module below and to any new module added later; treat
   it as a standing review criterion, not a one-time module.

## 7. Decision log

- **2026-08-16 — Initiative started:** user reported the Browser UAT tab
  looked broken (screenshot), which led to finding and fixing the
  evidence-merge bug (Finding 1). While verifying the fix, found a second,
  unrelated bug (Finding 2, not yet fixed). User then expanded scope to a
  full audit of the entire report system, explicitly requesting a
  module-by-module plan discussed before implementation, DB-backed
  logging/traceability everywhere, feedback collection, and this document's
  own continuous, portable maintenance so ownership can transfer to a
  different LLM/session later.
- **2026-08-16 — M12 (feedback collection) explicitly deferred:** discussed
  scope (per-finding vs. per-action vs. whole-report vs. general feedback);
  user chose to defer the decision, explicit instruction not to add it to
  the implementation queue yet. Stays listed as M12 for future discussion.
- **2026-08-16 — Historical planning document cross-checked, not adopted
  as-is:** user supplied a pre-existing planning doc (authored ~5 days
  before this initiative, targeting a sweeping "autonomous mode" rewrite)
  plus 12 PDF screenshots, explicit that it was reference material to
  cross-check, not a command. Verified its headline claim (6 vs. 220
  findings) against a real report generated today and found it already
  fixed; found its Browser UAT complaint already superseded by this
  session's own real-branded-browser work; found its accessibility
  manual-review complaint independently corroborated and still real (now
  merged into M6's description). Added 4 new module candidates (M15-M19)
  for genuinely open, not-yet-verified claims. Full reasoning in §4.5.
  Declined to adopt the document's own sweeping, uninterrupted "autonomous"
  working style — continuing the discussed-module-by-module process
  instead.
- **2026-08-16 — Site-wide-not-homepage-only elevated to a standing
  constraint:** user explicit instruction: every analysis must be
  site-wide, never homepage-limited, applying to every module, not just
  M15. Added as constraint #8 in §6, and M15 flagged as the top-priority
  item in Tier 2 to verify this holds across every domain.
- **2026-08-16 — User granted broad authority to change anything needed**
  to fix real problems, explicitly including locked architecture (agent
  count, scoring formula, schema) — with an important, self-imposed
  boundary: this authority is for design/architecture changes, not for
  safety/trust boundaries (SSRF protections, "no fabricated evidence"
  itself), which stay non-negotiable regardless. Used immediately for M15's
  real fix.
- **2026-08-17 — M15 shipped, no schema migration needed:** investigated
  before implementing and found `AccessibilityAudit`/`PerformanceSnapshot`
  were ALREADY designed to be multi-page-capable (real unique constraints
  include the page URL, not just `analysis_run_id`) — so the fix was
  wiring + query changes, not a database migration. Chose to classify the
  new deep-evidence-coverage limitation as `optional_infrastructure`
  (excluded from the blended `report_confidence` score) rather than
  `required` (included) — a deliberate design decision: including it would
  collapse nearly every real report's confidence to ~6% regardless of
  actual quality, which serves neither honesty nor the customer. Full
  reasoning and real live-verification results in M15's own writeup above.
  Decided NOT to spend the ~1 hour needed for a full new real analysis run
  to prove Level-2's real Lighthouse/axe-core execution end-to-end within
  this same session turn — flagged as the next concrete step, pending the
  user's explicit go-ahead on that time cost.

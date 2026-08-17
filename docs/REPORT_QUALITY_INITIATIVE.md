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

Each module, once discussed, gets a decision-log entry below (mirroring the
QA initiative's format) before implementation starts.

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

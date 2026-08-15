# Device / OS / Browser QA Testing — Initiative Plan

**Status: M1–M8 shipped (2026-08-14), plus M2 Lane B (desktop Safari), Lane C
(Android, manually-triggered via ChromeDriver-over-adb), the iOS/iPadOS
Simulator Safari lane (Appium, fully automated), artifact-fetch wiring
(GitHubActionsTier0DispatchClient now really downloads/parses/ingests a
completed run's results into the M4 tables, not a stub), and M3's 5th check
(`responsive_navigation_adapts`, cross-viewport nav-collapse detection), all
shipped 2026-08-15 — every `BRANDED_BROWSER_SCOPE` browser now has a Tier 0
lane covering ALL of its required platforms, a completed CI run's evidence
actually flows end-to-end into the report, and every M3 responsive check
named in `PRODUCT_MASTER_SPEC.md` is now implemented. A real GitHub PAT was
configured 2026-08-15/16 and used to run 5 live dispatches against
`fluidcontrols.com`, confirming Lane A/B and iPhone Simulator Safari all
work end-to-end for real (found and fixed 2 unrelated real bugs along the
way). iPad Simulator Safari is marked a known, pending limitation after 4
consecutive real failures and 3 targeted fixes that didn't resolve it — see
its own entry under the iOS lane section. Lane C's two manual steps
(check + report) were combined into one CLI command 2026-08-16
(`scripts/run_manual_tier0_android_check.py`) — the frontend "one-click"
piece is deliberately deferred pending an `apps/web` handoff. See §7
decision log for what's still open: Lane C's own real-device run (Android
hardware still needed), and eventually revisiting the iPad Simulator gap.**
This document is the
single source of truth for this initiative and is written to be portable —
any competent engineer or any LLM (not just Claude) should be able to resume
work from this file alone, combined with the existing repo docs it references.
Update this file every time a module below moves from planning to a decision
to implementation. Do not let decisions live only in chat history.

## 1. Why this document exists

The user wants ZuiGO WebIQ's own frontend (and the analyzed customer websites,
which the product already partially tests — see §3) verified across real
devices, operating systems, and browsers: Android and iOS (latest 2 major
versions), laptop, desktop, tablet, iPad. Test cases should be designed first
by an expert-level QA process, then executed via appropriate
simulators/emulators or real-device services, with results stored durably,
logged, and traceable, and fed back to the dev team as actionable reports.

This is being planned module-by-module with the user before any code is
written. Read this file top to bottom before proposing implementation for any
module.

## 2. Required reading before touching this initiative

In this order:
1. `CLAUDE.md` (repo root) — execution identity, locked invariants, working
   conventions for this codebase.
2. `docs/PRODUCT_MASTER_SPEC.md` §"BROWSER AND RESPONSIVE COMPATIBILITY" and
   §9 "RESPONSIVE AND CROSS-BROWSER ANALYSIS" and §10 "COMPATIBILITY COVERAGE"
   — the product's own stated requirements for this exact capability.
2. `apps/api/app/services/browser_compatibility.py` — the EXISTING locked
   Browser UAT contract. Read this fully before designing anything; do not
   duplicate or bypass it.
3. `docs/MULTI_AGENT_ARCHITECTURE.md` — the 8-agent/15-tool/3-workflow
   registry this initiative must fit inside without adding a 9th agent.
4. `docs/PRODUCTION_OPERATIONS.md` — deployment, concurrency, and operational
   conventions this initiative's execution engine must respect.

## 3. Current state — what already exists (do not rebuild)

Verified against the codebase, not assumed:

- **Viewport-level responsive testing already runs today**, inside the normal
  analysis pipeline, via Playwright: `apps/worker/worker_app/analysis/playwright_audit.py`
  iterates `responsive_viewports` (5 baseline viewports — mobile portrait/
  landscape, tablet, laptop, desktop — configured in
  `apps/worker/worker_app/config.py:88` via `RESPONSIVE_VIEWPORTS`). This is
  viewport emulation inside one browser engine, not a real device.
- **Three browser ENGINES already run**: chromium, firefox, webkit (Playwright
  engines) — see `worker/Dockerfile` (`playwright install --with-deps chromium
  firefox webkit`). Firefox cannot currently launch inside the worker
  container (`CanCreateUserNamespace EPERM` — environmental, documented in
  CLAUDE.md).
- **The critical distinction is already built and locked**: engine execution
  (chromium/firefox/webkit) is explicitly NOT branded-browser proof.
  `browser_compatibility.py` defines `BRANDED_BROWSER_SCOPE` (Google Chrome,
  Microsoft Edge, Apple Safari — latest-2-stable, specific OS/version scope)
  and five machine-readable verification states: `VERIFIED`,
  `PARTIALLY_VERIFIED`, `NOT_VERIFIED`, `UNAVAILABLE_IN_CURRENT_ENVIRONMENT`,
  `NOT_TESTED`. **Today every branded-browser result is `NOT_TESTED` or
  `UNAVAILABLE_IN_CURRENT_ENVIRONMENT` — nothing in the system has ever
  produced a real `VERIFIED` result.** This initiative's entire job is to
  responsibly fill that gap without weakening the honesty of the contract.
- **No frontend E2E browser test suite exists.** The 63 files under
  `apps/web/src` are validated only by Python tests
  (`tests/test_frontend_*_contract.py`) that read the `.tsx` source as text
  and assert strings/patterns are present. Nothing has ever actually rendered
  the ZuiGO WebIQ UI itself in a browser and asserted on real DOM/visual
  behavior. If part of this initiative's scope is testing ZuiGO's OWN
  frontend (not just customer websites it analyzes), this is the real
  starting gap.

## 4. Non-negotiable constraints for this initiative

Carried over from `CLAUDE.md` and confirmed applicable here:

- **Exactly 8 runtime agents.** No ninth agent. New capability is either a new
  tool consumed by an existing agent (`site_diagnostics_agent` or
  `accessibility_agent` are the natural fits) or entirely separate tooling
  outside the agent registry (e.g., a CI job), not a new agent.
- **Never claim support for an untested browser/device/OS.** Every result
  must map to one of the five existing `UAT_VERIFICATION_STATES`. Do not
  invent new states without updating the locked contract deliberately and
  documenting why.
- **Chromium is never Chrome or Edge proof; WebKit is never Safari proof.**
  Emulator/simulator results are also not automatically equivalent to real
  hardware — this must be decided explicitly per module (see M1) and the
  verification state must reflect the actual evidence tier, not the intent.
- **No fabricated evidence, ever.** Same rule that governs the rest of the
  product's scoring/findings applies here.
- **Formulas unchanged.** `FORMULA_VERSION 1.0.0` and `PRIORITY_FORMULA_VERSION
  1.0.0` are not touched by this initiative.
- **Reuse, don't duplicate, existing infrastructure**: the Action Plan entity
  model (`action_groups`/`action_items`), the execution/idempotency pattern
  used throughout (UUID execution id, idempotency key, immutable history),
  structured logging with request-id/execution-id tracing, and the existing
  `report_artifacts`-style durable storage pattern (bytes in Postgres, not on
  container filesystem — see `docs/PRODUCTION_OPERATIONS.md` §9/§14).

## 5. Module breakdown

Each module below is **NOT STARTED**. Status field must be updated as
decisions are made. Do not implement a module until the user has explicitly
discussed and approved its approach — this was an explicit instruction.

### M1 — Test case design & device/OS/browser matrix

- **Status:** DECIDED (2026-08-14). Test-case design and the tablet-naming
  change are implemented; the execution engine (M2), DB schema (M4), and
  evidence-state mapping (M5) are separate, still-not-started modules.
- **Purpose:** Define, as a QA expert would, which page × browser × OS ×
  device × viewport combinations are actually worth testing — risk-based, not
  exhaustive combinatorics.
- **Grounding check performed 2026-08-14:** compared the user's ask against
  the ALREADY-LOCKED `BRANDED_BROWSER_SCOPE` in `browser_compatibility.py:58`.
  That structure already declares the target combinations (Chrome on
  Windows/macOS/**Android 12+**; Edge on Windows only; Safari on macOS/**iOS
  16+**; Firefox explicitly excluded from customer UAT). M1 designs test
  cases to satisfy that existing target, plus explicitly closes one real gap:
  **iPadOS is not called out as its own platform** — Safari-on-iPad currently
  rides implicitly inside "iOS 16+", which blurs phone vs. tablet form-factor
  bugs. Proposed fix: add an explicit `iPadOS 16+` platform entry (and
  Android tablet under the existing Chrome/Android entry), tested against the
  existing `tablet: 768x1024` viewport already defined in
  `RESPONSIVE_VIEWPORTS`. **This changes a file `CLAUDE.md` marks LOCKED —
  requires explicit user sign-off before any code change**, not implied by
  "start with M1".
- **Current real-world version snapshot** (verified via web search 2026-08-14,
  not estimated — see chat for sources): Chrome latest-2 = 151/150; Edge
  latest-2 = 151/150; Safari = 26.6 (floor requirement, not latest-2); iOS/
  iPadOS latest-2-major = 26/18 (Apple's 2025 renumbering skipped 19–25);
  Android latest-2-major = 17/16. These are illustrative only — the contract
  requires re-deriving "latest-2-stable at UAT date" at execution time, not
  hardcoding today's snapshot.
- **Proposed tiering (risk-based):**
  - **Tier 0 — contract-critical:** exactly the six combinations
    `BRANDED_BROWSER_SCOPE` requires. Page selection reuses the existing
    critical-page logic in `select_compatibility_pages`
    (`browser_compatibility.py:174` — home/product/checkout/contact/flagged),
    not every page. Must use real-device evidence; this is the only tier that
    can legitimately produce `VERIFIED`.
  - **Tier 1 — form-factor extension:** the iPadOS/Android-tablet gap above.
  - **Tier 2 — fast regression net:** broader page/viewport coverage on
    emulators only, run often, capped at `PARTIALLY_VERIFIED` — never
    `VERIFIED`, matching the existing engine-vs-branded-browser honesty rule.
- **Evidence-tier strategy (SUPERSEDED 2026-08-14 — see decision 4 below):**
  originally proposed a paid real-device cloud lab for Tier 0; the user does
  not want to pay for one. Revised to a zero-cost, platform-tiered strategy —
  no third-party vendor account, no ongoing spend.
- **Decisions made (2026-08-14, via AskUserQuestion, user-confirmed; decision
  4 corrected same day after the user rejected paid options):**
  1. **Scope: customer-analyzed websites only** (extends the existing
     `browser_compatibility.py` machinery). ZuiGO's own frontend E2E coverage
     (`apps/web` has ZERO real-browser test coverage today) is explicitly
     OUT of scope for this initiative — noted as a separate, real gap that
     was NOT picked up here. Revisit as its own initiative if wanted later.
  2. **Evidence-tier strategy: hybrid, confirmed** — but "real-device cloud
     lab" now means the zero-cost sources in decision 4, not a paid vendor.
     Tier 0 (contract-critical, produces genuine `VERIFIED`) uses real
     evidence from free sources; Tier 2 (fast regression) uses simulators/
     emulators, capped below `VERIFIED`.
  3. **Tablet/iPad handling: "document now, restructure later," confirmed.**
     Implemented 2026-08-14 as an additive, zero-blast-radius change.
     Full per-form-factor `VERIFIED`/`PARTIALLY_VERIFIED` splitting (growing
     the matrix from 3 rows to 5) is explicitly DEFERRED to M4 (DB schema)
     and M5 (evidence-state mapping) design, not done today. This was a
     course-correction: the original AskUserQuestion wording ("get their own
     platform entries") implied more than a same-day locked-file edit should
     safely do without M4/M5 designed first — caught after checking the
     blast radius (`_build_browser_uat_matrix` and `browser_uat_completion`
     in `browser_compatibility.py` iterate one row per browser; CLAUDE.md's
     locked description itself frames scope as "exactly" 3 browsers).
  4. **Evidence source: NO PAID VENDOR. Zero-cost, platform-tiered, decided
     2026-08-14 after the user explicitly rejected paying:**
     - **Desktop Chrome/Edge/Safari (Windows/macOS): GitHub-hosted Actions
       runners.** These runners ship real installed Chrome, Edge, and Safari
       — genuine branded binaries, not engines, not emulation. The repo
       (`Ramashish-ZuiGO/ZuiGO-Website-Intelligence`) is confirmed PUBLIC
       (user-confirmed 2026-08-14), so GitHub Actions minutes are unlimited
       and free — no budget ceiling, including for the 10x-cost macOS/Safari
       runner. This is strictly better evidence than today's Chromium/WebKit
       engine-only signal and can legitimately justify real `VERIFIED` for
       these desktop combinations at zero incremental cost, reusing the
       already-existing `.github/workflows/ci.yml`.
     - **Android phone + tablet: Firebase Test Lab + Samsung Remote Test
       Lab.** Both are free, real-hardware (not emulated) offerings — Firebase
       Test Lab for solo/low-volume Android testing on real Google-hosted
       devices, Samsung Remote Test Lab for free remote access to real
       physical Galaxy devices. Genuine device evidence, zero cost.
     - **iOS/iPadOS: honest gap, not engineered around.** No service offers
       free real iPhone/iPad hardware — every real-device iOS option found is
       paid. Default path: the free macOS-runner iOS Simulator (Apple's real
       Safari/WebKit build, not physical hardware) — capped at
       `PARTIALLY_VERIFIED`, never `VERIFIED`, matching the existing
       engine-vs-branded honesty rule. **Non-blocking future upgrade**: if the
       team has any spare iPhone/iPad, [GADS](https://github.com/shamanec/GADS)
       (open-source, self-hosted Appium device farm) can drive real hardware
       at zero third-party cost — this was asked but not yet answered; revisit
       if/when a device becomes available, it does not block M2.
     - Sources: GitHub Actions 2026 pricing/macOS multiplier
       (cicdpipelinecost.com, gitspider.com), Firebase Test Lab
       (drizz.dev/post/firebase-test-lab-guide), GADS
       (github.com/shamanec/GADS) — verified via web search 2026-08-14, not
       assumed from training data.

- **What was implemented today (M1 only, additive, non-breaking):**
  `apps/api/app/services/browser_compatibility.py` — Safari's
  `required_platforms` gained `"iPadOS 16+"`; Chrome's Android platform
  string was clarified to `"Android 12+ (phone and tablet)"`; both entries'
  `limitations` gained an explicit sentence stating phone and tablet
  currently share one verification state. `CLAUDE.md`'s locked-contract
  summary line was updated to match. The matrix stays exactly 3 rows/3
  browsers — `browser_uat_completion`'s `required_browser_count` is
  unchanged. New regression test:
  `tests/api/test_browser_compatibility.py::test_tablet_form_factors_are_documented_without_growing_the_matrix`
  (asserts the row count, the new platform strings, the new limitations text,
  and that neither entry's `verification_state` moved off `NOT_VERIFIED` just
  because it's now named — naming a platform must never be mistaken for
  verifying it). Full suite: 924 passed, 1 skipped (923 baseline + 1 new).
  Nothing committed or pushed.

### M2 — Execution engine

- **Status:** Lane A shipped 2026-08-14 (desktop Chrome/Edge). Lane B shipped
  2026-08-15 (desktop Safari via Selenium/safaridriver). Lane C shipped
  2026-08-15 (Android Chrome via ChromeDriver-over-adb, manually triggered —
  see its own entry below). The iOS/iPadOS Simulator Safari lane also
  shipped 2026-08-15 (Appium's Safari driver, fully automated inside the
  same GitHub Actions workflow as Lane A/B — see its own entry below). Every
  planned platform combination in `BRANDED_BROWSER_SCOPE` now has a Tier 0
  lane; no execution-engine gaps remain in this initiative's original scope.
- **Purpose:** Actually drive the chosen matrix and capture pass/fail/warning
  per combination.
- **Key finding that reshaped this module (2026-08-14):** Playwright cannot
  automate real Safari — it only ships its own WebKit build, the exact
  "engine ≠ branded browser" gap the locked contract already names. Real
  Safari needs Selenium + Apple's `safaridriver`, a different toolchain.
  Firebase Test Lab is fundamentally an APP-testing service (Espresso/UI
  Automator/XCTest) — driving a URL in real Chrome on a real Android device
  needs a small Appium-based test-harness APK, not a trivial URL-in
  screenshot-out call. Samsung Remote Test Lab does genuinely support both
  automation APIs and manual testing (confirmed, not manual-only). These
  findings split M2 into three lanes of very different complexity — see
  decision log.
- **Trigger model (default applied, not formally re-asked):** on-demand only,
  via `POST /api/v1/analysis-runs/{analysis_run_id}/browser-uat/tier0`,
  idempotency-keyed. Decoupled entirely from `full_website_analysis`.
- **What shipped (Lane A — desktop Chrome/Edge, via GitHub Actions):**
  - `browser_uat_tier0_executions` table (migration `20260814_0022`,
    live-verified: upgrade → shape matches ORM exactly → downgrade → clean
    removal → re-upgrade → back at head, against the real dev Postgres).
    Minimal first cut per the model's own docstring — M4 will formalize the
    full per-combination schema.
  - `.github/workflows/browser-uat-tier0-desktop.yml` +
    `.github/scripts/browser_uat_tier0_check.mjs` — real jobs on
    `windows-latest` (Chrome + Edge via Playwright's `channel` option, which
    launches the actual installed browser, not bundled Chromium) and
    `macos-latest` (Chrome only — deliberately no Safari job). `run-name`
    embeds a correlation id since `workflow_dispatch` returns no run id.
  - `worker_app/integrations/browser_uat_tier0_dispatch.py` — `Tier0DispatchClient`
    Protocol (mirrors the existing `PageRunner` Protocol pattern in
    `browser_compatibility.py`), a fully deterministic `FakeTier0DispatchClient`
    for tests, and `GitHubActionsTier0DispatchClient` implemented against the
    documented, stable GitHub REST API contract — **NOT live-verified this
    session** (no PAT/GitHub App token available); the artifact-download step
    is an explicitly documented follow-up, not implemented blind.
  - `worker_app/tasks/browser_uat_tier0.py` — dispatch task (claims ownership
    via `SELECT ... FOR UPDATE`, refuses redelivery) and a poll task that
    reschedules itself via `apply_async(countdown=...)` rather than blocking,
    so it never holds a worker concurrency slot hostage, per
    `PRODUCTION_OPERATIONS.md`'s concurrency policy. Bounded at 60 poll
    attempts (~30 min) before honestly marking `unavailable`.
  - `GITHUB_ACTIONS_TOKEN`/`GITHUB_ACTIONS_REPO`/`GITHUB_ACTIONS_REF` added to
    worker settings, optional, matching the AI-provider pattern — absence
    never blocks startup or the main analysis pipeline.
  - Tests: 18 new (5 API route, 8 worker orchestration, 10 workflow-contract
    — one overlaps a category above), all passing; full suite
    947 passed, 1 skipped.
- **Lane B (desktop Safari via Selenium/safaridriver) shipped 2026-08-15:**
  added as a 4th job (`safari-macos`) to the SAME `browser-uat-tier0-desktop.yml`
  workflow and dispatch/poll/correlation-id pipeline as Lane A — no schema or
  backend changes needed beyond one line
  (`TIER0_BROWSER_CHANNELS["Apple Safari"] = "safari"` in
  `browser_compatibility.py`), because Lane B's output JSON deliberately
  matches Lane A's `JobResultPayload` contract exactly, so
  `ingest_browser_uat_tier0_job_result`, the M4 schema, and M5's
  `apply_tier0_evidence` all work unmodified. New
  `.github/scripts/browser_uat_tier0_check_safari.mjs` drives real Safari via
  `selenium-webdriver` (`Builder().forBrowser(Browser.SAFARI)`) — a
  genuinely different toolchain from Lane A's Playwright script, not a
  variant of it, because Playwright cannot automate real Safari (only its own
  WebKit build).
  - **Real feasibility risk found and cited, not assumed:** GitHub-hosted
    macOS runner images had a confirmed regression (June–July 2025,
    [actions/runner-images#12616](https://github.com/actions/runner-images/issues/12616))
    where a TCC permission dialog ("hosted-compute-agent wants access to
    control Safari") silently blocked all Safari automation, with no
    non-interactive workaround. GitHub shipped an official fix
    ([actions/runner-images#12752](https://github.com/actions/runner-images/pull/12752),
    merged ~August 2025) pre-granting the needed TCC entries. Proceeding on
    the strength of that fix having shipped over a year before this build
    (today: 2026-08-15) — but this has **not been live-verified this
    session** (no macOS/Safari environment available locally, and no PAT to
    trigger a real GitHub Actions run), so it remains the single largest
    unverified assumption in Lane B until a real run confirms it.
  - **Three deliberate, documented WebDriver-protocol limitations** (not
    oversights): `http_status` is always `null` (W3C WebDriver exposes no
    navigation HTTP status, unlike Playwright's CDP-based response object);
    `console_error_count` is always `0` (Safari's WebDriver logging is
    restricted to on/off with no retrievable entries — "not measured", not
    "no errors found"; confirmed unused by any downstream finding/action
    logic, so this can't fabricate a false-clean signal); viewport size is
    achieved by resizing the OS window and then measuring the ACTUAL
    resulting `window.innerWidth`/`innerHeight` (WebDriver's `setRect` sizes
    the outer window, not the inner document viewport — macOS window chrome
    eats part of it), and the assertion function is always called with the
    REAL measured size, never the nominal target.
  - **API surface verified against the real installed package**, not
    guessed: installed `selenium-webdriver@4.47.0` in a scratch directory and
    confirmed `Builder`, `Browser.SAFARI`, `Capabilities.getBrowserVersion`,
    and `WebDriver.prototype.{executeScript,manage,get,getCapabilities,quit}`
    all exist as documented, plus `Window.prototype.setRect({x,y,width,height})`
    by reading the installed package's own source
    (`node_modules/selenium-webdriver/lib/webdriver.js`).
  - Tests: 2 new evidence-mapping tests (Safari reaches `PARTIALLY_VERIFIED`
    from clean macOS evidence alone, never full `VERIFIED`, mirroring
    Chrome's existing Android-shaped gap) + 11 new/restructured workflow
    structural tests (job exists, safaridriver-enable-before-check ordering,
    Selenium not Playwright, null http_status, executeScript wrapping,
    `node --check` syntax validation since no runtime execution is possible
    here). Full suite: 1013 passed, 1 skipped (1000 baseline + 13 new).
- **Explicitly NOT built yet (separate follow-up lanes, not blocking):**
  iOS/iPadOS Safari (Simulator or real device) — Selenium cannot drive those,
  only Appium (XCUITest driver) can, a materially different toolchain closer
  to Lane C than to this desktop Selenium lane. The live GitHub API client's
  dispatch/poll HTTP calls are implemented but unverified against real GitHub
  infrastructure — no PAT configured this session.

#### Lane C (Android real device) — shipped 2026-08-15, manually-triggered

The user's explicit rule for this whole initiative: free-of-cost only, never
compromise validation. Investigation (below) found neither free candidate
cleanly fits the fully-automated GitHub-Actions-dispatch model Lane A/B use —
but the user clarified the goal is the most CAPABLE free option, flexible on
how much can be live-verified this session (matching Lane A/B's own
"not live-verified, no credentials this session" precedent), not a hard stop
at "can't automate it end-to-end." That reframing is what unblocked building
this.

- **Firebase Test Lab investigated and rejected as the build target**
  (Spark/free tier: 5 physical-device runs/day, no credit card —
  [pricing docs](https://firebase.google.com/docs/projects/billing/firebase-pricing-plans)).
  Checked against the OFFICIAL docs after an unreliable secondary source
  claimed Appium support: Test Lab's only supported Android test types are
  **Instrumentation, Robo, and Game Loop**
  ([firebase.google.com/docs/test-lab](https://firebase.google.com/docs/test-lab))
  — a cloud run uploads a self-contained test APK that executes autonomously
  with **no live network access** for an external client to drive it, unlike
  GitHub Actions' live shell or a real ADB connection. Making this work would
  need genuine on-device Kotlin/Gradle instrumentation code — a completely
  different toolchain (zero Android SDK/Gradle on this dev host, no way to
  compile-check it) for a materially worse evidence quality than the
  alternative below (accessibility-tree UI automation, not real JS/DOM
  assertions). Rejected on capability grounds, not just verification-risk
  grounds.
- **Chosen approach: ChromeDriver's official native Android support**
  ([developer.chrome.com/docs/chromedriver/get-started/android](https://developer.chrome.com/docs/chromedriver/get-started/android)) —
  the `androidChrome()` / `androidPackage` capability drives REAL Chrome on a
  REAL Android device over a plain `adb` connection, no root required for
  Chrome 33+. This is the standard, official mechanism (the same one Appium
  uses under the hood for Chrome automation) and — critically — it's the
  SAME ChromeDriver/WebDriver protocol Lane A/B already use, so it reuses the
  existing `selenium-webdriver` tooling AND the shared
  `responsive_assertions.js` module verbatim, running real JS/DOM structural
  assertions rather than Firebase's accessibility-tree-only alternative. API
  surface verified against the actually-installed npm package (`chrome.Options().androidChrome()`
  confirmed to set `{"androidPackage": "com.android.chrome"}`), same
  discipline as Lane B.
- **Trigger model is genuinely different from Lane A/B, and that's
  documented, not hidden:** no free provider offers live adb access to a real
  device from an unattended GitHub Actions runner. **Samsung Remote Test
  Lab** (free, no card) is the practical way to GET that access — it exposes
  a **Remote Debug Bridge** giving real ADB access "as if the device were
  connected to your computer"
  ([Samsung Developer blog](https://developer.samsung.com/sdp/blog/en/2021/02/18/get-started-with-remote-test-lab-for-mobile-app-testing)) —
  but reservation is manual (sign up, pick a device, schedule access) with no
  documented REST API for unattended dispatch. So Lane C is a **hybrid**: a
  human reserves a device and connects the Remote Debug Bridge (or just
  plugs in their own Android phone via USB for ad-hoc checks — the script
  doesn't care which), then runs the fully-automated check script against
  whatever `adb` sees.
- **What shipped:**
  - `scripts/browser_uat_tier0_check_android.mjs` (new) — the ChromeDriver-
    over-adb check script. Deliberately lives in `scripts/` (operator-run
    tools), not `.github/scripts/` (CI-only), since nothing dispatches it
    automatically. Tests exactly ONE viewport per page (the device's real
    screen, measured via `window.innerWidth`/`innerHeight`), not a
    Desktop+Mobile pair like Lane A/B — a real phone has no resizable
    window, and claiming a 1440x900 desktop viewport was tested on a handset
    would be fabricated evidence. Same WebDriver-protocol honesty pattern as
    Lane B: `http_status` always null, `console_error_count` always 0
    (ChromeDriver's browser-log capability exists but has a documented
    history of version-dependent breakage across ChromeDriver releases —
    deliberately not relied on blind; a real future upgrade, not a silent
    gap, since it's confirmed unused downstream).
  - `scripts/ingest_manual_tier0_result.py` (new) — feeds the script's JSON
    output into the SAME `browser_uat_tier0_executions`/`..._page_results`
    tables Lane A/B's Celery tasks write to, via the exact same
    `create_browser_uat_tier0_execution`/`ingest_browser_uat_tier0_job_result`
    service functions, reusing the same `DEFAULT_LANE` value (no new lane
    string — same reasoning as Lane B: `lane` names the GitHub-Actions-
    adjacent Tier 0 evidence-gathering effort as a whole, not literally
    "dispatched by a workflow"). Mirrors `_finalize`'s exact status semantics
    (`COMPLETED` only on full success, else `PARTIAL`, never `FAILED`, since
    real per-page evidence WAS produced).
  - **Real bug caught by tests, not shipped:** the ingestion script initially
    passed `execution.execution_id` (the external/correlation UUID) where
    `BrowserUatTier0PageResult`'s foreign key actually targets
    `execution.id` (the primary key) — two separate UUID columns on the same
    row, easy to confuse since `ingest_browser_uat_tier0_job_result`'s own
    parameter is also named `execution_id`. A SQLite `IntegrityError` from
    the first test run caught it immediately; fixed and documented inline
    with a comment pointing at the existing M4 ingestion tests as the
    reference for which UUID is correct. Exactly the kind of thing "don't
    compromise on validation" is for.
  - One line in `browser_compatibility.py`: `TIER0_PLATFORM_LABELS["android"]
    = "Android 12+ (phone and tablet)"` — no other M5 evidence-mapping code
    needed changing, because `apply_tier0_evidence` was already written
    generically over platform codes. This is Chrome's LAST missing required
    platform (`BRANDED_BROWSER_SCOPE`'s `required_platforms` = Windows +
    macOS + Android) — with clean evidence on all three, Chrome can now
    reach full `VERIFIED` for the first time in this initiative, proven by a
    new test.
  - Tests: 2 new evidence-mapping tests (Chrome reaches full `VERIFIED` with
    clean Windows+macOS+Android; a failing Android page alone caps it at
    `PARTIALLY_VERIFIED`) + 11 Android-script structural tests (mirroring
    Lane B's pattern, including `node --check` syntax validation) + 4
    ingestion-CLI tests (against an in-memory SQLite DB via monkeypatching
    the script's `SessionLocal` import — the script has no FastAPI-style
    dependency-injection seam, so this is the closest equivalent). Full
    suite: 1030 passed, 1 skipped (1013 baseline + 17 new).
- **What's still unverified, honestly:** no real Android device or Samsung
  RTL account was available this session to run the script end-to-end — the
  API surface is verified against the real npm package (same as Lane B), but
  a live device run (real `adb`, real ChromeDriver-Chrome handshake) has not
  happened. This is the same category of gap as Lane A's un-PAT-verified
  GitHub client and Lane B's un-macOS-verified safaridriver step — documented
  as the next thing to confirm, not silently assumed working.

##### One-click Android CLI — shipped 2026-08-16

Lane C originally needed two separate manual commands (drive Chrome, then
report the result). Combined into one: `scripts/run_manual_tier0_android_check.py
--analysis-run-id <uuid>`.

- **Design decision (discussed before building):** the eventual goal is a
  one-click button in the actual product UI, but the web frontend cannot
  reach a locally-plugged-in phone at all — browsers are sandboxed from
  local hardware/shell access by design, and Chrome's "Local Network
  Access" restriction (shipped Chrome 142, expanded 147) specifically
  blocks a public website from silently reaching `localhost`/a local
  agent, showing a permission prompt that fails silently if unapproved.
  Weighed three real options: (1) a persistent local helper agent the web
  UI calls over `localhost` — works, but fights that exact browser
  restriction on every use; (2) a desktop/Electron wrapper — real access,
  but heavier to build/maintain for one narrow feature; (3) a
  self-reporting CLI that POSTs its own result to the backend, with the
  web UI only ever polling and displaying status, never reaching into the
  operator's machine. Chose (3) — no browser security fight, reuses ~90%
  of what Lane C already had, and the web UI's role stays the simplest
  possible thing a webpage can do (read and display). The actual frontend
  polling/status piece is deliberately NOT built yet — `apps/web` is
  flagged in `CLAUDE.md` as often owned by a separate parallel agent
  ("Antigravity"), and touching it without an explicit handoff risks
  colliding with unseen in-progress work; this CLI stands alone as a real,
  usable tool in the meantime.
- **What it does:** looks up the target website's URL from
  `--analysis-run-id` directly (same DB access `ingest_manual_tier0_result`
  already had — no new API call needed), runs
  `browser_uat_tier0_check_android.mjs` as a subprocess with the right env
  vars, and — only if that subprocess succeeds — calls
  `ingest_manual_tier0_result()` directly as a normal Python function call
  (not a second subprocess hop) to record the result. A failed check is
  never ingested, so a broken run can't silently write bad/partial data
  into a report.
- **Tests:** 6 new (URL lookup + missing-analysis-run error; successful
  check gets ingested with the right env vars; a failed check is never
  ingested; device-serial passthrough present/absent) — all via
  monkeypatched `subprocess.run`/`ingest_manual_tier0_result`, no real
  Node process or device touched. Full suite: 1081 passed, 1 skipped
  (1075 baseline + 6 new).

#### iOS/iPadOS Simulator Safari lane — shipped 2026-08-15, fully automated

Unlike Lane C, this lane is genuinely FULLY automatable: GitHub-hosted macOS
runners ship Xcode with iOS/iPadOS Simulator runtimes preinstalled (confirmed
via [actions/runner-images research](https://github.blog/changelog/2026-02-26-macos-26-is-now-generally-available-for-github-hosted-runners/)
done for Lane B — the Simulator needs no real device, no adb, no manual
reservation), and Appium's official Safari driver
([appium.github.io/appium-safari-driver](https://appium.github.io/appium-safari-driver/latest/))
documents first-class iOS Simulator support with exact, unambiguous
capabilities (`platformName: "ios"`, `appium:automationName: "Safari"`,
`safari:useSimulator: true`, `safari:deviceType: "iPhone"|"iPad"`) — a much
clearer story than Android/Firebase's murkier, contradicted-by-official-docs
situation.

- **Architecture: Appium server + the SAME `selenium-webdriver` client Lane
  B/C already use**, just pointed at a local Appium server
  (`new Builder().usingServer("http://localhost:4723")`) instead of a local
  browser process — Appium implements the standard WebDriver protocol, so no
  new client library was needed. API surface verified against the real
  installed `selenium-webdriver` package (`usingServer`/`withCapabilities`
  confirmed to exist), and both `appium@3.6.0` and `appium-safari-driver@5.0.7`
  confirmed to exist on the npm registry (both Appium-3-generation releases,
  consistent with the docs' "since 4.0.0, Safari driver requires Appium 3"
  note).
- **Added as a 5th job (`ios-safari-simulator`) to the SAME
  `browser-uat-tier0-desktop.yml` workflow/dispatch/poll pipeline** as Lane
  A/B, matrixed over `device_type: [iPhone, iPad]` (Safari's `required_platforms`
  names iOS 16+ and iPadOS 16+ as separate entries, so separate evidence
  rows are needed, mirroring the Windows job's `[chrome, msedge]` matrix
  pattern). The workflow file is genuinely no longer "desktop-only" now, but
  keeping one file/one lane avoids duplicating the entire
  dispatch/poll/correlation-id machinery for a second workflow — the same
  naming-simplicity tradeoff already made for Lane B's `lane` value.
  Prerequisite steps run in order (enable safaridriver → install Appium +
  the Safari driver → start the Appium server in the background → poll its
  `/status` endpoint until ready → run the check script), verified via a
  dedicated ordering test.
- **New `.github/scripts/browser_uat_tier0_check_ios.mjs`** — lives under
  `.github/scripts/` (not `scripts/`) since this genuinely runs unattended
  inside CI, unlike Lane C. Tests exactly ONE viewport per page (the
  simulator's real device screen, measured via `window.innerWidth`/
  `innerHeight`), not a Desktop+Mobile pair, for the same reason as Lane C
  (a phone/tablet simulator has no resizable window). Deliberately omits a
  hardcoded `safari:platformVersion` by default — pinning one would break as
  the runner's default Xcode/Simulator version changes over time (the
  runner-images research for this same session found macOS runners already
  moving from Xcode 15-era to Xcode 26-era defaults within 2026), matching
  §8's "re-derive at execution time" principle already established for this
  plan doc. Same WebDriver-protocol honesty pattern as Lane B/C:
  `http_status` always null, `console_error_count` always 0.
- **Two lines in `browser_compatibility.py`**: `TIER0_PLATFORM_LABELS["ios"]
  = "iOS 16+"` and `["ipados"] = "iPadOS 16+"` — no other M5 code changed,
  same as Android. These are Safari's last two missing required platforms:
  with clean macOS + iOS + iPadOS evidence, Safari can now reach full
  VERIFIED for the first time, proven by a new test (mirrors Chrome's
  equivalent Lane C milestone).
- **Real, cited risk, not glossed over:** iOS Simulator JS execution via
  Appium/WebDriverAgent has a documented history of version-dependent
  reliability issues (e.g.
  [appium/appium#8735](https://github.com/appium/appium/issues/8735),
  [appium/appium#1791](https://github.com/appium/appium/issues/1791) — JS
  silently not executing, or not executing again after in-page navigation,
  on some Appium/iOS version combinations). This is the single largest
  unverified assumption in this lane; the shared assertion module's
  execution correctness on a real Simulator has not been confirmed this
  session (no macOS/Xcode environment available).
- **Tests:** 2 new evidence-mapping tests (Safari reaches full `VERIFIED`
  with clean macOS+iOS+iPadOS; a failing iPad page alone caps it at
  `PARTIALLY_VERIFIED`) + 5 new workflow-job structural tests (matrix,
  Appium/Safari-driver install, prerequisite ordering, readiness wait,
  per-matrix-entry device-type env) + 11 script-structural tests (mirroring
  Lane B/C's pattern, including `node --check` syntax validation). Full
  suite: 1048 passed, 1 skipped (1030 baseline + 18 new).
- **What's still unverified, honestly:** no macOS/Xcode/Simulator
  environment was available this session to run this end-to-end — same
  category of gap as Lane B's un-macOS-verified safaridriver step and Lane
  C's un-device-verified ChromeDriver-over-adb step, compounded here by the
  cited Appium/iOS JS-execution reliability history above. Treat the first
  real GitHub Actions dispatch as this lane's actual verification, per this
  initiative's established convention.

#### iOS lane real-dispatch verification, 2026-08-15/16 — iPhone works, iPad marked as a known pending limitation

Four real GitHub Actions dispatches were run against `fluidcontrols.com` to
close the "unverified" gap above (via the same `POST .../browser-uat/tier0`
route a real customer analysis would use, plus direct GitHub REST API calls
from inside the worker container to pull real job logs/artifacts for
diagnosis — all against the token set up for this exact purpose). This also
verified Lane A/B end-to-end for the first time, and caught two unrelated
real bugs (`actions/setup-node@v6`'s npm-cache default, and an empty-string
vs `None` gap in `_build_dispatch_client`'s token check) — see their own
decision-log entries. This entry is specifically about the iOS Simulator
lane's own iteration:

- **Dispatch 1**: all 6 jobs failed identically at the `setup-node` step
  (unrelated cache bug, fixed separately). No iOS-specific signal yet.
- **Dispatch 2** (after the cache fix): **4/6 succeeded** — both desktop
  Chrome/Edge jobs and desktop Safari all completed with real branded
  evidence. Both iOS Simulator jobs failed with `SessionNotCreatedError`:
  "...waiting for its RWIApplication to appear." Root cause: Appium's
  Safari driver does not auto-boot a simulator when `safari:deviceName` is
  omitted — it only finds Safari inside an already-running one.
  **Fix 1**: dynamically discover and boot a real simulator via `xcrun
  simctl` before the check step (never hardcoding a device/iOS version).
- **Dispatch 3** (after fix 1): **5/6 succeeded** — the iPhone Simulator job
  passed for the first time with a real Safari session and real structural
  findings (15 small tap targets, 2 clipped elements, real
  `viewport_problems` on the live site). iPad Simulator still failed with
  the identical `RWIApplication` timeout despite the simulator confirmed
  booting correctly this time. Root cause: booting gets the OS to "Booted,"
  but Apple's Remote Web Inspector only registers a browser once it has
  actually launched and connected to `webinspectord` — a freshly-booted,
  never-opened simulator can still exceed Appium's internal session-creation
  budget. **Fix 2**: explicitly launch Safari via `simctl launch
  <udid> com.apple.mobilesafari` right after boot, before Appium ever tries
  to create a session.
- **Dispatch 4** (after fix 2): **5/6 again** — iPhone succeeded again
  (3rd consecutive real success). iPad failed with a **different** error
  this time: `WebDriverError: Safari Driver server is not listening within
  10000ms timeout`. Read `appium-safari-driver`'s own source
  (`SafariDriverServer.start`, `lib/safari.ts`) directly: that 10-second
  timeout is hardcoded, not configurable via any capability, and spawns a
  plain local `safaridriver -p <port> --diagnose` process with no
  device/UDID argument — identical regardless of iPhone vs iPad. Pointed at
  system resource contention (a heavier simulator still settling) rather
  than a logic bug. **Fix 3**: prefer a lighter non-"Pro" device when
  available (still fully dynamic) + a longer settle window (5s → 15s).
- **Dispatch 5** (after fix 3): **5/6 again, identical error.** The log
  confirmed both mitigations were genuinely applied (booted "iPad Air
  13-inch (M4)" — the lighter-device preference worked; the full 15s settle
  elapsed) — the exact same hardcoded-10-second `safaridriver` timeout
  fired anyway.
- **Decision, 2026-08-16:** stopped iterating here rather than continue
  guessing. Searched GitHub's issue tracker directly (`appium-safari-driver`
  repo and all of GitHub) for the exact error text and for "RWIApplication"
  + iPad, plus the Appium community forum — **zero hits anywhere.** This
  isn't a known, previously-diagnosed community bug with an established
  fix; continuing would mean more first-principles guessing at real cost
  (~6-8 minutes per round trip) with no external validation to raise
  confidence. **iPhone Simulator Safari is now proven reliable (3/3 real
  successes with genuine evidence) and is production-ready. iPad Simulator
  Safari is marked a known, pending limitation** — the code requires no
  change for this (missing evidence for one platform already degrades
  gracefully: `apply_tier0_evidence` simply caps Safari at
  `PARTIALLY_VERIFIED` when `ipados` evidence is absent, exactly as
  designed — see the `TestSafariCanReachPartiallyVerifiedFromMacosLaneAlone`
  tests). The job is left in the workflow as-is (attempting and visibly
  failing each run, not silently skipped) so it can be revisited — by a
  future session, or if this becomes a documented Appium issue later.
  `browser_version` also came back `null` for the iPhone Simulator's own
  successful runs (confirmed via the raw artifact JSON, not an ingestion
  bug) — Appium's Safari driver doesn't reliably report a version the way
  desktop Safari/Chrome do; noted as another honest, non-blocking gap
  alongside the null `http_status`/zero `console_error_count` pattern.

#### Artifact-fetch wiring — shipped 2026-08-15

`GitHubActionsTier0DispatchClient._fetch_results_artifact` had been a stub
since M2 (logs a warning, returns `None`) — every lane's real results were
dispatched and polled correctly, but a completed run's actual evidence never
reached the M4 tables. This closes that gap for real, not just at the client
level.

- **`_fetch_results_artifacts` (now plural)** lists a run's artifacts
  (`GET .../runs/{run_id}/artifacts`) and downloads+unzips+parses each one.
  A run now legitimately produces up to 6 artifacts (2 Windows
  [chrome, msedge] + 1 macOS Chrome + 1 macOS Safari + 2 iOS Simulator
  [iPhone, iPad]), so `Tier0PollResult.results` changed type from
  `dict | None` to `list[dict] | None` -- a real breaking change to that
  dataclass, caught and fixed in the existing worker task tests that still
  passed a single dict.
- **Uses `httpx` (already a worker dependency), not the existing urllib-based
  `_request` helper**, specifically because GitHub's artifact-download
  endpoint 302-redirects to a signed URL on a DIFFERENT host, and that
  redirect target must NOT receive the original GitHub token -- httpx
  strips `Authorization` on cross-origin redirects by default; a naive
  urllib redirect would resend it. This was verified empirically with a
  local `httpx.MockTransport` repro (two-hop request, auth header present
  on the first hop, confirmed absent on the second) before relying on it,
  not assumed from documentation alone -- matching this initiative's
  consistent discipline of live-verifying cross-boundary HTTP/JS behavior.
- **Per-artifact failures are skipped with a warning, not fatal** -- a
  corrupt or missing single artifact must not discard the other real
  evidence a partially-successful run produced. Listing failures (a real
  auth/network problem) still propagate `DispatchUnavailableError`, same as
  every other call in this class, so the execution correctly finalizes as
  `UNAVAILABLE` rather than silently reporting zero results.
- **Wired into `poll_browser_uat_tier0`**: on completion, each parsed
  artifact now calls `ingest_browser_uat_tier0_job_result` for real (this
  function existed and was tested since M4, but nothing had called it from
  the actual task before). `_finalize`'s `structured_output` field changed
  from holding the raw results (`{"overall_status": "pass"}`) to a
  lightweight summary (`{"artifact_count": N}`) -- the model's own docstring
  already said `structured_output` should stay "lightweight
  summary/error context only," with real per-page/per-viewport evidence
  living in the M4 tables, not duplicated.
- **Tests:** 7 new dispatch-client tests (orchestration via monkeypatched
  `_request`/`_download_and_parse_artifact` -- listing failure propagates,
  a corrupt artifact is skipped not fatal, zero artifacts returns `[]`; plus
  3 tests against a REAL `httpx.MockTransport` covering the redirect+auth
  behavior, a non-JSON archive, and an HTTP error status) + 1 new/2 rewritten
  worker task tests (proving a completed poll cycle actually creates real
  `BrowserUatTier0PageResult` rows, not just logs a summary; an empty-artifact
  completion doesn't crash). Full suite: 1056 passed, 1 skipped (1048
  baseline + 8 new).
- **Still not live-verified**: same as the dispatch/poll HTTP calls
  themselves, no real PAT/GitHub infrastructure was available this session
  to confirm the real artifact-download endpoint behaves exactly as
  documented (the MockTransport repro proves httpx's redirect/auth handling
  is correct, not that GitHub's actual API returns what the docs say).

### M3 — Responsiveness assertion design

- **Status:** SHIPPED (2026-08-14) for the 4 structural checks that fit a
  single per-viewport evaluation, plus the 5th check (genuine cross-viewport
  navigation adaptation), shipped 2026-08-15 — see below.
- **Purpose:** Define concretely what "broken on mobile" means: horizontal
  overflow, clipped/overlapping elements, tap-target size, responsive
  navigation collapse — these are already named as required checks in
  `PRODUCT_MASTER_SPEC.md` §"BROWSER AND RESPONSIVE COMPATIBILITY".
- **Decision: DOM/structural assertions, not visual diffing** — grounded in
  what the codebase already does, not a green-field choice. Before designing
  anything, audited the existing responsive code in
  `apps/worker/worker_app/analysis/playwright_audit.py::inspect_page`: it
  already runs rich per-viewport DOM/CSSOM assertions (overflow, clipped
  elements, tap-target size with a spacing exception) across the full
  5-viewport `RESPONSIVE_VIEWPORTS` set — but Chromium-only, and only inside
  the bounded Level-2 deep-analysis path. No screenshot/pixel-diff code
  exists anywhere in the pipeline. Structural assertions fit the codebase's
  existing grain (deterministic, explainable, no subjective thresholds); a
  baseline-image approval workflow would be new infrastructure with no
  precedent. Visual diffing is not ruled out forever, just not chosen now.
- **Real defect found and fixed while auditing the cross-engine path:**
  `apps/api/app/services/browser_compatibility.py`'s multi-engine
  Chrome/Firefox/WebKit comparison runner (used by every customer analysis,
  not just this initiative) had `"viewport_problems": []` **hardcoded**, and
  its `classify_compatibility` function reads that field to help decide
  `compatible` vs `partially_compatible`. It could never fire from a real
  structural finding — silently dead since it was written. Fixed by wiring
  in the new shared assertion module. (`interaction_failures` and
  `accessibility_differences` are ALSO hardcoded empty in the same runner —
  confirmed but deliberately NOT touched; that's real interaction/
  accessibility-diff testing, a materially bigger scope than "what does
  broken responsive mean," flagged here so it isn't lost.)
- **Assertion contract (single source of truth):**
  `apps/api/app/services/responsive_assertions.js` — one JS expression
  callable via `page.evaluate(source, [name, width, height])` in both
  Playwright language bindings. Four checks: `horizontal_overflow`
  (`scrollWidth > viewport.width`), `critical_elements_outside_viewport`
  (nav/main/h1/button/input extending past the edges), `overlapping_elements`
  (any two visible elements from that same set whose boxes collide —
  broadened from the prior tap-target-only overlap check), `small_tap_targets`
  / `tap_target_samples` (interactive elements below the WCAG 2.5.5 24×24px
  floor, with a spacing exception for adjacent elements). Field names
  `horizontal_overflow` and `tap_target_samples` are preserved exactly because
  `worker_app/analysis/diagnostics.py` already consumes them by name for
  site-diagnostics findings — confirmed via grep before touching anything.
  `viewport_problems: list[str]` carries human-readable findings, matching
  the shape already established in `presentation_exports.py`'s demo fixture.
- **5th check, shipped 2026-08-15 — `responsive_navigation_adapts`:**
  whether a page's navigation genuinely adapts across viewports (item count
  changes, a toggle/hamburger control appears at mobile width) rather than
  the existing weak `responsive_navigation` field, which only checks that a
  `<nav>` element exists at all (true even for a static nav that just
  overflows/shrinks without adapting). Split across two layers, matching the
  architectural constraint identified when this was originally deferred
  (comparing results ACROSS two viewport evaluations doesn't fit a single
  `page.evaluate()` call):
  - `responsive_assertions.js` gained two new RAW per-viewport fields —
    `nav_visible_item_count` (visible `a[href]`/`[role="menuitem"]` inside
    `<nav>`-like elements) and `has_navigation_toggle` (a visible toggle
    control, detected via the standard `aria-expanded`/`aria-label*="menu"`
    a11y pattern plus common CSS-class heuristics) — still one
    self-contained per-viewport call, no architecture change there.
  - New `compute_responsive_navigation_adapts(page_observations)` in
    `browser_compatibility.py` does the actual cross-viewport comparison,
    run once per page+engine over that pair's Desktop+Mobile observations
    (pure JSON-in/bool-out logic, no DOM access needed at comparison time,
    so no browser context required to test it). Adapts = a toggle appears
    at mobile, OR strictly fewer nav items are directly visible at mobile
    (collapsed behind a menu) — not just visually smaller/overlapping,
    which `horizontal_overflow`/`overlapping_elements` already flag
    separately. Returns `None` (inconclusive, never fabricated) when either
    viewport's data is missing, e.g. the assertion script failed at one of
    them.
  - Wired into `run_compatibility_analysis`'s real matrix output: each
    page's matrix row now carries `responsive_navigation_adapts: {engine:
    bool | None}`, computed independently per engine (mirroring the
    existing `engines: {engine: state}` pattern) — proven with a fake
    runner where chromium's nav collapses at mobile and firefox's doesn't.
  - **Live-verified against real Chromium**, not just unit-tested: two new
    crafted-HTML fixtures (an adapting nav with a hamburger toggle, and a
    static nav that just stays the same) proved
    `nav_visible_item_count`/`has_navigation_toggle` behave correctly at
    both Desktop and Mobile width before the Python-side comparison logic
    was trusted — desktop showed 3 items/no toggle, mobile showed 0
    items/toggle-present for the adapting fixture; both viewports showed
    identical 3/no-toggle for the static one.
  - Tests: 2 new real-Chromium tests
    (`tests/api/test_responsive_assertions.py`) + 8 new pure-Python unit
    tests for the comparison function's decision table (toggle appears,
    fewer items without a toggle, identical items, MORE items at mobile
    [not adapting], each missing-data case) + 1 new integration test
    proving the per-engine wiring through `run_compatibility_analysis`'s
    real matrix. Full suite: 1067 passed, 1 skipped (1056 baseline + 11
    new).
- **Wired into two real execution paths:**
  1. `browser_compatibility.py`'s `_run_playwright_observation` (the fix
     above) — real customer analyses now get real `viewport_problems`.
     Extracted into a small `evaluate_responsive_assertions(page, viewport)`
     helper specifically so the failure-fallback path (Playwright `Error`/
     `TimeoutError` during evaluation) is unit-testable without a real
     browser — verified it returns `{"horizontal_overflow": False,
     "viewport_problems": []}` rather than fabricating a finding, and that
     unrelated exceptions are NOT swallowed.
  2. `.github/scripts/browser_uat_tier0_check.mjs` (M2's Tier 0 lane) — now
     checks Desktop + Mobile viewports (matching `CompatibilityProfile`'s
     2-viewport convention, not the fuller 5-viewport set, to avoid changing
     the existing hot path's hidden performance assumptions) after a
     successful HTTP load, and a page with real structural problems now
     fails the check even with a clean HTTP status.
  3. `playwright_audit.py::inspect_page` was deliberately left untouched —
     its existing inline JS already works and is proven; refactoring a
     stable production hot path purely for single-sourcing aesthetics, with
     no functional need, was judged not worth the regression risk. True
     single-sourcing there is a nice-to-have follow-up, not done.
- **Real, hard-won cross-language bug found and fixed via live verification,
  not assumed:** Node's Playwright does NOT auto-detect and call a string
  `page.evaluate` source as a function the way Python's binding does — it
  evaluates the string as a plain expression, and a bare function expression
  isn't JSON-serializable across the protocol, so it silently resolves to
  `undefined`. Proven with a live minimal repro before touching the real
  script. The first fix attempt, `new Function('return ' + source)()`, ALSO
  silently failed for the real file specifically (not the simplified repro
  case): the file's leading `//` comment block sits on the same logical line
  as `return`, and JS's automatic-semicolon-insertion turns `return //
  comment...` into `return;`, discarding everything after. Root-caused via a
  second live repro. Final fix: indirect eval, `(0, eval)(source)`, which
  evaluates the whole file as a script and has neither trap. Verified
  end-to-end against real Chrome 151.0.7922.137 AND real Edge
  151.0.4129.78 with three crafted fixtures (overflow, small tap targets,
  clean baseline) before considering this done — this is exactly the kind of
  defect that would have shipped silently broken (every Tier 0 check
  crashing with `Cannot read properties of undefined`) without that
  verification.
- **Tests:** 15 new — 5 real-Chromium end-to-end tests
  (`tests/api/test_responsive_assertions.py`, skips cleanly if no browser
  binary is installed locally; CI does not install one for the Python suite)
  proving each problem category is genuinely detected against crafted HTML,
  not mocked; 6 wiring/fallback tests with a fake page object (no browser
  needed, always runs in CI); 4 new workflow-contract tests locking in the
  indirect-eval fix and the two-viewport check. Full suite: 962 passed, 1
  skipped (947 baseline + 15 new).

### M4 — Results storage (database schema)

- **Status:** SHIPPED (2026-08-14) for the desktop Tier 0 lane.
- **Purpose:** Durable, queryable, traceable history of every matrix
  execution and every individual combination's result.
- **Design, grounded in the closest real precedent, not invented:** studied
  `site_diagnostic_executions`/`findings`/`occurrences` (execution → grouped
  finding → per-page occurrence) before designing anything. That pattern's
  finding-DEDUPLICATION semantics don't apply here (a browser UAT
  page×viewport check is already the atomic unit of interest, nothing to
  group), so M4 uses a plainer 3-level hierarchy at the same depth: execution
  → page result → viewport result.
- **A real architectural gap surfaced while designing, not assumed:** the
  M2 workflow (`browser-uat-tier0-desktop.yml`) runs 3 SEPARATE jobs
  (chrome/windows, msedge/windows, chrome/macos), each uploading its OWN
  artifact — one execution legitimately produces 3 distinct result sets, not
  one. `BrowserUatTier0PageResult` is keyed by
  `(execution_id, browser_channel, platform, url)`, not just
  `(execution_id, url)`, specifically to hold all 3 without collision. This
  also surfaced that the Tier 0 script's own JSON output had no `platform`
  field — added one (`PLATFORM` env var per job, mirroring the existing
  `BROWSER_CHANNEL` pattern), live-verified it flows through correctly
  before designing the schema around it.
- **Schema:**
  - `browser_uat_tier0_executions` (M2, unchanged) — one row per
    `workflow_dispatch` call. Its `structured_output` JSONB is now
    documented as execution-level summary/error context ONLY — real results
    live below, not there.
  - `browser_uat_tier0_page_results` (NEW) — one row per
    `(execution, browser_channel, platform, url)`. Unique constraint on that
    tuple. `status IN ('pass','fail')`.
  - `browser_uat_tier0_viewport_results` (NEW) — one row per
    `(page_result, viewport)`. Field names deliberately match the M3 shared
    assertion module's own output exactly (`horizontal_overflow`,
    `critical_elements_outside_viewport`, `overlapping_elements`,
    `small_tap_targets`, `responsive_navigation`, `viewport_problems`,
    `tap_target_samples`), including its own `'passed'/'failed'` status
    vocabulary — deliberately distinct from the parent page result's
    `'pass'/'fail'`, so nothing gets silently remapped between what the
    browser actually returned and what's stored.
  - Migration `20260814_0023`, live-verified against the real dev Postgres:
    upgrade → both tables' shape matches the ORM exactly (confirmed via
    `\d`) → downgrade → clean removal, cascades correctly through the FK →
    re-upgrade → back at head.
- **Ingestion function**
  (`ingest_browser_uat_tier0_job_result` in `services/browser_uat_tier0.py`)
  takes ONE job's parsed JSON (the exact shape verified live in M2/M3, now
  pinned as a `TypedDict`) and writes/updates the normalized rows. Idempotent
  per page: re-ingesting the same job replaces that page's viewport rows
  rather than accumulating duplicates (a page is always re-checked as a
  whole unit, never one viewport at a time, so there's no finer natural key).
  Cascade-deletes correctly through execution → page → viewport (verified).
- **Explicitly NOT wired up yet:** `GitHubActionsTier0DispatchClient`'s
  artifact fetch is still the same documented M2 follow-up (no PAT available
  this session) — it currently needs to become "fetch ALL 3 artifacts for
  the run," not one, and call this ingestion function once per artifact.
  This function is ready and tested for that; the poll/finalize task doesn't
  call it yet.
- **Tests:** 9 new — 7 ingestion tests using fixture payloads that are the
  EXACT JSON captured from M3's live Chrome/Edge runs (not invented),
  covering fresh ingestion, multiple jobs per execution not colliding,
  idempotent re-ingestion (both no-duplication and stale-data replacement),
  and cascade delete; 2 workflow-contract tests for the new `platform`
  field. Full suite: 971 passed, 1 skipped (962 baseline + 9 new).

### M5 — Evidence → UAT-state mapping

- **Status:** SHIPPED (2026-08-14) for the desktop Tier 0 lane (Chrome +
  Edge). No new state was added — reused the existing five
  `UAT_VERIFICATION_STATES` exactly, no sign-off needed since nothing was
  added to the locked vocabulary.
- **Purpose:** The actual correctness-critical module — turn raw
  pass/fail/warning evidence into the existing five `UAT_VERIFICATION_STATES`
  without ever overclaiming. This is what finally lets
  `BRANDED_BROWSER_SCOPE` in `browser_compatibility.py` produce real
  `VERIFIED` entries.
- **A design shortcut found by re-reading the existing contract closely, not
  invented:** `BRANDED_BROWSER_SCOPE` already had an
  `actual_verified_environments: []` field on every entry — always empty,
  clearly intended for exactly this purpose but never populated. Using it
  meant **no row-count restructuring was needed at all** — the exact thing
  M1 explicitly deferred ("document now, restructure later") turned out not
  to require restructuring: `apply_tier0_evidence` populates that existing
  field with real per-platform sub-results while the row itself stays a
  single entry, whose own top-level `verification_state` is a computed
  roll-up over its `required_platforms`.
- **Roll-up rule, and why it matters:** a row reaches `VERIFIED` only when
  EVERY required platform has clean evidence. Concretely verified via test:
  Edge (`required_platforms = ["Windows 10/11"]`) reaches full `VERIFIED`
  from Tier 0's Windows-only evidence alone; Chrome
  (`required_platforms` = Windows + macOS + Android) caps at
  `PARTIALLY_VERIFIED` even with perfectly clean Windows+macOS evidence,
  because Android has no Tier 0 lane yet (Lane C, not built) — this is the
  "never claim an untested platform" rule enforced in code, not just prose.
  A platform that WAS tested and had real failures gets
  `PARTIALLY_VERIFIED` at the per-environment level too (distinct from
  simply-absent/untested), visible via `actual_verified_environments`'
  per-platform detail even though the row's single state string can't
  distinguish the two cases on its own.
- **Explicit, reviewable mapping tables, never fuzzy-matched:**
  `TIER0_PLATFORM_LABELS` (`"windows"` → `"Windows 10/11"`,
  `"macos"` → `"macOS 13+"`) and `TIER0_BROWSER_CHANNELS`
  (`"Google Chrome"` → `"chrome"`, `"Microsoft Edge"` → `"msedge"`) in
  `browser_compatibility.py`. An unrecognized platform code is silently
  skipped, never counted — tested explicitly.
- **Wired end to end:** `report_delivery.py`'s report-generation path now
  calls `fetch_latest_tier0_page_results(db, analysis_run_id=run.id)` —
  the MOST RECENT terminal-with-evidence Tier 0 execution for that analysis
  run (not a merge across every execution ever run, which could mix stale
  and fresh evidence) — and passes it into `_build_browser_uat_matrix`'s new
  optional `tier0_page_results` parameter. Omitting it (existing callers)
  behaves byte-identical to before — verified via the full existing
  `test_report_delivery.py`/`test_browser_compatibility.py` suites passing
  unchanged. Because reports are immutable snapshots, fresh Tier 0 evidence
  only ever appears in a NEW report generation (new idempotency key) — no
  retroactive mutation of frozen history, consistent with the locked
  immutability invariant.
- **Must reuse, not replace:** `browser_compatibility.py`'s existing state
  machine and labels. Confirmed — reused exactly.
- **Tests:** 12 new, all against real `BRANDED_BROWSER_SCOPE` data (not
  simplified fixtures) — the no-op cases (no evidence, wrong browser, Safari
  untouched), the Edge-reaches-VERIFIED and Chrome-caps-at-PARTIALLY_VERIFIED
  properties above, real-failure honesty, unrecognized-platform rejection,
  backward-compatible matrix building, and the DB-level "most recent usable
  execution" query (real SQLite, proving stale executions are correctly
  ignored in favor of fresher ones, and `unavailable` status is excluded).
  Full suite: 983 passed, 1 skipped (971 baseline + 12 new).

### M6 — Reporting & dev-team feedback loop

- **Status:** SHIPPED (2026-08-14), Action Plan integration for the desktop
  Tier 0 lane. Reporting-section integration (surfacing Tier 0 findings in
  the customer-facing Findings register, not just Action Plan) was NOT in
  scope — the plan doc's own language ("a device/browser failure becomes an
  action item") pointed specifically at the Action Plan system.
- **Purpose:** Make results actionable, not just stored.
- **A real architectural mismatch found before writing any code, not
  assumed:** `AnalysisFinding` (the table one would naively expect to
  populate) has a `UniqueConstraint(analysis_run_id, finding_code)` where
  `analysis_run_id` is actually a PER-PAGE `deep_analysis_run_id` (each
  Level-2-analyzed page gets its own `AnalysisRun`-shaped row) — Tier 0
  pages have no such per-page deep-analysis run at all, since M2 deliberately
  decoupled Tier 0 from the page-analysis pipeline. Materializing
  `AnalysisFinding` rows would have meant fabricating fake per-page analysis
  runs purely to satisfy an FK, which was rejected as architecturally
  dishonest. **Verified first that this decoupling was actually safe**: grepped
  every service file and confirmed `AnalysisFinding` is consumed ONLY by
  `action_generation.py` and `report_delivery.py` — never by
  `scoring_intelligence.py`/`priority.py` — so a parallel action-generation
  path bypassing `AnalysisFinding` entirely cannot perturb the locked Overall
  Score Formula.
- **Design: a parallel ENTRY POINT, not a parallel system.** New
  `generate_tier0_actions()` in `action_generation.py` reuses the exact same
  `ActionGroup`/`ActionItem`/`ActionStatusHistory` tables, the same
  `calculate_priority_score` formula (`priority_formula_version: "1.0.0"`,
  unchanged), the same grouping-key/status-history mechanics as the existing
  `generate_actions()` — just entered from Tier 0 evidence instead of a
  `PageAnalysisRun` loop, since Tier 0's execution shape (decoupled, raw-URL
  based) doesn't fit that function's iteration model.
- **4 new finding-code templates**, matching the existing content style and
  quality bar exactly (`why_this_matters`/`exact_correction`/
  `implementation_steps`/`verification_steps`/`expected_result`/
  `limitations`), added to the existing `FINDING_TO_ACTION_MAP` (not a
  separate map): `TIER0_HORIZONTAL_OVERFLOW`, `TIER0_CLIPPED_ELEMENTS`,
  `TIER0_OVERLAPPING_ELEMENTS`, `TIER0_SMALL_TAP_TARGETS` — one per M3
  structural-problem category. All `responsible_area: frontend`. The
  documented "21 deterministic codes" count in the product spec grows to 25
  as a result — a descriptive fact, not a locked invariant, confirmed no test
  pins the old count.
- **Page resolution, honestly bounded:** `ActionItem.website_page_id` is a
  real NOT NULL foreign key. New `_resolve_website_page()` matches a Tier 0
  page's raw URL against `WebsitePage.normalized_url`/`original_url`/
  `final_url`. When no discovered page matches, that page is counted as
  `insufficient_evidence` — never a fabricated page link — tested explicitly.
  A page failing the same check at multiple viewports (e.g. overflow at both
  Desktop and Mobile) becomes ONE action item, not one per viewport —
  `_tier0_recommendations()` dedupes by finding-code per page, tested.
- **Traceability without a schema change:**
  `ActionGenerationExecution.page_analysis_execution_id` is not a real
  foreign key (a bare indexed UUID column) and is reused to hold the Tier 0
  execution id — avoiding a migration — but every resulting group/item's
  `source_audit` is set to `"browser_uat_tier0"`, so Tier 0-derived actions
  are never confused with page-analysis evidence. Documented clearly in code
  comments given the field-name reuse could otherwise mislead a future reader.
- **New endpoint**: `POST /websites/{website_id}/action-plan/generate-tier0`
  (separate from `/generate`, not an overloaded parameter, since the two
  source pipelines are structurally different) — takes
  `browser_uat_tier0_execution_id`, 404s if unknown, mirrors the existing
  route's idempotency-key convention (a fresh `generation_execution_id` is
  minted per call, matching — not fixing — the existing `/generate` route's
  same pre-existing behavior, out of scope to change here).
- **Tests:** 12 new — page resolution (match/no-match), recommendation
  dedup and multi-problem generation, full `generate_tier0_actions`
  integration (group/item creation, idempotent replay, insufficient-evidence
  counting, unavailable-execution error, clean-page no-op), and the route
  (success + 404). Full suite: 995 passed, 1 skipped (983 baseline + 12 new).

### M7 — Logging & traceability

- **Status:** SHIPPED (2026-08-14). Confirmed to be genuinely a small audit,
  not a build — matching the module's own "no new logging system" scope.
- **Purpose:** Every matrix run traceable end-to-end using the SAME
  conventions established in `docs/PRODUCTION_OPERATIONS.md` §10 (request id
  → execution id → task id → result). No new logging system.
- **Audited first, not assumed:** grepped every M2–M6 file for `logger.` —
  found exactly ONE log line across the entire pipeline (a stub warning in
  the still-unimplemented artifact-fetch). Before treating this as a gap,
  checked what the ESTABLISHED convention actually is by reading
  `discovery.py`/`page_analysis.py`: `snake_case_event key=%s` at genuine
  failure/deadline points, `warning`/`info` level, NOT exhaustive per-line
  logging — and confirmed `real_analysis.py` (the MAIN pipeline) has ZERO
  explicit logger calls of its own either, relying on persisted DB state as
  the primary trace mechanism. This meant the real gap was narrower than
  "no logging exists": three specific failure/timeout branches in
  `worker_app/tasks/browser_uat_tier0.py` that silently write to the
  database with no corresponding log line, unlike their counterparts in
  `discovery.py`/`page_analysis.py`.
- **Added exactly 3 log statements**, matching the exact existing
  convention (not inventing a new one): `browser_uat_tier0_dispatch_unavailable`
  (both branches — missing website URL, and the dispatch client itself
  failing), `browser_uat_tier0_poll_unavailable`, and
  `browser_uat_tier0_poll_timeout` — each carrying `execution_id`. No
  "success" log lines added, consistent with the rest of the codebase not
  having them either (DB state is the success-path trace mechanism).
- **A genuine pre-existing test gap found and closed while auditing:** the
  poll task's `DispatchUnavailableError` branch (the dispatch client
  becoming unavailable mid-poll, not just at initial dispatch) had NO test
  coverage at all since M2 — added one.
- **`docs/PRODUCTION_OPERATIONS.md` §10 updated** with the parallel Tier 0
  trace path (`request_id → execution_id → browser-uat-tier0:{...}:dispatch
  task id → correlation_id → GitHub Actions run → page/viewport result rows
  → action items with source_audit="browser_uat_tier0"`), explaining why the
  happy path has no custom log lines (DB rows are the trace, matching how
  `real_analysis.py` already works).
- **Tests:** 1 new test (the closed pre-existing gap) + 2 existing tests
  extended with `caplog` assertions proving the new log lines actually fire
  with the right logger name and `execution_id`, not just eyeballed. Full
  suite: 996 passed, 1 skipped (995 baseline + 1 new).

### M8 — Scheduling / CI integration

- **Status:** Shipped 2026-08-14.
- **Purpose (as originally scoped):** Decide when this runs. Options: per
  customer analysis (likely too slow/expensive for a full matrix), on-demand,
  nightly regression against ZuiGO's own frontend, or gated to release
  branches. This decision was framed as gating a cost model, since
  real-device-lab minutes cost money per run.
- **Reframed after investigation:** the cost-model question was already
  answered by M1's GitHub Actions decision (free, unlimited minutes on this
  public repo — nothing to ration), and the trigger model was already
  decided in M2 (on-demand only, via `POST /analysis-runs/{id}/browser-uat/tier0`,
  decoupled from `full_website_analysis`). There was no scheduling cadence
  left to design. The real, un-shipped gap M8 needed to close was **admission
  control**: nothing stopped a website from accumulating unbounded concurrent
  Tier 0 executions, each dispatching 3 real GitHub Actions jobs — the same
  class of problem the main pipeline already solved for itself (CLAUDE.md:
  "don't launch parallel same-site acceptance runs").
- **Implementation:** `create_browser_uat_tier0_execution()` in
  `apps/api/app/services/browser_uat_tier0.py` now locks the `Website` row
  (`SELECT ... FOR UPDATE`, the same discipline as stage-ownership claims in
  `worker_app/tasks/real_analysis.py`) and refuses a genuinely NEW request
  with `409 BROWSER_UAT_TIER0_ALREADY_IN_FLIGHT` (+ `in_flight_execution_id`
  detail) if any `pending`/`running` execution already exists for that
  website on the same lane. Idempotency-key replays of an in-flight request
  still succeed unchanged (200, same execution) — only a distinct new request
  is blocked. A new request succeeds again once the prior one reaches any
  terminal status (`completed`, `failed`, `cancelled`, `unavailable`).
- **Tests:** new `TestAdmissionControl` class (4 tests: blocked while
  in-flight, a different website is never blocked, idempotent replay still
  succeeds while in-flight, a new request succeeds once terminal) in
  `tests/api/test_browser_uat_tier0.py`. One pre-existing test
  (`test_a_different_idempotency_key_creates_independent_history`) asserted
  behavior the new guard correctly forbids (two different idempotency keys
  both in flight simultaneously for the same website) — fixed by marking the
  first execution terminal before issuing the second, renamed to
  `..._once_the_first_finishes` to state what it now actually proves. Full
  suite: 1000 passed, 1 skipped (996 baseline + 4 new).

## 6. Assessment findings relevant to this initiative (from the 2026-08-14
   platform review — see chat history for full assessment)

- No frontend E2E browser suite currently exists for ZuiGO's own UI — if this
  initiative includes testing ZuiGO's own frontend (not just customer sites),
  that gap should likely be module M0 (not yet added — raise with user).
- The platform has no authentication/tenant isolation at all
  (`apps/api/app/api/routes/projects.py` takes no user context; zero matches
  for `user_id`/`owner_id`/JWT/OAuth anywhere in `apps/api/app`). This is
  **out of scope for this initiative** but noted here because a device/OS
  testing dashboard storing results would inherit the same lack of access
  control unless addressed separately.

## 7. Decision log

- **2026-08-14 — M1 scope:** Test target is customer-analyzed websites only.
  ZuiGO's own frontend E2E testing is explicitly out of scope for this
  initiative (real gap, tracked separately, not forgotten).
- **2026-08-14 — M1 evidence tier:** Hybrid — real-device cloud lab for
  Tier 0 (contract-critical, produces `VERIFIED`), simulators for Tier 2
  (fast regression, capped below `VERIFIED`).
- **2026-08-14 — M1 tablet handling:** Document tablet/iPad platforms now
  within the existing 3-row structure (done); defer actual per-form-factor
  verification-state splitting to M4/M5. See `browser_compatibility.py`
  `BRANDED_BROWSER_SCOPE` for the implemented change.
- **2026-08-14 — M1 cloud lab, SUPERSEDED same day:** initially decided
  BrowserStack; user rejected paying for a cloud lab. Corrected decision:
  **no paid vendor** — GitHub Actions hosted runners (repo confirmed public,
  unlimited free minutes) for real desktop Chrome/Edge/Safari; Firebase Test
  Lab + Samsung Remote Test Lab for real Android hardware; iOS/iPadOS stays
  honestly capped at `PARTIALLY_VERIFIED` via the free Simulator, with
  physical-hardware + GADS as a non-blocking future upgrade path pending an
  answer on spare Apple device availability.
- **2026-08-14 — M2 Lane A shipped:** on-demand
  `POST /analysis-runs/{id}/browser-uat/tier0` → Celery dispatch task →
  GitHub Actions (`browser-uat-tier0-desktop.yml`) runs real Chrome/Edge on
  Windows + real Chrome on macOS → poll task reschedules itself until the run
  completes → result written to the new `browser_uat_tier0_executions` table.
  Trigger model applied as a default (on-demand, decoupled from
  `full_website_analysis`) rather than formally re-confirmed via
  AskUserQuestion, since cost is no longer the constraining factor for a free
  GitHub Actions lane on a public repo.
- **2026-08-14 — M2 Lane B/C deferred:** Playwright cannot automate real
  Safari (confirmed via search — it only ships its own WebKit build); Firebase
  Test Lab needs a custom Appium test-harness APK to drive a URL in Chrome
  (it's an app-testing service, not a plain URL-checker); Samsung Remote Test
  Lab does support automation APIs (confirmed, not manual-only). Given this
  real complexity and no way to live-verify Selenium/safaridriver or an Appium
  harness in this session, Lane A shipped alone rather than building the
  higher-risk lanes untested.
- **2026-08-14 — M3 shipped:** DOM/structural assertions decided (matches
  existing codebase grain, no visual-diffing infrastructure exists anywhere
  in the pipeline). Fixed a real, previously-silent defect:
  `browser_compatibility.py`'s cross-engine runner had `viewport_problems`
  hardcoded to `[]`, so its classification logic could never see a real
  structural finding. Shared assertion module wired into that runner AND
  into M2's Tier 0 script. Found and fixed a genuine Node/Python Playwright
  API difference (`page.evaluate` with a string source silently returns
  `undefined` in Node) plus a second, independent bug in the first fix
  attempt (leading `//` comments + `return` = automatic-semicolon-insertion
  trap) — both root-caused via live minimal repros, not assumed, then
  verified end-to-end against real Chrome and real Edge before considering
  it done. 5th assertion (genuine cross-viewport nav adaptation) designed but
  not implemented — needs cross-viewport aggregation that doesn't fit either
  execution path's current per-call shape.
- **2026-08-14 — M4 shipped:** 3-level schema (execution → page result →
  viewport result), depth matched to `site_diagnostic_executions` but without
  its finding-deduplication semantics, which don't apply here. Surfaced and
  fixed a real gap: the Tier 0 workflow's 3 separate per-job artifacts had no
  way to be told apart once fetched (no `platform` field existed anywhere) —
  added one, keyed `browser_uat_tier0_page_results` by
  `(execution, browser_channel, platform, url)`. Migration live-verified
  (upgrade/downgrade round-trip against real Postgres). Ingestion function
  built and tested against the EXACT JSON M3 already proved live against
  real Chrome/Edge — but not yet called by the poll/finalize task, since
  that's still gated on the same artifact-fetch follow-up flagged in M2.
- **2026-08-14 — M5 shipped:** reused `BRANDED_BROWSER_SCOPE`'s existing
  (always-empty) `actual_verified_environments` field rather than
  restructuring the locked 3-row matrix — the tablet/phone-split
  restructuring M1 deferred here turned out to be unnecessary for the
  desktop lane specifically. Roll-up rule: a row reaches `VERIFIED` only
  when every `required_platforms` entry has clean evidence, verified by test
  that Edge (Windows-only requirement) CAN reach full `VERIFIED` from Tier 0
  alone while Chrome (needs Android too) cannot, ever, until Lane C exists.
  Wired into `report_delivery.py`'s report-generation path via
  `fetch_latest_tier0_page_results`; backward-compatible (existing tests
  unchanged) when no Tier 0 evidence exists for an analysis run.
- **2026-08-14 — M6 shipped:** rejected materializing Tier 0 problems as
  `AnalysisFinding` rows after finding that table's per-page
  `deep_analysis_run_id` scoping doesn't fit Tier 0's decoupled, raw-URL
  execution shape (would have required fabricating fake per-page analysis
  runs). Verified first (grep, not assumed) that `AnalysisFinding` is never
  consumed by any scoring service, confirming a bypass path is safe. Built
  `generate_tier0_actions()` as a parallel entry point reusing the exact
  same `ActionGroup`/`ActionItem` tables and priority formula. 4 new
  finding-code templates added to the existing `FINDING_TO_ACTION_MAP`
  (grows 21 → 25, a descriptive count, not locked). New route
  `POST /websites/{id}/action-plan/generate-tier0`.
- **2026-08-14 — M7 shipped:** audited before building — found the pipeline
  had exactly one log line total, but also found `real_analysis.py` (the
  MAIN pipeline) has zero explicit logging too, so "no logging" wasn't
  automatically a gap. Real gap was narrower: 3 failure/timeout branches
  with no matching log line, unlike their `discovery.py`/`page_analysis.py`
  counterparts. Added exactly those 3, matching the existing
  `snake_case_event key=%s` convention precisely. Found and closed a
  pre-existing test gap (poll's `DispatchUnavailableError` branch, untested
  since M2) while auditing. Updated `PRODUCTION_OPERATIONS.md` §10 with the
  parallel Tier 0 trace path.
- **2026-08-14 — M8 shipped, reframed from its original scope:** the
  "scheduling cadence" question wasn't actually open — M1 already made Tier 0
  free (GitHub Actions, public repo) and M2 already fixed the trigger model
  (on-demand only). The real un-shipped gap was admission control: no bound
  existed on concurrent in-flight Tier 0 executions per website. Fixed with a
  `Website`-row-locked check-then-insert in
  `create_browser_uat_tier0_execution()`, refusing a new (non-replay) request
  with `409 BROWSER_UAT_TIER0_ALREADY_IN_FLIGHT` while one is already
  pending/running for that website. See the M8 entry above for full detail.
- **2026-08-15 — M2 Lane B (desktop Safari) shipped:** added as a 4th job to
  the existing `browser-uat-tier0-desktop.yml` workflow, reusing Lane A's
  entire dispatch/poll/schema/evidence-mapping pipeline unmodified because
  Lane B's output JSON deliberately matches Lane A's `JobResultPayload`
  contract exactly — the only backend change needed was one line
  (`TIER0_BROWSER_CHANNELS["Apple Safari"] = "safari"`). Real Selenium
  toolchain (`selenium-webdriver`, not Playwright), API surface verified
  against the actually-installed npm package (not guessed). Feasibility risk
  cited: GitHub-hosted macOS runners had a confirmed 2025 TCC-permission
  regression blocking Safari automation, officially fixed
  (actions/runner-images#12752) about a year before this build — proceeding
  on that fix's strength, but not live-verified this session (no macOS
  environment, no PAT). See the M2 entry above for the three deliberate
  WebDriver-protocol limitations (null http_status, unmeasured
  console_error_count, measured-not-assumed viewport size) this lane
  documents rather than fakes.
- **2026-08-15 — Lane C (Android) shipped, initially proposed as design-only
  then rebuilt on user clarification:** first investigated Firebase Test Lab
  and Samsung Remote Test Lab, found neither cleanly fits the fully-automated
  GitHub-Actions-dispatch model, and proposed stopping at design-only rather
  than shipping unverifiable Android/Gradle code. User clarified the actual
  bar was "most capable free option, flexible on how much can be
  live-verified this session, never spend money" — not a hard requirement
  for full automation. That reframing led to the real chosen approach:
  ChromeDriver's official native Android support
  (`chrome.Options().androidChrome()`), which reuses Lane A/B's existing
  Selenium tooling and the shared JS assertion module directly (real DOM
  assertions, not Firebase's accessibility-tree-only alternative) over a
  plain `adb` connection — manually triggered (`scripts/browser_uat_tier0_check_android.mjs`
  + `scripts/ingest_manual_tier0_result.py`) since no free provider offers
  live adb access from an unattended CI runner. One line added Android to
  M5's evidence mapping (`TIER0_PLATFORM_LABELS["android"]`) — Chrome's last
  missing required platform, so Chrome can now reach full VERIFIED for the
  first time. A real bug (wrong UUID column — execution.execution_id vs
  execution.id) was caught by the new tests before it shipped, not after.
  See the M2 entry above for full detail, including what's still
  unverified (no real device run yet this session).
- **2026-08-15 — iOS/iPadOS Simulator Safari lane shipped:** unlike Lane C,
  this one IS fully automatable — GitHub-hosted macOS runners already ship
  Xcode with Simulator runtimes preinstalled, and Appium's official Safari
  driver documents exact, unambiguous iOS Simulator capabilities (much
  clearer than Android/Firebase's contradicted-by-official-docs situation).
  Added as a 5th job (`ios-safari-simulator`, matrixed over
  `device_type: [iPhone, iPad]`) to the SAME `browser-uat-tier0-desktop.yml`
  workflow Lane A/B use — reuses the same `selenium-webdriver` client,
  pointed at a local Appium server instead of a local browser process. Two
  lines added to M5's evidence mapping (`TIER0_PLATFORM_LABELS["ios"]`,
  `["ipados"]`) — Safari's last two missing required platforms, so Safari
  can now reach full VERIFIED too. Real, cited risk: iOS Simulator JS
  execution via Appium/WebDriverAgent has a documented history of
  version-dependent reliability issues (appium/appium#8735, #1791) — the
  single largest unverified assumption in this lane. See the M2 entry above
  for full detail.
- **2026-08-15 — Artifact-fetch wiring shipped:** `GitHubActionsTier0DispatchClient`'s
  stubbed `_fetch_results_artifact` (M2, always returned `None`) is now real
  — lists a run's artifacts, downloads/unzips/parses each one via `httpx`
  (already a worker dependency, chosen specifically because GitHub's
  artifact-download endpoint redirects to a different host and httpx
  correctly strips the `Authorization` header on that cross-origin hop,
  verified with a local `httpx.MockTransport` repro before relying on it).
  `Tier0PollResult.results` changed from `dict | None` to `list[dict] | None`
  since a run produces up to 6 artifacts, not one. Wired into
  `poll_browser_uat_tier0`: every parsed artifact now actually calls
  `ingest_browser_uat_tier0_job_result` (existed and was tested since M4,
  never called from the real task before this). M6's action generation
  (`generate_tier0_actions`) can now genuinely trigger off real GitHub
  Actions evidence, not just manually-ingested Lane C/synthetic-test rows.
  See the M2 entry above for full detail.
- **2026-08-15 — M3's 5th check (`responsive_navigation_adapts`) shipped:**
  the cross-viewport-comparison architectural constraint that originally
  deferred this was solved by splitting the work: two new raw per-viewport
  fields in the shared JS module (`nav_visible_item_count`,
  `has_navigation_toggle`, still one self-contained page.evaluate() call
  each), and a new pure Python comparison function
  (`compute_responsive_navigation_adapts`) run once per page+engine over
  the Desktop+Mobile pair — no architecture change to
  `browser_compatibility.py`'s one-viewport-per-run-call model was needed
  after all. Live-verified against real Chromium with two crafted fixtures
  (an adapting nav with a hamburger toggle, and a static nav) before
  trusting the Python-side comparison logic. Wired into
  `run_compatibility_analysis`'s real matrix output, per engine. See the M3
  entry above for full detail.
- **2026-08-15/16 — Live GitHub PAT configured and used for real
  verification:** confirmed the token/permissions/repo access all work
  correctly (`Actions: Read and write`, fine-grained, scoped to this one
  repo). 5 real dispatches run against `fluidcontrols.com` via the actual
  product API route. Found and fixed 2 unrelated real bugs this surfaced
  (`actions/setup-node@v6`'s default npm-cache behavior; an empty-string
  vs `None` token-check gap in `_build_dispatch_client`, both with their
  own regression tests). Confirmed Lane A/B (Chrome/Edge/desktop-Safari)
  and the iOS Simulator lane's iPhone target all work end-to-end for real
  — genuine branded browser versions, genuine structural findings on a
  real customer site, correct ingestion into the DB every time.
- **2026-08-16 — iPad Simulator Safari marked a known, pending limitation:**
  after 4 consecutive real failures (2 distinct error types) and 3 targeted
  fixes (boot the simulator explicitly; pre-launch Safari before Appium's
  session creation; prefer a lighter non-"Pro" device + longer settle
  window) that did not resolve it, searched GitHub's issue tracker
  directly for the exact error text and for "RWIApplication" + iPad —
  zero hits anywhere, meaning this isn't a known community bug with an
  established fix. Decided to stop iterating rather than keep guessing at
  real cost with no external validation. No code change needed to "mark"
  this — missing evidence for one platform already degrades gracefully
  (Safari caps at `PARTIALLY_VERIFIED` without `ipados` evidence, exactly
  as designed). The job stays in the workflow, attempting and visibly
  failing each run rather than being silently skipped, so it can be
  revisited later. Full findings and all 4 dispatch outcomes are in the
  iOS lane's own M2 entry above.
- **2026-08-14 — Not yet decided:** interaction_failures/
  accessibility_differences in the cross-engine runner (confirmed also
  hardcoded empty, deliberately not touched — bigger scope than M3); the
  TRUE per-form-factor (phone vs tablet) verification split — still
  deferred, now moot everywhere except Lane C's phone-only Android coverage
  (no Android tablet lane exists); whether Tier 0 findings should also
  surface in the customer-facing Findings register (report_delivery.py),
  not just the Action Plan — explicitly out of scope for M6 as written; a
  real end-to-end run of Lane C specifically (Android hardware still not
  available); revisiting the iPad Simulator gap if this ever becomes a
  documented, better-understood Appium issue.

## 8. Current real-world version snapshot (illustrative, re-derive at
   execution time — do not hardcode)

Verified via web search 2026-08-14 (see chat history for full source list;
not present in training data, so these were looked up, not estimated):

- Chrome latest-2-stable: 151 (2026-07-29), 150 (2026-06-30).
- Edge latest-2-stable: 151 (2026-08-10), 150 (prior).
- Safari (floor requirement, not latest-2): 26.6 (2026-07-27).
- iOS/iPadOS latest-2-major: 26 (current, 26.6.1 in beta), 18 (previous —
  Apple's 2025 renumbering skipped 19–25 to align with calendar year).
- Android latest-2-major: 17 (current, Aug 2026 patch), 16 (previous).

## 9. How to resume this work in a new session / different LLM

1. Read §2 in order.
2. Read this file's §5 module table and §7 decision log to see what's already
   been decided vs. still open.
3. Do not implement a module whose status is still "Not started" without
   discussing its open questions with the user first — this was an explicit,
   repeated instruction.
4. Any new capability must stay inside the 8-agent/15-tool/3-workflow
   registry constraint (§4) — verify against
   `docs/MULTI_AGENT_ARCHITECTURE.md` before adding anything that looks like
   a new agent.
5. Update this file's module statuses and §7 decision log as you go. This
   file, not chat history, is the durable record.

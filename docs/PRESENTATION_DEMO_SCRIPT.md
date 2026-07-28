# ZuiGO Presentation Demo Script

This script presents the deterministic local demonstration. It does not crawl a
public website, call a public API, or use an LLM. Every conclusion shown in the
prepared report is labelled as synthetic demonstration evidence.

## Before the audience arrives

1. Start PostgreSQL, Redis, the API, worker, and web application.
2. Open `http://localhost:3000/presentation`.
3. Select **Open Prepared Demo Report** once.
4. Confirm that the screen shows `76/100`, confidence `88%`, evidence coverage
   `15/16 (93.75%)`, eight agents, and HTML/PDF/JSON exports.
5. Download one export and confirm that it opens. Return to presentation mode.
6. Select **Reset Demo**, then leave the clean presentation screen open.

Confirm the report controls show **Export Presentation PDF**, **Open Full
Report**, **Export Technical Appendix**, **Download Evidence JSON**, and
**Download Page Inventory JSON**.

## Suggested five-to-seven-minute narrative

### 1. Frame the product (45 seconds)

ZuiGO turns retained website and repository evidence into explainable findings,
scores, actions, and reports. The visible separation between score, confidence,
and coverage prevents a polished report from overstating incomplete evidence.

### 2. Run the one-click journey (90 seconds)

Select **Run Demo Analysis**. Point out the workflow:

1. Discovery builds the bounded inventory.
2. Performance, accessibility, and site diagnostics run as a visible parallel
   group.
3. Evidence validation checks provenance and prerequisites.
4. Repository intelligence maps evidence when a repository is configured.
5. Remediation creates evidence-linked actions.
6. Report assembles the versioned output and exports.

The demonstration is a deterministic local fixture; the movement is a
presentation of the persisted workflow contract, not a live public crawl.

### 3. Explain the result (90 seconds)

Call out:

- overall score `76/100`;
- score confidence `88%`, shown separately;
- evidence coverage `15/16 (93.75%)`;
- the unavailable CrUX field-evidence state, which is not displayed as passed;
- each of the eight reusable agents and its retained contribution.

Open **Pages** and explain that discovered, visited, and successfully analysed
are different states. The prepared fixture shows 12 discovered URLs, 10
scheduled pages, 9 visited pages, and 7 successfully analysed pages (7/10,
70%). Failed, skipped, excluded, redirected, duplicate-normalised, and
incomplete-evidence counts remain visible.

Open **Browser Compatibility** and identify the tests as Playwright Chromium,
Firefox, and WebKit engine tests at 1440 x 900 and 390 x 844. Point out the
WebKit checkout failure and the explicit limitation that branded browser
versions are not being claimed.

Overall Score Formula v1.0.0 deterministically combines the available category
scores using the configured weights; unavailable evidence affects coverage and
confidence rather than being invented. Priority Formula v1.0.0 ranks actions
from retained severity, affected scope, confidence, effort, and impact inputs.
Neither formula is calculated or modified by an LLM.

Use these one-line agent descriptions:

- **Discovery Agent:** builds the bounded, normalized page inventory.
- **Performance Agent:** keeps laboratory, browser, and field evidence distinct.
- **Accessibility Agent:** identifies automated findings and manual-review needs.
- **Site Diagnostics Agent:** detects cross-page, template, link, and metadata
  patterns from persisted evidence.
- **Evidence Validation Agent:** verifies provenance, coverage, and prerequisites.
- **Repository Intelligence Agent:** maps validated evidence to approved code.
- **Remediation Agent:** creates evidence-linked fixes and verification guidance.
- **Report Agent:** assembles the versioned report and exports.

### 4. Trace evidence to action (90 seconds)

Open a top finding. Show its page URL, severity, evidence state, explanation,
impact, owner, remediation, and verification. Then move to the priority Action
Plan and show the corresponding action, priority score, responsible role, and
verification method.

### 5. Use the report (90 seconds)

Show the embedded report navigation, finding filters, exact occurrences,
evidence references, agent attribution, partial-evidence label, and the
HTML/PDF/JSON export actions. Explain that each artifact has a stable safe
filename and retained SHA-256 checksum.

### 6. Close on safety and history (45 seconds)

The same presentation key safely reuses its execution. A different key preserves
independent history. If a live demo fails, that execution remains failed and the
screen clearly opens the last verified prepared report as a fallback.

## Exact screen and click sequence

1. Open `/presentation` from the home-page **Open presentation mode** link.
2. Select **Run Demo Analysis**.
3. Read the progress region and point to the parallel stage.
4. Move through **Top findings** and **Priority action plan**.
5. Use the embedded **Prepared report viewer** navigation.
6. Select **Download PDF**, then mention the HTML and JSON alternatives.
7. Open **Technical Details** and point out the separate appendix, evidence
   JSON, and page-inventory JSON exports.
8. For the fallback rehearsal, use the previously prepared browser/session and
   select **Open Prepared Demo Report** if live services are unavailable.
9. Select **Reset Demo** after the rehearsal.

## Prepared fallback wording

If the screen displays **Prepared fallback report**, say:

> The live execution did not complete and remains recorded as failed. To keep
> the presentation useful, ZuiGO is showing the last verified prepared local
> report. It is not presenting the failed execution as successful.

Do not describe synthetic evidence as a real customer result, automated
accessibility evidence as full compliance, laboratory performance as field
performance, or canonical evidence as proof of search-engine indexing.

## Likely audience questions

**Are the agents autonomous?**
No. Eight versioned domain agents run inside a validated deterministic workflow
with explicit tools, permissions, dependencies, timeouts, and evidence rules.

**Does an LLM calculate the score?**
No. Overall Score Formula v1.0.0 is deterministic. Confidence and coverage are
separate, and an LLM cannot change the score.

**Is this a real website result?**
No. Presentation mode uses a local synthetic fixture so the demonstration is
reliable and internet-independent. Production analysis retains real collected
evidence with the same contracts.

**Does the accessibility score prove compliance?**
No. Automated checks identify evidence and manual-review needs; they cannot
establish complete accessibility compliance.

**What happens when evidence is missing?**
It is marked incomplete or unavailable and reduces visible coverage. It is never
silently treated as a passed check.

**Can the report be shared?**
Yes. The report is available as accessible HTML, professional paginated PDF, and
structured JSON, each with a stable filename and SHA-256 checksum.

**How does the Action Plan help delivery teams?**
It ranks evidence-linked work and keeps the owner, expected impact, effort,
dependencies, remediation, and verification together.

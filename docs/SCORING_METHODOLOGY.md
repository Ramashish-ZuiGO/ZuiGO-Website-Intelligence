# Scoring methodology

## Formula version 1.0.0

The report uses five independently measured categories. Performance, Accessibility,
Best Practices, and SEO use the integer scores reported by Lighthouse. Technical
Quality starts at 100 and uses only verified Playwright or HTTP findings.

| Category | Weight |
| --- | ---: |
| Performance | 25% |
| Accessibility | 20% |
| Best Practices | 15% |
| SEO | 20% |
| Technical Quality | 20% |

The overall score is the weighted sum and is rounded to the nearest integer using
round-half-up. If a category is unavailable, its value is not fabricated. The
remaining weights are divided by their available-weight total before calculation.

## Technical Quality deductions

| Severity | Deduction |
| --- | ---: |
| Critical | 25 |
| High | 15 |
| Medium | 8 |
| Low | 3 |
| Informational | 0 |

Each stable finding code can be deducted once. Lighthouse findings are excluded
because their impact is already represented in the four Lighthouse category scores.
The final Technical Quality score is constrained to 0–100.

## Confidence

Confidence measures report completeness, not website quality:

- 60 points: 15 for each available Lighthouse category.
- 25 points: proportional availability of the 15 documented Playwright measurements.
- 10 points: successful HTTP status from 200 through 399.
- 5 points: the full audit and scoring lifecycle completed.

The result is rounded using the same round-half-up rule. Missing evidence reduces
confidence rather than creating substitute values.

## Page-level scoring

Page-level scores are available only for pages that received Level 2 (Lighthouse) analysis.
A page score uses the same formula version 1.0.0 as the site score when Lighthouse
categories are available. If only Level 1 analysis was performed, no page-level score is
computed — the report displays "unavailable" or "—/100" rather than fabricating a value.

Page scores are clearly distinguished from the site score:

- **Site score**: the overall analysis-run score for the homepage or primary URL.
- **Page score**: a per-page score for pages that received Level 2 deep analysis.
- **Category score**: a per-category breakdown for pages with Lighthouse data.
- **Coverage**: the percentage of eligible pages that received Level 1 analysis, not a
  quality metric.
- **Confidence**: reported separately from score for each page (high, medium, low, or
  unavailable).

Missing data is never averaged as zero. If insufficient evidence exists, the score is
marked unavailable or partial.

## Reproduction

Use the stored formula version, original category scores, original weights,
available/unavailable category lists, deduction records, and calculation details.
Deduct each eligible unique finding from 100, normalize weights across available
categories, calculate the weighted mean, and apply the documented rounding rule.

## Separate diagnostic scores

The following scores use their displayed diagnostic formula version independently. They are
labelled ZuiGO-derived and never contribute to overall scoring formula 1.0.0. Each starts at
100 and is constrained to 0–100 after the documented deductions.

### ZuiGO Markup Standards Score

- Deduct 5 points per verified W3C validation error, capped at 75.
- Deduct 1 point per verified warning, capped at 25.
- Confidence is 100 when the validator returns valid structured output and 0 when
  unavailable. This is not an official W3C score.

### Cache Efficiency Score

- Deduct 10 when HTML has neither an explicit cache policy nor a validator.
- For each bounded first-party static-resource sample, deduct 8 when cache metadata
  and validators are absent, or 4 when `max-age` is below one hour.
- At most ten resource deductions are applied. Explicit `no-store` is not treated as
  a short-lifetime failure. Confidence is `min(100, 20 + 16 × sampled resources)`.

When no static resource is sampled, the deterministic HTML-only result is retained
for reproduction but its status is `partial`, evidence completeness is `html_only`,
and the UI labels the score provisional. A truncated bounded sample is also partial.
This changes qualification, not cache formula 1.0.0.

### Page Security Posture Score 1.1.0

- Missing CSP: 20; weak CSP: 10; missing HSTS on HTTPS: 15.
- Missing frame protection: 10; missing `nosniff`: 10.
- Mixed content: 20; exposed `Server` or `X-Powered-By`: 5.
- Confidence is 90 when the main response and page observations are available.

This passive security posture score is not a penetration-test result and does not
prove the absence of vulnerabilities.

Security diagnostic formula 1.1.0 classifies CSP as `absent`, `upgrade_only`, `weak`,
`moderate`, or `strong`. An `upgrade-insecure-requests`-only policy receives the weak-policy
deduction because it does not restrict content sources. Weak also covers wildcard sources,
`unsafe-eval`, or unmitigated `unsafe-inline`. Moderate requires useful source restrictions
but lacks one or more key hardening directives. Strong requires restrictive source controls
without those unsafe expressions plus `object-src`, `base-uri`, and `frame-ancestors`.
This diagnostic-only version change does not affect overall formula 1.0.0.

### Responsive Design Score

- Deduct 20 for each failed tested viewport.
- Deduct 10 for horizontal overflow in each tested viewport.
- Deduct 15 when the viewport meta tag is absent.
- Confidence is the percentage of configured Chromium viewports successfully tested.

Tap targets are measured against a 24 by 24 CSS-pixel threshold. Targets smaller in either
dimension are informational when the target's expanded 24-pixel exclusion area does not
overlap another interactive target; otherwise they are confirmed usability observations.
Hidden and zero-size elements are excluded. Tap-target observations do not create deductions
in responsive formula 1.0.0, so the report explains them separately.

### Lighthouse interpretation context

Reports retain Lighthouse and Chromium versions when available, mobile/desktop form factor,
throttling method, screen emulation, audit timestamp, and a bounded list of failed or manual
audits. Time to Interactive is retained as a legacy supplementary metric: it is not a
current Core Web Vital and is not necessarily part of the Lighthouse performance score.
Lighthouse accessibility is automated evidence only; a score of 100 does not establish
complete accessibility compliance and manual testing remains required.

### Technology detection

Next.js detection uses bounded, verified indicators such as `/_next/` assets,
`__NEXT_DATA__`, build identifiers, framework root markers, and relevant response headers.
A framework-specific or corroborated signal returns `detected`; a lone weak asset-path or
DOM signal returns `uncertain`; no observed indicators returns `not_detected`.

Privacy Policy Freshness is a non-numeric indicator: current means an explicit date
is no more than 365 days old, stale means older than 365 days, and unknown means no
reliable explicit date was found. Copyright currency and the tested-browser matrix are
also non-numeric. Firefox and WebKit remain explicitly not tested in Task 015.

## Priority Formula v1.0.0

The Priority Formula is a separate deterministic formula (0-100) used by the
Actionable Remediation Engine to score action items. It does not modify the
Overall Score Formula v1.0.0, overall scores, page scores, category scores,
confidence, or any diagnostic scoring formula.

### Inputs

| Input | Type | Values |
|---|---|---|
| `severity` | string | `critical`, `high`, `medium`, `low`, `informational` |
| `affected_page_count` | integer | number of pages affected by the issue |
| `estimated_score_impact` | integer | 0-100, estimated improvement if fixed |
| `confidence_percent` | integer | 0-100, evidence-confidence percentage |
| `implementation_effort` | string | `low`, `medium`, `high`, `very_high` |
| `business_impact` | string | `critical`, `major`, `moderate`, `minor`, `negligible` |

### Component weights

1. **Severity base** (0-35): `critical`=35, `high`=25, `medium`=15, `low`=5, `informational`=0
2. **Affected pages** (0-25): ≥50 pages=25, ≥20=20, ≥10=15, ≥5=10, ≥2=5, 1 page=0
3. **Score impact** (0-15): `round(score_impact / 100 * 15)`, clamped to 0-15
4. **Confidence** (0-10): ≥90%=10, ≥70%=7, ≥50%=5, ≥30%=3, ≥10%=1, <10%=0
5. **Effort penalty** (0-15, inverted — lower effort = higher priority): `low`=15, `medium`=10, `high`=5, `very_high`=0
6. **Business impact boost** (0-15): `critical`=15, `major`=10, `moderate`=6, `minor`=3, `negligible`=0

### Formula

```
raw = severity_base + pages_score + impact_score + confidence_score
      - effort_penalty + business_boost
priority = max(0, min(100, raw))
```

Clamped to 0-100. Missing or unknown inputs default to zero instead of failing.

### Missing-evidence and default behaviour

- Unknown severity, effort, or business impact: component defaults to 0.
- `confidence_percent` out of range: clamped to 0-100 before scoring.
- `estimated_score_impact` out of range: clamped to 0-100 before scoring.
- `affected_page_count` less than 1: pages score defaults to 0.

### Representative calculation

Input: severity=critical (35), pages=12 (15), score_impact=60 (round(60/100*15)=9),
confidence=85 (7), effort=low (15), business_impact=major (10)

```
raw = 35 + 15 + 9 + 7 + 15 + 10 = 91
Privacy Policy Freshness is a non-numeric indicator: current means an explicit date
is no more than 365 days old, stale means older than 365 days, and unknown means no
reliable explicit date was found. Copyright currency and the tested-browser matrix are
also non-numeric. Firefox and WebKit remain explicitly not tested in Task 015.

## Priority Formula v1.0.0

The Priority Formula is a separate deterministic formula (0-100) used by the
Actionable Remediation Engine to score action items. It does not modify the
Overall Score Formula v1.0.0, overall scores, page scores, category scores,
confidence, or any diagnostic scoring formula.

### Inputs

| Input | Type | Values |
|---|---|---|
| `severity` | string | `critical`, `high`, `medium`, `low`, `informational` |
| `affected_page_count` | integer | number of pages affected by the issue |
| `estimated_score_impact` | integer | 0-100, estimated improvement if fixed |
| `confidence_percent` | integer | 0-100, evidence-confidence percentage |
| `implementation_effort` | string | `low`, `medium`, `high`, `very_high` |
| `business_impact` | string | `critical`, `major`, `moderate`, `minor`, `negligible` |

### Component weights

1. **Severity base** (0-35): `critical`=35, `high`=25, `medium`=15, `low`=5, `informational`=0
2. **Affected pages** (0-25): ≥50 pages=25, ≥20=20, ≥10=15, ≥5=10, ≥2=5, 1 page=0
3. **Score impact** (0-15): `round(score_impact / 100 * 15)`, clamped to 0-15
4. **Confidence** (0-10): ≥90%=10, ≥70%=7, ≥50%=5, ≥30%=3, ≥10%=1, <10%=0
5. **Effort penalty** (0-15, inverted — lower effort = higher priority): `low`=15, `medium`=10, `high`=5, `very_high`=0
6. **Business impact boost** (0-15): `critical`=15, `major`=10, `moderate`=6, `minor`=3, `negligible`=0

### Formula

```
raw = severity_base + pages_score + impact_score + confidence_score
      - effort_penalty + business_boost
priority = max(0, min(100, raw))
```

Clamped to 0-100. Missing or unknown inputs default to zero instead of failing.

### Missing-evidence and default behaviour

- Unknown severity, effort, or business impact: component defaults to 0.
- `confidence_percent` out of range: clamped to 0-100 before scoring.
- `estimated_score_impact` out of range: clamped to 0-100 before scoring.
- `affected_page_count` less than 1: pages score defaults to 0.

### Representative calculation

Input: severity=critical (35), pages=12 (15), score_impact=60 (round(60/100*15)=9),
confidence=85 (7), effort=low (15), business_impact=major (10)

```
raw = 35 + 15 + 9 + 7 + 15 + 10 = 91
priority = min(100, max(0, 91)) = 91
```

### Formula version

The version string `1.0.0` is stored on every action item and action group.
The `priority_components` JSONB column stores each component value and the raw
total for audit and reproduction.

## Metric Registry and Presentation

While the mathematical formulas (Overall Score Formula v1.0.0, Priority Formula v1.0.0)
and diagnostic deductions remain strictly separated and unchanged, the presentation
of these metrics is governed by a centralized Metric Registry.

The API exposes the definitions at `/api/v1/metadata/metrics`.
This ensures a consistent, accessible, and reusable metric-presentation system:

- Every metric has a canonical `metric_id` (e.g., `priority_score`, `analysis_coverage_percent`).
- Every metric has a `metric_type` (`score`, `percentage`, `count`, `duration`, `status`) dictating its formatting.
  - `score`: always uses `x/100` formatting. Never presented as a percentage.
  - `percentage`: uses `%`.
- Every metric definition includes:
  - what it measures
  - how it was calculated
  - which evidence produced it
  - whether higher or lower is better
  - which methodology applies
  - limitations

All frontend UI components (such as `WebsiteAnalysisPanel` or `ActionPlanPanel`)
consume these definitions to provide interactive, accessible explanations rather
than duplicating metric explanations in multiple places.


### Threshold Profiles

Starting with v1.0.0, the calculation of scores remains deterministic, but the **interpretation** of those metrics (i.e. Good, Needs Improvement, Poor) is governed by Threshold Profiles.

Four primary profiles are included:
- **Global General**: Standard Lighthouse interpretations
- **India General**: General standards optimized for Indian user bases
- **India Government**: Strict GIGW 3.0 adherence
- **Enterprise**: High-availability, ultra-strict web performance thresholds

When evaluating a metric, the system looks up the threshold rule defined in the assigned profile. The resulting `MetricInterpretation` includes the rating, the exact thresholds used, and limitations.

### Metric Registry Version: 1.0.0
Exact Metric Count: 86
Supported Value Types: score, percentage, count, duration, bytes, ratio, boolean, status, text, unavailable.
Endpoints: GET /api/v1/metadata/metrics, GET /api/v1/metadata/metrics/{metric_id}
Score/Percentage distinction: Scores are x/100, Percentages are %.
Accessibility: Components are fully accessible (focus, Enter/Space/Escape) without relying solely on hover.
Limitations: Screen-reader users may require manual tests for complex aria-label tables.

### Modern Performance Intelligence

- **Field vs Lab Separation**: Field evidence (CrUX) and Lab evidence (Lighthouse) are distinct. Missing field data is never averaged as zero, and lab values are never substituted for missing field values.
- **Disagreement Indicator**: Comparisons are made between Field and Lab metrics. If they differ materially, a disagreement indicator is provided, but this NEVER alters the Overall Score Formula v1.0.0 or Priority Formula v1.0.0.
- **History and Profiles**: Historical analyses are preserved, and threshold profiles are applied without modifying raw values.

## Site-diagnostic metrics and deterministic grouping

Site-wide diagnostics add 12 presentation metrics to both registries:
`site_diagnostic_finding_count`, `sitewide_finding_count`,
`template_finding_count`, `isolated_page_finding_count`,
`internal_broken_link_count`, `orphan_page_count`, `dead_end_page_count`,
`canonical_conflict_count`, `duplicate_title_group_count`,
`duplicate_description_group_count`, `near_duplicate_page_group_count`, and
`site_diagnostic_coverage_percentage`. Counts are observations, not scores. Coverage is
`evidence_coverage_numerator / evidence_coverage_denominator * 100` and must always be
presented with its numerator and denominator.

The 31-rule registry assigns severity, scope, remediation, responsible role, and
verification guidance independently of score calculation. Exact content grouping uses
normalized text with `sha256-normalized-text-v1`. Near-duplicate grouping uses
`token-set-jaccard-v1`, a similarity threshold of `0.85`, at least 80 usable characters,
and at least two affected pages. Repeated, section, and template classifications are
deterministic; template scope is not used when the evidence supports repetition only.

Missing link, content, canonical, indexability, or technical evidence is represented as
partial or unavailable. It is never assigned a zero issue count as a substitute for
evidence. Link-graph results are limited to persisted internal-link evidence, and
canonical/indexability diagnostics describe technical signals rather than real
search-engine indexing.

Site-diagnostic findings can supply original evidence references to the Action Plan, but
the workflows retain separate execution history and idempotency. None of the 12 metrics,
31 rules, deterministic clusters, or Action Plan references changes Overall Score
Formula v1.0.0 or Priority Formula v1.0.0.

## Multi-agent orchestration and scoring

The eight-agent, fifteen-tool platform coordinates existing evidence-producing
services through three versioned deterministic workflows. Agent status, workflow
progress, retry attempts, tool availability, evidence counts, checkpoints, token
totals, and provider costs are operational metadata. They are not score inputs,
deductions, confidence replacements, or substitute evidence.

Partial, failed, cancelled, and unavailable agent states remain explicit and do
not become zero-valued measurements. Deterministic LLM fallback does not invent a
score or evidence. Remediation and report agents may reference existing findings
and their published scoring components, but orchestration cannot recalculate or
silently alter them.

Consequently, Task 026 makes no mathematical or version change to Overall Score
Formula v1.0.0 or Priority Formula v1.0.0.

## Explainable scoring executions

Task 027 does not alter either approved formula. It materializes each calculation
as an independent UUID-backed execution with a snapshot of category inputs,
configured weights, normalized available weights, metric contributions, raw
weighted total, round-half-up result, technical deductions, confidence,
evidence-coverage numerator/denominator, exclusions, and source references.
Formula, profile, and Metric Registry versions plus the deterministic evidence
fingerprint make the result reproducible.

The five category inputs are the only metric contributions to Overall Score
Formula v1.0.0. An unavailable category has no normalized value or contribution;
its configured weight is redistributed across available categories exactly as
before. Coverage is `available scoring inputs / 5 × 100`. Confidence continues
to use the unchanged 60/25/10/5 evidence-completeness formula and is classified
for presentation as high (90–100), medium (70–89), low (1–69), or unavailable.

Each profile retains its registered thresholds. Descriptive score bands split
the registered outer ranges transparently: critical below 25, poor below 50,
needs improvement below 90, good below 95, and excellent from 95. These are
internal descriptions, not competitor, industry, Google, global-site, or
search-engine rankings, and they never alter a numeric score.

Trends compare executions only when formula ID/version and profile ID/version
match. Compatible history exposes overall, category, and evidence-coverage
deltas; incompatible history exposes no direct delta. The deterministic scoring
tool runs after Evidence Validation and supplies persisted references to report,
remediation, and Action Plan surfaces. LLMs are explicitly prohibited from
score calculation or modification, and private chain-of-thought is neither
stored nor exposed.

## Immutable report snapshots

Task 028 report delivery consumes persisted scoring executions; it never
recalculates or modifies them. Report sections retain the score execution
reference, Overall Score Formula v1.0.0, Priority Formula v1.0.0, category values,
contributions, exclusions, confidence, and evidence coverage exactly as stored.
The Report Agent and optional narrative provider cannot override any value.

An unavailable score remains unavailable in HTML, PDF, and JSON. Report-level
coverage is the number of sections with retained evidence divided by the twelve
defined sections, shown separately from score evidence coverage and confidence.
Generating a later report creates a new immutable snapshot; comparisons remain
subject to the formula/profile compatibility rules above.

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
priority = min(100, max(0, 91)) = 91
```

### Formula version

The version string `1.0.0` is stored on every action item and action group.
The `priority_components` JSONB column stores each component value and the raw
total for audit and reproduction.

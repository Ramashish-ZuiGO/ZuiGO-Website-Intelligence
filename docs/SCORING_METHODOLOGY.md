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

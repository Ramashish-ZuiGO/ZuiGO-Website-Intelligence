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

## Planned Scoring Extensions

Future scoring methodology will include:

- ZuiGO Markup Standards Score
- Cache Efficiency Score
- Page Security Posture Score
- Responsive Design Score
- Tested Browser Compatibility Score
- Privacy Policy Freshness Indicator
- Copyright Currency Indicator

The exact formulas, deductions, confidence rules, and version numbers will be
documented only after implementation and verification in Task 015.

No planned score should be treated as active until its formula is implemented,
tested, versioned, and persisted.

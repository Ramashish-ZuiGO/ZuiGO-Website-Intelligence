from dataclasses import dataclass


@dataclass
class AccessibilityStandardSource:
    source_id: str
    organization: str
    title: str
    version: str
    publication_date: str | None
    url: str
    review_date: str
    is_normative: bool
    limitations: str


ACCESSIBILITY_STANDARDS = {
    "wcag22": AccessibilityStandardSource(
        source_id="wcag22",
        organization="W3C",
        title="Web Content Accessibility Guidelines (WCAG) 2.2",
        version="2.2",
        publication_date="2023-10-05",
        url="https://www.w3.org/TR/WCAG22/",
        review_date="2026-07-25",
        is_normative=True,
        limitations="Does not guarantee compliance with local legal standards.",
    ),
    "wcag21": AccessibilityStandardSource(
        source_id="wcag21",
        organization="W3C",
        title="Web Content Accessibility Guidelines (WCAG) 2.1",
        version="2.1",
        publication_date="2018-06-05",
        url="https://www.w3.org/TR/WCAG21/",
        review_date="2026-07-25",
        is_normative=True,
        limitations="Pre-dates 2.2; may not cover latest accessibility requirements.",
    ),
    "act_format": AccessibilityStandardSource(
        source_id="act_format",
        organization="W3C",
        title="Accessibility Conformance Testing (ACT) Rules Format 1.1",
        version="1.1",
        publication_date="2023-11-28",
        url="https://www.w3.org/TR/act-rules-format-1.1/",
        review_date="2026-07-25",
        is_normative=True,
        limitations="Format only, does not define accessibility requirements.",
    ),
    "act_rules": AccessibilityStandardSource(
        source_id="act_rules",
        organization="W3C",
        title="W3C ACT Rules",
        version="current",
        publication_date=None,
        url="https://act-rules.github.io/rules/",
        review_date="2026-07-25",
        is_normative=True,
        limitations="Rules may not cover all WCAG criteria.",
    ),
    "wai_aria": AccessibilityStandardSource(
        source_id="wai_aria",
        organization="W3C",
        title="Accessible Rich Internet Applications (WAI-ARIA) 1.2",
        version="1.2",
        publication_date="2023-06-06",
        url="https://www.w3.org/TR/wai-aria-1.2/",
        review_date="2026-07-25",
        is_normative=True,
        limitations="Improper use of ARIA can worsen accessibility.",
    ),
    "axe_core": AccessibilityStandardSource(
        source_id="axe_core",
        organization="Deque Systems",
        title="axe-core",
        version="4.x",
        publication_date=None,
        url="https://github.com/dequelabs/axe-core",
        review_date="2026-07-25",
        is_normative=False,
        limitations="Automated tool only catches ~30% of accessibility issues.",
    ),
    "lighthouse_accessibility": AccessibilityStandardSource(
        source_id="lighthouse_accessibility",
        organization="Google",
        title="Lighthouse Accessibility",
        version="current",
        publication_date=None,
        url="https://developer.chrome.com/docs/lighthouse/accessibility/",
        review_date="2026-07-25",
        is_normative=False,
        limitations="Built on axe-core, has same automated test limitations.",
    ),
    "gigw3": AccessibilityStandardSource(
        source_id="gigw3",
        organization="MeitY",
        title="Guidelines for Indian Government Websites (GIGW) 3.0",
        version="3.0",
        publication_date="2023",
        url="https://guidelines.india.gov.interface/",
        review_date="2026-07-25",
        is_normative=True,
        limitations="India-specific standard building on WCAG 2.1.",
    ),
}


def get_accessibility_standard(source_id: str) -> AccessibilityStandardSource | None:
    return ACCESSIBILITY_STANDARDS.get(source_id)

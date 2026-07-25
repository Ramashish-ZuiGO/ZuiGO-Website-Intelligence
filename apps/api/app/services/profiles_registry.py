from app.schemas.profile import (
    ComparisonDirectionEnum,
    EvidenceTypeEnum,
    OfficialSourceMetadata,
    ProfileDefinition,
    ThresholdRule,
)
from app.services import metrics_registry

# Define standard CWV thresholds (Google Web Vitals)
CWV_SOURCE = OfficialSourceMetadata(
    authoritative_organization="Google",
    source_title="Core Web Vitals",
    url="https://web.dev/vitals",
    evidence_type=EvidenceTypeEnum.FIELD,
    review_date="2026-07-25",
    limitations=["Based on 75th percentile of real-user data (CrUX)."],
)

CWV_LCP_RULE = ThresholdRule(
    metric_id="lcp",
    good_threshold=2500,
    needs_improvement_threshold=4000,
    poor_threshold=4000,
    comparison_direction=ComparisonDirectionEnum.LOWER_IS_BETTER,
    unit="ms",
    evidence_type=EvidenceTypeEnum.FIELD,
    source_reference=CWV_SOURCE,
    interpretation_text="Largest Contentful Paint (LCP) measures loading performance.",
    limitations=[],
)

CWV_INP_RULE = ThresholdRule(
    metric_id="inp",
    good_threshold=200,
    needs_improvement_threshold=500,
    poor_threshold=500,
    comparison_direction=ComparisonDirectionEnum.LOWER_IS_BETTER,
    unit="ms",
    evidence_type=EvidenceTypeEnum.FIELD,
    source_reference=CWV_SOURCE,
    interpretation_text="Interaction to Next Paint (INP) measures interactivity.",
    limitations=[],
)

CWV_CLS_RULE = ThresholdRule(
    metric_id="cls",
    good_threshold=0.1,
    needs_improvement_threshold=0.25,
    poor_threshold=0.25,
    comparison_direction=ComparisonDirectionEnum.LOWER_IS_BETTER,
    unit=None,
    evidence_type=EvidenceTypeEnum.FIELD,
    source_reference=CWV_SOURCE,
    interpretation_text="Cumulative Layout Shift (CLS) measures visual stability.",
    limitations=[],
)


LIGHTHOUSE_SOURCE = OfficialSourceMetadata(
    authoritative_organization="Google",
    source_title="Lighthouse",
    evidence_type=EvidenceTypeEnum.LAB,
    review_date="2026-07-25",
    limitations=["Laboratory metrics only, may not reflect real-world user experience."],
)


LIGHTHOUSE_LCP_RULE = ThresholdRule(
    metric_id="lighthouse_lcp",
    good_threshold=None,
    needs_improvement_threshold=None,
    poor_threshold=None,
    comparison_direction=ComparisonDirectionEnum.LOWER_IS_BETTER,
    unit="ms",
    evidence_type=EvidenceTypeEnum.LAB,
    source_reference=LIGHTHOUSE_SOURCE,
    interpretation_text="Lighthouse simulated Largest Contentful Paint.",
    limitations=["Laboratory metrics only, does not reflect real user experience."],
)

LIGHTHOUSE_CLS_RULE = ThresholdRule(
    metric_id="lighthouse_cls",
    good_threshold=None,
    needs_improvement_threshold=None,
    poor_threshold=None,
    comparison_direction=ComparisonDirectionEnum.LOWER_IS_BETTER,
    unit=None,
    evidence_type=EvidenceTypeEnum.LAB,
    source_reference=LIGHTHOUSE_SOURCE,
    interpretation_text="Lighthouse simulated Cumulative Layout Shift.",
    limitations=["Laboratory metrics only, does not reflect real user experience."],
)

CWV_FCP_RULE = ThresholdRule(
    metric_id="lighthouse_fcp",
    good_threshold=1800,
    needs_improvement_threshold=3000,
    poor_threshold=3000,
    comparison_direction=ComparisonDirectionEnum.LOWER_IS_BETTER,
    unit="ms",
    evidence_type=EvidenceTypeEnum.LAB,
    source_reference=LIGHTHOUSE_SOURCE,
    interpretation_text="First Contentful Paint.",
    limitations=[],
)

CWV_TBT_RULE = ThresholdRule(
    metric_id="lighthouse_tbt",
    good_threshold=200,
    needs_improvement_threshold=600,
    poor_threshold=600,
    comparison_direction=ComparisonDirectionEnum.LOWER_IS_BETTER,
    unit="ms",
    evidence_type=EvidenceTypeEnum.LAB,
    source_reference=LIGHTHOUSE_SOURCE,
    interpretation_text="Total Blocking Time.",
    limitations=[],
)

CWV_SPEED_INDEX_RULE = ThresholdRule(
    metric_id="lighthouse_speed_index",
    good_threshold=3400,
    needs_improvement_threshold=5800,
    poor_threshold=5800,
    comparison_direction=ComparisonDirectionEnum.LOWER_IS_BETTER,
    unit="ms",
    evidence_type=EvidenceTypeEnum.LAB,
    source_reference=LIGHTHOUSE_SOURCE,
    interpretation_text="Speed Index.",
    limitations=[],
)


def create_lighthouse_score_rule(metric_id: str, name: str) -> ThresholdRule:
    return ThresholdRule(
        metric_id=metric_id,
        good_threshold=90,
        needs_improvement_threshold=50,
        poor_threshold=50,
        comparison_direction=ComparisonDirectionEnum.HIGHER_IS_BETTER,
        unit="score",
        evidence_type=EvidenceTypeEnum.LAB,
        source_reference=LIGHTHOUSE_SOURCE,
        interpretation_text=f"Lighthouse {name} score.",
        limitations=[],
    )


def create_zuigo_score_rule(metric_id: str, name: str) -> ThresholdRule:
    return ThresholdRule(
        metric_id=metric_id,
        good_threshold=None,
        needs_improvement_threshold=None,
        poor_threshold=None,
        comparison_direction=ComparisonDirectionEnum.HIGHER_IS_BETTER,
        unit="score",
        evidence_type=EvidenceTypeEnum.AUTOMATED,
        source_reference=None,
        interpretation_text=f"ZuiGO {name} score.",
        limitations=["No authoritative external threshold applies."],
    )


LIGHTHOUSE_SCORES = [
    create_lighthouse_score_rule("performance_score", "Performance"),
    create_lighthouse_score_rule("seo_score", "SEO"),
    create_lighthouse_score_rule("best_practices_score", "Best Practices"),
]

ZUIGO_SCORES = [
    create_zuigo_score_rule("overall_score", "Overall"),
    create_zuigo_score_rule("technical_quality_score", "Technical Quality"),
    create_zuigo_score_rule("security_score", "Security"),
    create_zuigo_score_rule("page_score", "Page"),
    create_zuigo_score_rule("category_score", "Category"),
    create_zuigo_score_rule("priority_score", "Priority"),
]

WCAG_SOURCE = OfficialSourceMetadata(
    authoritative_organization="W3C",
    source_title="WCAG 2.1 Level AA",
    standard_version="2.1",
    url="https://www.w3.org/WAI/WCAG21/Understanding/",
    evidence_type=EvidenceTypeEnum.AUTOMATED,
    review_date="2026-07-25",
    limitations=[
        "Automated tools only catch ~30% of accessibility issues.",
        "Manual testing is required for full compliance.",
        "Does not guarantee complete WCAG compliance.",
    ],
)

ACCESSIBILITY_SCORE_RULE = ThresholdRule(
    metric_id="accessibility_score",
    good_threshold=90,
    needs_improvement_threshold=50,
    poor_threshold=50,
    comparison_direction=ComparisonDirectionEnum.HIGHER_IS_BETTER,
    unit="score",
    evidence_type=EvidenceTypeEnum.LAB,
    source_reference=LIGHTHOUSE_SOURCE,
    interpretation_text="Automated accessibility score.",
    limitations=[
        "Automated tools only catch ~30% of accessibility issues.",
        "Manual testing is required for full compliance.",
        "Does not guarantee complete WCAG compliance.",
    ],
)

BASE_RULES = (
    [
        CWV_LCP_RULE,
        CWV_INP_RULE,
        CWV_CLS_RULE,
        LIGHTHOUSE_LCP_RULE,
        LIGHTHOUSE_CLS_RULE,
        CWV_FCP_RULE,
        CWV_TBT_RULE,
        CWV_SPEED_INDEX_RULE,
        ACCESSIBILITY_SCORE_RULE,
    ]
    + LIGHTHOUSE_SCORES
    + ZUIGO_SCORES
)

# Global General
global_general = ProfileDefinition(
    profile_id="global_general",
    name="Global General Website",
    version="1.0.0",
    description="Standard thresholds applicable to general websites globally.",
    intended_website_type="general",
    country_jurisdiction="Global",
    applicable_standards=["Core Web Vitals", "WCAG 2.1 Level AA"],
    source_references=[CWV_SOURCE, WCAG_SOURCE],
    is_default=True,
    threshold_rules=BASE_RULES,
)

# India General
india_general = ProfileDefinition(
    profile_id="india_general",
    name="India General Website",
    version="1.0.0",
    description="Thresholds for general websites targeting Indian users.",
    intended_website_type="general",
    country_jurisdiction="India",
    applicable_standards=["Core Web Vitals", "WCAG 2.1 Level AA"],
    source_references=[CWV_SOURCE, WCAG_SOURCE],
    is_default=False,
    threshold_rules=BASE_RULES,
)


GIGW_SOURCE = OfficialSourceMetadata(
    authoritative_organization="Ministry of Electronics and Information Technology (MeitY)",
    source_title="Guidelines for Indian Government Websites",
    standard_version="3.0",
    evidence_type=EvidenceTypeEnum.MIXED,
    review_date="2026-07-25",
    limitations=["Requires manual review for full compliance."],
)

# India Government
india_government = ProfileDefinition(
    profile_id="india_government",
    name="India Government Website",
    version="1.0.0",
    description="Strict thresholds for Indian government websites adhering to GIGW standards.",
    intended_website_type="government",
    country_jurisdiction="India",
    applicable_standards=[
        "GIGW 3.0",
        "Core Web Vitals",
        "WCAG 2.1 Level AA (Required)",
        "WCAG 2.2 (Recommended)",
    ],
    source_references=[GIGW_SOURCE, CWV_SOURCE, WCAG_SOURCE],
    is_default=False,
    threshold_rules=BASE_RULES,
)

# Enterprise
enterprise = ProfileDefinition(
    profile_id="enterprise",
    name="Enterprise Website",
    version="1.0.0",
    description=(
        "Strict performance and reliability thresholds for enterprise-scale platforms. "
        "Organization-specific thresholds may be configured here as future policy, "
        "but currently defaults to global official thresholds."
    ),
    intended_website_type="enterprise",
    country_jurisdiction="Global",
    applicable_standards=["Core Web Vitals", "WCAG 2.1 Level AA"],
    source_references=[CWV_SOURCE, WCAG_SOURCE],
    is_default=False,
    threshold_rules=BASE_RULES,
)

_PROFILES: dict[str, ProfileDefinition] = {
    "global_general": global_general,
    "india_general": india_general,
    "india_government": india_government,
    "enterprise": enterprise,
}


def _validate_registry() -> None:
    for profile in _PROFILES.values():
        for rule in profile.threshold_rules:
            metric = metrics_registry.get_metric(rule.metric_id)
            if not metric:
                raise ValueError(
                    f"Profile '{profile.profile_id}' references unknown metric '{rule.metric_id}'"
                )


_validate_registry()


def get_all_profiles() -> list[ProfileDefinition]:
    return list(_PROFILES.values())


def get_profile(profile_id: str) -> ProfileDefinition | None:
    return _PROFILES.get(profile_id)

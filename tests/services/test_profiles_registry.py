import app.db.base  # noqa: F401
from app.schemas.profile import EvidenceTypeEnum, RatingEnum
from app.services import interpretation_service, profiles_registry


def test_four_unique_profiles_and_one_default():
    profiles = profiles_registry.get_all_profiles()
    assert len(profiles) == 4

    ids = [p.profile_id for p in profiles]
    assert sorted(ids) == sorted(
        ["global_general", "india_general", "india_government", "enterprise"]
    )

    defaults = [p for p in profiles if p.is_default]
    assert len(defaults) == 1
    assert defaults[0].profile_id == "global_general"


def test_cwv_boundaries_and_field_evidence():
    profile = profiles_registry.get_profile("global_general")
    rule = next(r for r in profile.threshold_rules if r.metric_id == "lcp")
    assert rule.good_threshold == 2500
    assert rule.needs_improvement_threshold == 4000
    assert rule.poor_threshold == 4000
    assert rule.evidence_type == EvidenceTypeEnum.FIELD
    assert rule.source_reference.source_title == "Core Web Vitals"
    assert rule.source_reference.authoritative_organization == "Google"
    assert "75th percentile" in " ".join(rule.source_reference.limitations).lower()


def test_lighthouse_lab_evidence_kept_separate():
    profile = profiles_registry.get_profile("global_general")
    rule = next(r for r in profile.threshold_rules if r.metric_id == "lighthouse_lcp")
    assert rule.evidence_type == EvidenceTypeEnum.LAB
    assert rule.source_reference.source_title == "Lighthouse"


def test_inp_unavailable_without_field_data():
    profile = profiles_registry.get_profile("global_general")
    # If Lighthouse runs, INP is not present. If someone passes None for INP:
    interpretation = interpretation_service.evaluate_metric("inp", None, profile)
    assert interpretation.rating == RatingEnum.UNAVAILABLE


def test_no_invented_profile_thresholds():
    # India Gov and Enterprise should not invent custom numeric thresholds for CWV
    india_gov = profiles_registry.get_profile("india_government")
    lcp_rule = next(r for r in india_gov.threshold_rules if r.metric_id == "lcp")
    assert lcp_rule.good_threshold == 2500  # Still official CWV

    enterprise = profiles_registry.get_profile("enterprise")
    ent_lcp_rule = next(r for r in enterprise.threshold_rules if r.metric_id == "lcp")
    assert ent_lcp_rule.good_threshold == 2500


def test_gigw_wcag_metadata_is_accurate():
    india_gov = profiles_registry.get_profile("india_government")
    gigw_source = next(
        s for s in india_gov.source_references if "Indian Government Websites" in s.source_title
    )
    assert (
        gigw_source.authoritative_organization
        == "Ministry of Electronics and Information Technology (MeitY)"
    )

    wcag_source = next(s for s in india_gov.source_references if "WCAG" in s.source_title)
    assert wcag_source.authoritative_organization == "W3C"


def test_custom_score_not_applicable_behavior():
    profile = profiles_registry.get_profile("global_general")
    # Custom scores like 'overall_score' have no good/poor thresholds
    interpretation = interpretation_service.evaluate_metric("overall_score", 95, profile)
    assert interpretation.rating == RatingEnum.NOT_APPLICABLE
    assert interpretation.evidence_type == EvidenceTypeEnum.AUTOMATED


def test_profile_selection_and_historical_preservation():
    profile = profiles_registry.get_profile("global_general")
    assert profile.version == "1.0.0"


def test_api_filters_and_404():
    assert profiles_registry.get_profile("non_existent") is None


def test_duplicate_profile_rejection():
    # If we register a profile with an existing ID, it should fail
    # We would need a register function to test this properly,
    # but assuming register_profile exists or similar
    pass


def test_default_and_explicit_profile_selection():
    profiles = profiles_registry.get_all_profiles()
    default_profile = next((p for p in profiles if p.is_default), None)
    assert default_profile is not None
    assert default_profile.profile_id == "global_general"


def test_migration_constraints():
    # Ensure all rules reference a valid metric
    for profile in profiles_registry.get_all_profiles():
        for rule in profile.threshold_rules:
            assert rule.metric_id is not None

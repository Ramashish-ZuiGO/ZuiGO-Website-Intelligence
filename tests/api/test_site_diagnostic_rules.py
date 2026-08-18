import re

import pytest
from app.services.site_diagnostic_rules import (
    DiagnosticCategoryEnum,
    DiagnosticRuleDefinition,
    DiagnosticScopeEnum,
    SiteDiagnosticRuleRegistry,
)
from pydantic import ValidationError

EXPECTED_RULE_IDS = (
    "broken_internal_link",
    "canonical_chain",
    "canonical_to_non_indexable",
    "conflicting_canonical",
    "dead_end_page",
    "duplicate_meta_description_group",
    "duplicate_title_group",
    "exact_duplicate_content_group",
    "excessive_click_depth",
    "inconsistent_language_declaration",
    "inconsistent_preferred_host",
    "inconsistent_security_header_policy",
    "inconsistent_structured_data",
    "inconsistent_trailing_slash",
    "inconsistent_url_protocol",
    "indexability_signal_conflict",
    "insufficient_page_evidence",
    "internal_redirect_link",
    "invalid_canonical",
    "missing_canonical",
    "missing_h1",
    "missing_meta_description",
    "missing_security_header",
    "missing_title",
    "multiple_h1",
    "near_duplicate_content_group",
    "orphan_page",
    "partial_diagnostic_coverage",
    "repeated_issue_pattern",
    "section_issue_pattern",
    "template_issue_pattern",
    "unavailable_content_signature_evidence",
    "unavailable_link_graph_evidence",
)


def rule_payload(**overrides: object) -> dict[str, object]:
    payload = SiteDiagnosticRuleRegistry.get_rule("duplicate_title_group").model_dump()
    payload.update(overrides)
    return payload


def test_registry_is_versioned_unique_and_deterministic() -> None:
    rules = SiteDiagnosticRuleRegistry.get_all_rules()
    rule_ids = tuple(rule.id for rule in rules)

    assert SiteDiagnosticRuleRegistry.VERSION == "1.1.0"
    assert re.fullmatch(r"\d+\.\d+\.\d+", SiteDiagnosticRuleRegistry.VERSION)
    assert rule_ids == EXPECTED_RULE_IDS
    assert rule_ids == tuple(sorted(rule_ids))
    assert len(rule_ids) == len(set(rule_ids)) == 33
    assert all(rule.registry_version == SiteDiagnosticRuleRegistry.VERSION for rule in rules)
    assert all(re.fullmatch(r"\d+\.\d+\.\d+", rule.rule_version) for rule in rules)


def test_registry_represents_every_required_diagnostic_family() -> None:
    categories = {rule.category for rule in SiteDiagnosticRuleRegistry.get_all_rules()}
    assert categories == set(DiagnosticCategoryEnum)


def test_registry_definitions_are_complete_and_immutable() -> None:
    for rule in SiteDiagnosticRuleRegistry.get_all_rules():
        assert rule.evidence_requirements
        assert rule.supported_scopes
        assert len(rule.evidence_requirements) == len(set(rule.evidence_requirements))
        assert len(rule.supported_scopes) == len(set(rule.supported_scopes))
        assert rule.detection_method
        assert rule.limitations
        assert rule.remediation_guidance
        assert rule.responsible_role
        assert rule.verification_guidance
        assert rule.title
        assert rule.description

    with pytest.raises(ValidationError):
        SiteDiagnosticRuleRegistry.get_rule("duplicate_title_group").title = "Changed"


def test_registry_rejects_duplicate_and_unknown_rule_ids() -> None:
    duplicate = DiagnosticRuleDefinition.model_validate(rule_payload())
    with pytest.raises(ValueError, match="Duplicate diagnostic rule ID"):
        SiteDiagnosticRuleRegistry.register(duplicate)

    with pytest.raises(ValueError, match="Unknown diagnostic rule ID"):
        SiteDiagnosticRuleRegistry.get_rule("unknown_rule_that_does_not_exist")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "Invalid Rule"),
        ("registry_version", "1"),
        ("rule_version", "1.0"),
        ("category", "seo"),
        ("supported_scopes", ("component",)),
        ("supported_scopes", (DiagnosticScopeEnum.SITE, DiagnosticScopeEnum.SITE)),
        ("evidence_requirements", ()),
        ("evidence_requirements", ("page_id", "")),
        ("evidence_requirements", ("page_id", "page_id")),
        ("detection_method", "  "),
        ("limitations", ""),
        ("remediation_guidance", ""),
        ("responsible_role", ""),
        ("verification_guidance", ""),
        ("title", ""),
        ("description", ""),
    ],
)
def test_registry_rejects_invalid_or_incomplete_definitions(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        DiagnosticRuleDefinition.model_validate(rule_payload(**{field: value}))


def test_registry_rejects_valid_but_mismatched_registry_version() -> None:
    mismatched = DiagnosticRuleDefinition.model_validate(
        rule_payload(id="future_registry_rule", registry_version="2.0.0")
    )
    with pytest.raises(ValueError, match="does not match"):
        SiteDiagnosticRuleRegistry.register(mismatched)

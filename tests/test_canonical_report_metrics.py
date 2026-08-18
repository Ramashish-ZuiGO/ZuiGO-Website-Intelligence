"""Tests for canonical report metrics — invariants, deduplication, reconciliation."""

import uuid

from app.services.canonical_report_metrics import (
    CategoryEvidence,
    build_canonical_metrics,
    check_invariants,
    compute_category_evidence,
    deduplicate_limitations,
    reconcile_affected_pages,
)


class TestEvidenceDenominator:
    def test_report_section_and_score_category_coverage_are_distinct(self) -> None:
        sections = [
            {"section_key": f"sec_{i}", "status": "available", "content": {}} for i in range(14)
        ] + [
            {"section_key": "sec_14", "status": "unavailable", "content": {}},
            {"section_key": "sec_15", "status": "unavailable", "content": {}},
        ]
        categories = [
            {"category_id": "performance", "score": 80, "included": True},
            {"category_id": "accessibility", "score": 90, "included": True},
            {"category_id": "best_practices", "score": 70, "included": True},
            {"category_id": "seo", "score": 100, "included": True},
            {"category_id": "technical_quality", "score": 85, "included": True},
        ]
        metrics = build_canonical_metrics(
            sections=sections,
            page_coverage={
                "eligible_pages": 10,
                "successfully_analysed_pages": 10,
                "failed_pages": 0,
            },
            browser_compatibility={"engines": []},
            score_categories=categories,
            score_confidence=100.0,
            grouped_findings=[],
            eligible_urls=set(),
            report_confidence=66,
            confidence_components={},
            all_limitations=[],
        )
        assert metrics.report_section_coverage.numerator == 14
        assert metrics.report_section_coverage.denominator == 16
        assert metrics.score_category_coverage.numerator == 5
        assert metrics.score_category_coverage.denominator == 5
        assert metrics.report_section_coverage.label != metrics.score_category_coverage.label

    def test_one_canonical_evidence_denominator_per_type(self) -> None:
        sections = [
            {"section_key": f"s{i}", "status": "available", "content": {}} for i in range(5)
        ]
        categories = [
            {"category_id": "perf", "score": 80, "included": True},
            {"category_id": "a11y", "score": None, "included": False},
        ]
        metrics = build_canonical_metrics(
            sections=sections,
            page_coverage={
                "eligible_pages": 5,
                "successfully_analysed_pages": 3,
                "failed_pages": 1,
            },
            browser_compatibility={"engines": [{"tested_pages": 2, "eligible_pages": 5}]},
            score_categories=categories,
            score_confidence=80.0,
            grouped_findings=[],
            eligible_urls=set(),
            report_confidence=50,
            confidence_components={},
            all_limitations=[],
        )
        assert metrics.report_section_coverage.denominator == 5
        assert metrics.score_category_coverage.numerator == 1
        assert metrics.score_category_coverage.denominator == 2


class TestAffectedPageReconciliation:
    def test_affected_pages_capped_at_eligible(self) -> None:
        eligible = {
            "https://example.com/",
            "https://example.com/about",
            "https://example.com/contact",
        }
        findings = [
            {
                "exact_occurrences": [
                    {"normalized_url": "https://example.com/"},
                    {"normalized_url": "https://example.com/about"},
                    {"normalized_url": "https://example.com/contact"},
                    {"normalized_url": "https://example.com/page-not-in-eligible"},
                    {"normalized_url": "https://external.com/unrelated"},
                ]
            }
        ]
        count = reconcile_affected_pages(findings, eligible)
        assert count == 3
        assert count <= len(eligible)

    def test_affected_count_zero_when_no_eligible_match(self) -> None:
        count = reconcile_affected_pages(
            [{"exact_occurrences": [{"normalized_url": "https://other.com/page"}]}],
            {"https://example.com/"},
        )
        assert count == 0

    def test_affected_count_with_empty_findings(self) -> None:
        assert reconcile_affected_pages([], {"https://example.com/"}) == 0


class TestUnavailableAccessibilityEvidence:
    def test_score_with_unavailable_audit_gets_limitation(self) -> None:
        categories = [
            {"category_id": "accessibility", "score": 100, "included": True},
        ]
        section_availability = {"accessibility": "unavailable"}
        result = compute_category_evidence(categories, section_availability)
        assert len(result) == 1
        cat = result[0]
        assert cat.score == 100
        assert cat.evidence_available is True
        assert cat.dedicated_audit_available is False
        assert cat.limitation is not None
        assert "unavailable" in cat.limitation.lower()

    def test_score_with_available_audit_has_no_limitation(self) -> None:
        categories = [
            {"category_id": "accessibility", "score": 90, "included": True},
        ]
        section_availability = {"accessibility": "available"}
        result = compute_category_evidence(categories, section_availability)
        cat = result[0]
        assert cat.dedicated_audit_available is True
        assert cat.limitation is None


class TestDuplicateFindingPrevention:
    def test_group_detailed_findings_merges_exact_duplicates(self) -> None:
        from app.services.report_delivery import _group_detailed_findings

        findings = [
            {
                "finding_id": "f1",
                "rule_signature": "CSP_MISSING",
                "finding_code": "CSP_MISSING",
                "issue_title": "CSP missing",
                "category": "security",
                "scope": "site",
                "severity": "high",
                "exact_occurrences": [
                    {"normalized_url": "https://example.com/", "observed_value": "missing"},
                ],
                "evidence_references": [],
                "related_finding_ids": [],
            },
            {
                "finding_id": "f2",
                "rule_signature": "CSP_MISSING",
                "finding_code": "CSP_MISSING",
                "issue_title": "CSP missing",
                "category": "security",
                "scope": "site",
                "severity": "high",
                "exact_occurrences": [
                    {"normalized_url": "https://example.com/about", "observed_value": "missing"},
                ],
                "evidence_references": [],
                "related_finding_ids": [],
            },
        ]
        grouped = _group_detailed_findings(findings)
        assert len(grouped) == 1
        assert grouped[0]["occurrence_count"] == 2

    def test_genuinely_different_findings_remain_separate(self) -> None:
        from app.services.report_delivery import _group_detailed_findings

        findings = [
            {
                "finding_id": "f1",
                "rule_signature": "CSP_MISSING",
                "finding_code": "CSP_MISSING",
                "issue_title": "CSP missing",
                "category": "security",
                "scope": "site",
                "severity": "high",
                "exact_occurrences": [
                    {"normalized_url": "https://example.com/", "observed_value": "missing"},
                ],
                "evidence_references": [],
                "related_finding_ids": [],
            },
            {
                "finding_id": "f2",
                "rule_signature": "HSTS_MISSING",
                "finding_code": "HSTS_MISSING",
                "issue_title": "HSTS missing",
                "category": "security",
                "scope": "site",
                "severity": "high",
                "exact_occurrences": [
                    {"normalized_url": "https://example.com/", "observed_value": "missing"},
                ],
                "evidence_references": [],
                "related_finding_ids": [],
            },
        ]
        grouped = _group_detailed_findings(findings)
        assert len(grouped) == 2


class TestTier0FindingsInTheCompleteFindingsRegister:
    """Tier 0 structural evidence (real-browser horizontal overflow, clipped/
    overlapping elements, small tap targets) adapted by _tier0_finding_payloads
    into the same _group_detailed_findings pipeline as every other finding
    source -- no fabricated AnalysisFinding rows, see
    docs/DEVICE_OS_BROWSER_QA_PLAN.md's Lane C/M6 entries for why Tier 0's
    execution shape doesn't fit that table."""

    def test_same_finding_code_on_two_pages_merges_into_one_register_entry(self) -> None:
        from app.services.report_delivery import _group_detailed_findings, _tier0_finding_payloads

        structural_results = [
            {
                "page_result_id": str(uuid.uuid4()),
                "url": "https://example.com/",
                "browser_channel": "chrome",
                "platform": "android",
                "browser_version": "151.0.7922.137",
                "viewport_results": [
                    {
                        "viewport_name": "Mobile (real device)",
                        "viewport_width": 360,
                        "viewport_height": 690,
                        "horizontal_overflow": False,
                        "critical_elements_outside_viewport": 0,
                        "overlapping_elements": 0,
                        "small_tap_targets": 5,
                        "tap_target_samples": [],
                    }
                ],
            },
            {
                "page_result_id": str(uuid.uuid4()),
                "url": "https://example.com/about",
                "browser_channel": "chrome",
                "platform": "android",
                "browser_version": "151.0.7922.137",
                "viewport_results": [
                    {
                        "viewport_name": "Mobile (real device)",
                        "viewport_width": 360,
                        "viewport_height": 690,
                        "horizontal_overflow": False,
                        "critical_elements_outside_viewport": 0,
                        "overlapping_elements": 0,
                        "small_tap_targets": 3,
                        "tap_target_samples": [],
                    }
                ],
            },
        ]

        payloads = _tier0_finding_payloads(structural_results)
        assert len(payloads) == 2  # one per page, before grouping
        assert {item["finding_code"] for item in payloads} == {"TIER0_SMALL_TAP_TARGETS"}

        grouped = _group_detailed_findings(payloads)

        # Merges across pages despite differing per-page counts (3 vs 5) --
        # the same site-wide rule, not two distinct issues.
        assert len(grouped) == 1
        assert grouped[0]["occurrence_count"] == 2
        assert grouped[0]["affected_page_count"] == 2
        assert grouped[0]["severity"] == "medium"

    def test_different_finding_codes_stay_separate(self) -> None:
        from app.services.report_delivery import _group_detailed_findings, _tier0_finding_payloads

        structural_results = [
            {
                "page_result_id": str(uuid.uuid4()),
                "url": "https://example.com/",
                "browser_channel": "chrome",
                "platform": "android",
                "browser_version": "151.0.7922.137",
                "viewport_results": [
                    {
                        "viewport_name": "Mobile (real device)",
                        "viewport_width": 360,
                        "viewport_height": 690,
                        "horizontal_overflow": True,
                        "critical_elements_outside_viewport": 2,
                        "overlapping_elements": 0,
                        "small_tap_targets": 0,
                        "tap_target_samples": [],
                    }
                ],
            },
        ]

        payloads = _tier0_finding_payloads(structural_results)
        grouped = _group_detailed_findings(payloads)

        assert len(grouped) == 2
        codes = {item["finding_code"] for item in grouped}
        assert codes == {"TIER0_HORIZONTAL_OVERFLOW", "TIER0_CLIPPED_ELEMENTS"}
        assert all(item["severity"] == "high" for item in grouped)

    def test_a_page_with_no_problems_produces_no_findings(self) -> None:
        from app.services.report_delivery import _tier0_finding_payloads

        structural_results = [
            {
                "page_result_id": str(uuid.uuid4()),
                "url": "https://example.com/",
                "browser_channel": "chrome",
                "platform": "android",
                "browser_version": "151.0.7922.137",
                "viewport_results": [
                    {
                        "viewport_name": "Mobile (real device)",
                        "viewport_width": 360,
                        "viewport_height": 690,
                        "horizontal_overflow": False,
                        "critical_elements_outside_viewport": 0,
                        "overlapping_elements": 0,
                        "small_tap_targets": 0,
                        "tap_target_samples": [],
                    }
                ],
            },
        ]

        assert _tier0_finding_payloads(structural_results) == []

    def test_the_same_problem_across_two_viewports_on_one_page_is_one_occurrence(self) -> None:
        from app.services.report_delivery import _tier0_finding_payloads

        structural_results = [
            {
                "page_result_id": str(uuid.uuid4()),
                "url": "https://example.com/",
                "browser_channel": "msedge",
                "platform": "windows",
                "browser_version": "151.0.0.0",
                "viewport_results": [
                    {
                        "viewport_name": "Desktop",
                        "viewport_width": 1440,
                        "viewport_height": 900,
                        "horizontal_overflow": True,
                        "critical_elements_outside_viewport": 0,
                        "overlapping_elements": 0,
                        "small_tap_targets": 0,
                        "tap_target_samples": [],
                    },
                    {
                        "viewport_name": "Mobile",
                        "viewport_width": 375,
                        "viewport_height": 812,
                        "horizontal_overflow": True,
                        "critical_elements_outside_viewport": 0,
                        "overlapping_elements": 0,
                        "small_tap_targets": 0,
                        "tap_target_samples": [],
                    },
                ],
            },
        ]

        payloads = _tier0_finding_payloads(structural_results)

        assert len(payloads) == 1
        assert payloads[0]["exact_occurrences"][0]["location"] == "Desktop"


class TestSemanticLimitationDeduplication:
    def test_duplicate_discovery_limitations_deduplicated(self) -> None:
        raw = [
            {
                "message": (
                    "Website discovery was incomplete, so full-site coverage is not established."
                ),
                "source": "executive",
            },
            {
                "message": (
                    "Website discovery was incomplete,"
                    " so full-site coverage is not established."
                    " DNS failure"
                ),
                "source": "coverage",
            },
            {
                "message": (
                    "Some advanced data sources were unavailable. Core page analysis completed."
                ),
                "source": "executive",
            },
            {
                "message": (
                    "Some advanced data sources were unavailable. Core page analysis completed."
                ),
                "source": "methodology",
            },
        ]
        result = deduplicate_limitations(raw)
        ids = [item.limitation_id for item in result]
        assert ids.count("discovery_incomplete") == 1
        assert ids.count("evidence_incomplete") == 1
        assert len(result) == 2

    def test_distinct_limitations_preserved(self) -> None:
        raw = [
            {"message": "Website discovery was incomplete.", "source": "a"},
            {"message": "Firefox was unavailable.", "source": "b"},
            {"message": "Automated accessibility evidence cannot prove compliance.", "source": "c"},
        ]
        result = deduplicate_limitations(raw)
        assert len(result) == 3

    def test_empty_messages_filtered(self) -> None:
        raw = [
            {"message": "", "source": "a"},
            {"message": "  ", "source": "b"},
            {"message": "Real limitation.", "source": "c"},
        ]
        result = deduplicate_limitations(raw)
        assert len(result) == 1


class TestBrowserUnavailableSemantics:
    def test_unavailable_browser_cannot_be_failed_or_partial(self) -> None:
        violations = check_invariants(
            discovered=10,
            eligible=5,
            scheduled=5,
            visited=5,
            successful=5,
            affected_eligible=3,
            browser_tested=0,
            browser_expected=15,
            section_statuses={"accessibility": "available"},
            category_evidence=[],
        )
        assert not any("browser" in v.lower() for v in violations)

    def test_browser_tested_cannot_exceed_expected(self) -> None:
        violations = check_invariants(
            discovered=10,
            eligible=5,
            scheduled=5,
            visited=5,
            successful=5,
            affected_eligible=3,
            browser_tested=20,
            browser_expected=15,
            section_statuses={},
            category_evidence=[],
        )
        assert any("browser_tested" in v for v in violations)


class TestScoreConfidenceVsReportConfidence:
    def test_confidence_components_are_separate(self) -> None:
        metrics = build_canonical_metrics(
            sections=[{"section_key": "s1", "status": "available", "content": {}}],
            page_coverage={
                "eligible_pages": 5,
                "successfully_analysed_pages": 5,
                "failed_pages": 0,
            },
            browser_compatibility={"engines": [{"tested_pages": 5, "eligible_pages": 5}]},
            score_categories=[
                {"category_id": "perf", "score": 80, "included": True},
            ],
            score_confidence=95.0,
            grouped_findings=[],
            eligible_urls=set(),
            report_confidence=66,
            confidence_components={
                "formula_determinism_percent": 95.0,
                "evidence_completeness_percent": 100.0,
                "analysed_page_coverage_percent": 100.0,
                "browser_coverage_percent": 66.0,
            },
            all_limitations=[],
        )
        assert metrics.formula_determinism_percent == 95.0
        assert metrics.report_confidence_percent == 66
        assert metrics.formula_determinism_percent != metrics.report_confidence_percent


class TestPageCountInvariants:
    def test_successful_cannot_exceed_visited(self) -> None:
        violations = check_invariants(
            discovered=20,
            eligible=10,
            scheduled=10,
            visited=5,
            successful=8,
            affected_eligible=3,
            browser_tested=0,
            browser_expected=0,
            section_statuses={},
            category_evidence=[],
        )
        assert any("successful" in v and "visited" in v for v in violations)

    def test_visited_cannot_exceed_scheduled(self) -> None:
        violations = check_invariants(
            discovered=20,
            eligible=10,
            scheduled=5,
            visited=8,
            successful=5,
            affected_eligible=3,
            browser_tested=0,
            browser_expected=0,
            section_statuses={},
            category_evidence=[],
        )
        assert any("visited" in v and "scheduled" in v for v in violations)

    def test_scheduled_cannot_exceed_eligible(self) -> None:
        violations = check_invariants(
            discovered=20,
            eligible=5,
            scheduled=10,
            visited=5,
            successful=5,
            affected_eligible=3,
            browser_tested=0,
            browser_expected=0,
            section_statuses={},
            category_evidence=[],
        )
        assert any("scheduled" in v and "eligible" in v for v in violations)

    def test_affected_eligible_cannot_exceed_eligible(self) -> None:
        violations = check_invariants(
            discovered=20,
            eligible=5,
            scheduled=5,
            visited=5,
            successful=5,
            affected_eligible=8,
            browser_tested=0,
            browser_expected=0,
            section_statuses={},
            category_evidence=[],
        )
        assert any("affected_eligible" in v and "eligible" in v for v in violations)

    def test_valid_counts_produce_no_violations(self) -> None:
        violations = check_invariants(
            discovered=20,
            eligible=10,
            scheduled=10,
            visited=10,
            successful=8,
            affected_eligible=5,
            browser_tested=15,
            browser_expected=30,
            section_statuses={},
            category_evidence=[],
        )
        assert violations == []


class TestActionPlanAvailabilityConsistency:
    def test_deterministic_fallback_produces_actions(self) -> None:
        from app.services.report_delivery import _deterministic_actions_from_findings

        findings = [
            {
                "finding_id": "f1",
                "issue_title": "Missing alt text",
                "severity": "medium",
                "category": "accessibility",
                "exact_occurrences": [{"normalized_url": "https://example.com/"}],
                "business_impact": "Screen reader users cannot understand images.",
                "recommendation": "Add descriptive alt text.",
                "evidence_references": [],
            },
        ]
        actions = _deterministic_actions_from_findings(findings)
        assert len(actions) >= 1
        assert actions[0]["title"] == "Missing alt text"
        assert actions[0]["generation_method"] == "deterministic_from_findings"

    def test_empty_findings_produce_no_actions(self) -> None:
        from app.services.report_delivery import _deterministic_actions_from_findings

        actions = _deterministic_actions_from_findings([])
        assert actions == []


class TestBrowserFindingGrouping:
    def test_browser_findings_from_different_pages_are_grouped(self) -> None:
        from app.services.report_delivery import _group_detailed_findings

        findings = [
            {
                "finding_id": "bf1",
                "finding_code": "browser_engine_compatibility",
                "issue_title": "Browser-engine compatibility differs on Homepage",
                "category": "browser_compatibility",
                "scope": "",
                "severity": "high",
                "exact_occurrences": [
                    {
                        "normalized_url": "https://example.com/",
                        "observed_value": "Chromium: compatible, Firefox: incompatible",
                        "browser_engines_affected": ["Firefox"],
                    },
                ],
                "evidence_references": [],
                "related_finding_ids": [],
            },
            {
                "finding_id": "bf2",
                "finding_code": "browser_engine_compatibility",
                "issue_title": "Browser-engine compatibility differs on About",
                "category": "browser_compatibility",
                "scope": "",
                "severity": "medium",
                "exact_occurrences": [
                    {
                        "normalized_url": "https://example.com/about",
                        "observed_value": "Chromium: compatible, Firefox: incompatible",
                        "browser_engines_affected": ["Firefox"],
                    },
                ],
                "evidence_references": [],
                "related_finding_ids": [],
            },
        ]
        grouped = _group_detailed_findings(findings)
        assert len(grouped) == 1
        assert grouped[0]["affected_page_count"] == 2
        assert "2 pages" in grouped[0]["issue_title"]

    def test_different_browser_engines_stay_separate(self) -> None:
        from app.services.report_delivery import _group_detailed_findings

        findings = [
            {
                "finding_id": "bf1",
                "finding_code": "browser_engine_compatibility",
                "issue_title": "Browser-engine compatibility differs on Homepage",
                "category": "browser_compatibility",
                "scope": "",
                "severity": "high",
                "exact_occurrences": [
                    {
                        "normalized_url": "https://example.com/",
                        "observed_value": "Firefox: incompatible",
                        "browser_engines_affected": ["Firefox"],
                    },
                ],
                "evidence_references": [],
                "related_finding_ids": [],
            },
            {
                "finding_id": "bf2",
                "finding_code": "browser_engine_compatibility",
                "issue_title": "Browser-engine compatibility differs on About",
                "category": "browser_compatibility",
                "scope": "",
                "severity": "medium",
                "exact_occurrences": [
                    {
                        "normalized_url": "https://example.com/about",
                        "observed_value": "WebKit: incompatible",
                        "browser_engines_affected": ["WebKit"],
                    },
                ],
                "evidence_references": [],
                "related_finding_ids": [],
            },
        ]
        grouped = _group_detailed_findings(findings)
        assert len(grouped) == 2


class TestExecutiveActionPlanUsesDetFallback:
    def test_deterministic_actions_appear_in_executive_structure(self) -> None:
        from app.services.report_delivery import _deterministic_actions_from_findings

        findings = [
            {
                "finding_id": "f1",
                "issue_title": "Missing heading hierarchy",
                "severity": "high",
                "category": "accessibility",
                "exact_occurrences": [{"normalized_url": "https://example.com/"}],
                "business_impact": "Impacts navigation.",
                "recommendation": "Fix heading levels.",
                "evidence_references": [],
            },
            {
                "finding_id": "f2",
                "issue_title": "Broken internal link",
                "severity": "medium",
                "category": "technical_quality",
                "exact_occurrences": [{"normalized_url": "https://example.com/about"}],
                "business_impact": "404 for visitors.",
                "recommendation": "Fix the link target.",
                "evidence_references": [],
            },
        ]
        ranked_actions: list[dict] = []
        final_actions = ranked_actions
        if not final_actions and findings:
            final_actions = _deterministic_actions_from_findings(findings)
        assert len(final_actions) == 2
        top_five = final_actions[:5]
        assert len(top_five) == 2
        assert top_five[0]["title"] == "Missing heading hierarchy"


class TestAccessibility100WithUnavailableEvidence:
    def test_invariant_flags_100_score_with_unavailable_section(self) -> None:
        cat = CategoryEvidence(
            category_id="accessibility",
            score=100,
            included=True,
            evidence_available=True,
            dedicated_audit_available=False,
            exclusion_reason=None,
            limitation=(
                "Score calculated from available formula inputs;"
                " dedicated accessibility audit evidence was unavailable."
            ),
        )
        violations = check_invariants(
            discovered=10,
            eligible=5,
            scheduled=5,
            visited=5,
            successful=5,
            affected_eligible=3,
            browser_tested=10,
            browser_expected=15,
            section_statuses={"accessibility": "unavailable"},
            category_evidence=[cat],
        )
        assert any("accessibility" in v.lower() for v in violations)


class TestFalse100GuardCoversAllScoreCategories:
    """M9 (docs/REPORT_QUALITY_INITIATIVE.md): the false-100%-complete
    guard only covered accessibility; a perfect score claimed on
    unavailable evidence in performance/seo/best_practices/
    technical_quality passed unchecked.
    """

    @staticmethod
    def _category(category_id: str) -> CategoryEvidence:
        return CategoryEvidence(
            category_id=category_id,
            score=100,
            included=True,
            evidence_available=True,
            dedicated_audit_available=False,
            exclusion_reason=None,
            limitation=None,
        )

    def _violations(self, category_id: str, section_statuses: dict[str, str]) -> list[str]:
        return check_invariants(
            discovered=10,
            eligible=5,
            scheduled=5,
            visited=5,
            successful=5,
            affected_eligible=3,
            browser_tested=10,
            browser_expected=15,
            section_statuses=section_statuses,
            category_evidence=[self._category(category_id)],
        )

    def test_performance_100_with_unavailable_section_is_flagged(self) -> None:
        violations = self._violations("performance", {"performance": "unavailable"})
        assert any("performance" in v for v in violations)

    def test_seo_100_with_unavailable_content_seo_section_is_flagged(self) -> None:
        violations = self._violations("seo", {"content_seo": "unavailable"})
        assert any("seo" in v for v in violations)

    def test_best_practices_100_with_unavailable_diagnostics_is_flagged(self) -> None:
        violations = self._violations("best_practices", {"site_diagnostics": "unavailable"})
        assert any("best_practices" in v for v in violations)

    def test_technical_quality_100_with_unavailable_diagnostics_is_flagged(self) -> None:
        violations = self._violations("technical_quality", {"site_diagnostics": "unavailable"})
        assert any("technical_quality" in v for v in violations)

    def test_100_with_available_section_is_not_flagged(self) -> None:
        violations = self._violations("performance", {"performance": "available"})
        assert violations == []

    def test_sub_100_score_is_not_flagged(self) -> None:
        category = CategoryEvidence(
            category_id="performance",
            score=95,
            included=True,
            evidence_available=True,
            dedicated_audit_available=False,
            exclusion_reason=None,
            limitation=None,
        )
        violations = check_invariants(
            discovered=10,
            eligible=5,
            scheduled=5,
            visited=5,
            successful=5,
            affected_eligible=3,
            browser_tested=10,
            browser_expected=15,
            section_statuses={"performance": "unavailable"},
            category_evidence=[category],
        )
        assert violations == []

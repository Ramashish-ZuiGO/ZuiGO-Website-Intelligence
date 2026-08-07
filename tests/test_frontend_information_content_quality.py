import json
import re
from pathlib import Path

ROOT = Path("apps/web/src")
EXPLANATIONS = ROOT / "components/metrics/explanations.ts"
REPORT = ROOT / "components/reports/ReportDeliveryPanel.tsx"

CALCULATION_REQUIRED = {
    "eligible_html_pages",
    "website_coverage",
    "evidence_completeness",
    "browser_coverage",
    "report_confidence",
    "occurrences",
    "unique_findings",
    "accessibility_inapplicable_rules",
    "report_action_plan",
    "repository_scan_coverage",
    "repository_match_confidence_detail",
    "action_high_priority",
}
DETAIL_FIELDS = (
    "meaning",
    "included",
    "excluded",
    "calculation",
    "interpretation",
    "limitation",
    "example",
)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower()).rstrip(".!?")


def _sentences(value: str) -> set[str]:
    return {
        _normalize(sentence) for sentence in re.split(r"(?<=[.!?])\s+", value) if sentence.strip()
    }


def _concepts() -> dict[str, dict[str, str]]:
    source = EXPLANATIONS.read_text(encoding="utf-8")
    registry = source.split(
        "const CONCEPT_EXPLANATIONS: Record<string, ExplanationContent> = {",
        maxsplit=1,
    )[1].split("\n};\n\nconst CALCULATED_CONCEPT_IDS", maxsplit=1)[0]
    concepts: dict[str, dict[str, str]] = {}
    for concept_id, body in re.findall(
        r"^  ([a-z0-9_]+): \{\n(.*?)^  \},$",
        registry,
        flags=re.MULTILINE | re.DOTALL,
    ):
        fields: dict[str, str] = {}
        for field in ("shortTooltip", *DETAIL_FIELDS, "detailsLink"):
            match = re.search(
                rf'{field}:\s*"((?:[^"\\]|\\.)*)"',
                body,
                flags=re.DOTALL,
            )
            if match:
                fields[field] = json.loads(f'"{match.group(1)}"')
        concepts[concept_id] = fields
    return concepts


def test_explanation_registry_has_specific_structured_content() -> None:
    concepts = _concepts()
    assert len(concepts) >= 29
    assert CALCULATION_REQUIRED <= concepts.keys()
    for concept_id, content in concepts.items():
        assert content["shortTooltip"].strip()
        assert content["meaning"].strip()
        assert content["included"].strip()
        assert content["excluded"].strip()
        assert _normalize(content["shortTooltip"]) != _normalize(concept_id.replace("_", " "))
        if concept_id in CALCULATION_REQUIRED:
            assert content.get("calculation", "").strip()


def test_eligible_pages_explains_determination_and_classification_limits() -> None:
    content = _concepts()["eligible_html_pages"]
    assert content["meaning"] == "Internal HTML pages suitable for website analysis."
    assert "Same-site URLs" in content["included"]
    for excluded in (
        "PDFs",
        "images",
        "videos",
        "external links",
        "duplicate URLs",
        "unsafe targets",
        "unsupported resources",
    ):
        assert excluded in content["excluded"]
    for step in (
        "normalization",
        "scope validation",
        "final-response inspection",
        "HTML document classification",
    ):
        assert step in content["calculation"]
    assert "not the number of raw URLs discovered" in content["interpretation"]
    assert "remain unclassified" in content["limitation"]


def test_unrelated_concepts_do_not_duplicate_detailed_content() -> None:
    owners: dict[str, str] = {}
    for concept_id, content in _concepts().items():
        fingerprint = "|".join(
            _normalize(content[field]) for field in DETAIL_FIELDS if content.get(field)
        )
        assert fingerprint not in owners, (
            f"{concept_id} duplicates detailed content from {owners.get(fingerprint)}"
        )
        owners[fingerprint] = concept_id


def test_tooltip_sentence_is_not_repeated_in_detailed_dialog() -> None:
    for concept_id, content in _concepts().items():
        tooltip_sentences = _sentences(content["shortTooltip"])
        detail_sentences = set().union(
            *(_sentences(content[field]) for field in DETAIL_FIELDS if content.get(field))
        )
        assert tooltip_sentences.isdisjoint(detail_sentences), concept_id


def test_quality_validation_is_central_and_runtime_retrieval_is_non_fatal() -> None:
    registry = EXPLANATIONS.read_text(encoding="utf-8")
    concept_button = (ROOT / "components/metrics/ConceptInfoButton.tsx").read_text(encoding="utf-8")
    metric_button = (ROOT / "components/metrics/MetricInfoButton.tsx").read_text(encoding="utf-8")
    for contract in (
        "validateExplanationContent",
        "validateExplanationSet",
        "short tooltip must add information",
        "visible description",
        "Exclusion details are required",
        "Calculation or determination details are required",
        "short tooltip sentence must not be repeated",
        "detailed content duplicates unrelated concept",
    ):
        assert contract in registry
    assert "validateExplanationRegistry" in registry
    assert "getSafeConceptExplanation" in concept_button
    assert "getSafeMetricExplanation" in metric_button
    assert "requireCalculation: CALCULATED_CONCEPT_IDS.has(conceptId)" in registry
    assert "assertExplanationContentQuality" not in concept_button
    assert "assertExplanationContentQuality" not in metric_button
    assert "throw new Error" not in concept_button
    assert "throw new Error" not in metric_button
    assert "if (!content) return null" in concept_button
    assert "if (!content) return null" in metric_button
    assert "console.error" not in concept_button + metric_button


def test_every_referenced_concept_exists_and_has_a_non_crashing_render_path() -> None:
    concepts = _concepts()
    referenced: set[str] = set()
    for path in ROOT.rglob("*.tsx"):
        source = path.read_text(encoding="utf-8")
        referenced.update(re.findall(r'conceptId="([a-z0-9_]+)"', source))
    assert referenced
    assert referenced <= concepts.keys()
    assert "eligible_html_pages" in referenced


def test_every_literal_metric_information_button_references_a_registered_metric() -> None:
    registry = (ROOT / "components/metrics/registry.ts").read_text(encoding="utf-8")
    registered = set(re.findall(r'metric_id:\s*"([a-z0-9_]+)"', registry))
    referenced: set[str] = set()
    surfaces_with_information = set()
    for path in ROOT.rglob("*.tsx"):
        source = path.read_text(encoding="utf-8")
        metric_ids = re.findall(
            r'<MetricInfoButton\s+metricId="([a-z0-9_]+)"',
            source,
        )
        if metric_ids:
            surfaces_with_information.add(path.name)
            referenced.update(metric_ids)
    assert referenced
    assert referenced <= registered
    assert {
        "PageAnalysisPanel.tsx",
        "WebsiteAnalysisPanel.tsx",
        "ActionPlanPanel.tsx",
        "AccessibilityIntelligence.tsx",
        "SiteDiagnosticsPanel.tsx",
    } <= surfaces_with_information


def test_information_icons_use_the_central_registry() -> None:
    direct_uses = []
    for path in ROOT.rglob("*.tsx"):
        if "<AccessibleExplanation" in path.read_text(encoding="utf-8"):
            direct_uses.append(path.relative_to(ROOT).as_posix())
    assert sorted(direct_uses) == [
        "components/metrics/ConceptInfoButton.tsx",
        "components/metrics/MetricInfoButton.tsx",
    ]


def test_project_coverage_labels_tolerate_unclassified_optional_metadata() -> None:
    coverage = (ROOT / "app/projects/[projectId]/WebsiteCoveragePanel.tsx").read_text(
        encoding="utf-8"
    )
    assert "value?.replaceAll" in coverage
    assert "Not classified" in coverage
    assert "Source unavailable" in coverage
    assert "item.page_type.replaceAll" not in coverage
    assert "item.discovery_source.replaceAll" not in coverage


def test_report_sections_and_key_counts_use_specific_concepts() -> None:
    report = REPORT.read_text(encoding="utf-8")
    for concept_id in (
        "report_executive_summary",
        "report_website_coverage",
        "report_scores",
        "report_top_findings",
        "report_browser_compatibility",
        "report_page_inventory",
        "report_action_plan",
        "report_limitations",
        "report_technical_details",
        "eligible_html_pages",
        "website_coverage",
        "browser_coverage",
        "evidence_completeness",
        "report_confidence",
        "unique_findings",
        "occurrences",
        "partial_browser_result",
    ):
        assert f'conceptId="{concept_id}"' in report

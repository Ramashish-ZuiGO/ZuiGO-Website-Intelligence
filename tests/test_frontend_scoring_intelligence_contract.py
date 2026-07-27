from pathlib import Path

PANEL = Path("apps/web/src/components/scoring/ScoringIntelligencePanel.tsx").read_text(
    encoding="utf-8"
)
CLIENT = Path("apps/web/src/lib/scoring-api.ts").read_text(encoding="utf-8")
REPORT = Path("apps/web/src/app/analysis-runs/[analysisRunId]/page.tsx").read_text(encoding="utf-8")
WEBSITE = Path("apps/web/src/app/projects/[projectId]/WebsiteAnalysisPanel.tsx").read_text(
    encoding="utf-8"
)
PAGE = Path("apps/web/src/app/projects/[projectId]/PageAnalysisPanel.tsx").read_text(
    encoding="utf-8"
)
ACTION = Path("apps/web/src/app/projects/[projectId]/ActionPlanPanel.tsx").read_text(
    encoding="utf-8"
)
AGENT = Path("apps/web/src/components/agents/AgentExecutionPanel.tsx").read_text(encoding="utf-8")


def test_exact_scoring_frontend_api_contract() -> None:
    for path in (
        "/analysis-runs/${runId}/scores/calculate",
        "/analysis-runs/${runId}/scores",
        "/websites/${websiteId}/scores",
        "/websites/${websiteId}/scores/history",
        "/scores/${executionId}",
        "/scores/${executionId}/breakdown",
        "/scoring/formulas",
        "/scoring/profiles",
    ):
        assert path in CLIENT
    assert "idempotency_key" in CLIENT
    for parameter in ("formula_version", "profile_id", "status", "limit", "offset"):
        assert parameter in CLIENT


def test_scoring_sections_and_distinct_unavailable_states() -> None:
    for heading in (
        "Overall Score Overview",
        "Category Score Breakdown",
        "Metric Contributions",
        "Evidence coverage",
        "Confidence and Limitations",
        "Score Explanation",
        "Historical Trends",
        "Formula and Profile Details",
    ):
        assert heading in PANEL
    assert "Score not yet calculated" in PANEL
    assert "This is not a zero score" in PANEL
    assert "Excluded metric" in PANEL
    assert "Incompatible" in PANEL
    assert "Unavailable" in PANEL


def test_scoring_accessibility_safe_rendering_and_no_llm_calculation() -> None:
    assert "aria-labelledby" in PANEL
    assert 'role="alert"' in PANEL
    assert 'role="status"' in PANEL
    assert "focus-visible:outline" in PANEL
    assert 'type="button"' in PANEL
    assert "SafeStructuredValue" in PANEL
    assert "dangerouslySetInnerHTML" not in PANEL
    assert "An LLM cannot calculate or" in PANEL


def test_scoring_integrates_all_required_frontend_surfaces() -> None:
    assert "<ScoringIntelligencePanel" in REPORT
    assert "Score explanation" in REPORT
    assert "<ScoringIntelligencePanel" in WEBSITE
    assert "Review explainable site score" in PAGE
    assert "Review score contributions" in ACTION
    assert "Review persisted scoring execution and contributions" in AGENT

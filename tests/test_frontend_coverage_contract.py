from pathlib import Path


def test_coverage_interface_explains_empty_state_formula_reasons_and_information_icons() -> None:
    source = Path("apps/web/src/app/projects/[projectId]/WebsiteCoveragePanel.tsx").read_text(
        encoding="utf-8"
    )
    assert "No discovery run yet" in source
    assert "analyzed_coverage_numerator" in source
    assert "analyzed_coverage_denominator" in source
    assert "exclusion_reason || item.skip_reason" in source
    for explanation in (
        "discovered",
        "eligible",
        "coverage",
        "excluded",
        "skipped",
        "robots",
        "depth",
        "limit",
    ):
        assert f"{explanation}:" in source

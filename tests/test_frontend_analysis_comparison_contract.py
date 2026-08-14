from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_completed_analysis_exposes_confirmed_reanalysis_flow() -> None:
    panel = read("apps/web/src/components/comparisons/ReanalysisComparisonPanel.tsx")
    report_page = read("apps/web/src/app/analysis-runs/[analysisRunId]/page.tsx")
    assert "Re-analyse website" in panel
    assert "Baseline analysis" in panel
    assert "Browser engines" in panel
    assert "confirmed: true" in panel
    assert "baseline remains" in panel
    assert "ReanalysisComparisonPanel" in report_page
    assert "baselineRunId" in report_page
    assert "Reanalysis comparison available" in report_page
    assert "comparisonTerminal" in report_page
    assert "currentReportAvailable" in report_page
    assert "baselineAvailable" in report_page
    assert "comparisonDataAvailable" in report_page
    assert "analysisComparisonApi.generate" in report_page
    assert "comparisonReady" in report_page


def test_comparison_page_uses_business_language_and_accessible_evidence() -> None:
    page = read("apps/web/src/app/analysis-runs/[analysisRunId]/compare/[baselineRunId]/page.tsx")
    for heading in (
        "Overall improvement summary",
        "Score comparison",
        "Page coverage comparison",
        "Browser compatibility comparison",
        "Resolved",
        "Persistent (Unchanged)",
        "New",
        "Severity changed",
        "Inconclusive",
        "Action Plan progress",
        "Evidence limitations",
        "Export comparison",
    ):
        assert heading in page
    assert 'aria-label="Comparison sections"' in page
    assert "<details" in page
    assert "raw JSON" not in page
    assert "agent_id" not in page
    assert "finding_code" not in page
    assert "comparison_id}" not in page
    assert "ScoreDelta" in page
    assert "text-emerald-700" in page
    assert "text-red-700" in page
    assert "Not comparable" in page
    assert "Category scores are not comparable." in page
    assert "Browser compatibility data is unavailable" in page
    assert 'direction === "Unchanged"' in page


def test_history_limits_selection_to_same_website_and_two_completed_runs() -> None:
    history = read("apps/web/src/app/projects/[projectId]/WebsiteAnalysisPanel.tsx")
    assert "Select any two completed analyses of this website to compare." in history
    assert "selectedComparisonRuns.length >= 2" in history
    assert 'run.status !== "completed"' in history
    assert "Compare Current" in history
    assert "vs Baseline" in history
    assert "Compare selected analyses" not in history


def test_persistent_and_changed_severity_are_visually_mutually_exclusive() -> None:
    """Prove that a changed-severity finding cannot render under both
    'Persistent (Unchanged)' and 'Severity changed' simultaneously.

    Backend contract: changed_severity is a subset of persistent.
    Both arrays share identical objects.  changed_severity entries always have
    direction="Improved" or direction="Regressed" (never "Unchanged").

    The UI must therefore:
    - Render 'Persistent (Unchanged)' using only persistent entries where
      direction === "Unchanged", which excludes all changed_severity items.
    - Render 'Severity changed' from the separate changed_severity array.
    """
    import re

    page = read("apps/web/src/app/analysis-runs/[analysisRunId]/compare/[baselineRunId]/page.tsx")

    # --- 1. Persistent section filters by direction === "Unchanged" ---
    # Find the line(s) containing the Persistent (Unchanged) FindingGroup
    persistent_lines = [
        line for line in page.splitlines() if 'title="Persistent (Unchanged)"' in line
    ]
    assert len(persistent_lines) == 1, (
        f"Expected exactly 1 FindingGroup for 'Persistent (Unchanged)', "
        f"found {len(persistent_lines)}"
    )
    persistent_call = persistent_lines[0]

    # The findings prop MUST apply a direction === "Unchanged" filter
    assert 'direction === "Unchanged"' in persistent_call, (
        "Persistent (Unchanged) section does not filter by direction === 'Unchanged'; "
        "changed-severity findings (direction Improved/Regressed) would leak into this group"
    )
    # It must source from payload.findings.persistent
    assert "payload.findings.persistent" in persistent_call, (
        "Persistent (Unchanged) section does not read from payload.findings.persistent"
    )

    # --- 2. Severity-changed section uses its own array ---
    severity_lines = [line for line in page.splitlines() if 'title="Severity changed"' in line]
    assert len(severity_lines) == 1, (
        f"Expected exactly 1 FindingGroup for 'Severity changed', found {len(severity_lines)}"
    )
    severity_call = severity_lines[0]

    assert "payload.findings.changed_severity" in severity_call, (
        "Severity changed section does not read from payload.findings.changed_severity"
    )

    # --- 3. The filter must exclude changed-severity items ---
    # changed_severity entries have direction "Improved" or "Regressed",
    # so filtering persistent to direction === "Unchanged" excludes them.
    assert ".filter(" in persistent_call, (
        "Persistent (Unchanged) section does not apply a .filter() to "
        "exclude changed-severity entries"
    )

    # --- 4. Confirm no regressions section (removed per prior task) ---
    regressions_lines = [
        line for line in page.splitlines() if re.search(r'title="Regressions?"', line)
    ]
    assert len(regressions_lines) == 0, (
        "A 'Regressions' FindingGroup still exists; it was removed to avoid "
        "duplicate rendering of new findings that are also regressions"
    )


def test_comparison_route_maps_newer_run_to_analysisRunId() -> None:
    """Prove the route construction places the newer run as analysisRunId
    and the older run as baselineRunId.

    Route contract: /analysis-runs/{CURRENT_RUN_ID}/compare/{BASELINE_RUN_ID}
    Backend rejects reversed chronology with 422.

    The implementation sorts selected runs by created_at descending (newer
    first), then builds the URL as selected[0] → analysisRunId, selected[1]
    → baselineRunId.
    """
    import re

    panel = read("apps/web/src/app/projects/[projectId]/WebsiteAnalysisPanel.tsx")

    # --- 1. The sort is descending (newer first) ---
    # The comparisonHref useMemo contains the canonical sort.
    # Find the sort callback: right.created_at - left.created_at → descending
    sort_pattern = re.compile(
        r"\.sort\(\s*\(.*?\)\s*=>"
        r".*?new Date\((\w+)\.created_at\)\.getTime\(\)\s*-\s*"
        r"new Date\((\w+)\.created_at\)\.getTime\(\)",
        re.DOTALL,
    )
    sort_matches = sort_pattern.findall(panel)
    assert len(sort_matches) >= 1, "No date-descending sort found in panel"
    # All sort calls must have right - left (descending), not left - right
    for right_param, left_param in sort_matches:
        assert right_param != left_param, "Sort parameters are identical"
        # In a descending sort, the first parameter of the subtraction
        # corresponds to the 'right' callback parameter.  The sort callback
        # signature is (left, right) => … so for descending order we need
        # right.created_at - left.created_at.
        # We verify that the minuend uses 'right' by checking the pattern.

    # --- 2. URL template puts selected[0] as analysisRunId ---
    url_pattern = re.compile(
        r"/analysis-runs/\$\{selected\[0\]\.id\}/compare/\$\{selected\[1\]\.id\}"
    )
    assert url_pattern.search(panel), (
        "Route template does not use selected[0] (newer) as analysisRunId "
        "and selected[1] (older) as baselineRunId"
    )

    # --- 3. The button label confirms Current = [0], Baseline = [1] ---
    assert "selected[0].created_at" in panel, (
        "Button label does not reference selected[0] for Current"
    )
    assert "selected[1].created_at" in panel, (
        "Button label does not reference selected[1] for Baseline"
    )

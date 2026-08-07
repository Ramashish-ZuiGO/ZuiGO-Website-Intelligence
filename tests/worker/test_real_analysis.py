import inspect
from types import SimpleNamespace

import pytest
from worker_app.tasks import real_analysis


def test_real_browser_collection_uses_the_configured_page_limit() -> None:
    assert not hasattr(real_analysis, "REAL_BROWSER_PAGE_SAMPLE_LIMIT")
    assert real_analysis.REAL_BROWSER_NAVIGATION_TIMEOUT_MS == 15_000
    source = inspect.getsource(real_analysis.collect_real_browser_compatibility)
    assert "browser_page_limit = browser_eligible_count" in source
    assert "browser_eligible_count = len(page_records)" in source
    assert 'PageAnalysisRun.status.in_(("completed", "partial"))' not in source
    assert "selected_page_ids" in source
    assert "ResourceClassification.ELIGIBLE_HTML_PAGE" in source


def test_real_analysis_dispatches_deterministic_stage_chain_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution_id = "00000000-0000-0000-0000-000000000004"
    captured: list[object] = []
    monkeypatch.setattr(
        real_analysis,
        "_begin_journey",
        lambda _execution_id: (
            SimpleNamespace(status="running", attempt=1),
            True,
        ),
    )
    monkeypatch.setattr(
        real_analysis.run_real_analysis_journey,
        "replace",
        lambda pipeline: captured.extend(pipeline.tasks) or {"status": "replaced"},
    )

    result = real_analysis.run_real_analysis_journey.run(
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000003",
        execution_id,
    )

    assert result == {"status": "replaced"}
    assert [task.task for task in captured] == [
        "worker.run_real_discovery_stage",
        "worker.run_real_page_analysis_stage",
        "worker.run_real_primary_analysis_stage",
        "worker.run_real_browser_stage",
        "worker.run_real_agent_stage",
    ]
    expected_ids = real_analysis.real_stage_task_ids(execution_id, 1)
    assert [task.options["task_id"] for task in captured] == list(expected_ids.values())


def test_duplicate_real_dispatch_is_reused_without_replacing_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replacements: list[object] = []
    monkeypatch.setattr(
        real_analysis,
        "_begin_journey",
        lambda _execution_id: (
            SimpleNamespace(status="running", attempt=1),
            False,
        ),
    )
    monkeypatch.setattr(
        real_analysis.run_real_analysis_journey,
        "replace",
        lambda pipeline: replacements.append(pipeline),
    )
    result = real_analysis.run_real_analysis_journey.run(
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000003",
        "00000000-0000-0000-0000-000000000004",
    )
    assert result["status"] == "running"
    assert replacements == []


def test_cancelled_execution_skips_redelivered_stage_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution_id = "00000000-0000-0000-0000-000000000004"
    monkeypatch.setattr(
        real_analysis,
        "_execution",
        lambda _execution_id: SimpleNamespace(status="cancelled"),
    )

    def blocked(*_args, **_kwargs):
        raise AssertionError("cancelled stage executed")

    monkeypatch.setattr(real_analysis.run_discovery, "run", blocked)
    monkeypatch.setattr(real_analysis.run_page_analysis, "run", blocked)
    monkeypatch.setattr(real_analysis.run_analysis, "run", blocked)
    monkeypatch.setattr(real_analysis, "collect_real_browser_compatibility", blocked)
    monkeypatch.setattr(real_analysis.run_workflow_execution, "run", blocked)

    calls = (
        real_analysis.run_real_discovery_stage.run("discovery", execution_id),
        real_analysis.run_real_page_analysis_stage.run(
            "discovery",
            "page-execution",
            execution_id,
        ),
        real_analysis.run_real_primary_analysis_stage.run(
            "analysis",
            "discovery",
            execution_id,
        ),
        real_analysis.run_real_browser_stage.run("discovery", execution_id),
        real_analysis.run_real_agent_stage.run(execution_id),
    )
    assert all(item["status"] == "cancelled" for item in calls)
    assert all(item["skipped"] is True for item in calls)


def test_resume_reuses_retained_primary_failure_when_page_evidence_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution_id = "00000000-0000-0000-0000-000000000004"
    updates: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(
        real_analysis,
        "_skip_terminal_stage",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        real_analysis,
        "_execution",
        lambda _execution_id: SimpleNamespace(
            status="pending",
            attempt=2,
            structured_output={"primary_analysis_status": "failed"},
        ),
    )
    monkeypatch.setattr(real_analysis, "_usable_page_count", lambda *_args: 3)
    monkeypatch.setattr(
        real_analysis,
        "_update_journey_stage",
        lambda *args, **kwargs: updates.append((args, kwargs)),
    )
    monkeypatch.setattr(
        real_analysis.run_analysis,
        "run",
        lambda *_args: (_ for _ in ()).throw(AssertionError("primary analysis reran")),
    )

    result = real_analysis.run_real_primary_analysis_stage.run(
        "analysis",
        "discovery",
        execution_id,
    )
    assert result == {
        "status": "failed",
        "continued_with_page_evidence": True,
        "retry_skipped": True,
    }
    assert updates[0][0] == (execution_id, "browser_compatibility")
    assert updates[0][1]["additional_output"] == {
        "primary_analysis_status": "failed",
        "primary_analysis_retry_skipped": True,
    }


def test_real_analysis_never_substitutes_demo_after_discovery_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failures: list[tuple[str, str, str, bool]] = []
    monkeypatch.setattr(
        real_analysis,
        "_update_journey_stage",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        real_analysis,
        "_skip_terminal_stage",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        real_analysis.run_discovery,
        "run",
        lambda _run_id: (_ for _ in ()).throw(RuntimeError("discovery failed")),
    )
    monkeypatch.setattr(
        real_analysis,
        "_mark_stage_failed",
        lambda _execution_id, stage, code, _message, transient: failures.append(
            (stage, code, "failed", transient)
        ),
    )

    with pytest.raises(RuntimeError, match="discovery failed"):
        real_analysis.run_real_discovery_stage.run(
            "00000000-0000-0000-0000-000000000002",
            "00000000-0000-0000-0000-000000000004",
        )
    assert failures == [
        (
            "website_discovery",
            "DISCOVERY_PREREQUISITE_FAILED",
            "failed",
            False,
        )
    ]

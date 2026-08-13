from pathlib import Path

PANEL_PATH = Path("apps/web/src/components/agents/AgentExecutionPanel.tsx")
GRAPH_PATH = Path("apps/web/src/components/agents/DependencyGraph.tsx")
SAFE_VALUE_PATH = Path("apps/web/src/components/agents/SafeStructuredValue.tsx")
CLIENT_PATH = Path("apps/web/src/lib/agent-platform-api.ts")
API_PATH = Path("apps/web/src/lib/api.ts")
REPORT_PATH = Path("apps/web/src/app/analysis-runs/[analysisRunId]/page.tsx")
WEBSITE_PANEL_PATH = Path("apps/web/src/app/projects/[projectId]/WebsiteAnalysisPanel.tsx")
ACTION_PLAN_PATH = Path("apps/web/src/app/projects/[projectId]/ActionPlanPanel.tsx")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_workflow_listing_selection_start_and_idempotency_contract() -> None:
    panel = read(PANEL_PATH)
    client = read(CLIENT_PATH)

    assert "listWorkflows()" in panel
    assert "selectedWorkflowId" in panel
    assert "Start workflow" in panel
    assert "idempotency_key: requestedIdempotencyKey" in panel
    assert 'apiRequest<WorkflowExecution>("/api/v1/workflow-executions"' in client


def test_dependency_graph_parallel_and_conditional_repository_contract() -> None:
    graph = read(GRAPH_PATH)

    assert "workflowStages" in graph
    assert "deterministic_order" in graph
    assert "parallel branches" in graph
    assert 'condition === "repository_configured"' in graph
    assert "conditional stage" in graph
    assert "Deterministic text alternative" in graph


def test_execution_states_progress_and_recovery_controls() -> None:
    panel = read(PANEL_PATH)

    for status in (
        "running",
        "completed",
        "failed",
        "partial",
        "cancelled",
        "unavailable",
    ):
        assert f'"{status}"' in panel
    for label in (
        "Execution Progress",
        "Cancel execution",
        "Resume from checkpoint",
        "Retry failed agent",
        "Completed-agent checkpoints",
    ):
        assert label in panel
    assert "Completed runs remain immutable" in panel


def test_tool_evidence_artifact_and_unavailable_provider_contract() -> None:
    panel = read(PANEL_PATH)

    for label in (
        "Tool Activity",
        "Evidence and Artifacts",
        "Evidence references are unavailable",
        "No artifact storage reference",
        "deterministic fallback",
        "unavailable",
    ):
        assert label in panel
    assert "tool_activity_summary" in panel
    assert "evidence_references" in panel


def test_run_and_event_filtering_and_pagination_contract() -> None:
    panel = read(PANEL_PATH)
    client = read(CLIENT_PATH)

    for value in (
        "runAgentFilter",
        "runStatusFilter",
        "eventTypeFilter",
        "eventStatusFilter",
        "Previous runs",
        "Next runs",
        "Previous events",
        "Next events",
    ):
        assert value in panel
    for parameter in ("agent_id", "event_type", "status", "limit", "offset"):
        assert parameter in client


def test_safe_errors_costs_and_private_reasoning_filter() -> None:
    panel = read(PANEL_PATH)
    safe_value = read(SAFE_VALUE_PATH)
    api = read(API_PATH)

    assert 'role="alert"' in panel
    assert 'aria-live="assertive"' in panel
    assert "Not used or unavailable" in panel
    assert "token_total" in panel
    assert "cost_total_usd" in panel
    assert "PRIVATE_KEYS" in safe_value
    assert '"chainofthought"' in safe_value
    assert '"hiddenreasoning"' in safe_value
    assert '"password"' in safe_value
    assert '"apikey"' in safe_value
    assert "dangerouslySetInnerHTML" not in panel
    assert "dangerouslySetInnerHTML" not in safe_value
    for status in ("404", "409", "422"):
        assert status in panel
    assert "export class ApiError" in api


def test_semantic_keyboard_and_status_accessibility_contract() -> None:
    panel = read(PANEL_PATH)
    graph = read(GRAPH_PATH)

    assert 'role="progressbar"' in panel
    assert "aria-valuenow" in panel
    assert "aria-labelledby" in panel
    assert "focus-visible:outline" in panel
    assert 'type="button"' in panel
    assert "Status:" in graph
    assert "<ol" in graph
    assert "aria-describedby" in graph


def test_agent_interface_is_integrated_with_required_surfaces() -> None:
    report = read(REPORT_PATH)
    website_panel = read(WEBSITE_PANEL_PATH)
    action_plan = read(ACTION_PLAN_PATH)

    assert "<AgentExecutionPanel" in report
    assert "Agent Execution" in report
    assert "<AgentExecutionPanel" in website_panel
    assert "projectId={projectId}" in website_panel
    assert "Review agent execution evidence" in action_plan
    assert "#agent-execution-${websiteId}" in action_plan


def test_frontend_backend_api_contract_paths_align() -> None:
    client = read(CLIENT_PATH)
    metadata_routes = read(Path("apps/api/app/api/routes/agent_platform.py"))
    execution_routes = read(Path("apps/api/app/api/routes/workflow_executions.py"))

    metadata_paths = (
        "/agents",
        "/agents/{agent_id}",
        "/tools",
        "/tools/{tool_id}",
        "/workflows",
        "/workflows/{workflow_id}",
    )
    execution_paths = (
        "/workflow-executions",
        "/workflow-executions/{execution_id}",
        "/workflow-executions/{execution_id}/runs",
        "/workflow-executions/{execution_id}/events",
        "/workflow-executions/{execution_id}/cancel",
        "/workflow-executions/{execution_id}/resume",
        "/agent-runs/{run_id}/retry",
    )

    for path in metadata_paths:
        assert f'"{path}"' in metadata_routes
        assert path.split("{")[0] in client
    for path in execution_paths:
        assert f'"{path}"' in execution_routes
        assert path.split("{")[0] in client

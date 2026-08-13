import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from app.db.base import Base
from app.models import (
    AgentArtifact,
    AgentCheckpoint,
    AgentEvent,
    AgentExecution,
    AgentRun,
    Project,
    Website,
)
from app.schemas.agent_platform import (
    AgentDefinition,
    ExecutionStatus,
    RepositoryAnalysisInput,
    WorkflowExecutionCreate,
)
from app.services.agent_platform_registry import (
    AgentRegistry,
    ToolRegistry,
    WorkflowRegistry,
)
from app.services.tool_execution import (
    FunctionalToolAdapter,
    ToolAdapterRegistry,
    ToolContext,
    ToolExecutionError,
    ToolExecutionManager,
    ToolResult,
    default_tool_adapters,
    sanitize_persisted_value,
)
from app.services.workflow_execution import (
    AGENT_TOOL_PLAN,
    DeterministicWorkflowOrchestrator,
    WorkflowExecutionError,
    cancel_execution,
    create_workflow_execution,
    prepare_resume,
    validate_agent_retry,
)
from pydantic import BaseModel
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

SessionFactory = sessionmaker[Session]
ToolBehavior = Callable[[ToolContext, BaseModel], ToolResult]


def _session_factory(tmp_path: Path) -> SessionFactory:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'agent-platform.sqlite3'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed_scope(factory: SessionFactory) -> tuple[uuid.UUID, uuid.UUID]:
    with factory() as db:
        project = Project(name="Agent Platform")
        db.add(project)
        db.flush()
        website = Website(
            project_id=project.id,
            name="Local fixture",
            url="https://example.test/",
        )
        db.add(website)
        db.commit()
        return project.id, website.id


def _request(
    project_id: uuid.UUID,
    website_id: uuid.UUID,
    *,
    key: str = "workflow-key",
    concurrency: int = 3,
) -> WorkflowExecutionCreate:
    return WorkflowExecutionCreate(
        workflow_id="full_website_analysis",
        project_id=project_id,
        website_id=website_id,
        idempotency_key=key,
        max_concurrency=concurrency,
    )


def _completed_result(tool_id: str) -> ToolResult:
    return ToolResult(
        status=ExecutionStatus.COMPLETED,
        structured_output={"tool_id": tool_id, "result": "retained"},
        evidence_references=[
            {
                "evidence_type": tool_id,
                "evidence_id": str(uuid.uuid5(uuid.NAMESPACE_URL, tool_id)),
                "source": "local_fake",
            }
        ],
        provider_version_metadata={"provider": "local_fake", "version": "1.0.0"},
    )


def _tool_manager(
    behaviors: dict[str, ToolBehavior] | None = None,
) -> ToolExecutionManager:
    configured = behaviors or {}
    adapters = []
    for definition in ToolRegistry.get_all():
        tool_id = definition.tool_id

        def handler(
            context: ToolContext,
            typed_input: BaseModel,
            *,
            selected_tool_id: str = tool_id,
        ) -> ToolResult:
            behavior = configured.get(selected_tool_id)
            if behavior is not None:
                return behavior(context, typed_input)
            return _completed_result(selected_tool_id)

        adapters.append(FunctionalToolAdapter(tool_id, handler))
    return ToolExecutionManager(
        ToolAdapterRegistry(adapters),
        sleeper=lambda _seconds: None,
    )


def _create(
    factory: SessionFactory,
    request: WorkflowExecutionCreate,
) -> AgentExecution:
    with factory() as db:
        execution, created = create_workflow_execution(db, request)
        assert created
        return execution


def test_exact_workflow_batches_and_parallel_branch_order() -> None:
    workflow = WorkflowRegistry.get("full_website_analysis")
    assert workflow is not None
    assert DeterministicWorkflowOrchestrator.execution_batches(
        workflow,
        repository_configured=False,
    ) == (
        ("discovery_agent",),
        (
            "accessibility_agent",
            "performance_agent",
            "site_diagnostics_agent",
        ),
        ("evidence_validation_agent",),
        ("remediation_agent",),
        ("report_agent",),
    )
    assert DeterministicWorkflowOrchestrator.execution_batches(
        workflow,
        repository_configured=True,
    ) == (
        ("discovery_agent",),
        (
            "accessibility_agent",
            "performance_agent",
            "site_diagnostics_agent",
        ),
        ("evidence_validation_agent",),
        ("repository_intelligence_agent",),
        ("remediation_agent",),
        ("report_agent",),
    )


def test_orchestrator_runs_parallel_branches_and_persists_deterministic_history(
    tmp_path: Path,
) -> None:
    factory = _session_factory(tmp_path)
    project_id, website_id = _seed_scope(factory)
    execution = _create(factory, _request(project_id, website_id))
    barrier = threading.Barrier(3)

    def parallel_behavior(_context: ToolContext, _input: BaseModel) -> ToolResult:
        barrier.wait(timeout=10)
        return _completed_result("parallel_branch")

    manager = _tool_manager(
        {
            "axe_accessibility": parallel_behavior,
            "playwright_analysis": parallel_behavior,
            "site_diagnostics": parallel_behavior,
        }
    )
    result = DeterministicWorkflowOrchestrator(
        factory,
        tool_manager=manager,
    ).execute(execution.execution_id)

    assert result.status == ExecutionStatus.COMPLETED.value
    with factory() as db:
        persisted = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == execution.execution_id)
        )
        assert persisted is not None
        runs = list(
            db.scalars(
                select(AgentRun)
                .where(AgentRun.execution_id == persisted.id)
                .order_by(AgentRun.created_at, AgentRun.agent_id)
            )
        )
        assert {run.agent_id for run in runs} == {
            "discovery_agent",
            "performance_agent",
            "accessibility_agent",
            "site_diagnostics_agent",
            "evidence_validation_agent",
            "remediation_agent",
            "report_agent",
        }
        assert all(run.status == ExecutionStatus.COMPLETED.value for run in runs)
        assert db.query(AgentCheckpoint).filter_by(execution_id=persisted.id).count() == 7
        assert db.query(AgentArtifact).filter_by(execution_id=persisted.id).count() == 7
        events = list(
            db.scalars(
                select(AgentEvent)
                .where(AgentEvent.execution_id == persisted.id)
                .order_by(AgentEvent.sequence_number)
            )
        )
        assert [event.sequence_number for event in events] == list(range(9))
        assert events[0].event_type == "execution_started"
        assert events[-1].event_type == "execution_completed"


def test_scoped_idempotency_prevents_duplicate_execution_and_preserves_history(
    tmp_path: Path,
) -> None:
    factory = _session_factory(tmp_path)
    project_id, website_id = _seed_scope(factory)
    request = _request(project_id, website_id)
    with factory() as db:
        first, created_first = create_workflow_execution(db, request)
        repeated, created_repeated = create_workflow_execution(db, request)
        independent, created_independent = create_workflow_execution(
            db,
            _request(project_id, website_id, key="independent-history"),
        )
        assert created_first
        assert not created_repeated
        assert created_independent
        assert repeated.execution_id == first.execution_id
        assert independent.execution_id != first.execution_id
        assert db.query(AgentExecution).count() == 2

        with pytest.raises(WorkflowExecutionError, match="different workflow input"):
            create_workflow_execution(
                db,
                _request(
                    project_id,
                    website_id,
                    key=request.idempotency_key,
                    concurrency=1,
                ),
            )


def test_tool_access_permission_unavailable_and_retry_behavior(
    tmp_path: Path,
) -> None:
    factory = _session_factory(tmp_path)
    project_id, website_id = _seed_scope(factory)
    execution = _create(factory, _request(project_id, website_id))
    with factory() as db:
        persisted = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == execution.execution_id)
        )
        assert persisted is not None
        definition = AgentRegistry.get("discovery_agent")
        assert definition is not None
        run = AgentRun(
            execution_id=persisted.id,
            agent_id=definition.agent_id,
            agent_version=definition.version,
            input_fingerprint=persisted.input_fingerprint,
            idempotency_key="direct-tool-test",
            structured_input={},
        )
        db.add(run)
        db.flush()
        context = ToolContext(
            db=db,
            execution=persisted,
            agent_run=run,
            agent_definition=definition,
            execution_input=persisted.structured_input,
            dependency_evidence=[],
        )
        empty_manager = ToolExecutionManager(ToolAdapterRegistry([]))
        unavailable = empty_manager.execute(
            context=context,
            tool_id="website_discovery",
            payload={
                "project_id": str(project_id),
                "website_id": str(website_id),
            },
        )
        assert unavailable.result.status == ExecutionStatus.UNAVAILABLE

        with pytest.raises(ToolExecutionError, match="not allowed"):
            empty_manager.execute(
                context=context,
                tool_id="evidence_retrieval",
                payload={
                    "execution_id": str(persisted.execution_id),
                    "evidence_references": [],
                },
            )

        permission_limited: AgentDefinition = definition.model_copy(
            update={"allowed_tool_ids": ("repository_scanning",)}
        )
        context.agent_definition = permission_limited
        with pytest.raises(ToolExecutionError, match="required permissions"):
            empty_manager.execute(
                context=context,
                tool_id="repository_scanning",
                payload={
                    "project_id": str(project_id),
                    "repository_connection_id": str(uuid.uuid4()),
                },
            )
        db.commit()

    attempts = 0

    def transient_then_success(
        _context: ToolContext,
        _input: BaseModel,
    ) -> ToolResult:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ToolExecutionError(
                "temporary_unavailable",
                "Temporary local fake failure.",
                transient=True,
            )
        return _completed_result("website_discovery")

    with factory() as db:
        persisted = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == execution.execution_id)
        )
        assert persisted is not None
        run = db.scalar(select(AgentRun).where(AgentRun.execution_id == persisted.id))
        assert run is not None
        definition = AgentRegistry.get("discovery_agent")
        assert definition is not None
        record = _tool_manager({"website_discovery": transient_then_success}).execute(
            context=ToolContext(
                db=db,
                execution=persisted,
                agent_run=run,
                agent_definition=definition,
                execution_input=persisted.structured_input,
                dependency_evidence=[],
            ),
            tool_id="website_discovery",
            payload={
                "project_id": str(project_id),
                "website_id": str(website_id),
            },
        )
        assert record.result.status == ExecutionStatus.COMPLETED
        assert record.activity["attempts"] == 2


def test_repository_agent_accepts_explicit_not_configured_state() -> None:
    typed = RepositoryAnalysisInput(
        project_id=uuid.uuid4(),
        repository_connection_id=None,
    )
    assert typed.repository_connection_id is None
    assert typed.evidence_references == []


def test_browser_compatibility_evidence_is_retained_without_primary_result(
    tmp_path: Path,
) -> None:
    factory = _session_factory(tmp_path)
    project_id, website_id = _seed_scope(factory)
    execution = _create(factory, _request(project_id, website_id))
    with factory() as db:
        persisted = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == execution.execution_id)
        )
        assert persisted is not None
        definition = AgentRegistry.get("performance_agent")
        assert definition is not None
        run = AgentRun(
            execution_id=persisted.id,
            agent_id=definition.agent_id,
            agent_version=definition.version,
            input_fingerprint=persisted.input_fingerprint,
            idempotency_key="browser-evidence-fallback",
            structured_input={},
        )
        db.add(run)
        db.flush()
        artifact = AgentArtifact(
            execution_id=persisted.id,
            agent_run_id=run.id,
            artifact_type="browser_compatibility_evidence",
            name="Browser compatibility evidence",
            storage_reference=f"database://agent-executions/{persisted.execution_id}/browser",
            content_hash="a" * 64,
            media_type="application/json",
            artifact_metadata={
                "status": "completed",
                "engines": ["chromium", "firefox", "webkit"],
                "matrix": [{"page_url": "https://example.test/"}],
            },
            evidence_references=[
                {
                    "evidence_type": "browser_compatibility_evidence",
                    "evidence_id": str(persisted.execution_id),
                    "source": "database",
                }
            ],
        )
        db.add(artifact)
        db.flush()
        result = (
            ToolExecutionManager(
                default_tool_adapters(),
                sleeper=lambda _seconds: None,
            )
            .execute(
                context=ToolContext(
                    db=db,
                    execution=persisted,
                    agent_run=run,
                    agent_definition=definition,
                    execution_input=persisted.structured_input,
                    dependency_evidence=[],
                ),
                tool_id="playwright_analysis",
                payload={
                    "execution_id": persisted.execution_id,
                    "page_url": "https://example.test/",
                },
            )
            .result
        )
        assert result.status == ExecutionStatus.PARTIAL
        assert result.structured_output["browser_engine_evidence_available"] is True
        assert result.structured_output["browser_engine_count"] == 3
        assert result.structured_output["browser_matrix_page_count"] == 1
        assert len(result.evidence_references) == 1


def test_partial_failure_preserves_successful_branch_and_no_private_reasoning(
    tmp_path: Path,
) -> None:
    factory = _session_factory(tmp_path)
    project_id, website_id = _seed_scope(factory)
    execution = _create(factory, _request(project_id, website_id))

    def accessibility_failure(
        _context: ToolContext,
        _input: BaseModel,
    ) -> ToolResult:
        return ToolResult(
            status=ExecutionStatus.FAILED,
            failure_code="permanent_fixture_failure",
            failure_message="Local deterministic failure.",
            transient=False,
        )

    def sensitive_output(_context: ToolContext, _input: BaseModel) -> ToolResult:
        return ToolResult(
            status=ExecutionStatus.COMPLETED,
            structured_output={
                "api_token": "must-not-persist",
                "reasoning": "must-not-persist",
                "decision": "grounded-summary",
            },
            evidence_references=[
                {
                    "evidence_type": "safe",
                    "evidence_id": "safe-reference",
                    "source": "local_fake",
                }
            ],
        )

    result = DeterministicWorkflowOrchestrator(
        factory,
        tool_manager=_tool_manager(
            {
                "axe_accessibility": accessibility_failure,
                "accessibility_aggregation": accessibility_failure,
                "report_generation": sensitive_output,
            }
        ),
    ).execute(execution.execution_id)
    assert result.status == ExecutionStatus.PARTIAL.value
    with factory() as db:
        persisted = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == execution.execution_id)
        )
        assert persisted is not None
        latest = {
            run.agent_id: run
            for run in db.scalars(select(AgentRun).where(AgentRun.execution_id == persisted.id))
        }
        assert latest["performance_agent"].status == ExecutionStatus.COMPLETED.value
        assert latest["accessibility_agent"].status == ExecutionStatus.FAILED.value
        serialized = str(
            {
                "execution": persisted.structured_output,
                "runs": [run.structured_output for run in latest.values()],
                "events": [
                    event.structured_payload
                    for event in db.scalars(
                        select(AgentEvent).where(AgentEvent.execution_id == persisted.id)
                    )
                ],
            }
        )
        assert "must-not-persist" not in serialized
        assert "reasoning" not in serialized
        assert "[REDACTED]" in serialized


def test_cancel_resume_checkpoint_and_completed_immutability(
    tmp_path: Path,
) -> None:
    factory = _session_factory(tmp_path)
    project_id, website_id = _seed_scope(factory)
    execution = _create(factory, _request(project_id, website_id))
    with factory() as db:
        persisted = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == execution.execution_id)
        )
        assert persisted is not None
        cancelled = cancel_execution(db, persisted)
        assert cancelled.status == ExecutionStatus.CANCELLED.value

    cancelled_result = DeterministicWorkflowOrchestrator(
        factory,
        tool_manager=_tool_manager(),
    ).execute(execution.execution_id)
    assert cancelled_result.status == ExecutionStatus.CANCELLED.value

    with factory() as db:
        persisted = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == execution.execution_id)
        )
        assert persisted is not None
        resumed = prepare_resume(db, persisted)
        assert resumed.attempt == 2
        assert resumed.provider_version_metadata["resume_checkpoint_id"] is None

    completed = DeterministicWorkflowOrchestrator(
        factory,
        tool_manager=_tool_manager(),
    ).execute(execution.execution_id)
    assert completed.status == ExecutionStatus.COMPLETED.value
    with factory() as db:
        persisted = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == execution.execution_id)
        )
        assert persisted is not None
        event_count = db.query(AgentEvent).filter_by(execution_id=persisted.id).count()
        with pytest.raises(WorkflowExecutionError, match="immutable"):
            cancel_execution(db, persisted)
        with pytest.raises(WorkflowExecutionError, match="immutable"):
            prepare_resume(db, persisted)

    rerun = DeterministicWorkflowOrchestrator(
        factory,
        tool_manager=_tool_manager(),
    ).execute(execution.execution_id)
    assert rerun.status == ExecutionStatus.COMPLETED.value
    with factory() as db:
        persisted = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == execution.execution_id)
        )
        assert persisted is not None
        assert db.query(AgentEvent).filter_by(execution_id=persisted.id).count() == event_count


def test_resume_uses_latest_valid_checkpoint_and_retries_only_partial_agent(
    tmp_path: Path,
) -> None:
    factory = _session_factory(tmp_path)
    project_id, website_id = _seed_scope(factory)
    execution = _create(factory, _request(project_id, website_id))
    report_is_partial = True

    def report_behavior(_context: ToolContext, _input: BaseModel) -> ToolResult:
        if report_is_partial:
            return ToolResult(
                status=ExecutionStatus.PARTIAL,
                structured_output={"mode": "partial_fixture"},
                deterministic_fallback=True,
            )
        return _completed_result("report_generation")

    manager = _tool_manager({"report_generation": report_behavior})
    first = DeterministicWorkflowOrchestrator(
        factory,
        tool_manager=manager,
    ).execute(execution.execution_id)
    assert first.status == ExecutionStatus.PARTIAL.value
    with factory() as db:
        persisted = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == execution.execution_id)
        )
        assert persisted is not None
        initial_run_count = db.query(AgentRun).filter_by(execution_id=persisted.id).count()
        resumed = prepare_resume(db, persisted)
        assert resumed.provider_version_metadata["resume_checkpoint_id"] is not None

    report_is_partial = False
    second = DeterministicWorkflowOrchestrator(
        factory,
        tool_manager=manager,
    ).execute(execution.execution_id)
    assert second.status == ExecutionStatus.COMPLETED.value
    with factory() as db:
        persisted = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == execution.execution_id)
        )
        assert persisted is not None
        assert (
            db.query(AgentRun).filter_by(execution_id=persisted.id).count() == initial_run_count + 1
        )
        report_runs = list(
            db.scalars(
                select(AgentRun)
                .where(
                    AgentRun.execution_id == persisted.id,
                    AgentRun.agent_id == "report_agent",
                )
                .order_by(AgentRun.attempt)
            )
        )
        assert [run.attempt for run in report_runs] == [1, 2]


def test_retry_validation_rejects_permanent_and_completed_runs(
    tmp_path: Path,
) -> None:
    factory = _session_factory(tmp_path)
    project_id, website_id = _seed_scope(factory)
    execution = _create(factory, _request(project_id, website_id))
    with factory() as db:
        persisted = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == execution.execution_id)
        )
        assert persisted is not None
        definition = AgentRegistry.get("discovery_agent")
        assert definition is not None
        run = AgentRun(
            execution_id=persisted.id,
            agent_id=definition.agent_id,
            agent_version=definition.version,
            input_fingerprint=persisted.input_fingerprint,
            idempotency_key="retry-validation",
            status=ExecutionStatus.FAILED.value,
            attempt=1,
            structured_input={},
            failure_details={"transient": False},
        )
        db.add(run)
        db.commit()
        with pytest.raises(WorkflowExecutionError, match="transient"):
            validate_agent_retry(db, run)
        run.failure_details = {"transient": True}
        db.commit()
        assert validate_agent_retry(db, run).status == ExecutionStatus.PENDING.value
        run.status = ExecutionStatus.COMPLETED.value
        db.commit()
        with pytest.raises(WorkflowExecutionError, match="immutable"):
            validate_agent_retry(db, run)


def test_sanitizer_removes_chain_of_thought_and_redacts_secrets() -> None:
    sanitized = sanitize_persisted_value(
        {
            "decision": "retain evidence",
            "chain_of_thought": "private",
            "nested": {
                "password": "secret",
                "private_reasoning": "private",
            },
        }
    )
    assert sanitized == {
        "decision": "retain evidence",
        "nested": {"password": "[REDACTED]"},
    }


def test_exact_executable_adapters_and_deterministic_llm_policy(
    tmp_path: Path,
) -> None:
    assert tuple(sorted(AGENT_TOOL_PLAN)) == tuple(
        definition.agent_id for definition in AgentRegistry.get_all()
    )
    assert default_tool_adapters().ids() == tuple(
        definition.tool_id for definition in ToolRegistry.get_all()
    )

    factory = _session_factory(tmp_path)
    project_id, website_id = _seed_scope(factory)
    execution = _create(factory, _request(project_id, website_id))
    with factory() as db:
        persisted = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == execution.execution_id)
        )
        assert persisted is not None
        definition = AgentRegistry.get("remediation_agent")
        assert definition is not None
        run = AgentRun(
            execution_id=persisted.id,
            agent_id=definition.agent_id,
            agent_version=definition.version,
            input_fingerprint=persisted.input_fingerprint,
            idempotency_key="llm-policy",
            structured_input={},
        )
        db.add(run)
        db.flush()
        context = ToolContext(
            db=db,
            execution=persisted,
            agent_run=run,
            agent_definition=definition,
            execution_input=persisted.structured_input,
            dependency_evidence=[],
        )
        fallback = ToolExecutionManager(default_tool_adapters()).execute(
            context=context,
            tool_id="approved_llm_completion",
            payload={
                "execution_id": str(persisted.execution_id),
                "grounded_evidence_references": [],
                "structured_prompt": {"purpose": "local deterministic test"},
            },
        )
        assert fallback.result.status == ExecutionStatus.UNAVAILABLE
        assert fallback.result.deterministic_fallback
        assert fallback.result.provider_version_metadata["provider"] == "disabled"

        def local_llm(_context: ToolContext, _input: BaseModel) -> ToolResult:
            return ToolResult(
                status=ExecutionStatus.COMPLETED,
                structured_output={
                    "report_narrative": "Grounded local narrative.",
                    "factual_metric_score": 99,
                    "workflow_structure": ["untrusted"],
                },
                token_total=10,
                cost_total_usd=0.01,
            )

        manager = _tool_manager({"approved_llm_completion": local_llm})
        filtered = manager.execute(
            context=context,
            tool_id="approved_llm_completion",
            payload={
                "execution_id": str(persisted.execution_id),
                "grounded_evidence_references": [],
                "structured_prompt": {"purpose": "local deterministic test"},
            },
        )
        assert filtered.result.structured_output == {
            "report_narrative": "Grounded local narrative."
        }


def test_tool_timeout_is_transient_and_bounded(tmp_path: Path) -> None:
    factory = _session_factory(tmp_path)
    project_id, website_id = _seed_scope(factory)
    execution = _create(factory, _request(project_id, website_id))

    class SlowAdapter:
        tool_id = "website_discovery"

        def is_available(self, _context: ToolContext) -> bool:
            return True

        def execute(
            self,
            _context: ToolContext,
            _typed_input: BaseModel,
        ) -> ToolResult:
            time.sleep(0.2)
            return _completed_result(self.tool_id)

    class EmptyInput(BaseModel):
        pass

    with factory() as db:
        persisted = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == execution.execution_id)
        )
        assert persisted is not None
        definition = AgentRegistry.get("discovery_agent")
        assert definition is not None
        run = AgentRun(
            execution_id=persisted.id,
            agent_id=definition.agent_id,
            agent_version=definition.version,
            input_fingerprint=persisted.input_fingerprint,
            idempotency_key="timeout-test",
            structured_input={},
        )
        db.add(run)
        db.flush()
        context = ToolContext(
            db=db,
            execution=persisted,
            agent_run=run,
            agent_definition=definition,
            execution_input=persisted.structured_input,
            dependency_evidence=[],
        )
        with pytest.raises(ToolExecutionError) as timeout:
            ToolExecutionManager._execute_with_timeout(
                SlowAdapter(),
                context,
                EmptyInput(),
                0.01,
            )
        assert timeout.value.code == "timeout"
        assert timeout.value.transient


def test_unexpected_tool_error_marks_agent_run_as_failed(tmp_path: Path) -> None:
    factory = _session_factory(tmp_path)
    project_id, website_id = _seed_scope(factory)

    def exploding_tool(context: ToolContext, _typed: BaseModel) -> ToolResult:
        raise RuntimeError("unexpected internal error")

    manager = _tool_manager({"website_discovery": exploding_tool})
    with factory() as db:
        execution, _ = create_workflow_execution(
            db,
            _request(project_id, website_id, key="unexpected-error"),
        )
    orchestrator = DeterministicWorkflowOrchestrator(factory, tool_manager=manager)
    result = orchestrator.execute(execution.execution_id)
    assert result.status in {
        ExecutionStatus.PARTIAL.value,
        ExecutionStatus.FAILED.value,
    }
    with factory() as db:
        runs = list(
            db.scalars(
                select(AgentRun).where(
                    AgentRun.execution_id == result.id,
                    AgentRun.agent_id == "discovery_agent",
                )
            )
        )
        assert len(runs) >= 1
        discovery_run = runs[0]
        assert discovery_run.status == ExecutionStatus.FAILED.value
        assert discovery_run.completed_at is not None


def test_unexpected_future_exception_marks_agent_as_failed(
    tmp_path: Path,
) -> None:
    factory = _session_factory(tmp_path)
    project_id, website_id = _seed_scope(factory)

    call_count = 0

    def sometimes_explode(context: ToolContext, _typed: BaseModel) -> ToolResult:
        nonlocal call_count
        call_count += 1
        if context.agent_run.agent_id == "discovery_agent":
            raise RuntimeError("thread crash")
        return _completed_result(context.agent_run.agent_id)

    manager = _tool_manager({"website_discovery": sometimes_explode})
    with factory() as db:
        execution, _ = create_workflow_execution(
            db,
            _request(project_id, website_id, key="future-error"),
        )
    orchestrator = DeterministicWorkflowOrchestrator(factory, tool_manager=manager)
    result = orchestrator.execute(execution.execution_id)
    assert result.status in TERMINAL_STATUSES
    assert result.completed_at is not None


TERMINAL_STATUSES = {
    ExecutionStatus.COMPLETED.value,
    ExecutionStatus.PARTIAL.value,
    ExecutionStatus.FAILED.value,
    ExecutionStatus.CANCELLED.value,
    ExecutionStatus.UNAVAILABLE.value,
}


def test_stale_detection_and_retry_resume_lifecycle(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    from app.services.workflow_execution import (
        REAL_EXECUTION_STALE_AFTER_SECONDS,
        real_execution_is_stale,
    )

    assert REAL_EXECUTION_STALE_AFTER_SECONDS == 900

    factory = _session_factory(tmp_path)
    project_id, website_id = _seed_scope(factory)

    fail_count = 0

    def fail_first_discovery(context: ToolContext, _typed: BaseModel) -> ToolResult:
        nonlocal fail_count
        if context.agent_run.agent_id == "discovery_agent" and fail_count == 0:
            fail_count += 1
            raise RuntimeError("simulated worker crash")
        return _completed_result(context.agent_run.agent_id)

    manager = _tool_manager({"website_discovery": fail_first_discovery})
    with factory() as db:
        execution, _ = create_workflow_execution(
            db,
            _request(project_id, website_id, key="stale-lifecycle"),
        )
    orchestrator = DeterministicWorkflowOrchestrator(factory, tool_manager=manager)
    result = orchestrator.execute(execution.execution_id)
    assert result.status in TERMINAL_STATUSES

    with factory() as db:
        persisted = db.scalar(
            select(AgentExecution).where(AgentExecution.execution_id == execution.execution_id)
        )
        assert persisted is not None
        assert persisted.status in TERMINAL_STATUSES

        now = datetime.now(UTC)
        stale_exec = type(persisted)()
        stale_exec.structured_input = {"discovery_run_id": "test-id"}
        stale_exec.status = ExecutionStatus.RUNNING.value
        stale_exec.started_at = now - timedelta(seconds=1200)
        stale_exec.structured_output = {
            "journey_updated_at": (
                now - timedelta(seconds=REAL_EXECUTION_STALE_AFTER_SECONDS + 60)
            ).isoformat(),
        }
        assert real_execution_is_stale(stale_exec) is True

        fresh_exec = type(persisted)()
        fresh_exec.structured_input = {"discovery_run_id": "test-id"}
        fresh_exec.status = ExecutionStatus.RUNNING.value
        fresh_exec.started_at = now - timedelta(seconds=120)
        fresh_exec.structured_output = {
            "journey_updated_at": (now - timedelta(seconds=30)).isoformat(),
        }
        assert real_execution_is_stale(fresh_exec) is False

        completed_exec = type(persisted)()
        completed_exec.structured_input = {"discovery_run_id": "test-id"}
        completed_exec.status = ExecutionStatus.COMPLETED.value
        completed_exec.started_at = now - timedelta(hours=2)
        completed_exec.structured_output = {
            "journey_updated_at": (
                now - timedelta(seconds=REAL_EXECUTION_STALE_AFTER_SECONDS + 600)
            ).isoformat(),
        }
        assert real_execution_is_stale(completed_exec) is False

        no_disc_exec = type(persisted)()
        no_disc_exec.structured_input = {}
        no_disc_exec.status = ExecutionStatus.RUNNING.value
        no_disc_exec.started_at = now - timedelta(hours=2)
        no_disc_exec.structured_output = {
            "journey_updated_at": (
                now - timedelta(seconds=REAL_EXECUTION_STALE_AFTER_SECONDS + 600)
            ).isoformat(),
        }
        assert real_execution_is_stale(no_disc_exec) is False

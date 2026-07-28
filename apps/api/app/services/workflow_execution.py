import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AgentArtifact,
    AgentCheckpoint,
    AgentEvent,
    AgentExecution,
    AgentRun,
    AgentStep,
    AnalysisRun,
    Project,
    RepositoryConnection,
    Website,
)
from app.schemas.agent_platform import (
    AgentDefinition,
    ExecutionStatus,
    LLMPolicy,
    PartialFailureBehavior,
    WorkflowCondition,
    WorkflowDefinition,
    WorkflowExecutionCreate,
)
from app.services.agent_platform_registry import (
    AgentRegistry,
    SchemaRegistry,
    ToolRegistry,
    WorkflowRegistry,
)
from app.services.tool_execution import (
    ToolContext,
    ToolExecutionError,
    ToolExecutionManager,
    ToolResult,
    canonical_json,
    default_tool_adapters,
    fingerprint,
    sanitize_persisted_value,
)

TERMINAL_EXECUTION_STATUSES = {
    ExecutionStatus.COMPLETED.value,
    ExecutionStatus.PARTIAL.value,
    ExecutionStatus.FAILED.value,
    ExecutionStatus.CANCELLED.value,
    ExecutionStatus.UNAVAILABLE.value,
}
SUCCESSFUL_DEPENDENCY_STATUSES = {
    ExecutionStatus.COMPLETED.value,
    ExecutionStatus.PARTIAL.value,
}
AGENT_TOOL_PLAN: dict[str, tuple[str, ...]] = {
    "discovery_agent": ("website_discovery",),
    "performance_agent": (
        "playwright_analysis",
        "lighthouse_analysis",
        "crux_field_evidence",
        "browser_timing",
    ),
    "accessibility_agent": ("axe_accessibility", "accessibility_aggregation"),
    "site_diagnostics_agent": ("site_diagnostics", "evidence_retrieval"),
    "repository_intelligence_agent": ("repository_scanning", "evidence_retrieval"),
    "evidence_validation_agent": ("evidence_retrieval", "scoring_intelligence"),
    "remediation_agent": (
        "remediation_generation",
        "evidence_retrieval",
        "approved_llm_completion",
    ),
    "report_agent": (
        "report_generation",
        "evidence_retrieval",
        "approved_llm_completion",
    ),
}


class WorkflowExecutionError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class AgentRunOutcome:
    agent_run_id: uuid.UUID
    agent_id: str
    status: ExecutionStatus
    attempt: int
    transient_failure: bool


def utc_now() -> datetime:
    return datetime.now(UTC)


def create_workflow_execution(
    db: Session,
    request: WorkflowExecutionCreate,
) -> tuple[AgentExecution, bool]:
    workflow = WorkflowRegistry.get(request.workflow_id)
    if workflow is None:
        raise WorkflowExecutionError(
            "WORKFLOW_NOT_FOUND",
            "Workflow definition not found.",
            404,
        )
    project = db.get(Project, request.project_id)
    if project is None:
        raise WorkflowExecutionError("PROJECT_NOT_FOUND", "Project not found.", 404)

    website: Website | None = None
    if request.website_id is not None:
        website = db.get(Website, request.website_id)
        if website is None:
            raise WorkflowExecutionError("WEBSITE_NOT_FOUND", "Website not found.", 404)
        if website.project_id != request.project_id:
            raise WorkflowExecutionError(
                "WORKFLOW_SCOPE_MISMATCH",
                "Website does not belong to the requested project.",
                422,
            )

    analysis_run: AnalysisRun | None = None
    if request.analysis_run_id is not None:
        analysis_run = db.get(AnalysisRun, request.analysis_run_id)
        if analysis_run is None:
            raise WorkflowExecutionError(
                "ANALYSIS_RUN_NOT_FOUND",
                "Analysis run not found.",
                404,
            )
        run_website = db.get(Website, analysis_run.website_id)
        if run_website is None or run_website.project_id != request.project_id:
            raise WorkflowExecutionError(
                "WORKFLOW_SCOPE_MISMATCH",
                "Analysis run does not belong to the requested project.",
                422,
            )
        if website is not None and analysis_run.website_id != website.id:
            raise WorkflowExecutionError(
                "WORKFLOW_SCOPE_MISMATCH",
                "Analysis run does not belong to the requested website.",
                422,
            )
        website = website or run_website

    connection: RepositoryConnection | None = None
    if request.repository_connection_id is not None:
        connection = db.get(RepositoryConnection, request.repository_connection_id)
        if connection is None:
            raise WorkflowExecutionError(
                "REPOSITORY_CONNECTION_NOT_FOUND",
                "Repository connection not found.",
                404,
            )
        if connection.project_id != request.project_id:
            raise WorkflowExecutionError(
                "WORKFLOW_SCOPE_MISMATCH",
                "Repository connection does not belong to the requested project.",
                422,
            )

    if request.workflow_id in {"full_website_analysis", "reanalysis"} and website is None:
        raise WorkflowExecutionError(
            "WEBSITE_REQUIRED",
            "This workflow requires a website or analysis-run scope.",
            422,
        )
    if request.workflow_id == "repository_remediation" and connection is None:
        raise WorkflowExecutionError(
            "REPOSITORY_CONNECTION_REQUIRED",
            "Repository remediation requires an approved repository connection.",
            422,
        )

    execution_input = {
        "project_id": str(request.project_id),
        "analysis_run_id": str(analysis_run.id) if analysis_run else None,
        "website_id": str(website.id) if website else None,
        "website_url": website.url if website else None,
        "repository_connection_id": str(connection.id) if connection else None,
        "page_analysis_execution_id": (
            str(request.page_analysis_execution_id) if request.page_analysis_execution_id else None
        ),
        "evidence_references": sorted(set(request.evidence_references)),
        "max_concurrency": request.max_concurrency,
    }
    input_fingerprint = fingerprint(
        {
            "workflow_id": workflow.workflow_id,
            "workflow_version": workflow.version,
            "input": execution_input,
        }
    )
    existing = db.scalar(
        select(AgentExecution).where(
            AgentExecution.project_id == request.project_id,
            AgentExecution.workflow_id == workflow.workflow_id,
            AgentExecution.workflow_version == workflow.version,
            AgentExecution.idempotency_key == request.idempotency_key,
        )
    )
    if existing is not None:
        if existing.input_fingerprint != input_fingerprint:
            raise WorkflowExecutionError(
                "IDEMPOTENCY_CONFLICT",
                "The idempotency key is already associated with different workflow input.",
                409,
            )
        return existing, False

    execution = AgentExecution(
        execution_id=uuid.uuid4(),
        workflow_id=workflow.workflow_id,
        workflow_version=workflow.version,
        project_id=request.project_id,
        analysis_run_id=analysis_run.id if analysis_run else None,
        input_fingerprint=input_fingerprint,
        idempotency_key=request.idempotency_key,
        status=ExecutionStatus.PENDING.value,
        structured_input=execution_input,
        structured_output={},
        evidence_references=[],
        provider_version_metadata={
            "workflow_registry_version": WorkflowRegistry.VERSION,
            "agent_registry_version": AgentRegistry.VERSION,
            "tool_registry_version": ToolRegistry.VERSION,
            "orchestrator_id": workflow.orchestrator_id,
            "orchestrator_version": workflow.orchestrator_version,
        },
        failure_details={},
        partial_completion_details={},
    )
    db.add(execution)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(AgentExecution).where(
                AgentExecution.project_id == request.project_id,
                AgentExecution.workflow_id == workflow.workflow_id,
                AgentExecution.workflow_version == workflow.version,
                AgentExecution.idempotency_key == request.idempotency_key,
            )
        )
        if existing is None or existing.input_fingerprint != input_fingerprint:
            raise
        return existing, False
    db.refresh(execution)
    return execution, True


def record_dispatch(db: Session, execution: AgentExecution, task_id: str) -> None:
    metadata = dict(execution.provider_version_metadata)
    metadata["celery_task_id"] = task_id
    metadata["dispatch_count"] = int(metadata.get("dispatch_count", 0)) + 1
    execution.provider_version_metadata = metadata
    db.commit()


def latest_agent_runs(db: Session, execution: AgentExecution) -> dict[str, AgentRun]:
    runs = list(
        db.scalars(
            select(AgentRun)
            .where(AgentRun.execution_id == execution.id)
            .order_by(AgentRun.agent_id, AgentRun.attempt.desc(), AgentRun.created_at.desc())
        )
    )
    latest: dict[str, AgentRun] = {}
    for run in runs:
        latest.setdefault(run.agent_id, run)
    return latest


class DeterministicWorkflowOrchestrator:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        tool_manager: ToolExecutionManager | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.tool_manager = tool_manager or ToolExecutionManager(default_tool_adapters())

    @staticmethod
    def execution_batches(
        workflow: WorkflowDefinition,
        *,
        repository_configured: bool,
    ) -> tuple[tuple[str, ...], ...]:
        active_nodes = {
            node.agent_id: node
            for node in workflow.nodes
            if not (
                node.condition == WorkflowCondition.REPOSITORY_CONFIGURED
                and not repository_configured
            )
        }
        dependencies = {
            agent_id: {
                dependency
                for dependency in (*node.depends_on, *node.optional_dependencies)
                if dependency in active_nodes
            }
            for agent_id, node in active_nodes.items()
        }
        order_index = {
            agent_id: position for position, agent_id in enumerate(workflow.deterministic_order)
        }
        completed: set[str] = set()
        batches: list[tuple[str, ...]] = []
        while len(completed) < len(active_nodes):
            ready = sorted(
                (
                    agent_id
                    for agent_id, required in dependencies.items()
                    if agent_id not in completed and required <= completed
                ),
                key=order_index.__getitem__,
            )
            if not ready:
                raise WorkflowExecutionError(
                    "WORKFLOW_GRAPH_INVALID",
                    "Workflow graph cannot be executed deterministically.",
                    422,
                )
            batches.append(tuple(ready))
            completed.update(ready)
        return tuple(batches)

    def execute(self, execution_id: uuid.UUID) -> AgentExecution:
        with self.session_factory() as db:
            execution = db.scalar(
                select(AgentExecution)
                .where(AgentExecution.execution_id == execution_id)
                .with_for_update()
            )
            if execution is None:
                raise WorkflowExecutionError(
                    "WORKFLOW_EXECUTION_NOT_FOUND",
                    "Workflow execution not found.",
                    404,
                )
            if execution.status == ExecutionStatus.COMPLETED.value:
                return execution
            if execution.status == ExecutionStatus.RUNNING.value:
                return execution
            if execution.status in {
                ExecutionStatus.PARTIAL.value,
                ExecutionStatus.FAILED.value,
                ExecutionStatus.CANCELLED.value,
                ExecutionStatus.UNAVAILABLE.value,
            }:
                return execution
            workflow = WorkflowRegistry.get(execution.workflow_id)
            if workflow is None or workflow.version != execution.workflow_version:
                raise WorkflowExecutionError(
                    "WORKFLOW_VERSION_UNAVAILABLE",
                    "Pinned workflow definition is unavailable.",
                    409,
                )
            repository_configured = bool(execution.structured_input.get("repository_connection_id"))
            batches = self.execution_batches(
                workflow,
                repository_configured=repository_configured,
            )
            execution.status = ExecutionStatus.RUNNING.value
            execution.completed_at = None
            execution.failure_details = {}
            self._append_event(
                db,
                execution,
                event_type="execution_started",
                status=ExecutionStatus.RUNNING,
                payload={
                    "attempt": execution.attempt,
                    "workflow_id": execution.workflow_id,
                    "workflow_version": execution.workflow_version,
                },
            )
            db.commit()
            execution_pk = execution.id
            max_concurrency = int(execution.structured_input.get("max_concurrency", 3))

        for batch in batches:
            with self.session_factory() as db:
                execution = db.get(AgentExecution, execution_pk)
                assert execution is not None
                if execution.status == ExecutionStatus.CANCELLED.value:
                    return execution
                runnable, blocked = self._partition_batch(db, execution, workflow, batch)

            outcomes: list[AgentRunOutcome] = []
            for agent_id in blocked:
                outcomes.append(self._record_blocked_agent(execution_pk, agent_id))

            if runnable:
                worker_count = min(max_concurrency, len(runnable))
                executor = ThreadPoolExecutor(max_workers=worker_count)
                futures = {
                    agent_id: executor.submit(
                        self._execute_agent_to_terminal,
                        execution_pk,
                        agent_id,
                    )
                    for agent_id in runnable
                }
                for agent_id in runnable:
                    definition = AgentRegistry.get(agent_id)
                    assert definition is not None
                    future = futures[agent_id]
                    try:
                        outcomes.append(future.result(timeout=definition.timeout_seconds))
                    except FutureTimeoutError:
                        future.cancel()
                        outcomes.append(self._mark_agent_timeout(execution_pk, agent_id))
                executor.shutdown(wait=False, cancel_futures=True)

            with self.session_factory() as db:
                execution = db.get(AgentExecution, execution_pk)
                assert execution is not None
                for outcome in sorted(
                    outcomes,
                    key=lambda item: workflow.deterministic_order.index(item.agent_id),
                ):
                    run = db.scalar(
                        select(AgentRun).where(AgentRun.agent_run_id == outcome.agent_run_id)
                    )
                    assert run is not None
                    self._record_agent_terminal_state(db, execution, run)
                db.commit()

        with self.session_factory() as db:
            execution = db.get(AgentExecution, execution_pk)
            assert execution is not None
            if execution.status == ExecutionStatus.CANCELLED.value:
                return execution
            self._finalize_execution(db, execution, workflow)
            db.commit()
            db.refresh(execution)
            return execution

    def _partition_batch(
        self,
        db: Session,
        execution: AgentExecution,
        workflow: WorkflowDefinition,
        batch: tuple[str, ...],
    ) -> tuple[list[str], list[str]]:
        latest = latest_agent_runs(db, execution)
        node_by_id = {node.agent_id: node for node in workflow.nodes}
        runnable: list[str] = []
        blocked: list[str] = []
        for agent_id in batch:
            previous = latest.get(agent_id)
            if previous is not None and previous.status == ExecutionStatus.COMPLETED.value:
                continue
            node = node_by_id[agent_id]
            dependency_statuses = [
                latest[dependency].status for dependency in node.depends_on if dependency in latest
            ]
            if node.depends_on and not any(
                status in SUCCESSFUL_DEPENDENCY_STATUSES for status in dependency_statuses
            ):
                blocked.append(agent_id)
            else:
                runnable.append(agent_id)
        return runnable, blocked

    def _execute_agent_to_terminal(
        self,
        execution_pk: uuid.UUID,
        agent_id: str,
    ) -> AgentRunOutcome:
        definition = AgentRegistry.get(agent_id)
        assert definition is not None
        outcome = self._execute_agent_once(execution_pk, agent_id)
        while (
            outcome.status == ExecutionStatus.FAILED
            and outcome.transient_failure
            and outcome.attempt < definition.retry_policy.max_attempts
        ):
            outcome = self._execute_agent_once(execution_pk, agent_id)
        return outcome

    def _execute_agent_once(
        self,
        execution_pk: uuid.UUID,
        agent_id: str,
    ) -> AgentRunOutcome:
        with self.session_factory() as db:
            execution = db.get(AgentExecution, execution_pk)
            if execution is None:
                raise WorkflowExecutionError(
                    "WORKFLOW_EXECUTION_NOT_FOUND",
                    "Workflow execution not found.",
                    404,
                )
            if execution.status == ExecutionStatus.CANCELLED.value:
                return self._cancelled_agent_outcome(db, execution, agent_id)
            definition = AgentRegistry.get(agent_id)
            if definition is None:
                raise WorkflowExecutionError(
                    "AGENT_VERSION_UNAVAILABLE",
                    "Pinned agent definition is unavailable.",
                    409,
                )
            existing_runs = list(
                db.scalars(
                    select(AgentRun)
                    .where(
                        AgentRun.execution_id == execution.id,
                        AgentRun.agent_id == agent_id,
                    )
                    .order_by(AgentRun.attempt.desc())
                )
            )
            if existing_runs and existing_runs[0].status == ExecutionStatus.COMPLETED.value:
                current = existing_runs[0]
                return AgentRunOutcome(
                    current.agent_run_id,
                    agent_id,
                    ExecutionStatus.COMPLETED,
                    current.attempt,
                    False,
                )
            attempt = (existing_runs[0].attempt if existing_runs else 0) + 1
            if attempt > definition.retry_policy.max_attempts:
                current = existing_runs[0]
                return AgentRunOutcome(
                    current.agent_run_id,
                    agent_id,
                    ExecutionStatus(current.status),
                    current.attempt,
                    bool(current.failure_details.get("transient")),
                )

            latest = latest_agent_runs(db, execution)
            dependency_runs = self._dependency_runs(execution.workflow_id, agent_id, latest)
            dependency_evidence = self._deduplicate_evidence(
                [
                    evidence
                    for dependency_run in dependency_runs
                    for evidence in dependency_run.evidence_references
                ]
                + [
                    {
                        "evidence_type": "input_reference",
                        "evidence_id": reference,
                        "source": "execution_input",
                    }
                    for reference in execution.structured_input.get("evidence_references", [])
                ]
            )
            agent_input = self._agent_input(
                definition,
                execution,
                dependency_evidence,
            )
            run = AgentRun(
                agent_run_id=uuid.uuid5(
                    execution.execution_id,
                    f"agent-run:{agent_id}:attempt:{attempt}",
                ),
                execution_id=execution.id,
                agent_id=agent_id,
                agent_version=definition.version,
                dependency_agent_run_id=dependency_runs[0].id if dependency_runs else None,
                dependency_agent_run_ids=[
                    str(dependency.agent_run_id) for dependency in dependency_runs
                ],
                input_fingerprint=fingerprint(agent_input),
                idempotency_key=f"{execution.idempotency_key}:{agent_id}",
                status=ExecutionStatus.RUNNING.value,
                attempt=attempt,
                structured_input=agent_input,
                structured_output={},
                tool_activity_summary=[],
                evidence_references=[],
                provider_version_metadata={},
                failure_details={},
                partial_completion_details={},
            )
            db.add(run)
            db.flush()
            db.commit()
            db.refresh(run)
            db.refresh(execution)

            activities: list[dict[str, Any]] = []
            results: list[ToolResult] = []
            for sequence, tool_id in enumerate(AGENT_TOOL_PLAN[agent_id]):
                db.refresh(execution)
                if execution.status == ExecutionStatus.CANCELLED.value:
                    run.status = ExecutionStatus.CANCELLED.value
                    run.completed_at = utc_now()
                    run.partial_completion_details = {"reason": "execution_cancelled"}
                    db.commit()
                    return AgentRunOutcome(
                        run.agent_run_id,
                        agent_id,
                        ExecutionStatus.CANCELLED,
                        attempt,
                        False,
                    )
                payload = self._tool_input(
                    tool_id,
                    execution,
                    dependency_evidence,
                    agent_id,
                )
                try:
                    record = self.tool_manager.execute(
                        context=ToolContext(
                            db=db,
                            execution=execution,
                            agent_run=run,
                            agent_definition=definition,
                            execution_input=execution.structured_input,
                            dependency_evidence=dependency_evidence,
                        ),
                        tool_id=tool_id,
                        payload=payload,
                    )
                except ToolExecutionError as exception:
                    result = ToolResult(
                        status=ExecutionStatus.FAILED,
                        failure_code=exception.code,
                        failure_message=exception.safe_message,
                        transient=exception.transient,
                    )
                    activity = {
                        "tool_id": tool_id,
                        "tool_version": ToolRegistry.get(tool_id).version
                        if ToolRegistry.get(tool_id)
                        else "unregistered",
                        "status": ExecutionStatus.FAILED.value,
                        "attempts": 0,
                        "failure_code": exception.code,
                    }
                else:
                    result = record.result
                    activity = record.activity
                results.append(result)
                activities.append(activity)
                step = AgentStep(
                    step_id=uuid.uuid5(
                        run.agent_run_id,
                        f"tool-step:{sequence}:{tool_id}:attempt:{attempt}",
                    ),
                    agent_run_id=run.id,
                    step_name=f"Execute {tool_id}",
                    sequence_number=sequence,
                    tool_id=tool_id,
                    tool_version=activity["tool_version"],
                    status=result.status.value,
                    attempt=attempt,
                    structured_input=sanitize_persisted_value(payload),
                    structured_output=result.structured_output,
                    tool_activity_summary=activity,
                    evidence_references=result.evidence_references,
                    failure_details=(
                        {
                            "code": result.failure_code,
                            "message": result.failure_message,
                            "transient": result.transient,
                        }
                        if result.failure_code
                        else {}
                    ),
                    partial_completion_details={},
                    completed_at=utc_now(),
                )
                db.add(step)

            status = self._aggregate_agent_status(definition, results)
            evidence = self._deduplicate_evidence(
                [item for result in results for item in result.evidence_references]
            )
            provider_metadata = {
                key: value
                for result in results
                for key, value in result.provider_version_metadata.items()
            }
            failures = [
                {
                    "code": result.failure_code,
                    "message": result.failure_message,
                    "transient": result.transient,
                }
                for result in results
                if result.failure_code and result.status == ExecutionStatus.FAILED
            ]
            run.status = status.value
            run.structured_output = sanitize_persisted_value(
                {
                    "status": status.value,
                    "agent_id": agent_id,
                    "tool_results": [
                        {
                            "tool_id": activity["tool_id"],
                            "status": result.status.value,
                            "output": result.structured_output,
                            "deterministic_fallback": result.deterministic_fallback,
                        }
                        for activity, result in zip(activities, results, strict=True)
                    ],
                    "decisions": self._structured_decisions(definition, results),
                }
            )
            run.tool_activity_summary = sanitize_persisted_value(activities)
            run.evidence_references = evidence
            run.provider_version_metadata = sanitize_persisted_value(provider_metadata)
            run.token_total = sum(result.token_total for result in results)
            run.cost_total_usd = sum(result.cost_total_usd for result in results)
            run.failure_details = (
                {
                    "failures": failures,
                    "transient": bool(failures) and all(item["transient"] for item in failures),
                }
                if failures
                else {}
            )
            unavailable_tools = [
                activity["tool_id"]
                for activity, result in zip(activities, results, strict=True)
                if result.status == ExecutionStatus.UNAVAILABLE
            ]
            run.partial_completion_details = (
                {
                    "unavailable_tool_ids": unavailable_tools,
                    "retained_evidence_count": len(evidence),
                }
                if status in {ExecutionStatus.PARTIAL, ExecutionStatus.UNAVAILABLE}
                else {}
            )
            run.completed_at = utc_now()
            db.commit()
            return AgentRunOutcome(
                run.agent_run_id,
                agent_id,
                status,
                attempt,
                bool(run.failure_details.get("transient")),
            )

    def _record_blocked_agent(
        self,
        execution_pk: uuid.UUID,
        agent_id: str,
    ) -> AgentRunOutcome:
        with self.session_factory() as db:
            execution = db.get(AgentExecution, execution_pk)
            assert execution is not None
            definition = AgentRegistry.get(agent_id)
            assert definition is not None
            latest = latest_agent_runs(db, execution)
            existing = latest.get(agent_id)
            if existing is not None:
                return AgentRunOutcome(
                    existing.agent_run_id,
                    agent_id,
                    ExecutionStatus(existing.status),
                    existing.attempt,
                    False,
                )
            dependency_runs = self._dependency_runs(execution.workflow_id, agent_id, latest)
            run = AgentRun(
                agent_run_id=uuid.uuid5(
                    execution.execution_id,
                    f"agent-run:{agent_id}:attempt:1",
                ),
                execution_id=execution.id,
                agent_id=agent_id,
                agent_version=definition.version,
                dependency_agent_run_id=dependency_runs[0].id if dependency_runs else None,
                dependency_agent_run_ids=[
                    str(dependency.agent_run_id) for dependency in dependency_runs
                ],
                input_fingerprint=execution.input_fingerprint,
                idempotency_key=f"{execution.idempotency_key}:{agent_id}",
                status=ExecutionStatus.UNAVAILABLE.value,
                attempt=1,
                structured_input={},
                structured_output={
                    "status": ExecutionStatus.UNAVAILABLE.value,
                    "agent_id": agent_id,
                    "decisions": [
                        {
                            "decision": "skip",
                            "reason": "required_prerequisite_unavailable",
                        }
                    ],
                },
                tool_activity_summary=[],
                evidence_references=[],
                provider_version_metadata={},
                failure_details={},
                partial_completion_details={"reason": "required_prerequisite_unavailable"},
                completed_at=utc_now(),
            )
            db.add(run)
            db.commit()
            return AgentRunOutcome(
                run.agent_run_id,
                agent_id,
                ExecutionStatus.UNAVAILABLE,
                1,
                False,
            )

    def _mark_agent_timeout(
        self,
        execution_pk: uuid.UUID,
        agent_id: str,
    ) -> AgentRunOutcome:
        with self.session_factory() as db:
            execution = db.get(AgentExecution, execution_pk)
            assert execution is not None
            latest = latest_agent_runs(db, execution).get(agent_id)
            if latest is None:
                return self._record_blocked_agent(execution_pk, agent_id)
            if latest.status == ExecutionStatus.RUNNING.value:
                latest.status = ExecutionStatus.FAILED.value
                latest.failure_details = {
                    "failures": [
                        {
                            "code": "timeout",
                            "message": "Agent execution exceeded its timeout.",
                            "transient": True,
                        }
                    ],
                    "transient": True,
                }
                latest.completed_at = utc_now()
                db.commit()
            return AgentRunOutcome(
                latest.agent_run_id,
                agent_id,
                ExecutionStatus(latest.status),
                latest.attempt,
                bool(latest.failure_details.get("transient")),
            )

    def _cancelled_agent_outcome(
        self,
        db: Session,
        execution: AgentExecution,
        agent_id: str,
    ) -> AgentRunOutcome:
        definition = AgentRegistry.get(agent_id)
        assert definition is not None
        latest = latest_agent_runs(db, execution).get(agent_id)
        if latest is None:
            latest = AgentRun(
                agent_run_id=uuid.uuid5(
                    execution.execution_id,
                    f"agent-run:{agent_id}:cancelled",
                ),
                execution_id=execution.id,
                agent_id=agent_id,
                agent_version=definition.version,
                dependency_agent_run_ids=[],
                input_fingerprint=execution.input_fingerprint,
                idempotency_key=f"{execution.idempotency_key}:{agent_id}",
                status=ExecutionStatus.CANCELLED.value,
                structured_input={},
                structured_output={},
                tool_activity_summary=[],
                evidence_references=[],
                provider_version_metadata={},
                failure_details={},
                partial_completion_details={"reason": "execution_cancelled"},
                completed_at=utc_now(),
            )
            db.add(latest)
            db.commit()
        return AgentRunOutcome(
            latest.agent_run_id,
            agent_id,
            ExecutionStatus(latest.status),
            latest.attempt,
            False,
        )

    @staticmethod
    def _dependency_runs(
        workflow_id: str,
        agent_id: str,
        latest: dict[str, AgentRun],
    ) -> list[AgentRun]:
        workflow = WorkflowRegistry.get(workflow_id)
        assert workflow is not None
        node = next(node for node in workflow.nodes if node.agent_id == agent_id)
        dependency_ids = (*node.depends_on, *node.optional_dependencies)
        return [latest[item] for item in dependency_ids if item in latest]

    @staticmethod
    def _agent_input(
        definition: AgentDefinition,
        execution: AgentExecution,
        dependency_evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        base = execution.structured_input
        evidence_keys = [
            f"{item.get('evidence_type')}:{item.get('evidence_id')}" for item in dependency_evidence
        ]
        if definition.input_schema_ref == "website_analysis_input":
            payload = {
                "project_id": base["project_id"],
                "analysis_run_id": base.get("analysis_run_id"),
                "website_id": base["website_id"],
                "repository_connection_id": base.get("repository_connection_id"),
                "page_analysis_execution_id": base.get("page_analysis_execution_id"),
            }
        elif definition.input_schema_ref == "repository_analysis_input":
            payload = {
                "project_id": base["project_id"],
                "repository_connection_id": base.get("repository_connection_id"),
                "evidence_references": evidence_keys,
            }
        elif definition.input_schema_ref == "evidence_validation_input":
            payload = {
                "execution_id": str(execution.execution_id),
                "evidence_references": evidence_keys,
            }
        elif definition.input_schema_ref == "remediation_input":
            payload = {
                "execution_id": str(execution.execution_id),
                "validated_evidence_references": evidence_keys,
                "repository_artifact_references": [
                    item for item in evidence_keys if item.startswith("repository_")
                ],
            }
        elif definition.input_schema_ref == "report_input":
            payload = {
                "execution_id": str(execution.execution_id),
                "evidence_references": evidence_keys,
                "remediation_references": [
                    item for item in evidence_keys if item.startswith("action_")
                ],
            }
        else:
            raise WorkflowExecutionError(
                "AGENT_INPUT_SCHEMA_UNSUPPORTED",
                f"Unsupported agent input schema: {definition.input_schema_ref}",
                422,
            )
        schema = SchemaRegistry.get(definition.input_schema_ref)
        assert schema is not None
        try:
            typed = schema.model_validate(payload)
        except ValidationError as exception:
            raise WorkflowExecutionError(
                "AGENT_INPUT_INVALID",
                f"Input validation failed for {definition.agent_id}.",
                422,
            ) from exception
        return sanitize_persisted_value(typed.model_dump(mode="json"))

    @staticmethod
    def _tool_input(
        tool_id: str,
        execution: AgentExecution,
        dependency_evidence: list[dict[str, Any]],
        agent_id: str,
    ) -> dict[str, Any]:
        definition = ToolRegistry.get(tool_id)
        assert definition is not None
        base = execution.structured_input
        evidence_keys = [
            f"{item.get('evidence_type')}:{item.get('evidence_id')}" for item in dependency_evidence
        ]
        payload_by_schema: dict[str, dict[str, Any]] = {
            "website_analysis_input": {
                "project_id": base["project_id"],
                "analysis_run_id": base.get("analysis_run_id"),
                "website_id": base.get("website_id"),
                "repository_connection_id": base.get("repository_connection_id"),
                "page_analysis_execution_id": base.get("page_analysis_execution_id"),
            },
            "page_tool_input": {
                "execution_id": str(execution.execution_id),
                "page_url": base.get("website_url") or "https://unavailable.invalid/",
                "evidence_reference": (evidence_keys[0] if evidence_keys else None),
            },
            "repository_analysis_input": {
                "project_id": base["project_id"],
                "repository_connection_id": base.get("repository_connection_id"),
                "evidence_references": evidence_keys,
            },
            "remediation_input": {
                "execution_id": str(execution.execution_id),
                "validated_evidence_references": evidence_keys,
                "repository_artifact_references": [
                    key for key in evidence_keys if key.startswith("repository_")
                ],
            },
            "report_input": {
                "execution_id": str(execution.execution_id),
                "evidence_references": evidence_keys,
                "remediation_references": [
                    key for key in evidence_keys if key.startswith("action_")
                ],
            },
            "evidence_retrieval_input": {
                "execution_id": str(execution.execution_id),
                "evidence_references": evidence_keys,
            },
            "approved_llm_input": {
                "execution_id": str(execution.execution_id),
                "grounded_evidence_references": evidence_keys,
                "structured_prompt": {
                    "agent_id": agent_id,
                    "purpose": "Evidence-grounded narrative only.",
                },
            },
        }
        payload = payload_by_schema.get(definition.input_schema_ref)
        if payload is None:
            raise ToolExecutionError(
                "unsupported_tool_input",
                f"Unsupported tool input schema: {definition.input_schema_ref}.",
                transient=False,
            )
        return payload

    @staticmethod
    def _aggregate_agent_status(
        definition: AgentDefinition,
        results: list[ToolResult],
    ) -> ExecutionStatus:
        material_results = [
            result
            for tool_id, result in zip(
                AGENT_TOOL_PLAN[definition.agent_id],
                results,
                strict=True,
            )
            if not (
                tool_id == "approved_llm_completion"
                and definition.llm_policy == LLMPolicy.OPTIONAL_APPROVED_PROVIDER
                and result.status == ExecutionStatus.UNAVAILABLE
            )
        ]
        statuses = {result.status for result in material_results}
        if not statuses:
            return ExecutionStatus.UNAVAILABLE
        if statuses == {ExecutionStatus.COMPLETED}:
            return ExecutionStatus.COMPLETED
        if statuses <= {ExecutionStatus.UNAVAILABLE}:
            return (
                ExecutionStatus.UNAVAILABLE
                if definition.partial_failure_behavior != PartialFailureBehavior.PRESERVE_PARTIAL
                else ExecutionStatus.PARTIAL
            )
        if statuses <= {ExecutionStatus.FAILED}:
            return ExecutionStatus.FAILED
        if ExecutionStatus.COMPLETED in statuses or ExecutionStatus.PARTIAL in statuses:
            return ExecutionStatus.PARTIAL
        if ExecutionStatus.FAILED in statuses:
            return ExecutionStatus.FAILED
        return ExecutionStatus.UNAVAILABLE

    @staticmethod
    def _structured_decisions(
        definition: AgentDefinition,
        results: list[ToolResult],
    ) -> list[dict[str, Any]]:
        unavailable = sum(result.status == ExecutionStatus.UNAVAILABLE for result in results)
        failed = sum(result.status == ExecutionStatus.FAILED for result in results)
        return [
            {
                "decision": "retain_available_evidence",
                "agent_policy": definition.partial_failure_behavior.value,
                "unavailable_tool_count": unavailable,
                "failed_tool_count": failed,
            }
        ]

    @staticmethod
    def _deduplicate_evidence(
        evidence: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        by_key = {canonical_json(item): sanitize_persisted_value(item) for item in evidence}
        return [by_key[key] for key in sorted(by_key)]

    def _record_agent_terminal_state(
        self,
        db: Session,
        execution: AgentExecution,
        run: AgentRun,
    ) -> None:
        status = ExecutionStatus(run.status)
        self._append_event(
            db,
            execution,
            event_type=f"agent_{status.value}",
            status=status,
            payload={
                "agent_id": run.agent_id,
                "agent_version": run.agent_version,
                "agent_run_id": str(run.agent_run_id),
                "attempt": run.attempt,
            },
            run=run,
            evidence=run.evidence_references,
        )
        self._persist_artifact(db, execution, run)
        if status == ExecutionStatus.COMPLETED:
            self._persist_checkpoint(db, execution, run)

    @staticmethod
    def _persist_artifact(
        db: Session,
        execution: AgentExecution,
        run: AgentRun,
    ) -> None:
        content_hash = fingerprint(run.structured_output)
        existing = db.scalar(
            select(AgentArtifact).where(
                AgentArtifact.execution_id == execution.id,
                AgentArtifact.artifact_type == "agent_structured_output",
                AgentArtifact.content_hash == content_hash,
            )
        )
        if existing is not None:
            return
        db.add(
            AgentArtifact(
                artifact_id=uuid.uuid5(
                    execution.execution_id,
                    f"artifact:{run.agent_run_id}:{content_hash}",
                ),
                execution_id=execution.id,
                agent_run_id=run.id,
                artifact_type="agent_structured_output",
                name=f"{run.agent_id} structured output",
                storage_reference=f"database://agent-runs/{run.agent_run_id}/structured-output",
                content_hash=content_hash,
                media_type="application/json",
                artifact_metadata={
                    "agent_id": run.agent_id,
                    "agent_version": run.agent_version,
                    "status": run.status,
                },
                evidence_references=run.evidence_references,
            )
        )

    @staticmethod
    def _persist_checkpoint(
        db: Session,
        execution: AgentExecution,
        run: AgentRun,
    ) -> None:
        existing = db.scalar(
            select(AgentCheckpoint).where(
                AgentCheckpoint.agent_run_id == run.id,
                AgentCheckpoint.checkpoint_version == 1,
            )
        )
        if existing is not None:
            return
        completed_agents = sorted(
            db.scalars(
                select(AgentRun.agent_id).where(
                    AgentRun.execution_id == execution.id,
                    AgentRun.status == ExecutionStatus.COMPLETED.value,
                )
            )
        )
        db.add(
            AgentCheckpoint(
                checkpoint_id=uuid.uuid5(
                    execution.execution_id,
                    f"checkpoint:{run.agent_run_id}:1",
                ),
                execution_id=execution.id,
                agent_run_id=run.id,
                checkpoint_version=1,
                status=ExecutionStatus.COMPLETED.value,
                resumable=True,
                input_fingerprint=execution.input_fingerprint,
                state_summary={
                    "completed_agent_ids": completed_agents,
                    "latest_completed_agent_id": run.agent_id,
                },
                evidence_references=run.evidence_references,
            )
        )

    @staticmethod
    def _append_event(
        db: Session,
        execution: AgentExecution,
        *,
        event_type: str,
        status: ExecutionStatus,
        payload: dict[str, Any],
        run: AgentRun | None = None,
        evidence: list[dict[str, Any]] | None = None,
    ) -> AgentEvent:
        last_sequence = db.scalar(
            select(func.max(AgentEvent.sequence_number)).where(
                AgentEvent.execution_id == execution.id
            )
        )
        sequence = 0 if last_sequence is None else last_sequence + 1
        event = AgentEvent(
            event_id=uuid.uuid5(
                execution.execution_id,
                f"event:{sequence}:{event_type}:{run.agent_run_id if run else 'workflow'}",
            ),
            execution_id=execution.id,
            agent_run_id=run.id if run else None,
            event_type=event_type,
            sequence_number=sequence,
            status=status.value,
            structured_payload=sanitize_persisted_value(payload),
            evidence_references=sanitize_persisted_value(evidence or []),
        )
        db.add(event)
        db.flush()
        return event

    def _finalize_execution(
        self,
        db: Session,
        execution: AgentExecution,
        workflow: WorkflowDefinition,
    ) -> None:
        latest = latest_agent_runs(db, execution)
        active_agent_ids = [
            agent_id for agent_id in workflow.deterministic_order if agent_id in latest
        ]
        grouped: dict[str, list[str]] = {status.value: [] for status in ExecutionStatus}
        for agent_id in active_agent_ids:
            grouped[latest[agent_id].status].append(agent_id)
        completed = grouped[ExecutionStatus.COMPLETED.value]
        partial = grouped[ExecutionStatus.PARTIAL.value]
        failed = grouped[ExecutionStatus.FAILED.value]
        unavailable = grouped[ExecutionStatus.UNAVAILABLE.value]
        if completed and not (partial or failed or unavailable):
            status = ExecutionStatus.COMPLETED
        elif completed or partial:
            status = ExecutionStatus.PARTIAL
        elif failed:
            status = ExecutionStatus.FAILED
        else:
            status = ExecutionStatus.UNAVAILABLE

        evidence = self._deduplicate_evidence(
            [item for agent_id in active_agent_ids for item in latest[agent_id].evidence_references]
        )
        execution.status = status.value
        execution.structured_output = {
            "status": status.value,
            "completed_agent_ids": completed,
            "partial_agent_ids": partial,
            "failed_agent_ids": failed,
            "unavailable_agent_ids": unavailable,
        }
        execution.evidence_references = evidence
        execution.token_total = sum(latest[item].token_total for item in active_agent_ids)
        execution.cost_total_usd = sum(latest[item].cost_total_usd for item in active_agent_ids)
        execution.failure_details = (
            {
                "failed_agent_ids": failed,
                "failures": {item: latest[item].failure_details for item in failed},
            }
            if failed
            else {}
        )
        execution.partial_completion_details = (
            {
                "partial_agent_ids": partial,
                "unavailable_agent_ids": unavailable,
                "successful_agent_ids": completed,
            }
            if status in {ExecutionStatus.PARTIAL, ExecutionStatus.UNAVAILABLE}
            else {}
        )
        execution.completed_at = utc_now()
        self._append_event(
            db,
            execution,
            event_type=f"execution_{status.value}",
            status=status,
            payload=execution.structured_output,
            evidence=evidence,
        )


def cancel_execution(db: Session, execution: AgentExecution) -> AgentExecution:
    if execution.status == ExecutionStatus.COMPLETED.value:
        raise WorkflowExecutionError(
            "COMPLETED_EXECUTION_IMMUTABLE",
            "Completed workflow executions are immutable.",
            409,
        )
    if execution.status == ExecutionStatus.CANCELLED.value:
        return execution
    execution.status = ExecutionStatus.CANCELLED.value
    execution.completed_at = utc_now()
    execution.partial_completion_details = {
        **execution.partial_completion_details,
        "cancellation_requested": True,
    }
    DeterministicWorkflowOrchestrator._append_event(
        db,
        execution,
        event_type="execution_cancelled",
        status=ExecutionStatus.CANCELLED,
        payload={"cancellation_requested": True},
    )
    db.commit()
    db.refresh(execution)
    return execution


def prepare_resume(db: Session, execution: AgentExecution) -> AgentExecution:
    if execution.status == ExecutionStatus.COMPLETED.value:
        raise WorkflowExecutionError(
            "COMPLETED_EXECUTION_IMMUTABLE",
            "Completed workflow executions are immutable.",
            409,
        )
    if execution.status in {
        ExecutionStatus.PENDING.value,
        ExecutionStatus.RUNNING.value,
    }:
        raise WorkflowExecutionError(
            "EXECUTION_ALREADY_ACTIVE",
            "Workflow execution is already pending or running.",
            409,
        )
    checkpoint = db.scalar(
        select(AgentCheckpoint)
        .where(
            AgentCheckpoint.execution_id == execution.id,
            AgentCheckpoint.resumable.is_(True),
            AgentCheckpoint.input_fingerprint == execution.input_fingerprint,
        )
        .order_by(AgentCheckpoint.created_at.desc(), AgentCheckpoint.id.desc())
    )
    execution.attempt += 1
    execution.status = ExecutionStatus.PENDING.value
    execution.completed_at = None
    execution.failure_details = {}
    metadata = dict(execution.provider_version_metadata)
    metadata["resume_checkpoint_id"] = str(checkpoint.checkpoint_id) if checkpoint else None
    metadata["resume_count"] = int(metadata.get("resume_count", 0)) + 1
    execution.provider_version_metadata = metadata
    DeterministicWorkflowOrchestrator._append_event(
        db,
        execution,
        event_type="execution_resumed",
        status=ExecutionStatus.PENDING,
        payload={
            "attempt": execution.attempt,
            "checkpoint_id": str(checkpoint.checkpoint_id) if checkpoint else None,
        },
    )
    db.commit()
    db.refresh(execution)
    return execution


def validate_agent_retry(db: Session, run: AgentRun) -> AgentExecution:
    execution = db.get(AgentExecution, run.execution_id)
    if execution is None:
        raise WorkflowExecutionError(
            "WORKFLOW_EXECUTION_NOT_FOUND",
            "Workflow execution not found.",
            404,
        )
    if execution.status == ExecutionStatus.COMPLETED.value:
        raise WorkflowExecutionError(
            "COMPLETED_EXECUTION_IMMUTABLE",
            "Completed workflow executions are immutable.",
            409,
        )
    if run.status == ExecutionStatus.COMPLETED.value:
        raise WorkflowExecutionError(
            "COMPLETED_AGENT_RUN_IMMUTABLE",
            "Completed agent runs are immutable.",
            409,
        )
    definition = AgentRegistry.get(run.agent_id)
    if definition is None:
        raise WorkflowExecutionError(
            "AGENT_VERSION_UNAVAILABLE",
            "Pinned agent definition is unavailable.",
            409,
        )
    latest_attempt = db.scalar(
        select(func.max(AgentRun.attempt)).where(
            AgentRun.execution_id == execution.id,
            AgentRun.agent_id == run.agent_id,
        )
    )
    if (latest_attempt or 0) >= definition.retry_policy.max_attempts:
        raise WorkflowExecutionError(
            "AGENT_RETRY_LIMIT_REACHED",
            "The registered agent retry limit has been reached.",
            409,
        )
    if not run.failure_details.get("transient"):
        raise WorkflowExecutionError(
            "AGENT_FAILURE_NOT_RETRYABLE",
            "Only transient agent failures may be retried.",
            409,
        )
    execution.status = ExecutionStatus.PENDING.value
    execution.completed_at = None
    db.commit()
    return execution

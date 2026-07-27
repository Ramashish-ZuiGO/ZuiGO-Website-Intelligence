import hashlib
import json
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AccessibilityAudit,
    AgentExecution,
    AgentRun,
    AnalysisResult,
    DiscoveryRun,
    PerformanceSnapshot,
    SiteDiagnosticExecution,
)
from app.schemas.agent_platform import (
    AgentDefinition,
    AvailabilityState,
    ExecutionStatus,
    IdempotencyRequirement,
    LLMPolicy,
    SecretHandlingPolicy,
    ToolDefinition,
    URLNormalizationInput,
)
from app.services.action_generation import generate_actions
from app.services.agent_platform_registry import AgentRegistry, SchemaRegistry, ToolRegistry
from app.services.report_delivery import ReportDeliveryError, generate_report
from app.services.repository.git_scanner import RepositoryScannerService
from app.services.scoring_intelligence import (
    ScoringIntelligenceError,
    calculate_score_execution,
)
from app.services.site_diagnostics_service import SiteDiagnosticsService

SECRET_KEY_MARKERS = (
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
)
PRIVATE_REASONING_KEYS = {
    "chain_of_thought",
    "hidden_reasoning",
    "internal_monologue",
    "private_reasoning",
    "reasoning",
    "scratchpad",
}
LLM_FORBIDDEN_FACTUAL_KEY_MARKERS = (
    "accessibility_classification",
    "crawl_result",
    "database_state",
    "factual_metric",
    "indexability_state",
    "score",
    "workflow_structure",
)
TRANSIENT_FAILURE_CODES = {"temporary_unavailable", "timeout"}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sanitize_persisted_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return sanitize_persisted_value(value.model_dump(mode="json"))
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized_key = key.casefold()
            if normalized_key in PRIVATE_REASONING_KEYS:
                continue
            if any(marker in normalized_key for marker in SECRET_KEY_MARKERS):
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = sanitize_persisted_value(item)
        return sanitized
    if isinstance(value, (list, tuple, set)):
        return [sanitize_persisted_value(item) for item in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def sanitize_llm_narrative(value: Any) -> Any:
    sanitized = sanitize_persisted_value(value)
    if isinstance(sanitized, dict):
        return {
            key: sanitize_llm_narrative(item)
            for key, item in sanitized.items()
            if not any(marker in key.casefold() for marker in LLM_FORBIDDEN_FACTUAL_KEY_MARKERS)
        }
    if isinstance(sanitized, list):
        return [sanitize_llm_narrative(item) for item in sanitized]
    return sanitized


@dataclass(frozen=True)
class ToolResult:
    status: ExecutionStatus
    structured_output: dict[str, Any] = field(default_factory=dict)
    evidence_references: list[dict[str, Any]] = field(default_factory=list)
    provider_version_metadata: dict[str, Any] = field(default_factory=dict)
    token_total: int = 0
    cost_total_usd: float = 0.0
    failure_code: str | None = None
    failure_message: str | None = None
    transient: bool = False
    deterministic_fallback: bool = False


@dataclass
class ToolContext:
    db: Session
    execution: AgentExecution
    agent_run: AgentRun
    agent_definition: AgentDefinition
    execution_input: dict[str, Any]
    dependency_evidence: list[dict[str, Any]]


class ToolExecutionError(Exception):
    def __init__(self, code: str, message: str, *, transient: bool) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.transient = transient


class ToolAdapter(Protocol):
    tool_id: str

    def is_available(self, context: ToolContext) -> bool: ...

    def execute(self, context: ToolContext, typed_input: BaseModel) -> ToolResult: ...


class FunctionalToolAdapter:
    def __init__(
        self,
        tool_id: str,
        handler: Callable[[ToolContext, BaseModel], ToolResult],
        *,
        availability: Callable[[ToolContext], bool] | None = None,
    ) -> None:
        self.tool_id = tool_id
        self._handler = handler
        self._availability = availability or (lambda _context: True)

    def is_available(self, context: ToolContext) -> bool:
        return self._availability(context)

    def execute(self, context: ToolContext, typed_input: BaseModel) -> ToolResult:
        return self._handler(context, typed_input)


class ToolAdapterRegistry:
    def __init__(self, adapters: list[ToolAdapter] | tuple[ToolAdapter, ...]) -> None:
        self._adapters: dict[str, ToolAdapter] = {}
        for adapter in adapters:
            if adapter.tool_id in self._adapters:
                raise ValueError(f"Duplicate executable tool adapter: {adapter.tool_id}")
            if ToolRegistry.get(adapter.tool_id) is None:
                raise ValueError(f"Unknown executable tool adapter: {adapter.tool_id}")
            self._adapters[adapter.tool_id] = adapter

    def get(self, tool_id: str) -> ToolAdapter | None:
        return self._adapters.get(tool_id)

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))


@dataclass(frozen=True)
class ToolExecutionRecord:
    result: ToolResult
    activity: dict[str, Any]


class ToolExecutionManager:
    def __init__(
        self,
        adapters: ToolAdapterRegistry,
        *,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.adapters = adapters
        self.sleeper = sleeper

    def execute(
        self,
        *,
        context: ToolContext,
        tool_id: str,
        payload: dict[str, Any],
    ) -> ToolExecutionRecord:
        definition = self._validate_tool_access(context.agent_definition, tool_id)
        typed_input = self._validate_input(definition, payload)
        adapter = self.adapters.get(tool_id)
        if adapter is None:
            return self._unavailable_record(definition, "adapter_not_registered")
        if definition.availability_state == AvailabilityState.UNAVAILABLE:
            return self._unavailable_record(definition, "registry_unavailable")
        if not adapter.is_available(context):
            return self._unavailable_record(definition, "provider_or_evidence_unavailable")

        result: ToolResult | None = None
        attempts = 0
        for attempts in range(1, definition.retry_policy.max_attempts + 1):
            try:
                result = self._execute_with_timeout(
                    adapter,
                    context,
                    typed_input,
                    definition.timeout_seconds,
                )
                break
            except ToolExecutionError as exception:
                retryable = (
                    exception.transient
                    and exception.code in definition.retry_policy.retryable_failures
                    and attempts < definition.retry_policy.max_attempts
                )
                if retryable:
                    self.sleeper(definition.retry_policy.backoff_seconds)
                    continue
                result = ToolResult(
                    status=ExecutionStatus.FAILED,
                    failure_code=exception.code,
                    failure_message=exception.safe_message,
                    transient=exception.transient,
                )
                break

        assert result is not None
        structured_output = (
            sanitize_llm_narrative(result.structured_output)
            if tool_id == "approved_llm_completion"
            else sanitize_persisted_value(result.structured_output)
        )
        budget = context.agent_definition.cost_token_budget
        budget_exceeded = bool(
            budget
            and (
                (budget.max_tokens is not None and result.token_total > budget.max_tokens)
                or (budget.max_cost_usd is not None and result.cost_total_usd > budget.max_cost_usd)
            )
        )
        sanitized_result = ToolResult(
            status=ExecutionStatus.FAILED if budget_exceeded else result.status,
            structured_output={} if budget_exceeded else structured_output,
            evidence_references=sanitize_persisted_value(result.evidence_references),
            provider_version_metadata=sanitize_persisted_value(result.provider_version_metadata),
            token_total=max(0, result.token_total),
            cost_total_usd=max(0.0, result.cost_total_usd),
            failure_code="budget_exceeded" if budget_exceeded else result.failure_code,
            failure_message=(
                "Registered agent token or cost budget was exceeded."
                if budget_exceeded
                else result.failure_message
            ),
            transient=False if budget_exceeded else result.transient,
            deterministic_fallback=result.deterministic_fallback,
        )
        return ToolExecutionRecord(
            result=sanitized_result,
            activity=self._activity(definition, sanitized_result, attempts),
        )

    @staticmethod
    def _validate_tool_access(agent_definition: AgentDefinition, tool_id: str) -> ToolDefinition:
        if tool_id not in agent_definition.allowed_tool_ids:
            raise ToolExecutionError(
                "undeclared_tool",
                f"Agent {agent_definition.agent_id} is not allowed to use {tool_id}.",
                transient=False,
            )
        if (
            tool_id == "approved_llm_completion"
            and agent_definition.llm_policy == LLMPolicy.PROHIBITED
        ):
            raise ToolExecutionError(
                "llm_policy_denied",
                f"Agent {agent_definition.agent_id} prohibits LLM execution.",
                transient=False,
            )
        definition = ToolRegistry.get(tool_id)
        if definition is None:
            raise ToolExecutionError(
                "unknown_tool",
                f"Tool {tool_id} is not registered.",
                transient=False,
            )
        missing_permissions = set(definition.permissions) - set(agent_definition.permissions)
        if missing_permissions:
            values = sorted(permission.value for permission in missing_permissions)
            raise ToolExecutionError(
                "permission_denied",
                f"Agent lacks required permissions: {values}.",
                transient=False,
            )
        if (
            definition.idempotency_behavior == IdempotencyRequirement.REQUIRED
            and not agent_definition.idempotency_requirement == IdempotencyRequirement.REQUIRED
        ):
            raise ToolExecutionError(
                "idempotency_required",
                "Persistent tool execution requires an idempotent agent scope.",
                transient=False,
            )
        return definition

    @staticmethod
    def _validate_input(definition: ToolDefinition, payload: dict[str, Any]) -> BaseModel:
        schema = SchemaRegistry.get(definition.input_schema_ref)
        if schema is None:
            raise ToolExecutionError(
                "missing_input_schema",
                f"Input schema {definition.input_schema_ref} is unavailable.",
                transient=False,
            )
        try:
            return schema.model_validate(payload)
        except ValidationError as exception:
            raise ToolExecutionError(
                "invalid_tool_input",
                f"Input validation failed for {definition.tool_id}.",
                transient=False,
            ) from exception

    @staticmethod
    def _execute_with_timeout(
        adapter: ToolAdapter,
        context: ToolContext,
        typed_input: BaseModel,
        timeout_seconds: int,
    ) -> ToolResult:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(adapter.execute, context, typed_input)
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeoutError as exception:
            future.cancel()
            raise ToolExecutionError(
                "timeout",
                f"Tool {adapter.tool_id} exceeded its timeout.",
                transient=True,
            ) from exception
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _activity(definition: ToolDefinition, result: ToolResult, attempts: int) -> dict[str, Any]:
        return {
            "tool_id": definition.tool_id,
            "tool_version": definition.version,
            "status": result.status.value,
            "attempts": attempts,
            "side_effect_classification": definition.side_effect_classification.value,
            "deterministic_fallback": result.deterministic_fallback,
            "failure_code": result.failure_code,
        }

    @classmethod
    def _unavailable_record(cls, definition: ToolDefinition, reason: str) -> ToolExecutionRecord:
        result = ToolResult(
            status=ExecutionStatus.UNAVAILABLE,
            structured_output={"availability": "unavailable", "reason": reason},
            failure_code="tool_unavailable",
            failure_message="The registered tool is unavailable in this execution context.",
            deterministic_fallback=definition.tool_id == "approved_llm_completion",
        )
        return ToolExecutionRecord(
            result=result,
            activity=cls._activity(definition, result, 0),
        )


def _execution_uuid(context: ToolContext) -> uuid.UUID:
    return context.execution.execution_id


def _input_uuid(context: ToolContext, key: str) -> uuid.UUID | None:
    value = context.execution_input.get(key)
    if value in (None, ""):
        return None
    return uuid.UUID(str(value))


def _evidence(
    evidence_type: str,
    evidence_id: uuid.UUID | str,
    *,
    source: str,
) -> dict[str, Any]:
    return {
        "evidence_type": evidence_type,
        "evidence_id": str(evidence_id),
        "source": source,
    }


def _website_discovery(context: ToolContext, _input: BaseModel) -> ToolResult:
    website_id = _input_uuid(context, "website_id")
    if website_id is None:
        return ToolResult(
            status=ExecutionStatus.UNAVAILABLE,
            failure_code="website_required",
            failure_message="Website evidence is required.",
        )
    run = context.db.scalar(
        select(DiscoveryRun)
        .where(DiscoveryRun.website_id == website_id)
        .order_by(DiscoveryRun.created_at.desc(), DiscoveryRun.id.desc())
    )
    if run is None:
        return ToolResult(
            status=ExecutionStatus.UNAVAILABLE,
            failure_code="discovery_evidence_unavailable",
            failure_message="No persisted discovery execution is available.",
        )
    status_value = run.status.value if hasattr(run.status, "value") else str(run.status)
    status = {
        "completed": ExecutionStatus.COMPLETED,
        "partial": ExecutionStatus.PARTIAL,
        "failed": ExecutionStatus.FAILED,
    }.get(status_value, ExecutionStatus.UNAVAILABLE)
    return ToolResult(
        status=status,
        structured_output={
            "discovery_status": status_value,
            "urls_discovered": run.urls_discovered,
            "urls_eligible": run.urls_eligible,
            "crawl_limit_reached": run.crawl_limit_reached,
        },
        evidence_references=[_evidence("discovery_run", run.id, source="database")],
    )


def _analysis_result(
    context: ToolContext,
    *,
    evidence_key: str,
    data_key: str,
) -> ToolResult:
    analysis_run_id = _input_uuid(context, "analysis_run_id")
    if analysis_run_id is None:
        return ToolResult(
            status=ExecutionStatus.UNAVAILABLE,
            failure_code="analysis_run_required",
            failure_message="An analysis run is required for retained page evidence.",
        )
    result = context.db.scalar(
        select(AnalysisResult).where(AnalysisResult.analysis_run_id == analysis_run_id)
    )
    if result is None:
        return ToolResult(
            status=ExecutionStatus.UNAVAILABLE,
            failure_code=f"{evidence_key}_unavailable",
            failure_message=f"No persisted {evidence_key} evidence is available.",
        )
    data = getattr(result, data_key)
    return ToolResult(
        status=ExecutionStatus.COMPLETED if data else ExecutionStatus.UNAVAILABLE,
        structured_output={"evidence_available": bool(data)},
        evidence_references=[_evidence(evidence_key, result.id, source="database")],
        provider_version_metadata={
            "lighthouse_version": result.lighthouse_version,
        },
    )


def _playwright(context: ToolContext, _input: BaseModel) -> ToolResult:
    return _analysis_result(
        context,
        evidence_key="playwright_analysis",
        data_key="raw_playwright_data",
    )


def _lighthouse(context: ToolContext, _input: BaseModel) -> ToolResult:
    return _analysis_result(
        context,
        evidence_key="lighthouse_analysis",
        data_key="raw_lighthouse_data",
    )


def _performance_snapshot(
    context: ToolContext,
    *,
    evidence_source: str | None = None,
    evidence_type: str | None = None,
) -> ToolResult:
    analysis_run_id = _input_uuid(context, "analysis_run_id")
    if analysis_run_id is None:
        return ToolResult(
            status=ExecutionStatus.UNAVAILABLE,
            failure_code="analysis_run_required",
            failure_message="An analysis run is required for performance evidence.",
        )
    statement = select(PerformanceSnapshot).where(
        PerformanceSnapshot.analysis_run_id == analysis_run_id
    )
    if evidence_source is not None:
        statement = statement.where(PerformanceSnapshot.evidence_source == evidence_source)
    if evidence_type is not None:
        statement = statement.where(PerformanceSnapshot.evidence_type == evidence_type)
    snapshots = list(context.db.scalars(statement.order_by(PerformanceSnapshot.created_at)))
    if not snapshots:
        return ToolResult(
            status=ExecutionStatus.UNAVAILABLE,
            failure_code="performance_evidence_unavailable",
            failure_message="No matching persisted performance evidence is available.",
        )
    available = [item for item in snapshots if item.availability_status == "available"]
    status = (
        ExecutionStatus.COMPLETED if len(available) == len(snapshots) else ExecutionStatus.PARTIAL
    )
    return ToolResult(
        status=status,
        structured_output={
            "snapshot_count": len(snapshots),
            "available_snapshot_count": len(available),
        },
        evidence_references=[
            _evidence("performance_snapshot", item.id, source="database") for item in snapshots
        ],
    )


def _crux(context: ToolContext, _input: BaseModel) -> ToolResult:
    return _performance_snapshot(context, evidence_source="crux")


def _browser_timing(context: ToolContext, _input: BaseModel) -> ToolResult:
    return _performance_snapshot(context, evidence_type="browser_timing")


def _accessibility(context: ToolContext, _input: BaseModel) -> ToolResult:
    analysis_run_id = _input_uuid(context, "analysis_run_id")
    if analysis_run_id is None:
        return ToolResult(
            status=ExecutionStatus.UNAVAILABLE,
            failure_code="analysis_run_required",
            failure_message="An analysis run is required for accessibility evidence.",
        )
    audits = list(
        context.db.scalars(
            select(AccessibilityAudit)
            .where(AccessibilityAudit.analysis_run_id == analysis_run_id)
            .order_by(AccessibilityAudit.created_at, AccessibilityAudit.id)
        )
    )
    if not audits:
        return ToolResult(
            status=ExecutionStatus.UNAVAILABLE,
            failure_code="accessibility_evidence_unavailable",
            failure_message="No persisted accessibility audit is available.",
        )
    completed = [audit for audit in audits if audit.status == "completed"]
    status = ExecutionStatus.COMPLETED if len(completed) == len(audits) else ExecutionStatus.PARTIAL
    return ToolResult(
        status=status,
        structured_output={
            "audit_count": len(audits),
            "completed_audit_count": len(completed),
            "automated_checks_establish_compliance": False,
        },
        evidence_references=[
            _evidence("accessibility_audit", audit.id, source="database") for audit in audits
        ],
    )


def _site_diagnostics(context: ToolContext, _input: BaseModel) -> ToolResult:
    analysis_run_id = _input_uuid(context, "analysis_run_id")
    if analysis_run_id is None:
        return ToolResult(
            status=ExecutionStatus.UNAVAILABLE,
            failure_code="analysis_run_required",
            failure_message="An analysis run is required for site diagnostics.",
        )
    existing = context.db.scalar(
        select(SiteDiagnosticExecution)
        .where(SiteDiagnosticExecution.analysis_run_id == analysis_run_id)
        .order_by(SiteDiagnosticExecution.created_at.desc(), SiteDiagnosticExecution.id.desc())
    )
    try:
        execution = existing or SiteDiagnosticsService(context.db).execute_diagnostics(
            analysis_run_id,
            idempotency_key=f"{context.execution.idempotency_key}:agent-platform",
        )
    except ValueError as exception:
        return ToolResult(
            status=ExecutionStatus.UNAVAILABLE,
            failure_code="site_diagnostics_unavailable",
            failure_message=str(exception),
        )
    context.db.flush()
    status_value = (
        execution.status.value if hasattr(execution.status, "value") else str(execution.status)
    )
    status = {
        "completed": ExecutionStatus.COMPLETED,
        "partial": ExecutionStatus.PARTIAL,
        "unavailable": ExecutionStatus.UNAVAILABLE,
        "failed": ExecutionStatus.FAILED,
    }.get(status_value, ExecutionStatus.UNAVAILABLE)
    return ToolResult(
        status=status,
        structured_output={
            "diagnostic_status": status_value,
            "evidence_coverage_numerator": execution.evidence_coverage_numerator,
            "evidence_coverage_denominator": execution.evidence_coverage_denominator,
        },
        evidence_references=[
            _evidence("site_diagnostic_execution", execution.id, source="database")
        ],
    )


def _scoring_intelligence(context: ToolContext, _input: BaseModel) -> ToolResult:
    analysis_run_id = _input_uuid(context, "analysis_run_id")
    if analysis_run_id is None:
        return ToolResult(
            status=ExecutionStatus.UNAVAILABLE,
            failure_code="analysis_run_required",
            failure_message="An analysis run is required for scoring.",
        )
    try:
        execution, _created = calculate_score_execution(
            context.db,
            analysis_run_id,
            idempotency_key=f"{context.execution.idempotency_key}:scoring",
        )
    except ScoringIntelligenceError as exception:
        return ToolResult(
            status=(
                ExecutionStatus.UNAVAILABLE
                if exception.status_code in {404, 409}
                else ExecutionStatus.FAILED
            ),
            failure_code=exception.code.casefold(),
            failure_message=exception.safe_message,
        )
    return ToolResult(
        status=ExecutionStatus(execution.status),
        structured_output={
            "score_execution_id": str(execution.execution_id),
            "overall_score": execution.overall_score,
            "confidence_percent": execution.confidence_percent,
            "evidence_coverage_percentage": execution.evidence_coverage_percentage,
            "formula_version": execution.formula_version,
            "llm_calculated": False,
        },
        evidence_references=[
            _evidence("score_execution", execution.execution_id, source="database")
        ],
    )


def _repository_scan(context: ToolContext, _input: BaseModel) -> ToolResult:
    connection_id = _input_uuid(context, "repository_connection_id")
    if connection_id is None:
        return ToolResult(
            status=ExecutionStatus.UNAVAILABLE,
            failure_code="repository_not_configured",
            failure_message="No approved repository connection is configured.",
        )
    scan_id = uuid.uuid5(_execution_uuid(context), "repository_scanning")
    try:
        scan = RepositoryScannerService(context.db).scan_repository(connection_id, scan_id)
    except Exception as exception:
        return ToolResult(
            status=ExecutionStatus.FAILED,
            failure_code="repository_scan_failed",
            failure_message=type(exception).__name__,
        )
    status_value = scan.status.value if hasattr(scan.status, "value") else str(scan.status)
    status = (
        ExecutionStatus.COMPLETED
        if status_value == "completed"
        else ExecutionStatus.PARTIAL
        if status_value == "partial"
        else ExecutionStatus.FAILED
    )
    return ToolResult(
        status=status,
        structured_output={"repository_scan_status": status_value},
        evidence_references=[_evidence("repository_scan_execution", scan.id, source="database")],
    )


def _remediation(context: ToolContext, _input: BaseModel) -> ToolResult:
    website_id = _input_uuid(context, "website_id")
    page_execution_id = _input_uuid(context, "page_analysis_execution_id")
    if website_id is None or page_execution_id is None:
        return ToolResult(
            status=ExecutionStatus.UNAVAILABLE,
            failure_code="remediation_prerequisites_unavailable",
            failure_message="Page-analysis evidence is required for remediation generation.",
            deterministic_fallback=True,
            structured_output={
                "mode": "deterministic_fallback",
                "message": "Retained evidence references require manual remediation review.",
            },
            evidence_references=context.dependency_evidence,
        )
    generation_id = uuid.uuid5(_execution_uuid(context), "remediation_generation")
    generation = generate_actions(
        context.db,
        website_id,
        page_execution_id,
        generation_execution_id=generation_id,
    )
    context.db.flush()
    return ToolResult(
        status=ExecutionStatus.COMPLETED,
        structured_output={"action_generation_status": generation.status},
        evidence_references=[
            _evidence("action_generation_execution", generation.id, source="database")
        ],
    )


def _report(context: ToolContext, _input: BaseModel) -> ToolResult:
    analysis_run_id = _input_uuid(context, "analysis_run_id")
    if analysis_run_id is None:
        return ToolResult(
            status=ExecutionStatus.PARTIAL,
            failure_code="analysis_report_unavailable",
            failure_message="No analysis-run report scope was configured.",
            deterministic_fallback=True,
            structured_output={
                "mode": "evidence_reference_report",
                "partial": True,
            },
            evidence_references=context.dependency_evidence,
        )
    try:
        report, _created = generate_report(
            context.db,
            analysis_run_id,
            idempotency_key=f"{context.execution.idempotency_key}:report-agent",
            workflow_execution_id=context.execution.execution_id,
            allow_active_workflow=True,
        )
    except ReportDeliveryError as exception:
        return ToolResult(
            status=(
                ExecutionStatus.PARTIAL
                if exception.status_code in {404, 409}
                else ExecutionStatus.FAILED
            ),
            failure_code=exception.code.casefold(),
            failure_message=exception.safe_message,
            deterministic_fallback=True,
            structured_output={
                "mode": "evidence_reference_report",
                "partial": True,
            },
            evidence_references=context.dependency_evidence,
        )
    return ToolResult(
        status=ExecutionStatus(report.status),
        structured_output={
            "report_reference": f"report:{report.report_id}",
            "score_execution_reference": (
                str(report.score_execution_id) if report.score_execution_id else None
            ),
            "score_calculated_by_llm": False,
            "generation_mode": "deterministic_fallback",
            "artifact_formats": ["html", "json", "pdf"],
        },
        evidence_references=[
            _evidence("report_execution", report.report_id, source="database"),
            *context.dependency_evidence,
        ],
        deterministic_fallback=True,
    )


def _evidence_retrieval(context: ToolContext, typed_input: BaseModel) -> ToolResult:
    requested = {
        str(item) for item in getattr(typed_input, "evidence_references", []) if str(item).strip()
    }
    available_by_key = {
        f"{item.get('evidence_type')}:{item.get('evidence_id')}": item
        for item in context.dependency_evidence
    }
    if requested:
        resolved = [value for key, value in sorted(available_by_key.items()) if key in requested]
    else:
        resolved = [available_by_key[key] for key in sorted(available_by_key)]
    return ToolResult(
        status=ExecutionStatus.COMPLETED if resolved else ExecutionStatus.UNAVAILABLE,
        structured_output={
            "requested_reference_count": len(requested),
            "resolved_reference_count": len(resolved),
        },
        evidence_references=resolved,
    )


def _url_normalization(_context: ToolContext, typed_input: BaseModel) -> ToolResult:
    if not isinstance(typed_input, URLNormalizationInput):
        raise ToolExecutionError(
            "invalid_tool_input",
            "URL normalization received an invalid typed input.",
            transient=False,
        )
    raw_url = typed_input.raw_url
    approved_origin = typed_input.approved_origin
    parsed = urlsplit(raw_url)
    origin = urlsplit(approved_origin)
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or parsed.hostname is None
        or parsed.hostname.casefold() != (origin.hostname or "").casefold()
    ):
        return ToolResult(
            status=ExecutionStatus.UNAVAILABLE,
            structured_output={
                "normalized_url": None,
                "rejection_reason": "URL is outside the approved HTTP(S) origin.",
            },
        )
    normalized = urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            parsed.path or "/",
            parsed.query,
            "",
        )
    )
    return ToolResult(
        status=ExecutionStatus.COMPLETED,
        structured_output={"normalized_url": normalized, "rejection_reason": None},
        evidence_references=[
            {
                "evidence_type": "normalized_url",
                "evidence_id": fingerprint(normalized),
                "source": "deterministic_local",
            }
        ],
    )


def _llm_unavailable(context: ToolContext, _input: BaseModel) -> ToolResult:
    return ToolResult(
        status=ExecutionStatus.UNAVAILABLE,
        structured_output={
            "provider": None,
            "model_version": None,
            "mode": "deterministic_fallback",
            "grounded_evidence_count": len(context.dependency_evidence),
        },
        evidence_references=context.dependency_evidence,
        provider_version_metadata={
            "provider": "disabled",
            "model_version": "not-configured",
        },
        failure_code="approved_llm_unavailable",
        failure_message="No approved LLM provider is configured.",
        deterministic_fallback=True,
    )


def default_tool_adapters() -> ToolAdapterRegistry:
    adapters = (
        FunctionalToolAdapter("website_discovery", _website_discovery),
        FunctionalToolAdapter("url_normalization", _url_normalization),
        FunctionalToolAdapter("playwright_analysis", _playwright),
        FunctionalToolAdapter("lighthouse_analysis", _lighthouse),
        FunctionalToolAdapter("crux_field_evidence", _crux),
        FunctionalToolAdapter("browser_timing", _browser_timing),
        FunctionalToolAdapter("axe_accessibility", _accessibility),
        FunctionalToolAdapter("accessibility_aggregation", _accessibility),
        FunctionalToolAdapter("site_diagnostics", _site_diagnostics),
        FunctionalToolAdapter("scoring_intelligence", _scoring_intelligence),
        FunctionalToolAdapter("repository_scanning", _repository_scan),
        FunctionalToolAdapter("remediation_generation", _remediation),
        FunctionalToolAdapter("report_generation", _report),
        FunctionalToolAdapter("evidence_retrieval", _evidence_retrieval),
        FunctionalToolAdapter("approved_llm_completion", _llm_unavailable),
    )
    registry = ToolAdapterRegistry(adapters)
    registered_ids = tuple(definition.tool_id for definition in ToolRegistry.get_all())
    if registry.ids() != registered_ids:
        raise ValueError("Executable tool adapters must exactly match the tool registry.")
    return registry


def agent_definition_or_raise(agent_id: str) -> AgentDefinition:
    definition = AgentRegistry.get(agent_id)
    if definition is None:
        raise ValueError(f"Unknown agent: {agent_id}")
    return definition


def tool_uses_secret_redaction(tool_id: str) -> bool:
    definition = ToolRegistry.get(tool_id)
    return bool(
        definition
        and definition.secret_handling_policy
        in {
            SecretHandlingPolicy.RUNTIME_ONLY,
            SecretHandlingPolicy.REDACTED_RUNTIME_ONLY,
        }
    )

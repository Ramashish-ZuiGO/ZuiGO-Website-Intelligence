from collections import defaultdict
from collections.abc import Iterable
from typing import ClassVar

from pydantic import BaseModel

from app.schemas.agent_platform import (
    AgentDefinition,
    ApprovedLLMInput,
    ApprovedLLMOutput,
    AvailabilityState,
    CostTokenBudget,
    EvidenceRetrievalInput,
    EvidenceValidationInput,
    IdempotencyRequirement,
    LLMPolicy,
    MemoryPolicy,
    NormalizedURLOutput,
    PageToolInput,
    PartialFailureBehavior,
    Permission,
    RemediationInput,
    RemediationOutput,
    ReportInput,
    ReportOutput,
    RepositoryAnalysisInput,
    RetryPolicy,
    SecretHandlingPolicy,
    SideEffectClassification,
    StructuredEvidenceOutput,
    ToolDefinition,
    URLNormalizationInput,
    WebsiteAnalysisInput,
    WorkflowCondition,
    WorkflowDefinition,
    WorkflowNodeDefinition,
)


class SchemaRegistry:
    VERSION = "1.0.0"
    _schemas: ClassVar[dict[str, type[BaseModel]]] = {
        "approved_llm_input": ApprovedLLMInput,
        "approved_llm_output": ApprovedLLMOutput,
        "evidence_retrieval_input": EvidenceRetrievalInput,
        "evidence_validation_input": EvidenceValidationInput,
        "normalized_url_output": NormalizedURLOutput,
        "page_tool_input": PageToolInput,
        "remediation_input": RemediationInput,
        "remediation_output": RemediationOutput,
        "report_input": ReportInput,
        "report_output": ReportOutput,
        "repository_analysis_input": RepositoryAnalysisInput,
        "structured_evidence_output": StructuredEvidenceOutput,
        "url_normalization_input": URLNormalizationInput,
        "website_analysis_input": WebsiteAnalysisInput,
    }

    @classmethod
    def has_schema(cls, schema_ref: str) -> bool:
        return schema_ref in cls._schemas

    @classmethod
    def get(cls, schema_ref: str) -> type[BaseModel] | None:
        return cls._schemas.get(schema_ref)


NO_RETRY = RetryPolicy(max_attempts=1, backoff_seconds=0, retryable_failures=())
SAFE_RETRY = RetryPolicy(
    max_attempts=2,
    backoff_seconds=2,
    retryable_failures=("timeout", "temporary_unavailable"),
)


def _tool(
    *,
    tool_id: str,
    input_ref: str,
    output_ref: str = "structured_evidence_output",
    permissions: tuple[Permission, ...],
    timeout: int,
    retry: RetryPolicy = SAFE_RETRY,
    side_effect: SideEffectClassification = SideEffectClassification.PERSISTENT_WRITE,
    idempotency: IdempotencyRequirement = IdempotencyRequirement.REQUIRED,
    evidence: tuple[str, ...],
    secret_policy: SecretHandlingPolicy = SecretHandlingPolicy.NONE,
    availability: AvailabilityState = AvailabilityState.AVAILABLE,
    limitations: str,
) -> ToolDefinition:
    return ToolDefinition(
        tool_id=tool_id,
        version="1.0.0",
        input_schema_ref=input_ref,
        output_schema_ref=output_ref,
        permissions=permissions,
        timeout_seconds=timeout,
        retry_policy=retry,
        side_effect_classification=side_effect,
        idempotency_behavior=idempotency,
        evidence_produced=evidence,
        secret_handling_policy=secret_policy,
        availability_state=availability,
        limitations=limitations,
    )


TOOL_DEFINITIONS = (
    _tool(
        tool_id="website_discovery",
        input_ref="website_analysis_input",
        permissions=(Permission.NETWORK, Permission.DATABASE_READ, Permission.DATABASE_WRITE),
        timeout=180,
        evidence=("discovery_run", "website_pages", "crawl_coverage"),
        limitations="Uses bounded same-site discovery and validated redirects only.",
    ),
    _tool(
        tool_id="url_normalization",
        input_ref="url_normalization_input",
        output_ref="normalized_url_output",
        permissions=(),
        timeout=5,
        retry=NO_RETRY,
        side_effect=SideEffectClassification.NONE,
        idempotency=IdempotencyRequirement.NOT_APPLICABLE,
        evidence=("normalized_url", "rejection_reason"),
        limitations="Normalization does not prove URL reachability or equivalence.",
    ),
    _tool(
        tool_id="playwright_analysis",
        input_ref="page_tool_input",
        permissions=(Permission.NETWORK, Permission.BROWSER, Permission.DATABASE_WRITE),
        timeout=90,
        evidence=("rendered_dom", "browser_observations", "network_observations"),
        limitations="Chromium evidence does not establish support in untested browsers.",
    ),
    _tool(
        tool_id="lighthouse_analysis",
        input_ref="page_tool_input",
        permissions=(Permission.NETWORK, Permission.BROWSER, Permission.DATABASE_WRITE),
        timeout=150,
        evidence=("lighthouse_audit", "lab_metrics"),
        limitations="Laboratory measurements are not field performance data.",
    ),
    _tool(
        tool_id="crux_field_evidence",
        input_ref="page_tool_input",
        permissions=(Permission.NETWORK, Permission.DATABASE_WRITE),
        timeout=30,
        evidence=("crux_field_snapshot",),
        secret_policy=SecretHandlingPolicy.REDACTED_RUNTIME_ONLY,
        availability=AvailabilityState.CONDITIONAL,
        limitations="Available only with an approved API key and a matching CrUX record.",
    ),
    _tool(
        tool_id="browser_timing",
        input_ref="page_tool_input",
        permissions=(Permission.BROWSER, Permission.DATABASE_WRITE),
        timeout=30,
        evidence=("browser_timing_snapshot",),
        limitations="Browser support and cross-origin timing access can limit measurements.",
    ),
    _tool(
        tool_id="axe_accessibility",
        input_ref="page_tool_input",
        permissions=(Permission.BROWSER, Permission.DATABASE_WRITE),
        timeout=45,
        evidence=("axe_findings", "accessibility_nodes"),
        limitations="Automated checks do not establish complete accessibility compliance.",
    ),
    _tool(
        tool_id="accessibility_aggregation",
        input_ref="website_analysis_input",
        permissions=(Permission.DATABASE_READ, Permission.DATABASE_WRITE),
        timeout=30,
        retry=NO_RETRY,
        evidence=("accessibility_audit", "manual_review_requirements"),
        limitations="Aggregation is limited to retained automated and manual-review evidence.",
    ),
    _tool(
        tool_id="site_diagnostics",
        input_ref="website_analysis_input",
        permissions=(Permission.DATABASE_READ, Permission.DATABASE_WRITE),
        timeout=180,
        evidence=("site_diagnostic_execution", "site_diagnostic_findings"),
        limitations="Uses persisted evidence and does not perform a new public crawl.",
    ),
    _tool(
        tool_id="repository_scanning",
        input_ref="repository_analysis_input",
        permissions=(Permission.FILESYSTEM_READ, Permission.DATABASE_WRITE),
        timeout=180,
        evidence=("repository_file_index", "detected_technologies"),
        limitations=(
            "Only approved local roots are scanned; generated and secret files are excluded."
        ),
    ),
    _tool(
        tool_id="remediation_generation",
        input_ref="remediation_input",
        output_ref="remediation_output",
        permissions=(Permission.DATABASE_READ, Permission.DATABASE_WRITE),
        timeout=120,
        evidence=("remediation_actions", "verification_guidance"),
        limitations="Recommendations remain bounded by validated evidence and repository coverage.",
    ),
    _tool(
        tool_id="report_generation",
        input_ref="report_input",
        output_ref="report_output",
        permissions=(Permission.DATABASE_READ, Permission.DATABASE_WRITE),
        timeout=120,
        evidence=("analysis_report",),
        limitations="Reports must retain partial, unavailable, and coverage limitations.",
    ),
    _tool(
        tool_id="evidence_retrieval",
        input_ref="evidence_retrieval_input",
        permissions=(Permission.DATABASE_READ,),
        timeout=30,
        retry=NO_RETRY,
        side_effect=SideEffectClassification.READ_ONLY,
        idempotency=IdempotencyRequirement.NOT_APPLICABLE,
        evidence=("resolved_evidence_references",),
        limitations="Returns only persisted evidence visible to the current execution scope.",
    ),
    _tool(
        tool_id="approved_llm_completion",
        input_ref="approved_llm_input",
        output_ref="approved_llm_output",
        permissions=(Permission.LLM_PROVIDER, Permission.NETWORK),
        timeout=120,
        evidence=("structured_provider_output", "provider_metadata"),
        secret_policy=SecretHandlingPolicy.REDACTED_RUNTIME_ONLY,
        availability=AvailabilityState.CONDITIONAL,
        limitations=(
            "Disabled unless an approved provider is configured; output must be evidence-grounded."
        ),
    ),
)


class ToolRegistry:
    VERSION = "1.0.0"
    _definitions: ClassVar[dict[str, ToolDefinition]] = {}

    @classmethod
    def validate_definitions(
        cls, definitions: Iterable[ToolDefinition]
    ) -> dict[str, ToolDefinition]:
        validated: dict[str, ToolDefinition] = {}
        for definition in definitions:
            if definition.tool_id in validated:
                raise ValueError(f"Duplicate tool ID: {definition.tool_id}")
            if not SchemaRegistry.has_schema(definition.input_schema_ref):
                raise ValueError(f"Unknown input schema: {definition.input_schema_ref}")
            if not SchemaRegistry.has_schema(definition.output_schema_ref):
                raise ValueError(f"Unknown output schema: {definition.output_schema_ref}")
            validated[definition.tool_id] = definition
        return validated

    @classmethod
    def configure(cls, definitions: Iterable[ToolDefinition]) -> None:
        cls._definitions = cls.validate_definitions(definitions)

    @classmethod
    def get_all(cls) -> tuple[ToolDefinition, ...]:
        return tuple(cls._definitions[tool_id] for tool_id in sorted(cls._definitions))

    @classmethod
    def get(cls, tool_id: str) -> ToolDefinition | None:
        return cls._definitions.get(tool_id)


def _agent(
    *,
    agent_id: str,
    name: str,
    purpose: str,
    goals: tuple[str, ...],
    input_ref: str,
    output_ref: str = "structured_evidence_output",
    tools: tuple[str, ...],
    dependencies: tuple[str, ...],
    permissions: tuple[Permission, ...],
    timeout: int,
    memory: MemoryPolicy = MemoryPolicy.EVIDENCE_REFERENCES_ONLY,
    llm: LLMPolicy = LLMPolicy.PROHIBITED,
    budget: CostTokenBudget | None = None,
    behavior: PartialFailureBehavior = PartialFailureBehavior.PRESERVE_PARTIAL,
    limitations: str,
) -> AgentDefinition:
    return AgentDefinition(
        agent_id=agent_id,
        version="1.0.0",
        name=name,
        purpose=purpose,
        supported_goals=goals,
        input_schema_ref=input_ref,
        output_schema_ref=output_ref,
        allowed_tool_ids=tools,
        dependency_agent_ids=dependencies,
        timeout_seconds=timeout,
        retry_policy=SAFE_RETRY,
        idempotency_requirement=IdempotencyRequirement.REQUIRED,
        memory_policy=memory,
        llm_policy=llm,
        permissions=permissions,
        cost_token_budget=budget,
        partial_failure_behavior=behavior,
        limitations=limitations,
    )


AGENT_DEFINITIONS = (
    _agent(
        agent_id="discovery_agent",
        name="Discovery Agent",
        purpose="Build bounded, normalized website inventory evidence.",
        goals=("discover eligible pages", "preserve crawl coverage and exclusions"),
        input_ref="website_analysis_input",
        tools=("website_discovery", "url_normalization"),
        dependencies=(),
        permissions=(Permission.NETWORK, Permission.DATABASE_READ, Permission.DATABASE_WRITE),
        timeout=240,
        limitations="Discovery remains bounded by configured limits and approved origins.",
    ),
    _agent(
        agent_id="performance_agent",
        name="Performance Agent",
        purpose="Collect separate laboratory, field, and browser-timing evidence.",
        goals=("collect lab performance", "collect available field evidence"),
        input_ref="website_analysis_input",
        tools=(
            "playwright_analysis",
            "lighthouse_analysis",
            "crux_field_evidence",
            "browser_timing",
        ),
        dependencies=("discovery_agent",),
        permissions=(
            Permission.NETWORK,
            Permission.BROWSER,
            Permission.DATABASE_WRITE,
        ),
        timeout=300,
        limitations="Field and laboratory evidence must never be substituted for each other.",
    ),
    _agent(
        agent_id="accessibility_agent",
        name="Accessibility Agent",
        purpose="Collect and aggregate automated accessibility evidence with manual limitations.",
        goals=("run automated checks", "identify manual review requirements"),
        input_ref="website_analysis_input",
        tools=("axe_accessibility", "accessibility_aggregation"),
        dependencies=("discovery_agent",),
        permissions=(Permission.BROWSER, Permission.DATABASE_READ, Permission.DATABASE_WRITE),
        timeout=180,
        limitations="Automated evidence cannot prove complete accessibility compliance.",
    ),
    _agent(
        agent_id="site_diagnostics_agent",
        name="Site Diagnostics Agent",
        purpose="Generate deterministic cross-page diagnostics from persisted evidence.",
        goals=("detect cross-page patterns", "preserve coverage and unavailable states"),
        input_ref="website_analysis_input",
        tools=("site_diagnostics", "evidence_retrieval"),
        dependencies=("discovery_agent",),
        permissions=(Permission.DATABASE_READ, Permission.DATABASE_WRITE),
        timeout=240,
        limitations="Does not perform public crawling or infer absent evidence as a clean result.",
    ),
    _agent(
        agent_id="evidence_validation_agent",
        name="Evidence Validation Agent",
        purpose="Validate evidence references, coverage, provenance, and prerequisite status.",
        goals=("validate evidence provenance", "reject unsupported downstream claims"),
        input_ref="evidence_validation_input",
        tools=("evidence_retrieval",),
        dependencies=(
            "performance_agent",
            "accessibility_agent",
            "site_diagnostics_agent",
        ),
        permissions=(Permission.DATABASE_READ,),
        timeout=60,
        behavior=PartialFailureBehavior.MARK_UNAVAILABLE,
        limitations="Validation cannot improve or fabricate missing source evidence.",
    ),
    _agent(
        agent_id="repository_intelligence_agent",
        name="Repository Intelligence Agent",
        purpose="Map validated findings to approved repository structure and symbols.",
        goals=("scan approved repository roots", "map evidence to code locations"),
        input_ref="repository_analysis_input",
        tools=("repository_scanning", "evidence_retrieval"),
        dependencies=("evidence_validation_agent",),
        permissions=(
            Permission.FILESYSTEM_READ,
            Permission.DATABASE_READ,
            Permission.DATABASE_WRITE,
        ),
        timeout=240,
        limitations="Unavailable when no approved repository connection is configured.",
    ),
    _agent(
        agent_id="remediation_agent",
        name="Remediation Agent",
        purpose="Produce evidence-grounded remediation and verification guidance.",
        goals=("generate prioritized remediation", "retain evidence links and limitations"),
        input_ref="remediation_input",
        output_ref="remediation_output",
        tools=("remediation_generation", "evidence_retrieval", "approved_llm_completion"),
        dependencies=("evidence_validation_agent", "repository_intelligence_agent"),
        permissions=(
            Permission.DATABASE_READ,
            Permission.DATABASE_WRITE,
            Permission.NETWORK,
            Permission.LLM_PROVIDER,
        ),
        timeout=180,
        llm=LLMPolicy.OPTIONAL_APPROVED_PROVIDER,
        budget=CostTokenBudget(max_tokens=8000, max_cost_usd=2.0),
        limitations="Provider output is optional and must use only validated evidence.",
    ),
    _agent(
        agent_id="report_agent",
        name="Report Agent",
        purpose="Assemble a versioned report from validated evidence and remediation outputs.",
        goals=("produce evidence-linked report", "preserve partial and unavailable states"),
        input_ref="report_input",
        output_ref="report_output",
        tools=("report_generation", "evidence_retrieval", "approved_llm_completion"),
        dependencies=("remediation_agent",),
        permissions=(
            Permission.DATABASE_READ,
            Permission.DATABASE_WRITE,
            Permission.NETWORK,
            Permission.LLM_PROVIDER,
        ),
        timeout=180,
        llm=LLMPolicy.OPTIONAL_APPROVED_PROVIDER,
        budget=CostTokenBudget(max_tokens=8000, max_cost_usd=2.0),
        limitations="A report cannot claim coverage or compliance beyond retained evidence.",
    ),
)


def _validate_acyclic(
    dependencies: dict[str, set[str]],
    *,
    label: str,
) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError(f"Circular {label} dependency involving {node}")
        if node in visited:
            return
        visiting.add(node)
        for dependency in dependencies[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in sorted(dependencies):
        visit(node)


class AgentRegistry:
    VERSION = "1.0.0"
    _definitions: ClassVar[dict[str, AgentDefinition]] = {}

    @classmethod
    def validate_definitions(
        cls,
        definitions: Iterable[AgentDefinition],
        *,
        tools: ToolRegistry = ToolRegistry,
    ) -> dict[str, AgentDefinition]:
        validated: dict[str, AgentDefinition] = {}
        known_tools = {tool.tool_id: tool for tool in tools.get_all()}
        for definition in definitions:
            if definition.agent_id in validated:
                raise ValueError(f"Duplicate agent ID: {definition.agent_id}")
            if not SchemaRegistry.has_schema(definition.input_schema_ref):
                raise ValueError(f"Unknown input schema: {definition.input_schema_ref}")
            if not SchemaRegistry.has_schema(definition.output_schema_ref):
                raise ValueError(f"Unknown output schema: {definition.output_schema_ref}")
            unknown_tools = set(definition.allowed_tool_ids) - set(known_tools)
            if unknown_tools:
                raise ValueError(f"Unknown tools: {sorted(unknown_tools)}")
            for tool_id in definition.allowed_tool_ids:
                missing_permissions = set(known_tools[tool_id].permissions) - set(
                    definition.permissions
                )
                if missing_permissions:
                    raise ValueError(
                        f"Agent {definition.agent_id} lacks permissions for {tool_id}: "
                        f"{sorted(missing_permissions)}"
                    )
            validated[definition.agent_id] = definition
        known_agents = set(validated)
        for definition in validated.values():
            unknown_dependencies = set(definition.dependency_agent_ids) - known_agents
            if unknown_dependencies:
                raise ValueError(f"Unknown dependencies: {sorted(unknown_dependencies)}")
            if definition.agent_id in definition.dependency_agent_ids:
                raise ValueError(f"Agent {definition.agent_id} cannot depend on itself")
        _validate_acyclic(
            {
                agent_id: set(definition.dependency_agent_ids)
                for agent_id, definition in validated.items()
            },
            label="agent",
        )
        return validated

    @classmethod
    def configure(cls, definitions: Iterable[AgentDefinition]) -> None:
        cls._definitions = cls.validate_definitions(definitions)

    @classmethod
    def get_all(cls) -> tuple[AgentDefinition, ...]:
        return tuple(cls._definitions[agent_id] for agent_id in sorted(cls._definitions))

    @classmethod
    def get(cls, agent_id: str) -> AgentDefinition | None:
        return cls._definitions.get(agent_id)


def _node(
    agent_id: str,
    *dependencies: str,
    optional: tuple[str, ...] = (),
    condition: WorkflowCondition = WorkflowCondition.ALWAYS,
) -> WorkflowNodeDefinition:
    return WorkflowNodeDefinition(
        agent_id=agent_id,
        depends_on=dependencies,
        optional_dependencies=optional,
        condition=condition,
    )


FULL_WEBSITE_NODES = (
    _node("discovery_agent"),
    _node("performance_agent", "discovery_agent"),
    _node("accessibility_agent", "discovery_agent"),
    _node("site_diagnostics_agent", "discovery_agent"),
    _node(
        "evidence_validation_agent",
        "performance_agent",
        "accessibility_agent",
        "site_diagnostics_agent",
    ),
    _node(
        "repository_intelligence_agent",
        "evidence_validation_agent",
        condition=WorkflowCondition.REPOSITORY_CONFIGURED,
    ),
    _node(
        "remediation_agent",
        "evidence_validation_agent",
        optional=("repository_intelligence_agent",),
    ),
    _node("report_agent", "remediation_agent"),
)

WORKFLOW_DEFINITIONS = (
    WorkflowDefinition(
        workflow_id="full_website_analysis",
        version="1.0.0",
        name="Full Website Analysis",
        purpose="Run the deterministic end-to-end evidence and reporting dependency graph.",
        orchestrator_id="workflow_orchestrator",
        orchestrator_version="1.0.0",
        deterministic=True,
        nodes=FULL_WEBSITE_NODES,
        entry_agent_ids=("discovery_agent",),
        terminal_agent_ids=("report_agent",),
        deterministic_order=(
            "discovery_agent",
            "accessibility_agent",
            "performance_agent",
            "site_diagnostics_agent",
            "evidence_validation_agent",
            "repository_intelligence_agent",
            "remediation_agent",
            "report_agent",
        ),
        limitations="Repository intelligence is conditional on an approved connection.",
    ),
    WorkflowDefinition(
        workflow_id="repository_remediation",
        version="1.0.0",
        name="Repository Remediation",
        purpose="Validate retained evidence, map repository locations, and produce remediation.",
        orchestrator_id="workflow_orchestrator",
        orchestrator_version="1.0.0",
        deterministic=True,
        nodes=(
            _node("evidence_validation_agent"),
            _node("repository_intelligence_agent", "evidence_validation_agent"),
            _node("remediation_agent", "repository_intelligence_agent"),
            _node("report_agent", "remediation_agent"),
        ),
        entry_agent_ids=("evidence_validation_agent",),
        terminal_agent_ids=("report_agent",),
        deterministic_order=(
            "evidence_validation_agent",
            "repository_intelligence_agent",
            "remediation_agent",
            "report_agent",
        ),
        limitations="Requires retained evidence and an approved repository connection.",
    ),
    WorkflowDefinition(
        workflow_id="reanalysis",
        version="1.0.0",
        name="Reanalysis",
        purpose="Create a new immutable evidence history for an existing website analysis scope.",
        orchestrator_id="workflow_orchestrator",
        orchestrator_version="1.0.0",
        deterministic=True,
        nodes=(
            _node("discovery_agent"),
            _node("performance_agent", "discovery_agent"),
            _node("accessibility_agent", "discovery_agent"),
            _node("site_diagnostics_agent", "discovery_agent"),
            _node(
                "evidence_validation_agent",
                "performance_agent",
                "accessibility_agent",
                "site_diagnostics_agent",
            ),
            _node("remediation_agent", "evidence_validation_agent"),
            _node("report_agent", "remediation_agent"),
        ),
        entry_agent_ids=("discovery_agent",),
        terminal_agent_ids=("report_agent",),
        deterministic_order=(
            "discovery_agent",
            "accessibility_agent",
            "performance_agent",
            "site_diagnostics_agent",
            "evidence_validation_agent",
            "remediation_agent",
            "report_agent",
        ),
        limitations="Creates new history and never overwrites a completed execution.",
    ),
)


class WorkflowRegistry:
    VERSION = "1.0.0"
    _definitions: ClassVar[dict[str, WorkflowDefinition]] = {}

    @staticmethod
    def deterministic_topological_order(
        node_dependencies: dict[str, set[str]],
    ) -> tuple[str, ...]:
        remaining = {node: set(dependencies) for node, dependencies in node_dependencies.items()}
        ordered: list[str] = []
        while remaining:
            ready = sorted(node for node, dependencies in remaining.items() if not dependencies)
            if not ready:
                raise ValueError("Circular workflow dependency")
            ordered.extend(ready)
            for node in ready:
                remaining.pop(node)
            for dependencies in remaining.values():
                dependencies.difference_update(ready)
        return tuple(ordered)

    @classmethod
    def validate_definitions(
        cls,
        definitions: Iterable[WorkflowDefinition],
        *,
        agents: AgentRegistry = AgentRegistry,
    ) -> dict[str, WorkflowDefinition]:
        validated: dict[str, WorkflowDefinition] = {}
        known_agents = {agent.agent_id for agent in agents.get_all()}
        for definition in definitions:
            if definition.workflow_id in validated:
                raise ValueError(f"Duplicate workflow ID: {definition.workflow_id}")
            if not definition.deterministic:
                raise ValueError("Workflow definitions must be deterministic")
            node_ids = [node.agent_id for node in definition.nodes]
            if len(node_ids) != len(set(node_ids)):
                raise ValueError(f"Duplicate workflow node in {definition.workflow_id}")
            unknown_agents = set(node_ids) - known_agents
            if unknown_agents:
                raise ValueError(f"Unknown workflow agents: {sorted(unknown_agents)}")
            dependencies = {
                node.agent_id: set(node.depends_on) | set(node.optional_dependencies)
                for node in definition.nodes
            }
            for node_id, node_dependencies in dependencies.items():
                unknown_dependencies = node_dependencies - set(node_ids)
                if unknown_dependencies:
                    raise ValueError(
                        f"Unknown workflow dependencies for {node_id}: "
                        f"{sorted(unknown_dependencies)}"
                    )
            order = cls.deterministic_topological_order(dependencies)
            if order != definition.deterministic_order:
                raise ValueError("Declared deterministic order does not match dependency graph")
            entries = tuple(sorted(node for node, deps in dependencies.items() if not deps))
            if tuple(sorted(definition.entry_agent_ids)) != entries:
                raise ValueError("Invalid workflow entry nodes")
            outgoing: dict[str, set[str]] = defaultdict(set)
            for node_id, node_dependencies in dependencies.items():
                for dependency in node_dependencies:
                    outgoing[dependency].add(node_id)
            terminals = tuple(sorted(node for node in node_ids if not outgoing[node]))
            if tuple(sorted(definition.terminal_agent_ids)) != terminals:
                raise ValueError("Invalid workflow terminal nodes")
            reachable: set[str] = set()
            frontier = list(definition.entry_agent_ids)
            while frontier:
                node_id = frontier.pop()
                if node_id in reachable:
                    continue
                reachable.add(node_id)
                frontier.extend(sorted(outgoing[node_id]))
            if reachable != set(node_ids):
                raise ValueError("Workflow contains unreachable nodes")
            validated[definition.workflow_id] = definition
        return validated

    @classmethod
    def configure(cls, definitions: Iterable[WorkflowDefinition]) -> None:
        cls._definitions = cls.validate_definitions(definitions)

    @classmethod
    def get_all(cls) -> tuple[WorkflowDefinition, ...]:
        return tuple(cls._definitions[workflow_id] for workflow_id in sorted(cls._definitions))

    @classmethod
    def get(cls, workflow_id: str) -> WorkflowDefinition | None:
        return cls._definitions.get(workflow_id)


ToolRegistry.configure(TOOL_DEFINITIONS)
AgentRegistry.configure(AGENT_DEFINITIONS)
WorkflowRegistry.configure(WORKFLOW_DEFINITIONS)

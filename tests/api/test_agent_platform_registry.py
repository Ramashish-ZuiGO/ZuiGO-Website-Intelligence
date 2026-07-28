import pytest
from app.schemas.agent_platform import (
    AgentDefinition,
    MemoryPolicy,
    ToolDefinition,
    WorkflowDefinition,
    WorkflowNodeDefinition,
)
from app.services.agent_platform_registry import (
    AGENT_DEFINITIONS,
    TOOL_DEFINITIONS,
    WORKFLOW_DEFINITIONS,
    AgentRegistry,
    ToolRegistry,
    WorkflowRegistry,
)
from pydantic import ValidationError

EXPECTED_AGENT_IDS = {
    "discovery_agent",
    "performance_agent",
    "accessibility_agent",
    "site_diagnostics_agent",
    "repository_intelligence_agent",
    "evidence_validation_agent",
    "remediation_agent",
    "report_agent",
}
EXPECTED_TOOL_IDS = {
    "website_discovery",
    "url_normalization",
    "playwright_analysis",
    "lighthouse_analysis",
    "crux_field_evidence",
    "browser_timing",
    "axe_accessibility",
    "accessibility_aggregation",
    "site_diagnostics",
    "scoring_intelligence",
    "repository_scanning",
    "remediation_generation",
    "report_generation",
    "evidence_retrieval",
    "approved_llm_completion",
}
EXPECTED_WORKFLOW_IDS = {
    "full_website_analysis",
    "repository_remediation",
    "reanalysis",
}


def test_exact_versioned_agent_and_tool_ids() -> None:
    agents = AgentRegistry.get_all()
    tools = ToolRegistry.get_all()

    assert {agent.agent_id for agent in agents} == EXPECTED_AGENT_IDS
    assert {tool.tool_id for tool in tools} == EXPECTED_TOOL_IDS
    assert len(agents) == 8
    assert len(tools) == 15
    assert all(agent.version == "1.0.0" for agent in agents)
    assert all(tool.version == "1.0.0" for tool in tools)
    assert ToolRegistry.get("approved_llm_completion").availability_state == "conditional"


def test_agent_registry_rejects_duplicates_unknown_references_and_cycles() -> None:
    with pytest.raises(ValueError, match="Duplicate agent ID"):
        AgentRegistry.validate_definitions((*AGENT_DEFINITIONS, AGENT_DEFINITIONS[0]))

    unknown_tool = AGENT_DEFINITIONS[0].model_copy(update={"allowed_tool_ids": ("unknown_tool",)})
    with pytest.raises(ValueError, match="Unknown tools"):
        AgentRegistry.validate_definitions((unknown_tool, *AGENT_DEFINITIONS[1:]))

    unknown_dependency = AGENT_DEFINITIONS[0].model_copy(
        update={"dependency_agent_ids": ("unknown_agent",)}
    )
    with pytest.raises(ValueError, match="Unknown dependencies"):
        AgentRegistry.validate_definitions((unknown_dependency, *AGENT_DEFINITIONS[1:]))

    cyclic_discovery = AGENT_DEFINITIONS[0].model_copy(
        update={"dependency_agent_ids": ("report_agent",)}
    )
    with pytest.raises(ValueError, match="Circular agent dependency"):
        AgentRegistry.validate_definitions((cyclic_discovery, *AGENT_DEFINITIONS[1:]))

    missing_schema = AGENT_DEFINITIONS[0].model_copy(update={"input_schema_ref": "missing_schema"})
    with pytest.raises(ValueError, match="Unknown input schema"):
        AgentRegistry.validate_definitions((missing_schema, *AGENT_DEFINITIONS[1:]))


def test_agent_contract_rejects_invalid_version_policies_purpose_and_goals() -> None:
    payload = AGENT_DEFINITIONS[0].model_dump()
    for field, value in (
        ("version", "1"),
        ("purpose", " "),
        ("supported_goals", ("",)),
        ("memory_policy", "global_hidden_memory"),
        ("llm_policy", "unrestricted"),
    ):
        with pytest.raises(ValidationError):
            AgentDefinition.model_validate({**payload, field: value})
    assert AGENT_DEFINITIONS[0].memory_policy == MemoryPolicy.EVIDENCE_REFERENCES_ONLY


def test_tool_registry_rejects_duplicates_invalid_versions_and_missing_schemas() -> None:
    with pytest.raises(ValueError, match="Duplicate tool ID"):
        ToolRegistry.validate_definitions((*TOOL_DEFINITIONS, TOOL_DEFINITIONS[0]))

    missing_schema = TOOL_DEFINITIONS[0].model_copy(update={"output_schema_ref": "missing_schema"})
    with pytest.raises(ValueError, match="Unknown output schema"):
        ToolRegistry.validate_definitions((missing_schema, *TOOL_DEFINITIONS[1:]))

    payload = TOOL_DEFINITIONS[0].model_dump()
    for field, value in (
        ("version", "latest"),
        ("tool_id", "Invalid Tool"),
        ("limitations", ""),
    ):
        with pytest.raises(ValidationError):
            ToolDefinition.model_validate({**payload, field: value})


def test_exact_workflows_and_full_analysis_dependency_graph() -> None:
    workflows = WorkflowRegistry.get_all()
    assert {workflow.workflow_id for workflow in workflows} == EXPECTED_WORKFLOW_IDS
    assert len(workflows) == 3
    full = WorkflowRegistry.get("full_website_analysis")
    assert full is not None
    nodes = {node.agent_id: node for node in full.nodes}
    assert nodes["discovery_agent"].depends_on == ()
    assert nodes["performance_agent"].depends_on == ("discovery_agent",)
    assert nodes["accessibility_agent"].depends_on == ("discovery_agent",)
    assert nodes["site_diagnostics_agent"].depends_on == ("discovery_agent",)
    assert set(nodes["evidence_validation_agent"].depends_on) == {
        "performance_agent",
        "accessibility_agent",
        "site_diagnostics_agent",
    }
    assert nodes["repository_intelligence_agent"].condition == "repository_configured"
    assert nodes["repository_intelligence_agent"].optional_dependencies == ()
    assert nodes["remediation_agent"].optional_dependencies == ("repository_intelligence_agent",)
    assert full.entry_agent_ids == ("discovery_agent",)
    assert full.terminal_agent_ids == ("report_agent",)
    assert full.orchestrator_id == "workflow_orchestrator"
    assert full.orchestrator_id not in EXPECTED_AGENT_IDS


def test_workflow_ordering_is_deterministic() -> None:
    for workflow in WORKFLOW_DEFINITIONS:
        dependencies = {
            node.agent_id: set(node.depends_on) | set(node.optional_dependencies)
            for node in workflow.nodes
        }
        assert (
            WorkflowRegistry.deterministic_topological_order(dependencies)
            == workflow.deterministic_order
        )
        assert WorkflowRegistry.validate_definitions((workflow,))[workflow.workflow_id]


def test_workflow_registry_rejects_invalid_graphs_and_definitions() -> None:
    base = WORKFLOW_DEFINITIONS[2]
    with pytest.raises(ValueError, match="Duplicate workflow ID"):
        WorkflowRegistry.validate_definitions((base, base))

    unknown_node = WorkflowNodeDefinition(agent_id="unknown_agent")
    with pytest.raises(ValueError, match="Unknown workflow agents"):
        WorkflowRegistry.validate_definitions(
            (base.model_copy(update={"nodes": (*base.nodes, unknown_node)}),)
        )

    circular_nodes = (
        WorkflowNodeDefinition(agent_id="discovery_agent", depends_on=("report_agent",)),
        WorkflowNodeDefinition(agent_id="report_agent", depends_on=("discovery_agent",)),
    )
    with pytest.raises(ValueError, match="Circular workflow dependency"):
        WorkflowRegistry.validate_definitions(
            (
                base.model_copy(
                    update={
                        "nodes": circular_nodes,
                        "entry_agent_ids": ("discovery_agent",),
                        "terminal_agent_ids": ("report_agent",),
                        "deterministic_order": (
                            "discovery_agent",
                            "report_agent",
                        ),
                    }
                ),
            )
        )

    invalid_entry = base.model_copy(update={"entry_agent_ids": ("report_agent",)})
    with pytest.raises(ValueError, match="Invalid workflow entry"):
        WorkflowRegistry.validate_definitions((invalid_entry,))

    invalid_terminal = base.model_copy(update={"terminal_agent_ids": ("discovery_agent",)})
    with pytest.raises(ValueError, match="Invalid workflow terminal"):
        WorkflowRegistry.validate_definitions((invalid_terminal,))

    with pytest.raises(ValueError, match="must be deterministic"):
        WorkflowRegistry.validate_definitions((base.model_copy(update={"deterministic": False}),))

    payload = base.model_dump()
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate({**payload, "version": "v1"})

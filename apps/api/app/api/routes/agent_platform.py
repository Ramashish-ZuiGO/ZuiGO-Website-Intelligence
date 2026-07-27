from fastapi import APIRouter, HTTPException

from app.schemas.agent_platform import AgentDefinition, ToolDefinition, WorkflowDefinition
from app.services.agent_platform_registry import (
    AgentRegistry,
    ToolRegistry,
    WorkflowRegistry,
)

router = APIRouter(tags=["Agent platform metadata"])


@router.get("/agents", response_model=list[AgentDefinition])
def get_agents() -> tuple[AgentDefinition, ...]:
    return AgentRegistry.get_all()


@router.get("/agents/{agent_id}", response_model=AgentDefinition)
def get_agent(agent_id: str) -> AgentDefinition:
    definition = AgentRegistry.get(agent_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Agent definition not found")
    return definition


@router.get("/tools", response_model=list[ToolDefinition])
def get_tools() -> tuple[ToolDefinition, ...]:
    return ToolRegistry.get_all()


@router.get("/tools/{tool_id}", response_model=ToolDefinition)
def get_tool(tool_id: str) -> ToolDefinition:
    definition = ToolRegistry.get(tool_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Tool definition not found")
    return definition


@router.get("/workflows", response_model=list[WorkflowDefinition])
def get_workflows() -> tuple[WorkflowDefinition, ...]:
    return WorkflowRegistry.get_all()


@router.get("/workflows/{workflow_id}", response_model=WorkflowDefinition)
def get_workflow(workflow_id: str) -> WorkflowDefinition:
    definition = WorkflowRegistry.get(workflow_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Workflow definition not found")
    return definition

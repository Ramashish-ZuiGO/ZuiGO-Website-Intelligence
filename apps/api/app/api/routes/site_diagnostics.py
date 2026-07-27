from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models.analysis_run import AnalysisRun, AnalysisStatus
from app.models.site_diagnostic import (
    DiagnosticScopeEnum,
    SiteDiagnosticExecution,
    SiteDiagnosticExecutionStatusEnum,
    SiteDiagnosticFinding,
)
from app.models.website import Website
from app.schemas.site_diagnostic import (
    SiteDiagnosticExecutionResponse,
    SiteDiagnosticFindingDetailResponse,
    SiteDiagnosticFindingResponse,
    SiteDiagnosticGenerateRequest,
    SiteDiagnosticLinkGraphResponse,
)
from app.services.site_diagnostic_rules import (
    DiagnosticCategoryEnum,
    DiagnosticRuleDefinition,
    DiagnosticSeverityEnum,
    SiteDiagnosticRuleRegistry,
)
from app.services.site_diagnostics_service import SiteDiagnosticsService

router = APIRouter(tags=["Site diagnostics"])
DatabaseSession = Annotated[Session, Depends(get_db)]
FindingConfidence = Literal["high", "medium", "low", "unavailable"]


def _website_or_404(db: Session, website_id: UUID) -> Website:
    website = db.get(Website, website_id)
    if website is None:
        raise HTTPException(status_code=404, detail="Website not found")
    return website


def _latest_execution(
    db: Session,
    *,
    website_id: UUID | None = None,
    analysis_run_id: UUID | None = None,
) -> SiteDiagnosticExecution | None:
    statement = select(SiteDiagnosticExecution)
    if website_id is not None:
        statement = statement.where(SiteDiagnosticExecution.website_id == website_id)
    if analysis_run_id is not None:
        statement = statement.where(SiteDiagnosticExecution.analysis_run_id == analysis_run_id)
    return db.execute(
        statement.order_by(
            SiteDiagnosticExecution.started_at.desc(),
            SiteDiagnosticExecution.created_at.desc(),
            SiteDiagnosticExecution.id.desc(),
        ).limit(1)
    ).scalar_one_or_none()


@router.get(
    "/analysis-runs/{run_id}/site-diagnostics",
    response_model=SiteDiagnosticExecutionResponse,
)
def get_execution_by_run(
    run_id: UUID,
    db: DatabaseSession,
) -> SiteDiagnosticExecution:
    if db.get(AnalysisRun, run_id) is None:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    execution = _latest_execution(db, analysis_run_id=run_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Site diagnostic execution not found")
    return execution


@router.post(
    "/analysis-runs/{run_id}/site-diagnostics/generate",
    response_model=SiteDiagnosticExecutionResponse,
)
def generate_site_diagnostics(
    run_id: UUID,
    db: DatabaseSession,
    request: Annotated[SiteDiagnosticGenerateRequest | None, Body()] = None,
    idempotency_header: Annotated[
        str | None,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ] = None,
) -> SiteDiagnosticExecution:
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    status = run.status.value if hasattr(run.status, "value") else str(run.status)
    if status != AnalysisStatus.COMPLETED.value:
        raise HTTPException(
            status_code=409,
            detail="Site diagnostics require a completed analysis run",
        )
    body_key = request.idempotency_key if request is not None else None
    if idempotency_header and body_key and idempotency_header != body_key:
        raise HTTPException(
            status_code=422,
            detail="Body and Idempotency-Key header values must match",
        )
    idempotency_key = idempotency_header or body_key or str(uuid4())
    try:
        return SiteDiagnosticsService(db).execute_diagnostics(
            run_id,
            idempotency_key=idempotency_key,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get(
    "/websites/{website_id}/site-diagnostics",
    response_model=SiteDiagnosticExecutionResponse,
)
def get_latest_execution_for_website(
    website_id: UUID,
    db: DatabaseSession,
) -> SiteDiagnosticExecution:
    _website_or_404(db, website_id)
    execution = _latest_execution(db, website_id=website_id)
    if execution is None:
        raise HTTPException(
            status_code=404,
            detail="No site diagnostics found for this website",
        )
    return execution


@router.get(
    "/websites/{website_id}/site-diagnostics/history",
    response_model=list[SiteDiagnosticExecutionResponse],
)
def get_execution_history_for_website(
    website_id: UUID,
    db: DatabaseSession,
    status: Annotated[SiteDiagnosticExecutionStatusEnum | None, Query()] = None,
    analysis_run_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SiteDiagnosticExecution]:
    _website_or_404(db, website_id)
    statement = select(SiteDiagnosticExecution).where(
        SiteDiagnosticExecution.website_id == website_id
    )
    if status is not None:
        statement = statement.where(SiteDiagnosticExecution.status == status.value)
    if analysis_run_id is not None:
        statement = statement.where(SiteDiagnosticExecution.analysis_run_id == analysis_run_id)
    return list(
        db.execute(
            statement.order_by(
                SiteDiagnosticExecution.started_at.desc(),
                SiteDiagnosticExecution.created_at.desc(),
                SiteDiagnosticExecution.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )


@router.get(
    "/websites/{website_id}/site-diagnostics/findings",
    response_model=list[SiteDiagnosticFindingResponse],
)
def get_findings_for_website(
    website_id: UUID,
    db: DatabaseSession,
    execution_id: Annotated[UUID | None, Query()] = None,
    rule_id: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    category: Annotated[DiagnosticCategoryEnum | None, Query()] = None,
    severity: Annotated[DiagnosticSeverityEnum | None, Query()] = None,
    scope: Annotated[DiagnosticScopeEnum | None, Query()] = None,
    confidence: Annotated[FindingConfidence | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SiteDiagnosticFinding]:
    _website_or_404(db, website_id)
    if execution_id is None:
        execution = _latest_execution(db, website_id=website_id)
        if execution is None:
            return []
    else:
        execution = db.execute(
            select(SiteDiagnosticExecution).where(
                SiteDiagnosticExecution.id == execution_id,
                SiteDiagnosticExecution.website_id == website_id,
            )
        ).scalar_one_or_none()
        if execution is None:
            raise HTTPException(
                status_code=404,
                detail="Site diagnostic execution not found for this website",
            )

    statement = select(SiteDiagnosticFinding).where(
        SiteDiagnosticFinding.execution_id == execution.id
    )
    if rule_id is not None:
        if rule_id not in {rule.id for rule in SiteDiagnosticRuleRegistry.get_all_rules()}:
            raise HTTPException(status_code=422, detail="Unknown diagnostic rule ID")
        statement = statement.where(SiteDiagnosticFinding.rule_id == rule_id)
    if category is not None:
        statement = statement.where(SiteDiagnosticFinding.category == category.value)
    if severity is not None:
        statement = statement.where(SiteDiagnosticFinding.severity == severity.value)
    if scope is not None:
        statement = statement.where(SiteDiagnosticFinding.scope == scope.value)
    if confidence is not None:
        statement = statement.where(SiteDiagnosticFinding.confidence == confidence)
    return list(
        db.execute(
            statement.order_by(
                SiteDiagnosticFinding.created_at,
                SiteDiagnosticFinding.id,
            )
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )


@router.get(
    "/site-diagnostics/findings/{finding_id}",
    response_model=SiteDiagnosticFindingDetailResponse,
)
def get_finding_by_id(
    finding_id: UUID,
    db: DatabaseSession,
) -> SiteDiagnosticFinding:
    finding = db.execute(
        select(SiteDiagnosticFinding)
        .options(selectinload(SiteDiagnosticFinding.occurrences))
        .where(SiteDiagnosticFinding.id == finding_id)
    ).scalar_one_or_none()
    if finding is None:
        raise HTTPException(
            status_code=404,
            detail="Site diagnostic finding not found",
        )
    return finding


@router.get(
    "/websites/{website_id}/site-diagnostics/link-graph",
    response_model=SiteDiagnosticLinkGraphResponse,
)
def get_link_graph(
    website_id: UUID,
    db: DatabaseSession,
    execution_id: Annotated[UUID | None, Query()] = None,
    node_limit: Annotated[int, Query(ge=1, le=1000)] = 250,
    node_offset: Annotated[int, Query(ge=0)] = 0,
    edge_limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
    edge_offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    _website_or_404(db, website_id)
    if execution_id is None:
        execution = _latest_execution(db, website_id=website_id)
    else:
        execution = db.execute(
            select(SiteDiagnosticExecution).where(
                SiteDiagnosticExecution.id == execution_id,
                SiteDiagnosticExecution.website_id == website_id,
            )
        ).scalar_one_or_none()
    if execution is None:
        raise HTTPException(
            status_code=404,
            detail="Site diagnostic execution not found for this website",
        )
    graph = execution.partial_completion_metadata.get("link_graph")
    if not isinstance(graph, dict):
        raise HTTPException(
            status_code=409,
            detail="Link-graph evidence is unavailable for this execution",
        )
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    malformed = (
        graph.get("malformed_edges") if isinstance(graph.get("malformed_edges"), list) else []
    )
    return {
        "execution_id": execution.id,
        "website_id": website_id,
        "evidence_complete": bool(graph.get("evidence_complete")),
        "discovery_run_id": graph.get("discovery_run_id"),
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "total_malformed_edges": len(malformed),
        "node_offset": node_offset,
        "node_limit": node_limit,
        "edge_offset": edge_offset,
        "edge_limit": edge_limit,
        "nodes": nodes[node_offset : node_offset + node_limit],
        "edges": edges[edge_offset : edge_offset + edge_limit],
        "malformed_edges": malformed,
    }


@router.get(
    "/metadata/site-diagnostic-rules",
    response_model=list[DiagnosticRuleDefinition],
)
def get_site_diagnostic_rules(
    category: Annotated[DiagnosticCategoryEnum | None, Query()] = None,
) -> list[DiagnosticRuleDefinition]:
    rules = list(SiteDiagnosticRuleRegistry.get_all_rules())
    if category is not None:
        rules = [rule for rule in rules if rule.category == category]
    return rules

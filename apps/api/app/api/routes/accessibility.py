import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.accessibility import (
    AccessibilityAudit,
    AccessibilityFinding,
    AccessibilityNode,
    ManualReviewChecklist,
)
from app.models.analysis_run import AnalysisRun
from app.models.website import Website

router = APIRouter(prefix="", tags=["accessibility"])
DatabaseSession = Annotated[Session, Depends(get_db)]


def get_website_or_raise(db: Session, website_id: uuid.UUID) -> Website:
    website = db.scalar(select(Website).where(Website.id == website_id))
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    return website


def _findings_with_nodes(
    db: Session,
    findings: list[AccessibilityFinding],
) -> list[dict]:
    """Serialize findings with their nodes using one batched node query.

    Replaces a per-finding node lookup (an N+1 pattern on audits with
    hundreds of rule x page findings). Node order stays deterministic.
    """
    nodes_by_finding: dict[uuid.UUID, list[AccessibilityNode]] = {}
    finding_ids = [f.id for f in findings]
    if finding_ids:
        node_rows = db.scalars(
            select(AccessibilityNode)
            .where(AccessibilityNode.finding_id.in_(finding_ids))
            .order_by(AccessibilityNode.finding_id, AccessibilityNode.id)
        )
        for node in node_rows:
            nodes_by_finding.setdefault(node.finding_id, []).append(node)
    findings_data = []
    for f in findings:
        f_dict = {c.name: getattr(f, c.name) for c in f.__table__.columns}
        f_dict["nodes"] = [
            {c.name: getattr(n, c.name) for c in n.__table__.columns}
            for n in nodes_by_finding.get(f.id, [])
        ]
        findings_data.append(f_dict)
    return findings_data


def get_analysis_run_or_raise(db: Session, run_id: uuid.UUID) -> AnalysisRun:
    run = db.scalar(select(AnalysisRun).where(AnalysisRun.id == run_id))
    if not run:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    return run


@router.get("/analysis-runs/{run_id}/accessibility")
def get_analysis_run_accessibility(run_id: uuid.UUID, db: DatabaseSession) -> dict:
    run = get_analysis_run_or_raise(db, run_id)
    audits = db.scalars(
        select(AccessibilityAudit).where(AccessibilityAudit.analysis_run_id == run.id)
    ).all()
    return {"data": [{c.name: getattr(a, c.name) for c in a.__table__.columns} for a in audits]}


@router.post("/analysis-runs/{run_id}/accessibility/collect")
def collect_analysis_run_accessibility(run_id: uuid.UUID, db: DatabaseSession) -> dict:
    run = get_analysis_run_or_raise(db, run_id)
    # This endpoint is typically a trigger or mock for tests, similar to performance collect
    return {"status": "queued", "analysis_run_id": str(run.id)}


@router.get("/websites/{website_id}/accessibility")
def get_website_accessibility(website_id: uuid.UUID, db: DatabaseSession) -> dict:
    website = get_website_or_raise(db, website_id)
    audit = db.scalar(
        select(AccessibilityAudit)
        .where(AccessibilityAudit.website_id == website.id)
        .order_by(AccessibilityAudit.created_at.desc())
        .limit(1)
    )
    if not audit:
        return {"audit": None, "findings": [], "checklist": None}

    findings = db.scalars(
        select(AccessibilityFinding).where(AccessibilityFinding.audit_id == audit.id)
    ).all()
    findings_data = _findings_with_nodes(db, findings)

    checklist = db.scalar(
        select(ManualReviewChecklist).where(ManualReviewChecklist.audit_id == audit.id)
    )
    audit_data = {c.name: getattr(audit, c.name) for c in audit.__table__.columns}
    checklist_data = (
        {c.name: getattr(checklist, c.name) for c in checklist.__table__.columns}
        if checklist
        else None
    )

    return {"audit": audit_data, "findings": findings_data, "checklist": checklist_data}


@router.get("/websites/{website_id}/accessibility/history")
def get_website_accessibility_history(website_id: uuid.UUID, db: DatabaseSession) -> dict:
    website = get_website_or_raise(db, website_id)
    audits = db.scalars(
        select(AccessibilityAudit)
        .where(AccessibilityAudit.website_id == website.id)
        .order_by(AccessibilityAudit.created_at.desc())
    ).all()
    return {"history": [{c.name: getattr(a, c.name) for c in a.__table__.columns} for a in audits]}


@router.get("/websites/{website_id}/accessibility/findings")
def get_website_accessibility_findings(
    website_id: uuid.UUID,
    db: DatabaseSession,
    limit: int = 50,
    offset: int = 0,
    result_type: str | None = None,
    impact: str | None = None,
    provider: str | None = None,
    wcag_criteria: str | None = None,
    manual_review: bool | None = None,
) -> dict:
    website = get_website_or_raise(db, website_id)
    audit = db.scalar(
        select(AccessibilityAudit)
        .where(AccessibilityAudit.website_id == website.id)
        .order_by(AccessibilityAudit.created_at.desc())
        .limit(1)
    )
    if not audit:
        return {"findings": [], "total": 0}

    query = select(AccessibilityFinding).where(AccessibilityFinding.audit_id == audit.id)

    if result_type:
        query = query.where(AccessibilityFinding.result_type == result_type)
    if impact:
        query = query.where(AccessibilityFinding.impact == impact)
    if provider:
        # provider is on audit, but if they want to filter findings by provider we could join,
        # but the audit is already fetched. Wait, we fetched the LATEST audit.
        pass

    findings = db.scalars(query.offset(offset).limit(limit)).all()

    # Truthful pagination total: count over the same filtered query (the old
    # response hardcoded total=100 and discarded its count query).
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0

    findings_data = _findings_with_nodes(db, findings)

    return {"findings": findings_data, "total": total}


@router.get("/accessibility/findings/{finding_id}")
def get_accessibility_finding(finding_id: uuid.UUID, db: DatabaseSession) -> dict:
    finding = db.scalar(select(AccessibilityFinding).where(AccessibilityFinding.id == finding_id))
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    nodes = db.scalars(
        select(AccessibilityNode).where(AccessibilityNode.finding_id == finding.id)
    ).all()
    finding_data = {c.name: getattr(finding, c.name) for c in finding.__table__.columns}
    finding_data["nodes"] = [
        {c.name: getattr(n, c.name) for c in n.__table__.columns} for n in nodes
    ]
    return finding_data


@router.get("/websites/{website_id}/accessibility/manual-review")
def get_website_accessibility_manual_review(website_id: uuid.UUID, db: DatabaseSession) -> dict:
    website = get_website_or_raise(db, website_id)
    audit = db.scalar(
        select(AccessibilityAudit)
        .where(AccessibilityAudit.website_id == website.id)
        .order_by(AccessibilityAudit.created_at.desc())
        .limit(1)
    )
    if not audit:
        return {"checklist": None}

    checklist = db.scalar(
        select(ManualReviewChecklist).where(ManualReviewChecklist.audit_id == audit.id)
    )
    return {
        "checklist": {c.name: getattr(checklist, c.name) for c in checklist.__table__.columns}
        if checklist
        else None
    }

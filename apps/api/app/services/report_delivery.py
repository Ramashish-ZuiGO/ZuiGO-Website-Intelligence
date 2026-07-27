import hashlib
import html
import json
import re
import textwrap
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AccessibilityAudit,
    ActionGenerationExecution,
    ActionItem,
    AgentExecution,
    AgentRun,
    AnalysisFinding,
    AnalysisRun,
    ReportArtifact,
    ReportExecution,
    ReportSection,
    ReportSnapshot,
    ScoreExecution,
    SiteDiagnosticExecution,
    SiteDiagnosticFinding,
)
from app.services.scoring_formula import FORMULA_ID, FORMULA_VERSION

REPORT_VERSION = "1.0.0"
TEMPLATE_ID = "zuigo_evidence_report"
TEMPLATE_VERSION = "1.0.0"
ARTIFACT_MEDIA_TYPES = {
    "html": "text/html; charset=utf-8",
    "pdf": "application/pdf",
    "json": "application/json",
}
TERMINAL_WORKFLOW_STATUSES = {"completed", "partial", "failed", "cancelled", "unavailable"}
SECTION_DEFINITIONS = (
    ("executive_summary", "Executive Summary"),
    ("scores", "Overall and Category Scores"),
    ("performance", "Performance"),
    ("accessibility", "Accessibility"),
    ("site_diagnostics", "Site-Wide Diagnostics"),
    ("security_technical", "Security and Technical Findings"),
    ("content_seo", "Content and SEO Findings"),
    ("priority_action_plan", "Priority Action Plan"),
    ("remediation", "Remediation Guidance"),
    ("coverage_limitations", "Evidence Coverage and Limitations"),
    ("methodology", "Methodology and Formula Versions"),
    ("multi_agent_execution", "Multi-Agent Execution Summary"),
)
SAFE_FILENAME_PATTERN = re.compile(r"[^a-z0-9._-]+")
PRIVATE_KEYS = {
    "chain_of_thought",
    "hidden_reasoning",
    "internal_monologue",
    "private_reasoning",
    "reasoning",
    "scratchpad",
}
SECRET_MARKERS = ("api_key", "authorization", "cookie", "credential", "password", "secret")


class ReportDeliveryError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status_code = status_code


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sanitize_persisted_value(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = key.casefold()
            if normalized in PRIVATE_KEYS:
                continue
            if any(marker in normalized for marker in SECRET_MARKERS):
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = sanitize_persisted_value(item)
        return sanitized
    if isinstance(value, (list, tuple, set)):
        return [sanitize_persisted_value(item) for item in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _evidence(evidence_type: str, evidence_id: uuid.UUID | str) -> dict[str, str]:
    return {
        "evidence_type": evidence_type,
        "evidence_id": str(evidence_id),
        "source": "database",
    }


def _safe_filename(website_name: str | None, report_id: uuid.UUID, artifact_format: str) -> str:
    base = SAFE_FILENAME_PATTERN.sub(
        "-",
        (website_name or "website-report").strip().casefold(),
    ).strip("-._")
    base = base[:80] or "website-report"
    return f"{base}-{str(report_id)[:8]}.{artifact_format}"


def _section(
    key: str,
    *,
    status: str,
    content: dict[str, Any],
    evidence: list[dict[str, Any]],
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    title = dict(SECTION_DEFINITIONS)[key]
    return {
        "section_key": key,
        "title": title,
        "status": status,
        "content": sanitize_persisted_value(content),
        "evidence_references": sanitize_persisted_value(evidence),
        "unavailable_reason": unavailable_reason,
    }


def _latest_score(db: Session, run_id: uuid.UUID) -> ScoreExecution | None:
    return db.scalar(
        select(ScoreExecution)
        .options(
            selectinload(ScoreExecution.categories),
            selectinload(ScoreExecution.contributions),
            selectinload(ScoreExecution.explanation),
        )
        .where(ScoreExecution.analysis_run_id == run_id)
        .order_by(ScoreExecution.created_at.desc(), ScoreExecution.id.desc())
    )


def _workflow_or_raise(
    db: Session,
    run: AnalysisRun,
    workflow_execution_id: uuid.UUID | None,
    *,
    allow_active_workflow: bool,
) -> AgentExecution:
    statement = select(AgentExecution).where(
        AgentExecution.analysis_run_id == run.id,
        AgentExecution.project_id == run.website.project_id,
        AgentExecution.workflow_id == "full_website_analysis",
    )
    if workflow_execution_id is not None:
        statement = statement.where(AgentExecution.execution_id == workflow_execution_id)
    else:
        statement = statement.order_by(AgentExecution.created_at.desc(), AgentExecution.id.desc())
    workflow = db.scalar(statement)
    if workflow is None:
        raise ReportDeliveryError(
            "WORKFLOW_EXECUTION_NOT_FOUND",
            "No full website analysis workflow exists for this analysis run.",
            404,
        )
    if not allow_active_workflow and workflow.status not in TERMINAL_WORKFLOW_STATUSES:
        raise ReportDeliveryError(
            "WORKFLOW_NOT_TERMINAL",
            "The report cannot be generated until the workflow reaches a terminal state.",
            409,
        )
    return workflow


def _loaded_run(db: Session, run_id: uuid.UUID) -> AnalysisRun:
    run = db.scalar(
        select(AnalysisRun)
        .options(
            selectinload(AnalysisRun.website),
            selectinload(AnalysisRun.result),
            selectinload(AnalysisRun.score),
            selectinload(AnalysisRun.interpretation),
            selectinload(AnalysisRun.findings),
            selectinload(AnalysisRun.diagnostics),
        )
        .where(AnalysisRun.id == run_id)
    )
    if run is None:
        raise ReportDeliveryError("ANALYSIS_RUN_NOT_FOUND", "Analysis run not found.", 404)
    return run


def _finding_payload(findings: list[AnalysisFinding]) -> list[dict[str, Any]]:
    return [
        {
            "finding_id": str(item.id),
            "finding_code": item.finding_code,
            "title": item.title,
            "category": item.category,
            "severity": item.severity.value,
            "affected_url": item.affected_url,
            "confidence_percent": item.confidence_percent,
            "evidence_reference": f"analysis_finding:{item.id}",
        }
        for item in findings
    ]


def _build_sections(
    db: Session,
    run: AnalysisRun,
    workflow: AgentExecution,
    score: ScoreExecution | None,
) -> list[dict[str, Any]]:
    result_ref = [_evidence("analysis_result", run.result.id)] if run.result else []
    score_ref = [_evidence("score_execution", score.execution_id)] if score else []
    finding_refs = [_evidence("analysis_finding", item.id) for item in run.findings]

    diagnostics = db.scalar(
        select(SiteDiagnosticExecution)
        .where(SiteDiagnosticExecution.analysis_run_id == run.id)
        .order_by(SiteDiagnosticExecution.created_at.desc(), SiteDiagnosticExecution.id.desc())
    )
    diagnostic_findings = (
        list(
            db.scalars(
                select(SiteDiagnosticFinding)
                .where(SiteDiagnosticFinding.execution_id == diagnostics.id)
                .order_by(
                    SiteDiagnosticFinding.severity,
                    SiteDiagnosticFinding.rule_id,
                    SiteDiagnosticFinding.id,
                )
            )
        )
        if diagnostics
        else []
    )
    diagnostic_refs = (
        [_evidence("site_diagnostic_execution", diagnostics.execution_id)] if diagnostics else []
    )
    accessibility = list(
        db.scalars(
            select(AccessibilityAudit)
            .where(AccessibilityAudit.analysis_run_id == run.id)
            .order_by(AccessibilityAudit.created_at, AccessibilityAudit.id)
        )
    )
    accessibility_refs = [_evidence("accessibility_audit", item.id) for item in accessibility]
    action_generation = db.scalar(
        select(ActionGenerationExecution)
        .where(ActionGenerationExecution.website_id == run.website_id)
        .order_by(
            ActionGenerationExecution.created_at.desc(),
            ActionGenerationExecution.id.desc(),
        )
    )
    actions = (
        list(
            db.scalars(
                select(ActionItem)
                .where(ActionItem.generation_execution_id == action_generation.id)
                .order_by(ActionItem.priority_score.desc(), ActionItem.id)
            )
        )
        if action_generation
        else []
    )
    action_refs = [_evidence("action_item", item.id) for item in actions]
    agent_runs = list(
        db.scalars(
            select(AgentRun)
            .where(AgentRun.execution_id == workflow.id)
            .order_by(AgentRun.created_at, AgentRun.agent_id, AgentRun.attempt)
        )
    )
    workflow_ref = [_evidence("agent_execution", workflow.execution_id)]

    technical_findings = [
        item
        for item in run.findings
        if item.category.casefold()
        in {"security", "best_practices", "best-practices", "technical", "performance"}
    ]
    content_findings = [
        item for item in run.findings if item.category.casefold() in {"seo", "content", "metadata"}
    ]
    overall_score = (
        score.overall_score if score else (run.score.overall_score if run.score else None)
    )
    summary_status = "available" if result_ref or score_ref or finding_refs else "unavailable"
    sections = [
        _section(
            "executive_summary",
            status=summary_status,
            content={
                "generation_mode": "deterministic_fallback",
                "analysis_status": run.status.value,
                "workflow_status": workflow.status,
                "overall_score": overall_score,
                "verified_finding_count": len(run.findings),
                "statement": (
                    "This summary is derived only from retained evidence and execution records."
                    if summary_status == "available"
                    else "No retained evidence is available for an executive summary."
                ),
            },
            evidence=[*result_ref, *score_ref, *finding_refs, *workflow_ref],
            unavailable_reason=(
                None
                if summary_status == "available"
                else "Analysis evidence and score evidence are unavailable."
            ),
        ),
        _section(
            "scores",
            status="available" if score else "unavailable",
            content={
                "overall_score": score.overall_score if score else None,
                "categories": (
                    [
                        {
                            "category_id": item.category_id,
                            "score": item.final_score,
                            "band": item.band,
                            "included": item.included,
                            "contribution": item.contribution,
                        }
                        for item in score.categories
                    ]
                    if score
                    else []
                ),
                "formula_id": score.formula_id if score else FORMULA_ID,
                "formula_version": score.formula_version if score else FORMULA_VERSION,
                "calculated_by_llm": False,
            },
            evidence=score_ref,
            unavailable_reason=None if score else "No persisted explainable score snapshot exists.",
        ),
        _section(
            "performance",
            status="available" if run.result else "unavailable",
            content={
                "laboratory_evidence_available": bool(
                    run.result and run.result.raw_lighthouse_data
                ),
                "browser_evidence_available": bool(run.result and run.result.raw_playwright_data),
                "field_and_lab_are_distinct": True,
                "http_status_code": run.result.http_status_code if run.result else None,
            },
            evidence=result_ref,
            unavailable_reason=None if run.result else "Performance evidence was not analysed.",
        ),
        _section(
            "accessibility",
            status="available" if accessibility else "unavailable",
            content={
                "audit_count": len(accessibility),
                "completed_audit_count": sum(item.status == "completed" for item in accessibility),
                "violation_count": sum(item.violation_count or 0 for item in accessibility),
                "incomplete_count": sum(item.incomplete_count or 0 for item in accessibility),
                "automated_checks_establish_compliance": False,
                "manual_review_required": True,
            },
            evidence=accessibility_refs,
            unavailable_reason=(
                None if accessibility else "Accessibility evidence was not analysed."
            ),
        ),
        _section(
            "site_diagnostics",
            status=(
                "available"
                if diagnostics and diagnostics.status == "completed"
                else "incomplete"
                if diagnostics
                else "unavailable"
            ),
            content={
                "execution_status": diagnostics.status if diagnostics else "not_analysed",
                "finding_count": len(diagnostic_findings),
                "findings": [
                    {
                        "finding_id": str(item.id),
                        "rule_id": item.rule_id,
                        "title": item.title,
                        "severity": item.severity,
                        "scope": item.scope,
                        "affected_page_count": item.affected_page_count,
                    }
                    for item in diagnostic_findings
                ],
            },
            evidence=diagnostic_refs,
            unavailable_reason=(
                None if diagnostics else "Site-wide diagnostics were not analysed."
            ),
        ),
        _section(
            "security_technical",
            status="available" if run.result else "unavailable",
            content={
                "finding_count": len(technical_findings),
                "findings": _finding_payload(technical_findings),
                "zero_findings_means_clean": False,
            },
            evidence=[
                *result_ref,
                *[_evidence("analysis_finding", item.id) for item in technical_findings],
            ],
            unavailable_reason=None if run.result else "Technical evidence was not analysed.",
        ),
        _section(
            "content_seo",
            status="available" if run.result or diagnostics else "unavailable",
            content={
                "finding_count": len(content_findings),
                "findings": _finding_payload(content_findings),
                "site_diagnostic_finding_count": sum(
                    item.category.casefold() in {"content", "metadata", "indexability"}
                    for item in diagnostic_findings
                ),
            },
            evidence=[
                *result_ref,
                *diagnostic_refs,
                *[_evidence("analysis_finding", item.id) for item in content_findings],
            ],
            unavailable_reason=(
                None if run.result or diagnostics else "Content and SEO evidence were not analysed."
            ),
        ),
        _section(
            "priority_action_plan",
            status="available" if action_generation else "unavailable",
            content={
                "generation_status": (
                    action_generation.status if action_generation else "not_analysed"
                ),
                "action_count": len(actions),
                "actions": [
                    {
                        "action_id": str(item.id),
                        "title": item.issue_title,
                        "priority_score": item.priority_score,
                        "priority_formula_version": item.priority_formula_version,
                        "responsible_role": item.responsible_role,
                        "status": item.status,
                    }
                    for item in actions
                ],
            },
            evidence=action_refs,
            unavailable_reason=(
                None if action_generation else "No persisted action-plan generation exists."
            ),
        ),
        _section(
            "remediation",
            status="available" if actions else "unavailable",
            content={
                "guidance": [
                    {
                        "action_id": str(item.id),
                        "exact_correction": item.exact_correction,
                        "implementation_steps": item.implementation_steps,
                        "verification_steps": item.verification_steps,
                        "limitations": item.limitations,
                    }
                    for item in actions
                ],
                "narrative_provider": "deterministic_fallback",
            },
            evidence=action_refs,
            unavailable_reason=None if actions else "No grounded remediation guidance exists.",
        ),
        _section(
            "coverage_limitations",
            status="available",
            content={
                "score_evidence_coverage_numerator": (
                    score.evidence_coverage_numerator if score else 0
                ),
                "score_evidence_coverage_denominator": (
                    score.evidence_coverage_denominator if score else 5
                ),
                "score_evidence_coverage_percentage": (
                    score.evidence_coverage_percentage if score else None
                ),
                "limitations": [
                    "Unavailable evidence is not interpreted as a successful result.",
                    "Automated accessibility evidence cannot prove complete compliance.",
                    "Laboratory performance evidence is not field evidence.",
                    "No competitor or search-engine ranking comparison is made.",
                ],
            },
            evidence=[*score_ref, *workflow_ref],
        ),
        _section(
            "methodology",
            status="available",
            content={
                "overall_score_formula": {
                    "formula_id": FORMULA_ID,
                    "version": FORMULA_VERSION,
                    "unchanged": True,
                },
                "priority_formula": {"version": "1.0.0", "unchanged": True},
                "report_version": REPORT_VERSION,
                "template_id": TEMPLATE_ID,
                "template_version": TEMPLATE_VERSION,
                "llm_calculates_scores": False,
            },
            evidence=score_ref,
        ),
        _section(
            "multi_agent_execution",
            status=(
                "available"
                if workflow.status == "completed"
                else "incomplete"
                if workflow.status == "partial"
                else "failed"
                if workflow.status == "failed"
                else "available"
            ),
            content={
                "execution_id": str(workflow.execution_id),
                "workflow_id": workflow.workflow_id,
                "workflow_version": workflow.workflow_version,
                "status": workflow.status,
                "agents": [
                    {
                        "agent_run_id": str(item.agent_run_id),
                        "agent_id": item.agent_id,
                        "agent_version": item.agent_version,
                        "status": item.status,
                        "attempt": item.attempt,
                    }
                    for item in agent_runs
                ],
                "private_reasoning_included": False,
            },
            evidence=workflow_ref,
        ),
    ]
    return sections


def _json_artifact(snapshot: dict[str, Any]) -> bytes:
    return json.dumps(
        snapshot,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _html_value(value: Any) -> str:
    if value is None:
        return "Unavailable"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (dict, list)):
        return html.escape(json.dumps(value, sort_keys=True, ensure_ascii=False))
    return html.escape(str(value))


def _html_artifact(snapshot: dict[str, Any]) -> bytes:
    sections = snapshot["sections"]
    toc = "".join(
        f'<li><a href="#{html.escape(item["section_key"])}">{html.escape(item["title"])}</a></li>'
        for item in sections
    )
    body = []
    for item in sections:
        content_rows = "".join(
            "<tr>"
            f'<th scope="row">{html.escape(str(key).replace("_", " ").title())}</th>'
            f"<td><pre>{_html_value(value)}</pre></td>"
            "</tr>"
            for key, value in sorted(item["content"].items())
        )
        refs = "".join(
            "<li>"
            f"{html.escape(str(ref['evidence_type']))}:"
            f"{html.escape(str(ref['evidence_id']))}"
            "</li>"
            for ref in item["evidence_references"]
        )
        body.append(
            f'<section aria-labelledby="{item["section_key"]}-heading" '
            f'id="{item["section_key"]}">'
            f'<h2 id="{item["section_key"]}-heading">{html.escape(item["title"])}</h2>'
            f"<p><strong>Status:</strong> {html.escape(item['status'])}</p>"
            + (
                f'<p role="note">{html.escape(item["unavailable_reason"])}</p>'
                if item["unavailable_reason"]
                else ""
            )
            + f"<table><caption>{html.escape(item['title'])} evidence summary</caption>"
            f"<tbody>{content_rows}</tbody></table>"
            f"<h3>Evidence references</h3><ul>{refs or '<li>None retained</li>'}</ul>"
            "</section>"
        )
    document = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(snapshot['title'])}</title>"
        "<style>"
        "body{font-family:system-ui,sans-serif;max-width:72rem;margin:auto;padding:2rem;"
        "line-height:1.5;color:#172033}a{color:#0645ad}a:focus{outline:3px solid #e8790c;"
        "outline-offset:3px}nav,section{margin:2rem 0;padding:1.25rem;border:1px solid #ccd3df;"
        "border-radius:.5rem}table{border-collapse:collapse;width:100%}th,td{padding:.6rem;"
        "border:1px solid #ccd3df;text-align:left;vertical-align:top}pre{white-space:pre-wrap;"
        "word-break:break-word;font:inherit}@media print{nav{break-after:page}section{break-inside:"
        "avoid}body{max-width:none}}"
        "</style></head><body><header><h1>"
        f"{html.escape(snapshot['title'])}</h1>"
        f"<p>Generated: {html.escape(snapshot['generated_at'])}</p>"
        f"<p>Report ID: {html.escape(snapshot['report_id'])}</p></header>"
        f'<nav aria-label="Report sections"><h2>Table of contents</h2><ol>{toc}</ol></nav>'
        f"<main>{''.join(body)}</main>"
        "<footer><p>Evidence-grounded report. Unavailable evidence is identified explicitly."
        "</p></footer></body></html>"
    )
    return document.encode("utf-8")


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_artifact(snapshot: dict[str, Any]) -> bytes:
    page_text: list[list[str]] = [
        [
            snapshot["title"],
            f"Report ID: {snapshot['report_id']}",
            f"Generated: {snapshot['generated_at']}",
            "",
            "Table of contents",
            *[
                f"{position}. {item['title']}"
                for position, item in enumerate(snapshot["sections"], 1)
            ],
        ]
    ]
    for item in snapshot["sections"]:
        lines = [
            item["title"],
            f"Status: {item['status']}",
        ]
        if item["unavailable_reason"]:
            lines.extend(textwrap.wrap(item["unavailable_reason"], width=86))
        for key, value in sorted(item["content"].items()):
            rendered = f"{key.replace('_', ' ').title()}: {json.dumps(value, sort_keys=True)}"
            lines.extend(textwrap.wrap(rendered, width=86) or [""])
        lines.append("Evidence references:")
        lines.extend(
            f"- {ref['evidence_type']}:{ref['evidence_id']}" for ref in item["evidence_references"]
        )
        for page_index, start in enumerate(range(0, len(lines), 46)):
            chunk = lines[start : start + 46]
            if page_index:
                chunk = [f"{item['title']} (continued)", *chunk]
            page_text.append(chunk)

    page_count = len(page_text)
    font_object_id = 3 + page_count * 2
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        font_object_id: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    page_ids: list[int] = []
    for index, lines in enumerate(page_text):
        page_object_id = 3 + index * 2
        stream_object_id = page_object_id + 1
        page_ids.append(page_object_id)
        commands = ["BT", "/F1 10 Tf", "54 790 Td", "14 TL"]
        for line in lines:
            safe_line = _pdf_escape(line.encode("latin-1", "replace").decode("latin-1"))
            commands.append(f"({safe_line}) Tj")
            commands.append("T*")
        commands.extend(
            [
                "ET",
                "BT",
                "/F1 9 Tf",
                "54 28 Td",
                f"(Page {index + 1} of {page_count} - {snapshot['generated_at']}) Tj",
                "ET",
            ]
        )
        stream = "\n".join(commands).encode("latin-1")
        objects[page_object_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
            f"/Resources << /Font << /F1 {font_object_id} 0 R >> >> "
            f"/Contents {stream_object_id} 0 R >>"
        ).encode()
        objects[stream_object_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )
    objects[2] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{item} 0 R' for item in page_ids)}] "
        f"/Count {page_count} >>"
    ).encode()

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id in range(1, font_object_id + 1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode())
        output.extend(objects[object_id])
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {font_object_id + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        (
            f"trailer\n<< /Size {font_object_id + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    return bytes(output)


def _artifact_content(artifact_format: str, snapshot: dict[str, Any]) -> bytes:
    if artifact_format == "json":
        return _json_artifact(snapshot)
    if artifact_format == "html":
        return _html_artifact(snapshot)
    if artifact_format == "pdf":
        return _pdf_artifact(snapshot)
    raise ValueError(f"Unsupported report format: {artifact_format}")


def generate_report(
    db: Session,
    run_id: uuid.UUID,
    *,
    idempotency_key: str,
    workflow_execution_id: uuid.UUID | None = None,
    report_type: str = "full_analysis",
    allow_active_workflow: bool = False,
) -> tuple[ReportExecution, bool]:
    normalized_key = idempotency_key.strip()
    if not normalized_key:
        raise ReportDeliveryError(
            "INVALID_IDEMPOTENCY_KEY", "Idempotency key cannot be empty.", 422
        )
    run = _loaded_run(db, run_id)
    workflow = _workflow_or_raise(
        db,
        run,
        workflow_execution_id,
        allow_active_workflow=allow_active_workflow,
    )
    score = _latest_score(db, run.id)
    sections = _build_sections(db, run, workflow, score)
    evidence_references = sorted(
        {
            canonical_json(reference): reference
            for section in sections
            for reference in section["evidence_references"]
        }.values(),
        key=canonical_json,
    )
    evidence_input = {
        "analysis_run_id": str(run.id),
        "analysis_updated_at": run.updated_at.isoformat(),
        "workflow_execution_id": str(workflow.execution_id),
        "workflow_status": workflow.status,
        "score_execution_id": str(score.execution_id) if score else None,
        "report_type": report_type,
        "report_version": REPORT_VERSION,
        "template_id": TEMPLATE_ID,
        "template_version": TEMPLATE_VERSION,
        "sections": sections,
        "evidence_references": evidence_references,
    }
    input_fingerprint = fingerprint(evidence_input)
    existing = db.scalar(
        select(ReportExecution)
        .options(
            selectinload(ReportExecution.sections),
            selectinload(ReportExecution.artifacts),
            selectinload(ReportExecution.snapshot),
        )
        .where(
            ReportExecution.analysis_run_id == run.id,
            ReportExecution.report_type == report_type,
            ReportExecution.report_version == REPORT_VERSION,
            ReportExecution.idempotency_key == normalized_key,
        )
    )
    if existing is not None:
        if existing.input_fingerprint != input_fingerprint:
            raise ReportDeliveryError(
                "REPORT_IDEMPOTENCY_CONFLICT",
                "The idempotency key is already associated with different report evidence.",
                409,
            )
        return existing, False

    report_id = uuid.uuid4()
    generated_at = datetime.now(UTC)
    unavailable = [
        section["section_key"]
        for section in sections
        if section["status"] in {"unavailable", "excluded"}
    ]
    numerator = len(sections) - len(unavailable)
    denominator = len(sections)
    coverage = round(numerator / denominator * 100, 2) if denominator else None
    report = ReportExecution(
        report_id=report_id,
        project_id=run.website.project_id,
        website_id=run.website_id,
        analysis_run_id=run.id,
        workflow_execution_id=workflow.id,
        score_execution_id=score.id if score else None,
        report_type=report_type,
        report_version=REPORT_VERSION,
        template_id=TEMPLATE_ID,
        template_version=TEMPLATE_VERSION,
        input_fingerprint=input_fingerprint,
        idempotency_key=normalized_key,
        status="partial" if unavailable else "completed",
        evidence_coverage_numerator=numerator,
        evidence_coverage_denominator=denominator,
        evidence_coverage_percentage=coverage,
        confidence_percent=(
            score.confidence_percent
            if score
            else run.score.confidence_percent
            if run.score
            else None
        ),
        unavailable_sections=unavailable,
        provider_version_metadata={
            "generation_mode": "deterministic_fallback",
            "llm_provider": "unavailable",
            "report_agent_id": "report_agent",
            "report_agent_version": "1.0.0",
            "report_generation_tool_version": "1.0.0",
        },
        failure_details={},
        partial_completion_details=({"unavailable_sections": unavailable} if unavailable else {}),
        started_at=generated_at,
        completed_at=generated_at,
    )
    db.add(report)
    db.flush()
    persisted_sections = [
        ReportSection(
            section_id=uuid.uuid5(report_id, f"section:{section['section_key']}"),
            report_execution_id=report.id,
            section_key=section["section_key"],
            position=position,
            title=section["title"],
            status=section["status"],
            content=section["content"],
            evidence_references=section["evidence_references"],
            unavailable_reason=section["unavailable_reason"],
        )
        for position, section in enumerate(sections, 1)
    ]
    db.add_all(persisted_sections)
    snapshot_payload = {
        "schema_version": REPORT_VERSION,
        "report_id": str(report_id),
        "title": f"{run.website.name or 'Website'} analysis report",
        "generated_at": generated_at.isoformat(),
        "project_id": str(run.website.project_id),
        "website_id": str(run.website_id),
        "analysis_run_id": str(run.id),
        "workflow_execution_id": str(workflow.execution_id),
        "score_execution_id": str(score.execution_id) if score else None,
        "status": report.status,
        "evidence_coverage": {
            "numerator": numerator,
            "denominator": denominator,
            "percentage": coverage,
        },
        "confidence_percent": report.confidence_percent,
        "sections": [
            {
                **section,
                "position": position,
                "section_id": str(persisted_sections[position - 1].section_id),
            }
            for position, section in enumerate(sections, 1)
        ],
        "limitations": [
            "Unavailable evidence is not represented as passed.",
            "Narrative generation used the deterministic fallback.",
            "No private reasoning, secrets, or internal file paths are included.",
        ],
    }
    snapshot = ReportSnapshot(
        snapshot_id=uuid.uuid5(report_id, "snapshot:1"),
        report_execution_id=report.id,
        snapshot_payload=snapshot_payload,
        evidence_references=evidence_references,
    )
    db.add(snapshot)
    for artifact_format in ("html", "pdf", "json"):
        content = _artifact_content(artifact_format, snapshot_payload)
        artifact_id = uuid.uuid5(report_id, f"artifact:{artifact_format}:1")
        db.add(
            ReportArtifact(
                artifact_id=artifact_id,
                report_execution_id=report.id,
                format=artifact_format,
                media_type=ARTIFACT_MEDIA_TYPES[artifact_format],
                filename=_safe_filename(
                    run.website.name,
                    report_id,
                    artifact_format,
                ),
                size_bytes=len(content),
                checksum_sha256=hashlib.sha256(content).hexdigest(),
                storage_location=f"database://report-artifacts/{artifact_id}",
                content=content,
            )
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.scalar(
            select(ReportExecution)
            .options(
                selectinload(ReportExecution.sections),
                selectinload(ReportExecution.artifacts),
                selectinload(ReportExecution.snapshot),
            )
            .where(
                ReportExecution.analysis_run_id == run.id,
                ReportExecution.report_type == report_type,
                ReportExecution.report_version == REPORT_VERSION,
                ReportExecution.idempotency_key == normalized_key,
            )
        )
        if concurrent is None or concurrent.input_fingerprint != input_fingerprint:
            raise
        return concurrent, False
    return load_report(db, report_id), True


def load_report(db: Session, report_id: uuid.UUID) -> ReportExecution:
    report = db.scalar(
        select(ReportExecution)
        .options(
            selectinload(ReportExecution.sections),
            selectinload(ReportExecution.artifacts),
            selectinload(ReportExecution.snapshot),
        )
        .where(ReportExecution.report_id == report_id)
    )
    if report is None:
        raise ReportDeliveryError("REPORT_NOT_FOUND", "Report not found.", 404)
    return report


def load_artifact(
    db: Session,
    report_id: uuid.UUID,
    artifact_format: str,
) -> ReportArtifact:
    if artifact_format not in ARTIFACT_MEDIA_TYPES:
        raise ReportDeliveryError(
            "REPORT_FORMAT_UNSUPPORTED",
            "Supported report formats are html, pdf, and json.",
            422,
        )
    report = db.scalar(select(ReportExecution).where(ReportExecution.report_id == report_id))
    if report is None:
        raise ReportDeliveryError("REPORT_NOT_FOUND", "Report not found.", 404)
    artifact = db.scalar(
        select(ReportArtifact).where(
            ReportArtifact.report_execution_id == report.id,
            ReportArtifact.format == artifact_format,
        )
    )
    if artifact is None:
        raise ReportDeliveryError(
            "REPORT_ARTIFACT_UNAVAILABLE",
            "The requested report artifact is unavailable.",
            404,
        )
    return artifact

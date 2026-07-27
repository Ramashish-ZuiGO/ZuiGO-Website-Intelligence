import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.models.accessibility import (
    AccessibilityAudit,
    AccessibilityFinding,
    AccessibilityNode,
    ManualReviewChecklist,
)


def truncate_html(html: str, max_length: int = 500) -> str:
    if not html:
        return ""
    # Redact common secrets/passwords (naive check for security)
    html = re.sub(
        r'(password|secret|token|key)["\']?\s*[:=]\s*["\'][^"\']+["\']',
        r'\1="***"',
        html,
        flags=re.IGNORECASE,
    )
    # Redact values in password inputs
    html = re.sub(
        r'(type=["\']?password["\']?[^>]*value=["\'])([^"\']+)(["\'])',
        r"\g<1>***\g<3>",
        html,
        flags=re.IGNORECASE,
    )
    html = re.sub(
        r'(value=["\'])([^"\']+)(["\'][^>]*type=["\']?password["\']?)',
        r"\g<1>***\g<3>",
        html,
        flags=re.IGNORECASE,
    )
    if len(html) > max_length:
        return html[:max_length] + "..."
    return html


def create_fingerprint(rule_id: str, target_selector: str, failure_summary: str) -> str:
    fingerprint_raw = f"{rule_id}:{target_selector}:{failure_summary}"
    return hashlib.sha256(fingerprint_raw.encode("utf-8")).hexdigest()


def normalize_impact(impact: str) -> str:
    impact = (impact or "unknown").lower()
    if impact in {"critical", "serious", "moderate", "minor"}:
        return impact
    return "unknown"


def process_axe_results(
    session: Session,
    execution_id: uuid.UUID,
    website_id: uuid.UUID,
    normalized_url: str,
    axe_data: dict[str, Any],
    analysis_run_id: uuid.UUID | None = None,
    page_id: uuid.UUID | None = None,
    profile_id: str | None = None,
    profile_version: str | None = None,
    requested_wcag_level: str | None = None,
) -> None:
    # idempotent check
    existing_audit = session.execute(
        select(AccessibilityAudit).where(
            AccessibilityAudit.execution_id == execution_id,
            AccessibilityAudit.website_id == website_id,
            AccessibilityAudit.normalized_url == normalized_url,
            AccessibilityAudit.provider == "axe-core",
        )
    ).scalar_one_or_none()

    if existing_audit:
        # Idempotent: safely return existing audit instead of rewriting history
        return

    now = datetime.now(UTC)
    audit_id = uuid.uuid4()

    status = "completed" if axe_data else "failed"
    failure_reason = None if axe_data else "Axe-core execution failed or was unavailable"

    violation_count = len(axe_data.get("violations", [])) if axe_data else None
    incomplete_count = len(axe_data.get("incomplete", [])) if axe_data else None
    pass_count = len(axe_data.get("passes", [])) if axe_data else None
    inapplicable_count = len(axe_data.get("inapplicable", [])) if axe_data else None

    session.execute(
        insert(AccessibilityAudit).values(
            id=audit_id,
            execution_id=execution_id,
            website_id=website_id,
            analysis_run_id=analysis_run_id,
            page_id=page_id,
            normalized_url=normalized_url,
            provider="axe-core",
            provider_version=axe_data.get("testEngine", {}).get("version", "unknown")
            if axe_data
            else "unknown",
            ruleset_version=None,
            profile_id=profile_id,
            profile_version=profile_version,
            requested_wcag_level=requested_wcag_level,
            status=status,
            failure_reason=failure_reason,
            violation_count=violation_count,
            incomplete_count=incomplete_count,
            pass_count=pass_count,
            inapplicable_count=inapplicable_count,
            started_at=now,
            completed_at=now,
            created_at=now,
        )
    )

    if not axe_data:
        session.commit()
        return

    findings_to_insert = []
    nodes_to_insert = []
    checklists_to_insert = []

    for result_type in ["violations", "incomplete", "passes", "inapplicable"]:
        for item in axe_data.get(result_type, []):
            finding_id = uuid.uuid4()
            wcag_tags = [t for t in item.get("tags", []) if t.startswith("wcag")]
            conformance_level = "unknown"
            if any(t == "wcag2a" or t == "wcag21a" or t == "wcag22a" for t in wcag_tags):
                conformance_level = "A"
            elif any(t == "wcag2aa" or t == "wcag21aa" or t == "wcag22aa" for t in wcag_tags):
                conformance_level = "AA"
            elif any(t == "wcag2aaa" or t == "wcag21aaa" or t == "wcag22aaa" for t in wcag_tags):
                conformance_level = "AAA"
            elif "best-practice" in item.get("tags", []):
                conformance_level = "best_practice"

            findings_to_insert.append(
                {
                    "id": finding_id,
                    "audit_id": audit_id,
                    "provider_rule_id": item.get("id", "unknown"),
                    "act_rule_id": None,
                    "title": item.get("description", "Unknown Rule"),
                    "description": item.get("help", ""),
                    "help_text": item.get("help", ""),
                    "help_url": item.get("helpUrl", ""),
                    "impact": normalize_impact(item.get("impact")),
                    "result_type": {
                        "violations": "violation",
                        "passes": "pass",
                        "incomplete": "incomplete",
                        "inapplicable": "inapplicable",
                    }.get(result_type, "inapplicable"),
                    "wcag_version": "2.2" if any("wcag22" in t for t in wcag_tags) else "2.1",
                    "wcag_criteria": wcag_tags,
                    "conformance_level": conformance_level,
                    "affected_element_count": len(item.get("nodes", [])),
                    "remediation_summary": None,
                    "manual_verification_required": result_type == "incomplete",
                    "source_metadata": {"tags": item.get("tags", [])},
                    "created_at": now,
                }
            )

            if result_type == "incomplete":
                checklists_to_insert.append(
                    {
                        "id": uuid.uuid4(),
                        "audit_id": audit_id,
                        "checklist_id": f"{item.get('id')}-manual-review",
                        "title": f"Manual Review Required: {item.get('description')}",
                        "reason": "Automated tool returned incomplete result",
                        "applicable_wcag_criterion": ", ".join(wcag_tags),
                        "required_evidence": "Manual verification",
                        "suggested_test_procedure": item.get("help", ""),
                        "status": "not_reviewed",
                        "automated_evidence_references": {"rule_id": item.get("id")},
                        "limitation_statement": "Automated tools cannot fully verify this rule.",
                        "created_at": now,
                    }
                )

            for node in item.get("nodes", []):
                target_selector = " ".join(node.get("target", []))
                failure_summary = node.get("failureSummary", "")
                nodes_to_insert.append(
                    {
                        "id": uuid.uuid4(),
                        "finding_id": finding_id,
                        "normalized_selector": target_selector,
                        "html_excerpt": truncate_html(node.get("html", "")),
                        "failure_summary": failure_summary,
                        "related_nodes": node.get("any", [])
                        + node.get("all", [])
                        + node.get("none", []),
                        "frame_context": None,
                        "shadow_dom_context": None,
                        "occurrence_fingerprint": create_fingerprint(
                            item.get("id", "unknown"), target_selector, failure_summary
                        ),
                        "created_at": now,
                    }
                )

    if findings_to_insert:
        session.execute(insert(AccessibilityFinding), findings_to_insert)
    if nodes_to_insert:
        session.execute(insert(AccessibilityNode), nodes_to_insert)
    if checklists_to_insert:
        session.execute(insert(ManualReviewChecklist), checklists_to_insert)

    session.commit()


def process_lighthouse_accessibility(
    session: Session,
    execution_id: uuid.UUID,
    website_id: uuid.UUID,
    normalized_url: str,
    lighthouse_data: dict[str, Any],
    analysis_run_id: uuid.UUID | None = None,
    page_id: uuid.UUID | None = None,
) -> None:
    existing_audit = session.execute(
        select(AccessibilityAudit).where(
            AccessibilityAudit.execution_id == execution_id,
            AccessibilityAudit.website_id == website_id,
            AccessibilityAudit.normalized_url == normalized_url,
            AccessibilityAudit.provider == "Lighthouse",
        )
    ).scalar_one_or_none()

    if existing_audit:
        # Idempotent: safely return existing audit instead of rewriting history
        return

    now = datetime.now(UTC)
    audit_id = uuid.uuid4()

    audits = lighthouse_data.get("audits", {})
    categories = lighthouse_data.get("categories", {})
    accessibility_category = categories.get("accessibility", {})

    status = "completed" if accessibility_category else "failed"
    failure_reason = None if accessibility_category else "Lighthouse accessibility data unavailable"

    violation_count = 0 if accessibility_category else None
    incomplete_count = 0 if accessibility_category else None
    pass_count = 0 if accessibility_category else None
    inapplicable_count = 0 if accessibility_category else None

    findings_to_insert = []

    if accessibility_category:
        for audit_ref in accessibility_category.get("auditRefs", []):
            audit_id_str = audit_ref.get("id")
            audit = audits.get(audit_id_str, {})
            if not audit:
                continue

            score = audit.get("score")
            score_display_mode = audit.get("scoreDisplayMode")
            result_type = "unknown"

            if score_display_mode == "notApplicable":
                result_type = "inapplicable"
                inapplicable_count += 1
            elif score_display_mode == "manual":
                result_type = "incomplete"
                incomplete_count += 1
            elif score == 1:
                result_type = "pass"
                pass_count += 1
            elif score == 0:
                result_type = "violation"
                violation_count += 1

            findings_to_insert.append(
                {
                    "id": uuid.uuid4(),
                    "audit_id": audit_id,
                    "provider_rule_id": audit_id_str,
                    "act_rule_id": None,
                    "title": audit.get("title", ""),
                    "description": audit.get("description", ""),
                    "help_text": audit.get("description", ""),
                    "help_url": None,
                    "impact": "unknown",
                    "result_type": result_type,
                    "wcag_version": None,
                    "wcag_criteria": None,
                    "conformance_level": "unknown",
                    "affected_element_count": 0,
                    "remediation_summary": None,
                    "manual_verification_required": result_type == "incomplete",
                    "source_metadata": {"score": score, "displayMode": score_display_mode},
                    "created_at": now,
                }
            )

    session.execute(
        insert(AccessibilityAudit).values(
            id=audit_id,
            execution_id=execution_id,
            website_id=website_id,
            analysis_run_id=analysis_run_id,
            page_id=page_id,
            normalized_url=normalized_url,
            provider="Lighthouse",
            provider_version=lighthouse_data.get("lighthouseVersion", "unknown"),
            ruleset_version=None,
            profile_id=None,
            profile_version=None,
            requested_wcag_level=None,
            status=status,
            failure_reason=failure_reason,
            violation_count=violation_count,
            incomplete_count=incomplete_count,
            pass_count=pass_count,
            inapplicable_count=inapplicable_count,
            started_at=now,
            completed_at=now,
            created_at=now,
        )
    )

    if findings_to_insert:
        session.execute(insert(AccessibilityFinding), findings_to_insert)

    session.commit()

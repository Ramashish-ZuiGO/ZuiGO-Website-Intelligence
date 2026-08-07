# ruff: noqa: E501

import hashlib
import html
import io
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AnalysisComparison,
    AnalysisComparisonArtifact,
    AnalysisRun,
    ReportExecution,
)

COMPARISON_VERSION = "1.0.0"
SEVERITY_RANK = {
    "critical": 5,
    "high": 4,
    "medium": 3,
    "low": 2,
    "informational": 1,
    "info": 1,
}
ENGINE_IDS = ("chromium", "firefox", "webkit")
SCORE_CATEGORY_IDS = (
    "performance",
    "accessibility",
    "best_practices",
    "seo",
    "technical_quality",
)
ARTIFACT_MEDIA_TYPES = {
    "html": "text/html; charset=utf-8",
    "pdf": "application/pdf",
    "json": "application/json",
}


class AnalysisComparisonError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status_code = status_code


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def normalize_comparison_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return text.casefold()
    if not parsed.scheme or not parsed.hostname:
        return text.casefold().rstrip("/")
    scheme = parsed.scheme.casefold()
    hostname = parsed.hostname.casefold().rstrip(".")
    port = parsed.port
    netloc = hostname
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{hostname}:{port}"
    path = re.sub(r"/+", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit((scheme, netloc, path, query, ""))


def _section(snapshot: dict[str, Any], key: str) -> dict[str, Any]:
    for section in snapshot.get("sections", []):
        if isinstance(section, dict) and section.get("section_key") == key:
            return section
    return {}


def _content(snapshot: dict[str, Any], key: str) -> dict[str, Any]:
    content = _section(snapshot, key).get("content", {})
    return content if isinstance(content, dict) else {}


def _latest_report(db: Session, run_id: uuid.UUID) -> ReportExecution:
    report = db.scalar(
        select(ReportExecution)
        .options(
            selectinload(ReportExecution.snapshot),
            selectinload(ReportExecution.artifacts),
        )
        .where(
            ReportExecution.analysis_run_id == run_id,
            ReportExecution.status.in_(("completed", "partial")),
        )
        .order_by(ReportExecution.created_at.desc(), ReportExecution.id.desc())
    )
    if report is None or report.snapshot is None:
        raise AnalysisComparisonError(
            "COMPARISON_EVIDENCE_UNAVAILABLE",
            "Both analyses need completed evidence-backed reports before comparison.",
            409,
        )
    return report


def _successful_urls(snapshot: dict[str, Any]) -> set[str]:
    statuses = {"completed", "passed", "available"}
    return {
        normalize_comparison_url(item.get("url"))
        for item in snapshot.get("page_inventory", [])
        if isinstance(item, dict)
        and str(item.get("analysis_status", "")).casefold() in statuses
        and normalize_comparison_url(item.get("url"))
    }


def _finding_urls(finding: dict[str, Any]) -> list[str]:
    values = []
    occurrences = finding.get("exact_occurrences") or finding.get("affected_pages") or []
    for occurrence in occurrences:
        if not isinstance(occurrence, dict):
            continue
        normalized = normalize_comparison_url(occurrence.get("normalized_url"))
        if normalized:
            values.append(normalized)
    return sorted(set(values))


def _finding_key(finding: dict[str, Any]) -> str:
    occurrences = [
        item
        for item in (finding.get("exact_occurrences") or finding.get("affected_pages") or [])
        if isinstance(item, dict)
    ]
    selectors = sorted(
        {
            _normalize_text(item.get("selector") or item.get("location"))
            for item in occurrences
            if item.get("selector") or item.get("location")
        }
    )
    observed = (
        []
        if selectors
        else sorted(
            {
                _normalize_text(item.get("observed_value"))[:160]
                for item in occurrences
                if item.get("observed_value")
            }
        )
    )
    browsers = sorted(
        {
            _normalize_text(engine)
            for engine in (
                finding.get("affected_browser_engines")
                or finding.get("browser_engines_affected")
                or []
            )
        }
    )
    identity = {
        "rule": _normalize_text(finding.get("finding_code") or finding.get("issue_title")),
        "category": _normalize_text(finding.get("category")),
        "scope": _normalize_text(finding.get("scope")),
        "selectors": selectors,
        "observed_signature": observed,
        "browsers": browsers,
    }
    return _fingerprint(identity)


def _findings(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = _content(snapshot, "page_level_findings").get("findings", [])
    grouped: dict[str, dict[str, Any]] = {}
    for finding in values if isinstance(values, list) else []:
        if not isinstance(finding, dict):
            continue
        key = _finding_key(finding)
        if key not in grouped:
            grouped[key] = finding
            continue
        existing = grouped[key]
        merged = sorted(set(_finding_urls(existing)) | set(_finding_urls(finding)))
        existing = dict(existing)
        existing["exact_occurrences"] = [{"normalized_url": url} for url in merged]
        existing["affected_page_count"] = len(merged)
        grouped[key] = existing
    return grouped


def _finding_summary(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    *,
    classification: str,
    change: str,
    limitation: str | None,
) -> dict[str, Any]:
    source = after or before or {}
    before_urls = _finding_urls(before or {})
    after_urls = _finding_urls(after or {})
    before_severity = str((before or {}).get("severity") or "Unavailable")
    after_severity = str((after or {}).get("severity") or "Unavailable")
    return {
        "title": str(source.get("issue_title") or "Retained evidence finding"),
        "category": str(source.get("category") or "General").replace("_", " "),
        "classification": classification,
        "severity_before": before_severity,
        "severity_after": after_severity,
        "affected_page_count_before": len(before_urls),
        "affected_page_count_after": len(after_urls),
        "affected_urls_before": before_urls,
        "affected_urls_after": after_urls,
        "affected_urls": sorted(set(before_urls) | set(after_urls)),
        "browser": (
            source.get("affected_browser_engines") or source.get("browser_engines_affected") or []
        ),
        "observed_change": change,
        "recommended_next_action": str(
            source.get("recommended_remediation")
            or "Review the retained evidence and verify the affected pages."
        ),
        "evidence_limitation": limitation or str(source.get("evidence_limitations") or ""),
    }


def _compare_findings(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    before = _findings(baseline)
    after = _findings(current)
    before_success = _successful_urls(baseline)
    after_success = _successful_urls(current)
    current_browser_pairs = _browser_pairs(current)
    coverage_not_decreased = len(after_success) >= len(before_success)
    result = {
        "resolved": [],
        "persistent": [],
        "new": [],
        "regressions": [],
        "changed_severity": [],
        "inconclusive": [],
    }
    for key in sorted(set(before) | set(after)):
        old = before.get(key)
        new = after.get(key)
        if old is not None and new is not None:
            old_rank = SEVERITY_RANK.get(str(old.get("severity", "")).casefold(), 0)
            new_rank = SEVERITY_RANK.get(str(new.get("severity", "")).casefold(), 0)
            direction = (
                "Regressed"
                if new_rank > old_rank
                else "Improved"
                if new_rank < old_rank
                else "Unchanged"
            )
            summary = _finding_summary(
                old,
                new,
                classification="Persistent",
                change=(
                    f"Severity changed from {old.get('severity')} to {new.get('severity')}."
                    if old_rank != new_rank
                    else "The evidence-grounded issue remains present."
                ),
                limitation=None,
            )
            summary["direction"] = direction
            result["persistent"].append(summary)
            if old_rank != new_rank:
                result["changed_severity"].append(summary)
            if direction == "Regressed":
                result["regressions"].append(summary)
            continue
        if old is not None:
            urls = set(_finding_urls(old))
            affected_engines = {
                _normalize_text(engine)
                for engine in (
                    old.get("affected_browser_engines") or old.get("browser_engines_affected") or []
                )
            }
            browser_comparable = not affected_engines or all(
                (url, engine) in current_browser_pairs
                for url in urls
                for engine in affected_engines
            )
            comparable = (
                bool(urls)
                and urls <= after_success
                and coverage_not_decreased
                and browser_comparable
            )
            bucket = "resolved" if comparable else "inconclusive"
            result[bucket].append(
                _finding_summary(
                    old,
                    None,
                    classification="Resolved" if comparable else "Inconclusive",
                    change=(
                        "The issue was absent when every previously affected page was re-analysed."
                        if comparable
                        else (
                            "The issue was absent, but page or browser coverage "
                            "was not comparable to the baseline."
                        )
                    ),
                    limitation=(
                        None
                        if comparable
                        else (
                            "Absence is not treated as resolution because current "
                            "page or browser evidence is incomplete or coverage decreased."
                        )
                    ),
                )
            )
            continue
        assert new is not None
        urls = set(_finding_urls(new))
        comparable = bool(urls) and urls <= before_success
        bucket = "new" if comparable else "inconclusive"
        summary = _finding_summary(
            None,
            new,
            classification="New" if comparable else "Inconclusive",
            change=(
                "The issue appears in current evidence for pages that were also "
                "analysed at baseline."
                if comparable
                else (
                    "The issue appears only in current evidence, but baseline page "
                    "coverage was not comparable."
                )
            ),
            limitation=(
                None
                if comparable
                else (
                    "The issue cannot be called new without baseline evidence for "
                    "every affected page."
                )
            ),
        )
        result[bucket].append(summary)
        if comparable:
            result["regressions"].append(summary)
    for values in result.values():
        values.sort(key=lambda item: (item["category"], item["title"], item["affected_urls"]))
    return result


def _direction(before: Any, after: Any, *, higher_is_better: bool = True) -> str:
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return "Not comparable"
    if before == after:
        return "Unchanged"
    improved = after > before if higher_is_better else after < before
    return "Improved" if improved else "Regressed"


def _scores(snapshot: dict[str, Any]) -> dict[str, Any]:
    content = _content(snapshot, "scores")
    categories = {
        str(item.get("category_id")): {
            "score": item.get("score"),
            "band": item.get("band"),
            "included": bool(item.get("included")),
        }
        for item in content.get("categories", [])
        if isinstance(item, dict) and item.get("category_id")
    }
    return {
        "overall": content.get("overall_score", snapshot.get("overall_score")),
        "confidence": content.get(
            "confidence_percent",
            snapshot.get("confidence_percent"),
        ),
        "formula_version": content.get("formula_version"),
        "categories": categories,
    }


def _compare_scores(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    before = _scores(baseline)
    after = _scores(current)
    limitations: list[str] = []
    same_formula = bool(before["formula_version"]) and (
        before["formula_version"] == after["formula_version"]
    )
    if not same_formula:
        limitations.append(
            "Score deltas are not comparable because the retained formula versions differ."
        )
    overall_before = before["overall"]
    overall_after = after["overall"]
    overall_delta = (
        round(float(overall_after) - float(overall_before), 2)
        if same_formula
        and isinstance(overall_before, (int, float))
        and isinstance(overall_after, (int, float))
        else None
    )
    categories = []
    for category_id in SCORE_CATEGORY_IDS:
        old = before["categories"].get(category_id, {})
        new = after["categories"].get(category_id, {})
        old_score = old.get("score")
        new_score = new.get("score")
        comparable = same_formula and old.get("included") and new.get("included")
        delta = (
            round(float(new_score) - float(old_score), 2)
            if comparable
            and isinstance(old_score, (int, float))
            and isinstance(new_score, (int, float))
            else None
        )
        categories.append(
            {
                "category": category_id.replace("_", " "),
                "score_before": old_score,
                "score_after": new_score,
                "delta": delta,
                "direction": (_direction(old_score, new_score) if comparable else "Not comparable"),
                "status_before": old.get("band"),
                "status_after": new.get("band"),
            }
        )
    return (
        {
            "overall_score_before": overall_before,
            "overall_score_after": overall_after,
            "overall_delta": overall_delta,
            "confidence_before": before["confidence"],
            "confidence_after": after["confidence"],
            "direction": (
                _direction(overall_before, overall_after) if same_formula else "Not comparable"
            ),
            "formula_version_before": before["formula_version"],
            "formula_version_after": after["formula_version"],
            "categories": categories,
        },
        limitations,
    )


def _coverage(snapshot: dict[str, Any]) -> dict[str, Any]:
    value = snapshot.get("page_coverage", {})
    return value if isinstance(value, dict) else {}


def _compare_coverage(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    before = _coverage(baseline)
    after = _coverage(current)
    keys = {
        "discovered": "total_urls_discovered",
        "scheduled": "total_pages_scheduled",
        "visited": "total_pages_visited",
        "successfully_analysed": "successfully_analysed_pages",
        "coverage_percentage": "coverage_percentage",
    }
    counts = {}
    for label, key in keys.items():
        old = before.get(key)
        new = after.get(key)
        counts[label] = {
            "before": old,
            "after": new,
            "delta": (
                round(float(new) - float(old), 2)
                if isinstance(old, (int, float)) and isinstance(new, (int, float))
                else None
            ),
        }
    before_urls = _successful_urls(baseline)
    after_urls = _successful_urls(current)
    comparable = before_urls == after_urls and bool(before_urls)
    return {
        **counts,
        "comparable": comparable,
        "direction": (
            _direction(
                before.get("coverage_percentage"),
                after.get("coverage_percentage"),
            )
            if comparable
            else "Inconclusive"
        ),
        "missing_current_urls": sorted(before_urls - after_urls),
        "newly_analysed_urls": sorted(after_urls - before_urls),
        "limitation": (
            None
            if comparable
            else (
                "Page sets differ, so absence of a finding is not automatically "
                "treated as resolution."
            )
        ),
    }


def _browser_pairs(snapshot: dict[str, Any]) -> dict[tuple[str, str], str]:
    browser = snapshot.get("browser_compatibility", {})
    matrix = browser.get("matrix", []) if isinstance(browser, dict) else []
    pairs: dict[tuple[str, str], str] = {}
    for row in matrix if isinstance(matrix, list) else []:
        if not isinstance(row, dict):
            continue
        url = normalize_comparison_url(row.get("page_url"))
        engines = row.get("engines", {})
        if not url or not isinstance(engines, dict):
            continue
        for engine, state in engines.items():
            if engine in ENGINE_IDS and state not in {"not_tested", "unavailable"}:
                pairs[(url, engine)] = str(state)
    return pairs


def _engine_summary(snapshot: dict[str, Any], engine: str) -> dict[str, int]:
    browser = snapshot.get("browser_compatibility", {})
    matrix = browser.get("matrix", []) if isinstance(browser, dict) else []
    states = [
        str(row.get("engines", {}).get(engine))
        for row in matrix
        if isinstance(row, dict)
        and isinstance(row.get("engines"), dict)
        and row["engines"].get(engine)
    ]
    return {
        "tested": sum(state not in {"not_tested", "unavailable"} for state in states),
        "passed": states.count("compatible"),
        "partial": states.count("partial"),
        "failed": states.count("incompatible"),
        "unavailable": states.count("unavailable"),
        "inconclusive": states.count("inconclusive"),
    }


def _compare_browser(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    before_pairs = _browser_pairs(baseline)
    after_pairs = _browser_pairs(current)
    engines = []
    for engine in ENGINE_IDS:
        old = _engine_summary(baseline, engine)
        new = _engine_summary(current, engine)
        common = sorted(
            url
            for url, pair_engine in set(before_pairs) & set(after_pairs)
            if pair_engine == engine
        )
        missing = sorted(
            url
            for url, pair_engine in set(before_pairs) - set(after_pairs)
            if pair_engine == engine
        )
        new_failures = [
            url
            for url in common
            if after_pairs[(url, engine)] == "incompatible"
            and before_pairs[(url, engine)] != "incompatible"
        ]
        resolved_failures = [
            url
            for url in common
            if before_pairs[(url, engine)] == "incompatible"
            and after_pairs[(url, engine)] != "incompatible"
        ]
        coverage_decreased = new["tested"] < old["tested"] or bool(missing)
        direction = (
            "Inconclusive"
            if coverage_decreased
            else "Regressed"
            if new_failures
            else "Improved"
            if resolved_failures
            else "Unchanged"
            if common
            else "Not comparable"
        )
        engines.append(
            {
                "engine": engine,
                "before": old,
                "after": new,
                "direction": direction,
                "comparable_page_count": len(common),
                "new_failures": new_failures,
                "resolved_failures": resolved_failures,
                "untested_combinations": missing,
                "limitation": (
                    "A positive compatibility delta is withheld because test coverage decreased."
                    if coverage_decreased
                    else None
                ),
            }
        )
    return {"engines": engines}


def _actions(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = _content(snapshot, "priority_action_plan").get("actions", [])
    result = {}
    for action in values if isinstance(values, list) else []:
        if not isinstance(action, dict):
            continue
        scope = action.get("affected_scope", {})
        key = _fingerprint(
            {
                "title": _normalize_text(action.get("title")),
                "url": normalize_comparison_url(
                    scope.get("final_url") or scope.get("requested_url")
                    if isinstance(scope, dict)
                    else ""
                ),
            }
        )
        result[key] = action
    return result


def _compare_actions(
    baseline: dict[str, Any],
    current: dict[str, Any],
    findings: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    before = _actions(baseline)
    after = _actions(current)
    resolved_titles = {_normalize_text(item["title"]) for item in findings["resolved"]}
    improved_titles = {
        _normalize_text(item["title"])
        for item in findings["persistent"]
        if item.get("direction") == "Improved"
    }
    output = []
    for key in sorted(set(before) | set(after)):
        old = before.get(key)
        new = after.get(key)
        source = new or old or {}
        title_key = _normalize_text(source.get("title"))
        if old and new:
            classification = (
                "Partially improved" if title_key in improved_titles else "Still required"
            )
            evidence = (
                "Current evidence shows reduced severity, but the issue remains."
                if classification == "Partially improved"
                else "The related evidence-grounded issue remains in the current analysis."
            )
        elif old:
            supported = title_key in resolved_titles
            classification = (
                "Completed or likely resolved through evidence" if supported else "Unable to verify"
            )
            evidence = (
                "Every affected page was re-analysed and the related finding is absent."
                if supported
                else "The action is absent, but retained evidence does not prove completion."
            )
        else:
            classification = "New action"
            evidence = "Current evidence introduced this recommendation."
        output.append(
            {
                "title": str(source.get("title") or "Recommended action"),
                "classification": classification,
                "priority_before": old.get("priority_score") if old else None,
                "priority_after": new.get("priority_score") if new else None,
                "status_before": old.get("status") if old else None,
                "status_after": new.get("status") if new else None,
                "supporting_evidence": evidence,
                "verification_method": str(
                    source.get("verification_method")
                    or "Repeat the relevant analysis and inspect retained evidence."
                ),
            }
        )
    return output


def build_comparison_payload(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    scores, limitations = _compare_scores(baseline, current)
    coverage = _compare_coverage(baseline, current)
    findings = _compare_findings(baseline, current)
    browser = _compare_browser(baseline, current)
    actions = _compare_actions(baseline, current, findings)
    if coverage["limitation"]:
        limitations.append(coverage["limitation"])
    limitations.extend(
        engine["limitation"] for engine in browser["engines"] if engine["limitation"]
    )
    limitations.extend(
        [
            "Only persisted evidence from the selected analyses is compared.",
            "Unavailable evidence is not interpreted as improvement or resolution.",
            "Browser results apply only to page and engine combinations tested in both runs.",
            "Action completion requires supporting analysis evidence, not only a manual status.",
        ]
    )
    limitations = list(dict.fromkeys(limitations))
    baseline_date = _coverage(baseline).get("completed_at") or baseline.get("generated_at")
    current_date = _coverage(current).get("completed_at") or current.get("generated_at")
    payload = {
        "schema_version": COMPARISON_VERSION,
        "website": {
            "name": current.get("website_name") or baseline.get("website_name") or "Website",
            "url": current.get("website_url") or baseline.get("website_url"),
        },
        "baseline": {"analysis_date": baseline_date, "status": baseline.get("status")},
        "current": {"analysis_date": current_date, "status": current.get("status")},
        "summary": {
            "direction": scores["direction"],
            "resolved_count": len(findings["resolved"]),
            "persistent_count": len(findings["persistent"]),
            "new_count": len(findings["new"]),
            "regression_count": len(findings["regressions"]),
            "inconclusive_count": len(findings["inconclusive"]),
        },
        "scores": scores,
        "coverage": coverage,
        "browser_compatibility": browser,
        "findings": findings,
        "action_plan": actions,
        "limitations": limitations,
    }
    return payload, limitations


def _html_document(payload: dict[str, Any]) -> bytes:
    def finding_list(title: str, values: list[dict[str, Any]]) -> str:
        rows = "".join(
            "<li><strong>"
            + html.escape(item["title"])
            + "</strong> — "
            + html.escape(item["classification"])
            + "<br><span>"
            + html.escape(item["observed_change"])
            + "</span><details><summary>All affected URLs</summary><ul>"
            + "".join(f"<li>{html.escape(url)}</li>" for url in item["affected_urls"])
            + "</ul></details></li>"
            for item in values
        )
        return f"<section><h2>{html.escape(title)}</h2><ul>{rows or '<li>None retained.</li>'}</ul></section>"

    score_rows = "".join(
        "<tr><th scope='row'>"
        + html.escape(item["category"].title())
        + "</th><td>"
        + html.escape(str(item["score_before"]))
        + "</td><td>"
        + html.escape(str(item["score_after"]))
        + "</td><td>"
        + html.escape(str(item["delta"]))
        + "</td><td>"
        + html.escape(item["direction"])
        + "</td></tr>"
        for item in payload["scores"]["categories"]
    )
    browser_rows = "".join(
        "<tr><th scope='row'>"
        + html.escape(item["engine"].title())
        + "</th><td>"
        + str(item["before"]["tested"])
        + "</td><td>"
        + str(item["after"]["tested"])
        + "</td><td>"
        + html.escape(item["direction"])
        + "</td></tr>"
        for item in payload["browser_compatibility"]["engines"]
    )
    actions = "".join(
        f"<li><strong>{html.escape(item['title'])}</strong> — "
        f"{html.escape(item['classification'])}<br>{html.escape(item['supporting_evidence'])}</li>"
        for item in payload["action_plan"]
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{html.escape(payload["website"]["name"])} before and after comparison</title>
<style>body{{font-family:Arial,sans-serif;line-height:1.5;max-width:1100px;margin:auto;padding:2rem;color:#172033}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #cbd5e1;padding:.55rem;text-align:left}}
a:focus,summary:focus{{outline:3px solid #c2410c;outline-offset:3px}}section{{margin:2rem 0}}</style></head>
<body><header><h1>{html.escape(payload["website"]["name"])} before and after</h1>
<p>{html.escape(str(payload["website"]["url"] or ""))}</p>
<p>Baseline {html.escape(str(payload["baseline"]["analysis_date"]))}; current {html.escape(str(payload["current"]["analysis_date"]))}.</p></header>
<main><section><h2>Overall improvement summary</h2><p>{html.escape(payload["summary"]["direction"])}</p>
<p>Score {payload["scores"]["overall_score_before"]}/100 to {payload["scores"]["overall_score_after"]}/100
({payload["scores"]["overall_delta"]}). Formula {html.escape(str(payload["scores"]["formula_version_after"]))}.</p></section>
<section><h2>Category scores</h2><table><thead><tr><th>Category</th><th>Before</th><th>After</th><th>Delta</th><th>Direction</th></tr></thead><tbody>{score_rows}</tbody></table></section>
<section><h2>Coverage comparison</h2><p>{html.escape(payload["coverage"]["direction"])}</p>
<p>Successfully analysed: {payload["coverage"]["successfully_analysed"]["before"]} before; {payload["coverage"]["successfully_analysed"]["after"]} after.</p></section>
<section><h2>Browser compatibility</h2><table><thead><tr><th>Engine</th><th>Tested before</th><th>Tested after</th><th>Direction</th></tr></thead><tbody>{browser_rows}</tbody></table></section>
{finding_list("Resolved findings", payload["findings"]["resolved"])}
{finding_list("Persistent findings", payload["findings"]["persistent"])}
{finding_list("New findings and regressions", [*payload["findings"]["new"], *payload["findings"]["regressions"]])}
<section><h2>Action Plan progress</h2><ul>{actions or "<li>No comparable actions.</li>"}</ul></section>
<section><h2>Evidence limitations</h2><ul>{"".join(f"<li>{html.escape(item)}</li>" for item in payload["limitations"])}</ul></section>
</main></body></html>"""
    return document.encode("utf-8")


def _pdf_document(payload: dict[str, Any]) -> bytes:
    output = io.BytesIO()
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "ComparisonTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        textColor=colors.HexColor("#172033"),
        fontSize=24,
        leading=29,
    )
    body = styles["BodyText"]
    heading = styles["Heading1"]
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"{payload['website']['name']} before and after comparison",
        author="ZuiGO Website Intelligence",
        subject="Evidence-grounded website analysis comparison",
    )
    story: list[Any] = [
        Spacer(1, 35 * mm),
        Paragraph("Before and After Website Analysis", title),
        Spacer(1, 10 * mm),
        Paragraph(html.escape(payload["website"]["name"]), styles["Heading2"]),
        Paragraph(html.escape(str(payload["website"]["url"] or "")), body),
        Spacer(1, 10 * mm),
        Paragraph(
            f"Baseline: {html.escape(str(payload['baseline']['analysis_date']))}<br/>"
            f"Current: {html.escape(str(payload['current']['analysis_date']))}",
            body,
        ),
    ]

    def new_page(name: str) -> None:
        story.extend([PageBreak(), Paragraph(name, heading), Spacer(1, 5 * mm)])

    new_page("1. Overall improvement summary")
    story.append(
        Paragraph(
            f"Direction: <b>{payload['summary']['direction']}</b><br/>"
            f"Overall score: {payload['scores']['overall_score_before']}/100 to "
            f"{payload['scores']['overall_score_after']}/100; "
            f"delta {payload['scores']['overall_delta']}.",
            body,
        )
    )
    new_page("2. Category score comparison")
    score_data = [["Category", "Before", "After", "Delta", "Direction"]] + [
        [
            item["category"].title(),
            item["score_before"],
            item["score_after"],
            item["delta"],
            item["direction"],
        ]
        for item in payload["scores"]["categories"]
    ]
    score_table = Table(
        score_data, repeatRows=1, colWidths=[50 * mm, 24 * mm, 24 * mm, 22 * mm, 35 * mm]
    )
    score_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#172033")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#94a3b8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(score_table)
    new_page("3. Page coverage")
    for key in (
        "discovered",
        "scheduled",
        "visited",
        "successfully_analysed",
        "coverage_percentage",
    ):
        item = payload["coverage"][key]
        story.append(
            Paragraph(
                f"<b>{key.replace('_', ' ').title()}:</b> {item['before']} before; "
                f"{item['after']} after; delta {item['delta']}.",
                body,
            )
        )
    story.append(Paragraph(html.escape(str(payload["coverage"]["limitation"] or "")), body))
    new_page("4. Browser compatibility")
    for engine in payload["browser_compatibility"]["engines"]:
        story.append(
            Paragraph(
                f"<b>{engine['engine'].title()}:</b> {engine['before']['tested']} tested before; "
                f"{engine['after']['tested']} after. {engine['direction']}.",
                body,
            )
        )
    new_page("5. Resolved findings")
    for item in payload["findings"]["resolved"][:20]:
        story.append(
            Paragraph(
                f"<b>{html.escape(item['title'])}</b> — {html.escape(item['observed_change'])}",
                body,
            )
        )
    if not payload["findings"]["resolved"]:
        story.append(Paragraph("No finding was safely classified as resolved.", body))
    new_page("6. Persistent, new, and regressed findings")
    combined = [
        *payload["findings"]["persistent"],
        *payload["findings"]["new"],
        *payload["findings"]["regressions"],
    ]
    for item in combined[:25]:
        story.append(
            Paragraph(
                f"<b>{html.escape(item['title'])}</b> — "
                f"{html.escape(item['classification'])}: {html.escape(item['observed_change'])}",
                body,
            )
        )
    if not combined:
        story.append(Paragraph("No comparable retained findings.", body))
    new_page("7. Action Plan progress")
    for item in payload["action_plan"][:20]:
        story.append(
            Paragraph(
                f"<b>{html.escape(item['title'])}</b> — "
                f"{html.escape(item['classification'])}. "
                f"{html.escape(item['supporting_evidence'])}",
                body,
            )
        )
    new_page("8. Evidence limitations")
    for item in payload["limitations"]:
        story.append(Paragraph(f"• {html.escape(item)}", body))
    document.build(story)
    return output.getvalue()


def _artifact_content(artifact_format: str, payload: dict[str, Any]) -> bytes:
    if artifact_format == "json":
        return json.dumps(payload, sort_keys=True, indent=2).encode("utf-8")
    if artifact_format == "html":
        return _html_document(payload)
    if artifact_format == "pdf":
        return _pdf_document(payload)
    raise ValueError(f"Unsupported comparison artifact format: {artifact_format}")


def generate_comparison(
    db: Session,
    current_run_id: uuid.UUID,
    baseline_run_id: uuid.UUID,
    *,
    idempotency_key: str,
) -> tuple[AnalysisComparison, bool]:
    if current_run_id == baseline_run_id:
        raise AnalysisComparisonError(
            "INVALID_COMPARISON_PAIR",
            "Select two different analysis runs.",
            422,
        )
    current_run = db.get(AnalysisRun, current_run_id)
    baseline_run = db.get(AnalysisRun, baseline_run_id)
    if current_run is None or baseline_run is None:
        raise AnalysisComparisonError(
            "ANALYSIS_RUN_NOT_FOUND",
            "One of the selected analysis runs was not found.",
            404,
        )
    if current_run.website_id != baseline_run.website_id:
        raise AnalysisComparisonError(
            "COMPARISON_SCOPE_MISMATCH",
            "Only analyses of the same website can be compared.",
            422,
        )
    if current_run.status != "completed" or baseline_run.status != "completed":
        raise AnalysisComparisonError(
            "COMPARISON_ANALYSIS_INCOMPLETE",
            "Both analysis runs must be completed before comparison.",
            409,
        )
    normalized_key = idempotency_key.strip()
    if not normalized_key:
        raise AnalysisComparisonError(
            "INVALID_IDEMPOTENCY_KEY", "Idempotency key is required.", 422
        )
    input_fingerprint = _fingerprint(
        {
            "comparison_version": COMPARISON_VERSION,
            "baseline_analysis_run_id": str(baseline_run.id),
            "current_analysis_run_id": str(current_run.id),
        }
    )
    existing = db.scalar(
        select(AnalysisComparison)
        .options(selectinload(AnalysisComparison.artifacts))
        .where(
            AnalysisComparison.baseline_analysis_run_id == baseline_run.id,
            AnalysisComparison.current_analysis_run_id == current_run.id,
            AnalysisComparison.idempotency_key == normalized_key,
        )
    )
    if existing is not None:
        if existing.input_fingerprint != input_fingerprint:
            raise AnalysisComparisonError(
                "COMPARISON_IDEMPOTENCY_CONFLICT",
                "The idempotency key belongs to different comparison input.",
                409,
            )
        return existing, False
    baseline_report = _latest_report(db, baseline_run.id)
    current_report = _latest_report(db, current_run.id)
    baseline_snapshot = baseline_report.snapshot.snapshot_payload
    current_snapshot = current_report.snapshot.snapshot_payload
    payload, limitations = build_comparison_payload(baseline_snapshot, current_snapshot)
    comparison_id = uuid.uuid4()
    status = (
        "partial"
        if (
            payload["scores"]["direction"] == "Not comparable"
            or not payload["coverage"]["comparable"]
            or any(
                engine["direction"] in {"Inconclusive", "Not comparable"}
                for engine in payload["browser_compatibility"]["engines"]
            )
        )
        else "completed"
    )
    comparison = AnalysisComparison(
        comparison_id=comparison_id,
        project_id=current_report.project_id,
        website_id=current_run.website_id,
        baseline_analysis_run_id=baseline_run.id,
        current_analysis_run_id=current_run.id,
        comparison_version=COMPARISON_VERSION,
        input_fingerprint=input_fingerprint,
        idempotency_key=normalized_key,
        status=status,
        result_payload=payload,
        limitations=limitations,
        completed_at=datetime.now(UTC),
    )
    db.add(comparison)
    db.flush()
    safe_name = re.sub(r"[^a-z0-9]+", "-", str(payload["website"]["name"]).casefold()).strip("-")
    safe_name = (safe_name or "website")[:60]
    for artifact_format in ("html", "pdf", "json"):
        content = _artifact_content(artifact_format, payload)
        artifact_id = uuid.uuid5(comparison_id, f"comparison:{artifact_format}:1")
        db.add(
            AnalysisComparisonArtifact(
                artifact_id=artifact_id,
                comparison_id=comparison.id,
                format=artifact_format,
                media_type=ARTIFACT_MEDIA_TYPES[artifact_format],
                filename=f"{safe_name}-before-after-{str(comparison_id)[:8]}.{artifact_format}",
                checksum_sha256=hashlib.sha256(content).hexdigest(),
                content=content,
            )
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.scalar(
            select(AnalysisComparison)
            .options(selectinload(AnalysisComparison.artifacts))
            .where(
                AnalysisComparison.baseline_analysis_run_id == baseline_run.id,
                AnalysisComparison.current_analysis_run_id == current_run.id,
                AnalysisComparison.idempotency_key == normalized_key,
            )
        )
        if concurrent is None or concurrent.input_fingerprint != input_fingerprint:
            raise
        return concurrent, False
    return (
        db.scalar(
            select(AnalysisComparison)
            .options(selectinload(AnalysisComparison.artifacts))
            .where(AnalysisComparison.id == comparison.id)
        ),
        True,
    )


def latest_comparison(
    db: Session,
    current_run_id: uuid.UUID,
    baseline_run_id: uuid.UUID,
) -> AnalysisComparison:
    comparison = db.scalar(
        select(AnalysisComparison)
        .options(selectinload(AnalysisComparison.artifacts))
        .where(
            AnalysisComparison.current_analysis_run_id == current_run_id,
            AnalysisComparison.baseline_analysis_run_id == baseline_run_id,
        )
        .order_by(AnalysisComparison.created_at.desc(), AnalysisComparison.id.desc())
    )
    if comparison is None:
        raise AnalysisComparisonError(
            "COMPARISON_NOT_FOUND",
            "No comparison has been generated for the selected analyses.",
            404,
        )
    return comparison


def comparison_artifact(
    db: Session,
    comparison_id: uuid.UUID,
    artifact_format: str,
) -> AnalysisComparisonArtifact:
    artifact = db.scalar(
        select(AnalysisComparisonArtifact).where(
            AnalysisComparisonArtifact.comparison_id
            == select(AnalysisComparison.id)
            .where(AnalysisComparison.comparison_id == comparison_id)
            .scalar_subquery(),
            AnalysisComparisonArtifact.format == artifact_format,
        )
    )
    if artifact is None:
        raise AnalysisComparisonError(
            "COMPARISON_ARTIFACT_NOT_FOUND",
            "The requested comparison export was not found.",
            404,
        )
    return artifact

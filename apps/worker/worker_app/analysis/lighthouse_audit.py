import json
import os
import re
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from worker_app.analysis.errors import AnalysisFailure, FailureDetail


def _failure(code: str, message: str, retryable: bool, detail: str) -> AnalysisFailure:
    return AnalysisFailure(
        FailureDetail(code, message, "running_lighthouse", retryable, internal_detail=detail[:1000])
    )


def _terminate_process_group(process: subprocess.Popen[str], *, force: bool = False) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
    except (AttributeError, OSError):
        process.kill() if force else process.terminate()


def run_lighthouse(url: str, chrome_path: str, timeout_seconds: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="lighthouse-") as temporary_directory:
        output_path = Path(temporary_directory) / "report.json"
        command = [
            "lighthouse",
            url,
            "--quiet",
            "--output=json",
            f"--output-path={output_path}",
            "--port=0",
            "--chrome-flags=--headless --disable-dev-shm-usage --no-sandbox "
            "--disable-crash-reporter --disable-breakpad",
            "--only-categories=performance,accessibility,best-practices,seo",
            "--max-wait-for-load=45000",
        ]
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={**os.environ, "CHROME_PATH": chrome_path, "HOME": temporary_directory},
                start_new_session=True,
            )
        except OSError as exception:
            raise _failure(
                "LIGHTHOUSE_START_FAILED",
                "The Lighthouse audit could not start.",
                True,
                str(exception),
            ) from exception

        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exception:
            _terminate_process_group(process)
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                _terminate_process_group(process, force=True)
                stdout, stderr = process.communicate()
            raise _failure(
                "LIGHTHOUSE_TIMEOUT", "The Lighthouse audit timed out.", True, stderr or stdout
            ) from exception

        if process.returncode != 0:
            detail = f"exit_code={process.returncode} stderr={stderr} stdout={stdout}"
            retryable = any(
                value in detail.lower()
                for value in ("devtools", "connection", "chrome", "econnrefused")
            )
            code = "LIGHTHOUSE_START_FAILED" if retryable else "LIGHTHOUSE_PROCESS_FAILED"
            raise _failure(code, "The Lighthouse audit failed.", retryable, detail)
        try:
            data = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exception:
            raise _failure(
                "LIGHTHOUSE_INVALID_OUTPUT",
                "Lighthouse returned invalid output.",
                False,
                str(exception),
            ) from exception
        if not isinstance(data, dict) or not isinstance(data.get("categories"), dict):
            raise _failure(
                "LIGHTHOUSE_INVALID_OUTPUT",
                "Lighthouse returned invalid output.",
                False,
                "missing categories",
            )
        data["_zuigo_execution"] = {"exit_code": process.returncode}
        return data


def parse_lighthouse(data: dict[str, Any]) -> dict[str, Any]:
    categories = data.get("categories", {})
    audits = data.get("audits", {})

    def score(name: str) -> int | None:
        value = categories.get(name, {}).get("score")
        return round(value * 100) if isinstance(value, (int, float)) else None

    def metric(name: str) -> float | None:
        value = audits.get(name, {}).get("numericValue")
        return float(value) if isinstance(value, (int, float)) else None

    def bounded_items(name: str, keys: tuple[str, ...], limit: int = 10) -> list[dict[str, Any]]:
        details = audits.get(name, {}).get("details", {})
        items = details.get("items", []) if isinstance(details, dict) else []
        return [
            {key: item.get(key) for key in keys if item.get(key) is not None}
            for item in items[:limit]
            if isinstance(item, dict)
        ]

    audit_breakdown: list[dict[str, Any]] = []
    for category_name in ("performance", "accessibility", "best-practices", "seo"):
        category = categories.get(category_name, {})
        for audit_ref in category.get("auditRefs", []) if isinstance(category, dict) else []:
            audit_id = audit_ref.get("id")
            audit = audits.get(audit_id, {})
            audit_score = audit.get("score")
            display_mode = audit.get("scoreDisplayMode")
            manual = display_mode == "manual"
            if not manual and not (isinstance(audit_score, (int, float)) and audit_score < 1):
                continue
            details = audit.get("details", {})
            item_count = (
                len(details.get("items", []))
                if isinstance(details, dict) and isinstance(details.get("items"), list)
                else None
            )
            audit_breakdown.append(
                {
                    "audit_id": str(audit_id)[:120],
                    "title": str(audit.get("title") or audit_id)[:300],
                    "score": audit_score,
                    "display_value": str(audit.get("displayValue") or "")[:300] or None,
                    "explanation": str(audit.get("explanation") or audit.get("description") or "")[
                        :600
                    ]
                    or None,
                    "category": category_name,
                    "evidence_summary": (
                        {"detail_type": details.get("type"), "item_count": item_count}
                        if isinstance(details, dict)
                        else None
                    ),
                    "manual_check": manual,
                }
            )
            if len(audit_breakdown) >= 40:
                break
        if len(audit_breakdown) >= 40:
            break

    config = data.get("configSettings", {})
    environment = data.get("environment", {})
    user_agent = str(environment.get("networkUserAgent") or environment.get("hostUserAgent") or "")
    chromium_match = re.search(r"(?:Chrome|Chromium)/([0-9.]+)", user_agent)
    context = {
        "lighthouse_version": data.get("lighthouseVersion"),
        "chromium_version": chromium_match.group(1) if chromium_match else None,
        "form_factor": config.get("formFactor"),
        "throttling_method": config.get("throttlingMethod"),
        "screen_emulation": config.get("screenEmulation"),
        "audit_timestamp": data.get("fetchTime"),
    }
    lcp_items = bounded_items(
        "largest-contentful-paint-element", ("nodeLabel", "snippet", "selector"), 1
    )
    performance_evidence = {
        "lcp_element": lcp_items[0] if lcp_items else None,
        "render_blocking_resources": bounded_items(
            "render-blocking-resources", ("url", "totalBytes", "wastedMs")
        ),
        "long_tasks": bounded_items("long-tasks", ("url", "duration", "startTime")),
        "main_thread_work": bounded_items(
            "mainthread-work-breakdown", ("group", "groupLabel", "duration")
        ),
        "script_execution": bounded_items(
            "bootup-time", ("url", "total", "scripting", "scriptParseCompile")
        ),
    }

    return {
        "lighthouse_version": data.get("lighthouseVersion"),
        "performance_score": score("performance"),
        "accessibility_score": score("accessibility"),
        "best_practices_score": score("best-practices"),
        "seo_score": score("seo"),
        "first_contentful_paint_ms": metric("first-contentful-paint"),
        "largest_contentful_paint_ms": metric("largest-contentful-paint"),
        "total_blocking_time_ms": metric("total-blocking-time"),
        "cumulative_layout_shift": metric("cumulative-layout-shift"),
        "speed_index_ms": metric("speed-index"),
        "time_to_interactive_ms": metric("interactive"),
        "time_to_interactive_context": {
            "status": "legacy_supplementary",
            "core_web_vital": False,
            "included_in_performance_score": False,
        },
        "lighthouse_context": context,
        "lighthouse_audit_breakdown": audit_breakdown,
        "accessibility_context": {
            "automated_checks_completed": score("accessibility") is not None,
            "score_100_proves_compliance": False,
            "manual_testing_required": True,
        },
        "performance_evidence": performance_evidence,
    }

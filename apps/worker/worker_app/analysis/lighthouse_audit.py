import json
import os
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
    }

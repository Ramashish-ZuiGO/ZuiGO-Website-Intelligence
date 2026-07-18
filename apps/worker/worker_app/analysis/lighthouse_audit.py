import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def run_lighthouse(url: str, chrome_path: str, timeout_seconds: int = 75) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="lighthouse-") as temporary_directory:
        output_path = Path(temporary_directory) / "report.json"
        command = [
            "lighthouse",
            url,
            "--quiet",
            "--output=json",
            f"--output-path={output_path}",
            "--chrome-flags=--headless --disable-dev-shm-usage --no-sandbox "
            "--disable-crash-reporter --disable-breakpad",
            "--only-categories=performance,accessibility,best-practices,seo",
            "--max-wait-for-load=30000",
        ]
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env={
                    **os.environ,
                    "CHROME_PATH": chrome_path,
                    "HOME": temporary_directory,
                },
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exception:
            raise RuntimeError("LIGHTHOUSE_FAILED") from exception
        return json.loads(output_path.read_text(encoding="utf-8"))


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

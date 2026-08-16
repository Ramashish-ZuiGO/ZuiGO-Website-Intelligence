"""One-click Android Tier 0 check.

Combines scripts/browser_uat_tier0_check_android.mjs (drives real Chrome on
a connected Android device via ChromeDriver-over-adb, Node/Selenium) and
ingest_manual_tier0_result() (writes the result into the same
browser_uat_tier0 tables Lane A/B use, Python) into a single command --
matching the "one-click" UX goal discussed for the eventual frontend piece,
even though the underlying work genuinely spans two languages. See
docs/DEVICE_OS_BROWSER_QA_PLAN.md's Lane C entry for why this is a manual,
operator-run tool rather than something dispatched automatically: no free
CI provider offers live adb access to a real Android device.

Prerequisites (one-time, on whichever machine the phone is plugged into):
  - A real Android phone with USB debugging enabled, connected via USB (or
    reached through a Samsung Remote Test Lab Remote Debug Bridge session).
    Confirm it's visible with `adb devices` before running this.
  - `npm install selenium-webdriver@4.47.0` run somewhere Node's module
    resolution can find from scripts/ (typically the repo root).
  - This script must run directly on the host (not inside a Docker
    container: Docker cannot pass USB devices through to adb/ChromeDriver).
    A host process needs a real path to Postgres, which the tracked
    docker-compose.yml deliberately does NOT publish (see
    tests/test_production_network_boundary.py). Create a
    docker-compose.override.yml (gitignored, auto-merged by `docker compose`)
    publishing the postgres port, e.g.:
        services:
          postgres:
            ports:
              - "5432:5432"
    then `docker compose up -d postgres` and run this script with
    POSTGRES_HOST=localhost set.

Usage (run with the same environment/DATABASE_URL as the API):
    PYTHONPATH=apps/api python scripts/run_manual_tier0_android_check.py \\
        --analysis-run-id <uuid>
"""

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.db.session import SessionLocal
from app.models import AnalysisRun, Website
from ingest_manual_tier0_result import ingest_manual_tier0_result

SCRIPT_DIR = Path(__file__).resolve().parent
ANDROID_CHECK_SCRIPT = SCRIPT_DIR / "browser_uat_tier0_check_android.mjs"


def _resolve_target_url(analysis_run_id: uuid.UUID) -> str:
    with SessionLocal() as db:
        analysis_run = db.get(AnalysisRun, analysis_run_id)
        if analysis_run is None:
            raise ValueError(f"Analysis run {analysis_run_id} does not exist.")
        website = db.get(Website, analysis_run.website_id)
        if website is None:
            raise ValueError(f"Website for analysis run {analysis_run_id} is unavailable.")
        return website.url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-run-id", required=True, type=uuid.UUID)
    parser.add_argument(
        "--android-device-serial",
        default=None,
        help="adb device serial, only needed when more than one device is attached "
        "(check with `adb devices`).",
    )
    parser.add_argument(
        "--idempotency-key",
        default=None,
        help="Defaults to a timestamp-based key so repeated runs create independent history.",
    )
    args = parser.parse_args()

    try:
        target_url = _resolve_target_url(args.analysis_run_id)
    except ValueError as exception:
        print(exception, file=sys.stderr)
        return 1

    print(f"Checking {target_url} on the connected Android device...")

    results_path = SCRIPT_DIR / f"tier0-results-android-{args.analysis_run_id}.json"
    env = os.environ.copy()
    env["TARGET_PAGES"] = json.dumps([target_url])
    env["RESULTS_PATH"] = str(results_path)
    if args.android_device_serial:
        env["ANDROID_DEVICE_SERIAL"] = args.android_device_serial

    check_result = subprocess.run(["node", str(ANDROID_CHECK_SCRIPT)], env=env, check=False)
    if check_result.returncode != 0:
        print(
            "Android check failed -- see output above. Nothing was reported to the analysis.",
            file=sys.stderr,
        )
        return check_result.returncode

    job_result = json.loads(results_path.read_text(encoding="utf-8"))
    idempotency_key = args.idempotency_key or f"manual-android-{datetime.now(UTC).isoformat()}"

    execution_id = ingest_manual_tier0_result(
        analysis_run_id=args.analysis_run_id,
        job_result=job_result,
        idempotency_key=idempotency_key,
    )

    print(f"Done. Execution {execution_id} recorded for analysis run {args.analysis_run_id}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Manual companion to Lane A/B's automatic Celery dispatch/poll path.

Lane C (Android, docs/DEVICE_OS_BROWSER_QA_PLAN.md M2 Lane C) has no free CI
provider offering live adb access to a real Android device during an
unattended run, so scripts/browser_uat_tier0_check_android.mjs is run BY A
HUMAN against a device they have adb access to, and its JSON output is fed in
here -- reusing the exact same create_browser_uat_tier0_execution /
ingest_browser_uat_tier0_job_result service functions Lane A/B's Celery tasks
call, so the resulting rows are indistinguishable from an automatic run to
every downstream consumer (M5 evidence mapping, M6 action generation).

Usage (run with the same environment/DATABASE_URL as the API):
    PYTHONPATH=apps/api python scripts/ingest_manual_tier0_result.py \\
        --analysis-run-id <uuid> \\
        --json-file tier0-results-android.json \\
        --idempotency-key manual-android-2026-08-15
"""

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.db.session import SessionLocal
from app.models import AnalysisRun, BrowserUatTier0Execution, BrowserUatTier0Status
from app.services.browser_uat_tier0 import (
    JobResultPayload,
    create_browser_uat_tier0_execution,
    ingest_browser_uat_tier0_job_result,
)
from sqlalchemy import select


def ingest_manual_tier0_result(
    *,
    analysis_run_id: uuid.UUID,
    job_result: JobResultPayload,
    idempotency_key: str,
) -> uuid.UUID:
    """Create (or reuse, if idempotency_key repeats) an execution row for
    analysis_run_id, ingest job_result into it, and mark it terminal --
    mirroring worker_app/tasks/browser_uat_tier0.py's _finalize semantics
    exactly (COMPLETED only when overall_status is "pass", else PARTIAL,
    never FAILED, since real per-page evidence WAS produced). Returns the
    execution_id.
    """
    with SessionLocal() as db:
        analysis_run = db.get(AnalysisRun, analysis_run_id)
        if analysis_run is None:
            raise ValueError(f"Analysis run {analysis_run_id} does not exist.")

        execution, _created = create_browser_uat_tier0_execution(
            db,
            website_id=analysis_run.website_id,
            analysis_run_id=analysis_run_id,
            idempotency_key=idempotency_key,
        )
        # execution.id (the primary key) is what BrowserUatTier0PageResult's
        # FK actually targets -- execution.execution_id is a SEPARATE
        # business/correlation key (used externally, e.g. by the API's
        # BrowserUatTier0ExecutionRead schema and Lane A/B's GitHub Actions
        # run-name matching), not a foreign key target. Easy to mix up since
        # ingest_browser_uat_tier0_job_result's own parameter is also named
        # execution_id -- confirmed against tests/api/test_browser_uat_tier0_ingestion.py,
        # which passes execution.id there.
        execution_pk = execution.id
        execution_id = execution.execution_id

    with SessionLocal() as db:
        ingest_browser_uat_tier0_job_result(db, execution_id=execution_pk, job_result=job_result)

    final_status = (
        BrowserUatTier0Status.COMPLETED
        if job_result["overall_status"] == "pass"
        else BrowserUatTier0Status.PARTIAL
    )
    with SessionLocal() as db:
        execution = db.scalar(
            select(BrowserUatTier0Execution).where(BrowserUatTier0Execution.id == execution_pk)
        )
        if execution is None:
            raise ValueError(f"Execution {execution_id} vanished before finalization.")
        execution.status = final_status.value
        execution.completed_at = datetime.now(UTC)
        db.commit()

    return execution_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-run-id", required=True, type=uuid.UUID)
    parser.add_argument("--json-file", required=True, type=Path)
    parser.add_argument(
        "--idempotency-key",
        default=None,
        help="Defaults to a timestamp-based key so repeated runs create independent history.",
    )
    args = parser.parse_args()

    job_result: JobResultPayload = json.loads(args.json_file.read_text(encoding="utf-8"))
    idempotency_key = (
        args.idempotency_key or f"manual-{job_result['platform']}-{datetime.now(UTC).isoformat()}"
    )

    execution_id = ingest_manual_tier0_result(
        analysis_run_id=args.analysis_run_id,
        job_result=job_result,
        idempotency_key=idempotency_key,
    )

    print(
        f"Ingested {args.json_file} into execution {execution_id} "
        f"(analysis_run {args.analysis_run_id})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

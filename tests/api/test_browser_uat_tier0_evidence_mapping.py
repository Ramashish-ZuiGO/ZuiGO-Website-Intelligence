"""M5: evidence -> UAT-state mapping.

apply_tier0_evidence/_build_browser_uat_matrix tests use plain dicts, matching
their existing dict-based interface. fetch_latest_tier0_page_results tests use
a real (SQLite) database to prove the "most recent usable execution" query
logic against actual rows.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from app.db.base import Base
from app.models import (
    AnalysisRun,
    BrowserUatTier0Execution,
    BrowserUatTier0PageResult,
    BrowserUatTier0ViewportResult,
    Project,
    Website,
)
from app.services.browser_compatibility import (
    BRANDED_BROWSER_SCOPE,
    _build_browser_uat_matrix,
    apply_tier0_evidence,
)
from app.services.browser_uat_tier0 import (
    fetch_latest_tier0_page_results,
    fetch_latest_tier0_structural_results,
)
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

EDGE_ROW = next(entry for entry in BRANDED_BROWSER_SCOPE if entry["browser"] == "Microsoft Edge")
CHROME_ROW = next(entry for entry in BRANDED_BROWSER_SCOPE if entry["browser"] == "Google Chrome")
SAFARI_ROW = next(entry for entry in BRANDED_BROWSER_SCOPE if entry["browser"] == "Apple Safari")


def _built_row(entry: dict) -> dict:
    """A row shaped like _build_browser_uat_matrix's own output, built from
    zero engine evidence -- the exact NOT_VERIFIED starting point apply_tier0_evidence
    must be able to transform."""
    return {
        "browser": entry["browser"],
        "required_platforms": list(entry["required_platforms"]),
        "verification_state": "NOT_VERIFIED",
        "verification_state_label": "Not verified in current environment",
        "actual_verified_environments": [],
        "actual_tested_browser_version": None,
        "page_coverage": {
            "eligible_pages": 10,
            "passed_pages": 0,
            "partial_pages": 0,
            "failed_pages": 0,
            "unavailable_pages": 0,
            "not_tested_pages": 10,
        },
        "evidence_source": "none",
        "limitations": list(entry["limitations"]),
    }


def _page(*, channel: str, platform: str, status: str, version: str = "151.0.0.0") -> dict:
    return {
        "browser_channel": channel,
        "platform": platform,
        "status": status,
        "browser_version": version,
    }


class TestNoEvidenceIsANoOp:
    def test_row_is_returned_unchanged_when_no_tier0_results_exist(self) -> None:
        row = _built_row(EDGE_ROW)

        result = apply_tier0_evidence(row, [])

        assert result == row

    def test_row_is_unchanged_when_evidence_is_for_a_different_browser(self) -> None:
        row = _built_row(EDGE_ROW)
        chrome_only_evidence = [_page(channel="chrome", platform="windows", status="pass")]

        result = apply_tier0_evidence(row, chrome_only_evidence)

        assert result == row

    def test_safari_is_unchanged_when_the_only_evidence_is_for_a_different_channel(self) -> None:
        # Safari's own Tier 0 lane (Lane B, Selenium/safaridriver) exists now
        # -- but Chrome evidence must never be mistaken for Safari evidence
        # just because both ran on macOS.
        row = _built_row(SAFARI_ROW)
        evidence = [_page(channel="chrome", platform="macos", status="pass")]

        result = apply_tier0_evidence(row, evidence)

        assert result == row
        assert result["verification_state"] == "NOT_VERIFIED"


class TestFullVerificationWhenAllRequiredPlatformsAreClean:
    def test_edge_reaches_verified_with_only_windows_evidence(self) -> None:
        # Edge's only required platform is Windows -- unlike Chrome, it CAN
        # reach full VERIFIED through the desktop-only Tier 0 lane alone.
        row = _built_row(EDGE_ROW)
        evidence = [
            _page(channel="msedge", platform="windows", status="pass"),
            _page(channel="msedge", platform="windows", status="pass"),
        ]

        result = apply_tier0_evidence(row, evidence)

        assert result["verification_state"] == "VERIFIED"
        assert result["verification_state_label"] == "Verified"
        assert result["actual_tested_browser_version"] == "151.0.0.0"
        assert len(result["actual_verified_environments"]) == 1
        assert result["actual_verified_environments"][0]["platform"] == "Windows 10/11"
        assert result["actual_verified_environments"][0]["verification_state"] == "VERIFIED"
        assert result["page_coverage"]["passed_pages"] == 2
        assert result["page_coverage"]["failed_pages"] == 0


class TestChromeCanNeverReachFullVerifiedFromDesktopAloneYet:
    def test_clean_windows_and_macos_still_caps_at_partially_verified(self) -> None:
        # Chrome requires Windows + macOS + Android. Without Android evidence
        # -- must never claim full VERIFIED just because the two desktop
        # platforms are spotless.
        row = _built_row(CHROME_ROW)
        evidence = [
            _page(channel="chrome", platform="windows", status="pass"),
            _page(channel="chrome", platform="macos", status="pass"),
        ]

        result = apply_tier0_evidence(row, evidence)

        assert result["verification_state"] == "PARTIALLY_VERIFIED"
        assert len(result["actual_verified_environments"]) == 2
        assert all(
            env["verification_state"] == "VERIFIED"
            for env in result["actual_verified_environments"]
        )
        # Android is simply absent -- never fabricated as tested.
        platforms = {env["platform"] for env in result["actual_verified_environments"]}
        assert platforms == {"Windows 10/11", "macOS 13+"}


class TestChromeReachesFullVerifiedWithLaneCAndroidEvidence:
    def test_clean_windows_macos_and_android_evidence_reaches_full_verified(self) -> None:
        # Lane C (manual ChromeDriver-over-adb, scripts/browser_uat_tier0_check_android.mjs
        # + scripts/ingest_manual_tier0_result.py) supplies the last missing
        # required platform -- with all three clean, Chrome finally reaches
        # full VERIFIED, the first time any browser gets there via Android
        # evidence.
        row = _built_row(CHROME_ROW)
        evidence = [
            _page(channel="chrome", platform="windows", status="pass"),
            _page(channel="chrome", platform="macos", status="pass"),
            _page(channel="chrome", platform="android", status="pass", version="151.0.7922.137"),
        ]

        result = apply_tier0_evidence(row, evidence)

        assert result["verification_state"] == "VERIFIED"
        assert result["verification_state_label"] == "Verified"
        assert len(result["actual_verified_environments"]) == 3
        platforms = {env["platform"] for env in result["actual_verified_environments"]}
        assert platforms == {"Windows 10/11", "macOS 13+", "Android 12+ (phone and tablet)"}
        assert all(
            env["verification_state"] == "VERIFIED"
            for env in result["actual_verified_environments"]
        )

    def test_a_failing_android_page_alone_caps_the_row_at_partially_verified(self) -> None:
        row = _built_row(CHROME_ROW)
        evidence = [
            _page(channel="chrome", platform="windows", status="pass"),
            _page(channel="chrome", platform="macos", status="pass"),
            _page(channel="chrome", platform="android", status="fail"),
        ]

        result = apply_tier0_evidence(row, evidence)

        assert result["verification_state"] == "PARTIALLY_VERIFIED"
        android_env = next(
            env
            for env in result["actual_verified_environments"]
            if env["platform"] == "Android 12+ (phone and tablet)"
        )
        assert android_env["verification_state"] == "PARTIALLY_VERIFIED"


class TestSafariCanReachPartiallyVerifiedFromMacosLaneAlone:
    def test_clean_macos_evidence_alone_caps_at_partially_verified(self) -> None:
        # Without iOS/iPadOS evidence too, one clean platform out of three
        # required must never round up to full VERIFIED -- see
        # TestSafariReachesFullVerifiedWithIosAndIpadosEvidence below for the
        # case where all three are present.
        row = _built_row(SAFARI_ROW)
        evidence = [
            _page(channel="safari", platform="macos", status="pass", version="19.0"),
            _page(channel="safari", platform="macos", status="pass", version="19.0"),
        ]

        result = apply_tier0_evidence(row, evidence)

        assert result["verification_state"] == "PARTIALLY_VERIFIED"
        assert len(result["actual_verified_environments"]) == 1
        assert result["actual_verified_environments"][0]["platform"] == "macOS 13+"
        assert result["actual_verified_environments"][0]["verification_state"] == "VERIFIED"
        assert result["actual_tested_browser_version"] == "19.0"
        # iOS/iPadOS are simply absent -- never fabricated as tested.
        platforms = {env["platform"] for env in result["actual_verified_environments"]}
        assert platforms == {"macOS 13+"}

    def test_a_failing_safari_page_marks_macos_partially_verified(self) -> None:
        row = _built_row(SAFARI_ROW)
        evidence = [
            _page(channel="safari", platform="macos", status="pass"),
            _page(channel="safari", platform="macos", status="fail"),
        ]

        result = apply_tier0_evidence(row, evidence)

        assert result["verification_state"] == "PARTIALLY_VERIFIED"
        environment = result["actual_verified_environments"][0]
        assert environment["verification_state"] == "PARTIALLY_VERIFIED"
        assert environment["passed_pages"] == 1
        assert environment["failed_pages"] == 1


class TestSafariReachesFullVerifiedWithIosAndIpadosEvidence:
    def test_clean_macos_ios_and_ipados_evidence_reaches_full_verified(self) -> None:
        # The iOS Simulator Safari lane (Appium's Safari driver,
        # .github/scripts/browser_uat_tier0_check_ios.mjs) supplies Safari's
        # last two missing required platforms -- with all three clean,
        # Safari finally reaches full VERIFIED, matching Chrome's equivalent
        # milestone via Lane C's Android evidence.
        row = _built_row(SAFARI_ROW)
        evidence = [
            _page(channel="safari", platform="macos", status="pass", version="19.0"),
            _page(channel="safari", platform="ios", status="pass", version="19.0"),
            _page(channel="safari", platform="ipados", status="pass", version="19.0"),
        ]

        result = apply_tier0_evidence(row, evidence)

        assert result["verification_state"] == "VERIFIED"
        assert result["verification_state_label"] == "Verified"
        assert len(result["actual_verified_environments"]) == 3
        platforms = {env["platform"] for env in result["actual_verified_environments"]}
        assert platforms == {"macOS 13+", "iOS 16+", "iPadOS 16+"}
        assert all(
            env["verification_state"] == "VERIFIED"
            for env in result["actual_verified_environments"]
        )

    def test_a_failing_ipad_page_alone_caps_the_row_at_partially_verified(self) -> None:
        row = _built_row(SAFARI_ROW)
        evidence = [
            _page(channel="safari", platform="macos", status="pass"),
            _page(channel="safari", platform="ios", status="pass"),
            _page(channel="safari", platform="ipados", status="fail"),
        ]

        result = apply_tier0_evidence(row, evidence)

        assert result["verification_state"] == "PARTIALLY_VERIFIED"
        ipados_env = next(
            env for env in result["actual_verified_environments"] if env["platform"] == "iPadOS 16+"
        )
        assert ipados_env["verification_state"] == "PARTIALLY_VERIFIED"


class TestRealFailuresAreHonestlyReflected:
    def test_a_failing_page_marks_that_platform_partially_verified_not_verified(self) -> None:
        row = _built_row(EDGE_ROW)
        evidence = [
            _page(channel="msedge", platform="windows", status="pass"),
            _page(channel="msedge", platform="windows", status="fail"),
        ]

        result = apply_tier0_evidence(row, evidence)

        assert result["verification_state"] == "PARTIALLY_VERIFIED"
        environment = result["actual_verified_environments"][0]
        assert environment["verification_state"] == "PARTIALLY_VERIFIED"
        assert environment["passed_pages"] == 1
        assert environment["failed_pages"] == 1
        assert result["page_coverage"]["passed_pages"] == 1
        assert result["page_coverage"]["failed_pages"] == 1

    def test_unrecognized_platform_codes_are_never_silently_counted(self) -> None:
        # A platform code with no entry in TIER0_PLATFORM_LABELS must not
        # count toward verification -- explicit mapping only, never guessed.
        row = _built_row(EDGE_ROW)
        evidence = [_page(channel="msedge", platform="linux", status="pass")]

        result = apply_tier0_evidence(row, evidence)

        assert result == row  # no known platform matched -> unchanged


class TestBackwardCompatibleWiring:
    def test_build_matrix_without_tier0_results_behaves_exactly_as_before(self) -> None:
        matrix = _build_browser_uat_matrix([], uat_date="2026-08-14")

        assert all(row["verification_state"] == "NOT_VERIFIED" for row in matrix)
        assert all(row["actual_verified_environments"] == [] for row in matrix)

    def test_build_matrix_with_tier0_results_updates_only_matching_rows(self) -> None:
        evidence = [_page(channel="msedge", platform="windows", status="pass")]

        matrix = _build_browser_uat_matrix([], uat_date="2026-08-14", tier0_page_results=evidence)

        by_browser = {row["browser"]: row for row in matrix}
        assert by_browser["Microsoft Edge"]["verification_state"] == "VERIFIED"
        assert by_browser["Google Chrome"]["verification_state"] == "NOT_VERIFIED"
        assert by_browser["Apple Safari"]["verification_state"] == "NOT_VERIFIED"


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection: object, record: object) -> None:
        del record
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session


def _seed_analysis_run(db: Session) -> uuid.UUID:
    project = Project(name="Tier0EvidenceFetchTest")
    db.add(project)
    db.flush()
    website = Website(project_id=project.id, url="https://evidence-fixture.test/")
    db.add(website)
    db.flush()
    analysis_run = AnalysisRun(website_id=website.id, status="completed", progress_percent=100)
    db.add(analysis_run)
    db.commit()
    return analysis_run.id


def _seed_execution(
    db: Session,
    analysis_run_id: uuid.UUID,
    *,
    idempotency_key: str,
    completed_at: datetime,
    status: str,
) -> BrowserUatTier0Execution:
    analysis_run = db.get(AnalysisRun, analysis_run_id)
    execution = BrowserUatTier0Execution(
        website_id=analysis_run.website_id,
        analysis_run_id=analysis_run_id,
        lane="github_actions_chrome_edge",
        idempotency_key=idempotency_key,
        correlation_id=f"tier0-{uuid.uuid4().hex[:8]}",
        status=status,
        completed_at=completed_at,
    )
    db.add(execution)
    db.commit()
    return execution


class TestFetchLatestTier0PageResults:
    def test_returns_empty_list_when_no_execution_exists(self, db_session: Session) -> None:
        analysis_run_id = _seed_analysis_run(db_session)

        results = fetch_latest_tier0_page_results(db_session, analysis_run_id=analysis_run_id)

        assert results == []

    def test_returns_page_results_from_the_most_recent_completed_execution(
        self, db_session: Session
    ) -> None:
        analysis_run_id = _seed_analysis_run(db_session)
        now = datetime.now(UTC)

        older = _seed_execution(
            db_session,
            analysis_run_id,
            idempotency_key="run-1",
            completed_at=now - timedelta(hours=2),
            status="completed",
        )
        db_session.add(
            BrowserUatTier0PageResult(
                execution_id=older.id,
                browser_channel="msedge",
                platform="windows",
                url="https://stale.test/",
                status="fail",
            )
        )
        newer = _seed_execution(
            db_session,
            analysis_run_id,
            idempotency_key="run-2",
            completed_at=now,
            status="completed",
        )
        db_session.add(
            BrowserUatTier0PageResult(
                execution_id=newer.id,
                browser_channel="msedge",
                platform="windows",
                url="https://fresh.test/",
                status="pass",
            )
        )
        db_session.commit()

        results = fetch_latest_tier0_page_results(db_session, analysis_run_id=analysis_run_id)

        assert len(results) == 1
        assert results[0]["status"] == "pass"

    def test_unavailable_executions_are_not_treated_as_usable_evidence(
        self, db_session: Session
    ) -> None:
        analysis_run_id = _seed_analysis_run(db_session)
        _seed_execution(
            db_session,
            analysis_run_id,
            idempotency_key="run-unavailable",
            completed_at=datetime.now(UTC),
            status="unavailable",
        )

        results = fetch_latest_tier0_page_results(db_session, analysis_run_id=analysis_run_id)

        assert results == []


class TestFetchLatestTier0StructuralResults:
    def test_returns_empty_list_when_no_execution_exists(self, db_session: Session) -> None:
        analysis_run_id = _seed_analysis_run(db_session)

        results = fetch_latest_tier0_structural_results(db_session, analysis_run_id=analysis_run_id)

        assert results == []

    def test_returns_viewport_detail_from_the_most_recent_completed_execution(
        self, db_session: Session
    ) -> None:
        analysis_run_id = _seed_analysis_run(db_session)
        now = datetime.now(UTC)

        older = _seed_execution(
            db_session,
            analysis_run_id,
            idempotency_key="run-1",
            completed_at=now - timedelta(hours=2),
            status="completed",
        )
        stale_page = BrowserUatTier0PageResult(
            execution_id=older.id,
            browser_channel="chrome",
            platform="android",
            url="https://stale.test/",
            status="fail",
        )
        db_session.add(stale_page)
        db_session.flush()
        db_session.add(
            BrowserUatTier0ViewportResult(
                page_result_id=stale_page.id,
                viewport_name="Mobile (real device)",
                viewport_width=360,
                viewport_height=690,
                status="failed",
                horizontal_overflow=True,
            )
        )

        newer = _seed_execution(
            db_session,
            analysis_run_id,
            idempotency_key="run-2",
            completed_at=now,
            status="partial",
        )
        fresh_page = BrowserUatTier0PageResult(
            execution_id=newer.id,
            browser_channel="chrome",
            platform="android",
            url="https://fresh.test/",
            status="fail",
            browser_version="151.0.7922.137",
        )
        db_session.add(fresh_page)
        db_session.flush()
        db_session.add(
            BrowserUatTier0ViewportResult(
                page_result_id=fresh_page.id,
                viewport_name="Mobile (real device)",
                viewport_width=360,
                viewport_height=690,
                status="failed",
                horizontal_overflow=False,
                critical_elements_outside_viewport=2,
                overlapping_elements=5,
                small_tap_targets=13,
                tap_target_samples=[{"element_type": "a", "width": 8.3, "height": 17.3}],
            )
        )
        db_session.commit()

        results = fetch_latest_tier0_structural_results(db_session, analysis_run_id=analysis_run_id)

        assert len(results) == 1
        page = results[0]
        assert page["url"] == "https://fresh.test/"
        assert page["browser_version"] == "151.0.7922.137"
        assert len(page["viewport_results"]) == 1
        viewport = page["viewport_results"][0]
        assert viewport["horizontal_overflow"] is False
        assert viewport["critical_elements_outside_viewport"] == 2
        assert viewport["overlapping_elements"] == 5
        assert viewport["small_tap_targets"] == 13
        assert viewport["tap_target_samples"][0]["element_type"] == "a"

    def test_unavailable_executions_are_not_treated_as_usable_evidence(
        self, db_session: Session
    ) -> None:
        analysis_run_id = _seed_analysis_run(db_session)
        _seed_execution(
            db_session,
            analysis_run_id,
            idempotency_key="run-unavailable",
            completed_at=datetime.now(UTC),
            status="unavailable",
        )

        results = fetch_latest_tier0_structural_results(db_session, analysis_run_id=analysis_run_id)

        assert results == []

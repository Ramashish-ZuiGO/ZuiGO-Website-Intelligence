import uuid
from collections.abc import Iterator
from unittest.mock import patch

import pytest
from app.db.base import Base  # noqa: F401
from app.models.analysis_run import AnalysisRun
from app.models.performance import PerformanceSnapshot
from app.models.project import Project
from app.models.website import Website
from app.services.performance_service import collect_performance_evidence, compare_performance
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def do_connect(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_collect_performance_evidence_success(db_session):
    proj = Project(id=uuid.uuid4(), name="T")
    db_session.add(proj)
    website = Website(id=uuid.uuid4(), url="https://example.com", project_id=proj.id)
    db_session.add(website)
    run = AnalysisRun(id=uuid.uuid4(), website_id=website.id)
    db_session.add(run)
    db_session.commit()

    with patch("app.services.performance_service.get_crux_provider") as mock_get_provider:
        mock_provider = mock_get_provider.return_value

        async def mock_fetch_record(url=None, origin=None, form_factor="ALL"):
            if url == "https://example.com":
                return {
                    "status": "success",
                    "data": {
                        "record": {
                            "metrics": {
                                "largest_contentful_paint": {"percentiles": {"p75": 1200}},
                                "interaction_to_next_paint": {"percentiles": {"p75": 200}},
                            },
                            "collectionPeriod": {
                                "firstDate": {"year": 2026, "month": 7, "day": 1},
                                "lastDate": {"year": 2026, "month": 7, "day": 25},
                            },
                        }
                    },
                }
            return {"status": "no_record"}

        mock_provider.fetch_record = mock_fetch_record

        result = collect_performance_evidence(db_session, run.id, website, run)

        assert result["status"] == "success"
        assert result["snapshots_created"] == 4  # LCP, INP for both PHONE and DESKTOP

        snapshots = db_session.query(PerformanceSnapshot).all()
        assert len(snapshots) == 4

        lcp_phone = next(
            s for s in snapshots if s.metric_id == "field_lcp" and s.form_factor == "phone"
        )
        assert lcp_phone.raw_value == 1200
        assert lcp_phone.evidence_type == "field"
        assert lcp_phone.scope == "url"


def test_collect_performance_evidence_fallback_origin(db_session):
    proj = Project(id=uuid.uuid4(), name="T")
    db_session.add(proj)
    website = Website(id=uuid.uuid4(), url="https://example.com/some/path", project_id=proj.id)
    db_session.add(website)
    run = AnalysisRun(id=uuid.uuid4(), website_id=website.id)
    db_session.add(run)
    db_session.commit()

    with patch("app.services.performance_service.get_crux_provider") as mock_get_provider:
        mock_provider = mock_get_provider.return_value

        async def mock_fetch_record(url=None, origin=None, form_factor="ALL"):
            if url:
                return {"status": "no_record"}
            if origin == "https://example.com":
                return {
                    "status": "success",
                    "data": {
                        "record": {
                            "metrics": {
                                "cumulative_layout_shift": {"percentiles": {"p75": 0.05}},
                            }
                        }
                    },
                }
            return {"status": "error", "reason": "invalid"}

        mock_provider.fetch_record = mock_fetch_record

        result = collect_performance_evidence(db_session, run.id, website, run)

        assert result["status"] == "success"
        assert result["snapshots_created"] == 2  # CLS for PHONE and DESKTOP

        snapshots = db_session.query(PerformanceSnapshot).all()
        assert len(snapshots) == 2
        assert snapshots[0].scope == "origin"
        assert snapshots[0].metric_id == "field_cls"


def test_compare_performance_disagreement(db_session):
    proj = Project(id=uuid.uuid4(), name="T")
    db_session.add(proj)
    website = Website(id=uuid.uuid4(), url="https://example.com", project_id=proj.id)
    db_session.add(website)
    db_session.commit()

    exec_id = uuid.uuid4()
    # Field snapshot
    snap_field = PerformanceSnapshot(
        execution_id=exec_id,
        website_id=website.id,
        url_or_origin="https://example.com",
        evidence_source="crux",
        evidence_type="field",
        scope="url",
        form_factor="desktop",
        metric_id="field_lcp",
        availability_status="available",
        raw_value=2500,  # 2.5s
    )
    # Lab snapshot
    snap_lab = PerformanceSnapshot(
        execution_id=exec_id,
        website_id=website.id,
        url_or_origin="https://example.com",
        evidence_source="lighthouse",
        evidence_type="lab",
        scope="url",
        form_factor="desktop",
        metric_id="lab_lcp",
        availability_status="available",
        raw_value=1200,  # 1.2s - much faster
    )
    db_session.add_all([snap_field, snap_lab])
    db_session.commit()

    result = compare_performance(db_session, website.id)
    assert result["disagreement"] is True
    assert "significantly slower than Lab LCP" in result["explanation"]


def test_compare_performance_agreement(db_session):
    proj = Project(id=uuid.uuid4(), name="T")
    db_session.add(proj)
    website = Website(id=uuid.uuid4(), url="https://example.com", project_id=proj.id)
    db_session.add(website)
    db_session.commit()

    exec_id = uuid.uuid4()
    snap_field = PerformanceSnapshot(
        execution_id=exec_id,
        website_id=website.id,
        url_or_origin="https://example.com",
        evidence_source="crux",
        evidence_type="field",
        scope="url",
        form_factor="desktop",
        metric_id="field_lcp",
        availability_status="available",
        raw_value=1200,
    )
    snap_lab = PerformanceSnapshot(
        execution_id=exec_id,
        website_id=website.id,
        url_or_origin="https://example.com",
        evidence_source="lighthouse",
        evidence_type="lab",
        scope="url",
        form_factor="desktop",
        metric_id="lab_lcp",
        availability_status="available",
        raw_value=1100,
    )
    db_session.add_all([snap_field, snap_lab])
    db_session.commit()

    result = compare_performance(db_session, website.id)
    assert result["disagreement"] is False
    assert result["explanation"] == "Field and Lab conditions align."


def test_compare_performance_boundary_abs_diff_lcp(db_session):
    proj = Project(id=uuid.uuid4(), name="T")
    db_session.add(proj)
    website = Website(id=uuid.uuid4(), url="https://example.com", project_id=proj.id)
    db_session.add(website)
    db_session.commit()

    exec_id = uuid.uuid4()
    # High relative diff (>0.2) but absolute diff is small (400 <= 500)
    # field = 1400, lab = 1000. abs = 400. rel = 400/1400 = 0.285 (>0.2)
    snap_field = PerformanceSnapshot(
        execution_id=exec_id,
        website_id=website.id,
        url_or_origin="https://example.com",
        evidence_source="crux",
        evidence_type="field",
        scope="url",
        form_factor="desktop",
        metric_id="field_lcp",
        availability_status="available",
        raw_value=1400,
    )
    snap_lab = PerformanceSnapshot(
        execution_id=exec_id,
        website_id=website.id,
        url_or_origin="https://example.com",
        evidence_source="lighthouse",
        evidence_type="lab",
        scope="url",
        form_factor="desktop",
        metric_id="lab_lcp",
        availability_status="available",
        raw_value=1000,
    )
    db_session.add_all([snap_field, snap_lab])
    db_session.commit()

    result = compare_performance(db_session, website.id)
    assert result["disagreement"] is False


def test_compare_performance_boundary_rel_diff_lcp(db_session):
    proj = Project(id=uuid.uuid4(), name="T")
    db_session.add(proj)
    website = Website(id=uuid.uuid4(), url="https://example.com", project_id=proj.id)
    db_session.add(website)
    db_session.commit()

    exec_id = uuid.uuid4()
    # High absolute diff (600 > 500) but rel diff is small (600/3600 = 0.166 <= 0.2)
    snap_field = PerformanceSnapshot(
        execution_id=exec_id,
        website_id=website.id,
        url_or_origin="https://example.com",
        evidence_source="crux",
        evidence_type="field",
        scope="url",
        form_factor="desktop",
        metric_id="field_lcp",
        availability_status="available",
        raw_value=3600,
    )
    snap_lab = PerformanceSnapshot(
        execution_id=exec_id,
        website_id=website.id,
        url_or_origin="https://example.com",
        evidence_source="lighthouse",
        evidence_type="lab",
        scope="url",
        form_factor="desktop",
        metric_id="lab_lcp",
        availability_status="available",
        raw_value=3000,
    )
    db_session.add_all([snap_field, snap_lab])
    db_session.commit()

    result = compare_performance(db_session, website.id)
    assert result["disagreement"] is False

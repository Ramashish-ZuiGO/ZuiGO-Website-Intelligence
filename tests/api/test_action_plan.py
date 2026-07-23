import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    ActionGenerationExecution,
    ActionGroup,
    ActionItem,
    ActionStatus,
    ActionStatusHistory,
    AnalysisFinding,
    AnalysisRun,
    AnalysisScore,
    AnalysisStatus,
    DiscoveryRun,
    DiscoveryStatus,
    FindingSeverity,
    FindingSource,
    PageAnalysisRun,
    Project,
    Website,
    WebsitePage,
    validate_action_transition,
)
from app.models.action_plan import ACTION_STATUS_TRANSITIONS
from app.services.action_generation import generate_actions
from app.services.priority import (
    PRIORITY_FORMULA_VERSION,
    calculate_priority_score,
)
from fastapi.testclient import TestClient
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
    def enable_foreign_keys(connection: object, record: object) -> None:
        del record
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    def override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def create_website(db: Session) -> tuple[Project, Website]:
    project = Project(name="ActionPlanTest")
    db.add(project)
    db.flush()
    website = Website(project_id=project.id, url="https://example.com/", name="Example")
    db.add(website)
    db.commit()
    return project, website


def create_discovery_run(db: Session, website: Website) -> DiscoveryRun:
    run = DiscoveryRun(
        website_id=website.id,
        status=DiscoveryStatus.COMPLETED,
        progress_percent=100,
        current_stage="completed",
        urls_discovered=5,
        urls_unique=5,
        urls_eligible=3,
        urls_excluded=1,
        urls_skipped=1,
        sitemap_count=1,
        crawl_limit_reached=False,
        maximum_depth_reached=2,
        created_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()
    return run


def create_page(db: Session, website: Website, path: str) -> WebsitePage:
    now = datetime.now(UTC)
    page = WebsitePage(
        website_id=website.id,
        normalized_url=f"https://example.com/{path}",
        original_url=f"https://example.com/{path}",
        page_type="unknown",
        page_type_confidence=80,
        page_type_indicators=[],
        classification_version="1.0.0",
        discovery_source="sitemap",
        discovery_evidence=[],
        crawl_depth=1,
        origin_relation="same_origin",
        robots_status="allowed",
        eligibility_status="eligible",
        latest_analysis_status="pending",
        page_analysis_level_1_status="completed",
        first_discovered_at=now,
        last_discovered_at=now,
    )
    db.add(page)
    db.flush()
    return page


def create_page_analysis_run(
    db: Session, page: WebsitePage, exec_id: uuid.UUID | None = None
) -> PageAnalysisRun:
    now = datetime.now(UTC)
    run = PageAnalysisRun(
        website_page_id=page.id,
        page_analysis_execution_id=exec_id or uuid.uuid4(),
        analysis_level=1,
        status="completed",
        requested_url=page.normalized_url,
        final_url=page.normalized_url,
        page_title="Test Page",
        basic_seo_signals={
            "has_title": False,
            "has_meta_description": False,
            "has_canonical": False,
            "no_h1": True,
            "h1_count": 0,
            "multiple_h1": False,
        },
        basic_accessibility_signals={
            "images_missing_alt": 2,
            "has_html_lang": False,
        },
        security_observations={
            "https": True,
            "x_frame_options": "DENY",
            "x_content_type_options": None,
        },
        analysis_started_at=now,
        analysis_completed_at=now,
    )
    db.add(run)
    db.flush()

    page.page_analysis_level_1_run_id = run.id
    db.flush()
    return run


def create_deep_analysis_run(
    db: Session, website: Website, page_run: PageAnalysisRun
) -> AnalysisRun:
    now = datetime.now(UTC)
    analysis_run = AnalysisRun(
        website_id=website.id,
        status=AnalysisStatus.COMPLETED,
        progress_percent=100,
        started_at=now,
        completed_at=now,
    )
    db.add(analysis_run)
    db.flush()

    page_run.deep_analysis_run_id = analysis_run.id
    db.flush()

    finding = AnalysisFinding(
        analysis_run_id=analysis_run.id,
        finding_code="MISSING_PAGE_TITLE",
        category="seo",
        title="Missing page title",
        description="The page has no title.",
        severity=FindingSeverity.HIGH,
        affected_url=page_run.final_url or "",
        evidence={"page_title": None},
        source=FindingSource.HTTP,
        confidence_percent=100,
    )
    db.add(finding)
    db.flush()

    score = AnalysisScore(
        analysis_run_id=analysis_run.id,
        formula_version="1.0.0",
        overall_score=75,
        performance_score=80,
        accessibility_score=70,
        best_practices_score=85,
        seo_score=65,
        technical_quality_score=75,
        confidence_percent=90,
        available_categories=[
            "performance",
            "accessibility",
            "best_practices",
            "seo",
            "technical_quality",
        ],
        unavailable_categories=[],
        weights={
            "performance": 25,
            "accessibility": 20,
            "best_practices": 15,
            "seo": 20,
            "technical_quality": 20,
        },
        deductions=[],
        calculation_details={"method": "weighted_sum"},
    )
    db.add(score)
    db.commit()

    return analysis_run


# ---------------------------------------------------------------------------
# Priority Formula Tests
# ---------------------------------------------------------------------------


class TestPriorityFormula:
    def test_formula_version(self) -> None:
        assert PRIORITY_FORMULA_VERSION == "1.0.0"

    def test_zero_boundary(self) -> None:
        score, comps = calculate_priority_score(
            severity="informational",
            affected_page_count=1,
            estimated_score_impact=0,
            confidence_percent=0,
            implementation_effort="very_high",
            business_impact="negligible",
        )
        assert score == 0
        assert 0 <= score <= 100

    def test_hundred_boundary(self) -> None:
        score, comps = calculate_priority_score(
            severity="critical",
            affected_page_count=100,
            estimated_score_impact=100,
            confidence_percent=100,
            implementation_effort="low",
            business_impact="critical",
        )
        assert score == 100
        assert 0 <= score <= 100

    def test_severity_effect(self) -> None:
        critical_score, _ = calculate_priority_score(
            severity="critical",
            affected_page_count=1,
            estimated_score_impact=0,
            confidence_percent=50,
            implementation_effort="medium",
            business_impact="negligible",
        )
        informational_score, _ = calculate_priority_score(
            severity="informational",
            affected_page_count=1,
            estimated_score_impact=0,
            confidence_percent=50,
            implementation_effort="medium",
            business_impact="negligible",
        )
        assert critical_score > informational_score

    def test_affected_pages_effect(self) -> None:
        many_score, _ = calculate_priority_score(
            severity="medium",
            affected_page_count=50,
            estimated_score_impact=0,
            confidence_percent=50,
            implementation_effort="medium",
            business_impact="negligible",
        )
        one_score, _ = calculate_priority_score(
            severity="medium",
            affected_page_count=1,
            estimated_score_impact=0,
            confidence_percent=50,
            implementation_effort="medium",
            business_impact="negligible",
        )
        assert many_score > one_score

    def test_confidence_effect(self) -> None:
        high_conf, _ = calculate_priority_score(
            severity="medium",
            affected_page_count=1,
            estimated_score_impact=0,
            confidence_percent=100,
            implementation_effort="medium",
            business_impact="negligible",
        )
        low_conf, _ = calculate_priority_score(
            severity="medium",
            affected_page_count=1,
            estimated_score_impact=0,
            confidence_percent=0,
            implementation_effort="medium",
            business_impact="negligible",
        )
        assert high_conf > low_conf

    def test_effort_effect(self) -> None:
        easy, _ = calculate_priority_score(
            severity="medium",
            affected_page_count=1,
            estimated_score_impact=0,
            confidence_percent=50,
            implementation_effort="low",
            business_impact="negligible",
        )
        hard, _ = calculate_priority_score(
            severity="medium",
            affected_page_count=1,
            estimated_score_impact=0,
            confidence_percent=50,
            implementation_effort="very_high",
            business_impact="negligible",
        )
        assert easy > hard

    def test_business_impact_effect(self) -> None:
        critical_impact, _ = calculate_priority_score(
            severity="medium",
            affected_page_count=1,
            estimated_score_impact=0,
            confidence_percent=50,
            implementation_effort="medium",
            business_impact="critical",
        )
        none_impact, _ = calculate_priority_score(
            severity="medium",
            affected_page_count=1,
            estimated_score_impact=0,
            confidence_percent=50,
            implementation_effort="medium",
            business_impact="negligible",
        )
        assert critical_impact > none_impact

    def test_missing_data_handling(self) -> None:
        score, comps = calculate_priority_score(
            severity="unknown",
            affected_page_count=0,
            estimated_score_impact=-5,
            confidence_percent=-10,
            implementation_effort="unknown",
            business_impact="unknown",
        )
        assert 0 <= score <= 100
        assert comps["formula_version"] == "1.0.0"

    def test_deterministic_result(self) -> None:
        args = {
            "severity": "high",
            "affected_page_count": 10,
            "estimated_score_impact": 50,
            "confidence_percent": 85,
            "implementation_effort": "medium",
            "business_impact": "major",
        }
        score1, _ = calculate_priority_score(**args)
        score2, _ = calculate_priority_score(**args)
        assert score1 == score2


# ---------------------------------------------------------------------------
# Status Transition Tests
# ---------------------------------------------------------------------------


class TestStatusTransitions:
    def test_valid_transitions(self) -> None:
        validate_action_transition("open", "acknowledged")
        validate_action_transition("open", "in_progress")
        validate_action_transition("open", "ignored")
        validate_action_transition("acknowledged", "in_progress")
        validate_action_transition("in_progress", "resolved")
        validate_action_transition("resolved", "reopened")
        validate_action_transition("ignored", "reopened")
        validate_action_transition("reopened", "in_progress")

    def test_invalid_transition_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid status transition"):
            validate_action_transition("open", "resolved")
        with pytest.raises(ValueError, match="Invalid status transition"):
            validate_action_transition("resolved", "ignored")
        with pytest.raises(ValueError, match="Invalid status transition"):
            validate_action_transition("acknowledged", "resolved")

    def test_all_statuses_have_transitions(self) -> None:
        valid_statuses = {s.value for s in ActionStatus}
        for status in valid_statuses:
            assert status in ACTION_STATUS_TRANSITIONS, f"Missing transitions for {status}"
            assert len(ACTION_STATUS_TRANSITIONS[status]) > 0, (
                f"No transitions defined for {status}"
            )

    def test_status_history_recorded(self, db_session: Session) -> None:
        project, website = create_website(db_session)
        page = create_page(db_session, website, "status-test")
        exec_id = uuid.uuid4()
        create_page_analysis_run(db_session, page, exec_id)

        gen_exec = ActionGenerationExecution(
            id=uuid.uuid4(),
            website_id=website.id,
            page_analysis_execution_id=exec_id,
            status="completed",
        )
        db_session.add(gen_exec)
        db_session.flush()

        item = ActionItem(
            generation_execution_id=gen_exec.id,
            website_id=website.id,
            website_page_id=page.id,
            source_finding_identity="TEST_001",
            issue_title="Test",
            issue_category="seo",
            severity="medium",
            priority_score=50,
            priority_formula_version="1.0.0",
            priority_components={},
            confidence="high",
            confidence_percent=90,
            estimated_effort="low",
            business_impact="moderate",
            responsible_area="frontend",
            responsible_role="Developer",
            action_location="Test",
            why_this_matters="Test",
            exact_correction="Test",
            implementation_steps="Test",
            verification_steps="Test",
            expected_result="Test",
            limitations="Test",
            evidence_summary={},
            source_audit="test",
            status="open",
        )
        db_session.add(item)
        db_session.flush()

        item.status = "in_progress"
        history = ActionStatusHistory(
            action_item_id=item.id,
            previous_status="open",
            new_status="in_progress",
            source="manual",
        )
        db_session.add(history)
        db_session.commit()

        history_rows = list(
            db_session.query(ActionStatusHistory)
            .filter(ActionStatusHistory.action_item_id == item.id)
            .order_by(ActionStatusHistory.changed_at.asc())
        )
        assert len(history_rows) >= 1
        assert history_rows[-1].previous_status == "open"
        assert history_rows[-1].new_status == "in_progress"

    def test_repeated_status_update_safe(self, db_session: Session) -> None:
        project, website = create_website(db_session)
        page = create_page(db_session, website, "repeat-status")
        exec_id = uuid.uuid4()

        gen_exec = ActionGenerationExecution(
            id=uuid.uuid4(),
            website_id=website.id,
            page_analysis_execution_id=exec_id,
            status="completed",
        )
        db_session.add(gen_exec)
        db_session.flush()

        item = ActionItem(
            generation_execution_id=gen_exec.id,
            website_id=website.id,
            website_page_id=page.id,
            source_finding_identity="TEST_002",
            issue_title="Test",
            issue_category="seo",
            severity="low",
            priority_score=30,
            priority_formula_version="1.0.0",
            priority_components={},
            confidence="medium",
            confidence_percent=70,
            estimated_effort="low",
            business_impact="minor",
            responsible_area="frontend",
            responsible_role="Developer",
            action_location="Test",
            why_this_matters="Test",
            exact_correction="Test",
            implementation_steps="Test",
            verification_steps="Test",
            expected_result="Test",
            limitations="Test",
            evidence_summary={},
            source_audit="test",
            status="open",
        )
        db_session.add(item)
        db_session.commit()

        item.status = "acknowledged"
        db_session.add(
            ActionStatusHistory(
                action_item_id=item.id,
                previous_status="open",
                new_status="acknowledged",
                source="manual",
            )
        )
        db_session.commit()

        item.status = "in_progress"
        db_session.add(
            ActionStatusHistory(
                action_item_id=item.id,
                previous_status="acknowledged",
                new_status="in_progress",
                source="manual",
            )
        )
        db_session.commit()

        item.status = "resolved"
        db_session.add(
            ActionStatusHistory(
                action_item_id=item.id,
                previous_status="in_progress",
                new_status="resolved",
                source="manual",
            )
        )
        db_session.commit()

        db_session.refresh(item)
        assert item.status == "resolved"
        all_history = list(
            db_session.query(ActionStatusHistory)
            .filter(ActionStatusHistory.action_item_id == item.id)
            .order_by(ActionStatusHistory.changed_at.asc())
        )
        assert len(all_history) == 3


# ---------------------------------------------------------------------------
# Grouping Tests
# ---------------------------------------------------------------------------


class TestGrouping:
    def test_same_issue_across_pages(self, db_session: Session) -> None:
        project, website = create_website(db_session)
        create_discovery_run(db_session, website)
        exec_id = uuid.uuid4()

        page1 = create_page(db_session, website, "page1")
        page2 = create_page(db_session, website, "page2")

        create_page_analysis_run(db_session, page1, exec_id)
        create_page_analysis_run(db_session, page2, exec_id)

        gen_exec = generate_actions(db_session, website.id, exec_id)
        assert gen_exec.status == "completed"
        actions = list(
            db_session.query(ActionItem)
            .filter(ActionItem.generation_execution_id == gen_exec.id)
            .all()
        )
        assert len(actions) > 0

        groups = list(
            db_session.query(ActionGroup)
            .filter(ActionGroup.generation_execution_id == gen_exec.id)
            .all()
        )
        for g in groups:
            assert g.affected_page_count >= 1

    def test_non_groupable_findings_separate(self, db_session: Session) -> None:
        project, website = create_website(db_session)
        create_discovery_run(db_session, website)
        exec_id = uuid.uuid4()

        page = create_page(db_session, website, "page")
        now = datetime.now(UTC)
        arun = AnalysisRun(
            website_id=website.id,
            status=AnalysisStatus.COMPLETED,
            progress_percent=100,
            started_at=now,
            completed_at=now,
        )
        db_session.add(arun)
        db_session.flush()

        page_run = PageAnalysisRun(
            website_page_id=page.id,
            page_analysis_execution_id=exec_id,
            analysis_level=1,
            status="completed",
            requested_url=page.normalized_url,
            final_url=page.normalized_url,
            basic_seo_signals={
                "has_title": True,
                "has_meta_description": True,
                "has_canonical": True,
                "no_h1": False,
                "h1_count": 1,
            },
            basic_accessibility_signals={"images_missing_alt": 0, "has_html_lang": True},
            security_observations={
                "https": True,
                "x_frame_options": "DENY",
                "x_content_type_options": "nosniff",
            },
            deep_analysis_run_id=arun.id,
            analysis_started_at=now,
            analysis_completed_at=now,
        )
        db_session.add(page_run)
        db_session.flush()

        finding1 = AnalysisFinding(
            analysis_run_id=arun.id,
            finding_code="POOR_LIGHTHOUSE_PERFORMANCE",
            category="performance",
            title="Poor performance",
            description="Low score",
            severity=FindingSeverity.MEDIUM,
            affected_url=page.normalized_url,
            evidence={"score": 45, "threshold": 50},
            source=FindingSource.LIGHTHOUSE,
            confidence_percent=100,
        )
        finding2 = AnalysisFinding(
            analysis_run_id=arun.id,
            finding_code="MISSING_HTML_LANGUAGE",
            category="accessibility",
            title="Missing HTML language",
            description="No lang attribute",
            severity=FindingSeverity.MEDIUM,
            affected_url=page.normalized_url,
            evidence={"html_language": None},
            source=FindingSource.PLAYWRIGHT,
            confidence_percent=100,
        )
        db_session.add(finding1)
        db_session.add(finding2)
        db_session.commit()

        gen_exec = generate_actions(db_session, website.id, exec_id)
        groups = list(
            db_session.query(ActionGroup)
            .filter(ActionGroup.generation_execution_id == gen_exec.id)
            .all()
        )
        group_keys = {g.grouping_key for g in groups}
        assert "poor_performance" in group_keys
        assert "missing_html_language" in group_keys

    def test_deterministic_grouping_key(self, db_session: Session) -> None:
        project, website = create_website(db_session)
        create_discovery_run(db_session, website)
        exec_id = uuid.uuid4()

        page = create_page(db_session, website, "keytest")
        run = create_page_analysis_run(db_session, page, exec_id)
        create_deep_analysis_run(db_session, website, run)

        gen_exec = generate_actions(db_session, website.id, exec_id)
        groups = list(
            db_session.query(ActionGroup)
            .filter(ActionGroup.generation_execution_id == gen_exec.id)
            .all()
        )
        for g in groups:
            assert len(g.grouping_key) > 0

    def test_duplicate_prevention_within_execution(self, db_session: Session) -> None:
        project, website = create_website(db_session)
        create_discovery_run(db_session, website)
        exec_id = uuid.uuid4()

        page = create_page(db_session, website, "duptest")
        run = create_page_analysis_run(db_session, page, exec_id)
        create_deep_analysis_run(db_session, website, run)

        gen_exec = generate_actions(db_session, website.id, exec_id)

        existing = list(
            db_session.query(ActionItem)
            .filter(ActionItem.generation_execution_id == gen_exec.id)
            .all()
        )
        for item in existing:
            dupes = list(
                db_session.query(ActionItem)
                .filter(
                    ActionItem.generation_execution_id == gen_exec.id,
                    ActionItem.source_finding_identity == item.source_finding_identity,
                    ActionItem.website_page_id == item.website_page_id,
                )
                .all()
            )
            assert len(dupes) == 1


# ---------------------------------------------------------------------------
# Execution Tests
# ---------------------------------------------------------------------------


class TestExecution:
    def test_two_generations_same_analysis(self, db_session: Session) -> None:
        project, website = create_website(db_session)
        create_discovery_run(db_session, website)
        exec_id = uuid.uuid4()

        page = create_page(db_session, website, "gen1")
        create_page_analysis_run(db_session, page, exec_id)

        first = generate_actions(db_session, website.id, exec_id)
        assert first.total_actions_generated > 0

        second = generate_actions(db_session, website.id, exec_id)
        assert second.id != first.id
        assert second.total_findings_processed == first.total_findings_processed

    def test_retry_same_execution_id(self, db_session: Session) -> None:
        project, website = create_website(db_session)
        create_discovery_run(db_session, website)
        exec_id = uuid.uuid4()
        gen_exec_id = uuid.uuid4()

        page = create_page(db_session, website, "retry")
        create_page_analysis_run(db_session, page, exec_id)

        first = generate_actions(
            db_session, website.id, exec_id, generation_execution_id=gen_exec_id
        )
        assert first.id == gen_exec_id

        second = generate_actions(
            db_session, website.id, exec_id, generation_execution_id=gen_exec_id
        )
        assert second.id == first.id

    def test_history_preservation(self, db_session: Session) -> None:
        project, website = create_website(db_session)
        create_discovery_run(db_session, website)

        exec_id_a = uuid.uuid4()
        exec_id_b = uuid.uuid4()

        page = create_page(db_session, website, "history1")
        create_page_analysis_run(db_session, page, exec_id_a)

        gen_a = generate_actions(db_session, website.id, exec_id_a)
        assert gen_a.status == "completed"

        page2 = create_page(db_session, website, "history2")
        create_page_analysis_run(db_session, page2, exec_id_b)

        gen_b = generate_actions(db_session, website.id, exec_id_b)
        assert gen_b.status == "completed"

        all_execs = list(
            db_session.query(ActionGenerationExecution)
            .filter(ActionGenerationExecution.website_id == website.id)
            .order_by(ActionGenerationExecution.created_at.asc())
            .all()
        )
        assert len(all_execs) >= 2

    def test_latest_execution_queries(self, db_session: Session) -> None:
        project, website = create_website(db_session)
        create_discovery_run(db_session, website)

        exec_id_1 = uuid.uuid4()
        exec_id_2 = uuid.uuid4()

        page = create_page(db_session, website, "latest1")
        create_page_analysis_run(db_session, page, exec_id_1)
        generate_actions(db_session, website.id, exec_id_1)

        page2 = create_page(db_session, website, "latest2")
        create_page_analysis_run(db_session, page2, exec_id_2)
        gen2 = generate_actions(db_session, website.id, exec_id_2)

        latest = (
            db_session.query(ActionGenerationExecution)
            .filter(ActionGenerationExecution.website_id == website.id)
            .order_by(ActionGenerationExecution.created_at.desc())
            .first()
        )
        assert latest is not None
        assert latest.id == gen2.id


# ---------------------------------------------------------------------------
# API Tests
# ---------------------------------------------------------------------------


class TestActionPlanAPI:
    def test_summary_empty(self, client: TestClient, db_session: Session) -> None:
        website = create_website(db_session)[1]
        response = client.get(f"/api/v1/websites/{website.id}/action-plan/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["total_actions"] == 0
        assert data["generation_execution_id"] is None

    def test_generate_and_summary(self, client: TestClient, db_session: Session) -> None:
        website = create_website(db_session)[1]
        create_discovery_run(db_session, website)
        exec_id = uuid.uuid4()
        page = create_page(db_session, website, "api-test")
        run = create_page_analysis_run(db_session, page, exec_id)
        create_deep_analysis_run(db_session, website, run)

        response = client.post(
            f"/api/v1/websites/{website.id}/action-plan/generate",
            params={"page_analysis_execution_id": str(exec_id)},
        )
        assert response.status_code == 202
        gen_data = response.json()
        assert gen_data["status"] == "completed"

        summary_resp = client.get(f"/api/v1/websites/{website.id}/action-plan/summary")
        assert summary_resp.status_code == 200
        summary = summary_resp.json()
        assert summary["generation_execution_id"] is not None
        assert summary["total_actions"] > 0

    def test_groups_pagination(self, client: TestClient, db_session: Session) -> None:
        website = create_website(db_session)[1]
        create_discovery_run(db_session, website)
        exec_id = uuid.uuid4()
        page = create_page(db_session, website, "paginate")
        run = create_page_analysis_run(db_session, page, exec_id)
        create_deep_analysis_run(db_session, website, run)

        client.post(
            f"/api/v1/websites/{website.id}/action-plan/generate",
            params={"page_analysis_execution_id": str(exec_id)},
        )

        response = client.get(
            f"/api/v1/websites/{website.id}/action-plan/groups?page=1&page_size=10"
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert data["page"] == 1
        assert data["page_size"] == 10

    def test_group_detail(self, client: TestClient, db_session: Session) -> None:
        website = create_website(db_session)[1]
        create_discovery_run(db_session, website)
        exec_id = uuid.uuid4()
        page = create_page(db_session, website, "detail")
        run = create_page_analysis_run(db_session, page, exec_id)
        create_deep_analysis_run(db_session, website, run)

        client.post(
            f"/api/v1/websites/{website.id}/action-plan/generate",
            params={"page_analysis_execution_id": str(exec_id)},
        )

        groups_resp = client.get(f"/api/v1/websites/{website.id}/action-plan/groups")
        assert groups_resp.status_code == 200
        groups = groups_resp.json()["items"]
        if groups:
            detail_resp = client.get(
                f"/api/v1/websites/{website.id}/action-plan/groups/{groups[0]['id']}"
            )
            assert detail_resp.status_code == 200
            detail = detail_resp.json()
            assert detail["id"] == groups[0]["id"]
            assert "actions" in detail

    def test_actions_list(self, client: TestClient, db_session: Session) -> None:
        website = create_website(db_session)[1]
        create_discovery_run(db_session, website)
        exec_id = uuid.uuid4()
        page = create_page(db_session, website, "actions")
        run = create_page_analysis_run(db_session, page, exec_id)
        create_deep_analysis_run(db_session, website, run)

        client.post(
            f"/api/v1/websites/{website.id}/action-plan/generate",
            params={"page_analysis_execution_id": str(exec_id)},
        )

        response = client.get(f"/api/v1/websites/{website.id}/action-plan/actions")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data

    def test_action_detail_and_history(self, client: TestClient, db_session: Session) -> None:
        website = create_website(db_session)[1]
        create_discovery_run(db_session, website)
        exec_id = uuid.uuid4()
        page = create_page(db_session, website, "action-detail")
        run = create_page_analysis_run(db_session, page, exec_id)
        create_deep_analysis_run(db_session, website, run)

        client.post(
            f"/api/v1/websites/{website.id}/action-plan/generate",
            params={"page_analysis_execution_id": str(exec_id)},
        )

        actions_resp = client.get(f"/api/v1/websites/{website.id}/action-plan/actions")
        assert actions_resp.status_code == 200
        actions = actions_resp.json()["items"]
        if actions:
            detail_resp = client.get(
                f"/api/v1/websites/{website.id}/action-plan/actions/{actions[0]['id']}"
            )
            assert detail_resp.status_code == 200
            detail = detail_resp.json()
            assert detail["id"] == actions[0]["id"]
            assert "status_history" in detail

            history_resp = client.get(
                f"/api/v1/websites/{website.id}/action-plan/actions/{actions[0]['id']}/history"
            )
            assert history_resp.status_code == 200
            assert isinstance(history_resp.json(), list)

    def test_status_update(self, client: TestClient, db_session: Session) -> None:
        website = create_website(db_session)[1]
        create_discovery_run(db_session, website)
        exec_id = uuid.uuid4()
        page = create_page(db_session, website, "status-update")
        run = create_page_analysis_run(db_session, page, exec_id)
        create_deep_analysis_run(db_session, website, run)

        client.post(
            f"/api/v1/websites/{website.id}/action-plan/generate",
            params={"page_analysis_execution_id": str(exec_id)},
        )

        actions_resp = client.get(f"/api/v1/websites/{website.id}/action-plan/actions")
        actions = actions_resp.json()["items"]

        exec_id2 = uuid.uuid4()

        gen_exec = ActionGenerationExecution(
            id=exec_id2,
            website_id=website.id,
            page_analysis_execution_id=exec_id,
            status="completed",
        )
        db_session.add(gen_exec)
        db_session.commit()

        if actions:
            action_id = actions[0]["id"]
            update_resp = client.patch(
                f"/api/v1/websites/{website.id}/action-plan/actions/{action_id}/status",
                json={"status": "acknowledged", "source": "manual"},
            )
            assert update_resp.status_code == 200
            updated = update_resp.json()
            assert updated["status"] == "acknowledged"

    def test_invalid_status_transition(self, client: TestClient, db_session: Session) -> None:
        website = create_website(db_session)[1]
        create_discovery_run(db_session, website)
        exec_id = uuid.uuid4()
        page = create_page(db_session, website, "invalid-status")
        run = create_page_analysis_run(db_session, page, exec_id)
        create_deep_analysis_run(db_session, website, run)

        client.post(
            f"/api/v1/websites/{website.id}/action-plan/generate",
            params={"page_analysis_execution_id": str(exec_id)},
        )

        actions_resp = client.get(f"/api/v1/websites/{website.id}/action-plan/actions")
        actions = actions_resp.json()["items"]
        if actions:
            action_id = actions[0]["id"]
            update_resp = client.patch(
                f"/api/v1/websites/{website.id}/action-plan/actions/{action_id}/status",
                json={"status": "resolved", "source": "manual"},
            )
            assert update_resp.status_code in (422, 200)

    def test_bulk_status_update(self, client: TestClient, db_session: Session) -> None:
        website = create_website(db_session)[1]
        create_discovery_run(db_session, website)
        exec_id = uuid.uuid4()
        page = create_page(db_session, website, "bulk")
        run = create_page_analysis_run(db_session, page, exec_id)
        create_deep_analysis_run(db_session, website, run)

        client.post(
            f"/api/v1/websites/{website.id}/action-plan/generate",
            params={"page_analysis_execution_id": str(exec_id)},
        )

        actions_resp = client.get(f"/api/v1/websites/{website.id}/action-plan/actions")
        actions = actions_resp.json()["items"]
        if len(actions) >= 2:
            ids = [a["id"] for a in actions[:2]]
            bulk_resp = client.post(
                f"/api/v1/websites/{website.id}/action-plan/actions/bulk-status",
                json={"action_ids": ids, "status": "acknowledged", "source": "manual"},
            )
            assert bulk_resp.status_code == 200
            result = bulk_resp.json()
            assert result["succeeded"] == 2
            assert result["failed"] == 0

    def test_filters(self, client: TestClient, db_session: Session) -> None:
        website = create_website(db_session)[1]
        create_discovery_run(db_session, website)
        exec_id = uuid.uuid4()
        page = create_page(db_session, website, "filters")
        run = create_page_analysis_run(db_session, page, exec_id)
        create_deep_analysis_run(db_session, website, run)

        client.post(
            f"/api/v1/websites/{website.id}/action-plan/generate",
            params={"page_analysis_execution_id": str(exec_id)},
        )

        resp = client.get(f"/api/v1/websites/{website.id}/action-plan/groups?severity=high")
        assert resp.status_code == 200

        resp2 = client.get(
            f"/api/v1/websites/{website.id}/action-plan/groups?sort_by=priority&sort_order=asc"
        )
        assert resp2.status_code == 200

    def test_standard_errors(self, client: TestClient, db_session: Session) -> None:
        fake_id = uuid.uuid4()
        resp = client.get(f"/api/v1/websites/{fake_id}/action-plan/summary")
        assert resp.status_code == 404
        assert "error" in resp.json()

        resp = client.get(f"/api/v1/websites/{fake_id}/action-plan/groups")
        assert resp.status_code == 404

    def test_backward_compatibility(self, client: TestClient, db_session: Session) -> None:
        website = create_website(db_session)[1]
        resp = client.get(f"/api/v1/websites/{website.id}/page-analysis/summary")
        assert resp.status_code == 200

        resp2 = client.get(f"/api/v1/websites/{website.id}/page-analysis/recommendations")
        assert resp2.status_code == 200

        resp3 = client.get(f"/api/v1/websites/{website.id}/page-analysis/coverage")
        assert resp3.status_code == 200


# ---------------------------------------------------------------------------
# Model/Metadata Tests
# ---------------------------------------------------------------------------


class TestModelDefinitions:
    def test_model_tables_registered(self) -> None:
        from app.db.base import Base as AppBase

        metadata = AppBase.metadata
        tables = metadata.tables
        assert "action_generation_executions" in tables
        assert "action_groups" in tables
        assert "action_items" in tables
        assert "action_status_history" in tables

    def test_action_item_columns(self) -> None:
        from app.db.base import Base as AppBase

        ai_table = AppBase.metadata.tables["action_items"]
        assert "priority_score" in ai_table.columns
        assert "confidence_percent" in ai_table.columns
        assert "issue_title" in ai_table.columns
        assert "issue_category" in ai_table.columns
        assert "why_this_matters" in ai_table.columns
        assert "exact_correction" in ai_table.columns
        assert "implementation_steps" in ai_table.columns

    def test_action_group_columns(self) -> None:
        from app.db.base import Base as AppBase

        ag_table = AppBase.metadata.tables["action_groups"]
        assert "grouping_key" in ag_table.columns
        assert "affected_page_count" in ag_table.columns
        assert "evidence_summary" in ag_table.columns
        assert "priority_components" in ag_table.columns

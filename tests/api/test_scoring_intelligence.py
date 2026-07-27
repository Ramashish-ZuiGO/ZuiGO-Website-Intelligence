import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    AnalysisResult,
    AnalysisRun,
    AnalysisScore,
    Project,
    ScoreExecution,
    Website,
)
from app.services.agent_platform_registry import AgentRegistry, ToolRegistry
from app.services.priority import PRIORITY_FORMULA_VERSION
from app.services.scoring_formula import CATEGORY_WEIGHTS, FORMULA_VERSION, calculate_score
from app.services.scoring_intelligence import calculate_score_execution, score_trend
from app.services.workflow_execution import AGENT_TOOL_PLAN
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def scoring_api() -> Iterator[tuple[TestClient, sessionmaker[Session], uuid.UUID, uuid.UUID]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        project = Project(name="Scoring intelligence")
        website = Website(
            project=project,
            url="https://scoring.test/",
            name="Scoring fixture",
            profile_id="global_general",
        )
        run = AnalysisRun(
            website=website,
            status="completed",
            progress_percent=100,
            profile_id="global_general",
            profile_version="1.0.0",
            completed_at=datetime.now(UTC),
        )
        db.add_all([project, website, run])
        db.flush()
        result = AnalysisResult(
            analysis_run_id=run.id,
            requested_url=website.url,
            final_url=website.url,
            http_status_code=200,
            page_title="Scoring",
            analysis_started_at=datetime.now(UTC),
            analysis_completed_at=datetime.now(UTC),
            raw_lighthouse_data={"categories": {}},
            raw_playwright_data={"http_status_code": 200},
        )
        score = AnalysisScore(
            analysis_run_id=run.id,
            formula_version="1.0.0",
            overall_score=89,
            performance_score=80,
            accessibility_score=90,
            best_practices_score=70,
            seo_score=100,
            technical_quality_score=100,
            confidence_percent=100,
            available_categories=list(CATEGORY_WEIGHTS),
            unavailable_categories=[],
            weights=CATEGORY_WEIGHTS,
            deductions=[],
            calculation_details={"rounding": "round-half-up"},
        )
        db.add_all([result, score])
        db.commit()
        run_id = run.id
        website_id = website.id

    def override_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app), factory, run_id, website_id
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_approved_formulas_and_exact_calculation_remain_unchanged() -> None:
    result = calculate_score(
        {
            "performance_score": 80,
            "accessibility_score": 90,
            "best_practices_score": 70,
            "seo_score": 100,
        },
        {"http_status_code": 200},
        [],
        audit_completed=True,
    )
    assert FORMULA_VERSION == "1.0.0"
    assert PRIORITY_FORMULA_VERSION == "1.0.0"
    assert CATEGORY_WEIGHTS == {
        "performance": 25,
        "accessibility": 20,
        "best_practices": 15,
        "seo": 20,
        "technical_quality": 20,
    }
    assert result["overall_score"] == 89


def test_execution_contributions_coverage_idempotency_and_history(
    scoring_api: tuple[TestClient, sessionmaker[Session], uuid.UUID, uuid.UUID],
) -> None:
    _client, factory, run_id, _website_id = scoring_api
    with factory() as db:
        first, created = calculate_score_execution(db, run_id, idempotency_key="same")
        repeated, repeated_created = calculate_score_execution(db, run_id, idempotency_key="same")
        historical, historical_created = calculate_score_execution(
            db, run_id, idempotency_key="different"
        )
        assert created is True
        assert repeated_created is False
        assert historical_created is True
        assert repeated.execution_id == first.execution_id
        assert historical.execution_id != first.execution_id
        assert first.overall_score == 89
        assert first.evidence_coverage_percentage == 100
        assert first.confidence_classification == "high"
        assert round(sum(item.contribution or 0 for item in first.categories), 6) == 88.5
        assert len(first.contributions) == 5
        assert db.scalar(select(ScoreExecution).where(ScoreExecution.id == first.id)) is first


def test_unavailable_metric_is_excluded_not_fabricated(
    scoring_api: tuple[TestClient, sessionmaker[Session], uuid.UUID, uuid.UUID],
) -> None:
    _client, factory, run_id, _website_id = scoring_api
    with factory() as db:
        legacy = db.scalar(select(AnalysisScore).where(AnalysisScore.analysis_run_id == run_id))
        assert legacy is not None
        legacy.accessibility_score = None
        legacy.overall_score = 88
        legacy.confidence_percent = 85
        db.commit()
        execution, _ = calculate_score_execution(db, run_id, idempotency_key="missing")
        accessibility = next(
            item for item in execution.contributions if item.metric_id == "accessibility_score"
        )
        assert execution.overall_score == 88
        assert execution.evidence_coverage_numerator == 4
        assert execution.evidence_coverage_denominator == 5
        assert execution.evidence_coverage_percentage == 80
        assert accessibility.inclusion_status == "excluded"
        assert accessibility.normalized_value is None
        assert accessibility.contribution is None


def test_trends_and_incompatible_profile_versions(
    scoring_api: tuple[TestClient, sessionmaker[Session], uuid.UUID, uuid.UUID],
) -> None:
    _client, factory, run_id, website_id = scoring_api
    with factory() as db:
        first, _ = calculate_score_execution(db, run_id, idempotency_key="first")
        first.created_at = datetime.now(UTC) - timedelta(days=1)
        db.commit()
        run = db.get(AnalysisRun, run_id)
        assert run is not None
        legacy = run.score
        assert legacy is not None
        legacy.performance_score = 90
        legacy.overall_score = 91
        db.commit()
        second, _ = calculate_score_execution(db, run_id, idempotency_key="second")
        assert second.overall_score == 91
        trend = score_trend(db, second)
        assert trend["state"] == "improved"
        assert trend["score_delta"] == 2
        first.scoring_profile_version = "0.9.0"
        db.commit()
        assert score_trend(db, second)["state"] == "incompatible"
        assert second.website_id == website_id


def test_exact_scoring_apis_filters_errors_and_breakdown(
    scoring_api: tuple[TestClient, sessionmaker[Session], uuid.UUID, uuid.UUID],
) -> None:
    client, _factory, run_id, website_id = scoring_api
    created = client.post(
        f"/api/v1/analysis-runs/{run_id}/scores/calculate",
        json={"idempotency_key": "api"},
    )
    repeated = client.post(
        f"/api/v1/analysis-runs/{run_id}/scores/calculate",
        json={"idempotency_key": "api"},
    )
    assert created.status_code == 201
    assert repeated.status_code == 201
    execution_id = created.json()["execution_id"]
    assert repeated.json()["execution_id"] == execution_id
    assert client.get(f"/api/v1/analysis-runs/{run_id}/scores?limit=1").status_code == 200
    assert client.get(f"/api/v1/websites/{website_id}/scores").status_code == 200
    history = client.get(f"/api/v1/websites/{website_id}/scores/history?limit=1&offset=0")
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert client.get(f"/api/v1/scores/{execution_id}").status_code == 200
    breakdown = client.get(f"/api/v1/scores/{execution_id}/breakdown")
    assert breakdown.status_code == 200
    assert len(breakdown.json()["categories"]) == 5
    assert len(breakdown.json()["contributions"]) == 5
    assert client.get("/api/v1/scoring/formulas").json()[0]["llm_calculation_allowed"] is False
    assert len(client.get("/api/v1/scoring/profiles").json()) == 4
    assert client.get(f"/api/v1/scores/{uuid.uuid4()}").status_code == 404
    assert (
        client.post(
            f"/api/v1/analysis-runs/{run_id}/scores/calculate",
            json={"idempotency_key": ""},
        ).status_code
        == 422
    )


def test_models_migration_and_private_reasoning_exclusion() -> None:
    inspector_names = set(Base.metadata.tables)
    assert {
        "score_executions",
        "score_snapshots",
        "category_scores",
        "metric_contributions",
        "score_explanations",
    } <= inspector_names
    execution_table = Base.metadata.tables["score_executions"]
    assert {fk.ondelete for fk in execution_table.foreign_key_constraints} == {"CASCADE"}
    assert {index.name for index in execution_table.indexes} == {
        "ix_score_executions_project_status",
        "ix_score_executions_run_created",
        "ix_score_executions_website_created",
    }
    all_columns = {
        column.name
        for table_name in inspector_names
        if table_name.startswith(("score_", "category_", "metric_"))
        for column in Base.metadata.tables[table_name].columns
    }
    assert (
        not {
            "chain_of_thought",
            "hidden_reasoning",
            "private_reasoning",
            "internal_monologue",
        }
        & all_columns
    )
    migration = Path("apps/api/alembic/versions/20260728_0017_scoring_intelligence.py").read_text(
        encoding="utf-8"
    )
    for table_name in (
        "score_executions",
        "score_snapshots",
        "category_scores",
        "metric_contributions",
        "score_explanations",
    ):
        assert f'"{table_name}"' in migration


def test_agent_integration_preserves_eight_agents_and_forbids_llm_scoring() -> None:
    assert len(AgentRegistry.get_all()) == 8
    tool = ToolRegistry.get("scoring_intelligence")
    assert tool is not None
    assert tool.availability_state == "available"
    assert "scoring_intelligence" in AGENT_TOOL_PLAN["evidence_validation_agent"]
    assert "approved_llm_completion" not in AGENT_TOOL_PLAN["evidence_validation_agent"]
    assert "Evidence Validation" not in tool.limitations
    assert "LLM cannot calculate or modify scores" in tool.limitations

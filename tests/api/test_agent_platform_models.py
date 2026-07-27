import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.db.base import Base
from app.models.agent_platform import (
    AgentArtifact,
    AgentCheckpoint,
    AgentEvent,
    AgentExecution,
    AgentRun,
    AgentStep,
)
from app.models.analysis_run import AnalysisRun
from app.models.project import Project
from app.models.website import Website
from sqlalchemy import Column, MetaData, Table, Uuid, create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

AGENT_TABLES = (
    AgentExecution.__table__,
    AgentRun.__table__,
    AgentStep.__table__,
    AgentEvent.__table__,
    AgentArtifact.__table__,
    AgentCheckpoint.__table__,
)


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
def project_and_run(db_session: Session) -> tuple[Project, AnalysisRun]:
    project = Project(name="Agent platform test")
    website = Website(
        project=project,
        url="https://agent-platform.test",
        name="Agent platform",
    )
    analysis_run = AnalysisRun(
        website=website,
        status="completed",
        progress_percent=100,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db_session.add_all([project, website, analysis_run])
    db_session.commit()
    return project, analysis_run


def make_execution(
    project: Project,
    analysis_run: AnalysisRun,
    *,
    idempotency_key: str,
) -> AgentExecution:
    return AgentExecution(
        workflow_id="full_website_analysis",
        workflow_version="1.0.0",
        project_id=project.id,
        analysis_run_id=analysis_run.id,
        input_fingerprint="a" * 64,
        idempotency_key=idempotency_key,
        status="completed",
        structured_input={"website_id": str(analysis_run.website_id)},
        structured_output={"status": "completed"},
        evidence_references=[{"reference": "analysis-run:test"}],
        provider_version_metadata={},
        failure_details={},
        partial_completion_details={},
        completed_at=datetime.now(UTC),
    )


def load_migration() -> ModuleType:
    migration_path = (
        Path(__file__).parents[2]
        / "apps"
        / "api"
        / "alembic"
        / "versions"
        / "20260727_0016_agent_platform_foundation.py"
    )
    spec = importlib.util.spec_from_file_location("task_026_migration_0016", migration_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def apply_migration(module: ModuleType, operations: Operations, action: str) -> None:
    original_op = module.op
    module.op = operations
    try:
        getattr(module, action)()
    finally:
        module.op = original_op


def test_historical_executions_and_idempotency_scope(
    db_session: Session,
    project_and_run: tuple[Project, AnalysisRun],
) -> None:
    project, analysis_run = project_and_run
    first = make_execution(project, analysis_run, idempotency_key="history-one")
    second = make_execution(project, analysis_run, idempotency_key="history-two")
    db_session.add_all([first, second])
    db_session.commit()

    assert isinstance(first.execution_id, UUID)
    assert first.execution_id != second.execution_id
    assert len(list(db_session.scalars(select(AgentExecution)))) == 2

    duplicate = make_execution(project, analysis_run, idempotency_key="history-one")
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    assert len(list(db_session.scalars(select(AgentExecution)))) == 2


def test_agent_execution_relationships_preserve_structured_activity(
    db_session: Session,
    project_and_run: tuple[Project, AnalysisRun],
) -> None:
    project, analysis_run = project_and_run
    execution = make_execution(project, analysis_run, idempotency_key="relationships")
    agent_run = AgentRun(
        execution=execution,
        agent_id="discovery_agent",
        agent_version="1.0.0",
        dependency_agent_run_ids=[],
        input_fingerprint="b" * 64,
        idempotency_key="discovery-attempt",
        status="completed",
        structured_input={"website_id": str(analysis_run.website_id)},
        structured_output={"page_count": 1},
        tool_activity_summary=[{"tool_id": "website_discovery", "status": "completed"}],
        evidence_references=[{"reference": "discovery-run:test"}],
        provider_version_metadata={},
        failure_details={},
        partial_completion_details={},
        completed_at=datetime.now(UTC),
    )
    step = AgentStep(
        agent_run=agent_run,
        step_name="discover",
        sequence_number=0,
        tool_id="website_discovery",
        tool_version="1.0.0",
        status="completed",
        structured_input={},
        structured_output={"page_count": 1},
        tool_activity_summary={"duration_ms": 5},
        evidence_references=[{"reference": "discovery-run:test"}],
        failure_details={},
        partial_completion_details={},
        completed_at=datetime.now(UTC),
    )
    event_record = AgentEvent(
        execution=execution,
        agent_run=agent_run,
        agent_step=step,
        event_type="step_completed",
        sequence_number=0,
        status="completed",
        structured_payload={"decision": "prerequisites_satisfied"},
        evidence_references=[{"reference": "discovery-run:test"}],
    )
    artifact = AgentArtifact(
        execution=execution,
        agent_run=agent_run,
        agent_step=step,
        artifact_type="evidence_manifest",
        name="Discovery evidence",
        storage_reference="database:discovery-run:test",
        content_hash="c" * 64,
        media_type="application/json",
        artifact_metadata={"version": "1.0.0"},
        evidence_references=[{"reference": "discovery-run:test"}],
    )
    checkpoint = AgentCheckpoint(
        execution=execution,
        agent_run=agent_run,
        agent_step=step,
        checkpoint_version=1,
        status="completed",
        resumable=False,
        input_fingerprint="b" * 64,
        state_summary={"completed_step_ids": [str(step.step_id)]},
        evidence_references=[{"reference": "discovery-run:test"}],
    )
    db_session.add_all([event_record, artifact, checkpoint])
    db_session.commit()
    db_session.expire_all()

    persisted = db_session.get(AgentExecution, execution.id)
    assert persisted is not None
    assert len(persisted.runs) == 1
    assert len(persisted.runs[0].steps) == 1
    assert len(persisted.events) == 1
    assert len(persisted.artifacts) == 1
    assert len(persisted.checkpoints) == 1
    assert persisted.runs[0].tool_activity_summary[0]["tool_id"] == "website_discovery"


def test_models_exclude_hidden_reasoning_fields_and_define_required_constraints() -> None:
    banned_names = {
        "chain_of_thought",
        "hidden_reasoning",
        "private_reasoning",
        "reasoning_trace",
        "scratchpad",
    }
    all_column_names = {column.name for table in AGENT_TABLES for column in table.columns}
    assert not all_column_names.intersection(banned_names)

    execution_columns = set(AgentExecution.__table__.columns.keys())
    assert {
        "execution_id",
        "workflow_id",
        "workflow_version",
        "project_id",
        "analysis_run_id",
        "input_fingerprint",
        "idempotency_key",
        "structured_input",
        "structured_output",
        "provider_version_metadata",
        "token_total",
        "cost_total_usd",
        "failure_details",
        "partial_completion_details",
    } <= execution_columns
    assert {table.name for table in AGENT_TABLES} == {
        "agent_executions",
        "agent_runs",
        "agent_steps",
        "agent_events",
        "agent_artifacts",
        "agent_checkpoints",
    }
    unique_names = {
        constraint.name
        for table in AGENT_TABLES
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert "uq_agent_executions_project_workflow_idempotency" in unique_names
    assert "uq_agent_runs_execution_agent_idempotency_attempt" in unique_names
    assert "uq_agent_checkpoints_run_version" in unique_names
    assert all(table.foreign_key_constraints for table in AGENT_TABLES)


def test_migration_upgrade_downgrade_reupgrade_matches_orm() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    parent_metadata = MetaData()
    for table_name in ("projects", "analysis_runs"):
        Table(table_name, parent_metadata, Column("id", Uuid(), primary_key=True))

    with engine.begin() as connection:
        parent_metadata.create_all(connection)
        operations = Operations(MigrationContext.configure(connection))
        migration = load_migration()

        apply_migration(migration, operations, "upgrade")
        inspector = inspect(connection)
        assert set(inspector.get_table_names()) >= {table.name for table in AGENT_TABLES}
        for model_table in AGENT_TABLES:
            migrated_columns = {
                column["name"]: column for column in inspector.get_columns(model_table.name)
            }
            assert set(migrated_columns) == set(model_table.columns.keys())
            assert all(
                migrated_columns[column.name]["nullable"] == column.nullable
                for column in model_table.columns
            )
            assert {
                index["name"]: tuple(index["column_names"] or ())
                for index in inspector.get_indexes(model_table.name)
            } == {
                index.name: tuple(column.name for column in index.columns)
                for index in model_table.indexes
            }
            assert {
                constraint["name"]: tuple(constraint["column_names"] or ())
                for constraint in inspector.get_unique_constraints(model_table.name)
            } == {
                constraint.name: tuple(column.name for column in constraint.columns)
                for constraint in model_table.constraints
                if constraint.__class__.__name__ == "UniqueConstraint"
            }
            assert {
                constraint["name"]
                for constraint in inspector.get_check_constraints(model_table.name)
            } == {
                constraint.name
                for constraint in model_table.constraints
                if constraint.__class__.__name__ == "CheckConstraint"
            }
            assert {
                (
                    tuple(foreign_key["constrained_columns"]),
                    foreign_key["referred_table"],
                    tuple(foreign_key["referred_columns"]),
                    foreign_key["options"].get("ondelete"),
                )
                for foreign_key in inspector.get_foreign_keys(model_table.name)
            } == {
                (
                    tuple(foreign_key.column_keys),
                    next(iter(foreign_key.elements)).column.table.name,
                    tuple(element.column.name for element in foreign_key.elements),
                    foreign_key.ondelete,
                )
                for foreign_key in model_table.foreign_key_constraints
            }

        apply_migration(migration, operations, "downgrade")
        assert not set(inspect(connection).get_table_names()).intersection(
            table.name for table in AGENT_TABLES
        )
        apply_migration(migration, operations, "upgrade")
        assert set(inspect(connection).get_table_names()) >= {table.name for table in AGENT_TABLES}

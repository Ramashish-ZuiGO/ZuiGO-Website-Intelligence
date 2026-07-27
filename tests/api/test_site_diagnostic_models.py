import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.db.base import Base
from app.models.analysis_run import AnalysisRun
from app.models.project import Project
from app.models.site_diagnostic import (
    SiteDiagnosticExecution,
    SiteDiagnosticFinding,
    SiteDiagnosticOccurrence,
)
from app.models.website import Website
from sqlalchemy import Column, MetaData, Table, Uuid, create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

DIAGNOSTIC_TABLES = (
    SiteDiagnosticExecution.__table__,
    SiteDiagnosticFinding.__table__,
    SiteDiagnosticOccurrence.__table__,
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
def website_and_run(db_session: Session) -> tuple[Website, AnalysisRun]:
    project = Project(id=uuid4(), name="Task 025 model test")
    website = Website(
        id=uuid4(),
        project=project,
        url="https://example.test",
        name="Example",
    )
    analysis_run = AnalysisRun(
        id=uuid4(),
        website=website,
        status="completed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db_session.add_all([project, website, analysis_run])
    db_session.commit()
    return website, analysis_run


def make_execution(
    website: Website,
    analysis_run: AnalysisRun,
    *,
    idempotency_key: str,
) -> SiteDiagnosticExecution:
    return SiteDiagnosticExecution(
        website_id=website.id,
        analysis_run_id=analysis_run.id,
        workflow_id="site_diagnostics",
        workflow_version="1.0.0",
        selected_profile_id="global_general",
        selected_profile_version="1.0.0",
        input_fingerprint="a" * 64,
        evidence_fingerprint="b" * 64,
        idempotency_key=idempotency_key,
        diagnostic_engine_version="1.0.0",
        rule_registry_version="1.0.0",
        status="completed",
        total_page_count=75,
        processed_page_count=75,
        failed_page_count=0,
        evidence_coverage_numerator=75,
        evidence_coverage_denominator=75,
        evidence_coverage_ratio=1.0,
        error_metadata={},
        partial_completion_metadata={},
        completed_at=datetime.now(UTC),
    )


def make_finding(
    execution: SiteDiagnosticExecution, occurrence_count: int
) -> SiteDiagnosticFinding:
    return SiteDiagnosticFinding(
        execution=execution,
        rule_id="duplicate_title_group",
        rule_version="1.0.0",
        category="metadata_content",
        severity="medium",
        confidence="high",
        scope="site",
        title="Duplicate page titles",
        description="Multiple pages share one normalized title.",
        why_it_matters="Distinct titles help people and search systems identify pages.",
        affected_page_count=occurrence_count,
        total_eligible_page_count=occurrence_count,
        occurrence_count=occurrence_count,
        affected_ratio=1.0,
        evidence_summary="All attributed pages share the same title.",
        evidence_references=[{"kind": "page_title", "version": "1.0.0"}],
        remediation_guidance="Give every page a distinct descriptive title.",
        responsible_role="Content strategy",
        verification_guidance="Re-run exact normalized-title grouping.",
    )


def load_migration() -> ModuleType:
    migration_path = (
        Path(__file__).parents[2]
        / "apps"
        / "api"
        / "alembic"
        / "versions"
        / "20260725_0015_site_diagnostics.py"
    )
    spec = importlib.util.spec_from_file_location("task_025_migration_0015", migration_path)
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


def constraint_map(table: Table, attribute: str) -> dict[str, tuple[str, ...]]:
    constraints = getattr(table, attribute)
    return {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in constraints
        if constraint.name is not None
    }


def test_multiple_historical_executions_have_independent_ids(
    db_session: Session,
    website_and_run: tuple[Website, AnalysisRun],
) -> None:
    website, analysis_run = website_and_run
    first = make_execution(website, analysis_run, idempotency_key="request-one")
    second = make_execution(website, analysis_run, idempotency_key="request-two")
    db_session.add_all([first, second])
    db_session.commit()

    executions = list(
        db_session.scalars(
            select(SiteDiagnosticExecution).where(
                SiteDiagnosticExecution.analysis_run_id == analysis_run.id
            )
        )
    )
    assert len(executions) == 2
    assert isinstance(first.id, UUID)
    assert isinstance(first.execution_id, UUID)
    assert first.id != second.id
    assert first.execution_id != second.execution_id
    assert first.execution_id != analysis_run.id
    assert second.execution_id != analysis_run.id


def test_idempotency_is_scoped_to_analysis_run(
    db_session: Session,
    website_and_run: tuple[Website, AnalysisRun],
) -> None:
    website, analysis_run = website_and_run
    db_session.add(make_execution(website, analysis_run, idempotency_key="same-request"))
    db_session.commit()

    db_session.add(make_execution(website, analysis_run, idempotency_key="same-request"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    assert (
        len(
            list(
                db_session.scalars(
                    select(SiteDiagnosticExecution).where(
                        SiteDiagnosticExecution.analysis_run_id == analysis_run.id
                    )
                )
            )
        )
        == 1
    )


def test_finding_relationship_persists_every_occurrence_without_cap(
    db_session: Session,
    website_and_run: tuple[Website, AnalysisRun],
) -> None:
    website, analysis_run = website_and_run
    execution = make_execution(website, analysis_run, idempotency_key="all-occurrences")
    finding = make_finding(execution, occurrence_count=75)
    finding.occurrences = [
        SiteDiagnosticOccurrence(
            normalized_url=f"https://example.test/page-{index}",
            evidence_reference=f"page-analysis:{index}",
            occurrence_fingerprint=f"{index:064x}",
            location="head > title",
            context={"page_index": index},
            observed_value="Shared title",
            expected_value="A unique title",
            supporting_evidence={"normalized_title": "shared title"},
        )
        for index in range(75)
    ]
    db_session.add(execution)
    db_session.commit()
    finding_id = finding.id
    db_session.expire_all()

    persisted = db_session.get(SiteDiagnosticFinding, finding_id)
    assert persisted is not None
    assert persisted.execution.id == execution.id
    assert len(persisted.occurrences) == 75
    assert all(occurrence.finding_id == persisted.id for occurrence in persisted.occurrences)


def test_model_required_columns_constraints_indexes_and_foreign_keys() -> None:
    execution_columns = set(SiteDiagnosticExecution.__table__.columns.keys())
    assert {
        "id",
        "execution_id",
        "analysis_run_id",
        "website_id",
        "workflow_id",
        "workflow_version",
        "selected_profile_id",
        "selected_profile_version",
        "input_fingerprint",
        "evidence_fingerprint",
        "idempotency_key",
        "status",
        "total_page_count",
        "processed_page_count",
        "failed_page_count",
        "evidence_coverage_numerator",
        "evidence_coverage_denominator",
        "evidence_coverage_ratio",
        "error_metadata",
        "partial_completion_metadata",
        "started_at",
        "completed_at",
        "created_at",
    } <= execution_columns

    finding_columns = set(SiteDiagnosticFinding.__table__.columns.keys())
    assert {
        "rule_id",
        "rule_version",
        "affected_page_count",
        "occurrence_count",
        "evidence_summary",
        "evidence_references",
        "remediation_guidance",
        "responsible_role",
        "verification_guidance",
    } <= finding_columns

    occurrence_columns = set(SiteDiagnosticOccurrence.__table__.columns.keys())
    assert {
        "website_page_id",
        "normalized_url",
        "evidence_reference",
        "occurrence_fingerprint",
        "element_selector",
        "resource_url",
        "location",
        "context",
    } <= occurrence_columns

    execution_uniques = constraint_map(SiteDiagnosticExecution.__table__, "constraints")
    assert execution_uniques["uq_site_diagnostic_executions_execution_id"] == ("execution_id",)
    assert execution_uniques["uq_site_diagnostic_executions_run_idempotency"] == (
        "analysis_run_id",
        "idempotency_key",
    )
    assert {index.name for table in DIAGNOSTIC_TABLES for index in table.indexes} >= {
        "ix_site_diagnostic_executions_run_created",
        "ix_site_diagnostic_executions_website_created",
        "ix_site_diagnostic_findings_execution_rule",
        "ix_site_diagnostic_occurrences_finding_id",
        "ix_site_diagnostic_occurrences_website_page_id",
    }

    occurrence_page_fk = next(
        foreign_key
        for foreign_key in SiteDiagnosticOccurrence.__table__.foreign_key_constraints
        if tuple(foreign_key.column_keys) == ("website_page_id",)
    )
    assert occurrence_page_fk.ondelete == "SET NULL"


def test_migration_upgrade_downgrade_reupgrade_matches_orm_structure() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    parent_metadata = MetaData()
    for table_name in ("websites", "analysis_runs", "website_pages"):
        Table(
            table_name,
            parent_metadata,
            Column("id", Uuid(), primary_key=True),
        )

    with engine.begin() as connection:
        parent_metadata.create_all(connection)
        context = MigrationContext.configure(connection)
        operations = Operations(context)
        migration = load_migration()

        apply_migration(migration, operations, "upgrade")
        inspector = inspect(connection)
        assert set(inspector.get_table_names()) >= {
            "site_diagnostic_executions",
            "site_diagnostic_findings",
            "site_diagnostic_occurrences",
        }

        for model_table in DIAGNOSTIC_TABLES:
            migrated_columns = {
                column["name"]: column for column in inspector.get_columns(model_table.name)
            }
            assert set(migrated_columns) == set(model_table.columns.keys())
            for model_column in model_table.columns:
                assert migrated_columns[model_column.name]["nullable"] == model_column.nullable

            migrated_indexes = {
                index["name"]: tuple(index["column_names"] or ())
                for index in inspector.get_indexes(model_table.name)
            }
            model_indexes = {
                index.name: tuple(column.name for column in index.columns)
                for index in model_table.indexes
            }
            assert migrated_indexes == model_indexes

            migrated_uniques = {
                constraint["name"]: tuple(constraint["column_names"] or ())
                for constraint in inspector.get_unique_constraints(model_table.name)
            }
            model_uniques = {
                constraint.name: tuple(column.name for column in constraint.columns)
                for constraint in model_table.constraints
                if constraint.__class__.__name__ == "UniqueConstraint"
            }
            assert migrated_uniques == model_uniques

            migrated_checks = {
                constraint["name"]
                for constraint in inspector.get_check_constraints(model_table.name)
            }
            model_checks = {
                constraint.name
                for constraint in model_table.constraints
                if constraint.__class__.__name__ == "CheckConstraint"
            }
            assert migrated_checks == model_checks

            migrated_foreign_keys = {
                (
                    tuple(foreign_key["constrained_columns"]),
                    foreign_key["referred_table"],
                    tuple(foreign_key["referred_columns"]),
                    foreign_key["options"].get("ondelete"),
                )
                for foreign_key in inspector.get_foreign_keys(model_table.name)
            }
            model_foreign_keys = {
                (
                    tuple(foreign_key.column_keys),
                    next(iter(foreign_key.elements)).column.table.name,
                    tuple(element.column.name for element in foreign_key.elements),
                    foreign_key.ondelete,
                )
                for foreign_key in model_table.foreign_key_constraints
            }
            assert migrated_foreign_keys == model_foreign_keys

        apply_migration(migration, operations, "downgrade")
        assert not set(inspect(connection).get_table_names()).intersection(
            table.name for table in DIAGNOSTIC_TABLES
        )

        apply_migration(migration, operations, "upgrade")
        assert set(inspect(connection).get_table_names()) >= {
            table.name for table in DIAGNOSTIC_TABLES
        }

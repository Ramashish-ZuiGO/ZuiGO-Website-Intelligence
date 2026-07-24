import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from app.db.base import Base
from app.models import Project
from app.models.repository import (
    FileScanStatus,
    RepositoryConnection,
    RepositoryFileIndex,
    RepositoryScanExecution,
    ScanStatus,
)
from app.services.repository.framework_detector import FrameworkDetectionService
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_: object, compiler: object, **kw: object) -> str:
    return "JSON"


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


def create_execution(db: Session) -> RepositoryScanExecution:
    project = Project(name="FrameworkDetectTest")
    db.add(project)
    db.flush()
    connection = RepositoryConnection(
        project_id=project.id,
        display_name="test-repo",
        local_root="/tmp/test",
        provider="local",
    )
    db.add(connection)
    db.flush()
    execution = RepositoryScanExecution(
        id=uuid.uuid4(),
        connection_id=connection.id,
        status=ScanStatus.COMPLETED,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db.add(execution)
    db.flush()
    return execution


def add_file(
    db: Session,
    execution_id: uuid.UUID,
    path: str,
    extension: str,
    first_lines: str = "",
    language: str | None = None,
    scan_status: str = FileScanStatus.SCANNED,
) -> RepositoryFileIndex:
    f = RepositoryFileIndex(
        scan_execution_id=execution_id,
        relative_path=path,
        normalized_path=path,
        extension=extension,
        detected_language=language,
        file_size=len(first_lines.encode("utf-8")),
        line_count=len(first_lines.splitlines()),
        content_hash="abc",
        first_lines=first_lines,
        scan_status=scan_status,
    )
    db.add(f)
    db.flush()
    return f


class TestFrameworkDetection:
    def test_detect_nextjs(self, db_session: Session) -> None:
        execution = create_execution(db_session)
        add_file(db_session, execution.id, "next.config.js", ".js", "module.exports = {};")
        add_file(
            db_session,
            execution.id,
            "package.json",
            ".json",
            '{"dependencies": {"next": "13.0.0"}}',
        )

        service = FrameworkDetectionService(db_session)
        technologies = service.detect_frameworks(execution.id)

        techs = {t.technology: t for t in technologies}
        assert "Next.js" in techs
        assert techs["Next.js"].confidence == "high"

    def test_detect_react(self, db_session: Session) -> None:
        execution = create_execution(db_session)
        add_file(db_session, execution.id, "src/App.jsx", ".jsx", "function App() { return null; }")
        add_file(
            db_session,
            execution.id,
            "package.json",
            ".json",
            '{"dependencies": {"react": "18.2.0"}}',
        )

        service = FrameworkDetectionService(db_session)
        technologies = service.detect_frameworks(execution.id)

        techs = {t.technology: t for t in technologies}
        assert "React" in techs
        assert techs["React"].confidence == "high"

    def test_detect_fastapi(self, db_session: Session) -> None:
        execution = create_execution(db_session)
        add_file(
            db_session,
            execution.id,
            "app/main.py",
            ".py",
            "from fastapi import FastAPI\napp = FastAPI()\n",
            language="Python",
        )

        service = FrameworkDetectionService(db_session)
        technologies = service.detect_frameworks(execution.id)

        techs = {t.technology: t for t in technologies}
        assert "FastAPI" in techs
        assert techs["FastAPI"].confidence == "high"

    def test_no_frameworks_for_empty_scan(self, db_session: Session) -> None:
        execution = create_execution(db_session)

        service = FrameworkDetectionService(db_session)
        technologies = service.detect_frameworks(execution.id)

        assert technologies == []

    def test_detect_typescript(self, db_session: Session) -> None:
        execution = create_execution(db_session)
        add_file(
            db_session,
            execution.id,
            "src/index.ts",
            ".ts",
            "const x: number = 1;\n",
            language="TypeScript",
        )
        add_file(
            db_session,
            execution.id,
            "src/app.tsx",
            ".tsx",
            "export const App = () => null;\n",
            language="TypeScript",
        )
        add_file(
            db_session,
            execution.id,
            "src/utils.ts",
            ".ts",
            "export const util = () => {};\n",
            language="TypeScript",
        )
        add_file(db_session, execution.id, "tsconfig.json", ".json", "{}")

        service = FrameworkDetectionService(db_session)
        technologies = service.detect_frameworks(execution.id)

        techs = {t.technology: t for t in technologies}
        assert "TypeScript" in techs
        assert techs["TypeScript"].confidence == "high"

    def test_confidence_levels(self, db_session: Session) -> None:
        execution = create_execution(db_session)
        add_file(
            db_session, execution.id, "src/component.jsx", ".jsx", "function C() { return null; }"
        )

        service = FrameworkDetectionService(db_session)
        technologies = service.detect_frameworks(execution.id)

        techs = {t.technology: t for t in technologies}
        assert "TypeScript" not in techs
        assert "React" in techs
        assert techs["React"].confidence == "medium"

    def test_nextjs_medium_confidence_with_config_only(self, db_session: Session) -> None:
        execution = create_execution(db_session)
        add_file(db_session, execution.id, "next.config.mjs", ".mjs", "export default {};")

        service = FrameworkDetectionService(db_session)
        technologies = service.detect_frameworks(execution.id)

        techs = {t.technology: t for t in technologies}
        assert "Next.js" in techs
        assert techs["Next.js"].confidence == "medium"

    def test_nextjs_low_confidence_with_pages_dir(self, db_session: Session) -> None:
        execution = create_execution(db_session)
        add_file(
            db_session, execution.id, "pages/index.tsx", ".tsx", "export default function Home() {}"
        )

        service = FrameworkDetectionService(db_session)
        technologies = service.detect_frameworks(execution.id)

        techs = {t.technology: t for t in technologies}
        assert "Next.js" in techs
        assert techs["Next.js"].confidence == "low"

    def test_typescript_low_confidence_without_tsconfig(self, db_session: Session) -> None:
        execution = create_execution(db_session)
        add_file(
            db_session, execution.id, "src/index.ts", ".ts", "const x = 1;\n", language="TypeScript"
        )

        service = FrameworkDetectionService(db_session)
        technologies = service.detect_frameworks(execution.id)

        techs = {t.technology: t for t in technologies}
        assert "TypeScript" in techs
        assert techs["TypeScript"].confidence == "low"

    def test_technology_preserved_across_runs(self, db_session: Session) -> None:
        execution = create_execution(db_session)
        add_file(db_session, execution.id, "next.config.js", ".js", "module.exports = {};")
        add_file(
            db_session,
            execution.id,
            "package.json",
            ".json",
            '{"dependencies": {"next": "13.0.0"}}',
        )

        service = FrameworkDetectionService(db_session)
        first_run = service.detect_frameworks(execution.id)
        second_run = service.detect_frameworks(execution.id)

        assert len(first_run) == len(second_run)
        assert first_run[0].id == second_run[0].id

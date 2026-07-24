import os
import subprocess
import tempfile
import uuid
from collections.abc import Iterator

import pytest
from app.db.base import Base
from app.errors.exceptions import ApplicationError
from app.models import (
    FileScanStatus,
    Project,
    RepositoryConnection,
    ScanStatus,
)
from app.models.repository import RepositoryFileIndex
from app.services.repository.git_scanner import RepositoryScannerService
from sqlalchemy import create_engine, event, select
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


def create_project(db: Session) -> Project:
    project = Project(name="ScannerTest")
    db.add(project)
    db.flush()
    return project


def create_connection(db: Session, project: Project, local_root: str) -> RepositoryConnection:
    conn = RepositoryConnection(
        project_id=project.id,
        display_name="test-repo",
        local_root=local_root,
        provider="local",
    )
    db.add(conn)
    db.flush()
    return conn


def init_git_repo(path: str) -> None:
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path,
        capture_output=True,
        check=True,
    )


def create_test_file(repo_path: str, relative_path: str, content: str = "") -> str:
    full_path = os.path.join(repo_path, relative_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    return full_path


class TestRepositoryScanner:
    def test_discover_python_files(self, db_session: Session) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            init_git_repo(tmpdir)
            project = create_project(db_session)
            connection = create_connection(db_session, project, tmpdir)
            create_test_file(tmpdir, "main.py", "def hello():\n    print('hello')\n")
            create_test_file(tmpdir, "utils/helpers.py", "def helper():\n    pass\n")
            subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=tmpdir,
                capture_output=True,
                env={**os.environ, "GIT_COMMITTER_DATE": "2024-01-01T00:00:00"},
            )

            service = RepositoryScannerService(db_session)
            execution_id = uuid.uuid4()
            execution = service.scan_repository(
                connection_id=connection.id,
                execution_id=execution_id,
            )

            assert execution.status == ScanStatus.COMPLETED
            assert execution.total_files_discovered == 2
            assert execution.scanned_files == 2

            files = list(
                db_session.scalars(
                    select(RepositoryFileIndex).where(
                        RepositoryFileIndex.scan_execution_id == execution_id,
                    )
                )
            )
            paths = {f.relative_path for f in files if f.scan_status == FileScanStatus.SCANNED}
            assert "main.py" in paths
            assert "utils/helpers.py" in paths
            langs = {f.detected_language for f in files if f.scan_status == FileScanStatus.SCANNED}
            assert "Python" in langs

    def test_discover_js_ts_files(self, db_session: Session) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            init_git_repo(tmpdir)
            project = create_project(db_session)
            connection = create_connection(db_session, project, tmpdir)
            create_test_file(tmpdir, "index.js", "const x = 1;\n")
            create_test_file(tmpdir, "component.tsx", "export const C = () => null;\n")
            subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=tmpdir,
                capture_output=True,
                env={**os.environ, "GIT_COMMITTER_DATE": "2024-01-01T00:00:00"},
            )

            service = RepositoryScannerService(db_session)
            execution_id = uuid.uuid4()
            execution = service.scan_repository(
                connection_id=connection.id,
                execution_id=execution_id,
            )

            assert execution.status == ScanStatus.COMPLETED
            assert execution.scanned_files == 2

    def test_ignores_binary_files(self, db_session: Session) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            init_git_repo(tmpdir)
            project = create_project(db_session)
            connection = create_connection(db_session, project, tmpdir)
            create_test_file(tmpdir, "main.py", "print('ok')\n")
            with open(os.path.join(tmpdir, "image.png"), "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
            subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=tmpdir,
                capture_output=True,
                env={**os.environ, "GIT_COMMITTER_DATE": "2024-01-01T00:00:00"},
            )

            service = RepositoryScannerService(db_session)
            execution_id = uuid.uuid4()
            execution = service.scan_repository(
                connection_id=connection.id,
                execution_id=execution_id,
            )

            assert execution.scanned_files == 1
            assert execution.skipped_files == 1

    def test_ignores_dotgit_node_modules_pycache(self, db_session: Session) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            init_git_repo(tmpdir)
            project = create_project(db_session)
            connection = create_connection(db_session, project, tmpdir)
            create_test_file(tmpdir, "main.py", "print('ok')\n")
            create_test_file(tmpdir, "node_modules/pkg/index.js", "ignored\n")
            create_test_file(tmpdir, "__pycache__/foo.pyc", "ignored\n")
            create_test_file(tmpdir, "src/app.py", "print('real')\n")
            subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=tmpdir,
                capture_output=True,
                env={**os.environ, "GIT_COMMITTER_DATE": "2024-01-01T00:00:00"},
            )

            service = RepositoryScannerService(db_session)
            execution_id = uuid.uuid4()
            execution = service.scan_repository(
                connection_id=connection.id,
                execution_id=execution_id,
            )

            assert execution.total_files_discovered == 2
            assert execution.scanned_files == 2
            assert execution.skipped_files == 0

    def test_secrets_are_redacted(self, db_session: Session) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            init_git_repo(tmpdir)
            project = create_project(db_session)
            connection = create_connection(db_session, project, tmpdir)
            create_test_file(
                tmpdir,
                "config.py",
                "API_KEY = 'sk-1234567890abcdef'\nPASSWORD = 'supersecret'\nprint('ok')\n",
            )
            subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=tmpdir,
                capture_output=True,
                env={**os.environ, "GIT_COMMITTER_DATE": "2024-01-01T00:00:00"},
            )

            service = RepositoryScannerService(db_session)
            execution_id = uuid.uuid4()
            service.scan_repository(
                connection_id=connection.id,
                execution_id=execution_id,
            )

            files = list(
                db_session.scalars(
                    select(RepositoryFileIndex).where(
                        RepositoryFileIndex.scan_execution_id == execution_id,
                        RepositoryFileIndex.scan_status == FileScanStatus.SCANNED,
                    )
                )
            )
            redacted_files = [f for f in files if f.redacted]
            assert len(redacted_files) >= 1
            redacted_file = redacted_files[0]
            assert "[REDACTED]" in (redacted_file.first_lines or "")
            assert "sk-1234567890abcdef" not in (redacted_file.first_lines or "")

    def test_content_snippets_are_bounded(self, db_session: Session) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            init_git_repo(tmpdir)
            project = create_project(db_session)
            connection = create_connection(db_session, project, tmpdir)
            lines = [f"line {i}" for i in range(200)]
            create_test_file(tmpdir, "large.py", "\n".join(lines))
            subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=tmpdir,
                capture_output=True,
                env={**os.environ, "GIT_COMMITTER_DATE": "2024-01-01T00:00:00"},
            )

            service = RepositoryScannerService(db_session)
            execution_id = uuid.uuid4()
            execution = service.scan_repository(
                connection_id=connection.id,
                execution_id=execution_id,
            )

            assert execution.status == ScanStatus.COMPLETED
            files = list(
                db_session.scalars(
                    select(RepositoryFileIndex).where(
                        RepositoryFileIndex.scan_execution_id == execution_id,
                    )
                )
            )
            scanned = [f for f in files if f.scan_status == FileScanStatus.SCANNED]
            assert len(scanned) == 1
            snippet_lines = (scanned[0].first_lines or "").splitlines()
            assert len(snippet_lines) <= 50

    def test_error_invalid_path(self, db_session: Session) -> None:
        project = create_project(db_session)
        connection = create_connection(db_session, project, "/nonexistent/path/that/does/not/exist")

        service = RepositoryScannerService(db_session)
        execution_id = uuid.uuid4()
        with pytest.raises(ApplicationError, match="does not exist"):
            service.scan_repository(
                connection_id=connection.id,
                execution_id=execution_id,
            )

    def test_idempotent_retry(self, db_session: Session) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            init_git_repo(tmpdir)
            project = create_project(db_session)
            connection = create_connection(db_session, project, tmpdir)
            create_test_file(tmpdir, "main.py", "x = 1\n")
            subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=tmpdir,
                capture_output=True,
                env={**os.environ, "GIT_COMMITTER_DATE": "2024-01-01T00:00:00"},
            )

            service = RepositoryScannerService(db_session)
            execution_id = uuid.uuid4()

            first_result = service.scan_repository(
                connection_id=connection.id,
                execution_id=execution_id,
            )
            assert first_result.status == ScanStatus.COMPLETED

            second_result = service.scan_repository(
                connection_id=connection.id,
                execution_id=execution_id,
            )
            assert second_result.id == first_result.id
            assert second_result.status == ScanStatus.COMPLETED

            files_count = len(
                list(
                    db_session.scalars(
                        select(RepositoryFileIndex).where(
                            RepositoryFileIndex.scan_execution_id == execution_id,
                        )
                    )
                )
            )
            assert files_count > 0

    def test_exported_symbols_detected(self, db_session: Session) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            init_git_repo(tmpdir)
            project = create_project(db_session)
            connection = create_connection(db_session, project, tmpdir)
            create_test_file(
                tmpdir,
                "module.py",
                "def my_function():\n    pass\n\nclass MyClass:\n    pass\n",
            )
            subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=tmpdir,
                capture_output=True,
                env={**os.environ, "GIT_COMMITTER_DATE": "2024-01-01T00:00:00"},
            )

            service = RepositoryScannerService(db_session)
            execution_id = uuid.uuid4()
            service.scan_repository(
                connection_id=connection.id,
                execution_id=execution_id,
            )

            files = list(
                db_session.scalars(
                    select(RepositoryFileIndex).where(
                        RepositoryFileIndex.scan_execution_id == execution_id,
                        RepositoryFileIndex.scan_status == FileScanStatus.SCANNED,
                    )
                )
            )
            py_file = next(f for f in files if f.extension == ".py")
            assert py_file.exported_symbols is not None
            symbols = set(py_file.exported_symbols)
            assert "my_function" in symbols
            assert "MyClass" in symbols

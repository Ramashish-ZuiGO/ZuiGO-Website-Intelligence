import os
import subprocess
import tempfile
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    DetectedTechnology,
    Project,
    RepositoryConnection,
    RepositoryFileIndex,
    RepositoryScanExecution,
)
from app.services.repository.framework_detector import FrameworkDetectionService
from app.services.repository.git_scanner import RepositoryScannerService
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_: JSONB, compiler: object, **kw: object) -> str:
    del type_, compiler, kw
    return "JSON"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_project(db: Session) -> Project:
    project = Project(name="RepoAPITest")
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def create_connection(
    db: Session,
    project: Project,
    local_root: str | None = None,
) -> RepositoryConnection:
    conn = RepositoryConnection(
        project_id=project.id,
        provider="local",
        display_name="Test Connection",
        local_root=local_root or "/tmp/test-repo",
        status="active",
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def create_scan_execution(
    db: Session,
    connection: RepositoryConnection,
    status: str = "completed",
) -> RepositoryScanExecution:
    scan = RepositoryScanExecution(
        id=uuid.uuid4(),
        connection_id=connection.id,
        status=status,
        started_at=datetime.now(UTC) if status != "queued" else None,
        completed_at=datetime.now(UTC) if status == "completed" else None,
        total_files_discovered=5,
        eligible_files=3,
        scanned_files=2,
        skipped_files=1,
        failed_files=0,
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


def create_file_index(  # noqa: E501
    db: Session, scan: RepositoryScanExecution, relative_path: str
) -> RepositoryFileIndex:
    ext = os.path.splitext(relative_path)[1]
    f = RepositoryFileIndex(
        id=uuid.uuid4(),
        scan_execution_id=scan.id,
        relative_path=relative_path,
        normalized_path=relative_path,
        extension=ext,
        detected_language=(  # noqa: E501
            "TypeScript" if ext in (".ts", ".tsx") else "Python" if ext == ".py" else None
        ),
        file_size=100,
        line_count=10,
        content_hash="abc",
        scan_status="scanned",
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


def create_technology(db: Session, scan: RepositoryScanExecution) -> DetectedTechnology:
    t = DetectedTechnology(
        id=uuid.uuid4(),
        scan_execution_id=scan.id,
        technology="Next.js",
        confidence="high",
        supporting_files=["package.json"],
        evidence={"dependencies": {"next": "14.0.0"}},
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def create_temp_git_repo() -> str:
    tmpdir = tempfile.mkdtemp()
    subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, timeout=30)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmpdir,
        capture_output=True,
        timeout=30,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmpdir,
        capture_output=True,
        timeout=30,
    )
    test_file = os.path.join(tmpdir, "index.tsx")
    with open(test_file, "w") as f:
        f.write("export default function Home() { return <div>Hello</div>; }")
    subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, timeout=30)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=tmpdir,
        capture_output=True,
        timeout=30,
    )
    return tmpdir


# ---------------------------------------------------------------------------
# Connection CRUD tests
# ---------------------------------------------------------------------------


class TestCreateConnection:
    def test_create_connection_success(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        payload = {
            "project_id": str(project.id),
            "provider": "local",
            "display_name": "My Repo",
            "local_root": os.path.expanduser("~"),
            "remote_url": None,
        }
        resp = client.post(
            f"/api/v1/projects/{project.id}/repository/connections",
            json=payload,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["provider"] == "local"
        assert data["display_name"] == "My Repo"
        assert data["project_id"] == str(project.id)
        assert "id" in data

    def test_create_connection_duplicate(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        create_connection(db_session, project)
        payload = {
            "project_id": str(project.id),
            "provider": "local",
            "display_name": "Duplicate",
            "local_root": os.path.expanduser("~"),
        }
        resp = client.post(
            f"/api/v1/projects/{project.id}/repository/connections",
            json=payload,
        )
        assert resp.status_code == 409

    def test_create_connection_project_not_found(self, client: TestClient) -> None:
        fake_id = uuid.uuid4()
        payload = {
            "project_id": str(fake_id),
            "provider": "local",
            "display_name": "Nope",
            "local_root": os.path.expanduser("~"),
        }
        resp = client.post(
            f"/api/v1/projects/{fake_id}/repository/connections",
            json=payload,
        )
        assert resp.status_code == 404


class TestListConnections:
    def test_list_connections(self, client: TestClient, db_session: Session) -> None:
        project_a = create_project(db_session)
        project_b = Project(name="Second Project")
        db_session.add(project_b)
        db_session.commit()
        db_session.refresh(project_b)
        create_connection(db_session, project_a, local_root="/tmp/a")
        create_connection(db_session, project_b, local_root="/tmp/b")

        resp = client.get(f"/api/v1/projects/{project_a.id}/repository/connections")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1

    def test_list_connections_empty(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        resp = client.get(f"/api/v1/projects/{project.id}/repository/connections")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_connections_project_not_found(self, client: TestClient) -> None:
        resp = client.get(f"/api/v1/projects/{uuid.uuid4()}/repository/connections")
        assert resp.status_code == 404


class TestGetConnection:
    def test_get_connection(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        conn = create_connection(db_session, project)
        resp = client.get(f"/api/v1/projects/{project.id}/repository/connections/{conn.id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == str(conn.id)

    def test_get_connection_not_found(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        resp = client.get(f"/api/v1/projects/{project.id}/repository/connections/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestUpdateConnection:
    def test_update_connection(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        conn = create_connection(db_session, project)
        resp = client.patch(
            f"/api/v1/projects/{project.id}/repository/connections/{conn.id}",
            json={"display_name": "Updated Name"},
        )
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "Updated Name"

    def test_update_connection_not_found(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        resp = client.patch(
            f"/api/v1/projects/{project.id}/repository/connections/{uuid.uuid4()}",
            json={"display_name": "Nope"},
        )
        assert resp.status_code == 404


class TestDeleteConnection:
    def test_delete_connection(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        conn = create_connection(db_session, project)
        resp = client.delete(f"/api/v1/projects/{project.id}/repository/connections/{conn.id}")
        assert resp.status_code == 204

        # Verify gone
        get_resp = client.get(f"/api/v1/projects/{project.id}/repository/connections/{conn.id}")
        assert get_resp.status_code == 404

    def test_delete_connection_not_found(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        resp = client.delete(f"/api/v1/projects/{project.id}/repository/connections/{uuid.uuid4()}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Validate endpoint
# ---------------------------------------------------------------------------


class TestValidateConnection:
    def test_validate_path_git_repo(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        repo_dir = create_temp_git_repo()
        try:
            resp = client.post(
                f"/api/v1/projects/{project.id}/repository/connections/{uuid.uuid4()}/validate",
                json={"local_root": repo_dir},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["is_git"] is True
            assert data["error_message"] is None
        finally:
            import shutil

            shutil.rmtree(repo_dir, ignore_errors=True)

    def test_validate_path_non_existent(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        resp = client.post(
            f"/api/v1/projects/{project.id}/repository/connections/{uuid.uuid4()}/validate",
            json={"local_root": "C:\\nonexistent_path_12345"},
        )
        # ApplicationError is re-raised and results in a 400 response
        assert resp.status_code == 400
        data = resp.json()
        assert "error" in data or "detail" in data


# ---------------------------------------------------------------------------
# Scan endpoints
# ---------------------------------------------------------------------------


class TestStartScan:
    def test_start_scan_success(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        repo_dir = create_temp_git_repo()
        try:
            conn = create_connection(db_session, project, local_root=repo_dir)

            def fake_scan(*args, **kwargs):
                pass

            def fake_detect(*args, **kwargs):
                return []

            with (
                patch.object(RepositoryScannerService, "scan_repository", fake_scan),
                patch.object(FrameworkDetectionService, "detect_frameworks", fake_detect),
            ):
                resp = client.post(
                    f"/api/v1/projects/{project.id}/repository/connections/{conn.id}/scans",
                    json={"connection_id": str(conn.id)},
                )
            assert resp.status_code == 202, resp.text
            data = resp.json()
            assert data["status"] == "completed"
            assert data["connection_id"] == str(conn.id)
        finally:
            import shutil

            shutil.rmtree(repo_dir, ignore_errors=True)

    def test_start_scan_not_active(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        conn = RepositoryConnection(
            project_id=project.id,
            provider="local",
            display_name="Pending",
            local_root="/tmp/pending",
            status="pending",
        )
        db_session.add(conn)
        db_session.commit()
        db_session.refresh(conn)

        resp = client.post(
            f"/api/v1/projects/{project.id}/repository/connections/{conn.id}/scans",
            json={"connection_id": str(conn.id)},
        )
        assert resp.status_code == 400

    def test_start_scan_connection_not_found(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        resp = client.post(
            f"/api/v1/projects/{project.id}/repository/connections/{uuid.uuid4()}/scans",
            json={"connection_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 404


class TestListScans:
    def test_list_scans(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        conn = create_connection(db_session, project)
        create_scan_execution(db_session, conn)
        create_scan_execution(db_session, conn, status="running")

        resp = client.get(f"/api/v1/projects/{project.id}/repository/connections/{conn.id}/scans")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    def test_list_scans_empty(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        conn = create_connection(db_session, project)
        resp = client.get(f"/api/v1/projects/{project.id}/repository/connections/{conn.id}/scans")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_list_scans_connection_not_found(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        resp = client.get(
            f"/api/v1/projects/{project.id}/repository/connections/{uuid.uuid4()}/scans"
        )
        assert resp.status_code == 404


class TestGetScan:
    def test_get_scan(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        conn = create_connection(db_session, project)
        scan = create_scan_execution(db_session, conn)

        resp = client.get(f"/api/v1/projects/{project.id}/repository/scans/{scan.id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == str(scan.id)

    def test_get_scan_not_found(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        resp = client.get(f"/api/v1/projects/{project.id}/repository/scans/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestListScanFiles:
    def test_list_files(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        conn = create_connection(db_session, project)
        scan = create_scan_execution(db_session, conn)
        create_file_index(db_session, scan, "pages/index.tsx")
        create_file_index(db_session, scan, "components/Button.tsx")

        resp = client.get(f"/api/v1/projects/{project.id}/repository/scans/{scan.id}/files")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    def test_list_files_with_extension_filter(  # noqa: E501
        self, client: TestClient, db_session: Session
    ) -> None:
        project = create_project(db_session)
        conn = create_connection(db_session, project)
        scan = create_scan_execution(db_session, conn)
        create_file_index(db_session, scan, "pages/index.tsx")
        create_file_index(db_session, scan, "api/main.py")

        resp = client.get(
            f"/api/v1/projects/{project.id}/repository/scans/{scan.id}/files",
            params={"extension": ".py"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["extension"] == ".py"

    def test_list_files_scan_not_found(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        resp = client.get(f"/api/v1/projects/{project.id}/repository/scans/{uuid.uuid4()}/files")
        assert resp.status_code == 404


class TestListScanTechnologies:
    def test_list_technologies(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        conn = create_connection(db_session, project)
        scan = create_scan_execution(db_session, conn)
        create_technology(db_session, scan)

        resp = client.get(f"/api/v1/projects/{project.id}/repository/scans/{scan.id}/technologies")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["technology"] == "Next.js"

    def test_list_technologies_empty(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        conn = create_connection(db_session, project)
        scan = create_scan_execution(db_session, conn)

        resp = client.get(f"/api/v1/projects/{project.id}/repository/scans/{scan.id}/technologies")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_technologies_scan_not_found(  # noqa: E501
        self, client: TestClient, db_session: Session
    ) -> None:
        project = create_project(db_session)
        resp = client.get(
            f"/api/v1/projects/{project.id}/repository/scans/{uuid.uuid4()}/technologies"
        )
        assert resp.status_code == 404


class TestGetScanSummary:
    def test_get_summary(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        conn = create_connection(db_session, project)
        scan = create_scan_execution(db_session, conn)

        resp = client.get(f"/api/v1/projects/{project.id}/repository/scans/{scan.id}/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_files_discovered"] == 5
        assert data["eligible_files"] == 3
        assert data["scanned_files"] == 2
        assert data["skipped_files"] == 1
        assert data["failed_files"] == 0

    def test_get_summary_with_technologies(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        conn = create_connection(db_session, project)
        scan = create_scan_execution(db_session, conn)
        create_technology(db_session, scan)

        resp = client.get(f"/api/v1/projects/{project.id}/repository/scans/{scan.id}/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_technologies"] == 1

    def test_get_summary_scan_not_found(self, client: TestClient, db_session: Session) -> None:
        project = create_project(db_session)
        resp = client.get(f"/api/v1/projects/{project.id}/repository/scans/{uuid.uuid4()}/summary")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Cross-resource error cases
# ---------------------------------------------------------------------------


class TestCrossResourceErrors:
    def test_scan_from_wrong_project_not_found(  # noqa: E501
        self, client: TestClient, db_session: Session
    ) -> None:
        project_a = create_project(db_session)
        project_b = Project(name="Other")
        db_session.add(project_b)
        db_session.commit()
        db_session.refresh(project_b)

        conn = create_connection(db_session, project_a)
        scan = create_scan_execution(db_session, conn)

        resp = client.get(f"/api/v1/projects/{project_b.id}/repository/scans/{scan.id}")
        assert resp.status_code == 404

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.accessibility import (
    AccessibilityAudit,
    AccessibilityFinding,
    AccessibilityNode,
    ManualReviewChecklist,
)
from app.models.project import Project
from app.models.website import Website
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

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


def get_test_db_session() -> Iterator[Session]:
    with factory() as session:
        yield session


@pytest.fixture(autouse=True)
def override_get_db():
    app.dependency_overrides[get_db] = get_test_db_session
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def db():
    return next(get_test_db_session())


@pytest.fixture
def seeded_db(db):
    p = Project(id=uuid.uuid4(), name="Test Project")
    db.add(p)
    w = Website(id=uuid.uuid4(), project_id=p.id, name="Test", url="https://example.com")
    db.add(w)
    db.flush()

    audit = AccessibilityAudit(
        id=uuid.uuid4(),
        execution_id=uuid.uuid4(),
        website_id=w.id,
        normalized_url="https://example.com",
        provider="axe-core",
        status="completed",
        violation_count=1,
        incomplete_count=1,
        pass_count=0,
        inapplicable_count=0,
        created_at=datetime.now(UTC),
    )
    db.add(audit)

    finding = AccessibilityFinding(
        id=uuid.uuid4(),
        audit_id=audit.id,
        result_type="violation",
        impact="critical",
        provider_rule_id="color-contrast",
        wcag_criteria=["wcag2aa", "wcag143"],
        title="Contrast issue",
        description="Fix contrast",
        help_url="https://example.com",
        created_at=datetime.now(UTC),
    )
    db.add(finding)

    node = AccessibilityNode(
        id=uuid.uuid4(),
        finding_id=finding.id,
        html_excerpt="<button></button>",
        normalized_selector="button",
        occurrence_fingerprint="fingerprint1",
        created_at=datetime.now(UTC),
    )
    db.add(node)

    checklist = ManualReviewChecklist(
        id=uuid.uuid4(),
        audit_id=audit.id,
        checklist_id="color-contrast",
        title="Check contrast",
        reason="Check contrast manually",
        created_at=datetime.now(UTC),
    )
    db.add(checklist)
    db.commit()
    return {"website_id": w.id, "audit_id": audit.id, "finding_id": finding.id}


@pytest.mark.anyio
async def test_get_website_accessibility_history(async_client: AsyncClient, seeded_db):
    website_id = seeded_db["website_id"]
    response = await async_client.get(f"/api/v1/websites/{website_id}/accessibility/history")
    assert response.status_code == 200
    assert len(response.json()["history"]) == 1


@pytest.mark.anyio
async def test_get_website_accessibility(async_client: AsyncClient, seeded_db):
    website_id = seeded_db["website_id"]
    response = await async_client.get(f"/api/v1/websites/{website_id}/accessibility")
    assert response.status_code == 200
    assert response.json()["audit"]["id"] == str(seeded_db["audit_id"])


@pytest.mark.anyio
async def test_findings_total_reflects_filtered_count(async_client: AsyncClient, seeded_db):
    """Regression: the paginated findings endpoint previously returned a
    hardcoded total of 100; the total must be the real filtered count."""
    website_id = seeded_db["website_id"]
    matching = await async_client.get(
        f"/api/v1/websites/{website_id}/accessibility/findings?result_type=violation"
    )
    assert matching.status_code == 200
    assert matching.json()["total"] == len(matching.json()["findings"]) == 1
    none_matching = await async_client.get(
        f"/api/v1/websites/{website_id}/accessibility/findings?result_type=pass"
    )
    assert none_matching.status_code == 200
    assert none_matching.json()["total"] == 0


@pytest.mark.anyio
async def test_get_website_accessibility_findings(async_client: AsyncClient, seeded_db):
    website_id = seeded_db["website_id"]
    response = await async_client.get(
        f"/api/v1/websites/{website_id}/accessibility/findings?result_type=violation&impact=critical"
    )
    assert response.status_code == 200
    assert len(response.json()["findings"]) == 1

    response = await async_client.get(
        f"/api/v1/websites/{website_id}/accessibility/findings?result_type=pass"
    )
    assert response.status_code == 200
    assert len(response.json()["findings"]) == 0


@pytest.mark.anyio
async def test_get_accessibility_finding_detail(async_client: AsyncClient, seeded_db):
    finding_id = seeded_db["finding_id"]
    response = await async_client.get(f"/api/v1/accessibility/findings/{finding_id}")
    assert response.status_code == 200
    assert response.json()["id"] == str(finding_id)
    assert len(response.json()["nodes"]) == 1


@pytest.mark.anyio
async def test_get_website_accessibility_manual_review(async_client: AsyncClient, seeded_db):
    website_id = seeded_db["website_id"]
    response = await async_client.get(f"/api/v1/websites/{website_id}/accessibility/manual-review")
    assert response.status_code == 200
    assert response.json()["checklist"] is not None


@pytest.mark.anyio
async def test_404_responses(async_client: AsyncClient):
    fake_id = uuid.uuid4()
    assert (await async_client.get(f"/api/v1/websites/{fake_id}/accessibility")).status_code == 404
    assert (
        await async_client.get(f"/api/v1/websites/{fake_id}/accessibility/history")
    ).status_code == 404
    assert (
        await async_client.get(f"/api/v1/websites/{fake_id}/accessibility/findings")
    ).status_code == 404
    assert (await async_client.get(f"/api/v1/accessibility/findings/{fake_id}")).status_code == 404
    assert (
        await async_client.get(f"/api/v1/websites/{fake_id}/accessibility/manual-review")
    ).status_code == 404


@pytest.mark.anyio
async def test_collect_accessibility(async_client: AsyncClient, seeded_db):
    run_id = uuid.uuid4()
    # Mocking collect is more complex since it talks to worker, we just test 404 for analysis-run
    response = await async_client.get(f"/api/v1/analysis-runs/{run_id}/accessibility")
    assert response.status_code == 404
    response = await async_client.post(f"/api/v1/analysis-runs/{run_id}/accessibility/collect")
    assert response.status_code == 404

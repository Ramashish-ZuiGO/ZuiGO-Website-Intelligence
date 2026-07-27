import uuid
from collections.abc import Iterator

import pytest
from app.db.base import Base
from app.models.accessibility import AccessibilityAudit
from app.models.website import Website
from app.services.accessibility_service import (
    create_fingerprint,
    normalize_impact,
    process_axe_results,
    process_lighthouse_accessibility,
    truncate_html,
)
from sqlalchemy import create_engine, event, select
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


def test_html_truncation_and_redaction():
    html = '<input type="password" value="mySecretPassword123">'
    redacted = truncate_html(html)
    assert 'value="***"' in redacted
    assert "mySecretPassword123" not in redacted


def test_create_fingerprint():
    fp1 = create_fingerprint("rule", "target", "fail")
    fp2 = create_fingerprint("rule", "target", "fail")
    assert fp1 == fp2


def test_normalize_impact():
    assert normalize_impact("critical") == "critical"
    assert normalize_impact("trivial") == "unknown"


def test_process_axe_results_idempotency_and_normalization(db_session):
    website_id = uuid.uuid4()
    from app.models.project import Project

    p = Project(id=uuid.uuid4(), name="Test Project")
    db_session.add(p)
    w = Website(id=website_id, project_id=p.id, name="Test", url="https://example.com")
    db_session.add(w)
    db_session.flush()

    execution_id = uuid.uuid4()
    axe_data = {"violations": [], "passes": [], "incomplete": [], "inapplicable": []}

    process_axe_results(db_session, execution_id, website_id, "https://example.com", axe_data)

    audit1 = db_session.execute(
        select(AccessibilityAudit).where(AccessibilityAudit.execution_id == execution_id)
    ).scalar_one_or_none()
    assert audit1 is not None

    # Idempotency
    process_axe_results(db_session, execution_id, website_id, "https://example.com", axe_data)
    audit2 = db_session.execute(
        select(AccessibilityAudit).where(AccessibilityAudit.execution_id == execution_id)
    ).scalar_one_or_none()
    assert audit2 is not None
    assert audit1.id == audit2.id
    assert audit1.created_at == audit2.created_at


def test_process_lighthouse_accessibility(db_session):
    website_id = uuid.uuid4()
    from app.models.project import Project

    p = Project(id=uuid.uuid4(), name="Test Project")
    db_session.add(p)
    w = Website(id=website_id, project_id=p.id, name="Test", url="https://example.com")
    db_session.add(w)
    db_session.flush()
    execution_id = uuid.uuid4()
    lh_data = {"categories": {"accessibility": {"auditRefs": []}}, "audits": {}}
    process_lighthouse_accessibility(
        db_session, execution_id, website_id, "https://example.com", lh_data
    )

    audit = db_session.execute(
        select(AccessibilityAudit).where(AccessibilityAudit.execution_id == execution_id)
    ).scalar_one_or_none()
    assert audit is not None

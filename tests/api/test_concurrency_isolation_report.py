"""Report/API page-selection isolation for concurrent same-website runs.

The report and progress endpoints resolve a run's pages with a run-scoped
``discovery_run_pages`` membership subquery, so a concurrent same-website run
that overwrites the shared ``website_pages.last_discovery_run_id`` pointer cannot
change which pages another run's report/coverage sees.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from app.db.base import Base
from app.models import DiscoveryRun, DiscoveryRunPage, Project, Website, WebsitePage
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        yield db


def _page(db: Session, website_id: uuid.UUID, url: str, discovery_id: uuid.UUID) -> uuid.UUID:
    now = datetime.now(UTC)
    page = WebsitePage(
        id=uuid.uuid4(),
        website_id=website_id,
        normalized_url=url,
        original_url=url,
        discovery_source="crawl",
        origin_relation="same_site",
        eligibility_status="eligible",
        last_discovery_run_id=discovery_id,
        first_discovered_at=now,
        last_discovered_at=now,
    )
    db.add(page)
    db.add(
        DiscoveryRunPage(
            id=uuid.uuid4(),
            discovery_run_id=discovery_id,
            website_page_id=page.id,
            eligibility_status="eligible",
            crawl_depth=0,
        )
    )
    return page.id


def _discovery(db: Session, website_id: uuid.UUID) -> uuid.UUID:
    run = DiscoveryRun(id=uuid.uuid4(), website_id=website_id, configuration={})
    db.add(run)
    return run.id


def test_report_page_query_is_run_scoped_under_pointer_overwrite(session: Session) -> None:
    project = Project(id=uuid.uuid4(), name="P")
    session.add(project)
    website = Website(id=uuid.uuid4(), project_id=project.id, url="https://c.test", name="c")
    session.add(website)
    session.flush()

    disc_a = _discovery(session, website.id)
    disc_b = _discovery(session, website.id)
    session.flush()

    a_pages = {_page(session, website.id, f"https://c.test/a{i}", disc_a) for i in range(3)}
    b_pages = {_page(session, website.id, f"https://c.test/b{i}", disc_b) for i in range(5)}
    session.flush()

    # Concurrent run B overwrites the shared pointer to itself.
    session.execute(
        update(WebsitePage)
        .where(WebsitePage.website_id == website.id)
        .values(last_discovery_run_id=disc_b)
    )
    session.flush()

    def run_scoped_pages(discovery_id: uuid.UUID) -> set[uuid.UUID]:
        return set(
            session.scalars(
                select(WebsitePage.id).where(
                    WebsitePage.id.in_(
                        select(DiscoveryRunPage.website_page_id).where(
                            DiscoveryRunPage.discovery_run_id == discovery_id
                        )
                    )
                )
            )
        )

    assert run_scoped_pages(disc_a) == a_pages  # unaffected by B's overwrite
    assert run_scoped_pages(disc_b) == b_pages
    assert run_scoped_pages(disc_a).isdisjoint(run_scoped_pages(disc_b))

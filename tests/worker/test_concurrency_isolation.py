"""Deterministic regression tests for concurrent same-website run isolation.

Root cause under test: ``website_pages`` is a shared per-(website, url) catalog
row whose ``last_discovery_run_id`` is a last-writer-wins pointer. When two
analyses of the same website ran concurrently, the second run's discovery
overwrote that pointer, so the first run's downstream selection (page analysis /
browser stage) queried ``last_discovery_run_id == its_own_id`` and found zero
eligible pages. The fix records each run's discovered pages in the run-scoped
``discovery_run_pages`` membership table, which no other run can mutate.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, insert, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from worker_app import db as worker_db
from worker_app.db import discovery_run_pages, website_pages
from worker_app.tasks.discovery import persist_pages
from worker_app.tasks.page_analysis import eligible_pages_for_run


@pytest.fixture
def factory() -> Iterator[sessionmaker]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    worker_db.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    yield maker
    worker_db.metadata.drop_all(engine)
    engine.dispose()


def _insert_page(
    session,
    *,
    website_id: uuid.UUID,
    normalized_url: str,
    discovery_run_id: uuid.UUID,
    eligibility_status: str = "eligible",
    crawl_depth: int = 0,
) -> uuid.UUID:
    """Insert a shared catalog page and this run's membership row."""
    now = datetime.now(UTC)
    page_id = uuid.uuid4()
    session.execute(
        insert(website_pages).values(
            id=page_id,
            website_id=website_id,
            normalized_url=normalized_url,
            original_url=normalized_url,
            page_type="content",
            page_type_confidence=90,
            page_type_indicators=[],
            classification_version="1.0.0",
            discovery_source="crawl",
            discovery_evidence=[],
            crawl_depth=crawl_depth,
            origin_relation="same_site",
            robots_status="allowed",
            eligibility_status=eligibility_status,
            last_discovery_run_id=discovery_run_id,
            latest_analysis_status="pending",
            page_analysis_level_1_status="pending",
            page_analysis_level_2_status="pending",
            first_discovered_at=now,
            last_discovered_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    session.execute(
        insert(discovery_run_pages).values(
            id=uuid.uuid4(),
            discovery_run_id=discovery_run_id,
            website_page_id=page_id,
            eligibility_status=eligibility_status,
            crawl_depth=crawl_depth,
            created_at=now,
        )
    )
    return page_id


def _overwrite_last_discovery_pointer(
    session, website_id: uuid.UUID, new_run_id: uuid.UUID
) -> None:
    """Simulate a concurrent run's discovery re-touching the shared catalog rows."""
    from sqlalchemy import update

    session.execute(
        update(website_pages)
        .where(website_pages.c.website_id == website_id)
        .values(last_discovery_run_id=new_run_id)
    )
    session.commit()


def _page_payload(normalized_url: str, eligibility_status: str = "eligible") -> dict:
    return {
        "normalized_url": normalized_url,
        "original_url": normalized_url,
        "final_url": normalized_url,
        "canonical_url": None,
        "page_title": "Page",
        "page_type": "content",
        "confidence_percent": 90,
        "indicators": [],
        "classification_version": "1.0.0",
        "discovery_source": "crawl",
        "discovery_evidence": [],
        "source_page_url": None,
        "crawl_depth": 0,
        "origin_relation": "same_site",
        "robots_status": "allowed",
        "eligibility_status": eligibility_status,
        "exclusion_reason": None,
        "skip_reason": None,
    }


# --- Item N: the exact observed regression -------------------------------------


def test_concurrent_run_never_sees_zero_eligible_pages(factory: sessionmaker) -> None:
    """Run A keeps its eligible pages even after Run B's discovery overwrites the
    shared last_discovery_run_id pointer to Run B."""
    website_id = uuid.uuid4()
    run_a = uuid.uuid4()
    run_b = uuid.uuid4()
    with factory() as session:
        for i in range(5):
            _insert_page(
                session,
                website_id=website_id,
                normalized_url=f"https://x.test/a{i}",
                discovery_run_id=run_a,
            )
        # Run B discovers the same site: its membership rows AND it overwrites the
        # shared pointer to itself (last-writer-wins).
        for i in range(5):
            _insert_page(
                session,
                website_id=website_id,
                normalized_url=f"https://x.test/a{i}",
                discovery_run_id=run_b,
            )
        _overwrite_last_discovery_pointer(session, website_id, run_b)

        pages_a = eligible_pages_for_run(session, run_a, website_id)
        pages_b = eligible_pages_for_run(session, run_b, website_id)

    # Before the fix Run A would have seen 0 (pointer overwritten to Run B).
    assert len(pages_a) == 5
    assert len(pages_b) == 5


# --- Items B / D: independent discovery contexts -------------------------------


def test_runs_have_independent_membership(factory: sessionmaker) -> None:
    website_id = uuid.uuid4()
    run_a = uuid.uuid4()
    run_b = uuid.uuid4()
    with factory() as session:
        a_ids = {
            _insert_page(
                session,
                website_id=website_id,
                normalized_url=f"https://y/a{i}",
                discovery_run_id=run_a,
            )
            for i in range(3)
        }
        b_ids = {
            _insert_page(
                session,
                website_id=website_id,
                normalized_url=f"https://y/b{i}",
                discovery_run_id=run_b,
            )
            for i in range(4)
        }
        session.commit()
        members_a = {
            r.website_page_id
            for r in session.execute(
                select(discovery_run_pages).where(discovery_run_pages.c.discovery_run_id == run_a)
            )
        }
        members_b = {
            r.website_page_id
            for r in session.execute(
                select(discovery_run_pages).where(discovery_run_pages.c.discovery_run_id == run_b)
            )
        }
    assert members_a == a_ids
    assert members_b == b_ids
    assert members_a.isdisjoint(members_b)


def test_run_a_eligibility_unchanged_while_run_b_marks_ineligible(factory: sessionmaker) -> None:
    """Run B recording a page as ineligible in its own membership must not change
    what Run A considers eligible."""
    website_id = uuid.uuid4()
    run_a = uuid.uuid4()
    run_b = uuid.uuid4()
    with factory() as session:
        _insert_page(
            session,
            website_id=website_id,
            normalized_url="https://z/shared",
            discovery_run_id=run_a,
        )
        # Run B's membership marks the same URL ineligible for itself.
        now = datetime.now(UTC)
        page = session.execute(
            select(website_pages.c.id).where(website_pages.c.normalized_url == "https://z/shared")
        ).scalar_one()
        session.execute(
            insert(discovery_run_pages).values(
                id=uuid.uuid4(),
                discovery_run_id=run_b,
                website_page_id=page,
                eligibility_status="excluded",
                crawl_depth=0,
                created_at=now,
            )
        )
        session.commit()
        pages_a = eligible_pages_for_run(session, run_a, website_id)
        pages_b = eligible_pages_for_run(session, run_b, website_id)
    assert len(pages_a) == 1  # still eligible for A
    assert len(pages_b) == 0  # excluded for B


# --- Items E / F: browser-stage-equivalent selection is run-scoped -------------


def test_browser_membership_join_selects_only_own_run(factory: sessionmaker) -> None:
    """Mirror the browser stage's fallback selection: join membership by run id.
    Each run's join must return only its own pages regardless of the shared
    pointer."""
    website_id = uuid.uuid4()
    run_a = uuid.uuid4()
    run_b = uuid.uuid4()
    with factory() as session:
        for i in range(2):
            _insert_page(
                session,
                website_id=website_id,
                normalized_url=f"https://b/a{i}",
                discovery_run_id=run_a,
            )
        for i in range(6):
            _insert_page(
                session,
                website_id=website_id,
                normalized_url=f"https://b/b{i}",
                discovery_run_id=run_b,
            )
        _overwrite_last_discovery_pointer(session, website_id, run_a)  # pointer now all run_a

        def membership_pages(run_id: uuid.UUID) -> list:
            return list(
                session.execute(
                    select(website_pages.c.id)
                    .join(
                        discovery_run_pages,
                        discovery_run_pages.c.website_page_id == website_pages.c.id,
                    )
                    .where(
                        discovery_run_pages.c.discovery_run_id == run_id,
                        discovery_run_pages.c.eligibility_status == "eligible",
                    )
                )
            )

        assert len(membership_pages(run_a)) == 2
        assert len(membership_pages(run_b)) == 6  # unaffected by pointer pointing to run_a


# --- discovery.persist_pages writes run-scoped membership ----------------------


def test_persist_pages_writes_run_scoped_membership(factory: sessionmaker) -> None:
    website_id = uuid.uuid4()
    run_a = uuid.uuid4()
    run_b = uuid.uuid4()
    with factory() as session:
        pages = [_page_payload(f"https://p/{i}") for i in range(4)]
        persist_pages(session, run_a, website_id, pages, None)
        # A concurrent run persists the same URLs; must not delete A's membership.
        persist_pages(session, run_b, website_id, pages, None)

        members_a = list(
            session.execute(
                select(discovery_run_pages).where(discovery_run_pages.c.discovery_run_id == run_a)
            )
        )
        members_b = list(
            session.execute(
                select(discovery_run_pages).where(discovery_run_pages.c.discovery_run_id == run_b)
            )
        )
    assert len(members_a) == 4
    assert len(members_b) == 4


def test_persist_pages_retry_only_rebuilds_own_run(factory: sessionmaker) -> None:
    """Re-running discovery for run A rebuilds only run A's membership, leaving a
    concurrent run B's membership intact."""
    website_id = uuid.uuid4()
    run_a = uuid.uuid4()
    run_b = uuid.uuid4()
    with factory() as session:
        persist_pages(
            session, run_a, website_id, [_page_payload(f"https://r/{i}") for i in range(3)], None
        )
        persist_pages(
            session, run_b, website_id, [_page_payload(f"https://r/{i}") for i in range(3)], None
        )
        # Retry discovery for A with a different page set.
        persist_pages(
            session, run_a, website_id, [_page_payload(f"https://r/{i}") for i in range(2)], None
        )

        members_a = list(
            session.execute(
                select(discovery_run_pages).where(discovery_run_pages.c.discovery_run_id == run_a)
            )
        )
        members_b = list(
            session.execute(
                select(discovery_run_pages).where(discovery_run_pages.c.discovery_run_id == run_b)
            )
        )
    assert len(members_a) == 2  # rebuilt
    assert len(members_b) == 3  # untouched by A's retry


# --- Item M: completed run's membership immutable while another run executes ----


def test_completed_run_membership_immutable_under_new_run(factory: sessionmaker) -> None:
    website_id = uuid.uuid4()
    run_a = uuid.uuid4()
    run_b = uuid.uuid4()
    with factory() as session:
        persist_pages(
            session, run_a, website_id, [_page_payload(f"https://m/{i}") for i in range(5)], None
        )
        before = sorted(
            str(r.website_page_id)
            for r in session.execute(
                select(discovery_run_pages).where(discovery_run_pages.c.discovery_run_id == run_a)
            )
        )
        # Run B discovers (larger set) and overwrites the shared pointer.
        persist_pages(
            session, run_b, website_id, [_page_payload(f"https://m/{i}") for i in range(9)], None
        )
        _overwrite_last_discovery_pointer(session, website_id, run_b)
        after = sorted(
            str(r.website_page_id)
            for r in session.execute(
                select(discovery_run_pages).where(discovery_run_pages.c.discovery_run_id == run_a)
            )
        )
    assert before == after  # Run A's membership unchanged by Run B
    assert len(after) == 5

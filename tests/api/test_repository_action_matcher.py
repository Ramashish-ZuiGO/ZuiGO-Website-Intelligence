import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from app.db.base import Base
from app.models import (
    ActionGenerationExecution,
    ActionItem,
    MappingStrategy,
    MatchConfidence,
    Project,
    RepositoryConnection,
    RepositoryFileIndex,
    RepositoryScanExecution,
    Website,
    WebsitePage,
)
from app.services.repository.action_matcher import ActionToCodeMatcherService
from sqlalchemy import create_engine, event, select
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_project(db: Session) -> Project:
    project = Project(name="MatcherTest")
    db.add(project)
    db.flush()
    return project


def create_connection(
    db: Session, project: Project, local_root: str = "/tmp/repo"
) -> RepositoryConnection:  # noqa: E501
    conn = RepositoryConnection(
        project_id=project.id,
        provider="local",
        display_name="Test Repo",
        local_root=local_root,
        status="active",
    )
    db.add(conn)
    db.flush()
    return conn


def create_scan_execution(db: Session, connection: RepositoryConnection) -> RepositoryScanExecution:
    scan = RepositoryScanExecution(
        id=uuid.uuid4(),
        connection_id=connection.id,
        status="completed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        total_files_discovered=0,
        eligible_files=0,
        scanned_files=0,
        skipped_files=0,
        failed_files=0,
    )
    db.add(scan)
    db.flush()
    return scan


def create_file_index(
    db: Session,
    scan_execution: RepositoryScanExecution,
    relative_path: str,
    normalized_path: str | None = None,
    exported_symbols: list[str] | None = None,
    framework_role: str | None = None,
    first_lines: str | None = None,
) -> RepositoryFileIndex:
    file_entry = RepositoryFileIndex(
        id=uuid.uuid4(),
        scan_execution_id=scan_execution.id,
        relative_path=relative_path,
        normalized_path=normalized_path or relative_path,
        extension=".tsx" if ".tsx" in relative_path else ".ts" if ".ts" in relative_path else ".py",
        detected_language="TypeScript" if ".ts" in relative_path else "Python",
        file_size=100,
        line_count=10,
        content_hash="abc123",
        scan_status="scanned",
        exported_symbols=exported_symbols,
        framework_role=framework_role,
        first_lines=first_lines,
    )
    db.add(file_entry)
    db.flush()
    return file_entry


def create_generation_execution(db: Session, website: Website) -> ActionGenerationExecution:
    gen = ActionGenerationExecution(
        id=uuid.uuid4(),
        website_id=website.id,
        page_analysis_execution_id=uuid.uuid4(),
        status="completed",
    )
    db.add(gen)
    db.flush()
    return gen


def create_website_and_page(
    db: Session, project: Project, path: str
) -> tuple[Website, WebsitePage]:
    website = Website(project_id=project.id, url=f"https://example.com/{path}", name="Example")
    db.add(website)
    db.flush()

    page = WebsitePage(
        website_id=website.id,
        normalized_url=f"https://example.com/{path}",
        original_url=f"https://example.com/{path}",
        page_type="unknown",
        page_type_confidence=80,
        page_type_indicators=[],
        classification_version="1.0.0",
        discovery_source="sitemap",
        discovery_evidence=[],
        crawl_depth=1,
        origin_relation="same_origin",
        robots_status="allowed",
        eligibility_status="eligible",
        latest_analysis_status="pending",
        page_analysis_level_1_status="completed",
        first_discovered_at=datetime.now(UTC),
        last_discovered_at=datetime.now(UTC),
    )
    db.add(page)
    db.flush()
    return website, page


def create_action_item(
    db: Session,
    generation_execution: ActionGenerationExecution,
    website: Website,
    website_page: WebsitePage,
    *,
    final_url: str | None = None,
    requested_url: str | None = None,
    issue_title: str = "Fix missing alt text on hero image",
    action_location: str = "components/HeroBanner",
    responsible_area: str = "frontend",
    responsible_role: str = "developer",
) -> ActionItem:
    item = ActionItem(
        id=uuid.uuid4(),
        generation_execution_id=generation_execution.id,
        website_id=website.id,
        website_page_id=website_page.id,
        source_finding_identity="test-finding-001",
        requested_url=requested_url or "https://example.com/page",
        final_url=final_url or "https://example.com/page",
        page_title="Test Page",
        issue_title=issue_title,
        issue_category="accessibility",
        severity="high",
        priority_score=50,
        priority_formula_version="1.0.0",
        priority_components={},
        confidence="medium",
        confidence_percent=80,
        estimated_effort="medium",
        business_impact="Improves accessibility compliance",
        responsible_area=responsible_area,
        responsible_role=responsible_role,
        action_location=action_location,
        why_this_matters="Alt text improves accessibility",
        exact_correction='<img alt="descriptive text" src="..."/>',
        implementation_steps="1. Find component\n2. Add alt prop",
        verification_steps="1. Check with axe",
        expected_result="Images will have alt text",
        limitations="None",
        evidence_summary={},
        source_audit="lighthouse",
        status="open",
    )
    db.add(item)
    db.flush()
    return item


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestActionToCodeMatcherService:
    def test_match_by_page_url(self, db_session: Session) -> None:
        project = create_project(db_session)
        conn = create_connection(db_session, project)
        scan = create_scan_execution(db_session, conn)
        website, page = create_website_and_page(db_session, project, "about")
        gen = create_generation_execution(db_session, website)

        create_file_index(
            db_session,
            scan,
            relative_path="pages/about.tsx",
            normalized_path="pages/about.tsx",
        )
        create_file_index(
            db_session,
            scan,
            relative_path="pages/contact.tsx",
            normalized_path="pages/contact.tsx",
        )

        create_action_item(
            db_session,
            gen,
            website,
            page,
            final_url="https://example.com/about",
        )

        matching_id = uuid.uuid4()
        service = ActionToCodeMatcherService(db_session)
        result = service.match_actions(
            matching_execution_id=matching_id,
            connection_id=conn.id,
            scan_execution_id=scan.id,
            generation_execution_id=gen.id,
        )

        assert result.status == "completed"
        assert result.total_actions == 1
        assert result.located_actions == 1
        assert result.unlocated_actions == 0

        from app.models.repository import ActionRepositoryMatch

        url_matches = list(
            db_session.scalars(
                select(ActionRepositoryMatch).where(
                    ActionRepositoryMatch.matching_execution_id == matching_id,
                    ActionRepositoryMatch.mapping_strategy
                    == MappingStrategy.PAGE_URL_TO_NEXTJS_ROUTE,
                )
            )
        )
        assert len(url_matches) == 1
        assert url_matches[0].match_confidence == MatchConfidence.HIGH
        assert "about" in (url_matches[0].relative_path or "")

    def test_match_by_component_name(self, db_session: Session) -> None:
        project = create_project(db_session)
        conn = create_connection(db_session, project)
        scan = create_scan_execution(db_session, conn)
        website, page = create_website_and_page(db_session, project, "home")
        gen = create_generation_execution(db_session, website)

        create_file_index(
            db_session,
            scan,
            relative_path="components/HeroBanner.tsx",
            normalized_path="components/HeroBanner.tsx",
            exported_symbols=["HeroBanner"],
        )

        create_action_item(
            db_session,
            gen,
            website,
            page,
            action_location="components/HeroBanner",
        )

        matching_id = uuid.uuid4()
        service = ActionToCodeMatcherService(db_session)
        result = service.match_actions(
            matching_execution_id=matching_id,
            connection_id=conn.id,
            scan_execution_id=scan.id,
            generation_execution_id=gen.id,
        )

        assert result.status == "completed"
        assert result.located_actions == 1

        from app.models.repository import ActionRepositoryMatch

        matches = list(
            db_session.scalars(
                select(ActionRepositoryMatch).where(
                    ActionRepositoryMatch.matching_execution_id == matching_id,
                    ActionRepositoryMatch.match_confidence != MatchConfidence.UNLOCATED,
                )
            )
        )
        assert len(matches) >= 1
        # Component match via exported symbol or file name
        assert any(m.mapping_strategy == MappingStrategy.COMPONENT_NAME_MATCH for m in matches)

    def test_match_by_responsible_area(self, db_session: Session) -> None:
        project = create_project(db_session)
        conn = create_connection(db_session, project)
        scan = create_scan_execution(db_session, conn)
        website, page = create_website_and_page(db_session, project, "dashboard")
        gen = create_generation_execution(db_session, website)

        create_file_index(
            db_session,
            scan,
            relative_path="components/Navbar.tsx",
            normalized_path="components/Navbar.tsx",
        )
        create_file_index(
            db_session,
            scan,
            relative_path="api/routes/users.py",
            normalized_path="api/routes/users.py",
        )

        create_action_item(
            db_session,
            gen,
            website,
            page,
            responsible_area="backend",
        )

        matching_id = uuid.uuid4()
        service = ActionToCodeMatcherService(db_session)
        result = service.match_actions(
            matching_execution_id=matching_id,
            connection_id=conn.id,
            scan_execution_id=scan.id,
            generation_execution_id=gen.id,
        )

        assert result.status == "completed"
        assert result.located_actions == 1

        from app.models.repository import ActionRepositoryMatch

        matches = list(
            db_session.scalars(
                select(ActionRepositoryMatch).where(
                    ActionRepositoryMatch.matching_execution_id == matching_id,
                    ActionRepositoryMatch.match_confidence != MatchConfidence.UNLOCATED,
                )
            )
        )
        assert len(matches) >= 1
        assert any(
            m.mapping_strategy == MappingStrategy.FRAMEWORK_CONVENTION_MATCH for m in matches
        )

    def test_unlocated_action_gets_unlocated_confidence(self, db_session: Session) -> None:
        project = create_project(db_session)
        conn = create_connection(db_session, project)
        scan = create_scan_execution(db_session, conn)
        website, page = create_website_and_page(db_session, project, "orphan")
        gen = create_generation_execution(db_session, website)

        # No file index entries -> no possible matches
        create_action_item(
            db_session,
            gen,
            website,
            page,
            final_url="https://example.com/nonexistent",
            action_location="no/such/component",
            responsible_area="nowhere",
        )

        matching_id = uuid.uuid4()
        service = ActionToCodeMatcherService(db_session)
        result = service.match_actions(
            matching_execution_id=matching_id,
            connection_id=conn.id,
            scan_execution_id=scan.id,
            generation_execution_id=gen.id,
        )

        assert result.status == "completed"
        assert result.total_actions == 1
        assert result.located_actions == 0
        assert result.unlocated_actions == 1

        from app.models.repository import ActionRepositoryMatch

        unlocated_matches = list(
            db_session.scalars(
                select(ActionRepositoryMatch).where(
                    ActionRepositoryMatch.matching_execution_id == matching_id,
                    ActionRepositoryMatch.match_confidence == MatchConfidence.UNLOCATED,
                )
            )
        )
        assert len(unlocated_matches) == 1
        assert unlocated_matches[0].relative_path is None

    def test_multiple_strategies_can_match_same_action(self, db_session: Session) -> None:
        project = create_project(db_session)
        conn = create_connection(db_session, project)
        scan = create_scan_execution(db_session, conn)
        website, page = create_website_and_page(db_session, project, "pricing")
        gen = create_generation_execution(db_session, website)

        # File that matches via page URL
        create_file_index(
            db_session,
            scan,
            relative_path="pages/pricing.tsx",
            normalized_path="pages/pricing.tsx",
        )
        # File that matches via component name (different file, avoids dedup)
        create_file_index(
            db_session,
            scan,
            relative_path="components/PricingPage.tsx",
            normalized_path="components/PricingPage.tsx",
            exported_symbols=["PricingPage"],
        )

        create_action_item(
            db_session,
            gen,
            website,
            page,
            final_url="https://example.com/pricing",
            action_location="components/PricingPage",
        )

        matching_id = uuid.uuid4()
        service = ActionToCodeMatcherService(db_session)
        result = service.match_actions(
            matching_execution_id=matching_id,
            connection_id=conn.id,
            scan_execution_id=scan.id,
            generation_execution_id=gen.id,
        )

        assert result.status == "completed"
        assert result.located_actions == 1

        from app.models.repository import ActionRepositoryMatch

        all_matches = list(
            db_session.scalars(
                select(ActionRepositoryMatch).where(
                    ActionRepositoryMatch.matching_execution_id == matching_id,
                )
            )
        )
        strategies = {m.mapping_strategy for m in all_matches}
        assert MappingStrategy.PAGE_URL_TO_NEXTJS_ROUTE in strategies
        assert MappingStrategy.COMPONENT_NAME_MATCH in strategies

    def test_empty_action_list_returns_zero_matches(self, db_session: Session) -> None:
        project = create_project(db_session)
        conn = create_connection(db_session, project)
        scan = create_scan_execution(db_session, conn)
        website, page = create_website_and_page(db_session, project, "empty")
        gen = create_generation_execution(db_session, website)

        create_file_index(
            db_session,
            scan,
            relative_path="pages/something.tsx",
            normalized_path="pages/something.tsx",
        )

        # No action items created

        matching_id = uuid.uuid4()
        service = ActionToCodeMatcherService(db_session)
        result = service.match_actions(
            matching_execution_id=matching_id,
            connection_id=conn.id,
            scan_execution_id=scan.id,
            generation_execution_id=gen.id,
        )

        assert result.status == "completed"
        assert result.total_actions == 0
        assert result.located_actions == 0
        assert result.unlocated_actions == 0

    def test_idempotent_re_run_returns_same_execution(self, db_session: Session) -> None:
        project = create_project(db_session)
        conn = create_connection(db_session, project)
        scan = create_scan_execution(db_session, conn)
        website, page = create_website_and_page(db_session, project, "idempotent")
        gen = create_generation_execution(db_session, website)

        create_file_index(
            db_session,
            scan,
            relative_path="pages/idempotent.tsx",
            normalized_path="pages/idempotent.tsx",
        )

        create_action_item(
            db_session,
            gen,
            website,
            page,
            final_url="https://example.com/idempotent",
        )

        matching_id = uuid.uuid4()
        service = ActionToCodeMatcherService(db_session)

        result1 = service.match_actions(
            matching_execution_id=matching_id,
            connection_id=conn.id,
            scan_execution_id=scan.id,
            generation_execution_id=gen.id,
        )
        result2 = service.match_actions(
            matching_execution_id=matching_id,
            connection_id=conn.id,
            scan_execution_id=scan.id,
            generation_execution_id=gen.id,
        )

        assert result1.id == result2.id
        assert result2.status == "completed"

    def test_match_with_exported_symbol_gets_high_confidence(self, db_session: Session) -> None:
        project = create_project(db_session)
        conn = create_connection(db_session, project)
        scan = create_scan_execution(db_session, conn)
        website, page = create_website_and_page(db_session, project, "symbols")
        gen = create_generation_execution(db_session, website)

        # File basename does NOT contain the search term "contactform",
        # so the first loop in _match_by_component_name misses it.
        # But exported_symbols=["ContactForm"] triggers the second loop → HIGH.
        create_file_index(
            db_session,
            scan,
            relative_path="forms/contact.tsx",
            normalized_path="forms/contact.tsx",
            exported_symbols=["ContactForm"],
            framework_role="component",
        )

        create_action_item(
            db_session,
            gen,
            website,
            page,
            final_url="https://example.com/contact",
            action_location="components/ContactForm",
            issue_title="ContactForm missing validation",
        )

        matching_id = uuid.uuid4()
        service = ActionToCodeMatcherService(db_session)
        result = service.match_actions(
            matching_execution_id=matching_id,
            connection_id=conn.id,
            scan_execution_id=scan.id,
            generation_execution_id=gen.id,
        )

        assert result.status == "completed"
        assert result.located_actions == 1

        from app.models.repository import ActionRepositoryMatch

        high_matches = list(
            db_session.scalars(
                select(ActionRepositoryMatch).where(
                    ActionRepositoryMatch.matching_execution_id == matching_id,
                    ActionRepositoryMatch.match_confidence == MatchConfidence.HIGH,
                )
            )
        )
        assert len(high_matches) >= 1

from collections.abc import Iterator
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import uuid4

import app.models  # noqa: F401
import pytest
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.accessibility import AccessibilityAudit, AccessibilityFinding
from app.models.analysis_result import AnalysisResult
from app.models.analysis_run import AnalysisRun, AnalysisStatus
from app.models.discovery_run import DiscoveryRun, DiscoveryStatus
from app.models.page_analysis_run import PageAnalysisRun, PageAnalysisStatus
from app.models.performance import PerformanceSnapshot
from app.models.project import Project
from app.models.site_diagnostic import (
    SiteDiagnosticExecution,
    SiteDiagnosticExecutionStatusEnum,
    SiteDiagnosticFinding,
)
from app.models.website import Website
from app.models.website_page import WebsitePage
from app.services.site_diagnostics_service import (
    EXACT_CONTENT_SIGNATURE_METHOD,
    MINIMUM_USABLE_CONTENT_LENGTH,
    NEAR_DUPLICATE_SIMILARITY_METHOD,
    NEAR_DUPLICATE_SIMILARITY_THRESHOLD,
    SiteDiagnosticsService,
)
from fastapi.testclient import TestClient
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


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _create_run(db: Session, *, suffix: str = "") -> tuple[Website, AnalysisRun]:
    project = Project(name=f"Diagnostics project {suffix}")
    db.add(project)
    db.flush()
    website = Website(
        project_id=project.id,
        url=f"https://{suffix or 'example'}.test",
        name="Diagnostics site",
        profile_id="global_general",
    )
    db.add(website)
    db.flush()
    run = AnalysisRun(
        website_id=website.id,
        status=AnalysisStatus.COMPLETED,
        progress_percent=100,
        profile_id="global_general",
        profile_version="1.0.0",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()
    return website, run


def _unique_content(label: str) -> str:
    return " ".join([f"{label}uniqueword"] * (MINIMUM_USABLE_CONTENT_LENGTH // 5))


def _add_page(
    db: Session,
    website: Website,
    run: AnalysisRun,
    path: str,
    *,
    title: str | None = "Unique title",
    description: str | None = "Unique description",
    h1_count: int = 1,
    language: str | None = "en",
    content: str | None = None,
    template_signature: str | None = None,
    status: PageAnalysisStatus | None = PageAnalysisStatus.COMPLETED,
) -> tuple[WebsitePage, PageAnalysisRun | None]:
    url = f"{website.url}{path}"
    page = WebsitePage(
        website_id=website.id,
        normalized_url=url,
        original_url=url,
        page_title=title,
        page_type="content",
        page_type_confidence=100,
        discovery_source="test_fixture",
        discovery_evidence=[{"source": "persisted_test_evidence"}],
        origin_relation="internal",
        eligibility_status="eligible",
        first_discovered_at=datetime.now(UTC),
        last_discovered_at=datetime.now(UTC),
    )
    db.add(page)
    db.flush()
    if status is None:
        return page, None

    evidence: dict[str, str] = {}
    if content is not None:
        evidence["content_text"] = content
    if template_signature is not None:
        evidence["template_signature"] = template_signature
    page_run = PageAnalysisRun(
        website_page_id=page.id,
        page_analysis_execution_id=uuid4(),
        analysis_level=1,
        status=status,
        requested_url=url,
        final_url=url,
        page_title=title,
        meta_description=description,
        heading_structure=[{"level": 1, "text": f"Heading {index}"} for index in range(h1_count)],
        language=language,
        evidence=evidence,
        deep_analysis_run_id=run.id,
    )
    db.add(page_run)
    db.flush()
    return page, page_run


def _findings(
    db: Session,
    execution: SiteDiagnosticExecution,
    rule_id: str,
) -> list[SiteDiagnosticFinding]:
    return list(
        db.execute(
            select(SiteDiagnosticFinding)
            .where(
                SiteDiagnosticFinding.execution_id == execution.id,
                SiteDiagnosticFinding.rule_id == rule_id,
            )
            .order_by(SiteDiagnosticFinding.id)
        )
        .scalars()
        .all()
    )


def _add_complete_discovery(
    db: Session,
    website: Website,
) -> DiscoveryRun:
    discovery = DiscoveryRun(
        website_id=website.id,
        status=DiscoveryStatus.COMPLETED,
        progress_percent=100,
        configuration={"max_crawl_depth": 5},
        urls_discovered=1,
        urls_unique=1,
        urls_eligible=1,
        urls_excluded=0,
        urls_skipped=0,
        sitemap_count=1,
        crawl_limit_reached=False,
        maximum_depth_reached=5,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db.add(discovery)
    db.flush()
    return discovery


def _finding_subtypes(
    db: Session,
    execution: SiteDiagnosticExecution,
    rule_id: str,
) -> set[str]:
    return {
        occurrence.context["diagnostic_subtype"]
        for finding in _findings(db, execution, rule_id)
        for occurrence in finding.occurrences
        if "diagnostic_subtype" in occurrence.context
    }


def test_metadata_diagnostics_use_page_evidence_without_accessibility_findings(
    db_session: Session,
) -> None:
    website, run = _create_run(db_session)
    _add_page(
        db_session,
        website,
        run,
        "/missing",
        title=None,
        description=None,
        h1_count=0,
        language="en",
        content=_unique_content("missing"),
    )
    _add_page(
        db_session,
        website,
        run,
        "/duplicate-a",
        title="  Shared\u00a0Title ",
        description=" Shared description ",
        h1_count=2,
        language="en",
        content=_unique_content("duplicatea"),
    )
    _add_page(
        db_session,
        website,
        run,
        "/duplicate-b",
        title="shared title",
        description="shared\u00a0description",
        h1_count=1,
        language="fr",
        content=_unique_content("duplicateb"),
    )
    db_session.commit()

    execution = SiteDiagnosticsService(db_session).execute_diagnostics(
        run.id,
        idempotency_key="metadata",
    )

    assert len(_findings(db_session, execution, "missing_title")) == 1
    assert len(_findings(db_session, execution, "duplicate_title_group")) == 1
    assert len(_findings(db_session, execution, "missing_meta_description")) == 1
    assert len(_findings(db_session, execution, "duplicate_meta_description_group")) == 1
    assert len(_findings(db_session, execution, "missing_h1")) == 1
    assert len(_findings(db_session, execution, "multiple_h1")) == 1
    language_finding = _findings(
        db_session,
        execution,
        "inconsistent_language_declaration",
    )[0]
    assert language_finding.affected_page_count == 3
    assert language_finding.occurrence_count == 3


def test_analysis_result_is_selected_as_persisted_primary_page_evidence(
    db_session: Session,
) -> None:
    website, run = _create_run(db_session)
    page, _ = _add_page(
        db_session,
        website,
        run,
        "/",
        title=None,
        status=None,
    )
    result = AnalysisResult(
        analysis_run_id=run.id,
        requested_url=page.normalized_url,
        final_url=page.normalized_url,
        page_title=None,
        meta_description="Primary page description",
        analysis_started_at=datetime.now(UTC),
        analysis_completed_at=datetime.now(UTC),
        raw_lighthouse_data={},
        raw_playwright_data={
            "h1_texts": ["Primary heading"],
            "html_language": "en",
        },
    )
    db_session.add(result)
    db_session.commit()

    execution = SiteDiagnosticsService(db_session).execute_diagnostics(
        run.id,
        idempotency_key="analysis-result",
    )

    missing_title = _findings(db_session, execution, "missing_title")[0]
    assert missing_title.occurrence_count == 1
    assert missing_title.occurrences[0].evidence_reference == f"analysis_result:{result.id}"
    assert not _findings(db_session, execution, "missing_h1")
    assert execution.evidence_coverage_numerator == 1
    assert (
        execution.partial_completion_metadata["evidence_field_coverage"]["content_signature"][
            "numerator"
        ]
        == 0
    )


def test_duplicate_groups_do_not_merge_unrelated_values(db_session: Session) -> None:
    website, run = _create_run(db_session)
    for index, (title, description) in enumerate(
        (
            ("Group A", "Description A"),
            (" group a ", "description a"),
            ("Group B", "Description B"),
            ("group b", "description b"),
        )
    ):
        _add_page(
            db_session,
            website,
            run,
            f"/group-{index}",
            title=title,
            description=description,
            content=_unique_content(f"group{index}"),
        )
    db_session.commit()

    execution = SiteDiagnosticsService(db_session).execute_diagnostics(
        run.id,
        idempotency_key="separate-groups",
    )

    title_groups = _findings(db_session, execution, "duplicate_title_group")
    description_groups = _findings(
        db_session,
        execution,
        "duplicate_meta_description_group",
    )
    assert len(title_groups) == 2
    assert len(description_groups) == 2
    assert sorted(finding.occurrence_count for finding in title_groups) == [2, 2]
    assert sorted(finding.occurrence_count for finding in description_groups) == [2, 2]
    assert len({finding.evidence_summary for finding in title_groups}) == 2


def test_content_signatures_group_exact_near_and_unavailable_evidence(
    db_session: Session,
) -> None:
    website, run = _create_run(db_session)
    exact = (
        "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu "
        "nu xi omicron pi rho sigma tau upsilon phi chi psi omega"
    )
    near_a = (
        "orchard apple pear peach plum cherry apricot citrus lemon lime orange "
        "grape melon berry garden harvest basket market seasonal local fresh"
    )
    near_b = f"{near_a} organic"
    _add_page(db_session, website, run, "/exact-a", content=exact)
    _add_page(db_session, website, run, "/exact-b", content=exact)
    _add_page(db_session, website, run, "/near-a", content=near_a)
    _add_page(db_session, website, run, "/near-b", content=near_b)
    _add_page(db_session, website, run, "/short", content="too short")
    _, signature_run_a = _add_page(db_session, website, run, "/signature-a", content=None)
    _, signature_run_b = _add_page(db_session, website, run, "/signature-b", content=None)
    assert signature_run_a is not None
    assert signature_run_b is not None
    stored_signature = "a" * 64
    signature_run_a.evidence = {
        "content_signature": stored_signature,
        "content_signature_method": EXACT_CONTENT_SIGNATURE_METHOD,
    }
    signature_run_b.evidence = {
        "content_signature": stored_signature,
        "content_signature_method": EXACT_CONTENT_SIGNATURE_METHOD,
    }
    db_session.commit()

    execution = SiteDiagnosticsService(db_session).execute_diagnostics(
        run.id,
        idempotency_key="content",
    )

    exact_findings = _findings(db_session, execution, "exact_duplicate_content_group")
    near_finding = _findings(db_session, execution, "near_duplicate_content_group")[0]
    unavailable = _findings(
        db_session,
        execution,
        "unavailable_content_signature_evidence",
    )[0]
    assert len(exact_findings) == 2
    assert all(finding.occurrence_count == 2 for finding in exact_findings)
    assert all(
        EXACT_CONTENT_SIGNATURE_METHOD in finding.evidence_summary for finding in exact_findings
    )
    assert any(stored_signature[:12] in finding.evidence_summary for finding in exact_findings)
    assert near_finding.occurrence_count == 2
    assert NEAR_DUPLICATE_SIMILARITY_METHOD in near_finding.evidence_summary
    assert f"{NEAR_DUPLICATE_SIMILARITY_THRESHOLD:.2f}" in near_finding.evidence_summary
    assert unavailable.occurrence_count == 1
    assert unavailable.confidence == "unavailable"
    assert unavailable.occurrences[0].supporting_evidence["content_signature_status"] == (
        "content_below_minimum_length"
    )


def test_pattern_classification_distinguishes_repeated_section_and_template(
    db_session: Session,
) -> None:
    website, run = _create_run(db_session)
    _add_page(
        db_session,
        website,
        run,
        "/products/one",
        title=None,
        description="Product one",
        content=_unique_content("productone"),
        template_signature="product-template-v1",
    )
    _add_page(
        db_session,
        website,
        run,
        "/products/two",
        title=None,
        description="Product two",
        content=_unique_content("producttwo"),
        template_signature="product-template-v1",
    )
    _add_page(
        db_session,
        website,
        run,
        "/blog/one",
        title="Blog one",
        description="Shared blog description",
        content=_unique_content("blogone"),
    )
    _add_page(
        db_session,
        website,
        run,
        "/blog/two",
        title="Blog two",
        description="shared blog description",
        content=_unique_content("blogtwo"),
    )
    _add_page(
        db_session,
        website,
        run,
        "/alpha/one",
        title="Shared cross-section title",
        description="Alpha description",
        content=_unique_content("alphaone"),
    )
    _add_page(
        db_session,
        website,
        run,
        "/beta/two",
        title="shared cross-section title",
        description="Beta description",
        content=_unique_content("betatwo"),
    )
    db_session.commit()

    execution = SiteDiagnosticsService(db_session).execute_diagnostics(
        run.id,
        idempotency_key="patterns",
    )

    template = _findings(db_session, execution, "template_issue_pattern")
    section = _findings(db_session, execution, "section_issue_pattern")
    repeated = _findings(db_session, execution, "repeated_issue_pattern")
    assert any(
        finding.occurrences[0].context["source_rule_id"] == "missing_title" for finding in template
    )
    assert all("likely, not proven" in finding.evidence_summary for finding in template)
    assert any(
        finding.occurrences[0].context["source_rule_id"] == "duplicate_meta_description_group"
        for finding in section
    )
    assert any(
        finding.occurrences[0].context["source_rule_id"] == "duplicate_title_group"
        for finding in repeated
    )


def test_all_occurrences_and_execution_counts_are_preserved(db_session: Session) -> None:
    website, run = _create_run(db_session)
    page_count = 55
    for index in range(page_count):
        _add_page(
            db_session,
            website,
            run,
            f"/bulk/{index}",
            title=None,
            description=f"Description {index}",
            content=_unique_content(f"bulk{index}"),
        )
    db_session.commit()

    execution = SiteDiagnosticsService(db_session).execute_diagnostics(
        run.id,
        idempotency_key="all-occurrences",
    )

    missing_title = _findings(db_session, execution, "missing_title")[0]
    assert missing_title.affected_page_count == page_count
    assert missing_title.occurrence_count == page_count
    assert len(missing_title.occurrences) == page_count
    assert execution.total_page_count == page_count
    assert execution.processed_page_count == page_count
    assert execution.failed_page_count == 0
    assert execution.evidence_coverage_numerator == page_count
    assert execution.evidence_coverage_denominator == page_count
    assert execution.evidence_coverage_ratio == 1.0


def test_partial_and_unavailable_evidence_populate_coverage_metadata(
    db_session: Session,
) -> None:
    website, run = _create_run(db_session, suffix="partial")
    _add_page(
        db_session,
        website,
        run,
        "/available",
        content=None,
    )
    _add_page(
        db_session,
        website,
        run,
        "/failed",
        title=None,
        status=PageAnalysisStatus.FAILED,
    )
    _add_page(
        db_session,
        website,
        run,
        "/not-run",
        title=None,
        status=None,
    )
    db_session.commit()

    execution = SiteDiagnosticsService(db_session).execute_diagnostics(
        run.id,
        idempotency_key="partial",
    )
    assert execution.status == SiteDiagnosticExecutionStatusEnum.PARTIAL.value
    assert execution.total_page_count == 3
    assert execution.processed_page_count == 3
    assert execution.failed_page_count == 2
    assert execution.evidence_coverage_numerator == 1
    assert execution.evidence_coverage_denominator == 3
    assert execution.evidence_coverage_ratio == pytest.approx(1 / 3)
    assert len(execution.partial_completion_metadata["unavailable_or_partial_pages"]) == 3
    content_coverage = execution.partial_completion_metadata["evidence_field_coverage"][
        "content_signature"
    ]
    assert content_coverage == {"numerator": 0, "denominator": 3, "ratio": 0.0}

    unavailable_website, unavailable_run = _create_run(db_session, suffix="unavailable")
    _add_page(
        db_session,
        unavailable_website,
        unavailable_run,
        "/not-run",
        title=None,
        status=None,
    )
    db_session.commit()
    unavailable_execution = SiteDiagnosticsService(db_session).execute_diagnostics(
        unavailable_run.id,
        idempotency_key="unavailable",
    )
    assert unavailable_execution.status == SiteDiagnosticExecutionStatusEnum.UNAVAILABLE.value
    assert unavailable_execution.evidence_coverage_numerator == 0
    assert _findings(
        db_session,
        unavailable_execution,
        "unavailable_content_signature_evidence",
    )


def test_idempotency_reuses_execution_and_preserves_completed_history(
    db_session: Session,
) -> None:
    website, run = _create_run(db_session)
    _, page_run = _add_page(
        db_session,
        website,
        run,
        "/history",
        title=None,
        content=_unique_content("history"),
    )
    db_session.commit()
    service = SiteDiagnosticsService(db_session)

    first = service.execute_diagnostics(run.id, idempotency_key="same-key")
    first_id = first.id
    first_execution_id = first.execution_id
    first_completed_at = first.completed_at
    first_evidence_fingerprint = first.evidence_fingerprint
    first_finding_ids = {finding.id for finding in first.findings}

    second = service.execute_diagnostics(run.id, idempotency_key="different-key")
    assert second.id != first_id
    assert second.execution_id != first_execution_id
    assert second.input_fingerprint == first.input_fingerprint
    assert second.evidence_fingerprint == first_evidence_fingerprint

    assert page_run is not None
    page_run.page_title = "Changed after completed execution"
    db_session.commit()
    reused = service.execute_diagnostics(run.id, idempotency_key="same-key")
    assert reused.id == first_id
    assert reused.execution_id == first_execution_id
    assert reused.completed_at == first_completed_at
    assert reused.evidence_fingerprint == first_evidence_fingerprint
    assert {finding.id for finding in reused.findings} == first_finding_ids

    executions = db_session.execute(
        select(SiteDiagnosticExecution)
        .where(SiteDiagnosticExecution.analysis_run_id == run.id)
        .order_by(SiteDiagnosticExecution.created_at)
    ).scalars()
    assert len(list(executions)) == 2
    preserved = db_session.get(SiteDiagnosticExecution, first_id)
    assert preserved is not None
    assert preserved.completed_at == first_completed_at
    assert {finding.id for finding in preserved.findings} == first_finding_ids


def test_internal_link_graph_diagnostics_cover_persisted_edge_evidence(
    db_session: Session,
) -> None:
    website, run = _create_run(db_session, suffix="links")
    discovery = _add_complete_discovery(db_session, website)
    pages: dict[str, tuple[WebsitePage, PageAnalysisRun | None]] = {}
    for path in (
        "/",
        "/ok",
        "/broken",
        "/redirect",
        "/loop",
        "/nonindex",
        "/canonical-alt",
        "/orphan",
        "/no-inbound",
        "/dead-end",
        "/deep",
    ):
        pages[path] = _add_page(
            db_session,
            website,
            run,
            path,
            title=f"Page {path}",
            description=f"Description {path}",
            content=_unique_content(path.replace("/", "") or "home"),
        )
        page, page_run = pages[path]
        page.last_discovery_run_id = discovery.id
        page_run.internal_link_count = 0

    home_page, home_run = pages["/"]
    home_run.internal_link_count = 12
    home_run.evidence = {
        **home_run.evidence,
        "internal_links": [
            "/ok",
            "/ok/",
            {"url": "/broken", "http_status_code": 404},
            {
                "url": "/redirect",
                "redirect_chain": [
                    {"url": f"{website.url}/redirect", "status": 301},
                    {"url": f"{website.url}/redirect-2", "status": 302},
                ],
            },
            {
                "url": "/loop",
                "redirect_chain": [
                    {"url": f"{website.url}/loop", "status": 301},
                    {"url": f"{website.url}/loop", "status": 302},
                ],
            },
            f"http://{urlsplit(website.url).hostname}/ok",
            f"https://www.{urlsplit(website.url).hostname}/ok",
            "/nonindex",
            "/canonical-alt",
            "http://[bad",
            "mailto:person@example.test",
            "tel:+10000000000",
            "javascript:void(0)",
            "https://external.test/outside",
        ],
    }
    nonindex_page, nonindex_run = pages["/nonindex"]
    nonindex_run.robots_directives = {"meta_robots": "noindex", "x_robots_tag": None}
    canonical_page, canonical_run = pages["/canonical-alt"]
    canonical_run.canonical_url = f"{website.url}/ok"
    dead_end_page, _ = pages["/dead-end"]
    deep_page, _ = pages["/deep"]
    deep_page.crawl_depth = 5
    for path in (
        "/ok",
        "/broken",
        "/redirect",
        "/loop",
        "/nonindex",
        "/canonical-alt",
        "/dead-end",
        "/deep",
    ):
        page, _ = pages[path]
        page.discovery_source = "page_link"
        page.source_page_url = home_page.normalized_url
        page.discovery_evidence = [
            {
                "source": "page_link",
                "source_page_url": home_page.normalized_url,
                "original_url": page.original_url,
            }
        ]
    orphan_page, _ = pages["/orphan"]
    orphan_page.discovery_source = "sitemap"
    orphan_page.discovery_evidence = [
        {
            "source": "sitemap",
            "source_page_url": f"{website.url}/sitemap.xml",
            "original_url": orphan_page.original_url,
        }
    ]
    no_inbound_page, _ = pages["/no-inbound"]
    no_inbound_page.discovery_source = "test_fixture"
    no_inbound_page.discovery_evidence = []
    db_session.commit()

    execution = SiteDiagnosticsService(db_session).execute_diagnostics(
        run.id,
        idempotency_key="link-graph",
    )

    assert "broken_internal_link" in _finding_subtypes(
        db_session, execution, "broken_internal_link"
    )
    assert "malformed_internal_url" in _finding_subtypes(
        db_session, execution, "broken_internal_link"
    )
    assert {
        "redirected_internal_link",
        "internal_redirect_chain",
        "internal_redirect_loop",
    } <= _finding_subtypes(db_session, execution, "internal_redirect_link")
    assert {"orphan_page", "no_inbound_link_page"} <= _finding_subtypes(
        db_session, execution, "orphan_page"
    )
    assert "dead_end_page" in _finding_subtypes(db_session, execution, "dead_end_page")
    assert "excessive_click_depth" in _finding_subtypes(
        db_session, execution, "excessive_click_depth"
    )
    assert {
        "link_to_non_indexable_page",
        "link_to_canonical_alternative",
    } <= _finding_subtypes(db_session, execution, "indexability_signal_conflict")
    assert "internal_link_protocol_inconsistency" in _finding_subtypes(
        db_session, execution, "inconsistent_url_protocol"
    )
    assert "internal_link_host_inconsistency" in _finding_subtypes(
        db_session, execution, "inconsistent_preferred_host"
    )
    assert "internal_link_trailing_slash_inconsistency" in _finding_subtypes(
        db_session, execution, "inconsistent_trailing_slash"
    )
    graph = execution.partial_completion_metadata["link_graph"]
    assert graph["evidence_complete"] is True
    targets = {edge["target_url"] for edge in graph["edges"]}
    assert "https://external.test/outside" not in targets
    assert all(
        not edge["raw_target"].startswith(("mailto:", "tel:", "javascript:"))
        for edge in graph["edges"]
    )
    assert len(graph["malformed_edges"]) == 1
    assert dead_end_page.id in {
        occurrence.website_page_id
        for finding in _findings(db_session, execution, "dead_end_page")
        for occurrence in finding.occurrences
    }
    assert deep_page.id in {
        occurrence.website_page_id
        for finding in _findings(db_session, execution, "excessive_click_depth")
        for occurrence in finding.occurrences
    }


def test_canonical_and_indexability_diagnostics_cover_persisted_signals(
    db_session: Session,
) -> None:
    website, run = _create_run(db_session, suffix="canonicals")
    pages: dict[str, tuple[WebsitePage, PageAnalysisRun | None]] = {}
    for path in (
        "/self",
        "/missing",
        "/invalid",
        "/conflict",
        "/chain-a",
        "/chain-b",
        "/chain-c",
        "/loop-a",
        "/loop-b",
        "/target-noindex",
        "/to-noindex",
        "/target-redirect",
        "/to-redirect",
        "/external",
        "/mismatch",
        "/robots",
        "/sitemap-noindex",
        "/duplicate",
    ):
        pages[path] = _add_page(
            db_session,
            website,
            run,
            path,
            title=f"Canonical {path}",
            description=f"Description {path}",
            content=_unique_content(path.replace("/", "")),
        )
        _, page_run = pages[path]
        page_run.http_status_code = 200
        page_run.internal_link_count = 0

    pages["/self"][1].canonical_url = f"{website.url}/self"
    pages["/invalid"][1].canonical_url = "javascript:invalid"
    conflict_page, conflict_run = pages["/conflict"]
    conflict_page.canonical_url = f"{website.url}/chain-a"
    conflict_run.canonical_url = f"{website.url}/chain-b"
    pages["/chain-a"][1].canonical_url = f"{website.url}/chain-b"
    pages["/chain-b"][1].canonical_url = f"{website.url}/chain-c"
    pages["/chain-c"][1].canonical_url = f"{website.url}/chain-c"
    pages["/loop-a"][1].canonical_url = f"{website.url}/loop-b"
    pages["/loop-b"][1].canonical_url = f"{website.url}/loop-a"
    pages["/target-noindex"][1].canonical_url = f"{website.url}/target-noindex"
    pages["/target-noindex"][1].robots_directives = {
        "meta_robots": "noindex",
        "x_robots_tag": None,
    }
    pages["/to-noindex"][1].canonical_url = f"{website.url}/target-noindex"
    pages["/target-redirect"][1].canonical_url = f"{website.url}/target-redirect"
    pages["/target-redirect"][1].redirect_chain = [
        {"url": f"{website.url}/target-redirect", "status": 301}
    ]
    pages["/to-redirect"][1].canonical_url = f"{website.url}/target-redirect"
    pages["/external"][1].canonical_url = "https://external.test/preferred"
    pages["/mismatch"][1].canonical_url = f"http://www.{urlsplit(website.url).hostname}/mismatch"
    pages["/robots"][1].canonical_url = f"{website.url}/robots"
    pages["/robots"][1].robots_directives = {
        "meta_robots": "index, noindex",
        "x_robots_tag": "index, noindex",
    }
    sitemap_page, sitemap_run = pages["/sitemap-noindex"]
    sitemap_run.canonical_url = f"{website.url}/sitemap-noindex"
    sitemap_run.robots_directives = {
        "meta_robots": "noindex",
        "x_robots_tag": "index",
    }
    sitemap_page.discovery_source = "sitemap"
    sitemap_page.discovery_evidence = [
        {
            "source": "sitemap",
            "source_page_url": f"{website.url}/sitemap.xml",
            "original_url": sitemap_page.original_url,
        }
    ]
    duplicate_page, duplicate_run = pages["/duplicate"]
    duplicate_page.original_url = f"http://{urlsplit(website.url).hostname}/duplicate/"
    duplicate_run.final_url = f"{website.url}/duplicate"
    duplicate_run.canonical_url = f"{website.url}/duplicate"
    db_session.commit()

    execution = SiteDiagnosticsService(db_session).execute_diagnostics(
        run.id,
        idempotency_key="canonical-indexability",
    )

    assert "missing_canonical" in _finding_subtypes(db_session, execution, "missing_canonical")
    assert "invalid_canonical" in _finding_subtypes(db_session, execution, "invalid_canonical")
    assert "conflicting_canonical" in _finding_subtypes(
        db_session, execution, "conflicting_canonical"
    )
    assert {"canonical_chain", "canonical_loop"} <= _finding_subtypes(
        db_session, execution, "canonical_chain"
    )
    assert "canonical_to_redirect_error_or_non_indexable_target" in _finding_subtypes(
        db_session,
        execution,
        "canonical_to_non_indexable",
    )
    assert {
        "external_canonical",
        "robots_or_x_robots_conflict",
        "sitemap_indexability_disagreement",
        "duplicate_normalized_url",
    } <= _finding_subtypes(db_session, execution, "indexability_signal_conflict")
    assert "canonical_protocol_mismatch" in _finding_subtypes(
        db_session, execution, "inconsistent_url_protocol"
    )
    assert "canonical_host_mismatch" in _finding_subtypes(
        db_session, execution, "inconsistent_preferred_host"
    )
    assert (
        "actual search-engine indexing"
        not in " ".join(finding.evidence_summary for finding in execution.findings).casefold()
    )


def test_technical_consistency_aggregates_references_without_raw_report_copy(
    db_session: Session,
) -> None:
    website, run = _create_run(db_session, suffix="technical")
    page_pairs = [
        _add_page(
            db_session,
            website,
            run,
            f"/technical-{index}",
            title=f"Technical {index}",
            description=f"Technical description {index}",
            content=_unique_content(f"technical{index}"),
        )
        for index in range(2)
    ]
    for index, (page, page_run) in enumerate(page_pairs):
        page_run.http_status_code = 200 + index
        page_run.content_type = (
            "text/html; charset=utf-8" if index == 0 else "text/html; charset=iso-8859-1"
        )
        page_run.structured_data_present = index == 0
        page_run.internal_link_count = 0
        page_run.security_observations = {
            "https": True,
            "strict_transport_security": None,
            "content_security_policy": f"default-src policy-{index}",
            "x_frame_options": "DENY",
            "x_content_type_options": "nosniff",
            "referrer_policy": "strict-origin",
            "permissions_policy": "geolocation=()",
        }
        page_run.evidence = {
            **page_run.evidence,
            "headers_sampled": {
                "cache-control": f"max-age={index * 60}",
                "content-type": page_run.content_type,
            },
            "console_errors": ["Shared deterministic console error"],
            "failed_network_requests": [
                {
                    "url": f"{website.url}/asset.js",
                    "status": 503,
                    "error": "service unavailable",
                }
            ],
            "large_resources": [
                {
                    "url": f"{website.url}/large.js",
                    "type": "script",
                    "bytes": 500000,
                }
            ],
            "mixed_content_count": 1,
        }
        snapshot = PerformanceSnapshot(
            execution_id=uuid4(),
            website_id=website.id,
            analysis_run_id=run.id,
            url_or_origin=page.normalized_url,
            evidence_source="lighthouse",
            evidence_type="lab",
            scope="url",
            form_factor="desktop",
            metric_id="lab_lcp",
            raw_value=5000 + index,
            rating="poor",
            availability_status="available",
            provider="lighthouse",
            provider_metadata={"bottleneck": True},
        )
        audit = AccessibilityAudit(
            id=uuid4(),
            execution_id=uuid4(),
            website_id=website.id,
            analysis_run_id=run.id,
            page_id=page.id,
            normalized_url=page.normalized_url,
            provider="axe-core",
            status="completed",
            violation_count=1,
            incomplete_count=0,
            pass_count=0,
            inapplicable_count=0,
        )
        finding = AccessibilityFinding(
            audit_id=audit.id,
            provider_rule_id="color-contrast",
            title="Color contrast",
            description="Persisted accessibility evidence",
            impact="serious",
            result_type="violation",
            affected_element_count=1,
        )
        db_session.add_all([snapshot, audit, finding])
    unavailable_page, _ = _add_page(
        db_session,
        website,
        run,
        "/unavailable",
        title=None,
        status=None,
    )
    db_session.commit()

    execution = SiteDiagnosticsService(db_session).execute_diagnostics(
        run.id,
        idempotency_key="technical-consistency",
    )

    protocol_subtypes = _finding_subtypes(
        db_session,
        execution,
        "inconsistent_url_protocol",
    )
    assert "mixed_protocol_resources" in protocol_subtypes
    repeated_subtypes = _finding_subtypes(
        db_session,
        execution,
        "repeated_issue_pattern",
    )
    # M3: security-header findings moved from repeated_issue_pattern to
    # dedicated security-category rules so they reach the Security &
    # Technical report section instead of Repeated and Template Problems.
    missing_header_subtypes = _finding_subtypes(
        db_session,
        execution,
        "missing_security_header",
    )
    assert any(
        subtype.startswith("missing_security_header:") for subtype in missing_header_subtypes
    )
    header_policy_subtypes = _finding_subtypes(
        db_session,
        execution,
        "inconsistent_security_header_policy",
    )
    assert any(
        subtype.startswith("inconsistent_header_policy:") for subtype in header_policy_subtypes
    )
    assert not any(
        subtype.startswith(("repeated_missing_security_header:", "inconsistent_header_policy:"))
        for subtype in repeated_subtypes
    )
    assert any(subtype.startswith("repeated_console_error:") for subtype in repeated_subtypes)
    assert any(subtype.startswith("repeated_failed_resource:") for subtype in repeated_subtypes)
    assert any(subtype.startswith("repeated_large_resource:") for subtype in repeated_subtypes)
    assert "inconsistent_http_status_code:content" in repeated_subtypes
    assert "inconsistent_content_type_charset:content" in repeated_subtypes
    assert "inconsistent_cache_policy:content" in repeated_subtypes
    assert "repeated_performance_bottleneck:lab_lcp" in repeated_subtypes
    assert "repeated_accessibility_pattern:color-contrast" in repeated_subtypes
    assert "inconsistent_structured_data:content" in _finding_subtypes(
        db_session,
        execution,
        "inconsistent_structured_data",
    )
    assert "unavailable_canonical_or_technical_evidence" in _finding_subtypes(
        db_session,
        execution,
        "insufficient_page_evidence",
    )
    assert "partial_diagnostic_coverage" in _finding_subtypes(
        db_session,
        execution,
        "partial_diagnostic_coverage",
    )
    assert unavailable_page.id in {
        occurrence.website_page_id
        for finding in _findings(db_session, execution, "insufficient_page_evidence")
        for occurrence in finding.occurrences
    }
    technical_occurrences = [
        occurrence
        for finding in _findings(db_session, execution, "repeated_issue_pattern")
        for occurrence in finding.occurrences
    ]
    assert any(
        occurrence.evidence_reference.startswith("performance_snapshot:")
        for occurrence in technical_occurrences
    )
    assert any(
        occurrence.evidence_reference.startswith("accessibility_finding:")
        for occurrence in technical_occurrences
    )


def test_exact_eight_api_endpoints_filter_paginate_validate_and_report_errors(
    db_session: Session,
    client: TestClient,
) -> None:
    from app.api.routes.site_diagnostics import router as diagnostics_router

    expected_routes = {
        ("GET", "/analysis-runs/{run_id}/site-diagnostics"),
        ("POST", "/analysis-runs/{run_id}/site-diagnostics/generate"),
        ("GET", "/websites/{website_id}/site-diagnostics"),
        ("GET", "/websites/{website_id}/site-diagnostics/history"),
        ("GET", "/websites/{website_id}/site-diagnostics/findings"),
        ("GET", "/site-diagnostics/findings/{finding_id}"),
        ("GET", "/websites/{website_id}/site-diagnostics/link-graph"),
        ("GET", "/metadata/site-diagnostic-rules"),
    }
    actual_routes = {
        (method, route.path)
        for route in diagnostics_router.routes
        for method in route.methods
        if method in {"GET", "POST"}
    }
    assert actual_routes == expected_routes

    website, run = _create_run(db_session, suffix="api")
    discovery = _add_complete_discovery(db_session, website)
    page, page_run = _add_page(
        db_session,
        website,
        run,
        "/",
        title=None,
        description=None,
        h1_count=0,
        content=_unique_content("apipage"),
    )
    page.last_discovery_run_id = discovery.id
    page_run.internal_link_count = 0
    page_run.evidence = {**page_run.evidence, "internal_links": []}
    db_session.commit()

    first = client.post(
        f"/api/v1/analysis-runs/{run.id}/site-diagnostics/generate",
        headers={"Idempotency-Key": "api-key-one"},
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["execution_id"] != str(run.id)
    assert first_payload["evidence_coverage_numerator"] == 1
    reused = client.post(
        f"/api/v1/analysis-runs/{run.id}/site-diagnostics/generate",
        json={"idempotency_key": "api-key-one"},
    )
    assert reused.status_code == 200
    assert reused.json()["id"] == first_payload["id"]
    second = client.post(
        f"/api/v1/analysis-runs/{run.id}/site-diagnostics/generate",
        headers={"Idempotency-Key": "api-key-two"},
    )
    assert second.status_code == 200
    assert second.json()["id"] != first_payload["id"]

    by_run = client.get(f"/api/v1/analysis-runs/{run.id}/site-diagnostics")
    latest = client.get(f"/api/v1/websites/{website.id}/site-diagnostics")
    assert by_run.status_code == latest.status_code == 200
    assert by_run.json()["id"] == latest.json()["id"] == second.json()["id"]
    history = client.get(
        f"/api/v1/websites/{website.id}/site-diagnostics/history",
        params={"limit": 1, "offset": 1, "status": "completed"},
    )
    assert history.status_code == 200
    assert len(history.json()) == 1

    findings = client.get(
        f"/api/v1/websites/{website.id}/site-diagnostics/findings",
        params={
            "rule_id": "missing_title",
            "severity": "high",
            "scope": "site",
            "confidence": "high",
            "limit": 1,
            "offset": 0,
        },
    )
    assert findings.status_code == 200
    assert len(findings.json()) == 1
    finding_id = findings.json()[0]["id"]
    detail = client.get(f"/api/v1/site-diagnostics/findings/{finding_id}")
    assert detail.status_code == 200
    assert len(detail.json()["occurrences"]) == detail.json()["occurrence_count"]

    graph = client.get(
        f"/api/v1/websites/{website.id}/site-diagnostics/link-graph",
        params={"node_limit": 1, "edge_limit": 1},
    )
    assert graph.status_code == 200
    assert graph.json()["total_nodes"] == 1
    assert len(graph.json()["nodes"]) == 1
    rules = client.get(
        "/api/v1/metadata/site-diagnostic-rules",
        params={"category": "internal_link_graph"},
    )
    assert rules.status_code == 200
    assert rules.json()
    assert {rule["category"] for rule in rules.json()} == {"internal_link_graph"}

    unknown_id = uuid4()
    assert client.get(f"/api/v1/websites/{unknown_id}/site-diagnostics").status_code == 404
    assert client.get(f"/api/v1/analysis-runs/{unknown_id}/site-diagnostics").status_code == 404
    assert client.get(f"/api/v1/site-diagnostics/findings/{unknown_id}").status_code == 404
    assert (
        client.get(
            f"/api/v1/websites/{website.id}/site-diagnostics/findings",
            params={"category": "not-a-category"},
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/v1/websites/{website.id}/site-diagnostics/findings",
            params={"rule_id": "unknown_rule"},
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/v1/websites/{website.id}/site-diagnostics/history",
            params={"limit": 0},
        ).status_code
        == 422
    )
    incomplete = AnalysisRun(
        website_id=website.id,
        status=AnalysisStatus.RUNNING,
        progress_percent=50,
    )
    db_session.add(incomplete)
    db_session.commit()
    assert (
        client.post(
            f"/api/v1/analysis-runs/{incomplete.id}/site-diagnostics/generate",
            headers={"Idempotency-Key": "incomplete"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/analysis-runs/{run.id}/site-diagnostics/generate",
            headers={"Idempotency-Key": "header-key"},
            json={"idempotency_key": "body-key"},
        ).status_code
        == 422
    )

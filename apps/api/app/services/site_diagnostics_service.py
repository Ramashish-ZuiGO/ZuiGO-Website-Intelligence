import hashlib
import html
import json
import logging
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from uuid import UUID

from datasketch import MinHash, MinHashLSH
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.accessibility import AccessibilityAudit, AccessibilityFinding
from app.models.analysis_result import AnalysisResult
from app.models.analysis_run import AnalysisRun, AnalysisStatus
from app.models.discovery_run import DiscoveryRun, DiscoveryStatus
from app.models.page_analysis_run import PageAnalysisRun, PageAnalysisStatus
from app.models.performance import PerformanceSnapshot
from app.models.site_diagnostic import (
    DiagnosticScopeEnum,
    SiteDiagnosticExecution,
    SiteDiagnosticExecutionStatusEnum,
    SiteDiagnosticFinding,
    SiteDiagnosticOccurrence,
)
from app.models.website import Website
from app.models.website_page import WebsitePage
from app.services.profiles_registry import get_profile
from app.services.site_diagnostic_rules import (
    DiagnosticRuleDefinition,
    SiteDiagnosticRuleRegistry,
)

MINIMUM_USABLE_CONTENT_LENGTH: Final[int] = 80
EXACT_CONTENT_SIGNATURE_METHOD: Final[str] = "sha256-normalized-text-v1"
NEAR_DUPLICATE_SIMILARITY_METHOD: Final[str] = "token-set-jaccard-v1"
NEAR_DUPLICATE_SIMILARITY_THRESHOLD: Final[float] = 0.85
MINIMUM_AFFECTED_PAGE_COUNT: Final[int] = 2
# AT-3: above this many near-duplicate candidates, full pairwise Jaccard
# comparison (O(n^2)) becomes expensive -- discovery allows up to 10,000
# pages per site. Below this size, nothing changes: the existing exact
# algorithm runs unmodified. Above it, MinHash/LSH narrows which pairs are
# even worth an exact check; the final similarity decision below always
# still uses exact _jaccard() on the real token sets, so results are
# identical except for a small, disclosed, well-established LSH
# false-negative probability (tuned low via NEAR_DUPLICATE_LSH_NUM_PERM).
NEAR_DUPLICATE_LSH_PREFILTER_PAGE_COUNT: Final[int] = 300
NEAR_DUPLICATE_LSH_NUM_PERMUTATIONS: Final[int] = 128
WORKFLOW_ID: Final[str] = "site_diagnostics"
WORKFLOW_VERSION: Final[str] = "2.0.0"
DIAGNOSTIC_ENGINE_VERSION: Final[str] = "2.0.0"
CLICK_DEPTH_THRESHOLDS: Final[dict[str, int]] = {
    "global_general": 3,
    "india_general": 3,
    "india_government": 3,
    "enterprise": 4,
}
logger = logging.getLogger(__name__)

SECURITY_HEADER_KEYS: Final[tuple[str, ...]] = (
    "strict_transport_security",
    "content_security_policy",
    "x_frame_options",
    "x_content_type_options",
    "referrer_policy",
    "permissions_policy",
)

_CONTENT_TEXT_KEYS: Final[tuple[str, ...]] = (
    "content_text",
    "main_content_text",
    "visible_text",
)
_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class PageEvidence:
    page_id: UUID
    normalized_url: str
    page_type: str
    section: str
    source_run_id: UUID | None
    evidence_reference: str
    page_analysis_status: str | None
    title: str | None
    normalized_title: str | None
    title_evidence_available: bool
    meta_description: str | None
    normalized_meta_description: str | None
    metadata_evidence_available: bool
    h1_count: int | None
    heading_evidence_available: bool
    language: str | None
    normalized_language: str | None
    language_evidence_available: bool
    content_signature: str | None
    content_tokens: frozenset[str] | None
    content_evidence_status: str
    template_signature: str | None
    discovery_evidence_fingerprint: str

    @property
    def base_evidence_available(self) -> bool:
        return any(
            (
                self.title_evidence_available,
                self.metadata_evidence_available,
                self.heading_evidence_available,
                self.language_evidence_available,
            )
        )


@dataclass(frozen=True)
class FindingGroup:
    source_rule_id: str
    group_key: str
    pages: tuple[PageEvidence, ...]
    observed_value: str


@dataclass(frozen=True)
class TechnicalPageEvidence:
    page_id: UUID
    normalized_url: str
    original_url: str
    final_url: str | None
    page_type: str
    eligibility_status: str
    discovery_source: str
    discovery_run_id: UUID | None
    discovery_evidence: tuple[dict[str, Any], ...]
    source_page_url: str | None
    crawl_depth: int
    robots_status: str
    evidence_reference: str
    evidence_available: bool
    http_status_code: int | None
    redirect_chain: tuple[dict[str, Any], ...]
    canonical_values: tuple[str, ...]
    canonical_evidence_available: bool
    robots_directives: dict[str, Any]
    content_type: str | None
    structured_data_present: bool | None
    internal_link_count: int | None
    internal_link_values: tuple[Any, ...]
    internal_link_evidence_available: bool
    security_observations: dict[str, Any]
    headers: dict[str, Any]
    console_errors: tuple[str, ...]
    failed_resources: tuple[dict[str, Any], ...]
    large_resources: tuple[dict[str, Any], ...]
    mixed_content_count: int | None


@dataclass(frozen=True)
class LinkGraphSnapshot:
    nodes: tuple[dict[str, Any], ...]
    edges: tuple[dict[str, Any], ...]
    malformed_edges: tuple[dict[str, Any], ...]
    evidence_complete: bool
    discovery_run_id: UUID | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "nodes": list(self.nodes),
            "edges": list(self.edges),
            "malformed_edges": list(self.malformed_edges),
            "evidence_complete": self.evidence_complete,
            "discovery_run_id": str(self.discovery_run_id) if self.discovery_run_id else None,
        }


def compute_fingerprint(data: Any) -> str:
    serialized = json.dumps(
        data,
        default=str,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", html.unescape(value))
    normalized = " ".join(normalized.split()).casefold()
    return normalized or None


def _normalize_content(value: str) -> str:
    return _normalize_text(value) or ""


def _normalize_url(value: str) -> str:
    split = urlsplit(value.strip())
    scheme = split.scheme.casefold()
    hostname = (split.hostname or "").casefold()
    port = split.port
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        hostname = f"{hostname}:{port}"
    path = re.sub(r"/{2,}", "/", split.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(sorted(parse_qsl(split.query, keep_blank_values=True)))
    return urlunsplit((scheme, hostname, path, query, ""))


def _url_section(normalized_url: str) -> str:
    parts = [part.casefold() for part in urlsplit(normalized_url).path.split("/") if part]
    return parts[0] if parts else "/"


def _host_family(hostname: str | None) -> str:
    host = (hostname or "").casefold().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _path_identity(value: str) -> str:
    split = urlsplit(value)
    path = re.sub(r"/{2,}", "/", split.path or "/")
    return f"{_host_family(split.hostname)}{path.rstrip('/') or '/'}?{split.query}"


def _directives(value: Any) -> set[str]:
    if not isinstance(value, str):
        return set()
    return {item.strip().casefold() for item in re.split(r"[,;]", value) if item.strip()}


def _sequence_of_strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item.strip())


def _sequence_of_dicts(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def _status_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _content_text(run: PageAnalysisRun) -> str | None:
    sources = (run.evidence or {}, run.basic_seo_signals or {})
    for source in sources:
        for key in _CONTENT_TEXT_KEYS:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return None


def _stored_content_signature(sources: tuple[dict[str, Any], ...]) -> str | None:
    for source in sources:
        signature = source.get("content_signature")
        method = source.get("content_signature_method") or source.get("signature_method")
        if (
            isinstance(signature, str)
            and re.fullmatch(r"[0-9a-fA-F]{64}", signature)
            and method == EXACT_CONTENT_SIGNATURE_METHOD
        ):
            return signature.casefold()
    return None


def _template_signature(run: PageAnalysisRun) -> str | None:
    for source in (run.evidence or {}, run.basic_seo_signals or {}):
        value = source.get("template_signature") or source.get("structural_signature")
        if isinstance(value, str):
            normalized = _normalize_text(value)
            if normalized:
                return normalized
    return None


def _h1_count(headings: list[dict[str, Any]]) -> int:
    count = 0
    for heading in headings:
        level = heading.get("level")
        tag = heading.get("tag") or heading.get("tag_name")
        if level == 1 or (isinstance(tag, str) and tag.casefold() == "h1"):
            count += 1
    return count


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _minhash_for_tokens(tokens: frozenset[str]) -> MinHash:
    minhash = MinHash(num_perm=NEAR_DUPLICATE_LSH_NUM_PERMUTATIONS)
    for token in tokens:
        minhash.update(token.encode("utf8"))
    return minhash


def _lsh_candidate_neighbors(
    candidates: list["PageEvidence"],
) -> dict[UUID, set[UUID]]:
    """Return, for each candidate page, the set of other candidates' page
    ids that MinHash/LSH flags as plausibly near-duplicate. This is a
    PRE-FILTER only: it never decides similarity itself, it only narrows
    which pairs _near_duplicate_clusters bothers checking with exact
    _jaccard(). Only called when the candidate count exceeds
    NEAR_DUPLICATE_LSH_PREFILTER_PAGE_COUNT.
    """
    lsh = MinHashLSH(
        threshold=NEAR_DUPLICATE_SIMILARITY_THRESHOLD,
        num_perm=NEAR_DUPLICATE_LSH_NUM_PERMUTATIONS,
    )
    minhashes: dict[UUID, MinHash] = {}
    for page in candidates:
        minhash = _minhash_for_tokens(page.content_tokens or frozenset())
        minhashes[page.page_id] = minhash
        lsh.insert(str(page.page_id), minhash)
    neighbors: dict[UUID, set[UUID]] = defaultdict(set)
    for page in candidates:
        for match_key in lsh.query(minhashes[page.page_id]):
            match_id = UUID(match_key)
            if match_id != page.page_id:
                neighbors[page.page_id].add(match_id)
    return neighbors


class SiteDiagnosticsService:
    def __init__(self, db: Session):
        self.db = db

    def execute_diagnostics(
        self,
        analysis_run_id: UUID,
        *,
        idempotency_key: str,
    ) -> SiteDiagnosticExecution:
        normalized_key = idempotency_key.strip()
        if not normalized_key:
            raise ValueError("A non-empty idempotency key is required.")

        run = self.db.get(AnalysisRun, analysis_run_id)
        if run is None:
            raise ValueError(f"AnalysisRun {analysis_run_id} not found.")
        if _status_value(run.status) != AnalysisStatus.COMPLETED.value:
            raise ValueError("Site diagnostics require a completed analysis run.")

        existing = self.db.execute(
            select(SiteDiagnosticExecution).where(
                SiteDiagnosticExecution.analysis_run_id == analysis_run_id,
                SiteDiagnosticExecution.idempotency_key == normalized_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        website = self.db.get(Website, run.website_id)
        if website is None:
            raise ValueError(f"Website {run.website_id} not found.")

        page_evidence = self._select_evidence(run)
        technical_pages, discovery_run = self._select_technical_evidence(run, website)
        link_graph = self._build_link_graph(website, technical_pages, discovery_run)
        input_fingerprint = self._input_fingerprint(run, page_evidence)
        evidence_fingerprint = compute_fingerprint(
            {
                "page_evidence": self._evidence_fingerprint(page_evidence),
                "technical_evidence": [
                    {
                        key: value
                        for key, value in page.__dict__.items()
                        if key
                        not in {
                            "console_errors",
                            "failed_resources",
                            "large_resources",
                        }
                    }
                    for page in technical_pages
                ],
                "technical_reference_counts": [
                    {
                        "page_id": str(page.page_id),
                        "console_error_count": len(page.console_errors),
                        "failed_resource_count": len(page.failed_resources),
                        "large_resource_count": len(page.large_resources),
                    }
                    for page in technical_pages
                ],
                "link_graph": link_graph.as_dict(),
            }
        )
        profile_id, profile_version = self._selected_profile(run, website)
        total_pages = len(page_evidence)
        base_evidence_pages = sum(page.base_evidence_available for page in page_evidence)
        fully_comparable_pages = sum(
            page.base_evidence_available and page.content_signature is not None
            for page in page_evidence
        )
        failed_pages = total_pages - base_evidence_pages
        coverage_ratio = base_evidence_pages / total_pages if total_pages else 0.0
        missing_content = [page for page in page_evidence if page.content_signature is None]

        if base_evidence_pages == 0:
            status = SiteDiagnosticExecutionStatusEnum.UNAVAILABLE.value
        elif failed_pages or missing_content:
            status = SiteDiagnosticExecutionStatusEnum.PARTIAL.value
        else:
            status = SiteDiagnosticExecutionStatusEnum.COMPLETED.value

        completion_metadata = self._completion_metadata(
            page_evidence,
            fully_comparable_pages=fully_comparable_pages,
        )
        completion_metadata["link_graph"] = link_graph.as_dict()
        execution = SiteDiagnosticExecution(
            website_id=run.website_id,
            analysis_run_id=run.id,
            workflow_id=WORKFLOW_ID,
            workflow_version=WORKFLOW_VERSION,
            selected_profile_id=profile_id,
            selected_profile_version=profile_version,
            input_fingerprint=input_fingerprint,
            evidence_fingerprint=evidence_fingerprint,
            idempotency_key=normalized_key,
            diagnostic_engine_version=DIAGNOSTIC_ENGINE_VERSION,
            rule_registry_version=SiteDiagnosticRuleRegistry.VERSION,
            status=status,
            total_page_count=total_pages,
            processed_page_count=total_pages,
            failed_page_count=failed_pages,
            evidence_coverage_numerator=base_evidence_pages,
            evidence_coverage_denominator=total_pages,
            evidence_coverage_ratio=coverage_ratio,
            error_metadata={},
            partial_completion_metadata=completion_metadata,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        self.db.add(execution)
        self.db.flush()

        finding_groups = self._metadata_findings(execution, page_evidence)
        finding_groups.extend(self._content_findings(execution, page_evidence))
        self._pattern_findings(execution, finding_groups)
        eligible_page_map = {page.page_id: page for page in page_evidence}
        self._link_graph_findings(
            execution,
            eligible_page_map,
            technical_pages,
            link_graph,
            profile_id,
        )
        self._canonical_indexability_findings(
            execution,
            eligible_page_map,
            technical_pages,
        )
        self._technical_consistency_findings(
            execution,
            eligible_page_map,
            technical_pages,
            run,
        )
        self._availability_findings(execution, page_evidence, technical_pages, link_graph)
        self.db.commit()
        self.db.refresh(execution)
        logger.info(
            "site_diagnostics_completed execution_id=%s analysis_run_id=%s status=%s "
            "processed_pages=%s failed_pages=%s",
            execution.id,
            execution.analysis_run_id,
            execution.status,
            execution.processed_page_count,
            execution.failed_page_count,
        )
        return execution

    def _select_evidence(self, run: AnalysisRun) -> tuple[PageEvidence, ...]:
        pages = tuple(
            self.db.execute(
                select(WebsitePage)
                .where(
                    WebsitePage.website_id == run.website_id,
                    WebsitePage.eligibility_status == "eligible",
                )
                .order_by(WebsitePage.normalized_url, WebsitePage.id)
            )
            .scalars()
            .all()
        )
        if not pages:
            return ()

        page_ids = [page.id for page in pages]
        all_runs = tuple(
            self.db.execute(
                select(PageAnalysisRun)
                .where(PageAnalysisRun.website_page_id.in_(page_ids))
                .order_by(
                    PageAnalysisRun.website_page_id,
                    PageAnalysisRun.analysis_level.desc(),
                    PageAnalysisRun.id,
                )
            )
            .scalars()
            .all()
        )
        runs_by_page: dict[UUID, list[PageAnalysisRun]] = defaultdict(list)
        for page_run in all_runs:
            runs_by_page[page_run.website_page_id].append(page_run)
        analysis_result = self.db.execute(
            select(AnalysisResult).where(AnalysisResult.analysis_run_id == run.id)
        ).scalar_one_or_none()
        result_urls = (
            {
                _normalize_url(analysis_result.requested_url),
                _normalize_url(analysis_result.final_url),
            }
            if analysis_result is not None
            else set()
        )

        result: list[PageEvidence] = []
        for page in pages:
            candidates = [
                candidate
                for candidate in runs_by_page[page.id]
                if candidate.deep_analysis_run_id == run.id
                or candidate.id
                in {
                    page.page_analysis_level_1_run_id,
                    page.page_analysis_level_2_run_id,
                }
            ]
            selected = (
                min(candidates, key=lambda item: self._candidate_sort_key(item, run.id))
                if candidates
                else None
            )
            matching_result = (
                analysis_result if _normalize_url(page.normalized_url) in result_urls else None
            )
            result.append(self._normalize_page_evidence(page, selected, matching_result))
        return tuple(result)

    def _select_technical_evidence(
        self,
        run: AnalysisRun,
        website: Website,
    ) -> tuple[tuple[TechnicalPageEvidence, ...], DiscoveryRun | None]:
        pages = tuple(
            self.db.execute(
                select(WebsitePage)
                .where(WebsitePage.website_id == website.id)
                .order_by(WebsitePage.normalized_url, WebsitePage.id)
            )
            .scalars()
            .all()
        )
        discovery_run = self.db.execute(
            select(DiscoveryRun)
            .where(DiscoveryRun.website_id == website.id)
            .order_by(DiscoveryRun.created_at.desc(), DiscoveryRun.id)
            .limit(1)
        ).scalar_one_or_none()
        if not pages:
            return (), discovery_run

        page_runs = tuple(
            self.db.execute(
                select(PageAnalysisRun)
                .where(PageAnalysisRun.website_page_id.in_([page.id for page in pages]))
                .order_by(
                    PageAnalysisRun.website_page_id,
                    PageAnalysisRun.analysis_level.desc(),
                    PageAnalysisRun.id,
                )
            )
            .scalars()
            .all()
        )
        runs_by_page: dict[UUID, list[PageAnalysisRun]] = defaultdict(list)
        for page_run in page_runs:
            runs_by_page[page_run.website_page_id].append(page_run)
        analysis_result = self.db.execute(
            select(AnalysisResult).where(AnalysisResult.analysis_run_id == run.id)
        ).scalar_one_or_none()
        result_urls = (
            {
                _normalize_url(analysis_result.requested_url),
                _normalize_url(analysis_result.final_url),
            }
            if analysis_result is not None
            else set()
        )

        technical_pages: list[TechnicalPageEvidence] = []
        for page in pages:
            candidates = [
                candidate
                for candidate in runs_by_page[page.id]
                if candidate.deep_analysis_run_id == run.id
                or candidate.id
                in {
                    page.page_analysis_level_1_run_id,
                    page.page_analysis_level_2_run_id,
                }
            ]
            page_run = (
                min(candidates, key=lambda item: self._candidate_sort_key(item, run.id))
                if candidates
                else None
            )
            matching_result = (
                analysis_result if _normalize_url(page.normalized_url) in result_urls else None
            )
            technical_pages.append(self._normalize_technical_page(page, page_run, matching_result))
        return tuple(technical_pages), discovery_run

    def _normalize_technical_page(
        self,
        page: WebsitePage,
        page_run: PageAnalysisRun | None,
        analysis_result: AnalysisResult | None,
    ) -> TechnicalPageEvidence:
        successful = page_run is not None and _status_value(page_run.status) in {
            PageAnalysisStatus.COMPLETED.value,
            PageAnalysisStatus.PARTIAL.value,
        }
        result_available = analysis_result is not None
        result_data = analysis_result.raw_playwright_data if result_available else {}
        run_evidence = page_run.evidence if successful and page_run is not None else {}
        run_seo = page_run.basic_seo_signals if successful and page_run is not None else {}

        canonical_values: list[str] = []
        for value in (
            page.canonical_url,
            page_run.canonical_url if successful and page_run is not None else None,
            run_evidence.get("canonical_url"),
            run_seo.get("canonical_url"),
            result_data.get("canonical_url"),
        ):
            if isinstance(value, str) and value.strip() and value not in canonical_values:
                canonical_values.append(value.strip())
        extra_canonicals = run_evidence.get("canonical_declarations")
        if isinstance(extra_canonicals, list):
            for value in extra_canonicals:
                if isinstance(value, str) and value.strip() and value not in canonical_values:
                    canonical_values.append(value.strip())

        link_values: list[Any] = []
        link_evidence_available = False
        for source in (run_evidence, run_seo, result_data):
            for key in ("internal_links", "internal_link_urls", "rendered_dom_links"):
                if key in source:
                    link_evidence_available = True
                    value = source.get(key)
                    if isinstance(value, list):
                        link_values.extend(value)
        if successful and page_run is not None and page_run.internal_link_count is not None:
            link_evidence_available = True

        console_errors = _sequence_of_strings(
            run_evidence.get("console_errors")
        ) + _sequence_of_strings(result_data.get("console_errors"))
        failed_resources = _sequence_of_dicts(
            run_evidence.get("failed_network_requests")
        ) + _sequence_of_dicts(result_data.get("failed_network_requests"))
        large_resources = _sequence_of_dicts(
            run_evidence.get("large_resources")
        ) + _sequence_of_dicts(result_data.get("large_resources"))
        mixed_count = run_evidence.get("mixed_content_count")
        if not isinstance(mixed_count, int):
            mixed_count = result_data.get("mixed_content_count")
        if not isinstance(mixed_count, int):
            mixed_resources = run_evidence.get("mixed_protocol_resources")
            mixed_count = len(mixed_resources) if isinstance(mixed_resources, list) else None

        evidence_reference = (
            f"page_analysis_run:{page_run.id}"
            if successful and page_run is not None
            else f"analysis_result:{analysis_result.id}"
            if result_available
            else f"website_page:{page.id}"
        )
        headers = run_evidence.get("headers_sampled")
        if not isinstance(headers, dict):
            headers = {}
        security = (
            page_run.security_observations
            if successful and page_run is not None
            else result_data.get("security_observations", {})
        )
        if not isinstance(security, dict):
            security = {}
        robots_directives = (
            page_run.robots_directives
            if successful and page_run is not None
            else result_data.get("robots_directives", {})
        )
        if not isinstance(robots_directives, dict):
            robots_directives = {}
        redirect_chain = (
            page_run.redirect_chain
            if successful and page_run is not None
            else result_data.get("redirect_chain", [])
        )
        if not isinstance(redirect_chain, list):
            redirect_chain = []

        return TechnicalPageEvidence(
            page_id=page.id,
            normalized_url=_normalize_url(page.normalized_url),
            original_url=page.original_url,
            final_url=(
                page_run.final_url
                if successful and page_run is not None
                else analysis_result.final_url
                if result_available
                else page.final_url
            ),
            page_type=page.page_type,
            eligibility_status=page.eligibility_status,
            discovery_source=page.discovery_source,
            discovery_run_id=page.last_discovery_run_id,
            discovery_evidence=tuple(page.discovery_evidence or []),
            source_page_url=page.source_page_url,
            crawl_depth=page.crawl_depth,
            robots_status=page.robots_status,
            evidence_reference=evidence_reference,
            evidence_available=successful or result_available,
            http_status_code=(
                page_run.http_status_code
                if successful and page_run is not None
                else analysis_result.http_status_code
                if result_available
                else None
            ),
            redirect_chain=tuple(redirect_chain),
            canonical_values=tuple(canonical_values),
            canonical_evidence_available=successful
            or result_available
            or page.final_url is not None,
            robots_directives=robots_directives,
            content_type=(
                page_run.content_type
                if successful and page_run is not None
                else result_data.get("content_type")
            ),
            structured_data_present=(
                page_run.structured_data_present
                if successful and page_run is not None
                else result_data.get("structured_data_present")
            ),
            internal_link_count=(
                page_run.internal_link_count
                if successful and page_run is not None
                else result_data.get("internal_link_count")
            ),
            internal_link_values=tuple(link_values),
            internal_link_evidence_available=link_evidence_available,
            security_observations=security,
            headers=headers,
            console_errors=console_errors,
            failed_resources=failed_resources,
            large_resources=large_resources,
            mixed_content_count=mixed_count,
        )

    def _build_link_graph(
        self,
        website: Website,
        pages: tuple[TechnicalPageEvidence, ...],
        discovery_run: DiscoveryRun | None,
    ) -> LinkGraphSnapshot:
        website_family = _host_family(urlsplit(website.url).hostname)
        page_by_url: dict[str, TechnicalPageEvidence] = {}
        for page in pages:
            page_by_url[page.normalized_url] = page
            if page.final_url:
                page_by_url[_normalize_url(page.final_url)] = page

        edges: list[dict[str, Any]] = []
        malformed: list[dict[str, Any]] = []

        def add_edge(
            source_page: TechnicalPageEvidence | None,
            raw_target: Any,
            evidence_reference: str,
            details: dict[str, Any] | None = None,
        ) -> None:
            if source_page is None or not isinstance(raw_target, str):
                return
            raw_target = raw_target.strip()
            if not raw_target:
                return
            lower = raw_target.casefold()
            if lower.startswith(("mailto:", "tel:", "javascript:", "data:", "#")):
                return
            try:
                resolved = urljoin(source_page.normalized_url, raw_target)
                split = urlsplit(resolved)
                if (
                    split.scheme.casefold() not in {"http", "https"}
                    or not split.hostname
                    or any(ord(character) < 32 for character in resolved)
                ):
                    raise ValueError("unsupported or incomplete internal URL")
            except (TypeError, ValueError):
                malformed.append(
                    {
                        "source_page_id": str(source_page.page_id),
                        "source_url": source_page.normalized_url,
                        "raw_target": raw_target[:2048],
                        "evidence_reference": evidence_reference,
                    }
                )
                return
            if _host_family(split.hostname) != website_family:
                return
            target_url = _normalize_url(resolved)
            target_page = page_by_url.get(target_url)
            detail = details or {}
            status = detail.get("http_status_code") or detail.get("status")
            if not isinstance(status, int):
                status = target_page.http_status_code if target_page else None
            redirect_chain = detail.get("redirect_chain")
            if not isinstance(redirect_chain, list):
                redirect_chain = list(target_page.redirect_chain) if target_page is not None else []
            edge = {
                "source_page_id": str(source_page.page_id),
                "source_url": source_page.normalized_url,
                "raw_target": raw_target[:2048],
                "target_url": target_url,
                "target_page_id": str(target_page.page_id) if target_page else None,
                "target_http_status": status,
                "redirect_chain": redirect_chain,
                "target_eligibility_status": (
                    target_page.eligibility_status if target_page else None
                ),
                "target_robots_status": target_page.robots_status if target_page else None,
                "target_robots_directives": (target_page.robots_directives if target_page else {}),
                "target_canonical_values": (
                    list(target_page.canonical_values) if target_page else []
                ),
                "evidence_reference": evidence_reference,
            }
            edges.append(edge)

        source_lookup = {page.normalized_url: page for page in pages}
        for target_page in pages:
            has_discovery_edge = False
            for index, evidence in enumerate(target_page.discovery_evidence):
                source = evidence.get("source")
                source_url = evidence.get("source_page_url")
                if source not in {"homepage_link", "page_link", "rendered_dom"}:
                    continue
                if not isinstance(source_url, str):
                    continue
                source_page = source_lookup.get(_normalize_url(source_url))
                has_discovery_edge = source_page is not None or has_discovery_edge
                add_edge(
                    source_page,
                    evidence.get("original_url") or target_page.original_url,
                    f"website_page:{target_page.page_id}:discovery:{index}",
                )
            if target_page.source_page_url and not has_discovery_edge:
                source_page = source_lookup.get(_normalize_url(target_page.source_page_url))
                add_edge(
                    source_page,
                    target_page.original_url,
                    f"website_page:{target_page.page_id}:source_page",
                )

        for source_page in pages:
            for index, raw_link in enumerate(source_page.internal_link_values):
                if isinstance(raw_link, dict):
                    target = (
                        raw_link.get("target_url") or raw_link.get("url") or raw_link.get("href")
                    )
                    details = raw_link
                else:
                    target = raw_link
                    details = None
                add_edge(
                    source_page,
                    target,
                    f"{source_page.evidence_reference}:internal_link:{index}",
                    details,
                )

        inbound: dict[str, int] = defaultdict(int)
        outbound: dict[str, int] = defaultdict(int)
        for edge in edges:
            outbound[edge["source_page_id"]] += 1
            if edge["target_page_id"]:
                inbound[edge["target_page_id"]] += 1
        nodes = tuple(
            {
                "page_id": str(page.page_id),
                "normalized_url": page.normalized_url,
                "eligibility_status": page.eligibility_status,
                "crawl_depth": page.crawl_depth,
                "inbound_link_count": inbound[str(page.page_id)],
                "outbound_link_count": outbound[str(page.page_id)],
                "outbound_evidence_available": page.internal_link_evidence_available,
                "http_status_code": page.http_status_code,
                "canonical_values": list(page.canonical_values),
            }
            for page in pages
        )
        evidence_complete = bool(
            discovery_run is not None
            and _status_value(discovery_run.status) == DiscoveryStatus.COMPLETED.value
            and not discovery_run.crawl_limit_reached
        )
        return LinkGraphSnapshot(
            nodes=nodes,
            edges=tuple(edges),
            malformed_edges=tuple(malformed),
            evidence_complete=evidence_complete,
            discovery_run_id=discovery_run.id if discovery_run else None,
        )

    @staticmethod
    def _candidate_sort_key(page_run: PageAnalysisRun, analysis_run_id: UUID) -> tuple[Any, ...]:
        status = _status_value(page_run.status)
        return (
            page_run.deep_analysis_run_id != analysis_run_id,
            status not in {PageAnalysisStatus.COMPLETED.value, PageAnalysisStatus.PARTIAL.value},
            -page_run.analysis_level,
            str(page_run.id),
        )

    def _normalize_page_evidence(
        self,
        page: WebsitePage,
        page_run: PageAnalysisRun | None,
        analysis_result: AnalysisResult | None,
    ) -> PageEvidence:
        successful = page_run is not None and _status_value(page_run.status) in {
            PageAnalysisStatus.COMPLETED.value,
            PageAnalysisStatus.PARTIAL.value,
        }
        result_available = analysis_result is not None
        result_data = analysis_result.raw_playwright_data if analysis_result is not None else {}
        raw_title = (
            page_run.page_title
            if successful
            else analysis_result.page_title
            if result_available
            else page.page_title
        )
        title_available = successful or result_available or bool(_normalize_text(page.page_title))
        raw_description = (
            page_run.meta_description
            if successful
            else analysis_result.meta_description
            if result_available
            else None
        )
        headings = page_run.heading_structure if successful else None
        h1_texts = result_data.get("h1_texts")
        result_h1_count = len(h1_texts) if isinstance(h1_texts, list) else None
        raw_language = page_run.language if successful else result_data.get("html_language")
        if raw_language is not None and not isinstance(raw_language, str):
            raw_language = None
        content_signature: str | None = None
        content_tokens: frozenset[str] | None = None
        content_status = "page_analysis_evidence_unavailable"
        template_signature = None

        if successful and page_run is not None:
            template_signature = _template_signature(page_run)
            raw_content = _content_text(page_run)
            if raw_content is None:
                stored_signature = _stored_content_signature(
                    (page_run.evidence or {}, page_run.basic_seo_signals or {})
                )
                if stored_signature is not None:
                    content_signature = stored_signature
                    content_status = "available_exact_signature_only"
                else:
                    content_status = "content_text_or_supported_signature_unavailable"
            else:
                normalized_content = _normalize_content(raw_content)
                if len(normalized_content) < MINIMUM_USABLE_CONTENT_LENGTH:
                    content_status = "content_below_minimum_length"
                else:
                    content_signature = hashlib.sha256(
                        normalized_content.encode("utf-8")
                    ).hexdigest()
                    content_tokens = frozenset(_TOKEN_PATTERN.findall(normalized_content))
                    content_status = "available"
        elif result_available:
            result_sources = (result_data,)
            raw_content = next(
                (
                    result_data[key]
                    for key in _CONTENT_TEXT_KEYS
                    if isinstance(result_data.get(key), str) and result_data[key].strip()
                ),
                None,
            )
            raw_template_signature = result_data.get("template_signature") or result_data.get(
                "structural_signature"
            )
            if isinstance(raw_template_signature, str):
                template_signature = _normalize_text(raw_template_signature)
            if raw_content is None:
                stored_signature = _stored_content_signature(result_sources)
                if stored_signature is not None:
                    content_signature = stored_signature
                    content_status = "available_exact_signature_only"
                else:
                    content_status = "content_text_or_supported_signature_unavailable"
            else:
                normalized_content = _normalize_content(raw_content)
                if len(normalized_content) < MINIMUM_USABLE_CONTENT_LENGTH:
                    content_status = "content_below_minimum_length"
                else:
                    content_signature = hashlib.sha256(
                        normalized_content.encode("utf-8")
                    ).hexdigest()
                    content_tokens = frozenset(_TOKEN_PATTERN.findall(normalized_content))
                    content_status = "available"

        normalized_url = _normalize_url(page.normalized_url)
        source_reference = (
            f"page_analysis_run:{page_run.id}"
            if successful and page_run is not None
            else f"analysis_result:{analysis_result.id}"
            if analysis_result is not None
            else f"website_page:{page.id}"
        )
        return PageEvidence(
            page_id=page.id,
            normalized_url=normalized_url,
            page_type=page.page_type,
            section=_url_section(normalized_url),
            source_run_id=(
                page_run.id
                if successful and page_run is not None
                else analysis_result.id
                if analysis_result is not None
                else None
            ),
            evidence_reference=source_reference,
            page_analysis_status=(
                _status_value(page_run.status)
                if successful and page_run is not None
                else "analysis_run_completed"
                if analysis_result is not None
                else _status_value(page_run.status)
                if page_run is not None
                else None
            ),
            title=raw_title,
            normalized_title=_normalize_text(raw_title),
            title_evidence_available=title_available,
            meta_description=raw_description,
            normalized_meta_description=_normalize_text(raw_description),
            metadata_evidence_available=successful or result_available,
            h1_count=(_h1_count(headings) if headings is not None else result_h1_count),
            heading_evidence_available=successful or result_h1_count is not None,
            language=raw_language,
            normalized_language=_normalize_text(raw_language),
            language_evidence_available=successful or "html_language" in result_data,
            content_signature=content_signature,
            content_tokens=content_tokens,
            content_evidence_status=content_status,
            template_signature=template_signature,
            discovery_evidence_fingerprint=compute_fingerprint(page.discovery_evidence or []),
        )

    @staticmethod
    def _selected_profile(run: AnalysisRun, website: Website) -> tuple[str, str]:
        profile_id = run.profile_id or website.profile_id or "global_general"
        profile = get_profile(profile_id) or get_profile("global_general")
        if profile is None:
            raise ValueError("The default diagnostic profile is unavailable.")
        return profile.profile_id, run.profile_version or profile.version

    @staticmethod
    def _input_fingerprint(
        run: AnalysisRun,
        pages: tuple[PageEvidence, ...],
    ) -> str:
        return compute_fingerprint(
            {
                "analysis_run_id": str(run.id),
                "website_id": str(run.website_id),
                "profile_id": run.profile_id,
                "profile_version": run.profile_version,
                "pages": [
                    {
                        "page_id": str(page.page_id),
                        "normalized_url": page.normalized_url,
                        "source_run_id": str(page.source_run_id) if page.source_run_id else None,
                    }
                    for page in pages
                ],
            }
        )

    @staticmethod
    def _evidence_fingerprint(pages: tuple[PageEvidence, ...]) -> str:
        return compute_fingerprint(
            [
                {
                    "page_id": str(page.page_id),
                    "normalized_url": page.normalized_url,
                    "title": page.normalized_title,
                    "title_available": page.title_evidence_available,
                    "meta_description": page.normalized_meta_description,
                    "metadata_available": page.metadata_evidence_available,
                    "h1_count": page.h1_count,
                    "heading_available": page.heading_evidence_available,
                    "language": page.normalized_language,
                    "language_available": page.language_evidence_available,
                    "content_signature": page.content_signature,
                    "content_status": page.content_evidence_status,
                    "template_signature": page.template_signature,
                    "discovery_evidence_fingerprint": page.discovery_evidence_fingerprint,
                }
                for page in pages
            ]
        )

    @staticmethod
    def _completion_metadata(
        pages: tuple[PageEvidence, ...],
        *,
        fully_comparable_pages: int,
    ) -> dict[str, Any]:
        total = len(pages)
        field_counts = {
            "title": sum(page.title_evidence_available for page in pages),
            "meta_description": sum(page.metadata_evidence_available for page in pages),
            "heading_structure": sum(page.heading_evidence_available for page in pages),
            "language_declaration": sum(page.language_evidence_available for page in pages),
            "content_signature": sum(page.content_signature is not None for page in pages),
        }
        unavailable = [
            {
                "page_id": str(page.page_id),
                "normalized_url": page.normalized_url,
                "page_analysis_status": page.page_analysis_status,
                "content_signature_status": page.content_evidence_status,
                "unavailable_fields": [
                    name
                    for name, available in (
                        ("title", page.title_evidence_available),
                        ("meta_description", page.metadata_evidence_available),
                        ("heading_structure", page.heading_evidence_available),
                        ("language_declaration", page.language_evidence_available),
                        ("content_signature", page.content_signature is not None),
                    )
                    if not available
                ],
            }
            for page in pages
            if not (
                page.title_evidence_available
                and page.metadata_evidence_available
                and page.heading_evidence_available
                and page.language_evidence_available
                and page.content_signature is not None
            )
        ]
        return {
            "evidence_field_coverage": {
                name: {
                    "numerator": count,
                    "denominator": total,
                    "ratio": count / total if total else 0.0,
                }
                for name, count in field_counts.items()
            },
            "fully_comparable_page_count": fully_comparable_pages,
            "unavailable_or_partial_pages": unavailable,
            "content_signature": {
                "exact_method": EXACT_CONTENT_SIGNATURE_METHOD,
                "near_duplicate_method": NEAR_DUPLICATE_SIMILARITY_METHOD,
                "minimum_usable_content_length": MINIMUM_USABLE_CONTENT_LENGTH,
                "similarity_threshold": NEAR_DUPLICATE_SIMILARITY_THRESHOLD,
                "minimum_affected_page_count": MINIMUM_AFFECTED_PAGE_COUNT,
                # AT-3: the similarity decision itself is always exact
                # Jaccard; on large sites a MinHash/LSH pre-filter narrows
                # which page pairs are checked at all, which carries a
                # small, well-established false-negative probability not
                # present when this flag is False.
                "large_site_lsh_prefilter_engaged": (
                    total > NEAR_DUPLICATE_LSH_PREFILTER_PAGE_COUNT
                ),
            },
        }

    def _metadata_findings(
        self,
        execution: SiteDiagnosticExecution,
        pages: tuple[PageEvidence, ...],
    ) -> list[FindingGroup]:
        groups: list[FindingGroup] = []
        missing_titles = tuple(
            page
            for page in pages
            if page.title_evidence_available and page.normalized_title is None
        )
        groups.extend(
            self._add_group_if_present(
                execution,
                "missing_title",
                "missing",
                missing_titles,
                observed_value="title absent",
                expected_value="a non-empty page title",
                summary=(
                    f"{len(missing_titles)} eligible pages have confirmed empty title evidence."
                ),
            )
        )
        groups.extend(
            self._group_normalized_values(
                execution,
                pages,
                rule_id="duplicate_title_group",
                value_attribute="normalized_title",
                availability_attribute="title_evidence_available",
                expected_value="a page-specific normalized title",
                label="normalized title",
            )
        )

        missing_descriptions = tuple(
            page
            for page in pages
            if page.metadata_evidence_available and page.normalized_meta_description is None
        )
        groups.extend(
            self._add_group_if_present(
                execution,
                "missing_meta_description",
                "missing",
                missing_descriptions,
                observed_value="meta description absent",
                expected_value="a non-empty meta description",
                summary=(
                    f"{len(missing_descriptions)} eligible pages have confirmed empty "
                    "meta-description evidence."
                ),
            )
        )
        groups.extend(
            self._group_normalized_values(
                execution,
                pages,
                rule_id="duplicate_meta_description_group",
                value_attribute="normalized_meta_description",
                availability_attribute="metadata_evidence_available",
                expected_value="a page-specific normalized meta description",
                label="normalized meta description",
            )
        )

        missing_h1 = tuple(
            page for page in pages if page.heading_evidence_available and page.h1_count == 0
        )
        groups.extend(
            self._add_group_if_present(
                execution,
                "missing_h1",
                "count:0",
                missing_h1,
                observed_value="0 H1 elements",
                expected_value="one intended H1 element",
                summary=f"{len(missing_h1)} eligible pages have zero H1 elements.",
            )
        )
        multiple_h1 = tuple(
            page
            for page in pages
            if page.heading_evidence_available and page.h1_count is not None and page.h1_count > 1
        )
        groups.extend(
            self._add_group_if_present(
                execution,
                "multiple_h1",
                "count:multiple",
                multiple_h1,
                observed_value="more than one H1 element",
                expected_value="the selected profile's intended H1 convention",
                summary=f"{len(multiple_h1)} eligible pages have more than one H1 element.",
            )
        )

        language_cohorts: dict[str, dict[str, list[PageEvidence]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for page in pages:
            if page.language_evidence_available and page.normalized_language:
                language_cohorts[page.page_type][page.normalized_language].append(page)
        for cohort, languages in sorted(language_cohorts.items()):
            if len(languages) <= 1:
                continue
            affected = tuple(
                sorted(
                    (page for group in languages.values() for page in group),
                    key=lambda page: (page.normalized_url, str(page.page_id)),
                )
            )
            distribution = ", ".join(
                f"{language}={len(group)}" for language, group in sorted(languages.items())
            )
            groups.extend(
                self._add_group_if_present(
                    execution,
                    "inconsistent_language_declaration",
                    compute_fingerprint(
                        {
                            "cohort": cohort,
                            "languages": sorted(languages),
                        }
                    ),
                    affected,
                    observed_value=distribution,
                    expected_value="a profile-aware consistent language cohort",
                    summary=(
                        f"{len(affected)} comparable {cohort!r} pages use "
                        f"{len(languages)} declarations ({distribution}); multilingual "
                        "intent requires review."
                    ),
                    include_for_patterns=False,
                )
            )
        return groups

    def _content_findings(
        self,
        execution: SiteDiagnosticExecution,
        pages: tuple[PageEvidence, ...],
    ) -> list[FindingGroup]:
        groups: list[FindingGroup] = []
        exact_groups: dict[str, list[PageEvidence]] = defaultdict(list)
        for page in pages:
            if page.content_signature:
                exact_groups[page.content_signature].append(page)
        exact_grouped_page_ids: set[UUID] = set()
        for signature, group in sorted(exact_groups.items()):
            if len(group) < MINIMUM_AFFECTED_PAGE_COUNT:
                continue
            affected = tuple(sorted(group, key=lambda page: page.normalized_url))
            exact_grouped_page_ids.update(page.page_id for page in affected)
            groups.extend(
                self._add_group_if_present(
                    execution,
                    "exact_duplicate_content_group",
                    signature,
                    affected,
                    observed_value=f"{EXACT_CONTENT_SIGNATURE_METHOD}:{signature}",
                    expected_value="a distinct primary-content signature",
                    summary=(
                        f"{len(affected)} pages share exact content signature "
                        f"{signature[:12]} using {EXACT_CONTENT_SIGNATURE_METHOD}."
                    ),
                )
            )

        near_candidates = [
            page
            for page in pages
            if page.content_tokens is not None and page.page_id not in exact_grouped_page_ids
        ]
        for cluster in self._near_duplicate_clusters(near_candidates):
            similarities = [
                _jaccard(left.content_tokens or frozenset(), right.content_tokens or frozenset())
                for index, left in enumerate(cluster)
                for right in cluster[index + 1 :]
            ]
            minimum_similarity = min(similarities)
            group_key = compute_fingerprint(
                {
                    "method": NEAR_DUPLICATE_SIMILARITY_METHOD,
                    "page_ids": [str(page.page_id) for page in cluster],
                    "threshold": NEAR_DUPLICATE_SIMILARITY_THRESHOLD,
                }
            )
            groups.extend(
                self._add_group_if_present(
                    execution,
                    "near_duplicate_content_group",
                    group_key,
                    cluster,
                    observed_value=f"minimum pairwise similarity {minimum_similarity:.4f}",
                    expected_value=(
                        f"pairwise similarity below {NEAR_DUPLICATE_SIMILARITY_THRESHOLD:.2f}"
                    ),
                    summary=(
                        f"{len(cluster)} pages form a complete-link cluster using "
                        f"{NEAR_DUPLICATE_SIMILARITY_METHOD}; minimum pairwise similarity "
                        f"{minimum_similarity:.4f}, threshold "
                        f"{NEAR_DUPLICATE_SIMILARITY_THRESHOLD:.2f}."
                    ),
                )
            )

        unavailable = tuple(page for page in pages if page.content_signature is None)
        groups.extend(
            self._add_group_if_present(
                execution,
                "unavailable_content_signature_evidence",
                "unavailable",
                unavailable,
                observed_value="content signature unavailable",
                expected_value=f"{EXACT_CONTENT_SIGNATURE_METHOD} signature",
                summary=(
                    f"{len(unavailable)} of {len(pages)} eligible pages lack usable content "
                    f"evidence; minimum normalized length is "
                    f"{MINIMUM_USABLE_CONTENT_LENGTH} characters."
                ),
                confidence="unavailable",
                include_for_patterns=False,
            )
        )
        return groups

    @staticmethod
    def _near_duplicate_clusters(
        candidates: list[PageEvidence],
    ) -> tuple[tuple[PageEvidence, ...], ...]:
        remaining = sorted(candidates, key=lambda page: (page.normalized_url, str(page.page_id)))
        # AT-3: below the threshold, behavior is unchanged from before --
        # every candidate is checked against every other candidate with
        # exact Jaccard, same as always. Only large sites engage the LSH
        # pre-filter, and even then the actual similarity/threshold
        # decision below is still always exact _jaccard().
        neighbor_ids: dict[UUID, set[UUID]] | None = (
            _lsh_candidate_neighbors(remaining)
            if len(remaining) > NEAR_DUPLICATE_LSH_PREFILTER_PAGE_COUNT
            else None
        )
        clusters: list[tuple[PageEvidence, ...]] = []
        while remaining:
            seed = remaining.pop(0)
            pool = (
                [page for page in remaining if page.page_id in neighbor_ids.get(seed.page_id, ())]
                if neighbor_ids is not None
                else tuple(remaining)
            )
            cluster = [seed]
            for candidate in tuple(pool):
                if all(
                    _jaccard(
                        candidate.content_tokens or frozenset(),
                        member.content_tokens or frozenset(),
                    )
                    >= NEAR_DUPLICATE_SIMILARITY_THRESHOLD
                    for member in cluster
                ):
                    cluster.append(candidate)
                    remaining.remove(candidate)
            if len(cluster) >= MINIMUM_AFFECTED_PAGE_COUNT:
                clusters.append(tuple(cluster))
        return tuple(clusters)

    def _group_normalized_values(
        self,
        execution: SiteDiagnosticExecution,
        pages: tuple[PageEvidence, ...],
        *,
        rule_id: str,
        value_attribute: str,
        availability_attribute: str,
        expected_value: str,
        label: str,
    ) -> list[FindingGroup]:
        values: dict[str, list[PageEvidence]] = defaultdict(list)
        for page in pages:
            value = getattr(page, value_attribute)
            if getattr(page, availability_attribute) and value:
                values[value].append(page)
        result: list[FindingGroup] = []
        for value, group in sorted(values.items()):
            if len(group) < MINIMUM_AFFECTED_PAGE_COUNT:
                continue
            affected = tuple(sorted(group, key=lambda page: page.normalized_url))
            result.extend(
                self._add_group_if_present(
                    execution,
                    rule_id,
                    compute_fingerprint({"value": value}),
                    affected,
                    observed_value=value,
                    expected_value=expected_value,
                    summary=f"{len(affected)} pages share {label} {value!r}.",
                )
            )
        return result

    def _add_group_if_present(
        self,
        execution: SiteDiagnosticExecution,
        rule_id: str,
        group_key: str,
        pages: tuple[PageEvidence, ...],
        *,
        observed_value: str,
        expected_value: str,
        summary: str,
        confidence: str = "high",
        include_for_patterns: bool = True,
    ) -> list[FindingGroup]:
        if not pages:
            return []
        self._add_finding(
            execution,
            rule_id,
            group_key,
            pages,
            observed_value=observed_value,
            expected_value=expected_value,
            summary=summary,
            confidence=confidence,
            scope=DiagnosticScopeEnum.SITE,
        )
        if not include_for_patterns or len(pages) < MINIMUM_AFFECTED_PAGE_COUNT:
            return []
        return [
            FindingGroup(
                source_rule_id=rule_id,
                group_key=group_key,
                pages=pages,
                observed_value=observed_value,
            )
        ]

    def _pattern_findings(
        self,
        execution: SiteDiagnosticExecution,
        groups: list[FindingGroup],
    ) -> None:
        for group in groups:
            pages = group.pages
            template_signatures = {page.template_signature for page in pages}
            sections = {page.section for page in pages}
            ratio = len(pages) / execution.total_page_count if execution.total_page_count else 0.0

            if None not in template_signatures and len(template_signatures) == 1:
                rule_id = "template_issue_pattern"
                scope = DiagnosticScopeEnum.TEMPLATE
                confidence = "high"
                signature = next(iter(template_signatures))
                rationale = (
                    f"{len(pages)} pages ({ratio:.1%}) share structural signature "
                    f"{signature!r} and source issue {group.source_rule_id}; this is a "
                    "likely, not proven, shared template."
                )
            elif len(sections) == 1 and "/" not in sections:
                rule_id = "section_issue_pattern"
                scope = DiagnosticScopeEnum.SECTION
                confidence = "medium"
                section = next(iter(sections))
                rationale = (
                    f"{len(pages)} pages ({ratio:.1%}) with consistent issue evidence are "
                    f"concentrated in URL section /{section}/."
                )
            else:
                rule_id = "repeated_issue_pattern"
                scope = DiagnosticScopeEnum.SITE
                confidence = "medium"
                rationale = (
                    f"{len(pages)} pages ({ratio:.1%}) share source issue "
                    f"{group.source_rule_id}; no common structural signature or single "
                    "non-root URL section proves a narrower scope."
                )

            self._add_finding(
                execution,
                rule_id,
                compute_fingerprint(
                    {
                        "source_rule_id": group.source_rule_id,
                        "source_group_key": group.group_key,
                        "classification": rule_id,
                    }
                ),
                pages,
                observed_value=group.observed_value,
                expected_value="the source issue absent from every affected page",
                summary=rationale,
                confidence=confidence,
                scope=scope,
                context_extra={
                    "source_rule_id": group.source_rule_id,
                    "source_group_key": group.group_key,
                    "affected_page_count": len(pages),
                    "affected_page_ratio": ratio,
                    "classification_rationale": rationale,
                },
            )

    def _add_subtype_finding(
        self,
        execution: SiteDiagnosticExecution,
        page_map: dict[UUID, PageEvidence],
        *,
        rule_id: str,
        subtype: str,
        observations: list[dict[str, Any]],
        summary: str,
        expected_value: str,
        confidence: str = "high",
        scope: DiagnosticScopeEnum = DiagnosticScopeEnum.SITE,
    ) -> SiteDiagnosticFinding | None:
        attributed: list[PageEvidence] = []
        details: list[dict[str, Any]] = []
        for observation in observations:
            raw_page_id = observation.get("page_id")
            try:
                page_id = UUID(str(raw_page_id))
            except (TypeError, ValueError):
                continue
            page = page_map.get(page_id)
            if page is None:
                continue
            attributed.append(page)
            reference = observation.get("evidence_reference")
            details.append(
                {
                    "evidence_reference": (
                        reference if isinstance(reference, str) else page.evidence_reference
                    ),
                    "resource_url": observation.get("resource_url"),
                    "location": observation.get("location"),
                    "observed_value": str(observation.get("observed_value", subtype))[:4000],
                    "expected_value": expected_value,
                    "context": {
                        "diagnostic_subtype": subtype,
                        **(
                            observation.get("context")
                            if isinstance(observation.get("context"), dict)
                            else {}
                        ),
                    },
                    "supporting_evidence": (
                        observation.get("supporting_evidence")
                        if isinstance(observation.get("supporting_evidence"), dict)
                        else {}
                    ),
                }
            )
        if not attributed:
            return None
        return self._add_finding(
            execution,
            rule_id,
            compute_fingerprint(
                {
                    "rule_id": rule_id,
                    "subtype": subtype,
                    "observations": [
                        {
                            "page_id": str(page.page_id),
                            "detail": detail,
                        }
                        for page, detail in zip(attributed, details, strict=True)
                    ],
                }
            ),
            tuple(attributed),
            observed_value=subtype,
            expected_value=expected_value,
            summary=summary,
            confidence=confidence,
            scope=scope,
            context_extra={"diagnostic_subtype": subtype},
            occurrence_details=tuple(details),
        )

    def _link_graph_findings(
        self,
        execution: SiteDiagnosticExecution,
        page_map: dict[UUID, PageEvidence],
        technical_pages: tuple[TechnicalPageEvidence, ...],
        graph: LinkGraphSnapshot,
        profile_id: str,
    ) -> None:
        broken: list[dict[str, Any]] = []
        redirected: list[dict[str, Any]] = []
        redirect_chains: list[dict[str, Any]] = []
        redirect_loops: list[dict[str, Any]] = []
        links_to_non_indexable: list[dict[str, Any]] = []
        links_to_canonical_alternatives: list[dict[str, Any]] = []
        protocol_mismatches: list[dict[str, Any]] = []
        host_mismatches: list[dict[str, Any]] = []
        edge_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

        for edge in graph.edges:
            source_id = edge["source_page_id"]
            base_observation = {
                "page_id": source_id,
                "resource_url": edge["target_url"],
                "evidence_reference": edge["evidence_reference"],
                "observed_value": edge["raw_target"],
                "context": {
                    "target_page_id": edge["target_page_id"],
                    "target_url": edge["target_url"],
                },
                "supporting_evidence": {
                    "target_http_status": edge["target_http_status"],
                    "redirect_chain": edge["redirect_chain"],
                    "target_eligibility_status": edge["target_eligibility_status"],
                    "target_robots_status": edge["target_robots_status"],
                    "target_robots_directives": edge["target_robots_directives"],
                    "target_canonical_values": edge["target_canonical_values"],
                },
            }
            status = edge["target_http_status"]
            if isinstance(status, int) and status >= 400:
                broken.append(base_observation)

            chain = edge["redirect_chain"]
            if chain:
                redirected.append(base_observation)
                if len(chain) > 1:
                    redirect_chains.append(base_observation)
                chain_urls = [
                    _normalize_url(item["url"])
                    for item in chain
                    if isinstance(item, dict)
                    and isinstance(item.get("url"), str)
                    and item["url"].startswith(("http://", "https://"))
                ]
                if len(chain_urls) != len(set(chain_urls)) or edge["target_url"] in chain_urls:
                    redirect_loops.append(base_observation)

            target_status = edge["target_eligibility_status"]
            target_robots = edge["target_robots_status"]
            target_directives = edge["target_robots_directives"]
            target_meta = _directives(target_directives.get("meta_robots"))
            target_header = _directives(target_directives.get("x_robots_tag"))
            if (
                target_status in {"excluded", "skipped"}
                or target_robots == "disallowed"
                or "noindex" in target_meta
                or "noindex" in target_header
            ):
                links_to_non_indexable.append(base_observation)
            canonical_values = edge["target_canonical_values"]
            if canonical_values:
                try:
                    target_canonical = _normalize_url(
                        urljoin(edge["target_url"], canonical_values[0])
                    )
                except (TypeError, ValueError):
                    target_canonical = edge["target_url"]
                if target_canonical != edge["target_url"]:
                    links_to_canonical_alternatives.append(base_observation)

            raw_resolved = urljoin(edge["source_url"], edge["raw_target"])
            raw_split = urlsplit(raw_resolved)
            preferred_split = urlsplit(edge["source_url"])
            if raw_split.scheme.casefold() != preferred_split.scheme.casefold():
                protocol_mismatches.append(base_observation)
            if (raw_split.hostname or "").casefold() != (preferred_split.hostname or "").casefold():
                host_mismatches.append(base_observation)
            edge_groups[(source_id, edge["target_url"])].append(edge)

        self._add_subtype_finding(
            execution,
            page_map,
            rule_id="broken_internal_link",
            subtype="broken_internal_link",
            observations=broken,
            summary=(
                f"{len(broken)} internal link occurrences have persisted target response "
                "status evidence of 400 or greater."
            ),
            expected_value="an internal target with successful response evidence",
        )
        for subtype, observations in (
            ("redirected_internal_link", redirected),
            ("internal_redirect_chain", redirect_chains),
            ("internal_redirect_loop", redirect_loops),
        ):
            self._add_subtype_finding(
                execution,
                page_map,
                rule_id="internal_redirect_link",
                subtype=subtype,
                observations=observations,
                summary=f"{len(observations)} internal link occurrences match {subtype}.",
                expected_value="a direct internal link to the preferred final URL",
            )

        malformed = [
            {
                "page_id": item["source_page_id"],
                "resource_url": item["raw_target"],
                "evidence_reference": item["evidence_reference"],
                "observed_value": item["raw_target"],
                "context": {"parse_status": "malformed"},
            }
            for item in graph.malformed_edges
        ]
        self._add_subtype_finding(
            execution,
            page_map,
            rule_id="broken_internal_link",
            subtype="malformed_internal_url",
            observations=malformed,
            summary=f"{len(malformed)} persisted internal link values cannot be normalized.",
            expected_value="a valid HTTP(S) internal URL",
        )

        for subtype, observations in (
            ("link_to_non_indexable_page", links_to_non_indexable),
            ("link_to_canonical_alternative", links_to_canonical_alternatives),
        ):
            self._add_subtype_finding(
                execution,
                page_map,
                rule_id="indexability_signal_conflict",
                subtype=subtype,
                observations=observations,
                summary=f"{len(observations)} internal link occurrences match {subtype}.",
                expected_value="a direct link to the intended indexable preferred target",
            )
        self._add_subtype_finding(
            execution,
            page_map,
            rule_id="inconsistent_url_protocol",
            subtype="internal_link_protocol_inconsistency",
            observations=protocol_mismatches,
            summary=(
                f"{len(protocol_mismatches)} internal links use a protocol different from "
                "their source page."
            ),
            expected_value="the site's preferred HTTPS protocol",
        )
        self._add_subtype_finding(
            execution,
            page_map,
            rule_id="inconsistent_preferred_host",
            subtype="internal_link_host_inconsistency",
            observations=host_mismatches,
            summary=(
                f"{len(host_mismatches)} internal links use a different www/non-www host form."
            ),
            expected_value="the site's consistent preferred host",
        )

        duplicate_targets: list[dict[str, Any]] = []
        slash_variants: list[dict[str, Any]] = []
        for (_, target_url), grouped_edges in sorted(edge_groups.items()):
            raw_values = {edge["raw_target"] for edge in grouped_edges}
            if len(raw_values) <= 1:
                continue
            for edge in grouped_edges:
                observation = {
                    "page_id": edge["source_page_id"],
                    "resource_url": target_url,
                    "evidence_reference": edge["evidence_reference"],
                    "observed_value": edge["raw_target"],
                    "context": {"normalized_target": target_url},
                }
                duplicate_targets.append(observation)
                slash_forms = {
                    urlsplit(urljoin(edge["source_url"], value)).path.endswith("/")
                    for value in raw_values
                }
                if len(slash_forms) > 1:
                    slash_variants.append(observation)
        self._add_subtype_finding(
            execution,
            page_map,
            rule_id="repeated_issue_pattern",
            subtype="duplicate_normalized_internal_target",
            observations=duplicate_targets,
            summary=(
                f"{len(duplicate_targets)} link occurrences use multiple raw forms for the "
                "same normalized target."
            ),
            expected_value="one normalized internal target form",
            confidence="high",
        )
        self._add_subtype_finding(
            execution,
            page_map,
            rule_id="inconsistent_trailing_slash",
            subtype="internal_link_trailing_slash_inconsistency",
            observations=slash_variants,
            summary=(f"{len(slash_variants)} internal link occurrences mix trailing-slash forms."),
            expected_value="one trailing-slash convention per normalized path",
        )

        inbound = {node["page_id"]: node["inbound_link_count"] for node in graph.nodes}
        homepage = (
            _normalize_url(
                urlunsplit(
                    (
                        urlsplit(next(iter(page_map.values())).normalized_url).scheme,
                        urlsplit(next(iter(page_map.values())).normalized_url).netloc,
                        "/",
                        "",
                        "",
                    )
                )
            )
            if page_map
            else ""
        )
        orphan: list[dict[str, Any]] = []
        no_inbound: list[dict[str, Any]] = []
        dead_ends: list[dict[str, Any]] = []
        excessive_depth: list[dict[str, Any]] = []
        depth_threshold = CLICK_DEPTH_THRESHOLDS.get(
            profile_id,
            CLICK_DEPTH_THRESHOLDS["global_general"],
        )
        for page in technical_pages:
            if page.page_id not in page_map:
                continue
            if (
                graph.evidence_complete
                and page.normalized_url != homepage
                and not inbound.get(
                    str(page.page_id),
                    0,
                )
            ):
                observation = {
                    "page_id": str(page.page_id),
                    "evidence_reference": page.evidence_reference,
                    "observed_value": "0 evidenced inbound internal links",
                    "context": {
                        "discovery_source": page.discovery_source,
                        "discovery_run_id": str(graph.discovery_run_id)
                        if graph.discovery_run_id
                        else None,
                    },
                }
                if page.discovery_source in {
                    "sitemap",
                    "sitemap_index",
                    "robots_sitemap",
                    "submitted_url",
                }:
                    orphan.append(observation)
                else:
                    no_inbound.append(observation)
            if page.internal_link_evidence_available and (
                page.internal_link_count == 0
                or (
                    page.internal_link_count is None
                    and not any(edge["source_page_id"] == str(page.page_id) for edge in graph.edges)
                )
            ):
                dead_ends.append(
                    {
                        "page_id": str(page.page_id),
                        "evidence_reference": page.evidence_reference,
                        "observed_value": "0 evidenced outbound internal links",
                    }
                )
            if page.crawl_depth > depth_threshold:
                excessive_depth.append(
                    {
                        "page_id": str(page.page_id),
                        "evidence_reference": (f"website_page:{page.page_id}:crawl_depth"),
                        "observed_value": f"crawl depth {page.crawl_depth}",
                        "context": {"threshold": depth_threshold},
                    }
                )
        for subtype, observations in (
            ("orphan_page", orphan),
            ("no_inbound_link_page", no_inbound),
        ):
            self._add_subtype_finding(
                execution,
                page_map,
                rule_id="orphan_page",
                subtype=subtype,
                observations=observations,
                summary=(
                    f"{len(observations)} eligible pages have zero inbound internal links "
                    "within complete bounded discovery evidence."
                ),
                expected_value="at least one reachable inbound internal link",
            )
        self._add_subtype_finding(
            execution,
            page_map,
            rule_id="dead_end_page",
            subtype="dead_end_page",
            observations=dead_ends,
            summary=f"{len(dead_ends)} eligible pages have explicit zero-outbound evidence.",
            expected_value="at least one useful outbound internal link",
        )
        self._add_subtype_finding(
            execution,
            page_map,
            rule_id="excessive_click_depth",
            subtype="excessive_click_depth",
            observations=excessive_depth,
            summary=(
                f"{len(excessive_depth)} eligible pages exceed the {profile_id!r} "
                f"click-depth threshold of {depth_threshold}."
            ),
            expected_value=f"crawl depth at or below {depth_threshold}",
        )

    def _canonical_indexability_findings(
        self,
        execution: SiteDiagnosticExecution,
        page_map: dict[UUID, PageEvidence],
        pages: tuple[TechnicalPageEvidence, ...],
    ) -> None:
        technical_by_url: dict[str, TechnicalPageEvidence] = {}
        for page in pages:
            technical_by_url[page.normalized_url] = page
            if page.final_url:
                technical_by_url[_normalize_url(page.final_url)] = page
        internal_families = {_host_family(urlsplit(page.normalized_url).hostname) for page in pages}

        normalized_canonicals: dict[UUID, tuple[str, ...]] = {}
        missing: list[dict[str, Any]] = []
        invalid: list[dict[str, Any]] = []
        conflicting: list[dict[str, Any]] = []
        external: list[dict[str, Any]] = []
        protocol_mismatch: list[dict[str, Any]] = []
        host_mismatch: list[dict[str, Any]] = []
        indexability_conflicts: list[dict[str, Any]] = []
        sitemap_conflicts: list[dict[str, Any]] = []

        for page in pages:
            if page.page_id not in page_map:
                continue
            if page.canonical_evidence_available and not page.canonical_values:
                missing.append(
                    {
                        "page_id": str(page.page_id),
                        "evidence_reference": page.evidence_reference,
                        "observed_value": "no canonical declaration",
                    }
                )
            normalized_values: list[str] = []
            for raw_value in page.canonical_values:
                try:
                    resolved = urljoin(page.normalized_url, raw_value)
                    split = urlsplit(resolved)
                    if split.scheme.casefold() not in {"http", "https"} or not split.hostname:
                        raise ValueError("canonical must be an absolute HTTP(S) URL")
                    normalized = _normalize_url(resolved)
                except (TypeError, ValueError):
                    invalid.append(
                        {
                            "page_id": str(page.page_id),
                            "resource_url": raw_value,
                            "evidence_reference": page.evidence_reference,
                            "observed_value": raw_value,
                            "context": {"normalization_status": "invalid"},
                        }
                    )
                    continue
                if normalized not in normalized_values:
                    normalized_values.append(normalized)
                source_split = urlsplit(page.normalized_url)
                target_split = urlsplit(normalized)
                target_family = _host_family(target_split.hostname)
                observation = {
                    "page_id": str(page.page_id),
                    "resource_url": normalized,
                    "evidence_reference": page.evidence_reference,
                    "observed_value": raw_value,
                    "context": {"normalized_canonical": normalized},
                }
                if target_family not in internal_families:
                    external.append(observation)
                elif target_split.scheme.casefold() != source_split.scheme.casefold():
                    protocol_mismatch.append(observation)
                if (target_split.hostname or "").casefold() != (
                    source_split.hostname or ""
                ).casefold():
                    host_mismatch.append(observation)
            normalized_canonicals[page.page_id] = tuple(normalized_values)
            if len(normalized_values) > 1:
                conflicting.append(
                    {
                        "page_id": str(page.page_id),
                        "evidence_reference": page.evidence_reference,
                        "observed_value": ", ".join(normalized_values),
                        "supporting_evidence": {
                            "canonical_declarations": list(page.canonical_values),
                            "normalized_canonicals": normalized_values,
                        },
                    }
                )

            meta_directives = _directives(page.robots_directives.get("meta_robots"))
            header_directives = _directives(page.robots_directives.get("x_robots_tag"))
            if {"index", "noindex"} <= meta_directives:
                indexability_conflicts.append(
                    {
                        "page_id": str(page.page_id),
                        "evidence_reference": page.evidence_reference,
                        "observed_value": "meta robots contains index and noindex",
                        "context": {"conflict_type": "robots_meta_conflict"},
                    }
                )
            if {"index", "noindex"} <= header_directives:
                indexability_conflicts.append(
                    {
                        "page_id": str(page.page_id),
                        "evidence_reference": page.evidence_reference,
                        "observed_value": "X-Robots-Tag contains index and noindex",
                        "context": {"conflict_type": "x_robots_tag_conflict"},
                    }
                )
            if ("noindex" in meta_directives and "index" in header_directives) or (
                "index" in meta_directives and "noindex" in header_directives
            ):
                indexability_conflicts.append(
                    {
                        "page_id": str(page.page_id),
                        "evidence_reference": page.evidence_reference,
                        "observed_value": "robots meta and X-Robots-Tag disagree",
                        "context": {"conflict_type": "robots_header_conflict"},
                    }
                )
            sitemap_declared = any(
                evidence.get("source")
                in {
                    "sitemap",
                    "sitemap_index",
                    "robots_sitemap",
                }
                for evidence in page.discovery_evidence
            )
            technically_non_indexable = bool(
                page.robots_status == "disallowed"
                or "noindex" in meta_directives
                or "noindex" in header_directives
                or (page.http_status_code is not None and page.http_status_code >= 400)
            )
            if sitemap_declared and technically_non_indexable:
                sitemap_conflicts.append(
                    {
                        "page_id": str(page.page_id),
                        "evidence_reference": page.evidence_reference,
                        "observed_value": (
                            "sitemap declaration conflicts with technical non-indexability evidence"
                        ),
                        "context": {"conflict_type": "sitemap_indexability_disagreement"},
                    }
                )

        self._add_subtype_finding(
            execution,
            page_map,
            rule_id="missing_canonical",
            subtype="missing_canonical",
            observations=missing,
            summary=(
                f"{len(missing)} eligible pages have available canonical evidence with no "
                "declaration."
            ),
            expected_value="one intended canonical declaration",
        )
        self._add_subtype_finding(
            execution,
            page_map,
            rule_id="invalid_canonical",
            subtype="invalid_canonical",
            observations=invalid,
            summary=f"{len(invalid)} canonical declarations cannot be normalized safely.",
            expected_value="one valid absolute HTTP(S) canonical URL",
        )
        self._add_subtype_finding(
            execution,
            page_map,
            rule_id="conflicting_canonical",
            subtype="conflicting_canonical",
            observations=conflicting,
            summary=f"{len(conflicting)} pages expose distinct canonical declarations.",
            expected_value="one consistent canonical target",
        )

        canonical_chains: list[dict[str, Any]] = []
        canonical_loops: list[dict[str, Any]] = []
        target_conflicts: list[dict[str, Any]] = []
        for page in pages:
            if page.page_id not in page_map:
                continue
            canonicals = normalized_canonicals.get(page.page_id, ())
            if len(canonicals) != 1:
                continue
            canonical = canonicals[0]
            if canonical == page.normalized_url:
                continue
            target = technical_by_url.get(canonical)
            if target is None:
                continue
            target_canonicals = normalized_canonicals.get(target.page_id, ())
            observation = {
                "page_id": str(page.page_id),
                "resource_url": canonical,
                "evidence_reference": page.evidence_reference,
                "observed_value": canonical,
                "context": {"canonical_target_page_id": str(target.page_id)},
            }
            if target_canonicals and target_canonicals[0] != canonical:
                canonical_chains.append(observation)

            visited = {page.normalized_url}
            cursor = target
            loop_detected = False
            for _ in range(len(pages) + 1):
                if cursor.normalized_url in visited:
                    loop_detected = True
                    break
                visited.add(cursor.normalized_url)
                cursor_targets = normalized_canonicals.get(cursor.page_id, ())
                if len(cursor_targets) != 1:
                    break
                next_page = technical_by_url.get(cursor_targets[0])
                if next_page is None:
                    break
                cursor = next_page
            if loop_detected:
                canonical_loops.append(observation)

            target_meta = _directives(target.robots_directives.get("meta_robots"))
            target_header = _directives(target.robots_directives.get("x_robots_tag"))
            target_non_indexable = bool(
                target.eligibility_status in {"excluded", "skipped"}
                or target.robots_status == "disallowed"
                or "noindex" in target_meta
                or "noindex" in target_header
                or (target.http_status_code is not None and target.http_status_code >= 400)
                or target.redirect_chain
            )
            if target_non_indexable:
                observation["supporting_evidence"] = {
                    "target_http_status": target.http_status_code,
                    "target_eligibility_status": target.eligibility_status,
                    "target_robots_status": target.robots_status,
                    "target_redirect_count": len(target.redirect_chain),
                    "target_meta_robots": sorted(target_meta),
                    "target_x_robots_tag": sorted(target_header),
                }
                target_conflicts.append(observation)

        for subtype, observations in (
            ("canonical_chain", canonical_chains),
            ("canonical_loop", canonical_loops),
        ):
            self._add_subtype_finding(
                execution,
                page_map,
                rule_id="canonical_chain",
                subtype=subtype,
                observations=observations,
                summary=f"{len(observations)} canonical declarations match {subtype}.",
                expected_value="a direct canonical to the final preferred URL",
            )
        self._add_subtype_finding(
            execution,
            page_map,
            rule_id="canonical_to_non_indexable",
            subtype="canonical_to_redirect_error_or_non_indexable_target",
            observations=target_conflicts,
            summary=(
                f"{len(target_conflicts)} canonical declarations target pages with redirect, "
                "error, or technical non-indexability evidence."
            ),
            expected_value="a successful technically indexable preferred target",
        )
        for subtype, observations in (
            ("external_canonical", external),
            ("robots_or_x_robots_conflict", indexability_conflicts),
            ("sitemap_indexability_disagreement", sitemap_conflicts),
        ):
            self._add_subtype_finding(
                execution,
                page_map,
                rule_id="indexability_signal_conflict",
                subtype=subtype,
                observations=observations,
                summary=f"{len(observations)} pages match {subtype}.",
                expected_value="consistent technical indexability signals",
            )
        self._add_subtype_finding(
            execution,
            page_map,
            rule_id="inconsistent_url_protocol",
            subtype="canonical_protocol_mismatch",
            observations=protocol_mismatch,
            summary=(f"{len(protocol_mismatch)} canonical declarations use a different protocol."),
            expected_value="the site's preferred HTTPS protocol",
        )
        self._add_subtype_finding(
            execution,
            page_map,
            rule_id="inconsistent_preferred_host",
            subtype="canonical_host_mismatch",
            observations=host_mismatch,
            summary=f"{len(host_mismatch)} canonical declarations use another host form.",
            expected_value="the site's intended preferred host",
        )

        identity_groups: dict[str, list[TechnicalPageEvidence]] = defaultdict(list)
        for page in pages:
            if page.page_id in page_map:
                identity_groups[_path_identity(page.original_url)].append(page)
                if page.final_url and _normalize_url(page.final_url) != page.normalized_url:
                    identity_groups[_path_identity(page.final_url)].append(page)
        duplicate_normalized: list[dict[str, Any]] = []
        for identity, grouped_pages in identity_groups.items():
            page_ids = {page.page_id for page in grouped_pages}
            url_forms = {page.original_url for page in grouped_pages} | {
                page.final_url for page in grouped_pages if page.final_url
            }
            if len(url_forms) <= 1:
                continue
            for page_id in page_ids:
                page = next(page for page in grouped_pages if page.page_id == page_id)
                duplicate_normalized.append(
                    {
                        "page_id": str(page_id),
                        "evidence_reference": page.evidence_reference,
                        "observed_value": ", ".join(sorted(url_forms)),
                        "context": {
                            "conflict_type": "duplicate_normalized_url",
                            "path_identity": identity,
                        },
                    }
                )
        self._add_subtype_finding(
            execution,
            page_map,
            rule_id="indexability_signal_conflict",
            subtype="duplicate_normalized_url",
            observations=duplicate_normalized,
            summary=(
                f"{len(duplicate_normalized)} page occurrences use conflicting URL forms "
                "for one normalized identity."
            ),
            expected_value="one stable normalized URL per page identity",
        )

    def _technical_consistency_findings(
        self,
        execution: SiteDiagnosticExecution,
        page_map: dict[UUID, PageEvidence],
        pages: tuple[TechnicalPageEvidence, ...],
        run: AnalysisRun,
    ) -> None:
        mixed_protocol = [
            {
                "page_id": str(page.page_id),
                "evidence_reference": page.evidence_reference,
                "observed_value": f"{page.mixed_content_count} mixed-protocol resources",
                "supporting_evidence": {
                    "mixed_content_count": page.mixed_content_count,
                },
            }
            for page in pages
            if page.page_id in page_map
            and page.mixed_content_count is not None
            and page.mixed_content_count > 0
        ]
        self._add_subtype_finding(
            execution,
            page_map,
            rule_id="inconsistent_url_protocol",
            subtype="mixed_protocol_resources",
            observations=mixed_protocol,
            summary=(
                f"{len(mixed_protocol)} pages reference one or more persisted mixed-protocol "
                "resources."
            ),
            expected_value="HTTPS resources on HTTPS pages",
        )

        for header in SECURITY_HEADER_KEYS:
            observations = [
                {
                    "page_id": str(page.page_id),
                    "evidence_reference": page.evidence_reference,
                    "observed_value": f"{header} absent",
                    "context": {
                        "technical_consistency_type": "missing_security_header",
                        "header": header,
                    },
                }
                for page in pages
                if page.page_id in page_map
                and page.evidence_available
                and page.security_observations
                and not page.security_observations.get(header)
            ]
            if len({item["page_id"] for item in observations}) < MINIMUM_AFFECTED_PAGE_COUNT:
                continue
            self._add_subtype_finding(
                execution,
                page_map,
                rule_id="missing_security_header",
                subtype=f"missing_security_header:{header}",
                observations=observations,
                summary=(
                    f"{len(observations)} pages are missing the {header!r} security header; "
                    "the original page-analysis references are preserved."
                ),
                expected_value=f"a profile-appropriate {header} policy",
            )

        self._add_cohort_consistency_findings(execution, page_map, pages)
        self._add_repeated_runtime_findings(execution, page_map, pages)
        self._add_performance_consistency_findings(execution, page_map, run)
        self._add_accessibility_consistency_findings(execution, page_map, run)

    def _add_cohort_consistency_findings(
        self,
        execution: SiteDiagnosticExecution,
        page_map: dict[UUID, PageEvidence],
        pages: tuple[TechnicalPageEvidence, ...],
    ) -> None:
        cohorts: dict[str, list[TechnicalPageEvidence]] = defaultdict(list)
        for page in pages:
            if page.page_id in page_map and page.evidence_available:
                cohorts[page.page_type].append(page)

        for cohort, cohort_pages in sorted(cohorts.items()):
            signals: tuple[tuple[str, Any], ...] = (
                ("http_status_code", lambda page: page.http_status_code),
                ("content_type_charset", lambda page: _normalize_text(page.content_type)),
                (
                    "cache_policy",
                    lambda page: _normalize_text(
                        str(page.headers.get("cache-control"))
                        if page.headers.get("cache-control") is not None
                        else None
                    ),
                ),
            )
            for signal_name, getter in signals:
                values: dict[str, list[TechnicalPageEvidence]] = defaultdict(list)
                for page in cohort_pages:
                    value = getter(page)
                    if value is not None:
                        values[str(value)].append(page)
                if len(values) <= 1:
                    continue
                observations = [
                    {
                        "page_id": str(page.page_id),
                        "evidence_reference": page.evidence_reference,
                        "observed_value": value,
                        "context": {
                            "technical_consistency_type": signal_name,
                            "page_cohort": cohort,
                        },
                    }
                    for value, grouped_pages in sorted(values.items())
                    for page in grouped_pages
                ]
                self._add_subtype_finding(
                    execution,
                    page_map,
                    rule_id="repeated_issue_pattern",
                    subtype=f"inconsistent_{signal_name}:{cohort}",
                    observations=observations,
                    summary=(
                        f"Comparable {cohort!r} pages expose {len(values)} persisted "
                        f"{signal_name} values."
                    ),
                    expected_value=f"a consistent intended {signal_name} within the cohort",
                    confidence="medium",
                )

            structured_values: dict[str, list[TechnicalPageEvidence]] = defaultdict(list)
            for page in cohort_pages:
                if page.structured_data_present is not None:
                    structured_values[str(page.structured_data_present)].append(page)
            if len(structured_values) > 1:
                observations = [
                    {
                        "page_id": str(page.page_id),
                        "evidence_reference": page.evidence_reference,
                        "observed_value": value,
                        "context": {"page_cohort": cohort},
                    }
                    for value, grouped_pages in sorted(structured_values.items())
                    for page in grouped_pages
                ]
                self._add_subtype_finding(
                    execution,
                    page_map,
                    rule_id="inconsistent_structured_data",
                    subtype=f"inconsistent_structured_data:{cohort}",
                    observations=observations,
                    summary=(f"Comparable {cohort!r} pages disagree on structured-data presence."),
                    expected_value="the intended structured-data policy for the page cohort",
                    confidence="medium",
                )

            header_names = sorted(
                {
                    name
                    for page in cohort_pages
                    for name in page.security_observations
                    if name in SECURITY_HEADER_KEYS
                }
            )
            for header in header_names:
                values: dict[str, list[TechnicalPageEvidence]] = defaultdict(list)
                for page in cohort_pages:
                    value = page.security_observations.get(header)
                    if isinstance(value, str) and value.strip():
                        values[_normalize_text(value) or ""].append(page)
                if len(values) <= 1:
                    continue
                observations = [
                    {
                        "page_id": str(page.page_id),
                        "evidence_reference": page.evidence_reference,
                        "observed_value": value,
                        "context": {
                            "technical_consistency_type": "header_policy",
                            "header": header,
                            "page_cohort": cohort,
                        },
                    }
                    for value, grouped_pages in sorted(values.items())
                    for page in grouped_pages
                ]
                self._add_subtype_finding(
                    execution,
                    page_map,
                    rule_id="inconsistent_security_header_policy",
                    subtype=f"inconsistent_header_policy:{header}:{cohort}",
                    observations=observations,
                    summary=(
                        f"Comparable {cohort!r} pages expose {len(values)} values for "
                        f"security header {header!r}."
                    ),
                    expected_value=f"a consistent intended {header} policy",
                    confidence="medium",
                )

    def _add_repeated_runtime_findings(
        self,
        execution: SiteDiagnosticExecution,
        page_map: dict[UUID, PageEvidence],
        pages: tuple[TechnicalPageEvidence, ...],
    ) -> None:
        console_groups: dict[str, list[tuple[TechnicalPageEvidence, str]]] = defaultdict(list)
        resource_groups: dict[str, list[tuple[TechnicalPageEvidence, dict[str, Any]]]] = (
            defaultdict(list)
        )
        large_groups: dict[str, list[tuple[TechnicalPageEvidence, dict[str, Any]]]] = defaultdict(
            list
        )
        for page in pages:
            if page.page_id not in page_map:
                continue
            for message in page.console_errors:
                signature = _normalize_text(message)
                if signature:
                    console_groups[signature].append((page, message))
            for resource in page.failed_resources:
                signature = compute_fingerprint(
                    {
                        "url": resource.get("url") or resource.get("resource_url"),
                        "status": resource.get("status") or resource.get("status_code"),
                        "error": resource.get("error") or resource.get("failure"),
                    }
                )
                resource_groups[signature].append((page, resource))
            for resource in page.large_resources:
                signature = compute_fingerprint(
                    {
                        "url": resource.get("url") or resource.get("resource_url"),
                        "type": resource.get("type") or resource.get("resource_type"),
                    }
                )
                large_groups[signature].append((page, resource))

        for signature, grouped in sorted(console_groups.items()):
            if len({page.page_id for page, _ in grouped}) < MINIMUM_AFFECTED_PAGE_COUNT:
                continue
            observations = [
                {
                    "page_id": str(page.page_id),
                    "evidence_reference": page.evidence_reference,
                    "observed_value": message,
                    "context": {"console_error_signature": signature},
                }
                for page, message in grouped
            ]
            self._add_subtype_finding(
                execution,
                page_map,
                rule_id="repeated_issue_pattern",
                subtype=f"repeated_console_error:{compute_fingerprint(signature)}",
                observations=observations,
                summary=(
                    f"{len(observations)} page occurrences reference the same normalized "
                    "console-error signature."
                ),
                expected_value="the repeated console error absent",
            )

        for family, grouped_values, label in (
            ("repeated_failed_resource", resource_groups, "failed resource"),
            ("repeated_large_resource", large_groups, "large resource"),
        ):
            for signature, grouped in sorted(grouped_values.items()):
                if len({page.page_id for page, _ in grouped}) < MINIMUM_AFFECTED_PAGE_COUNT:
                    continue
                observations = [
                    {
                        "page_id": str(page.page_id),
                        "resource_url": (resource.get("url") or resource.get("resource_url")),
                        "evidence_reference": page.evidence_reference,
                        "observed_value": label,
                        "context": {
                            "resource_evidence_signature": signature,
                            "resource_status": (
                                resource.get("status") or resource.get("status_code")
                            ),
                        },
                    }
                    for page, resource in grouped
                ]
                self._add_subtype_finding(
                    execution,
                    page_map,
                    rule_id="repeated_issue_pattern",
                    subtype=f"{family}:{signature}",
                    observations=observations,
                    summary=(
                        f"{len(observations)} page occurrences reference the same {label} "
                        "signature."
                    ),
                    expected_value=f"the repeated {label} evidence resolved",
                )

    def _add_performance_consistency_findings(
        self,
        execution: SiteDiagnosticExecution,
        page_map: dict[UUID, PageEvidence],
        run: AnalysisRun,
    ) -> None:
        snapshots = tuple(
            self.db.execute(
                select(PerformanceSnapshot).where(
                    PerformanceSnapshot.analysis_run_id == run.id,
                    PerformanceSnapshot.availability_status == "available",
                )
            )
            .scalars()
            .all()
        )
        page_by_url = {page.normalized_url: page for page in page_map.values()}
        grouped: dict[str, list[tuple[PageEvidence, PerformanceSnapshot]]] = defaultdict(list)
        for snapshot in snapshots:
            metadata = snapshot.provider_metadata or {}
            is_bottleneck = snapshot.rating in {"poor", "needs_improvement"} or bool(
                metadata.get("bottleneck")
            )
            if not is_bottleneck:
                continue
            try:
                normalized_url = _normalize_url(snapshot.url_or_origin)
            except (TypeError, ValueError):
                continue
            page = page_by_url.get(normalized_url)
            if page is not None:
                grouped[snapshot.metric_id].append((page, snapshot))
        for metric_id, group in sorted(grouped.items()):
            if len({page.page_id for page, _ in group}) < MINIMUM_AFFECTED_PAGE_COUNT:
                continue
            observations = [
                {
                    "page_id": str(page.page_id),
                    "evidence_reference": f"performance_snapshot:{snapshot.id}",
                    "observed_value": (
                        snapshot.display_value or str(snapshot.raw_value)
                        if snapshot.raw_value is not None
                        else snapshot.rating or "persisted bottleneck"
                    ),
                    "context": {
                        "performance_metric_id": metric_id,
                        "evidence_type": snapshot.evidence_type,
                        "rating": snapshot.rating,
                    },
                }
                for page, snapshot in group
            ]
            self._add_subtype_finding(
                execution,
                page_map,
                rule_id="repeated_issue_pattern",
                subtype=f"repeated_performance_bottleneck:{metric_id}",
                observations=observations,
                summary=(
                    f"{len(observations)} pages reference persisted poor or explicitly "
                    f"flagged {metric_id!r} performance evidence."
                ),
                expected_value="the persisted performance bottleneck resolved",
            )

    def _add_accessibility_consistency_findings(
        self,
        execution: SiteDiagnosticExecution,
        page_map: dict[UUID, PageEvidence],
        run: AnalysisRun,
    ) -> None:
        rows = self.db.execute(
            select(AccessibilityAudit, AccessibilityFinding)
            .join(
                AccessibilityFinding,
                AccessibilityFinding.audit_id == AccessibilityAudit.id,
            )
            .where(
                AccessibilityAudit.analysis_run_id == run.id,
                AccessibilityAudit.status == "completed",
                AccessibilityFinding.result_type.in_(("violation", "incomplete")),
            )
            .order_by(AccessibilityFinding.provider_rule_id, AccessibilityFinding.id)
        ).all()
        grouped: dict[
            str,
            list[tuple[AccessibilityAudit, AccessibilityFinding]],
        ] = defaultdict(list)
        for audit, finding in rows:
            if audit.page_id in page_map:
                grouped[finding.provider_rule_id].append((audit, finding))
        for provider_rule_id, group in sorted(grouped.items()):
            if len({audit.page_id for audit, _ in group}) < MINIMUM_AFFECTED_PAGE_COUNT:
                continue
            observations = [
                {
                    "page_id": str(audit.page_id),
                    "evidence_reference": f"accessibility_finding:{finding.id}",
                    "observed_value": provider_rule_id,
                    "context": {
                        "provider": audit.provider,
                        "provider_rule_id": provider_rule_id,
                        "result_type": finding.result_type,
                    },
                }
                for audit, finding in group
            ]
            self._add_subtype_finding(
                execution,
                page_map,
                rule_id="repeated_issue_pattern",
                subtype=f"repeated_accessibility_pattern:{provider_rule_id}",
                observations=observations,
                summary=(
                    f"{len(observations)} pages reference original accessibility findings "
                    f"for provider rule {provider_rule_id!r}; this does not claim complete "
                    "accessibility compliance."
                ),
                expected_value="the repeated accessibility finding absent after verification",
            )

    def _availability_findings(
        self,
        execution: SiteDiagnosticExecution,
        page_evidence: tuple[PageEvidence, ...],
        technical_pages: tuple[TechnicalPageEvidence, ...],
        graph: LinkGraphSnapshot,
    ) -> None:
        page_map = {page.page_id: page for page in page_evidence}
        technical_by_id = {page.page_id: page for page in technical_pages}
        insufficient: list[dict[str, Any]] = []
        unavailable_graph: list[dict[str, Any]] = []
        for page in page_evidence:
            technical = technical_by_id.get(page.page_id)
            if technical is None or not technical.evidence_available:
                insufficient.append(
                    {
                        "page_id": str(page.page_id),
                        "evidence_reference": page.evidence_reference,
                        "observed_value": "technical page evidence unavailable",
                        "context": {
                            "unavailable_families": [
                                "canonical_indexability",
                                "technical_consistency",
                            ]
                        },
                    }
                )
            if technical is None or not technical.internal_link_evidence_available:
                unavailable_graph.append(
                    {
                        "page_id": str(page.page_id),
                        "evidence_reference": (
                            technical.evidence_reference
                            if technical is not None
                            else page.evidence_reference
                        ),
                        "observed_value": "outbound internal-link evidence unavailable",
                        "context": {
                            "discovery_run_id": str(graph.discovery_run_id)
                            if graph.discovery_run_id
                            else None,
                            "bounded_discovery_complete": graph.evidence_complete,
                        },
                    }
                )
        self._add_subtype_finding(
            execution,
            page_map,
            rule_id="insufficient_page_evidence",
            subtype="unavailable_canonical_or_technical_evidence",
            observations=insufficient,
            summary=(
                f"{len(insufficient)} eligible pages lack persisted evidence required for "
                "canonical/indexability or technical-consistency conclusions."
            ),
            expected_value="completed persisted page-analysis evidence",
            confidence="unavailable",
        )
        self._add_subtype_finding(
            execution,
            page_map,
            rule_id="unavailable_link_graph_evidence",
            subtype="unavailable_link_graph_evidence",
            observations=unavailable_graph,
            summary=(
                f"{len(unavailable_graph)} eligible pages lack explicit bounded outbound "
                "internal-link evidence."
            ),
            expected_value="explicit internal-edge collection status and preserved targets",
            confidence="unavailable",
        )
        if execution.failed_page_count or not graph.evidence_complete:
            observations = [
                {
                    "page_id": str(page.page_id),
                    "evidence_reference": page.evidence_reference,
                    "observed_value": (
                        f"coverage {execution.evidence_coverage_numerator}/"
                        f"{execution.evidence_coverage_denominator}; "
                        f"graph_complete={graph.evidence_complete}"
                    ),
                }
                for page in page_evidence
            ]
            self._add_subtype_finding(
                execution,
                page_map,
                rule_id="partial_diagnostic_coverage",
                subtype="partial_diagnostic_coverage",
                observations=observations,
                summary=(
                    "Diagnostic coverage or bounded link-graph evidence is partial: "
                    f"{execution.evidence_coverage_numerator}/"
                    f"{execution.evidence_coverage_denominator} pages have base evidence; "
                    f"failed pages={execution.failed_page_count}; "
                    f"link graph complete={graph.evidence_complete}."
                ),
                expected_value="complete prerequisite evidence for every eligible page",
                confidence="unavailable",
            )

    def _add_finding(
        self,
        execution: SiteDiagnosticExecution,
        rule_id: str,
        group_key: str,
        pages: tuple[PageEvidence, ...],
        *,
        observed_value: str,
        expected_value: str,
        summary: str,
        confidence: str,
        scope: DiagnosticScopeEnum,
        context_extra: dict[str, Any] | None = None,
        occurrence_details: tuple[dict[str, Any], ...] | None = None,
    ) -> SiteDiagnosticFinding:
        if occurrence_details is not None and len(occurrence_details) != len(pages):
            raise ValueError("Occurrence details must align with attributed pages.")
        rule = SiteDiagnosticRuleRegistry.get_rule(rule_id)
        affected_count = len({page.page_id for page in pages})
        total_pages = execution.total_page_count
        finding = SiteDiagnosticFinding(
            execution_id=execution.id,
            rule_id=rule.id,
            rule_version=rule.rule_version,
            category=rule.category.value,
            severity=rule.default_severity.value,
            confidence=confidence,
            scope=scope.value,
            title=rule.title,
            description=rule.description,
            why_it_matters=f"{rule.description} Limitation: {rule.limitations}",
            affected_page_count=affected_count,
            total_eligible_page_count=total_pages,
            occurrence_count=len(pages),
            affected_ratio=affected_count / total_pages if total_pages else 0.0,
            evidence_summary=summary,
            evidence_references=[
                {
                    "page_id": str(page.page_id),
                    "normalized_url": page.normalized_url,
                    "evidence_reference": (
                        occurrence_details[index].get("evidence_reference")
                        if occurrence_details
                        else page.evidence_reference
                    )
                    or page.evidence_reference,
                }
                for index, page in enumerate(pages)
            ],
            remediation_guidance=rule.remediation_guidance,
            responsible_role=rule.responsible_role,
            verification_guidance=rule.verification_guidance,
        )
        self.db.add(finding)
        self.db.flush()
        for index, page in enumerate(pages):
            self.db.add(
                self._occurrence(
                    finding,
                    rule,
                    group_key,
                    page,
                    observed_value=observed_value,
                    expected_value=expected_value,
                    context_extra=context_extra,
                    occurrence_detail=(occurrence_details[index] if occurrence_details else None),
                )
            )
        return finding

    @staticmethod
    def _occurrence(
        finding: SiteDiagnosticFinding,
        rule: DiagnosticRuleDefinition,
        group_key: str,
        page: PageEvidence,
        *,
        observed_value: str,
        expected_value: str,
        context_extra: dict[str, Any] | None,
        occurrence_detail: dict[str, Any] | None,
    ) -> SiteDiagnosticOccurrence:
        context = {
            "rule_id": rule.id,
            "group_key": group_key,
            "url_section": page.section,
            "page_type": page.page_type,
            "template_signature": page.template_signature,
        }
        if context_extra:
            context.update(context_extra)
        detail = occurrence_detail or {}
        detail_context = detail.get("context")
        if isinstance(detail_context, dict):
            context.update(detail_context)
        evidence_reference = detail.get("evidence_reference")
        if not isinstance(evidence_reference, str):
            evidence_reference = page.evidence_reference
        detail_supporting_evidence = detail.get("supporting_evidence")
        if not isinstance(detail_supporting_evidence, dict):
            detail_supporting_evidence = {}
        return SiteDiagnosticOccurrence(
            finding_id=finding.id,
            website_page_id=page.page_id,
            normalized_url=page.normalized_url,
            evidence_reference=evidence_reference,
            occurrence_fingerprint=compute_fingerprint(
                {
                    "rule_id": rule.id,
                    "group_key": group_key,
                    "page_id": str(page.page_id),
                    "evidence_reference": evidence_reference,
                    "detail_fingerprint": compute_fingerprint(detail),
                }
            ),
            resource_url=(
                detail.get("resource_url") if isinstance(detail.get("resource_url"), str) else None
            ),
            location=(
                detail.get("location")
                if isinstance(detail.get("location"), str)
                else page.normalized_url
            ),
            context=context,
            observed_value=(
                detail.get("observed_value")
                if isinstance(detail.get("observed_value"), str)
                else observed_value
            ),
            expected_value=(
                detail.get("expected_value")
                if isinstance(detail.get("expected_value"), str)
                else expected_value
            ),
            supporting_evidence={
                "source_page_analysis_run_id": str(page.source_run_id)
                if page.source_run_id
                else None,
                "page_analysis_status": page.page_analysis_status,
                "content_signature_method": EXACT_CONTENT_SIGNATURE_METHOD,
                "content_signature": page.content_signature,
                "content_signature_status": page.content_evidence_status,
                **detail_supporting_evidence,
            },
        )

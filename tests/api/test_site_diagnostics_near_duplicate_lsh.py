"""AT-3: near-duplicate content clustering stays exact (via _jaccard) at
any scale -- large candidate sets only change which pairs get checked
(via a MinHash/LSH pre-filter), never the similarity decision itself.
"""

from uuid import uuid4

from app.services.site_diagnostics_service import (
    NEAR_DUPLICATE_LSH_PREFILTER_PAGE_COUNT,
    PageEvidence,
    SiteDiagnosticsService,
    _lsh_candidate_neighbors,
)


def _page(tokens: frozenset[str], *, url: str | None = None) -> PageEvidence:
    page_id = uuid4()
    return PageEvidence(
        page_id=page_id,
        normalized_url=url or f"https://example.com/{page_id}",
        page_type="content",
        section="content",
        source_run_id=None,
        evidence_reference="test",
        page_analysis_status="completed",
        title=None,
        normalized_title=None,
        title_evidence_available=False,
        meta_description=None,
        normalized_meta_description=None,
        metadata_evidence_available=False,
        h1_count=None,
        heading_evidence_available=False,
        language=None,
        normalized_language=None,
        language_evidence_available=False,
        content_signature=None,
        content_tokens=tokens,
        content_evidence_status="available",
        template_signature=None,
        discovery_evidence_fingerprint="test",
    )


# A large, shared vocabulary so near-identical pages score >= 0.85 Jaccard
# and clearly-different pages score far below it.
_BASE_TOKENS = frozenset(f"shared-word-{i}" for i in range(200))
_DISTINCT_TOKENS = frozenset(f"unrelated-word-{i}" for i in range(200))


def test_small_candidate_set_stays_below_lsh_threshold_and_clusters_correctly() -> None:
    near_dupe_a = _page(_BASE_TOKENS)
    near_dupe_b = _page(_BASE_TOKENS | frozenset({"one-extra-word"}))
    distinct = _page(_DISTINCT_TOKENS)

    clusters = SiteDiagnosticsService._near_duplicate_clusters([near_dupe_a, near_dupe_b, distinct])

    assert len(clusters) == 1
    clustered_ids = {page.page_id for page in clusters[0]}
    assert clustered_ids == {near_dupe_a.page_id, near_dupe_b.page_id}


def test_lsh_prefilter_engages_above_threshold_and_still_finds_real_duplicates() -> None:
    # One genuine near-duplicate pair, surrounded by enough distinct pages
    # to push the candidate count over NEAR_DUPLICATE_LSH_PREFILTER_PAGE_COUNT
    # and engage the LSH path.
    near_dupe_a = _page(_BASE_TOKENS)
    near_dupe_b = _page(_BASE_TOKENS | frozenset({"one-extra-word"}))
    filler = [
        _page(frozenset(f"filler-{i}-word-{j}" for j in range(50)))
        for i in range(NEAR_DUPLICATE_LSH_PREFILTER_PAGE_COUNT + 5)
    ]
    candidates = [near_dupe_a, near_dupe_b, *filler]
    assert len(candidates) > NEAR_DUPLICATE_LSH_PREFILTER_PAGE_COUNT

    clusters = SiteDiagnosticsService._near_duplicate_clusters(candidates)

    assert len(clusters) == 1
    clustered_ids = {page.page_id for page in clusters[0]}
    assert clustered_ids == {near_dupe_a.page_id, near_dupe_b.page_id}


def test_lsh_candidate_neighbors_finds_the_real_near_duplicate_pair() -> None:
    near_dupe_a = _page(_BASE_TOKENS)
    near_dupe_b = _page(_BASE_TOKENS | frozenset({"one-extra-word"}))
    distinct = _page(_DISTINCT_TOKENS)

    neighbors = _lsh_candidate_neighbors([near_dupe_a, near_dupe_b, distinct])

    assert near_dupe_b.page_id in neighbors.get(near_dupe_a.page_id, set())
    assert distinct.page_id not in neighbors.get(near_dupe_a.page_id, set())


def test_lsh_prefilter_never_groups_genuinely_distinct_large_page_sets() -> None:
    pages = [
        _page(frozenset(f"distinct-{i}-word-{j}" for j in range(50)))
        for i in range(NEAR_DUPLICATE_LSH_PREFILTER_PAGE_COUNT + 10)
    ]
    assert len(pages) > NEAR_DUPLICATE_LSH_PREFILTER_PAGE_COUNT

    clusters = SiteDiagnosticsService._near_duplicate_clusters(pages)

    assert clusters == ()

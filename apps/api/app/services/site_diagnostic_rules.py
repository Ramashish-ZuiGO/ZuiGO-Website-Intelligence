import re
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.site_diagnostic import DiagnosticScopeEnum

SEMANTIC_VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
RULE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


class DiagnosticCategoryEnum(StrEnum):
    REPEATED_PATTERN = "repeated_pattern"
    INTERNAL_LINK_GRAPH = "internal_link_graph"
    CANONICAL_INDEXABILITY = "canonical_indexability"
    METADATA_CONTENT = "metadata_content"
    NEAR_DUPLICATE = "near_duplicate"
    TECHNICAL_CONSISTENCY = "technical_consistency"
    EVIDENCE_AVAILABILITY = "evidence_availability"
    # M3 (docs/REPORT_QUALITY_INITIATIVE.md): security-header findings were
    # previously filed under REPEATED_PATTERN, which routed them into the
    # "Repeated and Template Problems" report section instead of "Security
    # and Technical Findings" -- a customer checking the security tab saw
    # zero findings even when real ones existed elsewhere in the report.
    SECURITY = "security"


class DiagnosticSeverityEnum(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class DiagnosticRuleDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    registry_version: str
    rule_version: str
    category: DiagnosticCategoryEnum
    default_severity: DiagnosticSeverityEnum
    supported_scopes: tuple[DiagnosticScopeEnum, ...] = Field(min_length=1)
    detection_method: str
    evidence_requirements: tuple[str, ...] = Field(min_length=1)
    limitations: str
    remediation_guidance: str
    responsible_role: str
    verification_guidance: str
    title: str
    description: str

    @field_validator("id")
    @classmethod
    def validate_rule_id(cls, value: str) -> str:
        normalized = value.strip()
        if not RULE_ID_PATTERN.fullmatch(normalized):
            raise ValueError("Rule ID must be non-empty lower snake case")
        return normalized

    @field_validator("registry_version", "rule_version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        normalized = value.strip()
        if not SEMANTIC_VERSION_PATTERN.fullmatch(normalized):
            raise ValueError("Versions must use semantic MAJOR.MINOR.PATCH format")
        return normalized

    @field_validator(
        "detection_method",
        "limitations",
        "remediation_guidance",
        "responsible_role",
        "verification_guidance",
        "title",
        "description",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Required rule text fields cannot be empty")
        return normalized

    @field_validator("supported_scopes")
    @classmethod
    def validate_supported_scopes(
        cls, value: tuple[DiagnosticScopeEnum, ...]
    ) -> tuple[DiagnosticScopeEnum, ...]:
        if len(value) != len(set(value)):
            raise ValueError("Supported scopes must be unique")
        return value

    @field_validator("evidence_requirements")
    @classmethod
    def validate_evidence_requirements(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized):
            raise ValueError("Evidence requirements cannot contain empty values")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Evidence requirements must be unique")
        return normalized


class SiteDiagnosticRuleRegistry:
    # 1.1.0: added the security category rules (missing_security_header,
    # inconsistent_security_header_policy) -- additive, no existing rule
    # changed. This is NOT one of the locked formula versions in CLAUDE.md.
    VERSION = "1.1.0"
    _rules: ClassVar[dict[str, DiagnosticRuleDefinition]] = {}

    @classmethod
    def register(cls, rule: DiagnosticRuleDefinition) -> None:
        if rule.registry_version != cls.VERSION:
            raise ValueError(
                f"Rule registry version {rule.registry_version} does not match {cls.VERSION}"
            )
        if rule.id in cls._rules:
            raise ValueError(f"Duplicate diagnostic rule ID: {rule.id}")
        cls._rules[rule.id] = rule

    @classmethod
    def get_rule(cls, rule_id: str) -> DiagnosticRuleDefinition:
        try:
            return cls._rules[rule_id]
        except KeyError as exc:
            raise ValueError(f"Unknown diagnostic rule ID: {rule_id}") from exc

    @classmethod
    def get_all_rules(cls) -> tuple[DiagnosticRuleDefinition, ...]:
        return tuple(cls._rules[rule_id] for rule_id in sorted(cls._rules))


def _rule(
    *,
    rule_id: str,
    category: DiagnosticCategoryEnum,
    severity: DiagnosticSeverityEnum,
    scopes: tuple[DiagnosticScopeEnum, ...],
    detection_method: str,
    evidence: tuple[str, ...],
    limitations: str,
    remediation: str,
    role: str,
    verification: str,
    title: str,
    description: str,
) -> DiagnosticRuleDefinition:
    return DiagnosticRuleDefinition(
        id=rule_id,
        registry_version=SiteDiagnosticRuleRegistry.VERSION,
        rule_version="1.0.0",
        category=category,
        default_severity=severity,
        supported_scopes=scopes,
        detection_method=detection_method,
        evidence_requirements=evidence,
        limitations=limitations,
        remediation_guidance=remediation,
        responsible_role=role,
        verification_guidance=verification,
        title=title,
        description=description,
    )


_RULES = (
    _rule(
        rule_id="repeated_issue_pattern",
        category=DiagnosticCategoryEnum.REPEATED_PATTERN,
        severity=DiagnosticSeverityEnum.MEDIUM,
        scopes=(DiagnosticScopeEnum.TEMPLATE, DiagnosticScopeEnum.SITE),
        detection_method="Group stable page-level issue signatures across distinct pages.",
        evidence=("page_id", "rule_signature", "evidence_fingerprint"),
        limitations="A repeated signature does not prove a shared source template.",
        remediation="Investigate the shared implementation before changing every occurrence.",
        role="Engineering lead",
        verification="Re-run the same deterministic signature grouping after remediation.",
        title="Repeated issue pattern",
        description="The same evidence-backed issue occurs across multiple pages.",
    ),
    _rule(
        rule_id="section_issue_pattern",
        category=DiagnosticCategoryEnum.REPEATED_PATTERN,
        severity=DiagnosticSeverityEnum.MEDIUM,
        scopes=(DiagnosticScopeEnum.SECTION, DiagnosticScopeEnum.SITE),
        detection_method="Group stable issue signatures by deterministic URL section.",
        evidence=("normalized_url", "url_section", "rule_signature"),
        limitations="URL sections may not map exactly to application ownership boundaries.",
        remediation="Correct the shared section implementation and verify each attributed page.",
        role="Section owner",
        verification="Confirm the issue signature is absent from every affected section page.",
        title="Repeated section issue",
        description="A consistent issue pattern is concentrated in one site section.",
    ),
    _rule(
        rule_id="template_issue_pattern",
        category=DiagnosticCategoryEnum.REPEATED_PATTERN,
        severity=DiagnosticSeverityEnum.HIGH,
        scopes=(DiagnosticScopeEnum.TEMPLATE, DiagnosticScopeEnum.SITE),
        detection_method="Cluster normalized structural signatures and repeated issue locations.",
        evidence=("page_id", "structural_signature", "normalized_location"),
        limitations=(
            "Deterministic structural similarity identifies a likely, not proven, template."
        ),
        remediation="Fix the responsible shared template or component.",
        role="Frontend engineering",
        verification="Re-analyze every page in the template cluster and compare signatures.",
        title="Shared template issue",
        description="An evidence-backed issue repeats across a deterministic template cluster.",
    ),
    _rule(
        rule_id="missing_security_header",
        category=DiagnosticCategoryEnum.SECURITY,
        severity=DiagnosticSeverityEnum.MEDIUM,
        scopes=(DiagnosticScopeEnum.PAGE, DiagnosticScopeEnum.SITE),
        detection_method=(
            "Inspect each analysed page's persisted HTTP response headers for the recommended "
            "security headers."
        ),
        evidence=("page_id", "header", "evidence_reference"),
        limitations=(
            "Header requirements vary by site architecture; a header may be intentionally "
            "omitted or added by an edge layer not visible to this analysis."
        ),
        remediation=(
            "Configure the missing header at the web server, application, or CDN layer with a "
            "policy appropriate for the site."
        ),
        role="Security engineering",
        verification="Re-run the analysis and confirm the header is present on affected pages.",
        title="Missing security header",
        description="Pages respond without a recommended HTTP security header.",
    ),
    _rule(
        rule_id="inconsistent_security_header_policy",
        category=DiagnosticCategoryEnum.SECURITY,
        severity=DiagnosticSeverityEnum.MEDIUM,
        scopes=(DiagnosticScopeEnum.SITE,),
        detection_method=(
            "Compare persisted security-header values across comparable pages and flag headers "
            "whose values disagree."
        ),
        evidence=("page_id", "header", "observed_value"),
        limitations=(
            "Differing header values can be intentional for specific routes; disagreement "
            "signals a policy to review, not a proven defect."
        ),
        remediation=(
            "Decide the intended site-wide policy for the header and apply it consistently, "
            "documenting any deliberate per-route exceptions."
        ),
        role="Security engineering",
        verification=(
            "Re-run the analysis and confirm comparable pages report one consistent value."
        ),
        title="Inconsistent security header policy",
        description="Comparable pages expose different values for the same security header.",
    ),
    _rule(
        rule_id="broken_internal_link",
        category=DiagnosticCategoryEnum.INTERNAL_LINK_GRAPH,
        severity=DiagnosticSeverityEnum.HIGH,
        scopes=(
            DiagnosticScopeEnum.PAGE,
            DiagnosticScopeEnum.TEMPLATE,
            DiagnosticScopeEnum.SITE,
        ),
        detection_method="Match internal link edges to safely collected target response evidence.",
        evidence=("source_page_id", "target_url", "target_http_status"),
        limitations="Results cover only bounded, safely collected internal-link evidence.",
        remediation="Update, redirect, or remove each broken internal link.",
        role="Web engineering",
        verification=(
            "Re-crawl affected source pages and confirm each target resolves successfully."
        ),
        title="Broken internal link",
        description="An internal link points to a target with deterministic failure evidence.",
    ),
    _rule(
        rule_id="dead_end_page",
        category=DiagnosticCategoryEnum.INTERNAL_LINK_GRAPH,
        severity=DiagnosticSeverityEnum.MEDIUM,
        scopes=(DiagnosticScopeEnum.PAGE, DiagnosticScopeEnum.SITE),
        detection_method=(
            "Find eligible HTML page nodes with zero recorded internal outbound edges."
        ),
        evidence=("page_id", "eligible_page_set", "outbound_internal_edges"),
        limitations="Links outside the bounded evidence set may not be represented.",
        remediation="Add useful contextual links to relevant internal destinations.",
        role="Content strategy",
        verification="Rebuild the link graph and confirm the page has valid outbound edges.",
        title="Dead-end page",
        description="An eligible page has no evidenced outbound internal links.",
    ),
    _rule(
        rule_id="excessive_click_depth",
        category=DiagnosticCategoryEnum.INTERNAL_LINK_GRAPH,
        severity=DiagnosticSeverityEnum.MEDIUM,
        scopes=(DiagnosticScopeEnum.PAGE, DiagnosticScopeEnum.SITE),
        detection_method="Compute deterministic shortest-path depth from configured entry pages.",
        evidence=("page_id", "entry_page_ids", "shortest_path"),
        limitations="Interpretation depends on the selected website profile and crawl coverage.",
        remediation="Add relevant navigation paths that reduce depth from an entry page.",
        role="Information architecture",
        verification="Recompute shortest paths under the same profile and evidence set.",
        title="Excessive internal-link depth",
        description="A page exceeds the selected profile's evidenced click-depth threshold.",
    ),
    _rule(
        rule_id="internal_redirect_link",
        category=DiagnosticCategoryEnum.INTERNAL_LINK_GRAPH,
        severity=DiagnosticSeverityEnum.LOW,
        scopes=(
            DiagnosticScopeEnum.PAGE,
            DiagnosticScopeEnum.TEMPLATE,
            DiagnosticScopeEnum.SITE,
        ),
        detection_method="Match internal edges to bounded redirect-chain evidence.",
        evidence=("source_page_id", "target_url", "redirect_chain"),
        limitations="Only safely followed redirect chains are evaluated.",
        remediation="Point internal links directly to the preferred final URL.",
        role="Web engineering",
        verification=(
            "Re-crawl the source page and confirm the edge targets the final URL directly."
        ),
        title="Internal link uses a redirect",
        description="An internal edge resolves through one or more redirects.",
    ),
    _rule(
        rule_id="orphan_page",
        category=DiagnosticCategoryEnum.INTERNAL_LINK_GRAPH,
        severity=DiagnosticSeverityEnum.HIGH,
        scopes=(DiagnosticScopeEnum.PAGE, DiagnosticScopeEnum.SITE),
        detection_method="Find discovered eligible page nodes with zero internal inbound edges.",
        evidence=("page_id", "discovery_source", "inbound_internal_edges"),
        limitations="Orphan status is limited to the bounded discovery and link evidence set.",
        remediation="Add relevant internal links from reachable pages.",
        role="Information architecture",
        verification="Rebuild the link graph and confirm at least one reachable inbound path.",
        title="Orphan page",
        description="A discovered eligible page has no evidenced inbound internal link.",
    ),
    _rule(
        rule_id="canonical_chain",
        category=DiagnosticCategoryEnum.CANONICAL_INDEXABILITY,
        severity=DiagnosticSeverityEnum.MEDIUM,
        scopes=(DiagnosticScopeEnum.PAGE, DiagnosticScopeEnum.SITE),
        detection_method=(
            "Resolve canonical edges inside the evidence set and detect multi-hop chains."
        ),
        evidence=("page_id", "canonical_url", "canonical_target_canonical_url"),
        limitations="Targets outside safely collected evidence cannot be followed.",
        remediation="Point the source canonical directly to the final preferred URL.",
        role="Technical SEO",
        verification="Re-analyze the source and target and confirm a single canonical hop.",
        title="Canonical chain",
        description="A canonical target declares another canonical target.",
    ),
    _rule(
        rule_id="canonical_to_non_indexable",
        category=DiagnosticCategoryEnum.CANONICAL_INDEXABILITY,
        severity=DiagnosticSeverityEnum.HIGH,
        scopes=(DiagnosticScopeEnum.PAGE, DiagnosticScopeEnum.SITE),
        detection_method="Compare canonical targets with collected status and robots evidence.",
        evidence=("page_id", "canonical_url", "target_indexability_evidence"),
        limitations="This reports technical signals, not actual search-engine index status.",
        remediation=(
            "Use an indexable preferred target or correct the target's conflicting signals."
        ),
        role="Technical SEO",
        verification="Confirm the canonical target returns successful, indexable evidence.",
        title="Canonical targets a non-indexable page",
        description=(
            "The declared canonical target has conflicting technical indexability evidence."
        ),
    ),
    _rule(
        rule_id="conflicting_canonical",
        category=DiagnosticCategoryEnum.CANONICAL_INDEXABILITY,
        severity=DiagnosticSeverityEnum.HIGH,
        scopes=(
            DiagnosticScopeEnum.PAGE,
            DiagnosticScopeEnum.TEMPLATE,
            DiagnosticScopeEnum.SITE,
        ),
        detection_method="Compare canonical declarations from preserved deterministic sources.",
        evidence=("page_id", "canonical_declarations", "evidence_sources"),
        limitations="Dynamically injected declarations require rendered evidence.",
        remediation="Emit exactly one consistent canonical declaration.",
        role="Frontend engineering",
        verification="Inspect source and rendered evidence and confirm one canonical target.",
        title="Conflicting canonical declarations",
        description="A page exposes more than one distinct canonical target.",
    ),
    _rule(
        rule_id="indexability_signal_conflict",
        category=DiagnosticCategoryEnum.CANONICAL_INDEXABILITY,
        severity=DiagnosticSeverityEnum.HIGH,
        scopes=(
            DiagnosticScopeEnum.PAGE,
            DiagnosticScopeEnum.TEMPLATE,
            DiagnosticScopeEnum.SITE,
        ),
        detection_method="Compare robots, status, canonical, and eligibility signals per page.",
        evidence=("page_id", "robots_directives", "http_status", "canonical_url"),
        limitations="The result represents technical consistency, not actual index inclusion.",
        remediation="Align robots, response, eligibility, and canonical signals with page intent.",
        role="Technical SEO",
        verification="Re-analyze all signals and confirm they express one indexability intent.",
        title="Conflicting indexability signals",
        description="Technical evidence for a page expresses incompatible indexing intent.",
    ),
    _rule(
        rule_id="invalid_canonical",
        category=DiagnosticCategoryEnum.CANONICAL_INDEXABILITY,
        severity=DiagnosticSeverityEnum.HIGH,
        scopes=(DiagnosticScopeEnum.PAGE, DiagnosticScopeEnum.TEMPLATE),
        detection_method="Validate canonical syntax and normalization without network inference.",
        evidence=("page_id", "canonical_raw_value", "canonical_normalization_result"),
        limitations="A syntactically valid canonical may still be strategically incorrect.",
        remediation="Provide one absolute, normalized canonical URL for the preferred page.",
        role="Frontend engineering",
        verification="Re-parse the canonical and confirm deterministic normalization succeeds.",
        title="Invalid canonical URL",
        description="A canonical declaration cannot be safely normalized as a valid URL.",
    ),
    _rule(
        rule_id="missing_canonical",
        category=DiagnosticCategoryEnum.CANONICAL_INDEXABILITY,
        severity=DiagnosticSeverityEnum.MEDIUM,
        scopes=(DiagnosticScopeEnum.PAGE, DiagnosticScopeEnum.TEMPLATE),
        detection_method="Check preserved source and rendered canonical evidence for absence.",
        evidence=("page_id", "canonical_source_evidence", "canonical_rendered_evidence"),
        limitations="Canonical strategy may intentionally omit tags on some page types.",
        remediation="Add the profile-appropriate preferred canonical declaration.",
        role="Technical SEO",
        verification="Re-analyze source and rendered evidence and confirm the intended canonical.",
        title="Missing canonical declaration",
        description="No canonical declaration is present in the available page evidence.",
    ),
    _rule(
        rule_id="duplicate_meta_description_group",
        category=DiagnosticCategoryEnum.METADATA_CONTENT,
        severity=DiagnosticSeverityEnum.MEDIUM,
        scopes=(DiagnosticScopeEnum.TEMPLATE, DiagnosticScopeEnum.SITE),
        detection_method="Group exact normalized non-empty meta descriptions across page IDs.",
        evidence=("page_id", "normalized_meta_description"),
        limitations="Exact matching does not assess semantic quality or search snippets.",
        remediation="Write page-specific descriptions appropriate to each page's purpose.",
        role="Content strategy",
        verification="Re-analyze the group and confirm each intended description is unique.",
        title="Duplicate meta descriptions",
        description="Multiple pages share the same normalized meta description.",
    ),
    _rule(
        rule_id="duplicate_title_group",
        category=DiagnosticCategoryEnum.METADATA_CONTENT,
        severity=DiagnosticSeverityEnum.MEDIUM,
        scopes=(DiagnosticScopeEnum.TEMPLATE, DiagnosticScopeEnum.SITE),
        detection_method="Group exact normalized non-empty title values across page IDs.",
        evidence=("page_id", "normalized_page_title"),
        limitations="Exact matching does not detect semantically similar titles.",
        remediation="Give each indexable page a specific, descriptive title.",
        role="Content strategy",
        verification="Re-analyze the group and confirm each intended title is unique.",
        title="Duplicate page titles",
        description="Multiple pages share the same normalized title.",
    ),
    _rule(
        rule_id="missing_h1",
        category=DiagnosticCategoryEnum.METADATA_CONTENT,
        severity=DiagnosticSeverityEnum.MEDIUM,
        scopes=(DiagnosticScopeEnum.PAGE, DiagnosticScopeEnum.TEMPLATE),
        detection_method="Count H1 elements in preserved deterministic heading evidence.",
        evidence=("page_id", "heading_structure"),
        limitations="Automated checks cannot determine whether a heading is editorially effective.",
        remediation="Add one descriptive primary H1 appropriate to the page.",
        role="Content engineering",
        verification="Re-analyze heading evidence and confirm one intended H1 is present.",
        title="Missing H1 heading",
        description="The available heading evidence contains no H1.",
    ),
    _rule(
        rule_id="missing_meta_description",
        category=DiagnosticCategoryEnum.METADATA_CONTENT,
        severity=DiagnosticSeverityEnum.MEDIUM,
        scopes=(DiagnosticScopeEnum.PAGE, DiagnosticScopeEnum.TEMPLATE),
        detection_method="Check normalized meta-description evidence for absence or emptiness.",
        evidence=("page_id", "meta_description"),
        limitations="Presence alone does not guarantee a search engine will use the description.",
        remediation="Add a concise description aligned with the page's content and purpose.",
        role="Content strategy",
        verification="Re-analyze the page and confirm a non-empty description is preserved.",
        title="Missing meta description",
        description="No non-empty meta description exists in the available evidence.",
    ),
    _rule(
        rule_id="missing_title",
        category=DiagnosticCategoryEnum.METADATA_CONTENT,
        severity=DiagnosticSeverityEnum.HIGH,
        scopes=(DiagnosticScopeEnum.PAGE, DiagnosticScopeEnum.TEMPLATE),
        detection_method="Check normalized title evidence for absence or emptiness.",
        evidence=("page_id", "page_title"),
        limitations="A present title still requires editorial review for usefulness.",
        remediation="Add a unique, descriptive title for the page.",
        role="Content strategy",
        verification="Re-analyze the page and confirm a non-empty title is preserved.",
        title="Missing page title",
        description="No non-empty title exists in the available page evidence.",
    ),
    _rule(
        rule_id="multiple_h1",
        category=DiagnosticCategoryEnum.METADATA_CONTENT,
        severity=DiagnosticSeverityEnum.LOW,
        scopes=(DiagnosticScopeEnum.PAGE, DiagnosticScopeEnum.TEMPLATE),
        detection_method="Count H1 elements in preserved deterministic heading evidence.",
        evidence=("page_id", "heading_structure"),
        limitations="Multiple H1 elements are not always invalid and require contextual review.",
        remediation="Use the selected profile's heading convention consistently.",
        role="Content engineering",
        verification="Re-analyze headings and manually confirm the resulting hierarchy.",
        title="Multiple H1 headings",
        description="The available heading evidence contains more than one H1.",
    ),
    _rule(
        rule_id="exact_duplicate_content_group",
        category=DiagnosticCategoryEnum.NEAR_DUPLICATE,
        severity=DiagnosticSeverityEnum.HIGH,
        scopes=(DiagnosticScopeEnum.TEMPLATE, DiagnosticScopeEnum.SITE),
        detection_method="Group identical versioned normalized-content signatures.",
        evidence=("page_id", "content_signature", "signature_version"),
        limitations=(
            "Boilerplate removal and normalization can hide meaningful presentation differences."
        ),
        remediation="Consolidate duplicates or make each page's primary content distinct.",
        role="Content strategy",
        verification="Recompute signatures with the same version and confirm groups are resolved.",
        title="Exact duplicate content group",
        description="Multiple pages have the same deterministic normalized-content signature.",
    ),
    _rule(
        rule_id="near_duplicate_content_group",
        category=DiagnosticCategoryEnum.NEAR_DUPLICATE,
        severity=DiagnosticSeverityEnum.MEDIUM,
        scopes=(DiagnosticScopeEnum.TEMPLATE, DiagnosticScopeEnum.SITE),
        detection_method="Cluster versioned token signatures using a fixed profile threshold.",
        evidence=("page_id", "content_signature", "similarity_ratio", "threshold_profile"),
        limitations=(
            "Deterministic similarity can produce false positives and needs editorial review."
        ),
        remediation="Differentiate primary content or consolidate pages with the same purpose.",
        role="Content strategy",
        verification="Recompute similarity with the same version and review remaining clusters.",
        title="Near-duplicate content group",
        description="Multiple pages exceed the selected deterministic similarity threshold.",
    ),
    _rule(
        rule_id="inconsistent_language_declaration",
        category=DiagnosticCategoryEnum.TECHNICAL_CONSISTENCY,
        severity=DiagnosticSeverityEnum.MEDIUM,
        scopes=(DiagnosticScopeEnum.TEMPLATE, DiagnosticScopeEnum.SITE),
        detection_method=(
            "Aggregate normalized document-language declarations by deterministic cohort."
        ),
        evidence=("page_id", "document_language", "page_cohort"),
        limitations="Multilingual sites require profile-aware cohorts and manual intent review.",
        remediation="Declare the correct language consistently for each intended cohort.",
        role="Frontend engineering",
        verification="Re-analyze each cohort and confirm declarations match intended languages.",
        title="Inconsistent language declarations",
        description="Comparable pages use inconsistent document-language declarations.",
    ),
    _rule(
        rule_id="inconsistent_preferred_host",
        category=DiagnosticCategoryEnum.TECHNICAL_CONSISTENCY,
        severity=DiagnosticSeverityEnum.HIGH,
        scopes=(DiagnosticScopeEnum.SITE,),
        detection_method="Compare normalized final and canonical hosts across eligible pages.",
        evidence=("page_id", "final_host", "canonical_host"),
        limitations="Verified subdomains may intentionally use distinct hosts.",
        remediation="Apply the intended preferred host consistently within each allowed origin.",
        role="Platform engineering",
        verification="Re-analyze final and canonical hosts for every affected page.",
        title="Inconsistent preferred host",
        description="Eligible pages disagree on the preferred normalized host.",
    ),
    _rule(
        rule_id="inconsistent_structured_data",
        category=DiagnosticCategoryEnum.TECHNICAL_CONSISTENCY,
        severity=DiagnosticSeverityEnum.LOW,
        scopes=(DiagnosticScopeEnum.TEMPLATE, DiagnosticScopeEnum.SITE),
        detection_method="Compare normalized structured-data type sets within page cohorts.",
        evidence=("page_id", "structured_data_types", "page_cohort"),
        limitations="Different page purposes can legitimately require different schemas.",
        remediation="Align structured-data presence and types within equivalent page cohorts.",
        role="SEO engineering",
        verification="Re-analyze the cohort and validate intended schemas independently.",
        title="Inconsistent structured data",
        description="Comparable pages expose inconsistent structured-data type sets.",
    ),
    _rule(
        rule_id="inconsistent_trailing_slash",
        category=DiagnosticCategoryEnum.TECHNICAL_CONSISTENCY,
        severity=DiagnosticSeverityEnum.LOW,
        scopes=(DiagnosticScopeEnum.SITE,),
        detection_method=(
            "Compare normalized internal edges, final URLs, and canonicals by path identity."
        ),
        evidence=("page_id", "normalized_path", "final_url", "canonical_url"),
        limitations=(
            "Distinct slash variants can be intentional when they identify different resources."
        ),
        remediation="Use one intended slash convention in links, redirects, and canonicals.",
        role="Platform engineering",
        verification="Rebuild URL evidence and confirm one convention per path identity.",
        title="Inconsistent trailing-slash convention",
        description="Equivalent page paths use conflicting trailing-slash forms.",
    ),
    _rule(
        rule_id="inconsistent_url_protocol",
        category=DiagnosticCategoryEnum.TECHNICAL_CONSISTENCY,
        severity=DiagnosticSeverityEnum.HIGH,
        scopes=(DiagnosticScopeEnum.SITE,),
        detection_method="Compare normalized internal edges, final URLs, and canonical protocols.",
        evidence=("page_id", "final_url", "canonical_url", "internal_edge_urls"),
        limitations="The check covers only approved origins represented by preserved evidence.",
        remediation="Use HTTPS consistently in internal links, redirects, and canonicals.",
        role="Platform engineering",
        verification="Rebuild URL evidence and confirm no unintended HTTP variants remain.",
        title="Inconsistent URL protocol",
        description="Eligible site evidence mixes HTTP and HTTPS URL variants.",
    ),
    _rule(
        rule_id="insufficient_page_evidence",
        category=DiagnosticCategoryEnum.EVIDENCE_AVAILABILITY,
        severity=DiagnosticSeverityEnum.INFO,
        scopes=(DiagnosticScopeEnum.PAGE, DiagnosticScopeEnum.SITE),
        detection_method="Compare required rule inputs with preserved evidence available per page.",
        evidence=("page_id", "required_evidence_keys", "available_evidence_keys"),
        limitations=(
            "This records missing evidence and does not infer a successful diagnostic result."
        ),
        remediation="Complete the prerequisite analysis stage or correct its failure.",
        role="Analysis operations",
        verification="Repeat evidence collection and confirm required keys are available.",
        title="Insufficient page evidence",
        description="A page lacks evidence required for one or more deterministic diagnostics.",
    ),
    _rule(
        rule_id="partial_diagnostic_coverage",
        category=DiagnosticCategoryEnum.EVIDENCE_AVAILABILITY,
        severity=DiagnosticSeverityEnum.INFO,
        scopes=(DiagnosticScopeEnum.SITE,),
        detection_method=(
            "Compare processed evidence pages with the explicit eligible-page denominator."
        ),
        evidence=("eligible_page_count", "processed_page_count", "failed_page_count"),
        limitations="Coverage describes evidence availability, not site quality or compliance.",
        remediation="Resolve failed or skipped prerequisites and repeat the diagnostic execution.",
        role="Analysis operations",
        verification=(
            "Confirm the reported numerator and denominator match persisted page outcomes."
        ),
        title="Partial diagnostic coverage",
        description=(
            "Deterministic diagnostics processed fewer pages than the eligible denominator."
        ),
    ),
    _rule(
        rule_id="unavailable_content_signature_evidence",
        category=DiagnosticCategoryEnum.EVIDENCE_AVAILABILITY,
        severity=DiagnosticSeverityEnum.INFO,
        scopes=(DiagnosticScopeEnum.PAGE, DiagnosticScopeEnum.SITE),
        detection_method=(
            "Record pages lacking the versioned content signature required for comparison."
        ),
        evidence=("page_id", "content_signature_status", "signature_version"),
        limitations="Near-duplicate conclusions are unavailable for pages without signatures.",
        remediation="Complete deterministic content extraction and signature generation.",
        role="Analysis operations",
        verification="Confirm every eligible comparison page has a versioned signature.",
        title="Content-signature evidence unavailable",
        description="Near-duplicate analysis cannot evaluate all eligible pages.",
    ),
    _rule(
        rule_id="unavailable_link_graph_evidence",
        category=DiagnosticCategoryEnum.EVIDENCE_AVAILABILITY,
        severity=DiagnosticSeverityEnum.INFO,
        scopes=(DiagnosticScopeEnum.PAGE, DiagnosticScopeEnum.SITE),
        detection_method="Record eligible pages without bounded internal-edge evidence.",
        evidence=("page_id", "link_evidence_status", "discovery_run_id"),
        limitations="Link-graph conclusions are unavailable where edge evidence is absent.",
        remediation="Complete bounded discovery and page link extraction.",
        role="Analysis operations",
        verification="Confirm every eligible graph node has explicit edge collection status.",
        title="Link-graph evidence unavailable",
        description="Internal-link diagnostics cannot evaluate all eligible pages.",
    ),
)

for _definition in _RULES:
    SiteDiagnosticRuleRegistry.register(_definition)

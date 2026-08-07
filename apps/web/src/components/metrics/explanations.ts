import type { MetricDefinition } from "./types";

export interface ExplanationContent {
  shortTooltip: string;
  meaning: string;
  included?: string;
  excluded?: string;
  calculation?: string;
  interpretation?: string;
  limitation?: string;
  example?: string;
  detailsLink?: string;
}

interface ExplanationQualityRequirements {
  requireCalculation?: boolean;
  requireExclusion?: boolean;
  visibleDescription?: string;
}

interface ExplanationRegistryEntry extends ExplanationQualityRequirements {
  conceptId: string;
  content: ExplanationContent;
}

function normalizedText(value: string): string {
  return value
    .trim()
    .toLocaleLowerCase()
    .replace(/[.!?]+$/g, "")
    .replace(/\s+/g, " ");
}

function explanationSentences(value: string): string[] {
  return value
    .split(/(?<=[.!?])\s+/)
    .map(normalizedText)
    .filter(Boolean);
}

function detailedExplanationValues(content: ExplanationContent): string[] {
  return [
    content.meaning,
    content.included,
    content.excluded,
    content.calculation,
    content.interpretation,
    content.limitation,
    content.example,
  ].filter((value): value is string => Boolean(value));
}

export function validateExplanationContent(
  visibleLabel: string,
  content: ExplanationContent,
  requirements: ExplanationQualityRequirements = {},
): string[] {
  const issues: string[] = [];
  if (normalizedText(content.shortTooltip) === normalizedText(visibleLabel)) {
    issues.push("The short tooltip must add information beyond the visible label.");
  }
  if (
    requirements.visibleDescription &&
    normalizedText(content.shortTooltip) ===
      normalizedText(requirements.visibleDescription)
  ) {
    issues.push(
      "The short tooltip must add information beyond the visible description.",
    );
  }
  if (!content.meaning.trim()) {
    issues.push("A specific meaning is required.");
  }
  if (requirements.requireExclusion && !content.excluded?.trim()) {
    issues.push("Exclusion details are required for this concept.");
  }
  if (requirements.requireCalculation && !content.calculation?.trim()) {
    issues.push("Calculation or determination details are required for this concept.");
  }
  const tooltipSentences = new Set(explanationSentences(content.shortTooltip));
  const repeatedSentence = detailedExplanationValues(content)
    .flatMap(explanationSentences)
    .some((sentence) => tooltipSentences.has(sentence));
  if (repeatedSentence) {
    issues.push("The short tooltip sentence must not be repeated in the detailed dialog.");
  }
  return issues;
}

export function validateExplanationSet(
  entries: ExplanationRegistryEntry[],
): string[] {
  const issues: string[] = [];
  const detailedContentOwners = new Map<string, string>();
  for (const entry of entries) {
    const entryIssues = validateExplanationContent(
      entry.conceptId,
      entry.content,
      entry,
    );
    issues.push(...entryIssues.map((issue) => `${entry.conceptId}: ${issue}`));
    const fingerprint = detailedExplanationValues(entry.content)
      .map(normalizedText)
      .join("|");
    const existingOwner = detailedContentOwners.get(fingerprint);
    if (existingOwner && existingOwner !== entry.conceptId) {
      issues.push(
        `${entry.conceptId}: detailed content duplicates unrelated concept ${existingOwner}.`,
      );
    } else {
      detailedContentOwners.set(fingerprint, entry.conceptId);
    }
  }
  return issues;
}

export function assertExplanationContentQuality(
  visibleLabel: string,
  content: ExplanationContent,
  requirements: ExplanationQualityRequirements = {},
): void {
  const issues = validateExplanationContent(visibleLabel, content, requirements);
  if (issues.length > 0) {
    throw new Error(`Invalid explanation for ${visibleLabel}: ${issues.join(" ")}`);
  }
}

const CONCEPT_EXPLANATIONS: Record<string, ExplanationContent> = {
  eligible_html_pages: {
    shortTooltip: "See which discovered URLs qualify for browser-based page analysis.",
    meaning:
      "Internal HTML pages suitable for website analysis.",
    included:
      "Same-site URLs confirmed or strongly evidenced as HTML pages.",
    excluded:
      "PDFs, images, videos, external links, duplicate URLs, unsafe targets and unsupported resources are tracked separately.",
    calculation:
      "A URL becomes eligible after normalization, scope validation, final-response inspection and HTML document classification.",
    interpretation:
      "This count represents pages that can enter page and browser analysis. It is not the number of raw URLs discovered.",
    limitation:
      "A URL may remain unclassified when navigation or content-type evidence is unavailable.",
  },
  website_coverage: {
    shortTooltip: "See how much of the discovered eligible HTML-page set was analysed.",
    meaning:
      "The share of discovered eligible HTML pages successfully analysed in this run.",
    included:
      "Eligible scheduled HTML pages with the required successful page-analysis evidence.",
    excluded:
      "Documents, media assets, external URLs, duplicate URLs and pages that were never eligible are outside this percentage.",
    calculation:
      "Successfully analysed eligible HTML pages divided by eligible HTML pages retained by this discovery execution, multiplied by 100.",
    interpretation:
      "A partial value means one or more eligible pages failed, remained incomplete or were not scheduled.",
    limitation:
      "When discovery is partial, failed or inconclusive, this is analysed-page coverage only; full-site coverage remains unknown.",
  },
  evidence_completeness: {
    shortTooltip: "See which required evidence groups were available for this report.",
    meaning:
      "The share of required evidence groups successfully collected, such as performance, accessibility, diagnostics and browser evidence.",
    included:
      "Each required evidence group that has sufficient persisted data for the selected analysis profile.",
    excluded:
      "Page counts and asset counts are not used directly; this measure is separate from website coverage.",
    calculation:
      "Available required evidence groups divided by all required evidence groups, multiplied by 100.",
    interpretation:
      "A report can have complete page coverage but lower evidence completeness when a provider, engine or diagnostic source is unavailable.",
    limitation:
      "The required groups depend on the workflow and configured capabilities for the run.",
  },
  browser_coverage: {
    shortTooltip: "See how many eligible HTML pages each selected engine actually tested.",
    meaning:
      "The share of scheduled browser-eligible HTML pages tested by each selected browser engine.",
    included:
      "Navigation attempts for every scheduled eligible HTML page in Chromium, Firefox and WebKit when those engines are available.",
    excluded:
      "PDFs, media assets and engines unavailable in the current environment are not treated as website failures.",
    calculation:
      "Tested pages divided by browser-eligible pages, reported separately for each engine.",
    interpretation:
      "An unavailable engine was not executed and must not be read as passed, supported or failed.",
    limitation:
      "Engine testing does not prove support for every branded browser version or device.",
  },
  report_confidence: {
    shortTooltip: "See why reliable formulas can still produce a report with incomplete evidence.",
    meaning:
      "An overall reliability indicator for the evidence supporting the report.",
    included:
      "Website coverage, browser coverage, evidence completeness and unavailable data sources.",
    excluded:
      "Formula determinism is reported separately and does not automatically make the evidence complete.",
    calculation:
      "The report uses the most limiting retained coverage or availability component rather than averaging missing evidence away.",
    interpretation:
      "A lower value calls for caution when acting on absences or comparing this run with another run.",
    limitation:
      "Confidence describes retained evidence reliability, not the probability that every finding is correct.",
  },
  occurrences: {
    shortTooltip: "Distinguish a unique problem from every place where it was detected.",
    meaning:
      "The total number of times a finding was detected across pages, elements, resources or browser engines.",
    included:
      "Every retained page-level occurrence associated with the stable finding identity.",
    excluded:
      "The unique-finding count is not repeated for each occurrence, and unavailable evidence is not invented as an occurrence.",
    calculation: "Count of persisted occurrence records linked to the finding.",
    interpretation:
      "One unique finding can have many occurrences, so this number can be much larger than the finding count.",
    limitation:
      "The count covers only analysed evidence and may increase when coverage improves.",
  },
  unique_findings: {
    shortTooltip: "Separate stable problem types from their page-level occurrences.",
    meaning:
      "The number of distinct retained problems after deterministic grouping by finding identity.",
    included:
      "Each verified finding identity once, even when it affects many pages, elements or browser engines.",
    excluded:
      "Repeated occurrences of the same problem do not create additional unique findings, and unavailable evidence is not treated as a finding.",
    calculation:
      "Count of distinct persisted finding identities in the immutable report snapshot.",
    interpretation:
      "Compare this value with occurrences and affected pages to understand variety, repetition and breadth.",
    limitation:
      "The count covers only evidence collected in this run and may change when coverage or rule versions change.",
  },
  accessibility_inapplicable_rules: {
    shortTooltip: "Understand why an automated rule can be inapplicable without passing or failing.",
    meaning:
      "Automated accessibility rules whose target condition was not present in the analysed page structure.",
    included: "Rule results explicitly returned as inapplicable by the automated audit.",
    excluded:
      "These are not pages, violations, passes or checks requiring manual review.",
    calculation: "Sum of persisted inapplicable automated rule results across completed audits.",
    interpretation:
      "A high count describes page structure and rule applicability; it is not an accessibility-quality score.",
    limitation:
      "Automated results cannot establish complete accessibility compliance.",
  },
  partial_browser_result: {
    shortTooltip: "See why a loaded page may still have an incomplete browser result.",
    meaning:
      "The page loaded, but one or more browser checks found incomplete behavior or evidence.",
    included:
      "Failed resources, console errors, layout problems, unavailable expected elements and other retained engine evidence.",
    excluded:
      "A partial result is neither a full pass nor necessarily a navigation failure.",
    interpretation:
      "Open the finding occurrences to see the affected engine, URL and exact observed condition.",
    limitation:
      "Results describe the tested engine and viewport combinations only.",
  },
  report_executive_summary: {
    shortTooltip: "See how the report condenses its most decision-relevant evidence.",
    meaning:
      "A business-level synopsis of site health, coverage, leading risks and recommended next actions.",
    included:
      "The overall score, five category scores, coverage indicators, top verified problems and top actions.",
    excluded:
      "Raw provider payloads, internal execution identifiers and complete occurrence tables remain in Technical Details or exports.",
    interpretation:
      "Use this section to orient decisions, then open the linked evidence before assigning work.",
    limitation:
      "The summary inherits every unavailable or partial evidence condition shown elsewhere in the report.",
    detailsLink: "#top-findings",
  },
  report_website_coverage: {
    shortTooltip: "Inspect exactly which discovered resources entered page analysis.",
    meaning:
      "An accounting of discovered URLs from normalization through eligibility, scheduling and analysis.",
    included:
      "Eligible HTML pages plus separately identified documents, media assets, duplicates and failed classifications.",
    excluded:
      "External and unsafe targets are never included in the eligible HTML denominator.",
    interpretation:
      "Use the inventory to verify what was analysed, excluded, failed or classified as a non-page resource.",
    limitation:
      "Discovery is bounded by origin rules, safety controls and retained crawl evidence; incomplete discovery cannot establish full-site coverage.",
    detailsLink: "#page-results",
  },
  report_scores: {
    shortTooltip: "Understand how evidence contributes to the overall and category scores.",
    meaning:
      "Deterministic x/100 results for overall health and the five scored categories.",
    included:
      "Only persisted metric contributions accepted by Overall Score Formula v1.0.0.",
    excluded:
      "Report confidence, missing evidence and narrative interpretation are not silently converted into score points.",
    interpretation:
      "Use category scores to locate weak areas, then inspect contribution and finding evidence before remediation.",
    limitation:
      "Scores summarize the selected profile and evidence available at the time of the run.",
    detailsLink: "#technical-details",
  },
  report_top_findings: {
    shortTooltip: "See which verified problems currently carry the greatest severity.",
    meaning:
      "A concise view of up to five retained critical or high-severity findings.",
    included:
      "Stable finding identities with affected-page and occurrence counts.",
    excluded:
      "Lower-severity and remaining findings stay searchable and paginated under View All Findings.",
    interpretation:
      "Treat this as a triage view; open the evidence and remediation fields before implementation.",
    limitation:
      "Severity alone does not replace the Action Plan priority calculation.",
    detailsLink: "#all-findings",
  },
  report_browser_compatibility: {
    shortTooltip: "Compare observed behavior across the engines selected for this run.",
    meaning:
      "Engine-specific navigation and rendering evidence for eligible HTML pages.",
    included:
      "Attempted, tested, partial, failed, inconclusive and unavailable page states for each requested engine.",
    excluded:
      "Untested engines and branded browser versions are never claimed as supported.",
    interpretation:
      "Use exact page occurrences to identify whether a difference is isolated or repeated.",
    limitation:
      "Environment restrictions can make an engine unavailable independently of website behavior.",
    detailsLink: "#page-results",
  },
  report_page_inventory: {
    shortTooltip: "Verify every discovered internal resource and its analysis disposition.",
    meaning:
      "A resource-by-resource inventory showing eligibility, analysis, exclusion and asset classification.",
    included:
      "Eligible HTML pages, documents, media assets and persisted failure or exclusion reasons.",
    excluded:
      "External, unsafe and duplicate targets do not inflate the eligible-page denominator.",
    interpretation:
      "Use this section to confirm exactly what was and was not included in the report.",
    limitation:
      "Only evidence retained by the bounded discovery and analysis run can be listed.",
  },
  report_action_plan: {
    shortTooltip: "See how verified findings become prioritised, assignable work.",
    meaning: "A ranked set of remediation actions derived from retained findings.",
    included:
      "Urgency, impact, effort, responsible role, dependencies and verification guidance.",
    excluded:
      "User confirmation alone does not prove completion; evidence-free recommendations are not generated.",
    calculation:
      "Ordering uses Priority Formula v1.0.0 and deterministic stable tie-breaking.",
    interpretation:
      "Assign the highest-value feasible actions, then verify them with an independent reanalysis.",
    limitation:
      "Priority depends on the coverage and evidence available in this run.",
    detailsLink: "#all-findings",
  },
  report_limitations: {
    shortTooltip: "See which missing or bounded evidence constrains the conclusions.",
    meaning:
      "Conditions that restrict how confidently the report can be interpreted.",
    included:
      "Unavailable providers, incomplete evidence groups, bounded discovery and automated-check limitations.",
    excluded:
      "A limitation is not treated as a pass, failure or finding unless evidence supports that status.",
    interpretation:
      "Review these conditions before comparing runs or treating an absent finding as proof of no issue.",
    detailsLink: "#technical-details",
  },
  report_technical_details: {
    shortTooltip: "Open the complete provenance and execution context behind the summary.",
    meaning:
      "Collapsed supporting detail for evidence references, agent attribution, providers and section status.",
    included:
      "Friendly agent states, evidence counts, unavailable capabilities and per-section attribution.",
    excluded:
      "Private reasoning, secrets and unsafe raw content are never displayed.",
    interpretation:
      "Use this section to audit provenance or troubleshoot a partial result; use the Technical Appendix for full occurrence tables.",
  },
  page_selected: {
    shortTooltip: "See why an eligible page was chosen for deeper analysis.",
    meaning:
      "Eligible pages selected for Level 2 based on deterministic page type, depth and URL ordering.",
    included: "All eligible HTML pages discovered during full-site analysis.",
    excluded: "Non-HTML assets and failed Level 1 pages.",
    interpretation:
      "Not selected means eligible but outside this run’s bounded deep-analysis sample.",
    limitation: "Selection is deterministic but cannot represent evidence that was never discovered.",
  },
  page_level_1: {
    shortTooltip: "Understand the lightweight evidence collected before deeper tools run.",
    meaning:
      "A bounded HTTP and HTML inspection that establishes basic technical and content evidence.",
    included: "Status, headers, metadata, headings, links and lightweight page signals.",
    excluded: "Lighthouse and browser-rendered deep diagnostics run only after this prerequisite succeeds.",
    interpretation: "A failure prevents dependent deep analysis but remains visible with its reason.",
    limitation: "Static response evidence may differ from client-rendered behavior.",
  },
  page_level_2: {
    shortTooltip: "Understand the deeper browser and audit evidence collected for selected pages.",
    meaning:
      "Browser-rendered and Lighthouse analysis for the deterministic deep-analysis selection.",
    included: "Rendering, runtime, laboratory performance and configured automated audit evidence.",
    excluded: "Pages that failed Level 1 or were outside the deep-analysis selection.",
    interpretation: "Partial means some deep tools completed while other required evidence did not.",
    limitation: "Laboratory measurements are not real-user field measurements.",
  },
  repository_scan_coverage: {
    shortTooltip: "See how much eligible source code was successfully inspected.",
    meaning: "The share of eligible repository source files completed by the scan.",
    included: "Files permitted by repository scope, supported language rules and ignore policy.",
    excluded: "Media, generated output, ignored directories, secrets and unsupported file types.",
    calculation: "Successfully scanned eligible files divided by eligible files, multiplied by 100.",
    interpretation: "Partial coverage means some eligible files failed, were skipped or remained incomplete.",
    limitation: "Repository findings apply only to the connected revision and configured scan scope.",
  },
  repository_match_confidence_detail: {
    shortTooltip: "See why an action was mapped to a particular source location.",
    meaning:
      "Confidence that finding evidence corresponds to a specific repository file or symbol.",
    included: "URL, component, exported symbol, AST and deterministic text-pattern overlap.",
    excluded: "A high value does not prove the proposed code change is correct or complete.",
    calculation: "Deterministic match signals are combined using the versioned repository matcher.",
    interpretation: "Low or unlocated results require manual repository investigation.",
    limitation: "Minified, generated or dynamically composed code can reduce matching confidence.",
  },
  action_open: {
    shortTooltip: "See which verified actions still require implementation.",
    meaning: "Actions not yet moved to an in-progress or completed state.",
    included: "Persisted action items whose current status is open.",
    excluded: "Completed, dismissed and superseded actions.",
    interpretation: "Use this count for workload tracking, not as a severity measure.",
  },
  action_critical: {
    shortTooltip: "Identify open work tied to the most severe retained findings.",
    meaning: "Open actions whose source finding has critical severity.",
    included: "Critical actions still requiring implementation or verification.",
    excluded: "High, medium, low and already completed actions.",
    interpretation: "Review these first, while also considering feasibility and dependencies.",
  },
  action_high_priority: {
    shortTooltip: "See how many actions meet the high-priority decision threshold.",
    meaning: "Open actions with a deterministic priority score of 70/100 or higher.",
    included: "Severity, affected scope, confidence, effort and business-impact components.",
    excluded: "The displayed average priority is context and does not change the threshold count.",
    calculation: "Each action uses Priority Formula v1.0.0; qualifying scores are counted.",
    interpretation: "High priority means schedule soon, not that every item has critical severity.",
  },
  action_affected_pages: {
    shortTooltip: "See how widely current remediation work is distributed.",
    meaning: "Unique pages referenced by open or in-progress actions.",
    included: "Distinct normalized page URLs linked by retained action evidence.",
    excluded: "Repeated actions on the same page do not increase the page count.",
    interpretation: "Compare this count with action occurrences to distinguish breadth from repetition.",
  },
  action_completed: {
    shortTooltip: "See which actions have reached the completed workflow state.",
    meaning: "Actions marked complete in the persisted Action Plan history.",
    included: "Items with a completed status and retained status-transition record.",
    excluded: "Completion status alone is not new analysis evidence and does not erase the original finding.",
    interpretation: "Reanalyse the website to verify that the underlying issue no longer occurs.",
  },
  action_grouping: {
    shortTooltip: "Understand why several page occurrences can share one remediation action.",
    meaning:
      "Actions are grouped when their stable issue identity and exact correction can be addressed together.",
    included: "Matching issue signature, category, correction and affected-page evidence.",
    excluded: "Different rules or corrections are not merged merely because they repeat across pages.",
    interpretation: "Open a group to inspect every page and occurrence before applying a shared fix.",
    limitation: "A shared group does not prove that all occurrences come from one source template.",
  },
};

const CALCULATED_CONCEPT_IDS = new Set([
  "eligible_html_pages",
  "website_coverage",
  "evidence_completeness",
  "browser_coverage",
  "report_confidence",
  "occurrences",
  "unique_findings",
  "accessibility_inapplicable_rules",
  "report_action_plan",
  "repository_scan_coverage",
  "repository_match_confidence_detail",
  "action_high_priority",
]);

export function validateExplanationRegistry(): string[] {
  return validateExplanationSet(
    Object.entries(CONCEPT_EXPLANATIONS).map(([conceptId, content]) => ({
      conceptId,
      content,
      requireCalculation: CALCULATED_CONCEPT_IDS.has(conceptId),
      requireExclusion: true,
    })),
  );
}

const METRIC_OVERRIDES: Record<string, ExplanationContent> = {
  eligible_pages: CONCEPT_EXPLANATIONS.eligible_html_pages,
  analysis_coverage_percent: CONCEPT_EXPLANATIONS.website_coverage,
  site_diagnostic_coverage_percentage: {
    ...CONCEPT_EXPLANATIONS.website_coverage,
    shortTooltip: "See how much eligible page evidence entered site-wide diagnostics.",
    meaning:
      "The share of diagnostic-eligible pages processed by the site-diagnostics execution.",
    calculation:
      "Processed diagnostic pages divided by diagnostic-eligible pages, multiplied by 100.",
    limitation:
      "Diagnostic coverage is not a compliance score and is separate from browser-engine coverage.",
  },
  confidence: {
    shortTooltip: "See how strongly the retained evidence supports this finding.",
    meaning: "An evidence-strength assessment attached to a finding, separate from severity.",
    included: "Source availability, consistency and specificity of the retained observation.",
    excluded: "Confidence does not measure business impact or remediation priority.",
    calculation: "Assigned deterministically from the evidence conditions defined for the finding type.",
    interpretation: "Lower confidence calls for verification before acting; unavailable evidence is never high confidence.",
    limitation: "Confidence applies only to evidence collected in this run.",
  },
  accessibility_score: {
    shortTooltip: "Understand the automated evidence contributing to the accessibility category.",
    meaning: "An x/100 category score derived from retained automated accessibility evidence.",
    included: "Configured automated rule results and versioned score contributions.",
    excluded: "Manual testing, assistive-technology testing and complete compliance certification.",
    calculation: "The accessibility contribution defined by Overall Score Formula v1.0.0.",
    interpretation: "Higher is better, but no automated score proves complete accessibility.",
    limitation: "Results cover only analysed pages, rules and automated tools available in this run.",
  },
  priority_score: {
    shortTooltip: "See why one remediation action ranks above another.",
    meaning: "A deterministic x/100 ordering signal for an Action Plan item.",
    included: "Severity, affected scope, evidence confidence, effort and business impact.",
    excluded: "The value does not alter the Overall Score and is not generated by an LLM.",
    calculation: "Calculated using Priority Formula v1.0.0 with versioned component weights.",
    interpretation: "Higher values indicate earlier attention, subject to dependencies and feasibility.",
    limitation: "Priority changes when new evidence changes the underlying components.",
  },
  clean_pass_percent: {
    shortTooltip: "See how many analysed pages had no retained issues in the selected checks.",
    meaning: "The share of successfully analysed pages with zero findings in the measured scope.",
    included: "Pages with completed required checks and no retained finding occurrence.",
    excluded: "Failed, skipped, unavailable and partially analysed pages are not assumed clean.",
    calculation: "Completed pages with zero findings divided by completed analysed pages, multiplied by 100.",
    interpretation: "A high value describes tested evidence only; it is not proof that untested issues are absent.",
    limitation: "The result depends on the checks and coverage available in this run.",
  },
  generation_coverage: {
    shortTooltip: "See how many eligible findings produced grounded Action Plan items.",
    meaning: "The share of action-eligible findings represented in generated remediation work.",
    included: "Eligible findings that map to at least one persisted action.",
    excluded: "Unavailable, informational-only or explicitly non-actionable findings.",
    calculation: "Findings with generated actions divided by action-eligible findings, multiplied by 100.",
    interpretation: "Partial coverage means some eligible findings lack grounded remediation output.",
    limitation: "Coverage measures action generation, not action completion.",
  },
};

function metricExclusion(metric: MetricDefinition): string {
  if (metric.category === "accessibility") {
    return "Manual accessibility testing and complete compliance claims are not included.";
  }
  if (metric.category === "repository") {
    return "Ignored, generated, binary, unsupported and out-of-scope files are not included.";
  }
  if (metric.category === "coverage") {
    return "Unavailable evidence is not counted as completed, and unrelated resource classes stay outside the denominator.";
  }
  if (metric.category === "performance") {
    return metric.metric_id.startsWith("lighthouse_")
      ? "Real-user field experience is not included in this laboratory measurement."
      : "Unavailable measurements and unrelated performance signals are not substituted into this value.";
  }
  if (metric.value_type === "score") {
    return "Confidence and unavailable evidence are reported separately rather than silently converted into score points.";
  }
  return "Unavailable or uncollected evidence is not interpreted as a zero, pass or detected occurrence.";
}

export function getMetricExplanation(metric: MetricDefinition): ExplanationContent {
  const override = METRIC_OVERRIDES[metric.metric_id];
  if (override) return override;
  const direction =
    metric.higher_is_better === true
      ? "Higher values generally indicate a stronger result."
      : metric.higher_is_better === false
        ? "Lower values generally indicate fewer detected problems or less delay."
        : metric.interpretation_guidance;
  return {
    shortTooltip: `See the evidence, calculation and limits behind ${metric.label.toLocaleLowerCase()}.`,
    meaning: `${metric.label} represents ${metric.description.replace(/\.$/, "")} in the retained analysis evidence.`,
    included: `Only persisted ${metric.evidence_source.toLocaleLowerCase()} evidence applicable to this metric and analysis profile is included.`,
    excluded: metricExclusion(metric),
    calculation: metric.calculation_summary,
    interpretation: `${metric.interpretation_guidance} ${direction}`.trim(),
    limitation: metric.known_limitations,
  };
}

export function getSafeMetricExplanation(
  metric: MetricDefinition,
): ExplanationContent | undefined {
  const content = getMetricExplanation(metric);
  return validateExplanationContent(metric.label, content, {
    requireCalculation: true,
    requireExclusion: true,
    visibleDescription: metric.description,
  }).length === 0
    ? content
    : undefined;
}

export function getConceptExplanation(
  conceptId: string,
): ExplanationContent | undefined {
  return CONCEPT_EXPLANATIONS[conceptId];
}

export function getSafeConceptExplanation(
  conceptId: string,
  visibleLabel: string,
): ExplanationContent | undefined {
  const content = getConceptExplanation(conceptId);
  if (!content) return undefined;
  return validateExplanationContent(visibleLabel, content, {
    requireCalculation: CALCULATED_CONCEPT_IDS.has(conceptId),
    requireExclusion: true,
  }).length === 0
    ? content
    : undefined;
}

export const EXPLANATION_CONCEPT_IDS = Object.freeze(
  Object.keys(CONCEPT_EXPLANATIONS).sort(),
);

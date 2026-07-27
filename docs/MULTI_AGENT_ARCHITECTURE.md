# Multi-Agent Platform Architecture

## Scope and boundaries

The platform wraps existing deterministic analysis capabilities in versioned,
reusable orchestration. An **agent** owns a bounded goal and structured contract; a
**tool** is an allowed capability invoked by an agent; a **service** implements
project behavior behind those contracts; and the versioned workflow
**orchestrator** schedules the dependency graph. The orchestrator is infrastructure,
not a ninth domain agent.

The eight domain agents are:

1. `discovery_agent`
2. `performance_agent`
3. `accessibility_agent`
4. `site_diagnostics_agent`
5. `repository_intelligence_agent`
6. `evidence_validation_agent`
7. `remediation_agent`
8. `report_agent`

The fifteen registered tools are `website_discovery`, `url_normalization`,
`playwright_analysis`, `lighthouse_analysis`, `crux_field_evidence`,
`browser_timing`, `axe_accessibility`, `accessibility_aggregation`,
`site_diagnostics`, `repository_scanning`, `remediation_generation`,
`report_generation`, `evidence_retrieval`, `scoring_intelligence`, and
`approved_llm_completion`.
Each definition pins a semantic version, schemas, permissions, timeout, retry and
idempotency behavior, side-effect class, evidence type, secret policy,
availability, and limitations. Agent runs may invoke only their registered tools.

## Deterministic workflows

Three versioned workflows are registered: `full_website_analysis`,
`repository_remediation`, and `reanalysis`. Their nodes, entry points, terminal
nodes, dependencies, optional dependencies, conditions, and deterministic order
are validated before registration.

The full analysis graph is:

```text
Discovery
  +--> Performance ----------+
  +--> Accessibility --------+--> Evidence Validation
  +--> Site Diagnostics -----+          |
                                         v
                          Repository Intelligence (when configured)
                                         |
                                         v
                                  Remediation --> Report
```

Performance, accessibility, and site diagnostics are parallel branches.
Repository intelligence is conditional: without an approved repository
connection it is explicitly unavailable and downstream work follows the declared
optional-dependency policy. The graph never implies that unavailable evidence
completed successfully.

## Execution and recovery

FastAPI creates the persistent workflow execution and sends only its UUID to
Celery. The worker loads pinned registry versions and the deterministic
orchestrator claims ready nodes up to the stored concurrency limit. Execution,
agent-run, step, event, artifact, and checkpoint records preserve immutable
history. A repeated project/workflow/idempotency-key request returns the same
execution; a different key creates independent history.

Timeouts and retry limits come from agent and tool definitions. Transient failures
may retry with recorded attempts; permanent, partial, unavailable, cancelled, and
completed states remain distinct. Cancellation prevents new work without deleting
successful runs. Resume uses only a valid checkpoint whose execution and input
fingerprint match; already completed runs remain preserved. Partial completion
records successful branches, unavailable dependencies, and failure details.

Evidence is stored as references to original records. Artifacts store bounded
metadata and storage references, not copied secret material. Events and outputs
contain structured statuses, tool activity and concise decisions. Private
chain-of-thought, hidden reasoning, prompts, provider secrets, and credentials are
not persistence fields and are not rendered by the interface. Secret-bearing
providers receive credentials only at runtime under their registered redaction
policy.

`approved_llm_completion` is conditional and never represented as active without
an approved configured provider. LLM input must be grounded in evidence
references, provider/model metadata is recorded, and token/cost totals are shown
only when supplied. Disabled or failed provider use remains explicit and uses the
registered deterministic fallback; no unsupported AI conclusion is fabricated.

## API surface

Registry metadata is read-only:

- `GET /api/v1/agents`
- `GET /api/v1/agents/{agent_id}`
- `GET /api/v1/tools`
- `GET /api/v1/tools/{tool_id}`
- `GET /api/v1/workflows`
- `GET /api/v1/workflows/{workflow_id}`

Execution APIs are:

- `POST /api/v1/workflow-executions`
- `GET /api/v1/workflow-executions/{execution_id}`
- `GET /api/v1/workflow-executions/{execution_id}/runs`
- `GET /api/v1/workflow-executions/{execution_id}/events`
- `POST /api/v1/workflow-executions/{execution_id}/cancel`
- `POST /api/v1/workflow-executions/{execution_id}/resume`
- `POST /api/v1/agent-runs/{run_id}/retry`

Run and event lists support deterministic filtering and pagination. Missing
resources, idempotency conflicts, and invalid input use structured 404, 409, and
422 responses.

## Interface and scoring

The project and analysis-run report retain the existing deterministic analysis
views and add an Agent Execution landmark. It presents workflow metadata, an
accessible dependency representation, progress, pinned runs, retry/resume and
checkpoint state, tool activity, events, evidence/artifact references, and
available cost totals. Loading, empty, partial, unavailable, validation and error
states do not claim success. Status always has text, controls are keyboard
operable with visible focus, and structured values are bounded and safely escaped.

The platform changes neither Overall Score Formula v1.0.0 nor Priority Formula
v1.0.0. Agent orchestration coordinates evidence production; it does not add a
scoring path.

The deterministic `scoring_intelligence` tool is the exception to narrative-only
report assembly: it persists the already-approved formula result and explanation,
but does not introduce a new formula or autonomous agent. It runs in the Evidence
Validation stage after prerequisite analysis branches, stores a score-execution
reference for downstream remediation/report agents, and is prohibited from using
LLM output. Report and remediation results may reference contributions, never
override them. The eight agent IDs and three workflow DAGs remain unchanged.

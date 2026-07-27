import type {
  AgentRun,
  WorkflowDefinition,
  WorkflowNodeDefinition,
} from "@/components/agents/types";

interface DependencyGraphProps {
  workflow: WorkflowDefinition;
  repositoryConfigured: boolean;
  runs: AgentRun[];
}

export function workflowStages(
  workflow: WorkflowDefinition,
  repositoryConfigured: boolean,
): string[][] {
  const activeNodes = workflow.nodes.filter(
    (node) => node.condition !== "repository_configured" || repositoryConfigured,
  );
  const activeIds = new Set(activeNodes.map((node) => node.agent_id));
  const order = new Map(
    workflow.deterministic_order.map((agentId, index) => [agentId, index]),
  );
  const dependencies = new Map<string, Set<string>>();
  for (const node of activeNodes) {
    dependencies.set(
      node.agent_id,
      new Set(
        [...node.depends_on, ...node.optional_dependencies].filter((id) =>
          activeIds.has(id),
        ),
      ),
    );
  }
  const completed = new Set<string>();
  const stages: string[][] = [];
  while (completed.size < activeNodes.length) {
    const stage = activeNodes
      .map((node) => node.agent_id)
      .filter(
        (agentId) =>
          !completed.has(agentId) &&
          [...(dependencies.get(agentId) ?? [])].every((id) => completed.has(id)),
      )
      .sort((left, right) => (order.get(left) ?? 0) - (order.get(right) ?? 0));
    if (stage.length === 0) break;
    stages.push(stage);
    stage.forEach((agentId) => completed.add(agentId));
  }
  return stages;
}

function nodeById(
  workflow: WorkflowDefinition,
  agentId: string,
): WorkflowNodeDefinition | undefined {
  return workflow.nodes.find((node) => node.agent_id === agentId);
}

export function DependencyGraph({
  workflow,
  repositoryConfigured,
  runs,
}: DependencyGraphProps) {
  const stages = workflowStages(workflow, repositoryConfigured);
  const latestRuns = new Map<string, AgentRun>();
  for (const run of runs) {
    const current = latestRuns.get(run.agent_id);
    if (!current || run.attempt > current.attempt) latestRuns.set(run.agent_id, run);
  }
  const stageDescription = stages
    .map((stage, index) => `Stage ${index + 1}: ${stage.join(", ")}`)
    .join(". ");
  const conditionalNode = workflow.nodes.find(
    (node) => node.condition === "repository_configured",
  );

  return (
    <section aria-labelledby={`dependency-graph-${workflow.workflow_id}`}>
      <h3 className="text-lg font-semibold" id={`dependency-graph-${workflow.workflow_id}`}>
        Dependency Graph
      </h3>
      <p className="mt-1 text-sm text-slate-600" id={`graph-description-${workflow.workflow_id}`}>
        Deterministic text alternative: {stageDescription}.
      </p>
      <ol
        aria-describedby={`graph-description-${workflow.workflow_id}`}
        aria-label={`${workflow.name} deterministic dependency order`}
        className="mt-4 grid gap-3"
      >
        {stages.map((stage, stageIndex) => (
          <li className="rounded-xl border border-slate-200 bg-slate-50 p-3" key={stageIndex}>
            <p className="text-xs font-bold uppercase tracking-wide text-slate-500">
              Stage {stageIndex + 1}
              {stage.length > 1 ? " — parallel branches" : " — sequential"}
            </p>
            <ul className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {stage.map((agentId) => {
                const node = nodeById(workflow, agentId);
                const run = latestRuns.get(agentId);
                return (
                  <li className="rounded-lg border bg-white p-3" key={agentId}>
                    <p className="font-mono text-sm font-semibold">{agentId}</p>
                    <p className="mt-1 text-xs text-slate-600">
                      Status: {run?.status ?? "not started"}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      Depends on: {node?.depends_on.join(", ") || "workflow entry"}
                    </p>
                  </li>
                );
              })}
            </ul>
          </li>
        ))}
      </ol>
      {conditionalNode && !repositoryConfigured && (
        <div
          aria-label="Conditional repository intelligence stage is not configured"
          className="mt-3 rounded-xl border border-dashed border-amber-400 bg-amber-50 p-3 text-sm"
        >
          <strong className="font-mono">{conditionalNode.agent_id}</strong>: conditional stage
          unavailable because no approved repository connection is configured.
        </div>
      )}
    </section>
  );
}

export function ScoreBar({
  score,
  label,
  compact = false,
}: {
  score: number | null | undefined;
  label: string;
  compact?: boolean;
}) {
  const color =
    score == null
      ? "bg-slate-200"
      : score >= 90
        ? "bg-emerald-500"
        : score >= 50
          ? "bg-amber-500"
          : "bg-red-500";

  return (
    <div className={compact ? "" : "rounded-lg border border-slate-200 p-3"}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-medium text-slate-700">{label}</span>
        <span className="text-sm font-bold tabular-nums">
          {score != null ? `${score}/100` : "N/A"}
        </span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-100">
        <div
          className={`h-full rounded-full transition-all ${color}`}
          style={{ width: `${score ?? 0}%` }}
        />
      </div>
    </div>
  );
}

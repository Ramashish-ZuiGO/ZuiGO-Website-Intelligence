function scoreColor(score: number | null | undefined): string {
  if (score == null) return "text-slate-400 bg-slate-50 border-slate-200";
  if (score >= 90) return "text-emerald-700 bg-emerald-50 border-emerald-200";
  if (score >= 50) return "text-amber-700 bg-amber-50 border-amber-200";
  return "text-red-700 bg-red-50 border-red-200";
}

export function ScoreBadge({
  score,
  max = 100,
  label,
  size = "md",
}: {
  score: number | null | undefined;
  max?: number;
  label?: string;
  size?: "sm" | "md" | "lg";
}) {
  const sizeClass = {
    sm: "text-lg",
    md: "text-2xl",
    lg: "text-4xl",
  }[size];

  return (
    <div
      className={`inline-flex flex-col items-center rounded-xl border p-3 ${scoreColor(score)}`}
    >
      <span className={`font-bold leading-none ${sizeClass}`}>
        {score != null ? score : "—"}
      </span>
      {score != null && (
        <span className="mt-0.5 text-xs opacity-70">/{max}</span>
      )}
      {label && (
        <span className="mt-1 text-xs font-medium opacity-80">{label}</span>
      )}
      {score == null && (
        <span className="mt-1 text-xs">Not enough evidence</span>
      )}
    </div>
  );
}

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

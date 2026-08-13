export function MetricStat({
  label,
  value,
  detail,
  className,
}: {
  label: string;
  value: string | number;
  detail?: string;
  className?: string;
}) {
  return (
    <div className={`min-w-0 ${className ?? ""}`}>
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </dt>
      <dd className="mt-0.5 text-xl font-bold tabular-nums text-slate-900">
        {value}
      </dd>
      {detail && (
        <dd className="mt-0.5 text-xs text-slate-500">{detail}</dd>
      )}
    </div>
  );
}

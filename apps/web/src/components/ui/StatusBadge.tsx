import { CheckCircle2, AlertTriangle, XCircle, Info, Minus, Loader2 } from "lucide-react";

// Using semantic tokens
const STATUS_CONFIG: Record<string, { color: string, icon: React.ElementType }> = {
  complete: { color: "success", icon: CheckCircle2 },
  completed: { color: "success", icon: CheckCircle2 },
  passed: { color: "success", icon: CheckCircle2 },
  available: { color: "success", icon: CheckCircle2 },
  compatible: { color: "success", icon: CheckCircle2 },
  good: { color: "success", icon: CheckCircle2 },
  present: { color: "success", icon: CheckCircle2 },
  detected: { color: "success", icon: CheckCircle2 },
  current: { color: "success", icon: CheckCircle2 },
  resolved: { color: "success", icon: CheckCircle2 },
  active: { color: "success", icon: CheckCircle2 },

  partial: { color: "warning", icon: AlertTriangle },
  incomplete: { color: "warning", icon: AlertTriangle },
  needs_attention: { color: "warning", icon: AlertTriangle },
  issues_found: { color: "warning", icon: AlertTriangle },
  high: { color: "warning", icon: AlertTriangle },
  medium: { color: "warning", icon: AlertTriangle },
  inconclusive: { color: "warning", icon: AlertTriangle },
  in_progress: { color: "warning", icon: AlertTriangle },
  reopened: { color: "warning", icon: AlertTriangle },

  failed: { color: "danger", icon: XCircle },
  missing: { color: "danger", icon: XCircle },
  weak: { color: "danger", icon: XCircle },
  high_observable_risk: { color: "danger", icon: XCircle },
  critical: { color: "danger", icon: XCircle },
  unlinked: { color: "danger", icon: XCircle },

  low: { color: "info", icon: Info },
  informational: { color: "info", icon: Info },
  info: { color: "info", icon: Info },
  open: { color: "info", icon: Info },
  running: { color: "info", icon: Loader2 },

  unavailable: { color: "neutral", icon: Minus },
  pending: { color: "neutral", icon: Minus },
  queued: { color: "neutral", icon: Minus },
  cancelled: { color: "neutral", icon: Minus },
  not_detected: { color: "neutral", icon: Minus },
  acknowledged: { color: "neutral", icon: Minus },
  ignored: { color: "neutral", icon: Minus },
  mixed: { color: "neutral", icon: Minus },
  skipped: { color: "neutral", icon: Minus },
  inactive: { color: "neutral", icon: Minus },
};

function formatLabel(status: string): string {
  return status
    .replaceAll("_", " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function StatusBadge({
  status,
  label,
  size = "sm",
}: {
  status: string;
  label?: string;
  size?: "xs" | "sm";
}) {
  const config = STATUS_CONFIG[status] ?? { color: "neutral", icon: Minus };
  const Icon = config.icon;
  const isRunning = status === "running";

  const sizeClass =
    size === "xs" ? "px-1.5 py-0.5 text-[10px] gap-1" : "px-2 py-1 text-xs gap-1.5";

  const iconSize = size === "xs" ? "h-3 w-3" : "h-3.5 w-3.5";

  const colorClass =
    config.color === "success" ? "bg-z-success-subtle text-z-success border-z-success/30" :
    config.color === "warning" ? "bg-z-warning-subtle text-z-warning border-z-warning/30" :
    config.color === "danger"  ? "bg-z-danger-subtle text-z-danger border-z-danger/30" :
    config.color === "info"    ? "bg-z-info-subtle text-z-info border-z-info/30" :
    "bg-z-neutral-subtle text-z-neutral border-z-border";

  return (
    <span
      className={`inline-flex items-center rounded-full border font-medium leading-none ${colorClass} ${sizeClass}`}
    >
      <Icon className={`${iconSize} ${isRunning ? "animate-spin" : ""}`} aria-hidden="true" />
      <span>{label ?? formatLabel(status)}</span>
    </span>
  );
}

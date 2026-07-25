import { MetricInterpretation, RatingEnum } from "./types";

interface MetricRatingBadgeProps {
  interpretation?: MetricInterpretation;
  className?: string;
}

export function MetricRatingBadge({ interpretation, className }: MetricRatingBadgeProps) {
  if (!interpretation) {
    return null;
  }

  const getBadgeStyle = (rating: RatingEnum) => {
    switch (rating) {
      case "good":
        return "bg-emerald-100 text-emerald-800 border-emerald-200";
      case "needs_improvement":
        return "bg-amber-100 text-amber-800 border-amber-200";
      case "poor":
        return "bg-rose-100 text-rose-800 border-rose-200";
      case "unavailable":
      case "not_applicable":
        return "bg-slate-100 text-slate-800 border-slate-200";
      default:
        return "bg-slate-100 text-slate-800 border-slate-200";
    }
  };

  const formatLabel = (rating: RatingEnum) => {
    switch (rating) {
      case "good": return "Good";
      case "needs_improvement": return "Needs Improvement";
      case "poor": return "Poor";
      case "unavailable": return "Unavailable";
      case "not_applicable": return "N/A";
      default: return rating;
    }
  };

  return (
    <div className={`relative group inline-flex ${className || ""}`}>
      <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold cursor-help transition-colors ${getBadgeStyle(interpretation.rating)}`}>
        {formatLabel(interpretation.rating)}
        {interpretation.explanation && (
          <span className="ml-1 text-current opacity-70">
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
          </span>
        )}
      </span>

      {/* Tooltip */}
      <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 hidden group-hover:block w-64 z-50">
        <div className="rounded-lg bg-slate-950 p-3 text-sm text-slate-50 shadow-lg">
          {interpretation.explanation && (
            <p className="font-semibold mb-1">{interpretation.explanation}</p>
          )}
          {interpretation.evidence_type && (
            <p className="text-xs text-slate-400 capitalize mb-1">
              Data source: {interpretation.evidence_type}
            </p>
          )}
          {interpretation.limitations.length > 0 && (
            <ul className="text-xs text-slate-400 list-disc pl-4 space-y-1">
              {interpretation.limitations.map((lim, idx) => (
                <li key={idx}>{lim}</li>
              ))}
            </ul>
          )}
          <p className="text-xs mt-2 opacity-80 text-slate-500">
            Profile: {interpretation.selected_profile_id} (v{interpretation.selected_profile_version})
          </p>
        </div>
        <div className="absolute left-1/2 -bottom-1 h-2 w-2 -translate-x-1/2 rotate-45 bg-slate-950"></div>
      </div>
    </div>
  );
}

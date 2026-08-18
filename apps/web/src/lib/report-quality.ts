export type ReportQuality = "COMPLETE" | "PARTIAL" | "INCONCLUSIVE" | "FAILED";

// Shared across the two report-rendering surfaces (the live analysis-run
// page and the immutable ReportDeliveryPanel snapshot viewer). They read
// different backing data shapes -- AnalysisReport vs the canonical
// ReportExecution snapshot -- so each computes its own quality value, but
// both must render it with the same visual meaning.
export const QUALITY_STYLES: Record<ReportQuality, string> = {
  COMPLETE: "bg-emerald-100 text-emerald-800 border-emerald-200",
  PARTIAL: "bg-amber-100 text-amber-800 border-amber-200",
  INCONCLUSIVE: "bg-orange-100 text-orange-800 border-orange-200",
  FAILED: "bg-red-100 text-red-800 border-red-200",
};

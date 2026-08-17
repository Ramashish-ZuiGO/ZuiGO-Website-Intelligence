/** Status of a Tier 0 real-browser check execution. */
export type BrowserUatTier0Status =
  | "pending"
  | "running"
  | "completed"
  | "partial"
  | "failed"
  | "cancelled"
  | "unavailable";

/** Lane identifier — which CI/manual path produced the check. */
export type BrowserUatLane =
  | "github_actions_chrome_edge"
  | "github_actions_safari"
  | "simulator_iphone_safari"
  | "manual_android";

/** Response from GET/POST .../browser-uat/tier0 */
export interface BrowserUatExecution {
  execution_id: string;
  website_id: string;
  analysis_run_id: string;
  lane: string;
  status: BrowserUatTier0Status;
  attempt: number;
  requested_at: string;
  started_at: string | null;
  completed_at: string | null;
}

/** A single tap-target sample from viewport analysis. */
export interface BrowserUatTapTargetSample {
  width: number;
  height: number;
  element_type: string;
  accessible_label: string;
  spacing_exception: boolean;
}

/** Viewport-level findings for one page/browser combination. */
export interface BrowserUatViewportResult {
  viewport_name: string;
  viewport_width: number;
  viewport_height: number;
  horizontal_overflow: boolean;
  critical_elements_outside_viewport: number;
  overlapping_elements: number;
  small_tap_targets: number;
  tap_target_samples: BrowserUatTapTargetSample[];
}

/** Per-page result from a real browser check. */
export interface BrowserUatPageResult {
  page_result_id: string;
  url: string;
  browser_channel: string;
  platform: string;
  browser_version: string;
  status: string;
  error_message: string | null;
  viewport_results: BrowserUatViewportResult[];
}

/** Response from GET .../browser-uat/tier0/results */
export interface BrowserUatResults {
  page_results: BrowserUatPageResult[];
}

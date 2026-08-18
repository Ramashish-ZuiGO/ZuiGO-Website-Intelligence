export type BrowserEngine = "chromium" | "firefox" | "webkit";

// Internal rendering-engine diagnostics only. Per the locked browser UAT
// contract, Chromium is never Chrome/Edge verification and WebKit is never
// Safari verification -- callers must state that caveat in surrounding
// prose rather than relying on the label text alone.
export const ENGINE_LABELS: Record<string, string> = {
  chromium: "Chromium Engine",
  firefox: "Firefox Engine",
  webkit: "WebKit Engine",
};

export const ENGINE_SHORT_LABELS: Record<BrowserEngine, string> = {
  chromium: "Chromium",
  firefox: "Firefox",
  webkit: "WebKit",
};

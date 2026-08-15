// M2 Tier 0 desktop lane: drive the REAL installed browser (not Playwright's
// bundled Chromium) via the `channel` option, so results are genuine branded
// Chrome/Edge evidence rather than the engine-only signal the product
// already collects elsewhere. See docs/DEVICE_OS_BROWSER_QA_PLAN.md M2.
//
// Also runs the M3 shared responsive-assertion contract
// (apps/api/app/services/responsive_assertions.js) at desktop and mobile
// viewports, so this real-branded-browser lane produces genuine structural
// findings, not just an HTTP pass/fail -- the same contract already wired
// into browser_compatibility.py's cross-engine comparison path.
//
// Env vars (set by browser-uat-tier0-desktop.yml from workflow_dispatch inputs):
//   BROWSER_CHANNEL   "chrome" or "msedge"
//   TARGET_PAGES      JSON array of URLs to check
//   RESULTS_PATH      where to write the JSON results artifact

import { chromium } from "playwright";
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const channel = process.env.BROWSER_CHANNEL;
const platform = process.env.PLATFORM;
const pages = JSON.parse(process.env.TARGET_PAGES || "[]");
const resultsPath = process.env.RESULTS_PATH || "tier0-results.json";

// Mirrors CompatibilityProfile's DESKTOP_VIEWPORT/MOBILE_VIEWPORT in
// browser_compatibility.py, not the fuller 5-viewport RESPONSIVE_VIEWPORTS
// set used only by the deep single-engine analysis -- keeps this lane
// consistent with the existing cross-browser comparison's viewport count.
const VIEWPORTS = [
  ["Desktop", 1440, 900],
  ["Mobile", 390, 844],
];

const RESPONSIVE_ASSERTIONS_JS_PATH = fileURLToPath(
  new URL("../../apps/api/app/services/responsive_assertions.js", import.meta.url),
);

if (!channel) {
  throw new Error("BROWSER_CHANNEL is required (chrome or msedge).");
}
if (!platform) {
  throw new Error("PLATFORM is required (windows or macos) -- M4 ingestion keys results by it.");
}
if (pages.length === 0) {
  throw new Error("TARGET_PAGES must contain at least one URL.");
}

async function checkPage(browser, url, responsiveAssertions) {
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  try {
    const response = await page.goto(url, { waitUntil: "load", timeout: 30_000 });
    const status = response ? response.status() : null;
    const httpPassed = status !== null && status < 400;

    const viewportResults = [];
    if (httpPassed) {
      for (const [name, width, height] of VIEWPORTS) {
        await page.setViewportSize({ width, height });
        try {
          viewportResults.push(await page.evaluate(responsiveAssertions, [name, width, height]));
        } catch (error) {
          viewportResults.push({
            name,
            width,
            height,
            status: "failed",
            error: String(error && error.message ? error.message : error),
          });
        }
      }
    }

    const viewportProblems = viewportResults.flatMap((result) => result.viewport_problems || []);
    const passed = httpPassed && viewportProblems.length === 0;
    return {
      url,
      status: passed ? "pass" : "fail",
      http_status: status,
      console_error_count: consoleErrors.length,
      viewport_results: viewportResults,
    };
  } catch (error) {
    return {
      url,
      status: "fail",
      http_status: null,
      error: String(error && error.message ? error.message : error),
      viewport_results: [],
    };
  } finally {
    await page.close();
  }
}

function loadResponsiveAssertions(source) {
  // Node's Playwright, unlike Python's, does NOT auto-detect and call a
  // string source as a function -- it evaluates the string as a plain
  // expression, and a bare function expression is not JSON-serializable
  // across the protocol, so page.evaluate(sourceString, arg) silently
  // resolves to undefined instead of calling it (verified live 2026-08-14:
  // page.evaluate('([a,b]) => a+b', [1,2]) returned undefined in Node,
  // while the identical string worked correctly in Python). Materializing a
  // real function reference first, and passing THAT to page.evaluate, is
  // required for Node.
  //
  // Indirect eval (`(0, eval)(source)`), not `new Function('return ' +
  // source)`: the source file's leading `//` comment block sits on the same
  // logical line as a naive `return`, and JS's automatic-semicolon-insertion
  // silently turns `return // comment...` into `return;` -- also verified
  // live, `new Function` produced a function that always returned undefined.
  // Indirect eval evaluates the whole file as a script and yields its final
  // expression's value, sidestepping the ASI trap entirely.
  return (0, eval)(source);
}

async function main() {
  const responsiveAssertionsSource = await readFile(RESPONSIVE_ASSERTIONS_JS_PATH, "utf-8");
  const responsiveAssertions = loadResponsiveAssertions(responsiveAssertionsSource);
  const browser = await chromium.launch({ channel });
  const browserVersion = browser.version();
  try {
    const pageResults = [];
    for (const url of pages) {
      pageResults.push(await checkPage(browser, url, responsiveAssertions));
    }
    const allPassed = pageResults.every((result) => result.status === "pass");
    const results = {
      channel,
      platform,
      browser_version: browserVersion,
      overall_status: allPassed ? "pass" : "fail",
      pages: pageResults,
    };
    await writeFile(resultsPath, JSON.stringify(results, null, 2));
    console.log(JSON.stringify(results, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

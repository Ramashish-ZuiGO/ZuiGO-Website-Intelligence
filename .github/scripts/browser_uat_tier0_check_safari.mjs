// Lane B of the device/OS/browser QA initiative
// (docs/DEVICE_OS_BROWSER_QA_PLAN.md M2 Lane B): drive REAL desktop Safari on
// macOS via Selenium + Apple's built-in safaridriver. Playwright cannot do
// this -- it only ships its own WebKit build, never real Safari -- so this is
// a genuinely different toolchain from browser_uat_tier0_check.mjs (Lane A,
// Chrome/Edge via Playwright), not a variant of it.
//
// Also runs the M3 shared responsive-assertion contract
// (apps/api/app/services/responsive_assertions.js), same as Lane A, so this
// lane produces genuine structural findings too.
//
// Known, deliberate differences from Lane A (Selenium/WebDriver limitations,
// not oversights -- see docs/DEVICE_OS_BROWSER_QA_PLAN.md M2 Lane B):
//   - http_status is always null. The W3C WebDriver protocol (unlike
//     Playwright's CDP-based API) exposes no HTTP response status for a
//     navigation; page pass/fail is judged by whether driver.get() threw.
//   - console_error_count is always 0. Safari's WebDriver logging is
//     restricted to on/off, with no way to retrieve captured entries
//     programmatically (see selenium.dev's Safari-specific docs) -- this is
//     "not measured", not "no errors found", and is not used by any
//     downstream finding/action logic (informational only).
//   - Viewport size is achieved by resizing the OS window and then measuring
//     the ACTUAL resulting document viewport (window.innerWidth/Height),
//     rather than trusting a Playwright-style exact content-viewport API
//     (WebDriver's window.setRect controls the outer window, not the inner
//     viewport, and macOS window chrome eats some of it). The assertion
//     function is always called with the REAL measured width/height, never
//     the nominal target -- honest evidence over a precise-looking fake.
//
// Env vars (set by browser-uat-tier0-desktop.yml):
//   TARGET_PAGES   JSON array of URLs to check
//   RESULTS_PATH   where to write the JSON results artifact

import { Builder, Browser } from "selenium-webdriver";
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const platform = process.env.PLATFORM;
const pages = JSON.parse(process.env.TARGET_PAGES || "[]");
const resultsPath = process.env.RESULTS_PATH || "tier0-results-safari.json";

// Mirrors Lane A's viewport set exactly, so Safari's evidence is comparable
// to Chrome/Edge's rather than testing a different set of breakpoints.
const VIEWPORTS = [
  ["Desktop", 1440, 900],
  ["Mobile", 390, 844],
];

const RESPONSIVE_ASSERTIONS_JS_PATH = fileURLToPath(
  new URL("../../apps/api/app/services/responsive_assertions.js", import.meta.url),
);

if (!platform) {
  throw new Error("PLATFORM is required (macos) -- M4 ingestion keys results by it.");
}
if (pages.length === 0) {
  throw new Error("TARGET_PAGES must contain at least one URL.");
}

// Selenium's executeScript runs `script` as a function BODY (arguments via
// the `arguments` magic variable), unlike Playwright's page.evaluate which
// takes an expression -- so the wrapping differs from Lane A even though the
// underlying assertion module is identical. Materialization happens INSIDE
// the browser (not in this Node process) via the same indirect-eval
// technique Lane A's Node/Playwright script uses to avoid the shared
// module's leading-comment ASI trap (see that file's loadResponsiveAssertions
// for the root-caused explanation).
function buildExecuteScriptBody(assertionsSource) {
  return `
    const fn = (0, eval)(${JSON.stringify(assertionsSource)});
    return fn(arguments[0]);
  `;
}

async function measureActualViewport(driver, targetWidth, targetHeight) {
  // WebDriver's window.setRect sizes the OUTER window, not the inner
  // document viewport -- macOS window chrome (title bar, etc.) eats part of
  // it. Rather than guess the exact chrome overhead, set a generous rect and
  // measure what the page actually sees, then use THAT for the assertion
  // call -- always honest about what was really tested.
  await driver.manage().window().setRect({
    x: 0,
    y: 0,
    width: targetWidth + 40,
    height: targetHeight + 120,
  });
  const [actualWidth, actualHeight] = await driver.executeScript(
    "return [window.innerWidth, window.innerHeight];",
  );
  return [actualWidth, actualHeight];
}

async function checkPage(driver, url, assertionScriptBody) {
  let navigationError = null;
  try {
    await driver.get(url);
  } catch (error) {
    navigationError = String(error && error.message ? error.message : error);
  }

  const viewportResults = [];
  if (!navigationError) {
    for (const [name, targetWidth, targetHeight] of VIEWPORTS) {
      try {
        const [width, height] = await measureActualViewport(driver, targetWidth, targetHeight);
        viewportResults.push(
          await driver.executeScript(assertionScriptBody, [name, width, height]),
        );
      } catch (error) {
        viewportResults.push({
          name,
          width: targetWidth,
          height: targetHeight,
          status: "failed",
          error: String(error && error.message ? error.message : error),
        });
      }
    }
  }

  const viewportProblems = viewportResults.flatMap((result) => result.viewport_problems || []);
  const passed = !navigationError && viewportProblems.length === 0;
  return {
    url,
    status: passed ? "pass" : "fail",
    http_status: null,
    console_error_count: 0,
    ...(navigationError ? { error: navigationError } : {}),
    viewport_results: viewportResults,
  };
}

async function main() {
  const responsiveAssertionsSource = await readFile(RESPONSIVE_ASSERTIONS_JS_PATH, "utf-8");
  const assertionScriptBody = buildExecuteScriptBody(responsiveAssertionsSource);

  const driver = await new Builder().forBrowser(Browser.SAFARI).build();
  try {
    const capabilities = await driver.getCapabilities();
    const browserVersion = capabilities.getBrowserVersion();

    const pageResults = [];
    for (const url of pages) {
      pageResults.push(await checkPage(driver, url, assertionScriptBody));
    }
    const allPassed = pageResults.every((result) => result.status === "pass");
    const results = {
      channel: "safari",
      platform,
      browser_version: browserVersion,
      overall_status: allPassed ? "pass" : "fail",
      pages: pageResults,
    };
    await writeFile(resultsPath, JSON.stringify(results, null, 2));
    console.log(JSON.stringify(results, null, 2));
  } finally {
    await driver.quit();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

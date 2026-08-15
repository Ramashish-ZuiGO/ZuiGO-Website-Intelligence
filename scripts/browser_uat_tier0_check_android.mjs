// Lane C of the device/OS/browser QA initiative
// (docs/DEVICE_OS_BROWSER_QA_PLAN.md M2 Lane C): drive REAL Chrome on a REAL
// Android device via ChromeDriver's official Android support
// (https://developer.chrome.com/docs/chromedriver/get-started/android),
// which connects over `adb` to whatever device is currently attached --
// physical hardware over USB, or a device reached through a remote-debug
// bridge (e.g. Samsung Remote Test Lab), same script either way.
//
// UNLIKE Lane A/B, this is NOT dispatched by a GitHub Actions job -- no free
// CI provider offers live adb/network access to a real Android device during
// an unattended cloud run (Firebase Test Lab's free tier only runs
// self-contained on-device instrumentation tests with no live network
// access; investigated and rejected for this exact reason, see the plan
// doc's Lane C entry). This is why it lives in scripts/ (operator-run tools)
// rather than .github/scripts/ (CI-only). Meant to be run BY A HUMAN from
// any machine with `adb` access to a real device -- a developer's own
// Android phone for ad-hoc checks, or a Samsung Remote Test Lab device
// connected via its Remote Debug Bridge. Its JSON output feeds into the same
// browser_uat_tier0 tables as Lane A/B via scripts/ingest_manual_tier0_result.py
// (see that file), a manual companion to the automatic Celery
// dispatch/poll path Lane A/B use.
//
// Also runs the M3 shared responsive-assertion contract, same as every
// other lane -- structural findings, not just navigation pass/fail.
//
// Deliberate difference from Lane A/B: only ONE viewport is measured per
// page (the device's own real screen), not a Desktop+Mobile pair -- a real
// phone has no resizable "window", and pretending to test a 1440x900
// desktop viewport on a handset would be fabricated evidence, not real.
//
// Same WebDriver-protocol limitations as Lane B, for the same reasons (see
// that file's header): http_status always null, console_error_count always
// 0 (ChromeDriver's browser-log capability exists but has a documented
// history of version-dependent breakage -- deliberately not relied on here;
// a real future upgrade, not a silent gap, since it's unused downstream).
//
// Env vars:
//   TARGET_PAGES           JSON array of URLs to check
//   RESULTS_PATH           where to write the JSON results artifact
//   ANDROID_DEVICE_SERIAL  optional -- adb device serial, only needed when
//                          more than one device is attached (`adb devices`)

import { Builder } from "selenium-webdriver";
import chrome from "selenium-webdriver/chrome.js";
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const pages = JSON.parse(process.env.TARGET_PAGES || "[]");
const resultsPath = process.env.RESULTS_PATH || "tier0-results-android.json";
const deviceSerial = process.env.ANDROID_DEVICE_SERIAL || null;

const RESPONSIVE_ASSERTIONS_JS_PATH = fileURLToPath(
  new URL("../apps/api/app/services/responsive_assertions.js", import.meta.url),
);

if (pages.length === 0) {
  throw new Error("TARGET_PAGES must contain at least one URL.");
}

// Same function-body wrapping as Lane B's Safari script -- Selenium's
// executeScript convention is identical across browsers, only the browser
// launch mechanism differs.
function buildExecuteScriptBody(assertionsSource) {
  return `
    const fn = (0, eval)(${JSON.stringify(assertionsSource)});
    return fn(arguments[0]);
  `;
}

async function checkPage(driver, url, assertionScriptBody) {
  let navigationError = null;
  try {
    await driver.get(url);
  } catch (error) {
    navigationError = String(error && error.message ? error.message : error);
  }

  let viewportResult = null;
  if (!navigationError) {
    try {
      const [width, height] = await driver.executeScript(
        "return [window.innerWidth, window.innerHeight];",
      );
      viewportResult = await driver.executeScript(assertionScriptBody, [
        "Mobile (real device)",
        width,
        height,
      ]);
    } catch (error) {
      viewportResult = {
        name: "Mobile (real device)",
        status: "failed",
        error: String(error && error.message ? error.message : error),
      };
    }
  }

  const viewportResults = viewportResult ? [viewportResult] : [];
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

  const options = new chrome.Options().androidChrome();
  if (deviceSerial) {
    options.androidDeviceSerial(deviceSerial);
  }
  const driver = await new Builder().forBrowser("chrome").setChromeOptions(options).build();
  try {
    const capabilities = await driver.getCapabilities();
    const browserVersion = capabilities.getBrowserVersion();

    const pageResults = [];
    for (const url of pages) {
      pageResults.push(await checkPage(driver, url, assertionScriptBody));
    }
    const allPassed = pageResults.every((result) => result.status === "pass");
    const results = {
      channel: "chrome",
      platform: "android",
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

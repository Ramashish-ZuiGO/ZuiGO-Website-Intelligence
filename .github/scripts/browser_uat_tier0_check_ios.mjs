// iOS/iPadOS Safari lane of the device/OS/browser QA initiative
// (docs/DEVICE_OS_BROWSER_QA_PLAN.md M2 iOS lane): drive REAL Safari on a
// REAL iOS/iPadOS Simulator via Appium's official Safari driver
// (https://appium.github.io/appium-safari-driver/latest/), which speaks the
// standard WebDriver protocol -- reached here through the existing
// selenium-webdriver client pointed at a local Appium server
// (`new Builder().usingServer("http://localhost:4723")`), the exact same
// client library Lane B/C already use, just targeting a different endpoint.
//
// UNLIKE Lane C (Android), this IS fully automatable inside a GitHub Actions
// job: macOS runners ship Xcode with iOS/iPadOS Simulator runtimes
// preinstalled (verified for Lane B's macOS-runner research; simulators need
// no real device, no adb, no manual reservation), and Appium's Safari driver
// documents iOS Simulator support as a first-class capability set
// (`platformName: "ios"`, `appium:automationName: "Safari"`,
// `safari:useSimulator: true`). This is why this script lives in
// .github/scripts/ (CI-only) rather than scripts/ (operator-run), unlike
// Lane C's Android script.
//
// Real, documented risk this lane carries (cited, not assumed): iOS
// Simulator JS execution via Appium/WebDriverAgent has a real history of
// version-dependent reliability issues -- see e.g.
// https://github.com/appium/appium/issues/8735 and
// https://github.com/appium/appium/issues/1791 (JS silently not running,
// or not running again after in-page navigation, on some Appium/iOS
// version combinations). This is the single largest unverified assumption
// in this lane -- no macOS/Xcode/Simulator environment was available this
// session to run it live (same category of gap as Lane B's macOS-runner
// TCC-fix assumption). Treat the first real dispatch as this lane's actual
// verification, same convention as every prior lane in this initiative.
//
// Deliberate parallels with Lane C, for the same reasons (see that script's
// header): only ONE viewport is measured per page (the simulator's own
// device screen, measured via window.innerWidth/innerHeight), not a
// Desktop+Mobile pair -- a phone/tablet simulator has no resizable window.
// Same WebDriver-protocol limitations as Lane B/C: http_status always null,
// console_error_count always 0 (Safari-family drivers never expose
// retrievable console logs, confirmed unused downstream).
//
// Env vars (set by browser-uat-tier0-desktop.yml):
//   TARGET_PAGES        JSON array of URLs to check
//   RESULTS_PATH        where to write the JSON results artifact
//   IOS_DEVICE_TYPE     "iPhone" or "iPad" -- also determines the reported
//                       platform code (ios vs ipados)
//   IOS_DEVICE_NAME     optional -- e.g. "iPhone 15" (safari:deviceName)
//   IOS_PLATFORM_VERSION  optional -- e.g. "18" (safari:platformVersion,
//                       prefix-matched). Deliberately omitted by default so
//                       this doesn't go stale as Xcode/Simulator defaults
//                       change on the runner image -- Appium picks whatever
//                       simulator is actually available.
//   APPIUM_SERVER_URL   defaults to http://localhost:4723

import { Builder } from "selenium-webdriver";
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const pages = JSON.parse(process.env.TARGET_PAGES || "[]");
const resultsPath = process.env.RESULTS_PATH || "tier0-results-ios.json";
const deviceType = process.env.IOS_DEVICE_TYPE;
const deviceName = process.env.IOS_DEVICE_NAME || null;
const platformVersion = process.env.IOS_PLATFORM_VERSION || null;
const appiumServerUrl = process.env.APPIUM_SERVER_URL || "http://localhost:4723";

const RESPONSIVE_ASSERTIONS_JS_PATH = fileURLToPath(
  new URL("../../apps/api/app/services/responsive_assertions.js", import.meta.url),
);

const DEVICE_TYPE_TO_PLATFORM_CODE = { iPhone: "ios", iPad: "ipados" };

if (!deviceType || !(deviceType in DEVICE_TYPE_TO_PLATFORM_CODE)) {
  throw new Error('IOS_DEVICE_TYPE is required and must be "iPhone" or "iPad".');
}
if (pages.length === 0) {
  throw new Error("TARGET_PAGES must contain at least one URL.");
}

// Same function-body wrapping as Lane B/C -- Selenium's executeScript
// convention is identical regardless of what's on the other end of the
// WebDriver protocol (a local browser process, or an Appium server proxying
// to WebDriverAgent).
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
        `${deviceType} Simulator`,
        width,
        height,
      ]);
    } catch (error) {
      viewportResult = {
        name: `${deviceType} Simulator`,
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

  const capabilities = {
    platformName: "ios",
    "appium:automationName": "Safari",
    browserName: "Safari",
    "safari:useSimulator": true,
    "safari:deviceType": deviceType,
  };
  if (deviceName) capabilities["safari:deviceName"] = deviceName;
  if (platformVersion) capabilities["safari:platformVersion"] = platformVersion;

  const driver = await new Builder()
    .usingServer(appiumServerUrl)
    .withCapabilities(capabilities)
    .build();
  try {
    const sessionCapabilities = await driver.getCapabilities();
    const browserVersion = sessionCapabilities.getBrowserVersion();

    const pageResults = [];
    for (const url of pages) {
      pageResults.push(await checkPage(driver, url, assertionScriptBody));
    }
    const allPassed = pageResults.every((result) => result.status === "pass");
    const results = {
      channel: "safari",
      platform: DEVICE_TYPE_TO_PLATFORM_CODE[deviceType],
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

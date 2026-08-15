"""Lane C (docs/DEVICE_OS_BROWSER_QA_PLAN.md M2 Lane C): manually-operated
Android script contract.

Unlike Lane A/B, this script is not invoked by any GitHub Actions workflow --
no free CI provider offers live adb access to a real Android device -- so
there is no workflow YAML to validate. These are structural checks only, no
real Android device available to execute this against locally.
"""

import subprocess
from pathlib import Path

SCRIPT_PATH = Path("scripts/browser_uat_tier0_check_android.mjs")


def test_script_exists_outside_github_scripts() -> None:
    # Deliberately NOT under .github/scripts/ -- that directory implies
    # "run by a GitHub Actions job", which this script never is.
    assert SCRIPT_PATH.exists()
    assert not str(SCRIPT_PATH).startswith(".github")


def test_script_requires_target_pages() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "TARGET_PAGES" in source
    assert "must contain at least one URL" in source


def test_script_uses_chromedriver_android_support_not_playwright_or_appium() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'from "selenium-webdriver"' in source
    assert "androidChrome()" in source
    assert 'from "playwright"' not in source

    # "appium" legitimately appears in the header comment (explaining why
    # Firebase Test Lab was rejected) -- the real assertion is no appium
    # package import.
    assert 'from "appium' not in source.lower()


def test_script_reports_the_real_chrome_channel_and_android_platform() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'channel: "chrome"' in source
    assert 'platform: "android"' in source


def test_script_supports_an_optional_device_serial_for_multi_device_hosts() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "ANDROID_DEVICE_SERIAL" in source
    assert "androidDeviceSerial" in source


def test_script_always_reports_null_http_status() -> None:
    # Same general Selenium/WebDriver limitation as Lane B (no navigation
    # HTTP status in the base WebDriver protocol) -- not Android-specific.
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "http_status: null" in source


def test_script_tests_exactly_one_real_device_viewport_not_a_desktop_pair() -> None:
    # A real phone has no resizable window -- pretending to test a
    # 1440x900 desktop viewport on a handset would be fabricated evidence.
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert '"Mobile (real device)"' in source
    assert '["Desktop", 1440, 900]' not in source


def test_script_measures_the_actual_device_viewport_rather_than_assuming_one() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "window.innerWidth" in source
    assert "window.innerHeight" in source


def test_script_loads_the_shared_m3_responsive_assertions_module() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "apps/api/app/services/responsive_assertions.js" in source
    assert "readFile(RESPONSIVE_ASSERTIONS_JS_PATH" in source


def test_script_wraps_the_assertion_module_as_an_executescript_function_body() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "(0, eval)(${JSON.stringify(assertionsSource)})" in source
    assert "return fn(arguments[0]);" in source


def test_script_syntax_is_valid() -> None:
    result = subprocess.run(
        ["node", "--check", str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

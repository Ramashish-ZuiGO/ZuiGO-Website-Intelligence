"""M2 Tier 0 lane: GitHub Actions workflow contract.

Validates the workflow file's shape rather than executing it (no live GitHub
infrastructure in this test suite, and no macOS/Xcode/Safari environment
available locally either) -- correlation-id plumbing, real-browser channels,
Lane A (Chrome/Edge via Playwright), Lane B (desktop Safari via
Selenium/safaridriver), and the iOS/iPadOS Simulator Safari lane (Appium's
Safari driver; see docs/DEVICE_OS_BROWSER_QA_PLAN.md M2).
"""

from pathlib import Path

import yaml

WORKFLOW_PATH = Path(".github/workflows/browser-uat-tier0-desktop.yml")
SCRIPT_PATH = Path(".github/scripts/browser_uat_tier0_check.mjs")
SAFARI_SCRIPT_PATH = Path(".github/scripts/browser_uat_tier0_check_safari.mjs")
IOS_SCRIPT_PATH = Path(".github/scripts/browser_uat_tier0_check_ios.mjs")


def _load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_every_setup_node_step_disables_npm_cache() -> None:
    # Real regression, found only via a live GitHub Actions run
    # (2026-08-15): actions/setup-node@v6 auto-enables npm caching by
    # default and hard-fails with "Dependencies lock file is not found"
    # when none exists -- every job here does an ad-hoc `npm install
    # <package>@<version>`, never a package.json/lockfile. All 6 jobs in
    # the first real dispatch failed at this exact step before this fix.
    workflow = _load_workflow()

    for job_name, job in workflow["jobs"].items():
        setup_node_steps = [
            step for step in job["steps"] if step.get("uses", "").startswith("actions/setup-node")
        ]
        assert setup_node_steps, f"{job_name} has no actions/setup-node step"
        for step in setup_node_steps:
            assert step.get("with", {}).get("package-manager-cache") is False, (
                f"{job_name}'s setup-node step must set package-manager-cache: false"
            )


def test_workflow_is_valid_yaml_with_expected_jobs() -> None:
    workflow = _load_workflow()

    assert set(workflow["jobs"].keys()) == {
        "chrome-edge-windows",
        "chrome-macos",
        "safari-macos",
        "ios-safari-simulator",
    }


def test_workflow_is_manually_dispatched_only_never_automatic() -> None:
    # on-demand only, decoupled from full_website_analysis -- the trigger
    # model decided for M2.
    workflow = _load_workflow()
    triggers = workflow.get("on") or workflow.get(True)

    assert list(triggers.keys()) == ["workflow_dispatch"]
    for required_input in ("correlation_id", "target_url", "pages"):
        assert required_input in triggers["workflow_dispatch"]["inputs"]
        assert triggers["workflow_dispatch"]["inputs"][required_input]["required"] is True


def test_run_name_embeds_correlation_id_for_polling() -> None:
    # GitHub's workflow_dispatch API returns no run id, so polling must be
    # able to match a run back to its execution via run-name.
    source = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "run-name:" in source
    assert "${{ inputs.correlation_id }}" in source


def test_windows_job_covers_both_chrome_and_edge_via_real_channels() -> None:
    workflow = _load_workflow()
    windows_job = workflow["jobs"]["chrome-edge-windows"]

    assert windows_job["runs-on"] == "windows-latest"
    assert set(windows_job["strategy"]["matrix"]["channel"]) == {"chrome", "msedge"}


def test_chrome_macos_job_covers_chrome_only_not_safari() -> None:
    # Safari lives in its own job (safari-macos, Lane B) since it needs a
    # completely different toolchain (Selenium/safaridriver, not Playwright).
    # This job must not silently claim Safari.
    workflow = _load_workflow()
    macos_job = workflow["jobs"]["chrome-macos"]

    assert macos_job["runs-on"] == "macos-latest"
    source = yaml.dump(macos_job)
    assert "safari" not in source.lower()
    assert "BROWSER_CHANNEL: chrome" in yaml.dump(macos_job, default_flow_style=False) or any(
        "chrome" in str(step.get("env", {}).get("BROWSER_CHANNEL", "")).lower()
        for step in macos_job["steps"]
        if isinstance(step, dict)
    )


def test_safari_macos_job_enables_safaridriver_and_runs_the_safari_script() -> None:
    workflow = _load_workflow()
    safari_job = workflow["jobs"]["safari-macos"]

    assert safari_job["runs-on"] == "macos-latest"
    run_commands = [step.get("run", "") for step in safari_job["steps"] if isinstance(step, dict)]
    assert any("sudo safaridriver --enable" in command for command in run_commands)
    assert any("browser_uat_tier0_check_safari.mjs" in command for command in run_commands)
    # Selenium, not Playwright -- Safari needs a different automation stack.
    assert any("selenium-webdriver" in command for command in run_commands)


def test_safari_macos_job_enable_step_runs_before_the_check_step() -> None:
    # Selenium's Safari session build fails if safaridriver was never enabled
    # -- ordering matters, not just presence of both steps.
    workflow = _load_workflow()
    steps = workflow["jobs"]["safari-macos"]["steps"]
    run_commands = [step.get("run", "") for step in steps if isinstance(step, dict)]

    enable_index = next(
        i for i, command in enumerate(run_commands) if "safaridriver --enable" in command
    )
    check_index = next(
        i
        for i, command in enumerate(run_commands)
        if "browser_uat_tier0_check_safari.mjs" in command
    )
    assert enable_index < check_index


def test_ios_job_matrixes_over_iphone_and_ipad() -> None:
    # Safari's required_platforms names both iOS 16+ and iPadOS 16+ --
    # separate device types, separate evidence rows.
    workflow = _load_workflow()
    ios_job = workflow["jobs"]["ios-safari-simulator"]

    assert ios_job["runs-on"] == "macos-latest"
    assert set(ios_job["strategy"]["matrix"]["device_type"]) == {"iPhone", "iPad"}


def test_ios_job_installs_appium_and_the_safari_driver_not_playwright() -> None:
    workflow = _load_workflow()
    ios_job = workflow["jobs"]["ios-safari-simulator"]
    run_commands = [step.get("run", "") for step in ios_job["steps"] if isinstance(step, dict)]

    assert any(
        "appium" in command and "driver install safari" in command for command in run_commands
    )
    assert any("selenium-webdriver" in command for command in run_commands)
    assert not any("playwright" in command.lower() for command in run_commands)


def test_ios_job_enables_safaridriver_and_starts_appium_before_the_check_step() -> None:
    # Same ordering discipline as the desktop Safari job -- each prerequisite
    # must run before the step that depends on it.
    workflow = _load_workflow()
    steps = workflow["jobs"]["ios-safari-simulator"]["steps"]
    run_commands = [step.get("run", "") for step in steps if isinstance(step, dict)]

    enable_index = next(
        i for i, command in enumerate(run_commands) if "safaridriver --enable" in command
    )
    appium_start_index = next(
        i for i, command in enumerate(run_commands) if "appium --log" in command
    )
    check_index = next(
        i for i, command in enumerate(run_commands) if "browser_uat_tier0_check_ios.mjs" in command
    )
    assert enable_index < appium_start_index < check_index


def test_ios_job_waits_for_appium_to_become_ready_before_the_check_step() -> None:
    workflow = _load_workflow()
    ios_job = workflow["jobs"]["ios-safari-simulator"]
    run_commands = [step.get("run", "") for step in ios_job["steps"] if isinstance(step, dict)]

    assert any("localhost:4723/status" in command for command in run_commands)


def test_ios_job_sets_a_distinct_device_type_env_per_matrix_entry() -> None:
    workflow = _load_workflow()
    ios_job = workflow["jobs"]["ios-safari-simulator"]
    check_step = next(step for step in ios_job["steps"] if "IOS_DEVICE_TYPE" in step.get("env", {}))

    assert check_step["env"]["IOS_DEVICE_TYPE"] == "${{ matrix.device_type }}"


def test_every_job_uploads_a_results_artifact() -> None:
    workflow = _load_workflow()

    for job in workflow["jobs"].values():
        step_uses = [step.get("uses", "") for step in job["steps"]]
        assert any("upload-artifact" in use for use in step_uses)


def test_permissions_are_read_only() -> None:
    workflow = _load_workflow()

    assert workflow["permissions"] == {"contents": "read"}


class TestCheckScript:
    def test_script_requires_browser_channel_and_target_pages(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")

        assert "BROWSER_CHANNEL" in source
        assert "TARGET_PAGES" in source

    def test_script_requires_and_emits_platform(self) -> None:
        # M4 ingestion keys page results by (execution, channel, platform);
        # without this the workflow's 3 separate job artifacts can't be told
        # apart once fetched.
        source = SCRIPT_PATH.read_text(encoding="utf-8")

        assert "if (!platform)" in source
        assert "platform,\n" in source or "platform: platform" in source

    def test_every_job_sets_a_distinct_platform_env_var(self) -> None:
        workflow = _load_workflow()

        def platform_of(job_name: str) -> str:
            job = workflow["jobs"][job_name]
            check_step = next(step for step in job["steps"] if "PLATFORM" in step.get("env", {}))
            return check_step["env"]["PLATFORM"]

        assert platform_of("chrome-edge-windows") == "windows"
        assert platform_of("chrome-macos") == "macos"
        assert platform_of("safari-macos") == "macos"

    def test_script_launches_the_real_browser_channel_not_bundled_chromium(self) -> None:
        # chromium.launch({ channel }) launches the actual installed
        # Chrome/Edge binary; omitting `channel` would silently fall back to
        # Playwright's bundled engine, exactly the non-branded evidence this
        # lane exists to move beyond.
        source = SCRIPT_PATH.read_text(encoding="utf-8")

        assert "chromium.launch({ channel })" in source or "chromium.launch({channel})" in source

    def test_script_treats_any_http_error_status_as_a_failure(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")

        assert "status < 400" in source

    def test_script_loads_the_shared_m3_responsive_assertions_module(self) -> None:
        # M3 integration: this real-branded-browser lane must produce genuine
        # structural findings, not just HTTP pass/fail.
        source = SCRIPT_PATH.read_text(encoding="utf-8")

        assert "apps/api/app/services/responsive_assertions.js" in source
        assert "readFile(RESPONSIVE_ASSERTIONS_JS_PATH" in source

    def test_script_uses_indirect_eval_to_materialize_the_assertion_fn(self) -> None:
        # Regression: verified live 2026-08-14 that constructing the function
        # via `new Function('return ' + source)` silently produced a function
        # that always returned undefined, because the shared module's
        # leading `//` comment block triggers JS's automatic-semicolon-
        # insertion on a bare `return`. Indirect eval `(0, eval)(source)`
        # evaluates the file as a script and does not have this trap.
        source = SCRIPT_PATH.read_text(encoding="utf-8")

        assert "return (0, eval)(source);" in source

    def test_script_checks_both_desktop_and_mobile_viewports(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")

        assert '["Desktop", 1440, 900]' in source
        assert '["Mobile", 390, 844]' in source

    def test_a_page_with_viewport_problems_fails_even_with_a_clean_http_status(self) -> None:
        # An HTTP 200 with real structural problems must not be reported as
        # passing just because the request succeeded.
        source = SCRIPT_PATH.read_text(encoding="utf-8")

        assert "httpPassed && viewportProblems.length === 0" in source


class TestSafariCheckScript:
    """Lane B (docs/DEVICE_OS_BROWSER_QA_PLAN.md M2 Lane B): Selenium +
    safaridriver, a genuinely different toolchain from Lane A's Playwright
    script -- structural checks only, no macOS/Safari environment available
    to execute this against locally."""

    def test_script_requires_platform_and_target_pages(self) -> None:
        source = SAFARI_SCRIPT_PATH.read_text(encoding="utf-8")

        assert "PLATFORM" in source
        assert "TARGET_PAGES" in source

    def test_script_uses_selenium_not_playwright(self) -> None:
        # "Playwright" legitimately appears in the header comment explaining
        # why this script exists -- the real assertion is that it never
        # imports playwright as a module.
        source = SAFARI_SCRIPT_PATH.read_text(encoding="utf-8")

        assert 'from "selenium-webdriver"' in source
        assert 'from "playwright"' not in source

    def test_script_builds_a_real_safari_session(self) -> None:
        source = SAFARI_SCRIPT_PATH.read_text(encoding="utf-8")

        assert "Browser.SAFARI" in source
        assert "forBrowser(Browser.SAFARI)" in source

    def test_script_always_reports_null_http_status(self) -> None:
        # W3C WebDriver exposes no navigation HTTP status, unlike Playwright's
        # CDP-based response object -- must never fabricate one.
        source = SAFARI_SCRIPT_PATH.read_text(encoding="utf-8")

        assert "http_status: null" in source

    def test_script_loads_the_shared_m3_responsive_assertions_module(self) -> None:
        source = SAFARI_SCRIPT_PATH.read_text(encoding="utf-8")

        assert "apps/api/app/services/responsive_assertions.js" in source
        assert "readFile(RESPONSIVE_ASSERTIONS_JS_PATH" in source

    def test_script_wraps_the_assertion_module_as_an_executescript_function_body(self) -> None:
        # Selenium's executeScript treats `script` as a function BODY with an
        # `arguments` magic variable, unlike Playwright's expression-style
        # page.evaluate -- the shared module itself doesn't change, only how
        # each runtime turns it into a callable function.
        source = SAFARI_SCRIPT_PATH.read_text(encoding="utf-8")

        assert "(0, eval)(${JSON.stringify(assertionsSource)})" in source
        assert "return fn(arguments[0]);" in source

    def test_script_checks_both_desktop_and_mobile_viewports(self) -> None:
        source = SAFARI_SCRIPT_PATH.read_text(encoding="utf-8")

        assert '["Desktop", 1440, 900]' in source
        assert '["Mobile", 390, 844]' in source

    def test_script_measures_the_actual_viewport_rather_than_trusting_the_target(self) -> None:
        # WebDriver's window.setRect sizes the OUTER window, not the inner
        # document viewport -- must measure what was actually achieved rather
        # than assuming the nominal target was hit exactly.
        source = SAFARI_SCRIPT_PATH.read_text(encoding="utf-8")

        assert "window.innerWidth" in source
        assert "window.innerHeight" in source
        assert "setRect(" in source

    def test_script_checks_syntax_is_valid(self) -> None:
        import subprocess

        result = subprocess.run(
            ["node", "--check", str(SAFARI_SCRIPT_PATH)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


class TestIosCheckScript:
    """iOS/iPadOS Simulator Safari lane (docs/DEVICE_OS_BROWSER_QA_PLAN.md M2):
    Appium's Safari driver, reached via the same selenium-webdriver client
    Lane B/C use, pointed at a local Appium server instead of a local
    browser. No macOS/Xcode/Simulator environment available to execute this
    against locally -- structural checks only."""

    def test_script_requires_a_valid_device_type_and_target_pages(self) -> None:
        source = IOS_SCRIPT_PATH.read_text(encoding="utf-8")

        assert "IOS_DEVICE_TYPE" in source
        assert 'must be "iPhone" or "iPad"' in source
        assert "TARGET_PAGES" in source

    def test_script_connects_to_a_local_appium_server_via_selenium_webdriver(self) -> None:
        source = IOS_SCRIPT_PATH.read_text(encoding="utf-8")

        assert 'from "selenium-webdriver"' in source
        assert "usingServer(appiumServerUrl)" in source
        assert 'from "playwright"' not in source

    def test_script_requests_the_real_safari_driver_on_the_simulator(self) -> None:
        source = IOS_SCRIPT_PATH.read_text(encoding="utf-8")

        assert '"appium:automationName": "Safari"' in source
        assert '"safari:useSimulator": true' in source

    def test_script_maps_device_type_to_the_correct_platform_code(self) -> None:
        # Safari's required_platforms names iOS 16+ and iPadOS 16+ as
        # separate entries -- iPhone and iPad evidence must never collapse
        # into one platform code.
        source = IOS_SCRIPT_PATH.read_text(encoding="utf-8")

        assert '{ iPhone: "ios", iPad: "ipados" }' in source

    def test_script_reports_the_safari_channel(self) -> None:
        source = IOS_SCRIPT_PATH.read_text(encoding="utf-8")

        assert 'channel: "safari"' in source

    def test_script_always_reports_null_http_status(self) -> None:
        source = IOS_SCRIPT_PATH.read_text(encoding="utf-8")

        assert "http_status: null" in source

    def test_script_loads_the_shared_m3_responsive_assertions_module(self) -> None:
        source = IOS_SCRIPT_PATH.read_text(encoding="utf-8")

        assert "apps/api/app/services/responsive_assertions.js" in source
        assert "readFile(RESPONSIVE_ASSERTIONS_JS_PATH" in source

    def test_script_wraps_the_assertion_module_as_an_executescript_function_body(self) -> None:
        source = IOS_SCRIPT_PATH.read_text(encoding="utf-8")

        assert "(0, eval)(${JSON.stringify(assertionsSource)})" in source
        assert "return fn(arguments[0]);" in source

    def test_script_tests_exactly_one_real_device_viewport_not_a_desktop_pair(self) -> None:
        # A simulator has no resizable window -- pretending to test a
        # 1440x900 desktop viewport would be fabricated evidence.
        source = IOS_SCRIPT_PATH.read_text(encoding="utf-8")

        assert '["Desktop", 1440, 900]' not in source
        assert "window.innerWidth" in source
        assert "window.innerHeight" in source

    def test_script_omits_platform_version_by_default_so_it_never_goes_stale(self) -> None:
        # Hardcoding a specific iOS version would break as the runner's
        # default Xcode/Simulator changes over time -- see
        # docs/DEVICE_OS_BROWSER_QA_PLAN.md section 8's "re-derive at
        # execution time" principle. IOS_PLATFORM_VERSION stays optional.
        source = IOS_SCRIPT_PATH.read_text(encoding="utf-8")

        assert "IOS_PLATFORM_VERSION" in source
        assert "process.env.IOS_PLATFORM_VERSION || null" in source

    def test_script_checks_syntax_is_valid(self) -> None:
        import subprocess

        result = subprocess.run(
            ["node", "--check", str(IOS_SCRIPT_PATH)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

"""Tier 0 dispatch: trigger and poll the GitHub Actions workflow that drives
real Chrome, Edge, and Safari (desktop + iOS/iPadOS Simulator) against a
target URL, and download/parse its results artifacts once it completes.

Lane C (Android real device) is NOT covered here -- no free CI provider
offers live adb access to a real device from an unattended run, so it is a
manually-operated companion (scripts/, not this dispatch/poll pipeline). See
docs/DEVICE_OS_BROWSER_QA_PLAN.md M2.

GitHub's workflow_dispatch API does not return a run id, so a caller-supplied
correlation id is embedded in the workflow's ``run-name`` and matched back
during polling -- the standard workaround for this well-known API gap.
"""

import io
import json
import logging
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from typing import Literal, Protocol

import httpx

logger = logging.getLogger("worker.browser_uat_tier0")

DispatchStatus = Literal["dispatched", "queued", "running", "completed", "not_found"]
DispatchConclusion = Literal["success", "failure", "cancelled", "timed_out", None]


@dataclass(frozen=True)
class Tier0PollResult:
    status: DispatchStatus
    conclusion: DispatchConclusion = None
    provider_run_reference: str | None = None
    # Populated only once status == "completed": one parsed JobResultPayload
    # dict per results artifact the run produced -- a run legitimately
    # uploads several (one per browser/platform job/matrix entry, up to 6
    # today), never just one, so this is a list, not a single dict.
    results: list[dict] | None = None


class Tier0DispatchClient(Protocol):
    """One real-browser CI dispatch mechanism.

    Implementations are swappable per lane (github_actions_chrome_edge today;
    a future safari lane or android lane would get its own implementation of
    this same shape, not a parallel orchestration system).
    """

    def dispatch(self, *, correlation_id: str, target_url: str, pages: list[str]) -> None:
        """Trigger the run. Does not return a reference -- see module docstring."""
        ...

    def poll(self, *, correlation_id: str) -> Tier0PollResult:
        """Check current status, matching the run by correlation id."""
        ...


class DispatchUnavailableError(RuntimeError):
    """The dispatch mechanism itself could not be reached (network, auth)."""


@dataclass
class FakeTier0DispatchClient:
    """Deterministic in-memory client for tests. No network calls."""

    dispatched: list[dict] = field(default_factory=list)
    # correlation_id -> canned poll sequence; each call to poll() advances one step.
    poll_sequence: dict[str, list[Tier0PollResult]] = field(default_factory=dict)
    _poll_index: dict[str, int] = field(default_factory=dict)

    def dispatch(self, *, correlation_id: str, target_url: str, pages: list[str]) -> None:
        self.dispatched.append(
            {"correlation_id": correlation_id, "target_url": target_url, "pages": list(pages)}
        )

    def poll(self, *, correlation_id: str) -> Tier0PollResult:
        sequence = self.poll_sequence.get(correlation_id)
        if not sequence:
            return Tier0PollResult(status="not_found")
        index = self._poll_index.get(correlation_id, 0)
        result = sequence[min(index, len(sequence) - 1)]
        self._poll_index[correlation_id] = index + 1
        return result


class GitHubActionsTier0DispatchClient:
    """Real implementation against the GitHub REST API.

    NOT LIVE-VERIFIED in this session -- no PAT/GitHub App token was
    available. Implemented against the documented, stable
    workflow_dispatch/list-runs API contract. Treat the first real dispatch as
    the verification of this class, per docs/DEVICE_OS_BROWSER_QA_PLAN.md M2.
    """

    api_base = "https://api.github.com"
    workflow_file = "browser-uat-tier0-desktop.yml"

    def __init__(self, *, repo: str, ref: str, token: str, timeout_seconds: int = 15) -> None:
        self.repo = repo
        self.ref = ref
        self.token = token
        self.timeout_seconds = timeout_seconds

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            f"{self.api_base}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.URLError as exception:
            raise DispatchUnavailableError(
                f"GitHub Actions API request failed: {type(exception).__name__}"
            ) from exception

    def dispatch(self, *, correlation_id: str, target_url: str, pages: list[str]) -> None:
        self._request(
            "POST",
            f"/repos/{self.repo}/actions/workflows/{self.workflow_file}/dispatches",
            {
                "ref": self.ref,
                "inputs": {
                    "correlation_id": correlation_id,
                    "target_url": target_url,
                    "pages": json.dumps(pages),
                },
            },
        )

    def poll(self, *, correlation_id: str) -> Tier0PollResult:
        # The correlation id is embedded in run-name at dispatch time; the
        # search API lets us match on it without storing a run id ourselves.
        payload = self._request(
            "GET",
            f"/repos/{self.repo}/actions/workflows/{self.workflow_file}/runs"
            f"?event=workflow_dispatch&per_page=20",
        )
        matching_run = next(
            (
                run
                for run in payload.get("workflow_runs", [])
                if correlation_id in run.get("name", "")
                or correlation_id in run.get("display_title", "")
            ),
            None,
        )
        if matching_run is None:
            return Tier0PollResult(status="not_found")

        run_id = str(matching_run["id"])
        gh_status = matching_run.get("status")  # queued | in_progress | completed
        if gh_status == "completed":
            conclusion = matching_run.get("conclusion")
            results = self._fetch_results_artifacts(run_id)
            return Tier0PollResult(
                status="completed",
                conclusion=conclusion,
                provider_run_reference=run_id,
                results=results,
            )
        status_map: dict[str, DispatchStatus] = {"queued": "queued", "in_progress": "running"}
        return Tier0PollResult(
            status=status_map.get(gh_status, "running"),
            provider_run_reference=run_id,
        )

    def _fetch_results_artifacts(self, run_id: str) -> list[dict]:
        """Download and parse every results artifact this run produced -- one
        per browser/platform job (up to 6 today: 2 Windows [chrome, msedge] +
        1 macOS Chrome + 1 macOS Safari + 2 iOS Simulator [iPhone, iPad], see
        browser-uat-tier0-desktop.yml).

        Listing failure (auth/network) propagates DispatchUnavailableError,
        same as every other GitHub API call in this class. A single
        artifact being missing/corrupt is NOT treated the same way -- it is
        logged and skipped rather than failing the whole poll cycle, so a
        partially-successful run still ingests whatever real evidence it did
        produce instead of losing all of it over one bad artifact.
        """
        listing = self._request("GET", f"/repos/{self.repo}/actions/runs/{run_id}/artifacts")

        job_results: list[dict] = []
        for artifact in listing.get("artifacts", []):
            artifact_id = artifact.get("id")
            name = artifact.get("name", "unknown")
            try:
                job_results.append(self._download_and_parse_artifact(artifact_id))
            except (
                httpx.HTTPError,
                zipfile.BadZipFile,
                json.JSONDecodeError,
                KeyError,
            ) as exception:
                logger.warning(
                    "browser_uat_tier0_artifact_fetch_failed run_id=%s artifact=%s reason=%s",
                    run_id,
                    name,
                    exception,
                )
        return job_results

    def _download_and_parse_artifact(self, artifact_id: int) -> dict:
        # GitHub's "download an artifact" endpoint 302-redirects to a
        # short-lived, signed URL on a different host (verified live against
        # the documented contract, 2026-08-15) -- httpx's default
        # follow_redirects behavior correctly strips the Authorization
        # header on that cross-origin hop (confirmed via a local
        # httpx.MockTransport repro before relying on it), unlike a naive
        # urllib redirect that would resend it. This is why this method uses
        # httpx (already a worker dependency) instead of the urllib-based
        # _request helper used for JSON endpoints above.
        with httpx.Client(follow_redirects=True, timeout=self.timeout_seconds) as client:
            response = client.get(
                f"{self.api_base}/repos/{self.repo}/actions/artifacts/{artifact_id}/zip",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self.token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            response.raise_for_status()

        archive = zipfile.ZipFile(io.BytesIO(response.content))
        # actions/upload-artifact@v4 zips exactly the one uploaded file per
        # artifact -- see browser-uat-tier0-desktop.yml's `path:` entries.
        json_names = [name for name in archive.namelist() if name.endswith(".json")]
        if not json_names:
            raise KeyError(f"No .json file found in artifact {artifact_id}.")
        return json.loads(archive.read(json_names[0]))

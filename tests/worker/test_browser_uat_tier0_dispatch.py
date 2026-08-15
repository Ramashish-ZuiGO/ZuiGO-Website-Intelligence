"""GitHubActionsTier0DispatchClient's artifact-fetch implementation.

_fetch_results_artifacts (listing + per-artifact loop + skip-on-error) is
tested by monkeypatching the instance's own _request/_download_and_parse_artifact
methods -- pure orchestration logic, no HTTP involved. _download_and_parse_artifact
itself is tested against a real httpx.MockTransport that reproduces GitHub's
documented redirect-to-a-different-host contract (see
docs/DEVICE_OS_BROWSER_QA_PLAN.md's artifact-fetch entry for the citations
this design is based on), so the redirect-following and Authorization-header
handling are exercised for real, not assumed.
"""

import io
import json
import zipfile

import httpx
import pytest
from worker_app.integrations.browser_uat_tier0_dispatch import (
    DispatchUnavailableError,
    GitHubActionsTier0DispatchClient,
)


def _client() -> GitHubActionsTier0DispatchClient:
    return GitHubActionsTier0DispatchClient(repo="owner/repo", ref="main", token="secret-token")


def _zip_bytes(filename: str, payload: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(filename, json.dumps(payload))
    return buffer.getvalue()


VALID_JOB_RESULT = {
    "channel": "chrome",
    "platform": "windows",
    "browser_version": "151.0.7922.137",
    "overall_status": "pass",
    "pages": [],
}


class TestFetchResultsArtifactsOrchestration:
    def test_downloads_and_parses_every_listed_artifact(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client()
        monkeypatch.setattr(
            client,
            "_request",
            lambda method, path: {
                "artifacts": [
                    {"id": 1, "name": "tier0-results-chrome-windows"},
                    {"id": 2, "name": "tier0-results-msedge-windows"},
                ]
            },
        )
        downloaded = []

        def fake_download(artifact_id: int) -> dict:
            downloaded.append(artifact_id)
            return {**VALID_JOB_RESULT, "channel": f"artifact-{artifact_id}"}

        monkeypatch.setattr(client, "_download_and_parse_artifact", fake_download)

        results = client._fetch_results_artifacts("123456")

        assert downloaded == [1, 2]
        assert [result["channel"] for result in results] == ["artifact-1", "artifact-2"]

    def test_a_corrupt_artifact_is_skipped_not_fatal_to_the_others(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A partially-successful run (one job's upload got corrupted) must
        # still surface the OTHER real evidence it produced.
        client = _client()
        monkeypatch.setattr(
            client,
            "_request",
            lambda method, path: {
                "artifacts": [
                    {"id": 1, "name": "tier0-results-chrome-windows"},
                    {"id": 2, "name": "tier0-results-msedge-windows"},
                ]
            },
        )

        def fake_download(artifact_id: int) -> dict:
            if artifact_id == 1:
                raise zipfile.BadZipFile("not a zip")
            return VALID_JOB_RESULT

        monkeypatch.setattr(client, "_download_and_parse_artifact", fake_download)

        results = client._fetch_results_artifacts("123456")

        assert len(results) == 1

    def test_zero_artifacts_returns_an_empty_list_not_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _client()
        monkeypatch.setattr(client, "_request", lambda method, path: {"artifacts": []})

        results = client._fetch_results_artifacts("123456")

        assert results == []

    def test_listing_failure_propagates_as_dispatch_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A real connectivity/auth problem listing artifacts is NOT the same
        # kind of failure as one corrupt artifact -- it must propagate, same
        # as every other GitHub API call in this class, so the caller can
        # mark the whole execution unavailable rather than silently
        # reporting zero results.
        client = _client()

        def explode(method: str, path: str) -> dict:
            raise DispatchUnavailableError("network unreachable")

        monkeypatch.setattr(client, "_request", explode)

        with pytest.raises(DispatchUnavailableError):
            client._fetch_results_artifacts("123456")


class TestDownloadAndParseArtifact:
    def test_follows_the_redirect_and_parses_the_zipped_json(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        zip_content = _zip_bytes("tier0-results-chrome-windows.json", VALID_JOB_RESULT)
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append({"url": str(request.url), "auth": request.headers.get("Authorization")})
            if request.url.host == "api.github.com":
                return httpx.Response(
                    302,
                    headers={
                        "Location": "https://productionresultssa.blob.core.windows.net/signed"
                    },
                )
            return httpx.Response(200, content=zip_content)

        real_client_cls = httpx.Client

        def client_factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client_cls(*args, **kwargs)

        monkeypatch.setattr(httpx, "Client", client_factory)

        client = _client()
        result = client._download_and_parse_artifact(42)

        assert result == VALID_JOB_RESULT
        # Two hops: the GitHub API request (with auth), then the redirect
        # target (auth must be stripped -- verified live against a real
        # httpx.MockTransport repro before relying on this, not assumed).
        assert len(calls) == 2
        assert calls[0]["url"].startswith("https://api.github.com")
        assert calls[0]["auth"] == "Bearer secret-token"
        assert calls[1]["url"].startswith("https://productionresultssa.blob.core.windows.net")
        assert calls[1]["auth"] is None

    def test_a_non_json_archive_raises_key_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("readme.txt", "not json")
        zip_content = buffer.getvalue()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=zip_content)

        real_client_cls = httpx.Client

        def client_factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client_cls(*args, **kwargs)

        monkeypatch.setattr(httpx, "Client", client_factory)

        client = _client()
        with pytest.raises(KeyError):
            client._download_and_parse_artifact(42)

    def test_an_http_error_status_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        real_client_cls = httpx.Client

        def client_factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client_cls(*args, **kwargs)

        monkeypatch.setattr(httpx, "Client", client_factory)

        client = _client()
        with pytest.raises(httpx.HTTPStatusError):
            client._download_and_parse_artifact(42)

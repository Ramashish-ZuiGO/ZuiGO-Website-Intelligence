import subprocess
from pathlib import Path

import pytest
from worker_app.analysis import lighthouse_audit
from worker_app.analysis.errors import AnalysisFailure


class FakeProcess:
    def __init__(self, *, returncode: int = 0, timeout: bool = False) -> None:
        self.returncode = returncode
        self.timeout = timeout
        self.terminated = False
        self.killed = False
        self.calls = 0

    def communicate(self, timeout: int | None = None) -> tuple[str, str]:
        self.calls += 1
        if self.timeout and self.calls == 1:
            raise subprocess.TimeoutExpired("lighthouse", timeout or 0)
        return "stdout", "stderr"

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


def test_lighthouse_timeout_terminates_process(monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess(timeout=True)
    monkeypatch.setattr(lighthouse_audit.subprocess, "Popen", lambda *args, **kwargs: process)
    with pytest.raises(AnalysisFailure) as error:
        lighthouse_audit.run_lighthouse("https://example.com", "/chrome", 1)
    assert error.value.detail.code == "LIGHTHOUSE_TIMEOUT"
    assert process.terminated is True


def test_invalid_lighthouse_json_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess()

    def popen(command: list[str], **kwargs: object) -> FakeProcess:
        output_argument = next(value for value in command if value.startswith("--output-path="))
        Path(output_argument.split("=", 1)[1]).write_text("not-json", encoding="utf-8")
        return process

    monkeypatch.setattr(lighthouse_audit.subprocess, "Popen", popen)
    with pytest.raises(AnalysisFailure) as error:
        lighthouse_audit.run_lighthouse("https://example.com", "/chrome", 1)
    assert error.value.detail.code == "LIGHTHOUSE_INVALID_OUTPUT"

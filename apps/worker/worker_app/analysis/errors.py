from dataclasses import dataclass


@dataclass(frozen=True)
class FailureDetail:
    code: str
    safe_message: str
    stage: str
    retryable: bool
    attempt: int = 1
    internal_detail: str | None = None


class AnalysisFailure(RuntimeError):
    def __init__(self, detail: FailureDetail) -> None:
        super().__init__(detail.code)
        self.detail = detail

    def with_attempt(self, attempt: int) -> "AnalysisFailure":
        return AnalysisFailure(
            FailureDetail(
                code=self.detail.code,
                safe_message=self.detail.safe_message,
                stage=self.detail.stage,
                retryable=self.detail.retryable,
                attempt=attempt,
                internal_detail=self.detail.internal_detail,
            )
        )

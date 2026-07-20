from typing import Protocol


class AIProvider(Protocol):
    name: str
    model: str

    def generate(self, prompt: str) -> str: ...


class ProviderUnavailableError(RuntimeError):
    pass

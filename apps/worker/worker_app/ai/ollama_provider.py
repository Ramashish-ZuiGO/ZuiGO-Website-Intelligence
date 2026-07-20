import json
import urllib.error
import urllib.request

from worker_app.ai.base import ProviderUnavailableError


class OllamaProvider:
    name = "ollama"
    max_response_bytes = 2_000_000

    def __init__(self, model: str, base_url: str, timeout_seconds: int) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def generate(self, prompt: str) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw_response = response.read(self.max_response_bytes + 1)
                if len(raw_response) > self.max_response_bytes:
                    raise ProviderUnavailableError(
                        "The configured AI provider returned oversized output."
                    )
                payload = json.loads(raw_response.decode("utf-8"))
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exception:
            raise ProviderUnavailableError(
                "The configured AI provider is unavailable."
            ) from exception
        generated = payload.get("response")
        if not isinstance(generated, str):
            raise ProviderUnavailableError("The configured AI provider returned invalid output.")
        return generated

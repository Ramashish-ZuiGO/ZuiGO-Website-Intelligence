from worker_app.ai.base import AIProvider, ProviderUnavailableError
from worker_app.ai.ollama_provider import OllamaProvider
from worker_app.config import WorkerSettings


def create_provider(settings: WorkerSettings) -> AIProvider:
    if settings.ai_provider == "ollama":
        return OllamaProvider(
            model=settings.ai_model,
            base_url=str(settings.ai_base_url),
            timeout_seconds=settings.ai_timeout_seconds,
        )
    raise ProviderUnavailableError("AI generation is disabled.")

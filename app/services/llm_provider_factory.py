"""Construction of the configured LLM Provider."""

from app.core.config import Settings
from app.services.httpx_openai_compatible_llm_provider import (
    HttpPost,
    HttpxOpenAiCompatibleLlmProvider,
    default_http_post,
)
from app.services.llm_provider import LlmProvider, MockLlmProvider


def create_llm_provider(
    settings: Settings,
    *,
    http_post: HttpPost = default_http_post,
) -> LlmProvider:
    """Return the safe Mock Provider by default or the configured real Provider."""
    if settings.llm_provider == "real":
        return HttpxOpenAiCompatibleLlmProvider.from_settings(
            settings,
            http_post=http_post,
        )
    return MockLlmProvider()

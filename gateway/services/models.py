"""Model tier resolution — flash / pro / tts."""

from gateway.config import settings


def resolve_llm_model(tier: str | None) -> str:
    """Map official flash/pro tier to configured LLM model."""
    if tier == "pro":
        return settings.llm_model_pro or settings.llm_model
    if tier == "flash":
        return settings.llm_model_flash or settings.llm_model
    return settings.llm_model_flash or settings.llm_model


def resolve_tts_model(tier: str | None = None) -> str:
    if tier == "pro":
        return settings.tts_model_pro or settings.tts_model
    if tier == "flash":
        return settings.tts_model_flash or settings.tts_model
    return settings.tts_model_flash or settings.tts_model

"""Construct the configured structured-diagnosis provider chain."""

from chakravyuh.application.ports import StructuredDiagnostician
from chakravyuh.config import Settings
from chakravyuh.infrastructure.diagnosis.failover import FailoverStructuredDiagnostician
from chakravyuh.infrastructure.gemini.diagnostician import GeminiStructuredDiagnostician
from chakravyuh.infrastructure.openrouter.diagnostician import OpenRouterStructuredDiagnostician


def build_structured_diagnostician(settings: Settings) -> FailoverStructuredDiagnostician:
    """Build only the explicitly ordered providers; key presence never changes routing."""

    order = [settings.diagnosis_primary_provider]
    if settings.diagnosis_fallback_provider is not None:
        order.append(settings.diagnosis_fallback_provider)
    for provider in order:
        if provider == "openrouter" and settings.openrouter_api_key is None:
            msg = "CHAKRAVYUH_OPENROUTER_API_KEY is required by the diagnosis worker"
            raise RuntimeError(msg)
        if provider == "gemini" and settings.gemini_api_key is None:
            msg = "GEMINI_API_KEY is required by the diagnosis worker"
            raise RuntimeError(msg)
    providers: list[StructuredDiagnostician] = []
    for provider in order:
        if provider == "openrouter":
            providers.append(OpenRouterStructuredDiagnostician(settings))
        else:
            providers.append(GeminiStructuredDiagnostician(settings))
    return FailoverStructuredDiagnostician(providers)

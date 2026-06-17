"""Build the configured smart-layer from settings."""

from __future__ import annotations

from vad_proxy.config import Settings
from vad_proxy.llm.base import PassthroughSmartLayer, SmartLayer


def build_smart_layer(settings: Settings) -> SmartLayer:
    """Return a DeepSeek smart-layer, or passthrough if disabled / no key.

    The smart-layer is "core, on by default", but with no API key the service
    still runs end-to-end using acoustic endpointing and the raw transcript.
    """
    if not settings.llm_enabled or not settings.deepseek_api_key:
        return PassthroughSmartLayer()

    from vad_proxy.llm.deepseek import DeepSeekSmartLayer

    return DeepSeekSmartLayer(
        api_key=settings.deepseek_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )

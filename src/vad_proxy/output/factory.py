"""Build the configured output adapter from settings."""

from __future__ import annotations

from vad_proxy.config import Settings
from vad_proxy.output.base import OutputAdapter


def build_output(settings: Settings) -> OutputAdapter:
    kind = settings.output
    if kind == "stdout":
        from vad_proxy.output.stdout import StdoutOutputAdapter

        return StdoutOutputAdapter()
    if kind == "webhook":
        from vad_proxy.output.webhook import WebhookOutputAdapter

        return WebhookOutputAdapter(url=settings.webhook_url)
    if kind == "openai_chat":
        from vad_proxy.output.openai_chat import OpenAIChatOutputAdapter

        return OpenAIChatOutputAdapter(
            api_key=settings.output_api_key,
            base_url=settings.output_base_url,
            model=settings.output_model,
        )
    raise ValueError(f"Unknown output adapter: {kind}")

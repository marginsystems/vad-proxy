"""Environment-driven configuration for vad-proxy.

All settings are read from environment variables (prefix ``VAD_PROXY_``) or a
``.env`` file. Provider API keys use their conventional names
(``DEEPGRAM_API_KEY``, ``OPENAI_API_KEY``, ``DEEPSEEK_API_KEY``) so they line up
with the rest of the ecosystem.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SttBackend = Literal["mock", "deepgram", "openai"]
OutputKind = Literal["stdout", "webhook", "openai_chat"]


class Settings(BaseSettings):
    """Top-level runtime settings.

    Pydantic-settings resolves each field from, in order: an explicit kwarg,
    the matching environment variable, then the default below.
    """

    model_config = SettingsConfigDict(
        env_prefix="VAD_PROXY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- audio / VAD ---------------------------------------------------
    sample_rate: int = 16000
    vad_confidence: float = 0.5
    vad_start_secs: float = 0.2
    vad_stop_secs: float = 0.8
    # Optional noise gate on normalized RMS (0-1 of float audio). 0 disables it
    # and lets Silero confidence be the sole speech driver (recommended).
    vad_min_volume: float = 0.0
    max_utterance_secs: float = 30.0
    # Pre-roll kept before speech onset so the first phoneme is not clipped.
    pre_speech_secs: float = 0.3

    # --- STT -----------------------------------------------------------
    stt_backend: SttBackend = "mock"
    deepgram_api_key: str = Field(default="", validation_alias="DEEPGRAM_API_KEY")
    deepgram_model: str = "nova-2"
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    openai_stt_model: str = "whisper-1"
    language: str = "en"

    # --- LLM smart-layer ----------------------------------------------
    llm_enabled: bool = True
    deepseek_api_key: str = Field(default="", validation_alias="DEEPSEEK_API_KEY")
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"

    # --- output adapter -----------------------------------------------
    output: OutputKind = "stdout"
    webhook_url: str = ""
    output_base_url: str = "https://api.deepseek.com/v1"
    output_api_key: str = ""
    output_model: str = "deepseek-chat"

    # --- server --------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8080
    # Live interim transcripts: sub-chunk the in-progress utterance through STT
    # while speaking (no LLM). Off by default; existing path unchanged.
    interim_enabled: bool = False
    interim_secs: float = 2.0
    # Comma-separated browser app origins (full URLs with scheme).
    # localhost / 127.0.0.1 are always permitted for local dev.
    allowed_origins: str = ""

    # --- logging -------------------------------------------------------
    log_dir: str = "logs"
    log_level: str = "INFO"

    # --- personalization (roadmap) ------------------------------------
    log_utterances: bool = False
    data_dir: str = "data"

    @property
    def vad_chunk_size(self) -> int:
        """Silero requires 512 samples @ 16 kHz, 256 @ 8 kHz."""
        return 512 if self.sample_rate == 16000 else 256


def load_settings(**overrides) -> Settings:
    """Build a :class:`Settings` instance, applying optional overrides."""
    return Settings(**overrides)

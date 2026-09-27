"""Application settings, loaded from environment variables / the project `.env` file.

The `.env` file lives one level above this folder (conversational-agent/.env).
No credentials are ever hardcoded; missing keys only fail when the service
that needs them is actually used, so you can build up the pipeline phase by phase.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # an empty "GEMINI_LLM_MODEL=" falls back to the default
        extra="ignore",
    )

    # --- Provider credentials -------------------------------------------------
    deepgram_api_key: str = ""
    gemini_api_key: str = ""
    jev_api_key: str = ""
    mongodb_uri: str = ""

    # --- Models ---------------------------------------------------------------
    gemini_llm_model: str = "gemini-3.8-flash"
    gemini_thinking_level: str = "low"
    gemini_tts_model: str = "gemini-3.8-flash-lite-tts"
    gemini_tts_voice: str = "Kore"
    deepgram_stt_model: str = "flux-general-en"
    # Comma-separated words Deepgram should listen for (place names it may mishear).
    deepgram_keyterms: str = "University of Twente,Twente,Enschede,Hengelo"

    # --- Jev / TypeSafe ------------------------------------------------------------
    jev_api_url: str = "https://api.typesafe.ai/v1/systemone"
    jev_model: str = "jev-latest"
    jev_confidence_threshold: float = 0.70
    max_classification_clarifications: int = 1

    # --- MongoDB --------------------------------------------------------------
    mongodb_database: str = "emergency_voice_agent"
    mongodb_incident_collection: str = "incidents"

    # --- Web ------------------------------------------------------------------
    frontend_origin: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()

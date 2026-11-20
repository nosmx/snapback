"""Central configuration. Every sponsor integration resolves to `real` or `mock` here."""
from __future__ import annotations

from pathlib import Path
from typing import Dict

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
MOCK_DIR = ROOT / "mock"
DATA_DIR = ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")

    # LLM
    anthropic_api_key: str = ""
    llm_model: str = "claude-opus-5-5"
    llm_mode: str = "auto"

    # Senso
    senso_api_key: str = ""
    senso_base_url: str = ""
    senso_mode: str = "auto"

    # Superlinked SIE
    sie_api_key: str = ""
    sie_base_url: str = ""
    sie_image_embed_model: str = ""
    sie_text_embed_model: str = ""
    sie_extract_model: str = ""
    sie_rerank_model: str = ""
    image_embed_dim: int = 512
    text_embed_dim: int = 768
    sie_mode: str = "auto"

    # SingleStore
    singlestore_url: str = ""
    db_mode: str = "auto"

    # Persona
    persona_api_key: str = ""
    persona_environment_id: str = ""
    persona_template_id_mandate: str = ""
    persona_template_id_approval: str = ""
    persona_mode: str = "auto"
    persona_require_completed: bool = False   # True: execute only after the embedded flow completes

    # Amplitude / Statsig
    amplitude_api_key: str = ""
    amplitude_mode: str = "auto"
    statsig_server_secret: str = ""
    statsig_client_key: str = ""
    statsig_mode: str = "auto"

    # App
    backend_port: int = 8000
    merchant_port: int = 8001
    merchant_base_url: str = "http://localhost:8001"
    background_loop_seconds: int = 30
    photo_match_threshold: float = 0.80
    playwright_headless: bool = False
    refund_delay_seconds: int = 10
    await_refund_seconds: int = 20      # how long a flow waits for the refund before handing off to the loop
    playwright_slow_mo_ms: int = 150    # visible but quick browser actions on stage
    firedrill_api_key: str = ""


settings = Settings()


def _resolve(mode: str, *required: str) -> str:
    mode = (mode or "auto").lower()
    if mode in ("real", "mock"):
        return mode
    return "real" if all(r.strip() for r in required) else "mock"


def integration_modes() -> Dict[str, str]:
    s = settings
    return {
        "llm": _resolve(s.llm_mode, s.anthropic_api_key),
        "senso": _resolve(s.senso_mode, s.senso_api_key, s.senso_base_url),
        "sie": _resolve(s.sie_mode, s.sie_api_key, s.sie_base_url),
        "db": _resolve(s.db_mode, s.singlestore_url),
        # an inquiry can't be created without a template, so the key alone isn't "real"
        "persona": _resolve(s.persona_mode, s.persona_api_key, s.persona_template_id_mandate),
        "amplitude": _resolve(s.amplitude_mode, s.amplitude_api_key),
        "statsig": _resolve(s.statsig_mode, s.statsig_server_secret),
    }


def mode(name: str) -> str:
    return integration_modes()[name]

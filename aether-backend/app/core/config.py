"""Aether walkthrough backend configuration.

All settings come from environment variables / .env. API keys are SecretStr
and are only unwrapped inside provider adapters.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    aether_host: str = "127.0.0.1"
    aether_port: int = 8000
    aether_cors_origins: str = "http://localhost:3000,http://localhost:3001"
    aether_data_dir: str = "./data"

    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-2.0-flash"
    gemini_timeout_seconds: int = 60

    meshy_api_key: SecretStr = SecretStr("")
    meshy_base_url: str = "https://api.meshy.ai"
    meshy_timeout_seconds: int = 300

    provider_fallback_to_mock: bool = True

    # ── Blender (hybrid local pipeline) ─────────────────────────
    # Path to the blender executable (portable build). Empty = not configured;
    # render-lane jobs then fail fast with BLENDER_NOT_CONFIGURED.
    blender_path: str = ""
    blender_timeout_seconds: int = 1800

    # ── Job runner ──────────────────────────────────────────────
    # Two lanes: "ai" (network-bound agents) and "render" (owns the GPU).
    jobs_ai_workers: int = 2
    jobs_render_workers: int = 1
    jobs_retry_delay_seconds: float = 2.0
    jobs_default_max_attempts: int = 3

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.aether_cors_origins.split(",") if o.strip()]

    @property
    def data_dir(self) -> Path:
        path = Path(self.aether_data_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "allure.db"

    @property
    def projects_dir(self) -> Path:
        path = self.data_dir / "projects"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def repo_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def blender_scripts_dir(self) -> Path:
        return self.repo_root / "blender" / "scripts"

    @property
    def blender_configured(self) -> bool:
        return bool(self.blender_path) and Path(self.blender_path).exists()

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key.get_secret_value())

    @property
    def meshy_configured(self) -> bool:
        return bool(self.meshy_api_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""Gateway configuration — load from environment or gateway/.env."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

GATEWAY_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=GATEWAY_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OpenAI-compatible LLM (your third-party provider)
    llm_api_key: str = ""
    llm_base_url: str = "https://api.4022543.xyz/v1"
    llm_model: str = "gpt-4o-mini"

    # Gateway server
    host: str = "127.0.0.1"
    port: int = 8080
    public_url: str = "http://127.0.0.1:8080"

    # Local data directory
    data_dir: Path = GATEWAY_DIR / "data"

    # Stub balance for CLI
    default_balance: float = 999999.0


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
(settings.data_dir / "files").mkdir(exist_ok=True)
(settings.data_dir / "outputs").mkdir(exist_ok=True)

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
    llm_model: str = "gpt-4.1-mini"
    llm_model_flash: str = "gpt-4.1-mini"
    llm_model_pro: str = "gpt-4.1"

    # TTS — same API key / base URL as LLM (see https://api.4022543.xyz/pricing)
    tts_api_key: str = ""  # empty = use llm_api_key
    tts_model: str = "gpt-4o-mini-tts"
    tts_model_flash: str = "gpt-4o-mini-tts"
    tts_model_pro: str = "tts-1-hd"  # pro 档位：HD 音质，更接近官方 MiniMax 听感
    tts_provider: str = "openai"  # openai | edge
    tts_fallback_edge: bool = True

    # Commentary duration / chunking (align with official long-form behavior)
    writing_chunk_seconds: float = 240.0  # 4 min SRT windows
    target_duration_ratio: float = 0.22  # final video ~= 22% of source (typical recap)
    min_target_duration: float = 180.0  # at least 3 min for long sources
    max_target_duration: float = 900.0  # cap 15 min
    min_clip_seconds: float = 2.0
    max_clip_seconds: float = 18.0
    max_narration_clip_seconds: float = 24.0  # TTS 较长时允许略延长，避免过度加速
    narration_pad_seconds: float = 0.35  # 解说尾部留白
    max_audio_speed: float = 1.12  # 官方风格：轻微加速，不超过 12%
    chars_per_second: float = 4.2  # 中文解说语速估算
    segments_per_minute: float = 2.5  # narration segments density

    # Video compose — uniform output reduces concat stutter
    compose_fps: int = 30
    compose_crf: int = 20
    compose_preset: str = "medium"

    # CapCut / Jianying draft export (5.9 unencrypted)
    export_capcut_draft: bool = True
    capcut_width: int = 1920
    capcut_height: int = 1080

    # Burn narration/dialogue subtitles into final MP4
    burn_subtitles: bool = True
    subtitle_font: str = "Microsoft YaHei"
    subtitle_font_size: int = 24
    subtitle_margin_v: int = 48

    # Gateway server
    host: str = "127.0.0.1"
    port: int = 8080
    public_url: str = "http://127.0.0.1:8080"

    # Local data directory (project drive — keep temp/output here on Windows)
    data_dir: Path = GATEWAY_DIR / "data"
    temp_dir: Path = GATEWAY_DIR / "data" / "tmp"

    # Stub balance for CLI
    default_balance: float = 999999.0


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
(settings.data_dir / "files").mkdir(exist_ok=True)
(settings.data_dir / "outputs").mkdir(exist_ok=True)
settings.temp_dir.mkdir(parents=True, exist_ok=True)

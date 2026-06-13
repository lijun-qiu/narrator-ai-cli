"""TTS via OpenAI-compatible /audio/speech (gpt-4o-mini-tts), edge-tts fallback."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import httpx

from gateway.config import settings
from gateway.services.models import resolve_tts_model

logger = logging.getLogger(__name__)

# dubbing id / language -> OpenAI TTS voice (gpt-4o-mini-tts)
OPENAI_VOICE_MAP = {
    "MiniMaxVoiceId15553": "onyx",  # 解说男声
    "MiniMaxVoiceId15619": "onyx",  # 浑厚旁白
    "MiniMaxVoiceId15944": "echo",  # 知心哥哥
    "MiniMaxVoiceId16317": "nova",  # 温暖男声
    "mercury_yunxi_24k": "onyx",
    "mercury_yunye_24k@serious": "onyx",
    "mercury_guy_48k": "alloy",
    "default": "onyx",
}


def resolve_voice(dubbing_id: str, dubbing_type: str) -> str:
    if dubbing_id in OPENAI_VOICE_MAP:
        return OPENAI_VOICE_MAP[dubbing_id]
    if "英语" in dubbing_type or dubbing_type.lower() in ("english", "英语"):
        return "alloy"
    if "日语" in dubbing_type:
        return "nova"
    if "韩语" in dubbing_type:
        return "shimmer"
    return OPENAI_VOICE_MAP["default"]


async def _synthesize_openai(text: str, voice: str, out_path: Path, *, tier: str | None = None) -> Path:
    api_key = settings.tts_api_key or settings.llm_api_key
    if not api_key:
        raise RuntimeError("TTS API key not configured")

    url = f"{settings.llm_base_url.rstrip('/')}/audio/speech"
    model = resolve_tts_model(tier)
    payload = {
        "model": model,
        "input": text,
        "voice": voice,
        "response_format": "mp3",
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"TTS HTTP {resp.status_code}: {resp.text[:300]}")
        out_path.write_bytes(resp.content)
    return out_path


async def _synthesize_edge(text: str, voice: str, out_path: Path) -> Path:
    import edge_tts

    edge_voice = {
        "onyx": "zh-CN-YunxiNeural",
        "echo": "zh-CN-YunjianNeural",
        "nova": "zh-CN-XiaoxiaoNeural",
        "alloy": "en-US-GuyNeural",
        "shimmer": "ko-KR-SunHiNeural",
    }.get(voice, "zh-CN-YunxiNeural")
    communicate = edge_tts.Communicate(text, edge_voice)
    await communicate.save(str(out_path))
    return out_path


async def synthesize_to_file(
    text: str,
    voice: str,
    out_path: Path,
    *,
    tier: str | None = None,
) -> Path:
    if settings.tts_provider == "openai":
        try:
            return await _synthesize_openai(text, voice, out_path, tier=tier)
        except Exception as e:
            if not settings.tts_fallback_edge:
                raise
            logger.warning("OpenAI TTS failed (%s), falling back to edge-tts", e)
    return await _synthesize_edge(text, voice, out_path)


async def synthesize_for_dubbing(
    text: str,
    dubbing_id: str,
    dubbing_type: str,
    out_path: Path,
    *,
    tier: str | None = None,
) -> Path:
    voice = resolve_voice(dubbing_id, dubbing_type)
    return await synthesize_to_file(text, voice, out_path, tier=tier)


def get_audio_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)
        return float(out.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return 3.0

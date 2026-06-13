"""Text-to-speech via edge-tts (no extra API key)."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
from pathlib import Path

# dubbing id prefix hints -> edge-tts voice
VOICE_MAP = {
    "MiniMaxVoiceId15553": "zh-CN-YunxiNeural",
    "MiniMaxVoiceId15619": "zh-CN-YunjianNeural",
    "mercury_yunxi_24k": "zh-CN-YunxiNeural",
    "mercury_yunye_24k@serious": "zh-CN-YunyangNeural",
    "mercury_guy_48k": "en-US-GuyNeural",
    "default": "zh-CN-YunxiNeural",
}


def resolve_voice(dubbing_id: str, dubbing_type: str) -> str:
    if dubbing_id in VOICE_MAP:
        return VOICE_MAP[dubbing_id]
    if "英语" in dubbing_type or dubbing_type.lower() == "english":
        return "en-US-GuyNeural"
    if "日语" in dubbing_type:
        return "ja-JP-NanamiNeural"
    return VOICE_MAP["default"]


async def synthesize_to_file(text: str, voice: str, out_path: Path) -> Path:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(out_path))
    return out_path


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
        return max(3.0, len(text) * 0.15)


async def synthesize_segments(segments: list[dict], dubbing_id: str, dubbing_type: str, work_dir: Path) -> list[dict]:
    voice = resolve_voice(dubbing_id, dubbing_type)
    results = []
    for i, seg in enumerate(segments):
        if seg.get("type") not in ("解说", "narration", "解说词"):
            continue
        text = seg.get("text", "").strip()
        if not text:
            continue
        audio_path = work_dir / f"narration_{i:03d}.mp3"
        await synthesize_to_file(text, voice, audio_path)
        dur = get_audio_duration(audio_path)
        results.append({"index": i, "text": text, "audio_path": str(audio_path), "duration": dur})
    return results

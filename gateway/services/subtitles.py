"""Build output subtitles from clip timeline and burn into final video."""

from __future__ import annotations

import re
from pathlib import Path


def _fmt_srt_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _clean_subtitle_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    # SRT 单行不宜过长，简单按标点断行
    if len(text) > 36:
        parts = re.split(r"([，。！？；、])", text)
        lines: list[str] = []
        buf = ""
        for p in parts:
            buf += p
            if p in "，。！？；" and len(buf) >= 14:
                lines.append(buf.strip())
                buf = ""
        if buf.strip():
            lines.append(buf.strip())
        if lines:
            return "\n".join(lines[:2])
    return text


def build_timeline_srt(timeline: list[dict]) -> str:
    """Build SRT for composed output (cumulative timeline positions)."""
    cursor = 0.0
    blocks: list[str] = []
    idx = 1

    for clip in timeline:
        dur = float(clip.get("duration") or max(float(clip["video_end"]) - float(clip["video_start"]), 0.5))
        text = _clean_subtitle_text(clip.get("text") or "")
        if text:
            start = cursor
            end = cursor + dur
            blocks.append(
                f"{idx}\n{_fmt_srt_ts(start)} --> {_fmt_srt_ts(end)}\n{text}\n"
            )
            idx += 1
        cursor += dur

    return "\n".join(blocks)


def write_timeline_srt(timeline: list[dict], path: Path) -> Path:
    content = build_timeline_srt(timeline)
    path.write_text(content, encoding="utf-8")
    return path


def escape_subtitles_path(path: Path) -> str:
    """Escape path for ffmpeg subtitles filter (Windows-safe)."""
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:")

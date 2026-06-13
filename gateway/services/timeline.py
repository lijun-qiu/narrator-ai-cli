"""Build official-style clip timeline from writing + SRT."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from gateway.config import settings
from gateway.services.srt import SRTEntry


@dataclass
class TimelineClip:
    type: str  # narration | original
    text: str
    video_start: float
    video_end: float
    content_index: int


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text.strip().lower())


def estimate_narration_duration(text: str, *, min_clip: float | None = None, max_clip: float | None = None) -> float:
    """Estimate speaking duration from text length (Chinese ~4 chars/sec)."""
    chars = len(re.sub(r"\s+", "", text))
    min_c = min_clip if min_clip is not None else settings.min_clip_seconds
    max_c = max_clip if max_clip is not None else settings.max_clip_seconds
    est = chars / settings.chars_per_second + settings.narration_pad_seconds
    return max(min_c, min(max_c, est))


def match_srt_line(text: str, entries: list[SRTEntry], hint_start: float | None = None) -> SRTEntry | None:
    if not entries or not text.strip():
        return None
    target = _norm(text)
    best: SRTEntry | None = None
    best_score = 0.0
    for e in entries:
        if hint_start is not None and e.start < hint_start - 30:
            continue
        score = difflib.SequenceMatcher(None, target, _norm(e.text)).ratio()
        if score > best_score:
            best_score = score
            best = e
    return best if best_score >= 0.45 else None


def _expand_clip_end(start: float, min_dur: float, max_dur: float, video_duration: float) -> float:
    end = min(start + max_dur, video_duration)
    if end - start < min_dur:
        end = min(start + min_dur, video_duration)
    return end


def _cap_narration_window(start: float, end: float, text: str, video_duration: float, max_clip: float) -> float:
    """Prevent LLM from assigning 60s+ windows to a single narration line."""
    est = estimate_narration_duration(text, max_clip=max_clip)
    span = end - start
    if span > max(est, max_clip):
        return min(start + max(max_clip, est), video_duration)
    if span > max_clip:
        return min(start + max_clip, video_duration)
    return end


def build_timeline(
    content: list[dict],
    srt_entries: list[SRTEntry],
    *,
    target_mode: str,
    video_duration: float,
    min_clip: float,
    max_clip: float,
) -> list[TimelineClip]:
    clips: list[TimelineClip] = []
    cursor = 0.0

    for idx, seg in enumerate(content):
        seg_type = seg.get("type", "解说")
        text = (seg.get("text") or "").strip()
        if not text:
            continue

        is_original = seg_type in ("原声", "original", "原片")
        vs = seg.get("video_start", seg.get("srt_start"))
        ve = seg.get("video_end", seg.get("srt_end"))

        if vs is not None and ve is not None:
            start, end = float(vs), float(ve)
        else:
            matched = match_srt_line(text, srt_entries, cursor) if is_original else None
            if matched:
                start, end = matched.start, matched.end
            else:
                start = min(cursor, max(0.0, video_duration - min_clip))
                if is_original:
                    end = _expand_clip_end(start, min_clip, max_clip, video_duration)
                else:
                    end = min(start + estimate_narration_duration(text, min_clip=min_clip, max_clip=max_clip), video_duration)
            cursor = end

        start = max(0.0, min(start, video_duration - 0.5))
        end = max(start + 0.5, min(end, video_duration))

        if not is_original:
            end = _cap_narration_window(start, end, text, video_duration, max_clip)
        elif end - start > max_clip:
            end = start + max_clip

        if end - start < min_clip and target_mode != "1":
            end = min(start + min_clip, video_duration)

        clip_type = "original" if is_original and target_mode in ("2", "3") else "narration"
        if target_mode == "1":
            clip_type = "narration"

        clips.append(
            TimelineClip(
                type=clip_type,
                text=text,
                video_start=start,
                video_end=end,
                content_index=idx,
            )
        )
        cursor = end

    return clips


def align_timeline_after_tts(
    items: list[dict],
    *,
    video_duration: float,
    min_clip: float,
    max_clip: float,
    max_narration_clip: float,
    pad: float,
    max_audio_speed: float,
) -> None:
    """Official-style: narration clip length follows TTS audio, mild speedup only."""
    for item in items:
        clip_type = item.get("type", "narration")
        start = float(item["video_start"])
        start = max(0.0, min(start, video_duration - min_clip))

        if clip_type == "original":
            end = min(float(item["video_end"]), video_duration)
            if end - start > max_clip:
                end = start + max_clip
            if end - start < min_clip:
                end = min(start + min_clip, video_duration)
            item["video_start"] = start
            item["video_end"] = end
            item["duration"] = end - start
            item["audio_speed"] = 1.0
            continue

        audio_dur = float(item.get("audio_duration") or 0)
        if audio_dur <= 0:
            item["duration"] = float(item.get("duration") or max(item["video_end"] - start, min_clip))
            item["audio_speed"] = 1.0
            continue

        needed = audio_dur + pad
        # Prefer extending clip over speeding up (up to max_narration_clip)
        if needed / max_audio_speed <= max_narration_clip:
            clip_len = min(needed, max_narration_clip, video_duration - start)
            speed = min(max_audio_speed, needed / clip_len) if needed > clip_len else 1.0
        else:
            clip_len = min(max_narration_clip, video_duration - start)
            speed = min(max_audio_speed, audio_dur / max(clip_len - pad, 0.5))

        clip_len = max(min_clip, clip_len)
        end = min(start + clip_len, video_duration)
        item["video_start"] = start
        item["video_end"] = end
        item["duration"] = end - start
        item["audio_speed"] = round(speed, 4)

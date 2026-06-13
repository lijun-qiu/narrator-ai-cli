"""Multi-episode SRT / video loading for batch writing."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from gateway.services.media import ffprobe_duration
from gateway.services.srt import SRTEntry, parse_srt, srt_duration
from gateway.store import store


@dataclass
class EpisodeBundle:
    num: int
    srt_key: str
    video_key: str | None
    entries: list[SRTEntry] = field(default_factory=list)
    video_duration: float = 0.0


def _load_srt_bytes(srt_key: str) -> list[SRTEntry]:
    raw = store.read_file_bytes(srt_key)
    if not raw:
        return []
    return parse_srt(raw.decode("utf-8", errors="replace"))


def _video_duration_for_key(video_key: str | None) -> float:
    if not video_key:
        return 0.0
    rec = store.get_file(video_key)
    if rec and rec.path.exists():
        return ffprobe_duration(rec.path)
    return 0.0


def load_episodes(body: dict) -> list[EpisodeBundle]:
    """Load episodes from episodes_data or fall back to single SRT fields."""
    episodes_data = body.get("episodes_data") or []
    bundles: list[EpisodeBundle] = []

    if episodes_data:
        for ep in sorted(episodes_data, key=lambda x: int(x.get("num") or 0)):
            srt_key = ep.get("srt_oss_key") or ep.get("srt_path") or ""
            video_key = ep.get("video_oss_key") or ep.get("negative_oss_key")
            if not srt_key:
                continue
            entries = _load_srt_bytes(srt_key)
            dur = _video_duration_for_key(video_key) or srt_duration(entries)
            bundles.append(
                EpisodeBundle(
                    num=int(ep.get("num") or len(bundles) + 1),
                    srt_key=srt_key,
                    video_key=video_key,
                    entries=entries,
                    video_duration=dur,
                )
            )
        return bundles

    srt_key = body.get("video_srt_path") or body.get("native_srt") or ""
    video_key = body.get("native_video") or body.get("video_path")
    if not srt_key:
        return []
    entries = _load_srt_bytes(srt_key)
    dur = _video_duration_for_key(video_key) or srt_duration(entries)
    return [
        EpisodeBundle(
            num=1,
            srt_key=srt_key,
            video_key=video_key,
            entries=entries,
            video_duration=dur,
        )
    ]


def episode_video_path(episode: EpisodeBundle) -> Path | None:
    if not episode.video_key:
        return None
    rec = store.get_file(episode.video_key)
    if rec and rec.path.exists():
        return rec.path
    return None


def episode_map(body: dict) -> dict[int, EpisodeBundle]:
    return {ep.num: ep for ep in load_episodes(body)}


def resolve_video_id(body: dict, episode_num: int | None) -> str | None:
    eps = load_episodes(body)
    if not eps:
        return body.get("native_video") or body.get("video_path")
    num = episode_num or 1
    for ep in eps:
        if ep.num == num and ep.video_key:
            return ep.video_key
    return eps[0].video_key

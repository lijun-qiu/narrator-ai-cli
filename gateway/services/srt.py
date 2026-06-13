"""Parse SRT subtitle files."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class SRTEntry:
    index: int
    start: float
    end: float
    text: str


def _ts_to_seconds(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_srt(content: str) -> list[SRTEntry]:
    content = content.replace("\r\n", "\n").strip()
    blocks = re.split(r"\n\s*\n", content)
    entries: list[SRTEntry] = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        try:
            idx = int(lines[0].strip())
        except ValueError:
            continue
        timing = lines[1]
        m = re.match(
            r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})",
            timing.strip(),
        )
        if not m:
            continue
        text = " ".join(lines[2:]).strip()
        entries.append(
            SRTEntry(
                index=idx,
                start=_ts_to_seconds(m.group(1)),
                end=_ts_to_seconds(m.group(2)),
                text=text,
            )
        )
    return entries


def srt_summary(entries: list[SRTEntry], max_chars: int = 12000) -> str:
    lines = []
    total = 0
    for e in entries:
        line = f"[{e.start:.1f}-{e.end:.1f}s] {e.text}"
        if total + len(line) > max_chars:
            lines.append("...(truncated)")
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


def srt_duration(entries: list[SRTEntry]) -> float:
    if not entries:
        return 0.0
    return max(e.end for e in entries)


def chunk_srt_entries(entries: list[SRTEntry], chunk_seconds: float) -> list[tuple[float, float, list[SRTEntry]]]:
    """Split SRT into (start, end, entries) windows."""
    if not entries:
        return []
    total = srt_duration(entries)
    if total <= chunk_seconds:
        return [(entries[0].start, entries[-1].end, entries)]

    chunks: list[tuple[float, float, list[SRTEntry]]] = []
    window_start = entries[0].start
    while window_start < total:
        window_end = min(window_start + chunk_seconds, total)
        window_entries = [e for e in entries if e.start < window_end and e.end > window_start]
        if window_entries:
            chunks.append((window_start, window_end, window_entries))
        window_start = window_end
        if window_end >= total:
            break
    return chunks


def chunk_srt_text(entries: list[SRTEntry], max_chars: int = 6000) -> str:
    lines = []
    total = 0
    for e in entries:
        line = f"[{e.start:.1f}-{e.end:.1f}s] {e.text}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


_COMMON_WORDS = frozenset(
    "我们你们他们这是那个什么一个不是可以已经因为所以但是然后如果虽然"
    "自己这样怎么什么所有这种时候现在知道看到听到说话告诉开始结束"
    "警察局长队长同志公司国家中国汉州赵家".split()
)


def extract_name_hints(entries: list[SRTEntry], limit: int = 20) -> list[str]:
    """Extract recurring 2-4 char tokens from SRT as character/place name hints."""
    if not entries:
        return []
    counts: dict[str, int] = {}
    for e in entries:
        for token in re.findall(r"[\u4e00-\u9fff]{2,4}", e.text):
            if token in _COMMON_WORDS:
                continue
            counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda x: (-x[1], -len(x[0])))
    return [w for w, c in ranked if c >= 2][:limit]

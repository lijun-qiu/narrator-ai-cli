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

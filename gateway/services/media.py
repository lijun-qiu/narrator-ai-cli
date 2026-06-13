"""Media probing helpers (ffprobe)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def ffprobe_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)
        data = json.loads(out)
        return float(data["format"]["duration"])
    except (subprocess.CalledProcessError, FileNotFoundError, KeyError, ValueError, json.JSONDecodeError):
        return 0.0


def ffprobe_video_size(path: Path) -> tuple[int, int]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        str(path),
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)
        data = json.loads(out)
        streams = data.get("streams") or []
        if streams:
            return int(streams[0].get("width") or 0), int(streams[0].get("height") or 0)
    except (subprocess.CalledProcessError, FileNotFoundError, KeyError, ValueError, json.JSONDecodeError):
        pass
    return 0, 0

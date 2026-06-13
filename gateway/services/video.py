"""FFmpeg-based video composition."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

from gateway.config import settings


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr[-500:]}")


def concat_audio_segments(segment_paths: list[Path], out_path: Path) -> Path:
    if not segment_paths:
        raise RuntimeError("No narration audio segments")
    if len(segment_paths) == 1:
        segment_paths[0].replace(out_path)
        return out_path

    list_file = out_path.with_suffix(".txt")
    lines = [f"file '{p.resolve().as_posix()}'" for p in segment_paths]
    list_file.write_text("\n".join(lines), encoding="utf-8")
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(out_path),
        ]
    )
    list_file.unlink(missing_ok=True)
    return out_path


def mix_video_with_narration(
    video_path: Path,
    narration_path: Path,
    bgm_path: Path | None,
    out_path: Path,
) -> Path:
    """Replace/mix audio track: narration dominant, optional BGM at low volume."""
    if bgm_path and bgm_path.exists():
        filter_complex = (
            "[1:a]volume=1.0[narr];[2:a]volume=0.15[bgm];"
            "[narr][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(narration_path),
            "-i",
            str(bgm_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(out_path),
        ]
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(narration_path),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(out_path),
        ]
    _run(cmd)
    return out_path


def compose_output_path(suffix: str = ".mp4") -> Path:
    out_id = uuid.uuid4().hex
    return settings.data_dir / "outputs" / f"{out_id}{suffix}"


def ffmpeg_available() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

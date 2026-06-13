"""FFmpeg-based timeline video composition (official-style clip editing)."""

from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path

from gateway.config import settings


def _move_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() == dst.resolve():
        return
    shutil.move(str(src), str(dst))


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr[-800:]}")


def _fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _video_encode_args() -> list[str]:
    return [
        "-c:v",
        "libx264",
        "-preset",
        settings.compose_preset,
        "-crf",
        str(settings.compose_crf),
        "-r",
        str(settings.compose_fps),
        "-vsync",
        "cfr",
        "-pix_fmt",
        "yuv420p",
    ]


def _audio_encode_args() -> list[str]:
    return ["-c:a", "aac", "-ar", "44100", "-b:a", "192k"]


def adjust_audio_duration(
    audio_path: Path,
    target_duration: float,
    out_path: Path,
    *,
    max_speed: float | None = None,
) -> Path:
    """Fit narration to clip — prefer padding; mild speedup only (official-style)."""
    from gateway.services.tts import get_audio_duration

    cap = max_speed if max_speed is not None else settings.max_audio_speed
    dur = get_audio_duration(audio_path)
    if dur <= 0 or abs(dur - target_duration) < 0.15:
        if audio_path != out_path:
            out_path.write_bytes(audio_path.read_bytes())
        return out_path

    if dur > target_duration:
        speed = min(dur / max(target_duration, 0.5), cap)
        if speed <= 1.02:
            # Negligible difference — pad/trim instead of warping pitch
            _run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(audio_path),
                    "-af",
                    f"apad=pad_dur={max(0, target_duration - dur):.3f}",
                    "-t",
                    str(target_duration),
                    str(out_path),
                ]
            )
        else:
            _run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(audio_path),
                    "-filter:a",
                    f"atempo={speed:.4f}",
                    "-t",
                    str(target_duration),
                    str(out_path),
                ]
            )
    else:
        _run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(audio_path),
                "-af",
                f"apad=pad_dur={target_duration - dur:.3f}",
                "-t",
                str(target_duration),
                str(out_path),
            ]
        )
    return out_path


def render_clip(
    video_path: Path,
    *,
    start: float,
    end: float,
    clip_type: str,
    narration_audio: Path | None,
    out_path: Path,
    audio_speed: float = 1.0,
) -> Path:
    duration = max(0.5, end - start)
    ss = _fmt_ts(start)
    venc = _video_encode_args()
    aenc = _audio_encode_args()

    if clip_type == "original":
        # Accurate seek: -ss after -i reduces keyframe stutter
        _run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-ss",
                ss,
                "-t",
                f"{duration:.3f}",
                "-map",
                "0:v",
                "-map",
                "0:a?",
                *venc,
                *aenc,
                str(out_path),
            ]
        )
        return out_path

    if not narration_audio or not narration_audio.exists():
        raise RuntimeError("Narration audio missing for clip")

    adjusted = out_path.with_suffix(".adj.mp3")
    adjust_audio_duration(narration_audio, duration, adjusted, max_speed=audio_speed)

    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-ss",
            ss,
            "-i",
            str(adjusted),
            "-t",
            f"{duration:.3f}",
            "-map",
            "0:v",
            "-map",
            "1:a",
            *venc,
            *aenc,
            "-shortest",
            str(out_path),
        ]
    )
    adjusted.unlink(missing_ok=True)
    return out_path


def concat_video_clips(clip_paths: list[Path], out_path: Path) -> Path:
    if not clip_paths:
        raise RuntimeError("No clips to concat")
    if len(clip_paths) == 1:
        _move_file(clip_paths[0], out_path)
        return out_path

    list_file = out_path.with_suffix(".txt")
    lines = [f"file '{p.resolve().as_posix()}'" for p in clip_paths]
    list_file.write_text("\n".join(lines), encoding="utf-8")
    # Re-encode on concat for uniform fps/timestamps (avoids copy-mode stutter)
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
            *_video_encode_args(),
            *_audio_encode_args(),
            str(out_path),
        ]
    )
    list_file.unlink(missing_ok=True)
    return out_path


def mix_bgm(video_path: Path, bgm_path: Path | None, out_path: Path, bgm_volume: float = 0.12) -> Path:
    if not bgm_path or not bgm_path.exists():
        _move_file(video_path, out_path)
        return out_path

    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(bgm_path),
            "-filter_complex",
            f"[1:a]aloop=loop=-1:size=2e+09,volume={bgm_volume}[bgm];"
            f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map",
            "0:v",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            *_audio_encode_args(),
            str(out_path),
        ]
    )
    return out_path


def burn_subtitles(
    video_path: Path,
    srt_path: Path,
    out_path: Path,
    *,
    font_name: str | None = None,
    font_size: int | None = None,
    margin_v: int | None = None,
) -> Path:
    """Hard-burn SRT subtitles onto video (requires ffmpeg libass)."""
    from gateway.services.subtitles import escape_subtitles_path

    font = font_name or settings.subtitle_font
    size = font_size if font_size is not None else settings.subtitle_font_size
    margin = margin_v if margin_v is not None else settings.subtitle_margin_v
    srt_esc = escape_subtitles_path(srt_path)
    style = (
        f"FontName={font},FontSize={size},"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        "BorderStyle=1,Outline=2,Shadow=1,"
        f"MarginV={margin},Alignment=2"
    )
    vf = f"subtitles='{srt_esc}':force_style='{style}'"
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            vf,
            *_video_encode_args(),
            "-c:a",
            "copy",
            str(out_path),
        ]
    )
    return out_path


def compose_from_timeline(
    video_path: Path,
    timeline_clips: list[dict],
    bgm_path: Path | None,
    work_dir: Path,
    out_path: Path,
) -> Path:
    """Render each timeline clip, concat, mix BGM — official-style pipeline."""
    rendered: list[Path] = []
    for i, clip in enumerate(timeline_clips):
        clip_out = work_dir / f"clip_{i:04d}.mp4"
        narr_path = None
        if clip.get("audio_path"):
            narr_path = Path(clip["audio_path"])

        src_video = video_path
        if clip.get("video_path"):
            src_video = Path(clip["video_path"])
        elif clip.get("video_file_id"):
            from gateway.store import store

            frec = store.get_file(clip["video_file_id"])
            if frec and frec.path.exists():
                src_video = frec.path

        render_clip(
            src_video,
            start=float(clip["video_start"]),
            end=float(clip["video_end"]),
            clip_type=clip.get("type", "narration"),
            narration_audio=narr_path,
            out_path=clip_out,
            audio_speed=float(clip.get("audio_speed") or 1.0),
        )
        rendered.append(clip_out)

    merged = work_dir / "merged.mp4"
    concat_video_clips(rendered, merged)

    with_bgm = work_dir / "with_bgm.mp4"
    mix_bgm(merged, bgm_path, with_bgm)

    if settings.burn_subtitles and timeline_clips:
        from gateway.services.subtitles import write_timeline_srt

        srt_path = work_dir / "output.srt"
        write_timeline_srt(timeline_clips, srt_path)
        if srt_path.read_text(encoding="utf-8").strip():
            burn_subtitles(with_bgm, srt_path, out_path)
        else:
            _move_file(with_bgm, out_path)
    else:
        _move_file(with_bgm, out_path)
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

"""Export clip timeline as Jianying / CapCut draft (5.9 unencrypted format)."""

from __future__ import annotations

import copy
import io
import json
import logging
import shutil
import uuid
import zipfile
from pathlib import Path

from gateway.config import settings
from gateway.services.media import ffprobe_video_size
from gateway.services.tts import get_audio_duration

logger = logging.getLogger(__name__)

SEC = 1_000_000
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "data" / "capcut"


def _us(seconds: float) -> int:
    return int(round(max(0.0, seconds) * SEC))


def _new_id() -> str:
    return uuid.uuid4().hex


def _timerange(start_us: int, duration_us: int) -> dict:
    return {"duration": max(1, duration_us), "start": max(0, start_us)}


def _clip_settings() -> dict:
    return {
        "alpha": 1.0,
        "flip": {"horizontal": False, "vertical": False},
        "rotation": 0.0,
        "scale": {"x": 1.0, "y": 1.0},
        "transform": {"x": 0.0, "y": 0.0},
    }


def _base_segment(material_id: str, target_start: int, target_dur: int) -> dict:
    return {
        "enable_adjust": True,
        "enable_color_correct_adjust": False,
        "enable_color_curves": True,
        "enable_color_match_adjust": False,
        "enable_color_wheels": True,
        "enable_lut": True,
        "enable_smart_color_adjust": False,
        "last_nonzero_volume": 1.0,
        "reverse": False,
        "track_attribute": 0,
        "track_render_index": 0,
        "visible": True,
        "id": _new_id(),
        "material_id": material_id,
        "target_timerange": _timerange(target_start, target_dur),
        "common_keyframes": [],
        "keyframe_refs": [],
    }


def _speed_entry(speed: float) -> tuple[str, dict]:
    sid = _new_id()
    return sid, {"curve_speed": None, "id": sid, "mode": 0, "speed": speed, "type": "speed"}


def _video_material(path: str, *, width: int, height: int, duration_us: int, name: str) -> dict:
    mid = _new_id()
    return {
        "audio_fade": None,
        "category_id": "",
        "category_name": "local",
        "check_flag": 63487,
        "crop": {
            "upper_left_x": 0.0,
            "upper_left_y": 0.0,
            "upper_right_x": 1.0,
            "upper_right_y": 0.0,
            "lower_left_x": 0.0,
            "lower_left_y": 1.0,
            "lower_right_x": 1.0,
            "lower_right_y": 1.0,
        },
        "crop_ratio": "free",
        "crop_scale": 1.0,
        "duration": duration_us,
        "height": height,
        "id": mid,
        "local_material_id": "",
        "material_id": mid,
        "material_name": name,
        "media_path": "",
        "path": path,
        "type": "video",
        "width": width,
    }


def _audio_material(path: str, *, duration_us: int, name: str) -> dict:
    mid = _new_id()
    return {
        "app_id": 0,
        "category_id": "",
        "category_name": "local",
        "check_flag": 3,
        "copyright_limit_type": "none",
        "duration": duration_us,
        "effect_id": "",
        "formula_id": "",
        "id": mid,
        "local_material_id": mid,
        "music_id": mid,
        "name": name,
        "path": path,
        "source_platform": 0,
        "type": "extract_music",
        "wave_points": [],
    }


def _video_segment(
    material_id: str,
    *,
    source_start: int,
    source_dur: int,
    target_start: int,
    target_dur: int,
    speed: float,
    volume: float,
    speed_id: str,
) -> dict:
    seg = _base_segment(material_id, target_start, target_dur)
    seg.update(
        {
            "source_timerange": _timerange(source_start, source_dur),
            "speed": speed,
            "volume": volume,
            "extra_material_refs": [speed_id],
            "is_tone_modify": False,
            "clip": _clip_settings(),
            "uniform_scale": True,
            "hdr_settings": {"intensity": 1.0, "mode": 1, "nits": 1000},
        }
    )
    return seg


def _audio_segment(
    material_id: str,
    *,
    source_start: int,
    source_dur: int,
    target_start: int,
    target_dur: int,
    speed: float,
    volume: float,
    speed_id: str,
) -> dict:
    seg = _base_segment(material_id, target_start, target_dur)
    seg.update(
        {
            "source_timerange": _timerange(source_start, source_dur),
            "speed": speed,
            "volume": volume,
            "extra_material_refs": [speed_id],
            "is_tone_modify": False,
        }
    )
    return seg


def _text_material(text: str) -> dict:
    mid = _new_id()
    content = json.dumps(
        {
            "text": text,
            "styles": [
                {
                    "fill": {"content": {"solid": {"color": [1.0, 1.0, 1.0]}}},
                    "range": [0, len(text)],
                    "size": 8.0,
                }
            ],
        },
        ensure_ascii=False,
    )
    return {
        "id": mid,
        "content": content,
        "type": "text",
        "recognize_text": text,
        "recognize_type": 0,
        "subtitle_keywords": None,
        "subtitle_template_original_fontsize": 0.0,
        "text_to_audio_ids": [],
        "tts_auto_update": False,
        "words": {"end_time": [], "start_time": [], "text": []},
    }


def _text_segment(material_id: str, target_start: int, target_dur: int) -> dict:
    seg = _base_segment(material_id, target_start, target_dur)
    seg.update(
        {
            "source_timerange": None,
            "speed": 1.0,
            "volume": 1.0,
            "extra_material_refs": [],
            "is_tone_modify": False,
            "clip": _clip_settings(),
            "uniform_scale": True,
        }
    )
    return seg


def _load_template() -> dict:
    path = _TEMPLATE_DIR / "draft_content_template.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _load_meta_template() -> dict:
    path = _TEMPLATE_DIR / "draft_meta_info.json"
    return json.loads(path.read_text(encoding="utf-8"))


def build_draft_content(
    *,
    title: str,
    timeline: list[dict],
    video_materials: dict[str, dict],
    audio_materials: dict[str, dict],
    width: int,
    height: int,
    fps: int = 30,
) -> dict:
    """Build draft_content.json from resolved timeline + material dicts."""
    draft = _load_template()
    draft["name"] = title
    draft["fps"] = float(fps)
    draft["canvas_config"] = {"width": width, "height": height, "ratio": "16:9"}
    draft["id"] = str(uuid.uuid4()).upper()

    materials = draft["materials"]
    materials["videos"] = list(video_materials.values())
    materials["audios"] = list(audio_materials.values())
    materials["speeds"] = []
    materials["texts"] = []

    video_segments: list[dict] = []
    audio_segments: list[dict] = []
    text_segments: list[dict] = []

    output_cursor = 0

    for i, clip in enumerate(timeline):
        clip_type = clip.get("type", "narration")
        target_dur = _us(float(clip.get("duration") or (clip["video_end"] - clip["video_start"])))
        source_start = _us(float(clip["video_start"]))
        source_dur = _us(float(clip["video_end"]) - float(clip["video_start"]))
        video_key = clip.get("capcut_video_key") or "main"
        video_mat = video_materials.get(video_key)
        if not video_mat:
            continue

        vid_speed = float(clip.get("video_speed") or 1.0)
        vid_speed_id, vid_speed_obj = _speed_entry(vid_speed)
        materials["speeds"].append(vid_speed_obj)

        if clip_type == "original":
            vol = 1.0
        else:
            vol = 0.0

        video_segments.append(
            _video_segment(
                video_mat["id"],
                source_start=source_start,
                source_dur=source_dur,
                target_start=output_cursor,
                target_dur=target_dur,
                speed=vid_speed,
                volume=vol,
                speed_id=vid_speed_id,
            )
        )

        if clip_type != "original" and clip.get("capcut_audio_path"):
            audio_path = clip["capcut_audio_path"]
            audio_dur = _us(get_audio_duration(Path(audio_path)))
            aud_mat = audio_materials.get(f"narr_{i}")
            if aud_mat:
                aud_speed = float(clip.get("audio_speed") or 1.0)
                aud_speed_id, aud_speed_obj = _speed_entry(aud_speed)
                materials["speeds"].append(aud_speed_obj)
                audio_segments.append(
                    _audio_segment(
                        aud_mat["id"],
                        source_start=0,
                        source_dur=audio_dur,
                        target_start=output_cursor,
                        target_dur=target_dur,
                        speed=aud_speed,
                        volume=1.0,
                        speed_id=aud_speed_id,
                    )
                )

            text = (clip.get("text") or "").strip()
            if text:
                txt_mat = _text_material(text)
                materials["texts"].append(txt_mat)
                text_segments.append(_text_segment(txt_mat["id"], output_cursor, target_dur))

        output_cursor += target_dur

    draft["duration"] = output_cursor
    draft["tracks"] = [
        {
            "attribute": 0,
            "flag": 0,
            "id": _new_id(),
            "is_default_name": True,
            "name": "",
            "segments": video_segments,
            "type": "video",
        },
        {
            "attribute": 0,
            "flag": 0,
            "id": _new_id(),
            "is_default_name": True,
            "name": "",
            "segments": audio_segments,
            "type": "audio",
        },
        {
            "attribute": 0,
            "flag": 0,
            "id": _new_id(),
            "is_default_name": True,
            "name": "",
            "segments": text_segments,
            "type": "text",
        },
    ]
    return draft


def build_capcut_zip(
    *,
    title: str,
    timeline: list[dict],
    video_paths: dict[str, Path],
    work_dir: Path,
) -> bytes:
    """Package draft + copied media into a zip for manual import into Jianying 5.9 / CapCut."""
    assets_dir = work_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    # Copy source videos (dedupe by key)
    copied_videos: dict[str, str] = {}
    for key, src in video_paths.items():
        if not src.exists():
            continue
        ext = src.suffix or ".mp4"
        dst_name = f"video_{key}{ext}"
        dst = assets_dir / dst_name
        shutil.copy2(src, dst)
        copied_videos[key] = dst_name

    # Enrich timeline with capcut paths
    enriched: list[dict] = copy.deepcopy(timeline)
    video_materials: dict[str, dict] = {}
    audio_materials: dict[str, dict] = {}

    width, height = settings.capcut_width, settings.capcut_height
    for key, rel in copied_videos.items():
        src = video_paths[key]
        w, h = ffprobe_video_size(src)
        if w and h:
            width, height = w, h
        dur_us = _us(float(timeline[0].get("video_duration") or 0)) if timeline else 3_600_000_000
        video_materials[key] = _video_material(
            rel,
            width=width,
            height=height,
            duration_us=max(dur_us, 3_600_000_000),
            name=src.name,
        )

    for i, clip in enumerate(enriched):
        vkey = clip.get("capcut_video_key") or "main"
        if vkey not in video_materials and copied_videos:
            vkey = next(iter(copied_videos))
            clip["capcut_video_key"] = vkey

        audio_path = clip.get("audio_path")
        if audio_path and Path(audio_path).exists():
            dst = assets_dir / f"narr_{i:04d}.mp3"
            shutil.copy2(audio_path, dst)
            clip["capcut_audio_path"] = str(dst)
            aud_dur = _us(get_audio_duration(dst))
            audio_materials[f"narr_{i}"] = _audio_material(
                f"assets/narr_{i:04d}.mp3",
                duration_us=aud_dur,
                name=f"narr_{i:04d}.mp3",
            )

    # Use relative paths in materials for zip portability
    for key, mat in video_materials.items():
        mat["path"] = f"assets/{copied_videos[key]}"

    draft = build_draft_content(
        title=title,
        timeline=enriched,
        video_materials=video_materials,
        audio_materials=audio_materials,
        width=width,
        height=height,
        fps=settings.compose_fps,
    )

    meta = _load_meta_template()
    meta["draft_id"] = str(uuid.uuid4()).upper()
    meta["draft_name"] = title
    meta["tm_duration"] = draft["duration"]

    readme = (
        "Narrator Gateway — 剪映草稿导出\n"
        "================================\n\n"
        "适用：剪映 5.9 及以下（未加密 draft_content.json）或 CapCut 国际版。\n"
        "剪映 6.0+ 国内版会加密草稿，无法直接导入。\n\n"
        "安装步骤：\n"
        "1. 在剪映草稿目录新建文件夹，例如「narrator_export」\n"
        "   默认路径：%USERPROFILE%\\AppData\\Local\\JianyingPro\\User Data\\Projects\\com.lveditor.draft\\\n"
        "2. 解压本 zip 到该文件夹\n"
        "3. 重启剪映，在草稿列表中打开\n"
        "4. 若素材丢失，在剪映中重新链接 assets/ 下的视频与音频\n\n"
        "轨道说明：\n"
        "- 视频轨：按时间轴拼接的原片片段\n"
        "- 音频轨：解说 TTS\n"
        "- 文本轨：解说字幕（可微调样式）\n"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("draft_content.json", json.dumps(draft, ensure_ascii=False, indent=2))
        zf.writestr("draft_meta_info.json", json.dumps(meta, ensure_ascii=False, indent=2))
        zf.writestr("README.txt", readme)
        for rel in copied_videos.values():
            zf.write(assets_dir / rel, f"assets/{rel}")
        for i in range(len(enriched)):
            mp3 = assets_dir / f"narr_{i:04d}.mp3"
            if mp3.exists():
                zf.write(mp3, f"assets/narr_{i:04d}.mp3")

    logger.info("CapCut draft zip: %d clips, duration %.1fs", len(enriched), draft["duration"] / SEC)
    return buf.getvalue()

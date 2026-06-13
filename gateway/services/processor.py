"""Background task processors for each workflow step."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from pathlib import Path

from gateway.services.srt import parse_srt
from gateway.services.tts import synthesize_segments
from gateway.services.video import compose_output_path, concat_audio_segments, ffmpeg_available, mix_video_with_narration
from gateway.services.writing import generate_fast_writing, generate_standard_writing
from gateway.store import store

logger = logging.getLogger(__name__)


def _file_entry(file_id: str, file_name: str, suffix: str) -> dict:
    return {"file_id": file_id, "file_path": file_name, "suffix": suffix}


def _load_srt_from_body(body: dict) -> list:
    episodes = body.get("episodes_data") or []
    srt_key = None
    if episodes:
        srt_key = episodes[0].get("srt_oss_key")
    if not srt_key:
        srt_key = body.get("video_srt_path") or body.get("native_srt")
    if not srt_key:
        return []
    raw = store.read_file_bytes(srt_key)
    if not raw:
        return []
    return parse_srt(raw.decode("utf-8", errors="replace"))


def _video_from_body(body: dict) -> str | None:
    episodes = body.get("episodes_data") or []
    if episodes:
        return episodes[0].get("video_oss_key")
    return body.get("native_video") or body.get("video_path")


async def process_fast_writing(task_id: str) -> None:
    rec = store.get_task(task_id)
    if not rec:
        return
    store.update_task(task_id, status=1)
    body = rec.body
    try:
        srt_entries = _load_srt_from_body(body)
        movie_json = body.get("confirmed_movie_json")
        if isinstance(movie_json, str):
            movie_json = json.loads(movie_json)

        writing = await generate_fast_writing(
            playlet_name=body.get("playlet_name", "未命名"),
            target_mode=str(body.get("target_mode", "1")),
            movie_json=movie_json,
            srt_entries=srt_entries or None,
            language=body.get("language", "Chinese (中文)"),
            style_hint=body.get("learning_model_id", ""),
        )
        payload = json.dumps(writing, ensure_ascii=False, indent=2).encode("utf-8")
        frec = store.save_output(f"writing_{task_id[:8]}.json", payload)
        order = f"fast_writing_{task_id[:12]}"
        store.update_task(
            task_id,
            status=2,
            task_order_num=order,
            files=[_file_entry(frec.file_id, frec.file_name, ".json")],
            results={"file_ids": [frec.file_id], "writing": writing},
            consumed_points=5,
        )
    except Exception as e:
        logger.exception("fast_writing failed")
        store.update_task(task_id, status=3, error_message=str(e))


async def process_generate_writing(task_id: str) -> None:
    rec = store.get_task(task_id)
    if not rec:
        return
    store.update_task(task_id, status=1)
    body = rec.body
    try:
        srt_entries = _load_srt_from_body(body)
        writing = await generate_standard_writing(
            playlet_name=body.get("playlet_name", "未命名"),
            srt_entries=srt_entries or None,
            target_platform=body.get("target_platform", "douyin"),
        )
        payload = json.dumps(writing, ensure_ascii=False, indent=2).encode("utf-8")
        frec = store.save_output(f"writing_{task_id[:8]}.json", payload)
        order = f"generate_writing_{task_id[:12]}"
        store.update_task(
            task_id,
            status=2,
            task_order_num=order,
            files=[_file_entry(frec.file_id, frec.file_name, ".json")],
            results={"file_ids": [frec.file_id], "writing": writing},
            consumed_points=10,
        )
    except Exception as e:
        logger.exception("generate_writing failed")
        store.update_task(task_id, status=3, error_message=str(e))


async def process_clip_data(task_id: str, *, fast: bool) -> None:
    rec = store.get_task(task_id)
    if not rec:
        return
    store.update_task(task_id, status=1)
    body = rec.body
    try:
        # Resolve upstream writing
        if fast:
            upstream = store.get_task(body.get("task_id", ""))
            file_id = body.get("file_id")
        else:
            upstream = store.get_task_by_order(body.get("order_num", ""))
            file_id = (upstream.results.get("file_ids") or [None])[0] if upstream else None

        if not upstream or upstream.status != 2:
            raise RuntimeError("Upstream writing task not ready")
        writing_raw = store.read_file_bytes(file_id or upstream.files[0]["file_id"])
        writing = json.loads(writing_raw.decode("utf-8"))
        segments = writing.get("content", [])

        dubbing = body.get("dubbing", "")
        dubbing_type = body.get("dubbing_type", "普通话")

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            audio_segs = await synthesize_segments(segments, dubbing, dubbing_type, work)
            if not audio_segs:
                raise RuntimeError("No narration segments for TTS")

            narration_mp3 = work / "full_narration.mp3"
            concat_audio_segments([Path(s["audio_path"]) for s in audio_segs], narration_mp3)

            clip_data = {
                "segments": segments,
                "audio_segments": audio_segs,
                "bgm": body.get("bgm"),
                "dubbing": dubbing,
                "dubbing_type": dubbing_type,
                "video_file_id": _video_from_body(body if fast else upstream.body),
                "narration_audio": str(narration_mp3),
            }

            # Persist narration audio as file
            narr_bytes = narration_mp3.read_bytes()
            audio_rec = store.save_output(f"narration_{task_id[:8]}.mp3", narr_bytes, "audio/mpeg")

            # Save clip JSON (without local temp paths)
            clip_save = {**clip_data, "narration_audio_file_id": audio_rec.file_id, "narration_audio": None}
            clip_bytes = json.dumps(clip_save, ensure_ascii=False, indent=2).encode("utf-8")
            clip_rec = store.save_output(f"clip_{task_id[:8]}.json", clip_bytes)

            prefix = "fast_writing_clip_data" if fast else "generate_clip_data"
            order = f"{prefix}_{task_id[:12]}"
            store.update_task(
                task_id,
                status=2,
                task_order_num=order,
                files=[_file_entry(clip_rec.file_id, clip_rec.file_name, ".json")],
                results={
                    "file_ids": [clip_rec.file_id, audio_rec.file_id],
                    "clip_data": clip_save,
                },
                consumed_points=8,
            )
    except Exception as e:
        logger.exception("clip_data failed")
        store.update_task(task_id, status=3, error_message=str(e))


async def process_video_composing(task_id: str) -> None:
    rec = store.get_task(task_id)
    if not rec:
        return
    store.update_task(task_id, status=1)
    body = rec.body
    try:
        if not ffmpeg_available():
            raise RuntimeError("ffmpeg not found. Install ffmpeg and add to PATH.")

        order_num = body.get("order_num", "")
        clip_task = store.get_task_by_order(order_num)

        # Standard path: order_num is generate_writing — locate clip_data by reference
        if clip_task and clip_task.task_type == "generate_writing":
            clip_task = store.find_clip_for_writing_order(order_num)
        elif clip_task and clip_task.task_type != "fast_clip_data":
            # Might be generate_writing order without direct clip type on index
            alt = store.find_clip_for_writing_order(order_num)
            if alt:
                clip_task = alt

        if not clip_task or clip_task.status != 2:
            raise RuntimeError(f"Clip task not ready for order_num={order_num}")

        clip_data = clip_task.results.get("clip_data") or {}
        video_id = clip_data.get("video_file_id") or _video_from_body(clip_task.body)
        if not video_id:
            raise RuntimeError("No source video file_id in clip data")

        video_rec = store.get_file(video_id)
        if not video_rec or not video_rec.path.exists():
            raise RuntimeError(f"Video file not found: {video_id}")

        narr_file_id = clip_data.get("narration_audio_file_id")
        narr_rec = store.get_file(narr_file_id) if narr_file_id else None
        if not narr_rec:
            raise RuntimeError("Narration audio not found")

        bgm_path = None
        bgm_id = body.get("bgm") or clip_data.get("bgm")
        if bgm_id:
            bgm_rec = store.get_file(bgm_id)
            if bgm_rec and bgm_rec.path.exists():
                bgm_path = bgm_rec.path

        out_path = compose_output_path()
        mix_video_with_narration(video_rec.path, narr_rec.path, bgm_path, out_path)

        out_bytes = out_path.read_bytes()
        out_rec = store.add_file(out_path.name, len(out_bytes), "video/mp4", out_bytes)
        video_url = f"{_public_url()}/media/{out_rec.file_id}"

        store.update_task(
            task_id,
            status=2,
            task_order_num=f"video_composing_{task_id[:12]}",
            files=[_file_entry(out_rec.file_id, out_rec.file_name, ".mp4")],
            results={
                "file_ids": [out_rec.file_id],
                "tasks": [{"video_url": video_url, "status": "success"}],
            },
            consumed_points=15,
        )
    except Exception as e:
        logger.exception("video_composing failed")
        store.update_task(task_id, status=3, error_message=str(e))


def _public_url() -> str:
    from gateway.config import settings

    return settings.public_url.rstrip("/")

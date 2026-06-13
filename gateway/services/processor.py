"""Background task processors — official-aligned pipeline."""

from __future__ import annotations

import json
import logging

from gateway.config import settings
from gateway.services.capcut_export import build_capcut_zip
from gateway.services.episodes import episode_map, load_episodes
from gateway.services.media import ffprobe_duration
from gateway.services.srt import srt_duration
from gateway.services.timeline import align_timeline_after_tts, build_timeline
from gateway.services.tts import get_audio_duration, synthesize_for_dubbing
from gateway.services.video import compose_from_timeline, compose_output_path, ffmpeg_available
from gateway.services.workspace import work_directory
from gateway.services.writing import (
    generate_fast_writing,
    generate_fast_writing_episodes,
    generate_standard_writing,
)
from gateway.store import store

logger = logging.getLogger(__name__)


def _file_entry(file_id: str, file_name: str, suffix: str) -> dict:
    return {"file_id": file_id, "file_path": file_name, "suffix": suffix}


def _load_srt_from_body(body: dict) -> list:
    episodes = load_episodes(body)
    if episodes:
        return episodes[0].entries
    return []


def _video_from_body(body: dict) -> str | None:
    episodes = load_episodes(body)
    if episodes and episodes[0].video_key:
        return episodes[0].video_key
    return body.get("native_video") or body.get("video_path")


def _source_duration(body: dict, srt_entries: list) -> float:
    episodes = load_episodes(body)
    if episodes:
        if len(episodes) == 1:
            ep = episodes[0]
            if ep.video_duration > 0:
                return ep.video_duration
            return srt_duration(ep.entries)
        return sum(ep.video_duration or srt_duration(ep.entries) for ep in episodes)
    vid = body.get("native_video") or body.get("video_path")
    if vid:
        rec = store.get_file(vid)
        if rec and rec.path.exists():
            dur = ffprobe_duration(rec.path)
            if dur > 0:
                return dur
    return srt_duration(srt_entries)


async def process_fast_writing(task_id: str) -> None:
    rec = store.get_task(task_id)
    if not rec:
        return
    store.update_task(task_id, status=1)
    body = rec.body
    try:
        episodes = load_episodes(body)
        movie_json = body.get("confirmed_movie_json")
        if isinstance(movie_json, str):
            movie_json = json.loads(movie_json)

        request_model = body.get("model") or "pro"
        if len(episodes) > 1:
            writing = await generate_fast_writing_episodes(
                playlet_name=body.get("playlet_name", "未命名"),
                target_mode=str(body.get("target_mode", "1")),
                movie_json=movie_json,
                episodes=episodes,
                language=body.get("language", "Chinese (中文)"),
                learning_model_id=body.get("learning_model_id", ""),
                target_platform=body.get("target_platform", ""),
                perspective=body.get("perspective", "third_person"),
                target_character_name=body.get("target_character_name", ""),
                request_model=request_model,
            )
        else:
            srt_entries = episodes[0].entries if episodes else _load_srt_from_body(body)
            source_dur = _source_duration(body, srt_entries)
            writing = await generate_fast_writing(
                playlet_name=body.get("playlet_name", "未命名"),
                target_mode=str(body.get("target_mode", "1")),
                movie_json=movie_json,
                srt_entries=srt_entries or None,
                language=body.get("language", "Chinese (中文)"),
                learning_model_id=body.get("learning_model_id", ""),
                target_platform=body.get("target_platform", ""),
                perspective=body.get("perspective", "third_person"),
                target_character_name=body.get("target_character_name", ""),
                source_duration=source_dur,
                request_model=request_model,
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
        episodes = load_episodes(body)
        srt_entries = episodes[0].entries if episodes else _load_srt_from_body(body)
        source_dur = _source_duration(body, srt_entries)
        if len(episodes) > 1:
            writing = await generate_fast_writing_episodes(
                playlet_name=body.get("playlet_name", "未命名"),
                target_mode="2",
                movie_json=body.get("story_info") and {"story_info": body.get("story_info")} or None,
                episodes=episodes,
                target_platform=body.get("target_platform", "douyin"),
                learning_model_id=body.get("learning_model_id", ""),
                perspective=body.get("perspective", "third_person"),
                target_character_name=body.get("target_character_name", ""),
                request_model=body.get("model"),
            )
        else:
            writing = await generate_standard_writing(
                playlet_name=body.get("playlet_name", "未命名"),
                movie_json=body.get("story_info") and {"story_info": body.get("story_info")} or None,
                srt_entries=srt_entries or None,
                target_platform=body.get("target_platform", "douyin"),
                learning_model_id=body.get("learning_model_id", ""),
                perspective=body.get("perspective", "third_person"),
                target_character_name=body.get("target_character_name", ""),
                source_duration=source_dur,
                request_model=body.get("model"),
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
        if fast:
            upstream = store.get_task(body.get("task_id", ""))
            file_id = body.get("file_id")
            source_body = body
        else:
            upstream = store.get_task_by_order(body.get("order_num", ""))
            file_id = (upstream.results.get("file_ids") or [None])[0] if upstream else None
            source_body = upstream.body if upstream else body

        if not upstream or upstream.status != 2:
            raise RuntimeError("Upstream writing task not ready")

        writing_raw = store.read_file_bytes(file_id or upstream.files[0]["file_id"])
        writing = json.loads(writing_raw.decode("utf-8"))
        content = writing.get("content", [])

        episodes = load_episodes(source_body)
        ep_by_num = episode_map(source_body)

        def _duration_for_segment(seg: dict) -> float:
            num = int(seg.get("episode_num") or 1)
            if num in ep_by_num:
                ep = ep_by_num[num]
                return ep.video_duration or srt_duration(ep.entries)
            return 0.0

        default_video_id = _video_from_body(source_body)
        default_srt = episodes[0].entries if episodes else _load_srt_from_body(source_body)
        default_video_rec = store.get_file(default_video_id) if default_video_id else None
        default_video_duration = (
            ffprobe_duration(default_video_rec.path)
            if default_video_rec and default_video_rec.path.exists()
            else srt_duration(default_srt)
        )

        target_mode = str(upstream.body.get("target_mode", "2" if default_srt else "1"))

        # Build per-episode timelines then merge (supports multi-episode / multi-video)
        timeline_out: list[dict] = []
        content_groups: list[tuple[int, list[dict]]] = []
        if episodes and len(episodes) > 1:
            by_ep: dict[int, list[dict]] = {}
            for seg in content:
                num = int(seg.get("episode_num") or 1)
                by_ep.setdefault(num, []).append(seg)
            content_groups = sorted(by_ep.items(), key=lambda x: x[0])
        else:
            content_groups = [(1, content)]

        dubbing = body.get("dubbing", "")
        dubbing_type = body.get("dubbing_type", "普通话")
        model_tier = upstream.body.get("model")

        global_idx = 0
        with work_directory("clip_") as work:
            for ep_num, ep_content in content_groups:
                ep = ep_by_num.get(ep_num)
                srt_entries = ep.entries if ep else default_srt
                video_id = (ep.video_key if ep else None) or default_video_id
                video_rec = store.get_file(video_id) if video_id else None
                video_duration = (
                    ffprobe_duration(video_rec.path)
                    if video_rec and video_rec.path.exists()
                    else (_duration_for_segment(ep_content[0]) if ep_content else default_video_duration)
                )
                capcut_key = f"ep{ep_num}"

                ep_timeline = build_timeline(
                    ep_content,
                    srt_entries,
                    target_mode=target_mode,
                    video_duration=video_duration,
                    min_clip=settings.min_clip_seconds,
                    max_clip=settings.max_clip_seconds,
                )

                for clip in ep_timeline:
                    item = {
                        "type": clip.type,
                        "text": clip.text,
                        "video_start": clip.video_start,
                        "video_end": clip.video_end,
                        "content_index": clip.content_index,
                        "duration": clip.video_end - clip.video_start,
                        "episode_num": ep_num,
                        "video_file_id": video_id,
                        "capcut_video_key": capcut_key,
                        "video_duration": video_duration,
                    }
                    if clip.type == "narration":
                        audio_path = work / f"narr_{global_idx:04d}.mp3"
                        await synthesize_for_dubbing(
                            clip.text, dubbing, dubbing_type, audio_path, tier=model_tier or "pro"
                        )
                        item["audio_duration"] = get_audio_duration(audio_path)
                        audio_rec = store.save_output(
                            f"narr_{task_id[:6]}_{global_idx}.mp3", audio_path.read_bytes(), "audio/mpeg"
                        )
                        item["audio_file_id"] = audio_rec.file_id
                        item["audio_path"] = str(audio_rec.path)
                    timeline_out.append(item)
                    global_idx += 1

        align_timeline_after_tts(
            timeline_out,
            video_duration=max(default_video_duration, max((c.get("video_duration") or 0) for c in timeline_out) or 1),
            min_clip=settings.min_clip_seconds,
            max_clip=settings.max_clip_seconds,
            max_narration_clip=settings.max_narration_clip_seconds,
            pad=settings.narration_pad_seconds,
            max_audio_speed=settings.max_audio_speed,
        )

        total_duration = sum(c["duration"] for c in timeline_out)
        clip_data = {
            "timeline": timeline_out,
            "segments": content,
            "bgm": body.get("bgm"),
            "dubbing": dubbing,
            "dubbing_type": dubbing_type,
            "video_file_id": default_video_id,
            "video_duration": default_video_duration,
            "output_duration": total_duration,
            "target_mode": target_mode,
            "model_tier": model_tier,
            "meta": writing.get("meta", {}),
            "episode_count": len(episodes) if episodes else 1,
        }

        clip_bytes = json.dumps(clip_data, ensure_ascii=False, indent=2).encode("utf-8")
        clip_rec = store.save_output(f"clip_{task_id[:8]}.json", clip_bytes)

        result_files = [_file_entry(clip_rec.file_id, clip_rec.file_name, ".json")]
        capcut_file_id = None

        if settings.export_capcut_draft and timeline_out:
            try:
                video_paths: dict[str, Path] = {}
                if episodes:
                    for ep in episodes:
                        if ep.video_key:
                            rec = store.get_file(ep.video_key)
                            if rec and rec.path.exists():
                                video_paths[f"ep{ep.num}"] = rec.path
                if not video_paths and default_video_rec and default_video_rec.path.exists():
                    video_paths["main"] = default_video_rec.path
                    for item in timeline_out:
                        item.setdefault("capcut_video_key", "main")

                if video_paths:
                    title = upstream.body.get("playlet_name") or f"narrator_{task_id[:8]}"
                    with work_directory("capcut_") as cap_work:
                        zip_bytes = build_capcut_zip(
                            title=title,
                            timeline=timeline_out,
                            video_paths=video_paths,
                            work_dir=cap_work,
                        )
                    cap_rec = store.save_output(
                        f"capcut_{task_id[:8]}.zip", zip_bytes, "application/zip"
                    )
                    capcut_file_id = cap_rec.file_id
                    result_files.append(_file_entry(cap_rec.file_id, cap_rec.file_name, ".zip"))
            except Exception:
                logger.exception("CapCut draft export failed (clip_data still saved)")

        prefix = "fast_writing_clip_data" if fast else "generate_clip_data"
        order = f"{prefix}_{task_id[:12]}"
        results = {"file_ids": [f["file_id"] for f in result_files], "clip_data": clip_data}
        if capcut_file_id:
            results["capcut_draft_file_id"] = capcut_file_id
            results["capcut_draft_url"] = f"{_public_url()}/media/{capcut_file_id}"

        store.update_task(
            task_id,
            status=2,
            task_order_num=order,
            files=result_files,
            results=results,
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

        if clip_task and clip_task.task_type == "generate_writing":
            clip_task = store.find_clip_for_writing_order(order_num)
        elif clip_task and clip_task.task_type != "fast_clip_data":
            alt = store.find_clip_for_writing_order(order_num)
            if alt:
                clip_task = alt

        if not clip_task or clip_task.status != 2:
            raise RuntimeError(f"Clip task not ready for order_num={order_num}")

        clip_data = clip_task.results.get("clip_data") or {}
        timeline = clip_data.get("timeline") or []

        # Resolve audio paths from file store
        for item in timeline:
            fid = item.get("audio_file_id")
            if fid and not item.get("audio_path"):
                frec = store.get_file(fid)
                if frec:
                    item["audio_path"] = str(frec.path)

        video_id = clip_data.get("video_file_id") or _video_from_body(clip_task.body)
        if not video_id:
            raise RuntimeError("No source video file_id")

        video_rec = store.get_file(video_id)
        if not video_rec or not video_rec.path.exists():
            raise RuntimeError(f"Video file not found: {video_id}")

        if not timeline:
            raise RuntimeError("Empty clip timeline — re-run fast-clip-data")

        bgm_path = None
        bgm_id = body.get("bgm") or clip_data.get("bgm")
        if bgm_id:
            bgm_rec = store.get_file(bgm_id)
            if bgm_rec and bgm_rec.path.exists():
                bgm_path = bgm_rec.path
            else:
                # Pre-built BGM ids may not be uploaded — try bundled path skip
                logger.warning("BGM file %s not in store, composing without BGM file", bgm_id)

        out_path = compose_output_path()
        with work_directory("compose_") as work:
            compose_from_timeline(video_rec.path, timeline, bgm_path, work, out_path)

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
                "tasks": [{"video_url": video_url, "status": "success", "duration": clip_data.get("output_duration")}],
            },
            consumed_points=15,
        )
    except Exception as e:
        logger.exception("video_composing failed")
        store.update_task(task_id, status=3, error_message=str(e))


def _public_url() -> str:
    from gateway.config import settings

    return settings.public_url.rstrip("/")

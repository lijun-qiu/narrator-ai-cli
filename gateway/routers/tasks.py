"""Task creation, query, and commentary workflow endpoints."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks

from gateway.response import err, ok
from gateway.services.processor import (
    process_clip_data,
    process_fast_writing,
    process_generate_writing,
    process_video_composing,
)
from gateway.services.writing import search_movie
from gateway.store import store

logger = logging.getLogger(__name__)
router = APIRouter()


async def _stub_popular_learning(task_id: str) -> None:
    store.update_task(task_id, status=1)
    await asyncio.sleep(0.5)
    store.update_task(
        task_id,
        status=2,
        task_order_num=f"popular_learning_{task_id[:12]}",
        results={"learning_model_id": "gateway-stub-model", "agent_unique_code": "gateway-stub-model"},
        consumed_points=0,
    )


@router.post("/v2/task/commentary/create_popular_learning")
def create_popular_learning(body: dict, background: BackgroundTasks):
    rec = store.create_task("popular_learning", body)
    background.add_task(_stub_popular_learning, rec.task_id)
    return ok({"task_id": rec.task_id})


@router.post("/v2/task/commentary/create_generate_writing")
def create_generate_writing(body: dict, background: BackgroundTasks):
    rec = store.create_task("generate_writing", body)
    background.add_task(process_generate_writing, rec.task_id)
    return ok({"task_id": rec.task_id})


@router.post("/v2/task/commentary/create_fast_generate_writing")
def create_fast_writing(body: dict, background: BackgroundTasks):
    rec = store.create_task("fast_writing", body)
    background.add_task(process_fast_writing, rec.task_id)
    return ok({"task_id": rec.task_id})


@router.post("/v2/task/commentary/create_generate_clip_data")
def create_clip_data(body: dict, background: BackgroundTasks):
    rec = store.create_task("clip_data", body)

    async def run():
        await process_clip_data(rec.task_id, fast=False)

    background.add_task(run)
    return ok({"task_id": rec.task_id})


@router.post("/v2/task/commentary/create_generate_fast_writing_clip_data")
def create_fast_clip_data(body: dict, background: BackgroundTasks):
    rec = store.create_task("fast_clip_data", body)

    async def run():
        await process_clip_data(rec.task_id, fast=True)

    background.add_task(run)
    return ok({"task_id": rec.task_id})


@router.post("/v2/task/commentary/create_video_composing")
def create_video_composing(body: dict, background: BackgroundTasks):
    rec = store.create_task("video_composing", body)
    background.add_task(process_video_composing, rec.task_id)
    return ok({"task_id": rec.task_id})


@router.post("/v2/task/commentary/create_magic_video")
def create_magic_video(body: dict):
    rec = store.create_task("magic_video", body)
    store.update_task(rec.task_id, status=2, results={"message": "magic-video passthrough not implemented"})
    return ok({"task_id": rec.task_id})


@router.post("/v2/task/voice_clone/create")
def create_voice_clone(body: dict):
    rec = store.create_task("voice_clone", body)
    store.update_task(rec.task_id, status=2, results={"voice_id": "gateway-voice-stub"})
    return ok({"task_id": rec.task_id, "voice_id": "gateway-voice-stub"})


@router.post("/v2/task/text_to_speech/create")
def create_tts(body: dict, background: BackgroundTasks):
    rec = store.create_task("tts", body)
    background.add_task(_process_tts, rec.task_id)
    return ok({"task_id": rec.task_id})


async def _process_tts(task_id: str) -> None:
    from gateway.services.tts import resolve_voice, synthesize_to_file
    import tempfile
    from pathlib import Path

    rec = store.get_task(task_id)
    if not rec:
        return
    store.update_task(task_id, status=1)
    try:
        text = rec.body.get("audio_text", "")
        voice = resolve_voice(rec.body.get("voice_id", ""), "普通话")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "tts.mp3"
            await synthesize_to_file(text, voice, out)
            frec = store.save_output(f"tts_{task_id[:8]}.mp3", out.read_bytes(), "audio/mpeg")
        store.update_task(
            task_id,
            status=2,
            files=[{"file_id": frec.file_id, "file_path": frec.file_name, "suffix": ".mp3"}],
            results={"file_ids": [frec.file_id]},
        )
    except Exception as e:
        store.update_task(task_id, status=3, error_message=str(e))


@router.get("/v2/task/commentary/query/{task_id}")
def query_task(task_id: str):
    rec = store.get_task(task_id)
    if not rec:
        return err(10010, "Task not found")
    return ok(store.task_to_query(rec))


@router.get("/v2/task/commentary/list")
def list_tasks(page: int = 1, limit: int = 10, status: int | None = None, type: int | None = None, category: str | None = None):
    return ok(store.list_tasks(page=page, limit=limit, status=status, task_type=type))


@router.post("/v2/task/commentary/consume_budget")
def consume_budget(body: dict):
    return ok(
        {
            "viral_learning_points": 0,
            "commentary_generation_points": 5,
            "video_synthesis_points": 15,
            "visual_template_points": 0,
            "total_consume_points": 20,
        }
    )


@router.post("/v2/task/commentary/material_verification")
def material_verification(body: dict):
    return ok({"is_valid": True, "errors": [], "warnings": []})


@router.get("/v2/task/commentary/get_generate_writed")
def get_writing(task_id: str, file_id: str):
    raw = store.read_file_bytes(file_id)
    if not raw:
        return err(10007, "Writing file not found")
    import json

    return ok(json.loads(raw.decode("utf-8")))


@router.post("/v2/task/commentary/save_generate_writed")
def save_writing(body: dict):
    content = body.get("content", [])
    payload = __import__("json").dumps({"content": content}, ensure_ascii=False).encode("utf-8")
    frec = store.save_output(f"writing_edited_{body.get('task_id', '')[:8]}.json", payload)
    return ok({"file_id": frec.file_id})


@router.post("/v2/task/commentary/save_clip_data")
def save_clip(body: dict):
    return ok({"status": "saved"})


@router.get("/v2/task/commentary/search_media_information")
async def search_media(query: str):
    try:
        results = await search_movie(query)
        return ok({"data": results})
    except Exception as e:
        logger.exception("search_movie failed")
        return err(10001, str(e))


@router.get("/v2/task/commentary/get_magic_templates")
def magic_templates():
    return ok({"templates": [{"name": "default", "description": "Gateway stub template"}]})


@router.get("/v2/res/movie-sucai")
def movie_materials(page: int = 1, size: int = 100):
    return ok({"total": 0, "page": page, "size": size, "items": []})

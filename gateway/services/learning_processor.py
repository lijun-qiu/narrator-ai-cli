"""Process popular-learning task — LLM style extraction from reference SRT."""

from __future__ import annotations

import logging

from gateway.services.popular_learning import analyze_reference_style
from gateway.store import store

logger = logging.getLogger(__name__)


async def process_popular_learning(task_id: str) -> None:
    rec = store.get_task(task_id)
    if not rec:
        return
    store.update_task(task_id, status=1)
    body = rec.body
    try:
        srt_key = body.get("video_srt_path")
        if not srt_key:
            raise ValueError("video_srt_path is required")

        from gateway.services.srt import parse_srt

        raw = store.read_file_bytes(srt_key)
        if not raw:
            raise ValueError(f"SRT file not found: {srt_key}")
        entries = parse_srt(raw.decode("utf-8", errors="replace"))
        if not entries:
            raise ValueError("参考字幕为空")

        video_name = ""
        vid = body.get("video_path")
        if vid:
            frec = store.get_file(vid)
            if frec:
                video_name = frec.file_name

        learning_model_id, profile = await analyze_reference_style(entries, video_name=video_name)
        order = f"popular_learning_{task_id[:12]}"

        store.update_task(
            task_id,
            status=2,
            task_order_num=order,
            results={
                "learning_model_id": learning_model_id,
                "agent_unique_code": learning_model_id,
                "style_profile": profile,
            },
            consumed_points=3,
        )
    except Exception as e:
        logger.exception("popular_learning failed")
        store.update_task(task_id, status=3, error_message=str(e))

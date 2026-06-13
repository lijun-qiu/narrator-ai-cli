"""LLM-based popular-learning — analyze reference SRT to build a style profile."""

from __future__ import annotations

import logging
import uuid

from gateway.services.llm import chat, extract_json
from gateway.services.narration_styles import save_learned_profile
from gateway.services.srt import SRTEntry, srt_summary

logger = logging.getLogger(__name__)


async def analyze_reference_style(
    entries: list[SRTEntry],
    *,
    video_name: str = "",
) -> tuple[str, dict]:
    """Return (learning_model_id, profile dict) mimicking official popular-learning output."""
    sample = srt_summary(entries, max_chars=10000)
    if not sample.strip():
        raise ValueError("参考字幕为空，无法学习风格")

    system = (
        "你是影视解说风格分析师。根据参考解说字幕，提取可复用的写作风格 profile。"
        "只输出 JSON，不要 markdown。"
    )
    user = f"""分析以下参考解说字幕，提取风格 profile：

参考来源：{video_name or "用户上传参考"}

字幕样本：
{sample}

输出 JSON：
{{
  "summary": "50字内风格概述",
  "tone": "语气，如幽默/悬疑/热血",
  "sentence_style": "句式特点",
  "hook_pattern": "开头钩子套路",
  "pacing": "节奏快慢",
  "vocabulary": "常用词汇/口头禅",
  "rules": ["写作规则1", "写作规则2", "至少5条"]
}}"""

    raw = await chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        tier="pro",
        temperature=0.35,
    )
    profile = extract_json(raw)
    if not isinstance(profile, dict):
        raise ValueError("风格分析返回格式无效")

    learning_model_id = f"gateway-learn-{uuid.uuid4().hex[:12]}"
    profile["learning_model_id"] = learning_model_id
    profile["source"] = "popular_learning"
    save_learned_profile(learning_model_id, profile)
    logger.info("popular_learning profile saved: %s", learning_model_id)
    return learning_model_id, profile

"""Generate narration scripts via LLM."""

from __future__ import annotations

import json

from gateway.services.llm import chat, extract_json
from gateway.services.srt import SRTEntry, srt_summary


async def generate_fast_writing(
    *,
    playlet_name: str,
    target_mode: str,
    movie_json: dict | None,
    srt_entries: list[SRTEntry] | None,
    language: str = "Chinese (中文)",
    style_hint: str = "",
) -> dict:
    srt_block = srt_summary(srt_entries) if srt_entries else ""
    movie_block = json.dumps(movie_json, ensure_ascii=False) if movie_json else ""

    system = (
        "你是专业影视解说文案作者。根据电影信息和/或原片字幕，输出结构化 JSON，"
        "不要输出 markdown 代码块以外的任何解释。"
    )
    user = f"""片名：{playlet_name}
模式：{target_mode}（1=纯解说 2=原声混剪 3=冷门新剧）
语言：{language}
风格提示：{style_hint or "热血解说"}

电影信息：
{movie_block or "无"}

原片字幕摘要：
{srt_block or "无"}

请输出 JSON：
{{
  "content": [
    {{"type": "解说", "text": "开场解说..."}},
    {{"type": "原声", "text": "保留的原声台词（原声混剪模式可多条）"}},
    {{"type": "解说", "text": "..."}}
  ],
  "title": "视频标题建议"
}}
要求：8-15 段解说，每段 1-3 句，口语化，有节奏。"""

    raw = await chat([{"role": "system", "content": system}, {"role": "user", "content": user}])
    data = extract_json(raw)
    if isinstance(data, dict) and "content" in data:
        return data
    if isinstance(data, list):
        return {"content": data, "title": playlet_name}
    raise ValueError(f"Invalid writing JSON from LLM: {raw[:200]}")


async def generate_standard_writing(
    *,
    playlet_name: str,
    movie_json: dict | None,
    srt_entries: list[SRTEntry] | None,
    target_platform: str = "douyin",
) -> dict:
    return await generate_fast_writing(
        playlet_name=playlet_name,
        target_mode="1",
        movie_json=movie_json,
        srt_entries=srt_entries,
        style_hint=f"平台：{target_platform}，二创解说",
    )


async def search_movie(query: str) -> list[dict]:
    system = "你是电影数据库助手，返回 JSON 数组，不要其他文字。"
    user = f"""搜索电影「{query}」，返回最多 3 条结果 JSON 数组：
[{{"title":"中文名","title_en":"English","year":"2024","type":"喜剧","character_name":"主演","story_info":"剧情简介200字内","director":"导演"}}]"""
    raw = await chat([{"role": "system", "content": system}, {"role": "user", "content": user}], temperature=0.3)
    data = extract_json(raw)
    if isinstance(data, list):
        return data[:3]
    if isinstance(data, dict) and "data" in data:
        return data["data"][:3]
    return [data] if isinstance(data, dict) else []

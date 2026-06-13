"""Generate narration scripts via LLM — chunked for full-length sources."""

from __future__ import annotations

import json
import logging

from gateway.config import settings
from gateway.services.models import resolve_llm_model
from gateway.services.narration_styles import build_style_prompt
from gateway.services.llm import chat, extract_json
from gateway.services.srt import SRTEntry, chunk_srt_entries, chunk_srt_text, extract_name_hints, srt_duration

logger = logging.getLogger(__name__)

NARRATION_TYPES = {"解说", "narration", "解说词"}
ORIGINAL_TYPES = {"原声", "original", "原片"}


def _resolve_llm_model(request_model: str | None) -> str:
    return resolve_llm_model(request_model)


def _target_commentary_duration(source_seconds: float) -> float:
    if source_seconds <= 0:
        return settings.min_target_duration
    target = source_seconds * settings.target_duration_ratio
    target = max(target, settings.min_target_duration)
    return min(target, settings.max_target_duration)


def _segments_for_window(window_seconds: float, total_target: float, source_seconds: float) -> int:
    share = window_seconds / max(source_seconds, 1.0)
    window_target = total_target * share
    count = int(window_target / 60.0 * settings.segments_per_minute)
    return max(3, min(count, 12))


async def _generate_chunk(
    *,
    playlet_name: str,
    target_mode: str,
    window_start: float,
    window_end: float,
    window_entries: list[SRTEntry],
    movie_json: dict | None,
    language: str,
    style_hint: str,
    segment_count: int,
    use_pro: bool,
) -> list[dict]:
    srt_block = chunk_srt_text(window_entries)
    movie_block = json.dumps(movie_json, ensure_ascii=False) if movie_json else ""
    name_hints = extract_name_hints(window_entries)
    names_block = "、".join(name_hints[:15]) if name_hints else "（见字幕）"

    mode_rules = {
        "1": "纯解说：全部 type=解说，不要原声段。",
        "2": "原声混剪：解说与原声交替，原声段 text 必须来自字幕原文，type=原声。",
        "3": "冷门新剧：以解说为主，可少量原声，type=原声 必须来自字幕。",
    }

    system = (
        "你是专业影视解说剪辑师。根据字幕时间轴生成结构化解说脚本 JSON。"
        "每段必须标注 video_start / video_end（秒，浮点数），对应原片画面区间。"
        "人名、地名必须来自字幕或电影信息，禁止自造姓名。"
        "只输出 JSON，不要 markdown。"
    )
    quality = "高质量、细节丰富" if use_pro else "简洁流畅"
    user = f"""片名：{playlet_name}
本段原片时间：{window_start:.1f}s - {window_end:.1f}s
模式：{target_mode} — {mode_rules.get(target_mode, mode_rules["1"])}
语言：{language}
风格：
{style_hint or "热血悬疑解说"}
质量：{quality}

电影信息：{movie_block or "无"}
字幕中出现的人物/称谓（必须使用，禁止改写）：{names_block}

本段字幕：
{srt_block}

请输出 JSON：
{{
  "content": [
    {{
      "type": "解说",
      "text": "解说词...",
      "video_start": {window_start:.1f},
      "video_end": {window_start + 8:.1f}
    }},
    {{
      "type": "原声",
      "text": "字幕原文台词",
      "video_start": 120.5,
      "video_end": 125.0
    }}
  ]
}}

要求：
- 本段生成 {segment_count} 段左右（解说+原声合计）
- video_start/video_end 必须落在 [{window_start:.1f}, {window_end:.1f}] 内
- 解说段 video_end - video_start 建议 4-15 秒，与解说词长度匹配，禁止单段超过 18 秒
- 原声段 text 必须与字幕原文一致
- 人物姓名只能使用「{names_block}」及电影信息中的名字，禁止自造
- 解说口语化，推进剧情，不要写「在本段中」等元叙述"""

    raw = await chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        tier="pro" if use_pro else "flash",
        temperature=0.55 if use_pro else 0.65,
    )
    data = extract_json(raw)
    if isinstance(data, dict) and "content" in data:
        return data["content"]
    if isinstance(data, list):
        return data
    raise ValueError(f"Invalid chunk writing: {raw[:200]}")


async def generate_fast_writing(
    *,
    playlet_name: str,
    target_mode: str,
    movie_json: dict | None,
    srt_entries: list[SRTEntry] | None,
    language: str = "Chinese (中文)",
    style_hint: str = "",
    learning_model_id: str = "",
    target_platform: str = "",
    perspective: str = "third_person",
    target_character_name: str = "",
    source_duration: float = 0.0,
    request_model: str | None = None,
) -> dict:
    style_prompt = build_style_prompt(
        learning_model_id=learning_model_id or style_hint,
        target_platform=target_platform,
        perspective=perspective,
        target_character_name=target_character_name,
    )
    entries = srt_entries or []
    source_seconds = source_duration or srt_duration(entries)
    target_duration = _target_commentary_duration(source_seconds)
    use_pro = request_model == "pro"

    if not entries:
        # mode 1 without SRT — single-shot short script scaled to target
        segment_count = max(8, int(target_duration / 60 * settings.segments_per_minute))
        system = "你是专业影视解说文案作者。输出 JSON，不要 markdown。"
        user = f"""片名：{playlet_name}
模式：{target_mode}（纯解说）
语言：{language}
{style_prompt}
电影信息：{json.dumps(movie_json, ensure_ascii=False) if movie_json else "无"}
目标成片时长约 {target_duration/60:.0f} 分钟，请生成 {segment_count} 段解说。
JSON: {{"content":[{{"type":"解说","text":"..."}}], "title":"..."}}"""
        raw = await chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            tier=request_model or "flash",
        )
        data = extract_json(raw)
        content = data.get("content", data) if isinstance(data, dict) else data
        return {"content": content, "title": playlet_name, "meta": {"target_duration": target_duration}}

    chunks = chunk_srt_entries(entries, settings.writing_chunk_seconds)
    all_content: list[dict] = []

    for window_start, window_end, window_entries in chunks:
        seg_count = _segments_for_window(window_end - window_start, target_duration, source_seconds)
        try:
            part = await _generate_chunk(
                playlet_name=playlet_name,
                target_mode=target_mode,
                window_start=window_start,
                window_end=window_end,
                window_entries=window_entries,
                movie_json=movie_json,
                language=language,
                style_hint=style_prompt,
                segment_count=seg_count,
                use_pro=use_pro,
            )
            all_content.extend(part)
            logger.info("Writing chunk %.0f-%.0f: %d segments", window_start, window_end, len(part))
        except Exception:
            logger.exception("Chunk writing failed %.0f-%.0f", window_start, window_end)

    if not all_content:
        raise ValueError("No writing segments generated")

    return {
        "content": all_content,
        "title": playlet_name,
        "meta": {
            "source_duration": source_seconds,
            "target_duration": target_duration,
            "chunk_count": len(chunks),
            "segment_count": len(all_content),
            "model": _resolve_llm_model(request_model),
            "model_tier": request_model or "pro",
            "learning_model_id": learning_model_id or style_hint,
            "target_platform": target_platform,
            "perspective": perspective,
        },
    }


async def generate_fast_writing_episodes(
    *,
    playlet_name: str,
    target_mode: str,
    movie_json: dict | None,
    episodes: list,
    language: str = "Chinese (中文)",
    learning_model_id: str = "",
    target_platform: str = "",
    perspective: str = "third_person",
    target_character_name: str = "",
    request_model: str | None = None,
) -> dict:
    """Generate writing for multiple episodes; merge content with episode_num tags."""
    from gateway.services.episodes import EpisodeBundle

    all_content: list[dict] = []
    total_source = 0.0
    chunk_total = 0

    for ep in episodes:
        assert isinstance(ep, EpisodeBundle)
        ep_name = playlet_name if len(episodes) == 1 else f"{playlet_name} 第{ep.num}集"
        part = await generate_fast_writing(
            playlet_name=ep_name,
            target_mode=target_mode,
            movie_json=movie_json,
            srt_entries=ep.entries or None,
            language=language,
            learning_model_id=learning_model_id,
            target_platform=target_platform,
            perspective=perspective,
            target_character_name=target_character_name,
            source_duration=ep.video_duration,
            request_model=request_model,
        )
        for seg in part.get("content") or []:
            seg["episode_num"] = ep.num
        all_content.extend(part.get("content") or [])
        total_source += ep.video_duration
        chunk_total += part.get("meta", {}).get("chunk_count") or 0

    if not all_content:
        raise ValueError("No writing segments generated for episodes")

    return {
        "content": all_content,
        "title": playlet_name,
        "meta": {
            "source_duration": total_source,
            "episode_count": len(episodes),
            "segment_count": len(all_content),
            "chunk_count": chunk_total,
            "model_tier": request_model or "pro",
            "learning_model_id": learning_model_id,
            "target_platform": target_platform,
            "perspective": perspective,
        },
    }


async def generate_standard_writing(
    *,
    playlet_name: str,
    movie_json: dict | None,
    srt_entries: list[SRTEntry] | None,
    target_platform: str = "douyin",
    learning_model_id: str = "",
    perspective: str = "third_person",
    target_character_name: str = "",
    source_duration: float = 0.0,
    request_model: str | None = None,
) -> dict:
    return await generate_fast_writing(
        playlet_name=playlet_name,
        target_mode="2" if srt_entries else "1",
        movie_json=movie_json,
        srt_entries=srt_entries,
        learning_model_id=learning_model_id,
        target_platform=target_platform,
        perspective=perspective,
        target_character_name=target_character_name,
        source_duration=source_duration,
        request_model=request_model or "pro",
    )


async def search_movie(query: str) -> list[dict]:
    """Search movie/drama info — with fallback for sequels/episodes like 罚罪2."""
    import re

    query = query.strip()
    if not query:
        return []

    results = await _search_movie_llm(query)
    if results:
        return results

    # 罚罪2 / 某某第N集 → 尝试父片名
    parent = re.sub(r"第[一二三四五六七八九十百\d]+[集季部话]", "", query).strip()
    parent = re.sub(r"[\s\-_]+", "", parent)
    parent = re.sub(r"([^\d]+)\d+$", r"\1", parent)  # 罚罪2 → 罚罪
    if parent and parent != query:
        logger.info("search_movie fallback: %s -> %s", query, parent)
        parent_results = await _search_movie_llm(
            parent,
            extra=f"用户实际搜索的是「{query}」，可能是续集/某季/非正式称呼，请返回与「{parent}」相关的条目，title 可写「{query}」。",
        )
        if parent_results:
            for item in parent_results:
                if query not in (item.get("title") or ""):
                    item["title"] = query
                    note = f"（基于「{parent}」匹配，原搜索：{query}）"
                    item["story_info"] = note + (item.get("story_info") or "")
            return parent_results[:3]

    logger.warning("search_movie no results for %r, using fallback entry", query)
    return [_fallback_movie_entry(query)]


def _fallback_movie_entry(query: str) -> dict:
    return {
        "title": query,
        "title_en": "",
        "year": "",
        "type": "剧集",
        "character_name": "",
        "story_info": (
            f"公开片库未命中「{query}」。将以此片名继续；"
            f"若为本地上传剧集，建议选「原声混剪 mode 2」并上传 SRT，比纯搜片更准确。"
        ),
        "director": "",
    }


def _parse_search_results(data: object, query: str) -> list[dict]:
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and isinstance(data.get("data"), list):
        items = data["data"]
    elif isinstance(data, dict) and data.get("title"):
        items = [data]
    else:
        items = []

    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or item.get("local_title") or "").strip()
        story = (item.get("story_info") or item.get("summary") or "").strip()
        if title or story:
            out.append(item)
    return out[:3]


async def _search_movie_llm(query: str, extra: str = "") -> list[dict]:
    system = (
        "你是中文影视数据库助手。只输出 JSON 数组，不要 markdown，不要解释。"
        "即使是不存在的续集称呼、用户自命名（如罚罪2），也要返回最相关的真实作品条目。"
        "禁止返回空数组。"
    )
    user = f"""搜索影视：{query}
{extra}

返回 1-3 条 JSON 数组，字段：
title, title_en, year, type, character_name, story_info, director

规则：
- 电视剧/短剧/续集/「片名+数字」都要给结果（如罚罪2 → 关联《罚罪》并 title 用用户搜索词）
- story_info 200字内，中文
- 至少返回 1 条，禁止 []"""

    for attempt in range(2):
        try:
            raw = await chat(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                tier="pro",
                temperature=0.2 if attempt == 0 else 0.35,
            )
            data = extract_json(raw)
            results = _parse_search_results(data, query)
            if results:
                return results
        except Exception:
            logger.exception("search_movie LLM attempt %d failed for %r", attempt + 1, query)
    return []

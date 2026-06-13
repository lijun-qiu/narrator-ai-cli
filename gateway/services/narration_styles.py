"""Resolve learning_model_id → rich style prompts (SceneFab / official template approximation)."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

STYLE_PROFILES_DIR = Path(__file__).resolve().parents[1] / "data" / "style_profiles"

# 12 大类流派 → 写作约束（近似官方 90+ 模板的 genre 维度）
GENRE_STYLE_GUIDE: dict[str, str] = {
    "热血动作": "短句有力、节奏快、强调对抗与反转；多用动词，段尾留悬念。",
    "烧脑悬疑": "层层递进、少剧透关键真相；每段抛疑问，语气克制神秘。",
    "励志成长": "温暖励志、人物弧光；困境→突破，情绪由低到高。",
    "爆笑喜剧": "口语化、反差吐槽、适度玩梗；节奏轻快，避免沉重。",
    "灾难求生": "紧张压迫感、生存抉择；环境描写简练，危机感贯穿。",
    "悬疑惊悚": "氛围渲染、细节暗示；语速中等，关键处停顿。",
    "惊悚恐怖": "低沉旁白、留白造惧；避免直白剧透，用暗示。",
    "东方奇谈": "古风/志怪语感、意境描写；人名地名保持一致。",
    "家庭伦理": "贴近生活、情感冲突；对话感强，引发共鸣。",
    "情感人生": "细腻共情、关系张力；第一人称或第三人称情感线清晰。",
    "奇幻科幻": "世界观名词统一、设定一句点明；惊奇感与逻辑并重。",
    "传奇人物": "史诗感、人物命运起伏；突出抉择与历史感。",
}

PLATFORM_GUIDE: dict[str, str] = {
    "douyin": "抖音：前3秒强钩子，单段解说 15-40 字为主，口语化，忌长难句。",
    "抖音": "抖音：前3秒强钩子，单段解说 15-40 字为主，口语化，忌长难句。",
    "bilibili": "B站：可略长句，允许梗与铺垫，信息密度中高。",
    "哔哩哔哩": "B站：可略长句，允许梗与铺垫，信息密度中高。",
    "youtube": "YouTube：开场 summary hook，英文思维的中译口语风格。",
    "xiaohongshu": "小红书：生活化、强情绪、第一人称更自然。",
    "小红书": "小红书：生活化、强情绪、第一人称更自然。",
    "kuaishou": "快手：下沉口语、直给、节奏快。",
    "快手": "快手：下沉口语、直给、节奏快。",
}


def _load_templates() -> list[dict]:
    try:
        from narrator_ai.commands.task import NARRATION_TEMPLATES

        return NARRATION_TEMPLATES
    except ImportError:
        return []


def lookup_template(learning_model_id: str) -> dict | None:
    if not learning_model_id:
        return None
    for t in _load_templates():
        if t.get("id") == learning_model_id:
            return t
    return None


def load_learned_profile(learning_model_id: str) -> dict | None:
    path = STYLE_PROFILES_DIR / f"{learning_model_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_learned_profile(learning_model_id: str, profile: dict) -> None:
    STYLE_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    path = STYLE_PROFILES_DIR / f"{learning_model_id}.json"
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")


def _perspective_guide(perspective: str, character_name: str = "") -> str:
    if perspective == "first_person":
        who = character_name or "主角"
        return f"第一人称视角，以「{who}」口吻叙述，用「我」指代该角色，保持一致。"
    return "第三人称上帝视角解说，客观叙述剧情，不用「我」。"


def build_style_prompt(
    *,
    learning_model_id: str = "",
    target_platform: str = "",
    perspective: str = "third_person",
    target_character_name: str = "",
    extra_hint: str = "",
) -> str:
    """Turn learning_model_id / platform / perspective into a writing system fragment."""
    parts: list[str] = []

    learned = load_learned_profile(learning_model_id) if learning_model_id.startswith("gateway-learn-") else None
    if learned:
        parts.append(f"【爆款学习风格】{learned.get('summary', '')}")
        if learned.get("rules"):
            parts.append("规则：" + "；".join(learned["rules"][:8]))
    else:
        tpl = lookup_template(learning_model_id)
        if tpl:
            genre = tpl.get("genre", "")
            name = tpl.get("name", "")
            sub = name.split("-")[-1].replace("解说", "") if "-" in name else name
            guide = GENRE_STYLE_GUIDE.get(genre, "专业影视解说口语化风格。")
            parts.append(f"【预置模板】{name}")
            parts.append(f"流派：{genre}（{sub}）")
            parts.append(f"文风要求：{guide}")
        elif learning_model_id and not learning_model_id.startswith("gateway-"):
            parts.append(f"模板ID：{learning_model_id}（按烧脑悬疑解说风格处理）")
            parts.append(GENRE_STYLE_GUIDE.get("烧脑悬疑", ""))

    plat = target_platform.strip()
    if plat:
        parts.append(PLATFORM_GUIDE.get(plat.lower(), PLATFORM_GUIDE.get(plat, f"平台：{plat}")))

    parts.append(_perspective_guide(perspective, target_character_name))

    if extra_hint and extra_hint not in (learning_model_id or ""):
        parts.append(extra_hint)

    return "\n".join(p for p in parts if p)

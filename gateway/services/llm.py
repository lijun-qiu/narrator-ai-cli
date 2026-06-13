"""OpenAI-compatible chat completions client."""

from __future__ import annotations

import json
import re

import httpx

from gateway.config import settings


class LLMError(Exception):
    pass


async def chat(messages: list[dict], *, temperature: float = 0.7) -> str:
    if not settings.llm_api_key:
        raise LLMError("LLM API key not configured. Set LLM_API_KEY in gateway/.env")

    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": temperature,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        if resp.status_code != 200:
            raise LLMError(f"LLM HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"Unexpected LLM response: {data}") from e


def extract_json(text: str) -> dict | list:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)

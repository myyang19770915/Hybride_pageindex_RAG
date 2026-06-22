"""Thin LLM chat helper for the eval scripts.

Reuses the project's OpenAI-compatible endpoint (LM Studio via LITELLM_BASE_URL)
with the same httpx call shape as app.services.synthesis, so generation and the
optional faithfulness judge talk to the exact model the app uses. qwen35-27b is
a reasoning model, so `chat_json` strips any pre-answer reasoning and pulls the
first balanced JSON object out of the reply.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from app.core.config import get_settings


def chat(system: str, user: str, *, temperature: float = 0.2, max_tokens: int = 1024) -> str:
    """Single-turn chat completion; returns the assistant text."""
    settings = get_settings()
    response = httpx.post(
        f"{settings.litellm_base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {settings.litellm_api_key}"},
        json={
            "model": settings.model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=settings.synthesis_timeout_seconds,
    )
    response.raise_for_status()
    # Decode as UTF-8 explicitly: LM Studio omits the charset in Content-Type, so
    # httpx's response.json() can guess the wrong codec and mangle CJK text.
    payload = json.loads(response.content.decode("utf-8"))
    message = payload["choices"][0]["message"]
    return (message.get("content") or "").strip()


def _extract_json_object(text: str) -> str | None:
    """Return the first balanced {...} block, ignoring reasoning prose or code fences."""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        start = text.find("{", start + 1)
    return None


def chat_json(system: str, user: str, *, max_tokens: int = 1024) -> dict[str, Any] | None:
    """Chat completion expected to yield a JSON object. Returns None if unparseable."""
    raw = chat(system, user, temperature=0.0, max_tokens=max_tokens)
    block = _extract_json_object(raw)
    if block is None:
        return None
    try:
        parsed = json.loads(block)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None

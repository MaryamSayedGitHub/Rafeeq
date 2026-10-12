"""One small adapter for any OpenAI-compatible chat endpoint (OpenAI, Groq, OpenRouter,
Gemini's compatible mode, a local server...).

Environment:
  LLM_API_KEY   required to use a model at all
  LLM_BASE_URL  default https://api.openai.com/v1
  LLM_MODEL     default gpt-4o-mini (must support images for vision_json)

Every function returns None when no key is set or the call fails, so callers can fall back.
"""
from __future__ import annotations

import base64
import json
import os


def configured() -> bool:
    return bool(os.environ.get("LLM_API_KEY"))


def _post(messages: list) -> dict | None:
    key = os.environ.get("LLM_API_KEY")
    if not key:
        return None
    try:
        import httpx  # imported lazily so the app boots even without it

        base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        r = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "messages": messages, "temperature": 0,
                  "response_format": {"type": "json_object"}},
            timeout=60,
        )
        r.raise_for_status()
        return json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception:
        return None


def chat_json(system: str, user: str) -> dict | None:
    return _post([{"role": "system", "content": system}, {"role": "user", "content": user}])


def vision_json(system: str, prompt: str, image_jpeg: bytes) -> dict | None:
    b64 = base64.b64encode(image_jpeg).decode()
    return _post([
        {"role": "system", "content": system},
        {"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]},
    ])

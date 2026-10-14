"""One helper for the tutor: ask the team's LLM (the provider chosen in .env, see rafeeq/teacher/lecturer/llm.py) for a JSON answer.

LLM_PROVIDER=ollama  -> Ollama over HTTP (OLLAMA_MODEL, OLLAMA_BASE_URL): JSON mode, and qwen3's "thinking" is switched off
                        so it does not use up the answer's token budget.
anything else        -> the team's get_llm() (groq / gemini / xai).
Returns None when no LLM is configured or the call fails, so every tutor route still answers (in a reduced way) without a key.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import time

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")           # also when the tutor is used without the rest of the app

log = logging.getLogger(__name__)


def _parse_json(text: str):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                return None
    return None


def _ollama(prompt: str, max_tokens: int | None) -> str:
    model = os.environ["OLLAMA_MODEL"]
    opts = {"temperature": 0.2, **({"num_predict": max_tokens, "num_ctx": 8192} if max_tokens else {})}
    url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/") + "/api/chat"
    body = {"model": model, "stream": False, "format": "json", "options": opts,
            **({"think": False} if "qwen3" in model else {}), "messages": [{"role": "user", "content": prompt}]}
    for attempt in (1, 2):                                         # Ollama answers 500 now and then while it swaps models: one retry
        r = requests.post(url, timeout=600, json=body)
        if r.status_code < 500 or attempt == 2:
            break
        time.sleep(3)
    r.raise_for_status()
    return r.json()["message"]["content"]


def _langchain(prompt: str) -> str:
    from rafeeq.teacher.lecturer.llm import get_llm                # imported late: the tutor must load without these libraries
    reply = get_llm(temperature=0.2).invoke(prompt)
    return reply.content if isinstance(reply.content, str) else "".join(str(p) for p in reply.content)


def ask_json(prompt: str, max_tokens: int | None = None) -> dict | None:
    try:
        text = _ollama(prompt, max_tokens) if os.getenv("LLM_PROVIDER", "").lower() == "ollama" else _langchain(prompt)
        out = _parse_json(text)
        return out if isinstance(out, dict) else None
    except Exception as e:                                         # noqa: BLE001  (no key, provider down, bad JSON...)
        log.warning("tutor LLM unavailable: %s: %s", type(e).__name__, str(e)[:160])
        return None

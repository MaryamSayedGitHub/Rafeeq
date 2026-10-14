"""The tutor's connection to M2 (knowledge): the three M2 routes of contracts/openapi.yaml, called exactly as agreed.

  POST /search                       {room_id, query, top_k}      -> {chunks: [{file_name, page, text, topic_id}]}
  GET  /rooms/{room_id}/topics                                    -> {topics: [{topic_id, name}]}
  GET  /sources/page?room_id&file_name&page                       -> {file_name, page, text?, image_url?}

M2_BASE_URL  default http://127.0.0.1:8000 (M2's routes live in this same app). M2_SEARCH_URL overrides the full /search URL.
Until M2's routes exist (404, connection refused, empty answer) every call falls back to the agreed sample data and says so
("sample" instead of "m2"), so the pages can show where the material came from. TUTOR_SAMPLE_FALLBACK=0 turns the fallback off.
"""
from __future__ import annotations

import logging
import os

import requests

from rafeeq.samples import load_sample

log = logging.getLogger(__name__)
TOP_K = 3                       # the tutor never sends more than 3 passages to the model
TIMEOUT = 10
_seen: dict[tuple[str, int], str] = {}      # (file_name, page) -> text of the passages already returned by M2, newest last


def _remember(chunks: list[dict]) -> None:
    for c in chunks:
        _seen[(c["file_name"], c["page"])] = c["text"]
    while len(_seen) > 500:
        _seen.pop(next(iter(_seen)))


def _base() -> str:
    return os.getenv("M2_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _fallback_on() -> bool:
    return os.getenv("TUTOR_SAMPLE_FALLBACK", "1") != "0"


def search(room_id: str, query: str, top_k: int = TOP_K, topic_id: str | None = None) -> tuple[list[dict], str]:
    """-> (chunks, source) with source "m2" | "sample" | "none". At most top_k chunks, each with its text.
    topic_id: only passages of that topic (the contract has no such field, so more passages are asked for and filtered here)."""
    top_k = max(1, min(top_k, TOP_K))
    ask = 12 if topic_id else top_k
    url = os.getenv("M2_SEARCH_URL") or _base() + "/search"

    def keep(chunks: list[dict]) -> list[dict]:
        return [c for c in chunks if c.get("text") and (not topic_id or c.get("topic_id") == topic_id)][:top_k]

    try:
        r = requests.post(url, json={"room_id": room_id, "query": query, "top_k": ask}, timeout=TIMEOUT)
        r.raise_for_status()
        chunks = keep(r.json().get("chunks", []))
        _remember(chunks)
        return chunks, "m2"                                        # empty = M2 answered "nothing matches": that is an answer, not an outage
    except Exception as e:                                         # noqa: BLE001
        log.warning("M2 /search not reachable (%s): %s", url, type(e).__name__)
    if _fallback_on():
        sample = keep(load_sample("search_material")["chunks"])
        _remember(sample)
        return sample, "sample"
    return [], "none"


def topics(room_id: str) -> tuple[list[dict], str]:
    """-> ([{topic_id, name}], source)"""
    try:
        r = requests.get(f"{_base()}/rooms/{room_id}/topics", timeout=TIMEOUT)
        r.raise_for_status()
        items = r.json().get("topics", [])
        if items:
            return items, "m2"
    except Exception as e:                                         # noqa: BLE001
        log.warning("M2 topics not reachable: %s", type(e).__name__)
    if _fallback_on():
        return load_sample("room_topics")["topics"], "sample"
    return [], "none"


def source_page(room_id: str, file_name: str, page: int) -> tuple[dict | None, str]:
    """The exact page a citation points to -> ({file_name, page, text?, image_url?}, source).
    When M2 cannot give it, the passage the tutor already received for that page is shown instead."""
    try:
        r = requests.get(f"{_base()}/sources/page", params={"room_id": room_id, "file_name": file_name, "page": page}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if data.get("text") or data.get("image_url"):
            return data, "m2"
    except Exception as e:                                         # noqa: BLE001
        log.warning("M2 /sources/page not reachable: %s", type(e).__name__)
    if (file_name, page) in _seen:
        return {"file_name": file_name, "page": page, "text": _seen[(file_name, page)]}, "passage"
    if _fallback_on():
        sample = load_sample("source_page")
        if sample["file_name"] == file_name and sample["page"] == page:
            return sample, "sample"
    return None, "none"


def status() -> dict:
    """Is M2 really there? Used by the pages to say where the material comes from."""
    try:
        r = requests.post(os.getenv("M2_SEARCH_URL") or _base() + "/search", json={"room_id": "_ping", "query": "ping", "top_k": 1}, timeout=3)
        return {"connected": r.status_code < 400, "detail": f"HTTP {r.status_code}"}
    except Exception as e:                                         # noqa: BLE001
        return {"connected": False, "detail": type(e).__name__}

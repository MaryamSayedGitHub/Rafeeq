"""Tell M4 that the student asked a question (contracts: QuestionEvent -> POST /events, 204). Best effort: it never breaks the answer.

EVENTS_URL  default http://127.0.0.1:8000/events.
Who is asking: the X-User-Id header, or the demo login token (rafeeq/platform/router.py) until real login exists. No user -> no event.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)
DEMO_TOKENS = {"demo-token-sara-123": "u_sara"}


def current_user_id(headers) -> str | None:
    if headers.get("x-user-id"):
        return headers["x-user-id"]
    token = (headers.get("authorization") or "").removeprefix("Bearer ").strip()
    if token in DEMO_TOKENS:
        return DEMO_TOKENS[token]
    try:                                                           # a real M1 login token
        from rafeeq.platform import service
        user = service.get_store().user_for_token(token) if token else None
        return user["user_id"] if user else None
    except Exception:                                              # noqa: BLE001
        return None


def post_event(event: dict) -> bool:
    """POST a QuestionEvent (already built) to M4. Best effort."""
    try:
        requests.post(os.getenv("EVENTS_URL", "http://127.0.0.1:8000/events"), json=event, timeout=5).raise_for_status()
        return True
    except Exception as e:                                         # noqa: BLE001
        log.warning("M4 /events not reachable: %s", type(e).__name__)
        return False


def send_question_event(user_id: str | None, room_id: str, topic_id: str | None, text: str, kind: str = "question") -> bool:
    """kind "question" when the student asks, "understood" when they finish a solution or pass a quiz (the contract's proposal 4)."""
    if not user_id:
        return False
    return post_event({"user_id": user_id, "room_id": room_id, "topic_id": topic_id or "other", "kind": kind, "text": text,
                       "time": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")})

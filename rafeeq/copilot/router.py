"""Decides which capability handles a student message."""
from __future__ import annotations

from rafeeq.copilot.llm import chat_json

ROUTES = ["ask", "quiz", "check_work", "plan", "clarify"]
MODES = ["auto", "ask", "check_work"]

SYSTEM = (
    "You route a student's message in a study app. Reply with JSON {\"route\": X}. "
    "ask = a question about the course material, or a request to explain something. "
    "quiz = wants practice questions. "
    "check_work = wants their attached photo of solved work checked. "
    "plan = asks about deadlines, a schedule or what to study next. "
    "clarify = too vague to act on. The message may be Arabic or English."
)

_CHECK = ("check", "correct", "my answer", "my solution", "صحح", "صحّح", "راجع حل", "حلي", "حلّي")
_QUIZ = ("quiz", "test me", "practice", "اختبار", "اختبرني", "أسئلة تدريب", "تمرين")
_PLAN = ("plan", "schedule", "deadline", "what next", "خطة", "خطّة", "جدول", "موعد", "أذاكر إيه")


def rules(text: str, has_file: bool) -> str:
    t = (text or "").lower().strip()
    if has_file and any(w in t for w in _CHECK):
        return "check_work"
    if any(w in t for w in _QUIZ):
        return "quiz"
    if any(w in t for w in _PLAN):
        return "plan"
    if len(t.split()) < 2 and not has_file:
        return "clarify"
    return "ask"


def classify(text: str, has_file: bool, history: list, mode: str = "auto") -> str:
    # The student's explicit choice in the UI ("check my solution" vs "explain this") wins.
    if mode in ("ask", "check_work"):
        return mode
    last = " | ".join(m["text"] for m in history[-4:])
    out = chat_json(SYSTEM, f"Recent: {last}\nPhoto attached: {has_file}\nMessage: {text}")
    if out and out.get("route") in ROUTES:
        return out["route"]
    return rules(text, has_file)

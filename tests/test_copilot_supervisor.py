"""The Copilot's routing and honesty rules (no LLM key needed: the rule fallback is used)."""
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from rafeeq.copilot import clients
from rafeeq.copilot.router import rules
from rafeeq.copilot.supervisor import clear_history, handle_message

SPEC = yaml.safe_load((Path(__file__).resolve().parent.parent / "contracts" / "openapi.yaml").read_text(encoding="utf-8"))


def assert_reply_schema(reply):
    schema = {"$ref": "#/components/schemas/CopilotReply", "components": SPEC["components"]}
    assert not list(Draft202012Validator(schema).iter_errors(reply))


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("RAFEEQ_ALLOW_SAMPLES", raising=False)
    for name in ("tutor_answer", "check_work", "make_quiz", "next_step", "find_verified", "escalate", "record_event"):
        clients.disconnect(name)
    clear_history()
    yield
    for name in ("tutor_answer", "check_work", "make_quiz", "next_step", "find_verified", "escalate", "record_event"):
        clients.disconnect(name)


@pytest.mark.parametrize("text,has_file,route", [
    ("Explain Newton's third law", False, "ask"),
    ("اشرح لي قانون نيوتن الثالث", False, "ask"),
    ("اختبرني في الوراثة", False, "quiz"),
    ("what's my plan for this week", False, "plan"),
    ("ok", False, "clarify"),
    ("صحح حلي", True, "check_work"),
])
def test_rule_routing(text, has_file, route):
    assert rules(text, has_file) == route


def test_explicit_mode_wins_over_classification():
    out = handle_message("r_1", "ما هذا؟", file_id="snap_1", mode="check_work")
    assert out["route"] == "check_work"
    assert_reply_schema(out)


def test_unconnected_services_are_marked_as_samples():
    out = handle_message("r_1", "Explain Newton's third law")
    assert out["route"] == "ask"
    assert out["payload"]["sample"] is True
    assert_reply_schema(out)


def test_samples_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("RAFEEQ_ALLOW_SAMPLES", "0")
    out = handle_message("r_1", "Explain Newton's third law")
    assert out["payload"] == {"unavailable": True}


def test_live_answer_has_no_sample_flag_and_records_an_event():
    events = []
    clients.connect("tutor_answer", lambda room, q: {"answer": "A", "citations": [], "grounded": True,
                                                     "steps": [], "topic_id": "t1"})
    clients.connect("record_event", events.append)
    out = handle_message("r_1", "Explain Newton's third law", user_id="u_1")
    assert "sample" not in out["payload"]
    assert events and events[0]["topic_id"] == "t1" and events[0]["user_id"] == "u_1"


def test_ungrounded_answer_is_not_claimed_as_escalated_without_a_ticket():
    clients.connect("tutor_answer", lambda room, q: {"answer": "", "citations": [], "grounded": False, "steps": []})
    out = handle_message("r_1", "a very hard exam question")
    assert out["payload"]["escalated"] is False
    clients.connect("escalate", lambda room, q, user: {"question_id": "q_9"})
    out = handle_message("r_1", "a very hard exam question")
    assert out["payload"]["escalated"] is True and out["payload"]["question_id"] == "q_9"


def test_check_work_without_photo_asks_for_one():
    out = handle_message("r_1", "check my answer", mode="check_work")
    assert out["payload"] == {"needs_photo": True}


def test_history_is_per_student():
    handle_message("r_1", "Explain cells", user_id="u_a")
    from rafeeq.copilot.supervisor import _HISTORY
    assert ("r_1", "u_a") in _HISTORY and ("r_1", "u_b") not in _HISTORY

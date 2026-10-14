"""What the student does with the tutor moves the Progress page (M4's profile): questions count, a finished quiz and a checked solution give a result."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from rafeeq.copilot import clients
from rafeeq.quiz.profile import db as m4_db
from rafeeq.quiz.profile import service as profile_service
from rafeeq.quiz.profile.models import Base
from rafeeq.tutor import events


@pytest.fixture
def m4(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'm4.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(m4_db, "_engine", engine)
    return engine


def topic(engine, user="u1", room="r1"):
    with Session(engine) as s:
        return {t.topic_id: t for t in profile_service.get_profile(s, user, room).topics}


def test_a_finished_quiz_moves_the_topic_mastery(m4):
    assert events.record_quiz("u1", "r1", "t_cell", 1, 3)
    low = topic(m4)["t_cell"].mastery
    assert events.record_quiz("u1", "r1", "t_cell", 3, 3)
    assert topic(m4)["t_cell"].mastery > low and topic(m4)["t_cell"].attempts == 2


def test_a_checked_solution_counts_by_its_right_steps(m4):
    assert events.record_handwriting("u1", "r1", "t_algebra", 2, 3)
    assert topic(m4)["t_algebra"].attempts == 1


def test_no_student_or_no_topic_records_nothing(m4):
    assert not events.record_quiz(None, "r1", "t_cell", 1, 3)
    assert not events.record_quiz("u1", "r1", "other", 1, 3)
    assert not events.record_quiz("u1", "r1", "", 1, 3)
    assert not events.record_quiz("u1", "r1", "t_cell", 0, 0)
    assert topic(m4) == {}


def test_a_question_reaches_m4_through_the_copilot_hook_in_the_same_app(monkeypatch):
    got = []
    monkeypatch.setattr(clients, "is_connected", lambda name: name == "record_event")
    monkeypatch.setattr(clients, "optional", lambda name, *a: got.append((name, a[0])))
    monkeypatch.setattr(events.requests, "post", lambda *a, **k: pytest.fail("no HTTP to ourselves"))
    assert events.send_question_event("u1", "r1", "t_cell", "what is a cell?")
    assert got[0][0] == "record_event" and got[0][1]["topic_id"] == "t_cell"

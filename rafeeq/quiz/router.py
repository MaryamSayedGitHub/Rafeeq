"""M4 routes, exactly as the team contract (contracts/openapi.yaml) defines them.

    POST /quiz                  make a quiz           -> Quiz
    POST /quiz/{quiz_id}/submit send answers          -> QuizResult
    GET  /next-step?room_id=    what to do next       -> NextStep
    GET  /profile/summary?room_id=  weak topics       -> StudentSummary
    POST /events                a question was asked  -> 204

M4's own routes in api.py (paper sheet, grade a photo, class profile, wrong answers,
record_event) are included too, except /rooms/{room_id}/topics, which belongs to M2.

M1 connects this with one line in main.py:

    from rafeeq.quiz.router import install
    install(app)

install() also swaps M4's stand-in current_user_id for the real login (Bearer token).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from rafeeq.quiz import adapters
from rafeeq.quiz import api as m4_api
from rafeeq.quiz.contracts import QuizCreateResponse
from rafeeq.quiz.deps import current_user_id, get_approved_items, get_chunks, get_llm, get_verifier
from rafeeq.quiz.profile import service as profile_service
from rafeeq.quiz.profile.db import get_session
from rafeeq.quiz.quiz import service as quiz_service
from rafeeq.quiz.quiz.models import QuizRow

router = APIRouter(tags=["M4 quiz and profile"])


# ---------- request bodies (the contract's shapes) ----------
class MakeQuizBody(BaseModel):
    room_id: str
    topic_id: Optional[str] = None  # empty or missing = a mix of the room's topics
    count: int = Field(default=5, ge=1, le=20)


class SubmitBody(BaseModel):
    answers: list[str]  # one answer text per question, in the same order as the quiz


def _topic_names(chunks) -> dict[str, str]:
    return {c["topic_id"]: (c.get("topic_name") or c["topic_id"]) for c in chunks}


# ---------- POST /quiz ----------
@router.post("/quiz")
def make_quiz(
    body: MakeQuizBody,
    session: Session = Depends(get_session),
    user_id: str = Depends(current_user_id),
    llm=Depends(get_llm),
    chunks=Depends(get_chunks),
    approved=Depends(get_approved_items),
    verifier=Depends(get_verifier),
) -> dict:
    topic_id = (body.topic_id or "").strip() or None
    try:
        made = quiz_service.create_quiz(
            session,
            user_id=user_id,
            room_id=body.room_id,
            n=body.count,
            mode="screen",
            llm=llm,
            chunks=chunks,
            approved_items=approved,
            topic_id=topic_id,
            verifier=verifier,
        )
    except quiz_service.TopicNotFound:
        raise HTTPException(status_code=404, detail="topic not found in this course")
    except quiz_service.QuizGenerationError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return adapters.to_contract_quiz(QuizCreateResponse.model_validate(made), topic_id)


# ---------- POST /quiz/{quiz_id}/submit ----------
@router.post("/quiz/{quiz_id}/submit")
def submit_quiz(
    quiz_id: str,
    body: SubmitBody,
    session: Session = Depends(get_session),
    user_id: str = Depends(current_user_id),
) -> dict:
    try:
        items = quiz_service.get_quiz_items(session, quiz_id=quiz_id, user_id=user_id)
    except quiz_service.QuizNotFound:
        raise HTTPException(status_code=404, detail="quiz not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="this quiz belongs to another student")

    room_id = session.get(QuizRow, quiz_id).room_id
    before = profile_service.get_profile(session, user_id, room_id)
    try:
        result = quiz_service.submit_quiz(
            session,
            quiz_id=quiz_id,
            user_id=user_id,
            answers=adapters.answers_to_choices(items, body.answers),
        )
    except quiz_service.AlreadySubmitted:
        raise HTTPException(status_code=409, detail="this quiz was already submitted")
    after = profile_service.get_profile(session, user_id, room_id)
    return adapters.to_contract_result(items, result, before, after)


# ---------- GET /profile/summary ----------
@router.get("/profile/summary")
def profile_summary(
    room_id: str = Query(...),
    session: Session = Depends(get_session),
    user_id: str = Depends(current_user_id),
) -> dict:
    return adapters.to_student_summary(profile_service.get_profile(session, user_id, room_id))


# ---------- GET /next-step ----------
@router.get("/next-step")
def next_step(
    room_id: str = Query(...),
    session: Session = Depends(get_session),
    user_id: str = Depends(current_user_id),
    chunks=Depends(get_chunks),
) -> dict:
    names = _topic_names(chunks)
    profile = profile_service.get_profile(session, user_id, room_id, names)
    topic = adapters.pick_next_topic(profile)
    if topic is not None:
        return adapters.next_step(topic)
    if names:  # a new student: start with the first topic of the course
        first = next(iter(names))
        return adapters.first_topic_step(first, names[first])
    raise HTTPException(status_code=404, detail="no topics in this room yet")


# ---------- POST /events ----------
@router.post("/events", status_code=204)
def record_question_event(
    body: adapters.QuestionEvent, session: Session = Depends(get_session)
) -> Response:
    event = adapters.question_event_to_event(body)
    if event is not None:
        profile_service.record_event(session, event)
    return Response(status_code=204)


# ---------- M4's own extra routes (paper sheet, class data) ----------
_M2_OWNS = {"/rooms/{room_id}/topics"}
_extras = APIRouter()
_extras.routes.extend(r for r in m4_api.router.routes if getattr(r, "path", None) not in _M2_OWNS)
router.include_router(_extras)


# ---------- connecting to M1's login ----------
def bearer_user_id(authorization: Optional[str] = Header(default=None)) -> str:
    """The logged-in student, from M1's Bearer token."""
    from rafeeq.platform import service as platform

    token = platform.token_from_header(authorization)
    user = platform.get_store().user_for_token(token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="Log in first")
    return user["user_id"]


def install(app) -> None:
    """One call from main.py: mount the routes and use the real login."""
    app.dependency_overrides[current_user_id] = bearer_user_id
    app.include_router(router)

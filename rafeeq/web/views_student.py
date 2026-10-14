"""Student workspace inside a room: Ask Rafeeq (Copilot + photo), Practice, Progress.

Materials and the source viewer are shared with teachers and live here too.
"""
from __future__ import annotations

from urllib.parse import quote

from starlette.requests import Request

from rafeeq.web import api as A
from rafeeq.web.common import api, api_message, check_csrf, flash, notice, redirect, render, tr
from rafeeq.web.i18n import strip_isolates
from rafeeq.web.views_rooms import ensure_session, gather, load_room, topic_names

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
MAX_BYTES = 25 * 1024 * 1024


def too_large(request: Request) -> bool:
    """Reject before the multipart body is parsed (and spooled to disk)."""
    try:
        return int(request.headers.get("content-length", "0")) > MAX_BYTES + 1024 * 1024
    except ValueError:
        return False


# ---------------------------------------------------------------- Ask Rafeeq

async def study_page(request: Request):
    user, room, rooms = await load_room(request, request.path_params["room_id"], "student")
    inbox_res = await api(request).get(f"/rooms/{room['room_id']}/inbox", token=user["token"])
    my_questions = inbox_res.data.get("questions", [])[:6] if inbox_res.ok else []
    return render(request, "room/study.html", room=room, rooms=rooms, tab="study", my_questions=my_questions,
                  prefill=strip_isolates(request.query_params.get("q", ""))[:500])


async def study_message(request: Request):
    user, room, _ = await load_room(request, request.path_params["room_id"], "student")
    form = await check_csrf(request)
    mode = str(form.get("mode", "auto"))
    mode = mode if mode in ("auto", "ask", "check_work") else "auto"
    file_id = str(form.get("file_id", "")).strip() or None
    text = strip_isolates(str(form.get("text", ""))).strip()
    question = strip_isolates(str(form.get("question", ""))).strip()

    if file_id and mode == "ask":
        shown = question or tr(request, "snap.default_question")
        text = f"{shown}\n\n{text}" if text else shown
    elif file_id and mode == "check_work":
        shown = tr(request, "snap.check")
    else:
        shown = text
    if not text:
        return notice(request, tr(request, "error.empty_question"), "warning")

    body = {"room_id": room["room_id"], "text": text[:4000], "mode": mode}
    if file_id:
        body["file_id"] = file_id
    res = await api(request).post("/copilot/message", token=user["token"], json=body, timeout=120)
    ensure_session(request, res)
    names: dict = {}
    if res.ok and res.data.get("route") in ("quiz", "plan"):
        _, names = await topic_names(request, user, room["room_id"])
    return render(request, "partials/chat_turn.html", room=room, shown=shown, file_id=file_id, res=res,
                  reply=res.data if res.ok else None, topic_names=names,
                  error=None if res.ok else api_message(request, res))


async def study_photo(request: Request):
    user, room, _ = await load_room(request, request.path_params["room_id"], "student")
    if too_large(request):
        return notice(request, tr(request, "materials.too_big"), "warning")
    form = await check_csrf(request)
    photo = form.get("photo")
    if photo is None or not getattr(photo, "filename", ""):
        return notice(request, tr(request, "snap.choose_file"), "warning")
    if (photo.content_type or "").lower() not in IMAGE_TYPES:
        return notice(request, tr(request, "snap.not_image"), "warning")
    data = await photo.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        return notice(request, tr(request, "materials.too_big"), "warning")
    res = await api(request).post("/snap", token=user["token"], data={"room_id": room["room_id"]},
                                  files={"photo": (photo.filename, data, photo.content_type)}, timeout=90)
    ensure_session(request, res)
    if not res.ok:
        key = "snap.not_image" if res.kind == A.INVALID else "snap.reader_unavailable" if res.kind == A.UNAVAILABLE else None
        return notice(request, tr(request, key) if key else api_message(request, res), "warning")
    return render(request, "partials/snap_card.html", room=room, snap=res.data)


# ---------------------------------------------------------------- materials (shared)

async def _materials_data(request: Request, user: dict, room_id: str):
    files_res, (topics_res, _) = await gather(
        api(request).get(f"/rooms/{room_id}/files", token=user["token"]),
        topic_names(request, user, room_id),
    )
    ensure_session(request, files_res)
    return files_res, topics_res


async def materials_page(request: Request):
    user, room, rooms = await load_room(request, request.path_params["room_id"])
    files_res, topics_res = await _materials_data(request, user, room["room_id"])
    return render(request, "room/materials.html", room=room, rooms=rooms, tab="materials",
                  files_res=files_res, topics_res=topics_res)


async def materials_table(request: Request):
    user, room, _ = await load_room(request, request.path_params["room_id"])
    files_res = await api(request).get(f"/rooms/{room['room_id']}/files", token=user["token"])
    ensure_session(request, files_res)
    return render(request, "partials/files_table.html", room=room, files_res=files_res)


async def materials_upload(request: Request):
    user, room, _ = await load_room(request, request.path_params["room_id"], "teacher")
    if too_large(request):
        flash(request, "warning", tr(request, "materials.too_big"))
        return redirect(request, f"/rooms/{room['room_id']}/materials")
    form = await check_csrf(request)
    upload = form.get("file")
    if upload is None or not getattr(upload, "filename", ""):
        flash(request, "warning", tr(request, "materials.no_file"))
        return redirect(request, f"/rooms/{room['room_id']}/materials")
    data = await upload.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        flash(request, "warning", tr(request, "materials.too_big"))
        return redirect(request, f"/rooms/{room['room_id']}/materials")
    res = await api(request).post(f"/rooms/{room['room_id']}/files", token=user["token"],
                                  files={"file": (upload.filename, data, upload.content_type or "application/octet-stream")},
                                  timeout=120)
    ensure_session(request, res)
    if res.ok:
        flash(request, "success", tr(request, "materials.uploaded", name=upload.filename))
    else:
        flash(request, "error", api_message(request, res))
    return redirect(request, f"/rooms/{room['room_id']}/materials")


async def materials_delete(request: Request):
    user, room, _ = await load_room(request, request.path_params["room_id"], "teacher")
    await check_csrf(request)
    file_id = request.path_params["file_id"]
    res = await api(request).delete(f"/rooms/{room['room_id']}/files/{quote(file_id, safe='')}", token=user["token"])
    ensure_session(request, res)
    if res.ok:
        flash(request, "success", tr(request, "materials.deleted"))
    else:
        flash(request, "error", api_message(request, res))
    return redirect(request, f"/rooms/{room['room_id']}/materials")


async def source_page(request: Request):
    user, room, rooms = await load_room(request, request.path_params["room_id"])
    file_name = request.query_params.get("file_name", "")
    try:
        page = max(1, int(request.query_params.get("page", "1")))
    except ValueError:
        page = 1
    # The contract declares room_id here with the path parameter component but the path has no
    # {room_id}; it is sent as a query parameter (see docs/frontend/HANDOFF.md, contract issues).
    res = await api(request).get("/sources/page", token=user["token"],
                                 params={"room_id": room["room_id"], "file_name": file_name, "page": page})
    ensure_session(request, res)
    back = f"/rooms/{room['room_id']}/" + ("study" if user["role"] == "student" else "materials")
    return render(request, "room/source.html", room=room, rooms=rooms, tab="materials", res=res,
                  file_name=file_name, page=page, back=back)


# ---------------------------------------------------------------- practice

async def practice_page(request: Request):
    user, room, rooms = await load_room(request, request.path_params["room_id"], "student")
    topics_res, _ = await topic_names(request, user, room["room_id"])
    return render(request, "room/practice.html", room=room, rooms=rooms, tab="practice", topics_res=topics_res,
                  selected=request.query_params.get("topic", ""))


async def practice_quiz(request: Request):
    user, room, _ = await load_room(request, request.path_params["room_id"], "student")
    form = await check_csrf(request)
    topic_id = str(form.get("topic_id", "")).strip()
    try:
        count = min(10, max(3, int(form.get("count", 5))))
    except ValueError:
        count = 5
    res = await api(request).post("/quiz", token=user["token"], timeout=120,
                                  json={"room_id": room["room_id"], "topic_id": topic_id, "count": count})
    ensure_session(request, res)
    if not res.ok:
        return notice(request, api_message(request, res), "warning")
    return render(request, "partials/quiz_form.html", room=room, quiz=res.data)


async def practice_submit(request: Request):
    user, room, _ = await load_room(request, request.path_params["room_id"], "student")
    form = await check_csrf(request)
    quiz_id = str(form.get("quiz_id", ""))
    try:
        n = min(20, max(1, int(form.get("n", 0))))
    except ValueError:
        return notice(request, tr(request, "err.generic"), "warning")
    answers = [str(form.get(f"a_{i}", "")) for i in range(n)]
    questions = [str(form.get(f"q_{i}", "")) for i in range(n)]
    if any(not a for a in answers):
        return notice(request, tr(request, "practice.answer_all"), "warning")
    res, (_, names) = await gather(
        api(request).post(f"/quiz/{quiz_id}/submit", token=user["token"], json={"answers": answers}),
        topic_names(request, user, room["room_id"]),
    )
    ensure_session(request, res)
    if not res.ok:
        return notice(request, api_message(request, res), "warning")
    rows = [{"q": q, "a": a, "e": e} for q, a, e in zip(questions, answers, res.data.get("explanations", []) + [""] * n)]
    return render(request, "partials/quiz_result.html", room=room, result=res.data, rows=rows,
                  topic_names=names, topic_id=str(form.get("topic_id", "")))


# ---------------------------------------------------------------- progress

async def progress_page(request: Request):
    user, room, rooms = await load_room(request, request.path_params["room_id"], "student")
    params = {"room_id": room["room_id"]}
    summary_res, next_res, (topics_res, names) = await gather(
        api(request).get("/profile/summary", token=user["token"], params=params),
        api(request).get("/next-step", token=user["token"], params=params),
        topic_names(request, user, room["room_id"]),
    )
    return render(request, "room/progress.html", room=room, rooms=rooms, tab="progress",
                  summary_res=summary_res, next_res=next_res, topic_names=names)


"""The web UI as a Starlette app, mounted inside the FastAPI app (see rafeeq/web/__init__.py)."""
from __future__ import annotations

import os
import secrets
import warnings
from typing import Any

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from rafeeq.web import views_auth as auth
from rafeeq.web import views_rooms as rooms
from rafeeq.web import views_student as student
from rafeeq.web import views_teacher as teacher
from rafeeq.web.api import Api
from rafeeq.web.common import HERE, Redirect, is_htmx, notice, render, tr


def _routes() -> list:
    R = Route
    room = "/rooms/{room_id}"
    return [
        R("/", auth.home),
        R("/login", auth.login_page, methods=["GET"]),
        R("/login", auth.login_submit, methods=["POST"]),
        R("/register", auth.register_page, methods=["GET"]),
        R("/register", auth.register_submit, methods=["POST"]),
        R("/logout", auth.logout, methods=["POST"]),
        R("/lang/{code}", auth.set_language, methods=["GET"]),
        R("/rooms", rooms.rooms_index, methods=["GET"]),
        R("/rooms/join", rooms.rooms_join, methods=["POST"]),
        R("/rooms/create", rooms.rooms_create, methods=["POST"]),
        R(room, rooms.room_home, methods=["GET"]),
        # student
        R(room + "/study", student.study_page, methods=["GET"]),
        R(room + "/study/message", student.study_message, methods=["POST"]),
        R(room + "/study/photo", student.study_photo, methods=["POST"]),
        R(room + "/practice", student.practice_page, methods=["GET"]),
        R(room + "/practice/quiz", student.practice_quiz, methods=["POST"]),
        R(room + "/practice/submit", student.practice_submit, methods=["POST"]),
        R(room + "/progress", student.progress_page, methods=["GET"]),
        # shared
        R(room + "/materials", student.materials_page, methods=["GET"]),
        R(room + "/materials/table", student.materials_table, methods=["GET"]),
        R(room + "/materials/upload", student.materials_upload, methods=["POST"]),
        R(room + "/source", student.source_page, methods=["GET"]),
        # teacher
        R(room + "/overview", teacher.overview_page, methods=["GET"]),
        R(room + "/students", teacher.students_page, methods=["GET"]),
        R(room + "/students/draft", teacher.students_draft, methods=["POST"]),
        R(room + "/insights", teacher.insights_page, methods=["GET"]),
        R(room + "/studio", teacher.studio_page, methods=["GET"]),
        R(room + "/studio/sessions", teacher.studio_generate, methods=["POST"]),
        R(room + "/studio/sessions/{session_id}", teacher.session_page, methods=["GET"]),
        R(room + "/studio/sessions/{session_id}/decision", teacher.session_decision, methods=["POST"]),
        R(room + "/studio/sessions/{session_id}/files/{name:path}", teacher.session_file, methods=["GET"]),
        R("/profile", teacher.profile_page, methods=["GET"]),
        R("/profile", teacher.profile_save, methods=["POST"]),
        Mount("/static", app=StaticFiles(directory=str(HERE / "static")), name="static"),
    ]


async def _on_redirect(request: Request, exc: Redirect) -> Response:
    if is_htmx(request):
        return Response(status_code=200, headers={"HX-Redirect": exc.url})
    return RedirectResponse(exc.url, status_code=303)


async def _on_http_error(request: Request, exc: HTTPException) -> Response:
    if exc.status_code == 403 and exc.detail == "csrf":
        if is_htmx(request):
            return notice(request, tr(request, "err.csrf"), "warning")
        return render(request, "error.html", status=403, code=403, message=tr(request, "err.csrf"))
    messages = {403: "err.forbidden", 404: "err.notfound"}
    message = tr(request, messages[exc.status_code]) if exc.status_code in messages else (
        exc.detail if isinstance(exc.detail, str) and exc.status_code == 502 else tr(request, "err.generic"))
    if is_htmx(request):
        return notice(request, message, "warning")
    return render(request, "error.html", status=exc.status_code, code=exc.status_code, message=message)


class SecurityHeaders:
    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers += [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"same-origin"),
                            (b"x-frame-options", b"DENY")]
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


def create_web_app(api_app: Any = None, api_base: str | None = None, secret: str | None = None,
                   demo_accounts: bool | None = None) -> Starlette:
    secret = secret or os.environ.get("RAFEEQ_WEB_SECRET")
    if not secret:
        warnings.warn("RAFEEQ_WEB_SECRET is not set: using a random key, sessions end on restart.")
        secret = secrets.token_urlsafe(32)
    app = Starlette(
        routes=_routes(),
        middleware=[
            Middleware(SecurityHeaders),
            Middleware(SessionMiddleware, secret_key=secret, session_cookie="rafeeq_session", same_site="lax",
                       https_only=os.environ.get("RAFEEQ_HTTPS_ONLY", "0") == "1", max_age=14 * 24 * 3600),
        ],
        exception_handlers={Redirect: _on_redirect, HTTPException: _on_http_error},
    )
    app.state.api = Api(app=api_app, base_url=api_base)
    if demo_accounts is None:
        demo_accounts = os.environ.get("RAFEEQ_DEMO_ACCOUNTS", "1") != "0"
    app.state.demo_accounts = demo_accounts
    return app


__all__ = ["create_web_app"]

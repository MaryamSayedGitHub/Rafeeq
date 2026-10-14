import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from rafeeq.knowledge.integration import install as install_knowledge
from rafeeq.platform.router import router as platform_router
from rafeeq.quiz.router import install as install_quiz
from rafeeq.teacher.routes import router as teacher_router
from rafeeq.tutor.connect import connect_m3
from rafeeq.tutor.identity import IdentityMiddleware
from rafeeq.tutor.rooms_api import router as rooms_api_router
from rafeeq.tutor.router import router as tutor_router
from rafeeq.teacher.studio_routes import router as studio_router
from rafeeq.teacher.service import open_teacher_service

WEB = Path(__file__).parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # M5: the lecturer assistant (graph + Postgres memory). Starts without an LLM key.
    with open_teacher_service() as teacher:
        app.state.teacher = teacher
        demo_room = os.environ.get("RAFEEQ_DEMO_ROOM", "").strip()
        if demo_room:  # demo data for one room, once (rafeeq/demo_seed.py)
            from rafeeq.demo_seed import seed

            seed(demo_room, teacher.store)
        yield


app = FastAPI(title="Rafeeq", lifespan=lifespan)
app.add_middleware(IdentityMiddleware)   # M3: who is asking (the Copilot's hook has no user)
app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")

app.include_router(platform_router)
app.include_router(teacher_router)
app.include_router(tutor_router)
app.include_router(rooms_api_router)     # M3: /rooms/{id}/ask, /vision/check-work, /questions, /instructor/questions
app.include_router(studio_router)
install_quiz(app)  # M4: /quiz, /quiz/{id}/submit, /next-step, /profile/summary, /events (real login)
install_knowledge(app)  # M2: real /search, topics, sources and PDF indexing when RAFEEQ_KNOWLEDGE=1

connect_m3()                             # the Copilot (M1) uses M3's answer, photo reader, work checker and the M4 event hook

from rafeeq.web import install
install(app)                             # M1 UI at /app; "/" redirects there


@app.get("/health")
def health():
    return {"status": "ok"}

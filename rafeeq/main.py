import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from rafeeq.knowledge import indexer as knowledge_indexer
from rafeeq.knowledge.router import router as knowledge_router
from rafeeq.platform.router import router as platform_router
from rafeeq.teacher.routes import router as teacher_router
from rafeeq.tutor.connect import connect_m3
from rafeeq.tutor.identity import IdentityMiddleware
from rafeeq.tutor.rooms_api import router as rooms_api_router
from rafeeq.tutor.router import router as tutor_router
from rafeeq.teacher.service import open_teacher_service

WEB = Path(__file__).parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # M5: the lecturer assistant (graph + Postgres memory). Starts without an LLM key.
    threading.Thread(target=knowledge_indexer.reindex_pending, daemon=True).start()     # files uploaded before the index existed
    with open_teacher_service() as teacher:
        app.state.teacher = teacher
        yield


app = FastAPI(title="Rafeeq", lifespan=lifespan)
app.add_middleware(IdentityMiddleware)   # M3: who is asking (the Copilot's hook has no user)
app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")

app.include_router(platform_router)
app.include_router(knowledge_router)   # M2 stand-in: /search, /rooms/{id}/topics, /sources/page (local index of the uploaded files)
app.include_router(teacher_router)
app.include_router(tutor_router)
app.include_router(rooms_api_router)     # M3: /rooms/{id}/ask, /vision/check-work, /questions, /instructor/questions

knowledge_indexer.install()              # every uploaded file is read and indexed
connect_m3()                             # the Copilot (M1) uses M3's answer, photo reader, work checker and the M4 event hook

from rafeeq.web import install
install(app)                             # M1 UI at /app; "/" redirects there


@app.get("/health")
def health():
    return {"status": "ok"}

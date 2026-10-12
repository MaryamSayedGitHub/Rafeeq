from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from rafeeq.platform.router import router as platform_router
from rafeeq.teacher.routes import router as teacher_router
from rafeeq.teacher.service import open_teacher_service
from rafeeq.web.nav import NAV

WEB = Path(__file__).parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # M5: the lecturer assistant (graph + Postgres memory). Starts without an LLM key.
    with open_teacher_service() as teacher:
        app.state.teacher = teacher
        yield


app = FastAPI(title="Rafeeq", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")
templates = Jinja2Templates(directory=WEB / "templates")

app.include_router(platform_router)
app.include_router(teacher_router)

from rafeeq.web import install
install(app)

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "home.html", {"nav": NAV, "active": "home"})


@app.get("/health")
def health():
    return {"status": "ok"}

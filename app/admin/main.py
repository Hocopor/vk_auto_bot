import logging

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.admin.auth import router as auth_router
from app.admin.deps import NotAuthenticated, require_login
from app.admin.routes.events import router as events_router
from app.admin.routes.moderation import router as moderation_router
from app.admin.routes.participants import router as participants_router
from app.admin.routes.winners import router as winners_router
from app.core.config import settings
from fastapi import Depends

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Розыгрыш — админка")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)
app.mount("/static", StaticFiles(directory="app/admin/static"), name="static")
templates = Jinja2Templates(directory="app/admin/templates")

app.include_router(auth_router)
app.include_router(events_router)
app.include_router(moderation_router)
app.include_router(participants_router)
app.include_router(winners_router)


@app.exception_handler(NotAuthenticated)
async def _not_auth_handler(request: Request, exc: NotAuthenticated):
    return RedirectResponse(url="/login", status_code=303)


@app.get("/")
async def index(request: Request, user: str = Depends(require_login)):
    return templates.TemplateResponse("index.html", {"request": request, "user": user})

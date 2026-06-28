import logging

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.admin.auth import router as auth_router
from app.admin.deps import NotAuthenticated, require_login
from app.admin.routes.events import router as events_router
from app.admin.routes.moderation import router as moderation_router
from app.admin.routes.participants import router as participants_router
from app.admin.routes.public import router as public_router
from app.admin.routes.settings import router as settings_router
from app.admin.routes.winners import router as winners_router
from app.admin.security import SecurityHeadersMiddleware
from app.admin.templating import templates, refresh_settings_cache
from app.core.config import settings
from app.core.services import app_settings as s
from fastapi import Depends

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Админка", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    max_age=7 * 24 * 3600,  # сессия живёт 7 дней
    same_site="lax",  # cookie не уходит при cross-site POST → базовая защита от CSRF
    https_only=True,  # админка только по HTTPS (Caddy :443, tls internal) → cookie с флагом Secure
)
app.mount("/static", StaticFiles(directory="app/admin/static"), name="static")

app.include_router(auth_router)
app.include_router(events_router)
app.include_router(moderation_router)
app.include_router(participants_router)
app.include_router(winners_router)
app.include_router(settings_router)
app.include_router(public_router)


@app.exception_handler(NotAuthenticated)
async def _not_auth_handler(request: Request, exc: NotAuthenticated):
    return RedirectResponse(url="/login", status_code=303)


@app.on_event("startup")
async def _load_settings_cache():
    from app.core.db import async_session_maker
    async with async_session_maker() as session:
        title = await s.get_setting(session, s.KEY_ADMIN_TITLE) or "Админка"
        winners = (await s.get_setting(session, s.KEY_WINNERS_TAB_ENABLED)) != "false"
        refresh_settings_cache(title, winners)


@app.get("/")
async def index(request: Request, user: str = Depends(require_login)):
    return templates.TemplateResponse("index.html", {"request": request, "user": user})

import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from passlib.context import CryptContext

from app.admin.templating import templates
from app.core.config import settings

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

router = APIRouter()


def verify_credentials(login: str, password: str) -> bool:
    """Проверка логина и пароля против .env (ADMIN_LOGIN + ADMIN_PASSWORD_HASH)."""
    if login != settings.admin_login:
        return False
    if not settings.admin_password_hash:
        return False
    try:
        return pwd_context.verify(password, settings.admin_password_hash)
    except Exception:
        logger.exception("Password verification error")
        return False


@router.get("/login")
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login")
async def login_submit(request: Request, login: str = Form(...), password: str = Form(...)):
    if verify_credentials(login, password):
        request.session["user"] = login
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Неверный логин или пароль"},
        status_code=401,
    )


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)

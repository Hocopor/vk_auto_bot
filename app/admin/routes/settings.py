import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import get_session, require_login
from app.bot.vk_check import test_vk
from app.core.services import app_settings as s
from app.sheets import sync as sheets_sync

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/admin/templates")


async def _render(request, user, session, message=None, ok=None):
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "user": user,
            "vk_group_id": await s.get_setting(session, s.KEY_VK_GROUP_ID) or "",
            "sheets_owner_email": await s.get_setting(session, s.KEY_SHEETS_OWNER_EMAIL) or "",
            "vk_token_set": await s.is_set(session, s.KEY_VK_TOKEN),
            "message": message,
            "ok": ok,
        },
    )


@router.get("/settings")
async def settings_page(
    request: Request,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    return await _render(request, user, session)


@router.post("/settings")
async def settings_save(
    request: Request,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
    vk_token: str = Form(""),
    vk_group_id: str = Form(""),
    sheets_owner_email: str = Form(""),
):
    if vk_token.strip():  # пустое поле = не менять токен
        await s.set_setting(session, s.KEY_VK_TOKEN, vk_token)
    await s.set_setting(session, s.KEY_VK_GROUP_ID, vk_group_id)
    await s.set_setting(session, s.KEY_SHEETS_OWNER_EMAIL, sheets_owner_email)
    await session.commit()
    return await _render(
        request, user, session,
        message="Настройки сохранены. Изменение VK-токена применится автоматически в течение ~10 секунд (перезапуск не нужен).",
        ok=True,
    )


@router.post("/settings/test-vk")
async def settings_test_vk(
    request: Request,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    token = await s.get_setting(session, s.KEY_VK_TOKEN) or ""
    group_id = await s.get_setting(session, s.KEY_VK_GROUP_ID)
    ok, msg = await test_vk(token, group_id)
    return await _render(request, user, session, message=msg, ok=ok)


@router.post("/settings/test-sheets")
async def settings_test_sheets(
    request: Request,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    owner_email = await s.get_setting(session, s.KEY_SHEETS_OWNER_EMAIL)
    ok, msg = await sheets_sync.test_connection(owner_email)
    return await _render(request, user, session, message=msg, ok=ok)

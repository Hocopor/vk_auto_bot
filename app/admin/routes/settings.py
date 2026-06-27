import logging

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import get_session, require_login
from app.admin.templating import refresh_settings_cache, templates
from app.bot.vk_check import test_vk
from app.core.services import app_settings as s

logger = logging.getLogger(__name__)
router = APIRouter()


async def _render(request, user, session, message=None, ok=None):
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "user": user,
            "vk_group_id": await s.get_setting(session, s.KEY_VK_GROUP_ID) or "",
            "vk_token_set": await s.is_set(session, s.KEY_VK_TOKEN),
            "admin_title": await s.get_setting(session, s.KEY_ADMIN_TITLE) or "Админка",
            "winners_tab_enabled": (await s.get_setting(session, s.KEY_WINNERS_TAB_ENABLED)) != "false",
            "receipt_max_age_days": (await s.get_setting(session, s.KEY_RECEIPT_MAX_AGE_DAYS)) or "3",
            "autoconfirm_without_date": (await s.get_setting(session, s.KEY_AUTOCONFIRM_WITHOUT_DATE)) == "true",
            "message": message,
            "ok": ok,
        },
    )


def _update_cache(admin_title: str, winners_tab_enabled: bool):
    refresh_settings_cache(admin_title, winners_tab_enabled)


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
    admin_title: str = Form(""),
    winners_tab_enabled: str | None = Form(None),
    receipt_max_age_days: str = Form("3"),
    autoconfirm_without_date: str | None = Form(None),
):
    if vk_token.strip():
        await s.set_setting(session, s.KEY_VK_TOKEN, vk_token)
    await s.set_setting(session, s.KEY_VK_GROUP_ID, vk_group_id)
    title = admin_title.strip() or "Админка"
    winners = bool(winners_tab_enabled)
    await s.set_setting(session, s.KEY_ADMIN_TITLE, title)
    await s.set_setting(session, s.KEY_WINNERS_TAB_ENABLED, "true" if winners else "false")
    raw_age = (receipt_max_age_days or "").strip()
    try:
        age_val = int(raw_age)
        if age_val < 0:
            age_val = 3
    except ValueError:
        age_val = 3
    await s.set_setting(session, s.KEY_RECEIPT_MAX_AGE_DAYS, str(age_val))
    await s.set_setting(
        session,
        s.KEY_AUTOCONFIRM_WITHOUT_DATE,
        "true" if bool(autoconfirm_without_date) else "false",
    )
    await session.commit()
    _update_cache(title, winners)
    return await _render(
        request, user, session,
        message="Настройки сохранены.",
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

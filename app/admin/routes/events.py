import logging
import os
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import get_session, require_login
from app.core.config import settings
from app.core.defaults import DEFAULT_TEXTS
from app.core.models import Event, Purchase
from app.core.services.events import create_event, delete_event, set_active
from app.core.services import app_settings as app_settings_service
from app.sheets import sync as sheets_sync

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="app/admin/templates")


def _parse_optional_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    return datetime.fromisoformat(value)


def _parse_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


async def _save_qr_file(qr_file: UploadFile | None) -> str | None:
    if qr_file is None or not qr_file.filename:
        return None
    content = await qr_file.read()
    if not content:
        return None
    os.makedirs(settings.qr_dir, exist_ok=True)
    ext = os.path.splitext(qr_file.filename)[1]
    name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(settings.qr_dir, name)
    with open(path, "wb") as f:
        f.write(content)
    return path


@router.get("/events")
async def list_events(
    request: Request,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Event).order_by(Event.created_at.desc()))
    events = result.scalars().all()
    return templates.TemplateResponse(
        "events_list.html", {"request": request, "user": user, "events": events}
    )


@router.get("/events/new")
async def new_event_form(
    request: Request,
    user: str = Depends(require_login),
):
    return templates.TemplateResponse(
        "event_form.html",
        {
            "request": request,
            "user": user,
            "mode": "create",
            "event": None,
            "defaults": DEFAULT_TEXTS,
            "error": None,
        },
    )


@router.post("/events")
async def create_event_submit(
    request: Request,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
    name: str = Form(...),
    keyword: str = Form(...),
    price: str = Form(...),
    number_min: str = Form(...),
    number_max: str = Form(...),
    winners_count: str = Form("1"),
    starts_at: str = Form(""),
    ends_at: str = Form(""),
    expected_recipient: str = Form(""),
    auto_confirm: str | None = Form(None),
    msg_instruction: str = Form(""),
    msg_after_payment: str = Form(""),
    msg_receipt_received: str = Form(""),
    msg_need_contacts: str = Form(""),
    qr_file: UploadFile | None = None,
):
    form_values = {
        "name": name,
        "keyword": keyword,
        "price": price,
        "number_min": number_min,
        "number_max": number_max,
        "winners_count": winners_count,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "expected_recipient": expected_recipient,
        "auto_confirm": bool(auto_confirm),
        "msg_instruction": msg_instruction,
        "msg_after_payment": msg_after_payment,
        "msg_receipt_received": msg_receipt_received,
        "msg_need_contacts": msg_need_contacts,
    }

    try:
        price_val = Decimal(price)
        number_min_val = int(number_min)
        number_max_val = int(number_max)
        winners_count_val = int(winners_count) if winners_count else 1
        starts_at_val = _parse_optional_datetime(starts_at)
        ends_at_val = _parse_optional_datetime(ends_at)
    except (InvalidOperation, ValueError):
        return templates.TemplateResponse(
            "event_form.html",
            {
                "request": request,
                "user": user,
                "mode": "create",
                "event": form_values,
                "defaults": DEFAULT_TEXTS,
                "error": "Проверьте числовые поля и даты — введены некорректные значения.",
            },
            status_code=400,
        )

    qr_image_path = await _save_qr_file(qr_file)

    event = await create_event(
        session,
        name=name,
        keyword=keyword,
        price=price_val,
        number_min=number_min_val,
        number_max=number_max_val,
        winners_count=winners_count_val,
        starts_at=starts_at_val,
        ends_at=ends_at_val,
        expected_recipient=_parse_optional_str(expected_recipient),
        auto_confirm=bool(auto_confirm),
        qr_image_path=qr_image_path,
        msg_instruction=_parse_optional_str(msg_instruction),
        msg_after_payment=_parse_optional_str(msg_after_payment),
        msg_receipt_received=_parse_optional_str(msg_receipt_received),
        msg_need_contacts=_parse_optional_str(msg_need_contacts),
    )

    owner_email = await app_settings_service.get_setting(
        session, app_settings_service.KEY_SHEETS_OWNER_EMAIL
    )
    sheet_id = await sheets_sync.create_sheet(f"{event.name} — участники", owner_email=owner_email)
    if sheet_id:
        event.sheet_id = sheet_id
    else:
        logger.warning("Не удалось создать Google-лист для мероприятия %s", event.id)

    await session.commit()
    return RedirectResponse(url="/events", status_code=303)


@router.get("/events/{event_id}/edit")
async def edit_event_form(
    event_id: int,
    request: Request,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    from fastapi import HTTPException

    event = await session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Мероприятие не найдено")

    return templates.TemplateResponse(
        "event_form.html",
        {
            "request": request,
            "user": user,
            "mode": "edit",
            "event": event,
            "defaults": DEFAULT_TEXTS,
            "error": None,
        },
    )


@router.post("/events/{event_id}")
async def update_event_submit(
    event_id: int,
    request: Request,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
    name: str = Form(...),
    keyword: str = Form(...),
    price: str = Form(...),
    number_min: str = Form(...),
    number_max: str = Form(...),
    winners_count: str = Form("1"),
    starts_at: str = Form(""),
    ends_at: str = Form(""),
    expected_recipient: str = Form(""),
    auto_confirm: str | None = Form(None),
    msg_instruction: str = Form(""),
    msg_after_payment: str = Form(""),
    msg_receipt_received: str = Form(""),
    msg_need_contacts: str = Form(""),
    qr_file: UploadFile | None = None,
):
    from fastapi import HTTPException

    event = await session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Мероприятие не найдено")

    try:
        price_val = Decimal(price)
        number_min_val = int(number_min)
        number_max_val = int(number_max)
        winners_count_val = int(winners_count) if winners_count else 1
        starts_at_val = _parse_optional_datetime(starts_at)
        ends_at_val = _parse_optional_datetime(ends_at)
    except (InvalidOperation, ValueError):
        form_values = {
            "id": event.id,
            "name": name,
            "keyword": keyword,
            "price": price,
            "number_min": number_min,
            "number_max": number_max,
            "winners_count": winners_count,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "expected_recipient": expected_recipient,
            "auto_confirm": bool(auto_confirm),
            "msg_instruction": msg_instruction,
            "msg_after_payment": msg_after_payment,
            "msg_receipt_received": msg_receipt_received,
            "msg_need_contacts": msg_need_contacts,
            "qr_image_path": event.qr_image_path,
        }
        return templates.TemplateResponse(
            "event_form.html",
            {
                "request": request,
                "user": user,
                "mode": "edit",
                "event": form_values,
                "defaults": DEFAULT_TEXTS,
                "error": "Проверьте числовые поля и даты — введены некорректные значения.",
            },
            status_code=400,
        )

    event.name = name
    event.keyword = keyword.strip().lower()
    event.price = price_val
    event.number_min = number_min_val
    event.number_max = number_max_val
    event.winners_count = winners_count_val
    event.starts_at = starts_at_val
    event.ends_at = ends_at_val
    event.expected_recipient = _parse_optional_str(expected_recipient)
    event.auto_confirm = bool(auto_confirm)
    event.msg_instruction = msg_instruction or DEFAULT_TEXTS["msg_instruction"]
    event.msg_after_payment = msg_after_payment or DEFAULT_TEXTS["msg_after_payment"]
    event.msg_receipt_received = msg_receipt_received or DEFAULT_TEXTS["msg_receipt_received"]
    event.msg_need_contacts = msg_need_contacts or DEFAULT_TEXTS["msg_need_contacts"]

    new_qr_path = await _save_qr_file(qr_file)
    if new_qr_path:
        event.qr_image_path = new_qr_path

    await session.commit()
    return RedirectResponse(url="/events", status_code=303)


@router.post("/events/{event_id}/toggle")
async def toggle_event(
    event_id: int,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    from fastapi import HTTPException

    event = await session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Мероприятие не найдено")

    await set_active(session, event_id, not event.is_active)
    await session.commit()
    return RedirectResponse(url="/events", status_code=303)


@router.post("/events/{event_id}/delete")
async def delete_event_submit(
    event_id: int,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    from fastapi import HTTPException

    event = await session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Мероприятие не найдено")

    sheet_id = event.sheet_id
    qr_image_path = event.qr_image_path

    result = await session.execute(
        select(Purchase.receipt_file_path).where(
            Purchase.event_id == event_id, Purchase.receipt_file_path.is_not(None)
        )
    )
    receipt_paths = [row[0] for row in result.all() if row[0]]

    await delete_event(session, event_id)
    await session.commit()

    if sheet_id:
        try:
            await sheets_sync.delete_sheet(sheet_id)
        except Exception:
            logger.exception("Не удалось удалить Google-лист %s", sheet_id)

    for path in receipt_paths:
        try:
            os.remove(path)
        except OSError:
            pass

    if qr_image_path:
        try:
            os.remove(qr_image_path)
        except OSError:
            pass

    return RedirectResponse(url="/events", status_code=303)

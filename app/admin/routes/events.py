import hashlib
import logging
import os
import uuid
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import get_session, require_login
from app.admin.templating import templates
from app.core import timeutil
from app.core.config import settings
from app.core.defaults import DEFAULT_TEXTS
from app.core.models import Event, EventMessageImage, PosterNumber, Purchase
from app.core.services.events import (
    create_event,
    delete_event,
    find_active_event_by_keyword,
    set_active,
)
from app.core.services.numbers import event_capacity, recover_event_capacity

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _remove_file_quiet(path: str | None) -> None:
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


async def _save_message_image_file(event_id: int, message_key: str, upload) -> str | None:
    if upload is None or not getattr(upload, "filename", None):
        return None
    content = await upload.read()
    if not content:
        return None
    ext = os.path.splitext(upload.filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        return None
    os.makedirs(settings.message_images_dir, exist_ok=True)
    h = hashlib.sha1(content).hexdigest()[:12]
    name = f"{event_id}_{message_key}_{h}{ext}"
    path = os.path.join(settings.message_images_dir, name)
    with open(path, "wb") as f:
        f.write(content)
    return path


async def _process_message_image(
    session: AsyncSession, event_id: int, message_key: str, upload, delete_flag: bool
) -> None:
    existing = (
        await session.execute(
            select(EventMessageImage).where(
                EventMessageImage.event_id == event_id,
                EventMessageImage.message_key == message_key,
            )
        )
    ).scalar_one_or_none()
    if delete_flag:
        if existing is not None:
            _remove_file_quiet(existing.image_path)
            await session.delete(existing)
        return
    new_path = await _save_message_image_file(event_id, message_key, upload)
    if new_path is None:
        return  # ничего не загрузили — оставить как есть
    if existing is not None:
        if existing.image_path != new_path:
            _remove_file_quiet(existing.image_path)
        existing.image_path = new_path
        existing.attachment = None
        existing.attachment_error = None
    else:
        session.add(
            EventMessageImage(event_id=event_id, message_key=message_key, image_path=new_path)
        )


async def _event_msg_image_keys(session: AsyncSession, event_id: int) -> dict:
    rows = (
        await session.execute(
            select(EventMessageImage.message_key).where(EventMessageImage.event_id == event_id)
        )
    ).scalars().all()
    return {k: True for k in rows}


def _parse_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _keyword_conflict_message(conflict: Event) -> str:
    return (
        f"Кодовое слово уже используется в мероприятии «{conflict.name}» "
        f"(#{conflict.id}). Выберите другое слово или остановите то мероприятие."
    )


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
    caps = {e.id: await event_capacity(session, e.id) for e in events}
    return templates.TemplateResponse(
        "events_list.html",
        {"request": request, "user": user, "events": events, "caps": caps},
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
            "msg_images": {},
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
    msg_contacts_saved: str = Form(""),
    send_instruction: str | None = Form(None),
    send_qr: str | None = Form(None),
    send_receipt_received: str | None = Form(None),
    send_after_payment: str | None = Form(None),
    send_need_contacts: str | None = Form(None),
    send_contacts_saved: str | None = Form(None),
    qr_file: UploadFile | None = None,
    google_sheet_url: str = Form(""),
    image_receipt_received: UploadFile | None = None,
    image_contacts_saved: UploadFile | None = None,
    image_after_payment: UploadFile | None = None,
    image_receipt_received_delete: str | None = Form(None),
    image_contacts_saved_delete: str | None = Form(None),
    image_after_payment_delete: str | None = Form(None),
):
    msg_image_inputs = [
        ("receipt_received", image_receipt_received, image_receipt_received_delete),
        ("contacts_saved", image_contacts_saved, image_contacts_saved_delete),
        ("after_payment", image_after_payment, image_after_payment_delete),
    ]

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
        "msg_contacts_saved": msg_contacts_saved,
        "send_instruction": bool(send_instruction),
        "send_qr": bool(send_qr),
        "send_receipt_received": bool(send_receipt_received),
        "send_after_payment": bool(send_after_payment),
        "send_need_contacts": bool(send_need_contacts),
        "send_contacts_saved": bool(send_contacts_saved),
        "google_sheet_url": google_sheet_url,
    }

    try:
        price_val = Decimal(price)
        number_min_val = int(number_min)
        number_max_val = int(number_max)
        winners_count_val = int(winners_count) if winners_count else 1
        starts_at_val = timeutil.parse_local_datetime(starts_at)
        ends_at_val = timeutil.parse_local_datetime(ends_at)
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
                "msg_images": {},
            },
            status_code=400,
        )

    conflict = await find_active_event_by_keyword(session, keyword)
    if conflict is not None:
        return templates.TemplateResponse(
            "event_form.html",
            {
                "request": request,
                "user": user,
                "mode": "create",
                "event": form_values,
                "defaults": DEFAULT_TEXTS,
                "error": _keyword_conflict_message(conflict),
                "msg_images": {},
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
        msg_contacts_saved=_parse_optional_str(msg_contacts_saved),
        send_instruction=bool(send_instruction),
        send_qr=bool(send_qr),
        send_receipt_received=bool(send_receipt_received),
        send_after_payment=bool(send_after_payment),
        send_need_contacts=bool(send_need_contacts),
        send_contacts_saved=bool(send_contacts_saved),
    )

    event.google_sheet_url = _parse_optional_str(google_sheet_url)

    for key, upload, delete_flag in msg_image_inputs:
        await _process_message_image(session, event.id, key, upload, bool(delete_flag))

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        conflict = await find_active_event_by_keyword(session, keyword)
        msg = (
            _keyword_conflict_message(conflict)
            if conflict is not None
            else "Кодовое слово уже используется другим активным мероприятием."
        )
        return templates.TemplateResponse(
            "event_form.html",
            {
                "request": request,
                "user": user,
                "mode": "create",
                "event": form_values,
                "defaults": DEFAULT_TEXTS,
                "error": msg,
                "msg_images": {},
            },
            status_code=400,
        )
    return RedirectResponse(url="/events", status_code=303)


@router.get("/events/{event_id}/message-image/{message_key}")
async def event_message_image(
    event_id: int,
    message_key: str,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    from fastapi import HTTPException

    row = (
        await session.execute(
            select(EventMessageImage).where(
                EventMessageImage.event_id == event_id,
                EventMessageImage.message_key == message_key,
            )
        )
    ).scalar_one_or_none()
    if row is None or not row.image_path or not os.path.exists(row.image_path):
        raise HTTPException(status_code=404, detail="Изображение не найдено")
    return FileResponse(row.image_path)


@router.get("/events/{event_id}/qr")
async def event_qr(
    event_id: int,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    from fastapi import HTTPException

    event = await session.get(Event, event_id)
    if event is None or not event.qr_image_path or not os.path.exists(event.qr_image_path):
        raise HTTPException(status_code=404, detail="QR-код не найден")
    return FileResponse(event.qr_image_path)


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
            "msg_images": await _event_msg_image_keys(session, event.id),
            "cap": await event_capacity(session, event.id),
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
    msg_contacts_saved: str = Form(""),
    send_instruction: str | None = Form(None),
    send_qr: str | None = Form(None),
    send_receipt_received: str | None = Form(None),
    send_after_payment: str | None = Form(None),
    send_need_contacts: str | None = Form(None),
    send_contacts_saved: str | None = Form(None),
    qr_file: UploadFile | None = None,
    google_sheet_url: str = Form(""),
    image_receipt_received: UploadFile | None = None,
    image_contacts_saved: UploadFile | None = None,
    image_after_payment: UploadFile | None = None,
    image_receipt_received_delete: str | None = Form(None),
    image_contacts_saved_delete: str | None = Form(None),
    image_after_payment_delete: str | None = Form(None),
):
    from fastapi import HTTPException

    msg_image_inputs = [
        ("receipt_received", image_receipt_received, image_receipt_received_delete),
        ("contacts_saved", image_contacts_saved, image_contacts_saved_delete),
        ("after_payment", image_after_payment, image_after_payment_delete),
    ]

    event = await session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Мероприятие не найдено")

    old_sheet_url = event.google_sheet_url
    old_number_min = event.number_min
    old_number_max = event.number_max

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
        "msg_contacts_saved": msg_contacts_saved,
        "qr_image_path": event.qr_image_path,
        "send_instruction": bool(send_instruction),
        "send_qr": bool(send_qr),
        "send_receipt_received": bool(send_receipt_received),
        "send_after_payment": bool(send_after_payment),
        "send_need_contacts": bool(send_need_contacts),
        "send_contacts_saved": bool(send_contacts_saved),
        "google_sheet_url": google_sheet_url,
    }

    try:
        price_val = Decimal(price)
        number_min_val = int(number_min)
        number_max_val = int(number_max)
        winners_count_val = int(winners_count) if winners_count else 1
        starts_at_val = timeutil.parse_local_datetime(starts_at)
        ends_at_val = timeutil.parse_local_datetime(ends_at)
    except (InvalidOperation, ValueError):
        return templates.TemplateResponse(
            "event_form.html",
            {
                "request": request,
                "user": user,
                "mode": "edit",
                "event": form_values,
                "defaults": DEFAULT_TEXTS,
                "error": "Проверьте числовые поля и даты — введены некорректные значения.",
                "msg_images": await _event_msg_image_keys(session, event.id),
            },
            status_code=400,
        )

    # Нельзя сузить диапазон ниже уже присвоенных номеров (Фаза 9).
    bounds = (
        await session.execute(
            select(func.min(PosterNumber.number), func.max(PosterNumber.number)).where(
                PosterNumber.event_id == event.id
            )
        )
    ).one()
    assigned_min, assigned_max = bounds
    if assigned_min is not None and (
        number_min_val > assigned_min or number_max_val < assigned_max
    ):
        return templates.TemplateResponse(
            "event_form.html",
            {
                "request": request,
                "user": user,
                "mode": "edit",
                "event": form_values,
                "defaults": DEFAULT_TEXTS,
                "error": (
                    f"Нельзя сузить диапазон: уже присвоены номера "
                    f"{assigned_min}–{assigned_max}. Диапазон должен их включать."
                ),
                "msg_images": await _event_msg_image_keys(session, event.id),
                "cap": await event_capacity(session, event.id),
            },
            status_code=400,
        )

    if event.is_active:
        conflict = await find_active_event_by_keyword(session, keyword, exclude_id=event.id)
        if conflict is not None:
            return templates.TemplateResponse(
                "event_form.html",
                {
                    "request": request,
                    "user": user,
                    "mode": "edit",
                    "event": form_values,
                    "defaults": DEFAULT_TEXTS,
                    "error": _keyword_conflict_message(conflict),
                    "msg_images": await _event_msg_image_keys(session, event.id),
                    "cap": await event_capacity(session, event.id),
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
    event.msg_contacts_saved = msg_contacts_saved or DEFAULT_TEXTS["msg_contacts_saved"]
    event.send_instruction = bool(send_instruction)
    event.send_qr = bool(send_qr)
    event.send_receipt_received = bool(send_receipt_received)
    event.send_after_payment = bool(send_after_payment)
    event.send_need_contacts = bool(send_need_contacts)
    event.send_contacts_saved = bool(send_contacts_saved)
    event.google_sheet_url = _parse_optional_str(google_sheet_url)
    new_sheet_url = event.google_sheet_url

    # Диапазон расширили → освободилась ёмкость: дать воркеру дозаполнить покупки
    # с недостачей, бот снова начнёт принимать (Фаза 9, восстановление ёмкости).
    new_capacity = number_max_val - number_min_val + 1
    old_capacity = old_number_max - old_number_min + 1
    if new_capacity > old_capacity:
        await recover_event_capacity(session, event.id)

    new_qr_path = await _save_qr_file(qr_file)
    if new_qr_path:
        event.qr_image_path = new_qr_path
        event.qr_attachment = None
        event.qr_last_error = None

    if new_sheet_url is not None and new_sheet_url != old_sheet_url:
        # HTML -> Google либо Google -> другой Google: сразу переносим данные
        # из БД в новую таблицу. Старую (если была) просто отвязываем —
        # внешний Google-документ не трогаем.
        from app.sheets.sync import sync_event_to_sheet

        try:
            await sync_event_to_sheet(session, event.id, new_sheet_url, raise_on_error=True)
        except Exception:
            logger.exception(
                "Sheet migration failed for event %s (url=%s)", event.id, new_sheet_url
            )
            await session.rollback()
            return templates.TemplateResponse(
                "event_form.html",
                {
                    "request": request,
                    "user": user,
                    "mode": "edit",
                    "event": form_values,
                    "defaults": DEFAULT_TEXTS,
                    "error": (
                        "Не удалось записать в новую таблицу. Проверьте, что ссылка "
                        "верна и таблица расшарена service account на редактирование."
                    ),
                    "msg_images": {},
                },
                status_code=400,
            )

    for key, upload, delete_flag in msg_image_inputs:
        await _process_message_image(session, event.id, key, upload, bool(delete_flag))

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        conflict = await find_active_event_by_keyword(session, keyword, exclude_id=event.id)
        msg = (
            _keyword_conflict_message(conflict)
            if conflict is not None
            else "Кодовое слово уже используется другим активным мероприятием."
        )
        return templates.TemplateResponse(
            "event_form.html",
            {
                "request": request,
                "user": user,
                "mode": "edit",
                "event": form_values,
                "defaults": DEFAULT_TEXTS,
                "error": msg,
                "msg_images": await _event_msg_image_keys(session, event.id),
            },
            status_code=400,
        )
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

    qr_image_path = event.qr_image_path

    result = await session.execute(
        select(Purchase.receipt_file_path).where(
            Purchase.event_id == event_id, Purchase.receipt_file_path.is_not(None)
        )
    )
    receipt_paths = [row[0] for row in result.all() if row[0]]

    result = await session.execute(
        select(EventMessageImage.image_path).where(EventMessageImage.event_id == event_id)
    )
    msg_image_paths = [row[0] for row in result.all() if row[0]]

    await delete_event(session, event_id)
    await session.commit()

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

    for path in msg_image_paths:
        _remove_file_quiet(path)

    return RedirectResponse(url="/events", status_code=303)

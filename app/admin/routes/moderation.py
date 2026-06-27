import hashlib
import os
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.admin.deps import get_session, require_login
from app.admin.templating import templates
from app.core.config import settings
from app.core.models import Event, Participant, PosterNumber, Purchase, PurchaseStatus
from app.core.services import app_settings
from app.core.services.numbers import count_posters
from app.core.services.participants import (
    next_synthetic_vk_id,
    parse_vk_user_id,
    resolve_public_name,
    upsert_participant,
)
from app.core.services.purchases import approve, can_approve, reject, set_amount

router = APIRouter()


def _is_partial(purchase) -> bool:
    amount = purchase.amount if purchase.amount is not None else purchase.ocr_amount
    if amount is None:
        return False
    price = purchase.event.price if purchase.event else None
    if price is None or price <= 0:
        return False
    return amount < price or (amount % price != 0)


COLUMN_LIMIT = 50
BOARD_COLUMNS = [
    ("pending", "На проверке", [PurchaseStatus.pending_ocr, PurchaseStatus.manual_review]),
    ("confirmed", "Подтверждено", [PurchaseStatus.approved, PurchaseStatus.auto_confirmed]),
    ("rejected", "Отклонено", [PurchaseStatus.rejected, PurchaseStatus.revoked]),
]


def _purchase_base_stmt():
    return select(Purchase).options(
        selectinload(Purchase.participant),
        selectinload(Purchase.event),
        selectinload(Purchase.poster_numbers),
    )


def _apply_event_filter(stmt, event_id):
    if event_id is not None:
        stmt = stmt.where(Purchase.event_id == event_id)
    return stmt


def _apply_search(stmt, q):
    if q and q.strip():
        conditions = [
            Participant.provided_name.ilike(f"%{q}%"),
            Participant.vk_name.ilike(f"%{q}%"),
            Participant.phone.ilike(f"%{q}%"),
        ]

        try:
            q_int = int(q.strip())
            conditions.append(Participant.vk_user_id == q_int)
            conditions.append(
                Purchase.id.in_(
                    select(PosterNumber.purchase_id).where(PosterNumber.number == q_int)
                )
            )
        except ValueError:
            pass

        try:
            q_decimal = Decimal(q.strip())
            conditions.append(Purchase.amount == q_decimal)
            conditions.append(Purchase.ocr_amount == q_decimal)
        except (InvalidOperation, ValueError):
            pass

        stmt = stmt.join(Participant, Purchase.participant_id == Participant.id).where(
            or_(*conditions)
        )
    return stmt


@router.get("/moderation")
async def moderation_list(
    request: Request,
    status: str | None = None,
    q: str | None = None,
    event_id: int | None = None,
    view: str = "board",
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    events_result = await session.execute(select(Event).order_by(Event.created_at.desc()))
    events = events_result.scalars().all()

    vk_group_id = await app_settings.get_setting(session, app_settings.KEY_VK_GROUP_ID)

    if view == "list":
        stmt = _apply_event_filter(_purchase_base_stmt(), event_id)

        if status:
            try:
                status_enum = PurchaseStatus(status)
            except ValueError:
                status_enum = None
            if status_enum is not None:
                stmt = stmt.where(Purchase.status == status_enum)

        stmt = _apply_search(stmt, q).order_by(Purchase.created_at.desc())

        result = await session.execute(stmt)
        purchases = result.scalars().unique().all()
        rows = [{"purchase": p, "partial": _is_partial(p)} for p in purchases]

        return templates.TemplateResponse(
            "moderation_list.html",
            {
                "request": request,
                "user": user,
                "rows": rows,
                "status": status,
                "q": q or "",
                "event_id": event_id,
                "statuses": list(PurchaseStatus),
                "vk_group_id": vk_group_id,
                "events": events,
                "view": "list",
            },
        )

    columns = []
    for key, title, statuses in BOARD_COLUMNS:
        stmt = _apply_search(_apply_event_filter(_purchase_base_stmt(), event_id), q)
        stmt = stmt.where(Purchase.status.in_(statuses)).order_by(Purchase.created_at.desc())
        stmt = stmt.limit(COLUMN_LIMIT + 1)

        result = await session.execute(stmt)
        items = result.scalars().unique().all()
        has_more = len(items) > COLUMN_LIMIT
        items = items[:COLUMN_LIMIT]

        columns.append(
            {
                "key": key,
                "title": title,
                "rows": [{"purchase": p, "partial": _is_partial(p)} for p in items],
                "has_more": has_more,
            }
        )

    return templates.TemplateResponse(
        "moderation_board.html",
        {
            "request": request,
            "user": user,
            "columns": columns,
            "events": events,
            "event_id": event_id,
            "q": q or "",
            "vk_group_id": vk_group_id,
            "view": "board",
            "column_limit": COLUMN_LIMIT,
        },
    )


@router.get("/moderation/manual")
async def moderation_manual_form(
    request: Request,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Event).order_by(Event.created_at.desc()))
    events = result.scalars().all()
    return templates.TemplateResponse(
        "manual_add.html",
        {"request": request, "user": user, "events": events},
    )


@router.post("/moderation/manual")
async def moderation_manual_create(
    request: Request,
    event_id: int = Form(...),
    vk_link: str = Form(""),
    provided_name: str = Form(""),
    phone: str = Form(""),
    public_name: str = Form(""),
    amount: str = Form(""),
    receipt: UploadFile | None = File(None),
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    event = await session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Мероприятие не найдено")

    parsed_id = parse_vk_user_id(vk_link)
    if parsed_id is not None:
        vk_user_id = parsed_id
    else:
        vk_user_id = await next_synthetic_vk_id(session, event_id)

    link_value = vk_link.strip() or (f"https://vk.com/id{parsed_id}" if parsed_id else None)

    participant = await upsert_participant(
        session, event_id, vk_user_id,
        vk_link=link_value,
        provided_name=provided_name.strip() or None,
        phone=phone.strip() or None,
    )
    participant.public_name = public_name.strip() or None

    amount_val = None
    if amount.strip():
        try:
            amount_val = Decimal(amount.strip())
        except InvalidOperation:
            amount_val = None
    posters = count_posters(amount_val, event.price) if amount_val is not None else 0

    file_path = None
    receipt_hash = None
    if receipt is not None and receipt.filename:
        content = await receipt.read()
        if content:
            receipt_hash = hashlib.sha256(content).hexdigest()
            ext = receipt.filename.rsplit(".", 1)[-1].lower() if "." in receipt.filename else "jpg"
            if not (ext.isalnum() and len(ext) <= 5):
                ext = "jpg"
            os.makedirs(settings.receipts_dir, exist_ok=True)
            file_name = f"{event_id}_{vk_user_id}_{receipt_hash[:12]}.{ext}"
            file_path = os.path.join(settings.receipts_dir, file_name)
            with open(file_path, "wb") as f:
                f.write(content)

    purchase = Purchase(
        event_id=event_id,
        participant_id=participant.id,
        receipt_file_path=file_path,
        receipt_hash=receipt_hash,
        amount=amount_val,
        posters_count=posters,
        status=PurchaseStatus.manual_review,
        moderated_by=None,
    )
    session.add(purchase)
    await session.commit()
    await session.refresh(purchase)
    return RedirectResponse(url=f"/moderation/{purchase.id}", status_code=303)


@router.get("/moderation/{purchase_id}")
async def moderation_detail(
    purchase_id: int,
    request: Request,
    error: str | None = None,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Purchase).where(Purchase.id == purchase_id).options(
        selectinload(Purchase.participant),
        selectinload(Purchase.event),
        selectinload(Purchase.poster_numbers),
    )
    result = await session.execute(stmt)
    purchase = result.scalar_one_or_none()
    if purchase is None:
        raise HTTPException(status_code=404, detail="Покупка не найдена")

    partial = _is_partial(purchase)
    vk_group_id = await app_settings.get_setting(session, app_settings.KEY_VK_GROUP_ID)
    can_approve_flag = can_approve(purchase, purchase.event) if purchase.event else False
    public_name_value = resolve_public_name(purchase.participant) if purchase.participant else ""
    public_name_value = public_name_value or ""

    return templates.TemplateResponse(
        "purchase_detail.html",
        {
            "request": request,
            "user": user,
            "purchase": purchase,
            "partial": partial,
            "vk_group_id": vk_group_id,
            "can_approve": can_approve_flag,
            "error": error,
            "public_name_value": public_name_value,
        },
    )


@router.get("/moderation/{purchase_id}/receipt")
async def moderation_receipt(
    purchase_id: int,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    purchase = await session.get(Purchase, purchase_id)
    if (
        purchase is None
        or not purchase.receipt_file_path
        or not os.path.exists(purchase.receipt_file_path)
    ):
        raise HTTPException(status_code=404, detail="Чек не найден")
    media_type = (
        "application/pdf"
        if purchase.receipt_file_path.lower().endswith(".pdf")
        else None
    )
    return FileResponse(purchase.receipt_file_path, media_type=media_type)


@router.post("/moderation/{purchase_id}/approve")
async def moderation_approve(
    purchase_id: int,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Purchase).where(Purchase.id == purchase_id).options(selectinload(Purchase.event))
    result = await session.execute(stmt)
    purchase = result.scalar_one_or_none()
    if purchase is None:
        raise HTTPException(status_code=404, detail="Покупка не найдена")
    if not can_approve(purchase, purchase.event):
        return RedirectResponse(url=f"/moderation/{purchase_id}?error=amount", status_code=303)
    await approve(session, purchase, moderated_by=user, event=purchase.event)
    await session.commit()
    return RedirectResponse(url=f"/moderation/{purchase_id}", status_code=303)


@router.post("/moderation/{purchase_id}/reject")
async def moderation_reject(
    purchase_id: int,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    purchase = await session.get(Purchase, purchase_id)
    if purchase is None:
        raise HTTPException(status_code=404, detail="Покупка не найдена")
    # reject освобождает присвоенные номера и снимает флаг numbers_assigned.
    await reject(session, purchase, moderated_by=user)
    await session.commit()
    # Публичная таблица читается из БД на лету — освобождение номеров отражается
    # сразу, ничего пересобирать не нужно.
    return RedirectResponse(url=f"/moderation/{purchase_id}", status_code=303)


@router.post("/moderation/{purchase_id}/amount")
async def moderation_set_amount(
    purchase_id: int,
    amount: str = Form(...),
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Purchase).where(Purchase.id == purchase_id).options(selectinload(Purchase.event))
    result = await session.execute(stmt)
    purchase = result.scalar_one_or_none()
    if purchase is None:
        raise HTTPException(status_code=404, detail="Покупка не найдена")
    try:
        amount_val = Decimal(amount)
    except InvalidOperation:
        return RedirectResponse(url=f"/moderation/{purchase_id}", status_code=303)
    await set_amount(session, purchase, amount_val, purchase.event)
    await session.commit()
    return RedirectResponse(url=f"/moderation/{purchase_id}", status_code=303)


@router.post("/moderation/{purchase_id}/contacts")
async def moderation_set_contacts(
    purchase_id: int,
    provided_name: str = Form(""),
    phone: str = Form(""),
    public_name: str = Form(""),
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Purchase).where(Purchase.id == purchase_id).options(
        selectinload(Purchase.participant)
    )
    result = await session.execute(stmt)
    purchase = result.scalar_one_or_none()
    if purchase is None:
        raise HTTPException(status_code=404, detail="Покупка не найдена")
    participant = purchase.participant
    participant.provided_name = provided_name.strip() or None
    participant.phone = phone.strip() or None
    participant.public_name = public_name.strip() or None
    await session.commit()
    return RedirectResponse(url=f"/moderation/{purchase_id}", status_code=303)

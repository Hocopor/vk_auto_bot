from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.admin.deps import OptionalInt, get_session, require_login
from app.admin.templating import templates
from app.core.models import Event, Participant, PosterNumber, Purchase
from app.core.services import app_settings
from app.core.services.participants import resolve_public_name

router = APIRouter()

PAGE_SIZE = 50


def _text_conditions(qs: str):
    like = f"%{qs}%"
    return [
        Participant.provided_name.ilike(like),
        Participant.vk_name.ilike(like),
        Participant.phone.ilike(like),
    ]


def _build_person(parts: list[Participant]) -> dict:
    rep = max(parts, key=lambda p: p.id)
    groups = []
    for p in sorted(parts, key=lambda p: p.event.created_at, reverse=True):
        groups.append(
            {
                "event": p.event,
                "purchases": sorted(p.purchases, key=lambda x: x.created_at, reverse=True),
                "numbers": sorted(n.number for n in p.poster_numbers),
            }
        )
    return {
        "vk_user_id": rep.vk_user_id,
        "vk_name": rep.vk_name,
        "vk_link": rep.vk_link,
        "provided_name": rep.provided_name,
        "phone": rep.phone,
        "public_name": resolve_public_name(rep) or "",
        "groups": groups,
    }


@router.get("/participants")
async def participants_list(
    request: Request,
    event_id: OptionalInt = None,
    page: int = 1,
    q: str | None = None,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    page = max(page, 1)
    offset = (page - 1) * PAGE_SIZE
    qs = (q or "").strip()

    events_result = await session.execute(select(Event).order_by(Event.created_at.desc()))
    events = events_result.scalars().all()

    vk_group_id = await app_settings.get_setting(session, app_settings.KEY_VK_GROUP_ID)

    if event_id is not None:
        event_filters = [Participant.event_id == event_id]
        if qs:
            conditions = _text_conditions(qs)
            try:
                n = int(qs)
            except ValueError:
                pass
            else:
                conditions.append(Participant.vk_user_id == n)
                conditions.append(
                    Participant.id.in_(
                        select(PosterNumber.participant_id).where(
                            PosterNumber.event_id == event_id,
                            PosterNumber.number == n,
                        )
                    )
                )
            event_filters.append(or_(*conditions))

        total = (
            await session.execute(
                select(func.count()).select_from(Participant).where(*event_filters)
            )
        ).scalar() or 0

        parts_result = await session.execute(
            select(Participant)
            .where(*event_filters)
            .order_by(Participant.id)
            .limit(PAGE_SIZE)
            .offset(offset)
        )
        parts = parts_result.scalars().all()

        page_ids = [p.id for p in parts]
        numbers_by_participant: dict[int, list[int]] = {}
        if page_ids:
            numbers_result = await session.execute(
                select(PosterNumber).where(
                    PosterNumber.event_id == event_id,
                    PosterNumber.participant_id.in_(page_ids),
                )
            )
            for pn in numbers_result.scalars().all():
                numbers_by_participant.setdefault(pn.participant_id, []).append(pn.number)
            for participant_id in numbers_by_participant:
                numbers_by_participant[participant_id].sort()

        return templates.TemplateResponse(
            "participants_list.html",
            {
                "request": request,
                "user": user,
                "events": events,
                "event_id": event_id,
                "mode": "event",
                "participants": parts,
                "numbers_by_participant": numbers_by_participant,
                "page": page,
                "page_size": PAGE_SIZE,
                "total": total,
                "has_prev": page > 1,
                "has_next": offset + PAGE_SIZE < total,
                "vk_group_id": vk_group_id,
                "q": qs,
            },
        )

    all_filters = []
    if qs:
        conditions = _text_conditions(qs)
        try:
            n = int(qs)
        except ValueError:
            pass
        else:
            conditions.append(Participant.vk_user_id == n)
        all_filters.append(or_(*conditions))

    total = (
        await session.execute(
            select(func.count(distinct(Participant.vk_user_id))).where(*all_filters)
        )
    ).scalar() or 0

    vk_ids_result = await session.execute(
        select(Participant.vk_user_id)
        .where(*all_filters)
        .group_by(Participant.vk_user_id)
        .order_by(func.max(Participant.id).desc())
        .limit(PAGE_SIZE)
        .offset(offset)
    )
    vk_ids = vk_ids_result.scalars().all()

    people = []
    if vk_ids:
        parts_result = await session.execute(
            select(Participant)
            .where(Participant.vk_user_id.in_(vk_ids))
            .options(selectinload(Participant.event))
            .order_by(Participant.id)
        )
        parts_by_vk: dict[int, list[Participant]] = {}
        for p in parts_result.scalars().all():
            parts_by_vk.setdefault(p.vk_user_id, []).append(p)

        for vk in vk_ids:
            group = parts_by_vk.get(vk, [])
            if not group:
                continue
            rep = max(group, key=lambda p: p.id)
            events_for_person = sorted(
                (p.event for p in group), key=lambda e: e.created_at, reverse=True
            )
            people.append(
                {
                    "vk_user_id": vk,
                    "vk_name": rep.vk_name,
                    "provided_name": rep.provided_name,
                    "phone": rep.phone,
                    "events": events_for_person,
                }
            )

    return templates.TemplateResponse(
        "participants_list.html",
        {
            "request": request,
            "user": user,
            "events": events,
            "event_id": event_id,
            "mode": "all",
            "people": people,
            "page": page,
            "page_size": PAGE_SIZE,
            "total": total,
            "has_prev": page > 1,
            "has_next": offset + PAGE_SIZE < total,
            "vk_group_id": vk_group_id,
            "q": qs,
        },
    )


@router.get("/participants/vk/{vk_user_id}")
async def participant_card_aggregate(
    vk_user_id: int,
    request: Request,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Participant)
        .where(Participant.vk_user_id == vk_user_id)
        .options(
            selectinload(Participant.event),
            selectinload(Participant.purchases).selectinload(Purchase.event),
            selectinload(Participant.poster_numbers),
        )
        .order_by(Participant.id)
    )
    parts = result.scalars().unique().all()
    if not parts:
        raise HTTPException(status_code=404, detail="Участник не найден")

    person = _build_person(parts)
    vk_group_id = await app_settings.get_setting(session, app_settings.KEY_VK_GROUP_ID)

    return templates.TemplateResponse(
        "participant_card.html",
        {
            "request": request,
            "user": user,
            "person": person,
            "scope": "all",
            "back_event_id": None,
            "vk_group_id": vk_group_id,
        },
    )


@router.get("/participants/{participant_id}")
async def participant_card(
    participant_id: int,
    request: Request,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Participant)
        .where(Participant.id == participant_id)
        .options(
            selectinload(Participant.event),
            selectinload(Participant.purchases).selectinload(Purchase.event),
            selectinload(Participant.poster_numbers),
        )
    )
    p = result.scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="Участник не найден")

    person = _build_person([p])
    vk_group_id = await app_settings.get_setting(session, app_settings.KEY_VK_GROUP_ID)

    return templates.TemplateResponse(
        "participant_card.html",
        {
            "request": request,
            "user": user,
            "person": person,
            "scope": "event",
            "back_event_id": p.event_id,
            "vk_group_id": vk_group_id,
        },
    )

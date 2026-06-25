from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import get_session, require_login
from app.core.models import Event, Participant, PosterNumber

router = APIRouter()
templates = Jinja2Templates(directory="app/admin/templates")


@router.get("/participants")
async def participants_list(
    request: Request,
    event_id: int | None = None,
    user: str = Depends(require_login),
    session: AsyncSession = Depends(get_session),
):
    events_result = await session.execute(select(Event).order_by(Event.name))
    events = events_result.scalars().all()

    participants: list[Participant] = []
    numbers_by_participant: dict[int, list[int]] = {}

    if event_id is not None:
        participants_result = await session.execute(
            select(Participant)
            .where(Participant.event_id == event_id)
            .order_by(Participant.id)
        )
        participants = participants_result.scalars().all()

        numbers_result = await session.execute(
            select(PosterNumber).where(PosterNumber.event_id == event_id)
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
            "participants": participants,
            "numbers_by_participant": numbers_by_participant,
        },
    )

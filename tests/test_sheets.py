from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core import models  # noqa: F401  (наполняет Base.metadata)
from app.core.db import Base
from app.core.models import Event, Participant, PosterNumber, Purchase, PurchaseStatus
from app.sheets import sync
from app.sheets.sync import (
    HEADER,
    PAID_MARK,
    build_rows,
    collect_event_records,
    create_sheet,
    rebuild,
    rebuild_event_sheet,
)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


def make_event_obj(**overrides):
    defaults = dict(
        name="Тестовый розыгрыш",
        keyword="тест",
        price=Decimal("250"),
        number_min=1,
        number_max=100,
        winners_count=1,
        sheet_id=None,
    )
    defaults.update(overrides)
    return Event(**defaults)


def test_build_rows():
    rows = build_rows([(3, "Аня"), (1, "Боб"), (2, None)])
    assert rows[0] == HEADER
    assert rows[1] == [1, "Боб", PAID_MARK]
    assert rows[2] == [2, "", PAID_MARK]
    assert rows[3] == [3, "Аня", PAID_MARK]


@pytest.mark.asyncio
async def test_create_sheet_mock(monkeypatch):
    fake_ws = MagicMock()
    fake_sheet = MagicMock()
    fake_sheet.id = "SHEET123"
    fake_sheet.sheet1 = fake_ws
    fake_client = MagicMock()
    fake_client.create.return_value = fake_sheet

    monkeypatch.setattr(sync, "get_client", lambda: fake_client)

    sheet_id = await create_sheet("X")

    assert sheet_id == "SHEET123"
    fake_ws.update.assert_called_once_with([HEADER])
    fake_sheet.share.assert_called_once_with(None, perm_type="anyone", role="reader")


@pytest.mark.asyncio
async def test_create_sheet_api_failure(monkeypatch):
    def raising_client():
        raise RuntimeError("API down")

    monkeypatch.setattr(sync, "get_client", raising_client)

    assert await create_sheet("X") is None
    assert await rebuild("id", [(1, "Аня")]) is False
    assert await sync.add_rows("id", [(1, "Аня")]) is False


@pytest.mark.asyncio
async def test_rebuild_mock(monkeypatch):
    fake_ws = MagicMock()
    fake_sheet = MagicMock()
    fake_sheet.sheet1 = fake_ws
    fake_client = MagicMock()
    fake_client.open_by_key.return_value = fake_sheet

    monkeypatch.setattr(sync, "get_client", lambda: fake_client)

    records = [(2, "Боб"), (1, None)]
    result = await rebuild("SHEET123", records)

    assert result is True
    fake_ws.clear.assert_called_once()
    fake_ws.update.assert_called_once_with(build_rows(records))


async def test_rebuild_event_sheet_no_sheet_id(session):
    event = make_event_obj(sheet_id=None)
    session.add(event)
    await session.commit()
    await session.refresh(event)

    result = await rebuild_event_sheet(session, event.id)

    assert result is False


async def test_collect_event_records(session):
    event = make_event_obj()
    session.add(event)
    await session.flush()

    participant_approved = Participant(
        event_id=event.id, vk_user_id=1, provided_name="Аня"
    )
    participant_review = Participant(
        event_id=event.id, vk_user_id=2, provided_name="Игорь"
    )
    session.add_all([participant_approved, participant_review])
    await session.flush()

    purchase_approved = Purchase(
        event_id=event.id,
        participant_id=participant_approved.id,
        status=PurchaseStatus.approved,
    )
    purchase_review = Purchase(
        event_id=event.id,
        participant_id=participant_review.id,
        status=PurchaseStatus.manual_review,
    )
    session.add_all([purchase_approved, purchase_review])
    await session.flush()

    poster_numbers = [
        PosterNumber(
            event_id=event.id,
            participant_id=participant_approved.id,
            purchase_id=purchase_approved.id,
            number=10,
        ),
        PosterNumber(
            event_id=event.id,
            participant_id=participant_approved.id,
            purchase_id=purchase_approved.id,
            number=11,
        ),
        PosterNumber(
            event_id=event.id,
            participant_id=participant_review.id,
            purchase_id=purchase_review.id,
            number=99,
        ),
    ]
    session.add_all(poster_numbers)
    await session.commit()

    records = await collect_event_records(session, event.id)

    assert records == [(10, "Аня"), (11, "Аня")]

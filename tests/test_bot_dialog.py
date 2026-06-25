from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core import models  # noqa: F401  (наполняет Base.metadata)
from app.core.db import Base
from app.core.models import Participant, Purchase, PurchaseStatus
from app.core.services.events import create_event
from app.bot import dialog


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def make_event(session, **overrides):
    defaults = dict(
        name="Тестовый розыгрыш",
        keyword="розыгрыш",
        price=Decimal("250"),
        number_min=1,
        number_max=5,
        winners_count=1,
        auto_confirm=False,
    )
    defaults.update(overrides)
    event = await create_event(session, **defaults)
    await session.commit()
    return event


async def make_participant(session, event_id, vk_user_id=111):
    p = Participant(event_id=event_id, vk_user_id=vk_user_id, vk_name="Иван")
    session.add(p)
    await session.flush()
    await session.commit()
    return p


async def make_purchase(session, event_id, participant_id, **overrides):
    defaults = dict(status=PurchaseStatus.pending_ocr)
    defaults.update(overrides)
    purchase = Purchase(event_id=event_id, participant_id=participant_id, **defaults)
    session.add(purchase)
    await session.flush()
    await session.commit()
    return purchase


# 1. is_keyword_match ---------------------------------------------------------

def test_is_keyword_match_word_boundary():
    assert dialog.is_keyword_match("хочу участвовать розыгрыш", "розыгрыш") is True


def test_is_keyword_match_not_substring():
    assert dialog.is_keyword_match("розыгрышный билет", "розыгрыш") is False


def test_is_keyword_match_case_insensitive():
    assert dialog.is_keyword_match("Хочу РОЗЫГРЫШ участвовать", "розыгрыш") is True


def test_is_keyword_match_empty_keyword():
    assert dialog.is_keyword_match("любой текст", "") is False


# 2. is_event_open --------------------------------------------------------------

def _make_event_obj(**overrides):
    class FakeEvent:
        pass

    e = FakeEvent()
    e.is_active = overrides.get("is_active", True)
    e.starts_at = overrides.get("starts_at", None)
    e.ends_at = overrides.get("ends_at", None)
    return e


def test_is_event_open_active_no_bounds():
    e = _make_event_obj()
    assert dialog.is_event_open(e, datetime.now(timezone.utc)) is True


def test_is_event_open_inactive():
    e = _make_event_obj(is_active=False)
    assert dialog.is_event_open(e, datetime.now(timezone.utc)) is False


def test_is_event_open_before_start():
    now = datetime.now(timezone.utc)
    e = _make_event_obj(starts_at=now + timedelta(days=1))
    assert dialog.is_event_open(e, now) is False


def test_is_event_open_after_end():
    now = datetime.now(timezone.utc)
    e = _make_event_obj(ends_at=now - timedelta(days=1))
    assert dialog.is_event_open(e, now) is False


def test_is_event_open_within_window():
    now = datetime.now(timezone.utc)
    e = _make_event_obj(starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=1))
    assert dialog.is_event_open(e, now) is True


# 3. find_matching_event --------------------------------------------------------

async def test_find_matching_event_by_keyword(session):
    event1 = await make_event(session, keyword="word1")
    await make_event(session, keyword="word2")

    found = await dialog.find_matching_event(session, "хочу word1 участвовать")
    assert found is not None
    assert found.id == event1.id


async def test_find_matching_event_no_match(session):
    await make_event(session, keyword="word1")
    await make_event(session, keyword="word2")

    found = await dialog.find_matching_event(session, "случайный текст без слов")
    assert found is None


async def test_find_matching_event_stopped_not_found(session):
    event = await make_event(session, keyword="word1", is_active=False)

    found = await dialog.find_matching_event(session, "хочу word1 участвовать")
    assert found is None
    assert event.is_active is False


# 4. set_dialog / get_dialog_event_id / clear_dialog ----------------------------

async def test_dialog_state_set_get_clear(session):
    event1 = await make_event(session, keyword="word1")
    event2 = await make_event(session, keyword="word2")
    vk_user_id = 555

    await dialog.set_dialog(session, vk_user_id, event1.id)
    await session.commit()
    assert await dialog.get_dialog_event_id(session, vk_user_id) == event1.id

    # перезапись на другое событие — остаётся одна строка
    await dialog.set_dialog(session, vk_user_id, event2.id)
    await session.commit()
    assert await dialog.get_dialog_event_id(session, vk_user_id) == event2.id

    from sqlalchemy import select
    from app.core.models import BotDialogState

    result = await session.execute(
        select(BotDialogState).where(BotDialogState.vk_user_id == vk_user_id)
    )
    assert len(result.scalars().all()) == 1

    await dialog.clear_dialog(session, vk_user_id)
    await session.commit()
    assert await dialog.get_dialog_event_id(session, vk_user_id) is None


async def test_get_dialog_event_id_missing(session):
    assert await dialog.get_dialog_event_id(session, 999) is None


async def test_clear_dialog_missing_does_not_raise(session):
    await dialog.clear_dialog(session, 999)  # не должно бросать


# 5. compute_receipt_hash --------------------------------------------------------

def test_compute_receipt_hash_same_content_same_hash():
    content = b"some receipt bytes"
    assert dialog.compute_receipt_hash(content) == dialog.compute_receipt_hash(content)


def test_compute_receipt_hash_different_content_different_hash():
    h1 = dialog.compute_receipt_hash(b"content A")
    h2 = dialog.compute_receipt_hash(b"content B")
    assert h1 != h2


# 6. is_duplicate_receipt --------------------------------------------------------

async def test_is_duplicate_receipt(session):
    event = await make_event(session)
    participant = await make_participant(session, event.id)
    receipt_hash = dialog.compute_receipt_hash(b"receipt content")
    await make_purchase(session, event.id, participant.id, receipt_hash=receipt_hash)

    assert await dialog.is_duplicate_receipt(session, event.id, receipt_hash) is True
    assert await dialog.is_duplicate_receipt(session, event.id, "other-hash") is False


# 7. process_receipt --------------------------------------------------------------

async def test_process_receipt_creates_participant_and_purchase(session):
    event = await make_event(session)

    purchase = await dialog.process_receipt(
        session,
        event=event,
        vk_user_id=777,
        vk_name="Иван Иванов",
        vk_link="https://vk.com/id777",
        message_text="Иван +7 900 123 45 67",
        receipt_file_path="/tmp/receipt.jpg",
        receipt_hash="hash1",
    )
    await session.commit()

    assert purchase.id is not None
    assert purchase.event_id == event.id

    from sqlalchemy import select

    result = await session.execute(
        select(Participant).where(Participant.id == purchase.participant_id)
    )
    participant = result.scalar_one()
    assert participant.provided_name == "Иван"
    assert participant.phone == "+79001234567"


async def test_process_receipt_duplicate_goes_to_manual_review(session):
    event = await make_event(session, auto_confirm=True)

    purchase = await dialog.process_receipt(
        session,
        event=event,
        vk_user_id=778,
        message_text="Пётр",
        receipt_file_path="/tmp/receipt2.jpg",
        receipt_hash="hash2",
        ocr_amount=Decimal("500"),
        recipient_found=True,
        is_duplicate=True,
    )
    await session.commit()

    assert purchase.status == PurchaseStatus.manual_review


async def test_process_receipt_auto_confirm_approved(session):
    event = await make_event(session, auto_confirm=True, price=Decimal("250"))

    purchase = await dialog.process_receipt(
        session,
        event=event,
        vk_user_id=779,
        message_text="Мария",
        receipt_file_path="/tmp/receipt3.jpg",
        receipt_hash="hash3",
        ocr_amount=Decimal("500"),
        recipient_found=True,
        is_duplicate=False,
    )
    await session.commit()

    assert purchase.status == PurchaseStatus.approved


# 8. resolve_event_for_receipt ----------------------------------------------------

async def test_resolve_event_for_receipt_active_event(session):
    event = await make_event(session, keyword="word1")
    vk_user_id = 333
    await dialog.set_dialog(session, vk_user_id, event.id)
    await session.commit()

    resolved = await dialog.resolve_event_for_receipt(session, vk_user_id)
    assert resolved is not None
    assert resolved.id == event.id


async def test_resolve_event_for_receipt_stopped_event_returns_none(session):
    event = await make_event(session, keyword="word1")
    vk_user_id = 334
    await dialog.set_dialog(session, vk_user_id, event.id)
    await session.commit()

    event.is_active = False
    await session.commit()

    resolved = await dialog.resolve_event_for_receipt(session, vk_user_id)
    assert resolved is None


async def test_resolve_event_for_receipt_no_context_returns_none(session):
    resolved = await dialog.resolve_event_for_receipt(session, 999999)
    assert resolved is None

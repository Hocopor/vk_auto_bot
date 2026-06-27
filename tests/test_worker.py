from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core import models  # noqa: F401  (наполняет Base.metadata)
from app.core.db import Base
from app.core.models import Event, Participant, Purchase, PosterNumber, PurchaseStatus
from app.bot.worker import process_pending
from app.core.services import public_table


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


def make_callbacks():
    """Возвращает (send, sent) — мок-колбэк отправки + аккумулятор вызовов."""
    sent: list[tuple[int, str]] = []

    async def send_message(vk_user_id, text, attachment=None):
        sent.append((vk_user_id, text))

    return send_message, sent


async def setup_purchase(
    session,
    *,
    status=PurchaseStatus.approved,
    posters_count=4,
    numbers_assigned=False,
    provided_name="Иван",
    phone="+79001234567",
    number_min=1,
    number_max=10,
    amount=Decimal("1000"),
    send_after_payment=True,
    send_need_contacts=True,
):
    event = Event(
        name="Розыгрыш",
        keyword="роза",
        is_active=True,
        price=Decimal("250"),
        number_min=number_min,
        number_max=number_max,
        winners_count=1,
        msg_after_payment="Номера: {numbers} ({count})",
        msg_need_contacts="Пришлите контакты",
        auto_confirm=False,
        send_after_payment=send_after_payment,
        send_need_contacts=send_need_contacts,
    )
    session.add(event)
    await session.flush()
    participant = Participant(
        event_id=event.id,
        vk_user_id=555,
        provided_name=provided_name,
        phone=phone,
    )
    session.add(participant)
    await session.flush()
    purchase = Purchase(
        event_id=event.id,
        participant_id=participant.id,
        amount=amount,
        posters_count=posters_count,
        status=status,
        numbers_assigned=numbers_assigned,
    )
    session.add(purchase)
    await session.commit()
    return event, participant, purchase


async def test_assigns_and_sends(session):
    event, participant, purchase = await setup_purchase(session, posters_count=4)
    send, sent = make_callbacks()

    processed = await process_pending(session, send_message=send)

    assert processed == 1
    await session.refresh(purchase)
    assert purchase.numbers_assigned is True
    nums = (
        await session.execute(
            select(PosterNumber.number).where(PosterNumber.event_id == event.id)
        )
    ).scalars().all()
    assert len(nums) == 4
    assert len(set(nums)) == 4
    assert all(1 <= n <= 10 for n in nums)
    # сообщение с номерами отправлено
    assert any(str(sorted(nums)[0]) in text for _, text in sent)


async def test_need_contacts_sent_when_missing(session):
    await setup_purchase(session, provided_name=None, phone=None)
    send, sent = make_callbacks()

    await process_pending(session, send_message=send)

    assert any("контакты" in text.lower() for _, text in sent)
    assert len(sent) == 2  # after_payment + need_contacts


async def test_need_contacts_not_sent_when_present(session):
    await setup_purchase(session, provided_name="Иван", phone="+79001234567")
    send, sent = make_callbacks()

    await process_pending(session, send_message=send)

    assert len(sent) == 1  # только after_payment
    assert not any("контакты" in text.lower() for _, text in sent)


async def test_skips_already_assigned(session):
    await setup_purchase(session, numbers_assigned=True)
    send, sent = make_callbacks()

    processed = await process_pending(session, send_message=send)

    assert processed == 0
    assert sent == []


async def test_non_approved_ignored(session):
    await setup_purchase(session, status=PurchaseStatus.manual_review)
    send, sent = make_callbacks()

    processed = await process_pending(session, send_message=send)

    assert processed == 0
    assert sent == []


async def test_numbers_exhausted_does_not_crash(session):
    event, participant, purchase = await setup_purchase(
        session, number_min=1, number_max=2, posters_count=5
    )
    send, sent = make_callbacks()

    processed = await process_pending(session, send_message=send)

    assert processed == 0
    await session.refresh(purchase)
    assert purchase.numbers_assigned is False
    nums = (
        await session.execute(
            select(PosterNumber).where(PosterNumber.event_id == event.id)
        )
    ).scalars().all()
    assert nums == []
    assert sent == []


async def test_send_failure_does_not_block(session):
    event, participant, purchase = await setup_purchase(session, posters_count=2)

    async def failing_send(vk_user_id, text, attachment=None):
        raise RuntimeError("VK API down")

    processed = await process_pending(session, send_message=failing_send)

    assert processed == 1
    await session.refresh(purchase)
    assert purchase.numbers_assigned is True  # номера присвоены несмотря на сбой отправки


async def test_send_after_payment_disabled_still_assigns_numbers(session):
    event, participant, purchase = await setup_purchase(
        session, posters_count=3, send_after_payment=False
    )
    send, sent = make_callbacks()

    processed = await process_pending(session, send_message=send)

    assert processed == 1
    await session.refresh(purchase)
    assert purchase.numbers_assigned is True
    # after_payment отключён -> ничего не отправлено (need_contacts не нужен, контакты есть)
    assert sent == []


async def test_send_need_contacts_disabled(session):
    await setup_purchase(
        session, provided_name=None, phone=None, send_need_contacts=False
    )
    send, sent = make_callbacks()

    await process_pending(session, send_message=send)

    # after_payment отправлен, need_contacts — отключён тумблером
    assert len(sent) == 1
    assert not any("контакты" in text.lower() for _, text in sent)


async def test_idempotent_second_run(session):
    event, participant, purchase = await setup_purchase(session, posters_count=3)
    send, sent = make_callbacks()

    first = await process_pending(session, send_message=send)
    count_after_first = len(
        (
            await session.execute(
                select(PosterNumber).where(PosterNumber.event_id == event.id)
            )
        ).scalars().all()
    )
    second = await process_pending(session, send_message=send)
    count_after_second = len(
        (
            await session.execute(
                select(PosterNumber).where(PosterNumber.event_id == event.id)
            )
        ).scalars().all()
    )

    assert first == 1
    assert second == 0
    assert count_after_first == count_after_second == 3


async def test_sync_google_sheet_called_when_url_set(session):
    """When event has google_sheet_url, sync should be called after processing."""
    event, participant, purchase = await setup_purchase(session, posters_count=2)
    event.google_sheet_url = "https://docs.google.com/spreadsheets/d/test123/edit"
    await session.commit()

    send, sent = make_callbacks()
    sync_called = []

    async def mock_sync(sess, eid, url):
        sync_called.append((eid, url))

    with patch("app.sheets.sync.sync_event_to_sheet", mock_sync):
        processed = await process_pending(session, send_message=send)

    assert processed == 1
    assert len(sync_called) == 1
    assert sync_called[0] == (event.id, event.google_sheet_url)


async def test_sync_google_sheet_not_called_when_url_empty(session):
    """When event has no google_sheet_url, sync should NOT be called."""
    event, participant, purchase = await setup_purchase(session, posters_count=2)
    send, sent = make_callbacks()
    sync_called = []

    async def mock_sync(sess, eid, url):
        sync_called.append((eid, url))

    with patch("app.sheets.sync.sync_event_to_sheet", mock_sync):
        processed = await process_pending(session, send_message=send)

    assert processed == 1
    assert sync_called == []


async def test_after_payment_uses_google_sheet_reader_url_when_set(session):
    """When event.google_sheet_url is set, the {sheet_url} placeholder in the
    after-payment message must resolve to the read-only Google Sheets preview link,
    not the local public table URL."""
    event, participant, purchase = await setup_purchase(session, posters_count=2)
    event.google_sheet_url = "https://docs.google.com/spreadsheets/d/ABC123/edit"
    event.msg_after_payment = "Таблица: {sheet_url}"
    await session.commit()

    send, sent = make_callbacks()

    async def mock_sync(sess, eid, url):
        return None

    with patch("app.sheets.sync.sync_event_to_sheet", mock_sync):
        processed = await process_pending(session, send_message=send)

    assert processed == 1
    assert len(sent) == 1
    _, text = sent[0]
    assert "https://docs.google.com/spreadsheets/d/ABC123/preview" in text


async def test_after_payment_uses_public_table_url_when_no_google_sheet(session):
    """When event.google_sheet_url is not set, {sheet_url} falls back to the
    local public table URL (/p/{event_id})."""
    event, participant, purchase = await setup_purchase(session, posters_count=2)
    event.msg_after_payment = "Таблица: {sheet_url}"
    await session.commit()

    send, sent = make_callbacks()

    processed = await process_pending(session, send_message=send)

    assert processed == 1
    assert len(sent) == 1
    _, text = sent[0]
    assert public_table.public_table_url(event.id) in text


async def test_sync_failure_does_not_block_worker(session):
    """If sync fails, worker should continue processing."""
    event, participant, purchase = await setup_purchase(session, posters_count=2)
    event.google_sheet_url = "https://docs.google.com/spreadsheets/d/test123/edit"
    await session.commit()

    send, sent = make_callbacks()

    async def failing_sync(sess, eid, url):
        raise RuntimeError("Google API down")

    with patch("app.sheets.sync.sync_event_to_sheet", failing_sync):
        processed = await process_pending(session, send_message=send)

    assert processed == 1
    await session.refresh(purchase)
    assert purchase.numbers_assigned is True
    assert len(sent) == 1

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core import models  # noqa: F401  (наполняет Base.metadata)
from app.core.db import Base
from app.core.models import Event, Participant, Purchase, PosterNumber, PurchaseStatus
from app.core.placeholders import render, format_numbers
from app.core.services.participants import parse_phone, parse_name_and_phone, upsert_participant
from app.core.services.numbers import count_posters, assign_unique, free_numbers, NumbersExhausted
from app.core.services.purchases import decide_after_ocr, approve, revoke
from app.core.services.winners import pick_winners
from app.core.services.events import create_event, delete_event


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
        keyword="тест",
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


# 1. render -----------------------------------------------------------------

def test_render_known_token():
    result = render("Привет, {name}!", {"name": "Иван"})
    assert result == "Привет, Иван!"


def test_render_unknown_token_stays():
    result = render("Значение: {foo}", {"name": "Иван"})
    assert result == "Значение: {foo}"


def test_render_no_tokens_unchanged():
    text = "Просто текст без плейсхолдеров"
    assert render(text, {"name": "Иван"}) == text


def test_render_empty_template():
    assert render("", {"name": "Иван"}) == ""
    assert render(None, {"name": "Иван"}) == ""


def test_format_numbers():
    assert format_numbers([1, 2, 3]) == "1, 2, 3"
    assert format_numbers([]) == ""


# 2. parse_phone --------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "8 900 123-45-67",
        "+79001234567",
        "79001234567",
    ],
)
def test_parse_phone_normalizes(text):
    assert parse_phone(text) == "+79001234567"


def test_parse_phone_none_when_missing():
    assert parse_phone("Привет, меня зовут Иван") is None


# 3. parse_name_and_phone -----------------------------------------------------

def test_parse_name_and_phone():
    name, phone = parse_name_and_phone("Иван +7 900 123 45 67")
    assert name == "Иван"
    assert phone == "+79001234567"


def test_parse_name_and_phone_no_phone():
    name, phone = parse_name_and_phone("Просто Иван без телефона")
    assert phone is None
    assert name == "Просто Иван без телефона"


# 4. count_posters -------------------------------------------------------------

@pytest.mark.parametrize(
    "amount,price,expected",
    [
        (Decimal("1000"), Decimal("250"), 4),
        (Decimal("900"), Decimal("250"), 3),
        (Decimal("100"), Decimal("250"), 0),
        (None, Decimal("250"), 0),
    ],
)
def test_count_posters(amount, price, expected):
    assert count_posters(amount, price) == expected


# 5. create_event ---------------------------------------------------------------

async def test_create_event_defaults_and_keyword_normalized(session):
    event = await make_event(session, keyword="  ТеСт  ")
    assert event.keyword == "тест"
    assert event.msg_instruction
    assert event.msg_after_payment
    assert event.msg_receipt_received
    assert event.msg_need_contacts


# 6. assign_unique ----------------------------------------------------------------

async def test_assign_unique_success_and_exhaustion(session):
    event = await make_event(session, number_min=1, number_max=5)
    participant = await make_participant(session, event.id)
    purchase = await make_purchase(session, event.id, participant.id)

    numbers = await assign_unique(session, event.id, participant.id, purchase.id, 3)
    await session.commit()

    assert len(numbers) == 3
    assert len(set(numbers)) == 3
    assert all(1 <= n <= 5 for n in numbers)

    purchase2 = await make_purchase(session, event.id, participant.id)
    with pytest.raises(NumbersExhausted):
        await assign_unique(session, event.id, participant.id, purchase2.id, 3)


# 7. free_numbers / revoke -------------------------------------------------------

async def test_revoke_frees_numbers_and_reassign(session):
    event = await make_event(session, number_min=1, number_max=5)
    participant = await make_participant(session, event.id)
    purchase = await make_purchase(session, event.id, participant.id)

    numbers = await assign_unique(session, event.id, participant.id, purchase.id, 3)
    await session.commit()

    freed = await revoke(session, purchase, moderated_by="admin")
    await session.commit()

    assert freed == 3
    assert purchase.status == PurchaseStatus.revoked
    assert purchase.numbers_assigned is False

    result = await session.execute(
        select(PosterNumber).where(PosterNumber.purchase_id == purchase.id)
    )
    assert result.scalars().all() == []

    purchase2 = await make_purchase(session, event.id, participant.id)
    numbers2 = await assign_unique(session, event.id, participant.id, purchase2.id, 3)
    await session.commit()
    assert len(numbers2) == 3
    assert set(numbers2).issubset(set(numbers) | (set(range(1, 6)) - set(numbers)))


# 8. pick_winners -----------------------------------------------------------------

async def test_pick_winners(session):
    event = await make_event(session, number_min=1, number_max=10, winners_count=2)
    participant = await make_participant(session, event.id)
    purchase = await make_purchase(session, event.id, participant.id, status=PurchaseStatus.approved)

    await assign_unique(session, event.id, participant.id, purchase.id, 5)
    await session.commit()

    winners = await pick_winners(session, event.id)
    assert len(winners) == 2
    assert len({w.number for w in winners}) == 2


# 9. decide_after_ocr --------------------------------------------------------------

async def test_decide_after_ocr_auto_confirm_approved(session):
    event = await make_event(session, auto_confirm=True, price=Decimal("250"))
    participant = await make_participant(session, event.id)
    purchase = await make_purchase(
        session, event.id, participant.id, ocr_amount=Decimal("500")
    )

    status = await decide_after_ocr(session, purchase, event, recipient_found=True)
    await session.commit()

    assert status == PurchaseStatus.approved
    assert purchase.posters_count == 2


async def test_decide_after_ocr_no_auto_confirm_manual_review(session):
    event = await make_event(session, auto_confirm=False, price=Decimal("250"))
    participant = await make_participant(session, event.id)
    purchase = await make_purchase(
        session, event.id, participant.id, ocr_amount=Decimal("500")
    )

    status = await decide_after_ocr(session, purchase, event, recipient_found=True)
    await session.commit()

    assert status == PurchaseStatus.manual_review


async def test_decide_after_ocr_wrong_recipient_manual_review(session):
    event = await make_event(session, auto_confirm=True, price=Decimal("250"))
    participant = await make_participant(session, event.id)
    purchase = await make_purchase(
        session, event.id, participant.id, ocr_amount=Decimal("500")
    )

    status = await decide_after_ocr(session, purchase, event, recipient_found=False)
    await session.commit()

    assert status == PurchaseStatus.manual_review


# 10. delete_event ------------------------------------------------------------------

async def test_delete_event_cascades(session):
    event = await make_event(session, number_min=1, number_max=5)
    participant = await make_participant(session, event.id)
    purchase = await make_purchase(session, event.id, participant.id)
    await assign_unique(session, event.id, participant.id, purchase.id, 2)
    await session.commit()

    event_id = event.id
    deleted = await delete_event(session, event_id)
    await session.commit()

    assert deleted is True

    result = await session.execute(select(Purchase).where(Purchase.event_id == event_id))
    assert result.scalars().all() == []

    result = await session.execute(select(Participant).where(Participant.event_id == event_id))
    assert result.scalars().all() == []

    result = await session.execute(select(PosterNumber).where(PosterNumber.event_id == event_id))
    assert result.scalars().all() == []


async def test_delete_event_missing_returns_false(session):
    deleted = await delete_event(session, 999999)
    assert deleted is False

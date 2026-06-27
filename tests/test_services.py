from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core import models  # noqa: F401  (наполняет Base.metadata)
from app.core import timeutil
from app.core.db import Base
from app.core.models import Event, Participant, Purchase, PosterNumber, PurchaseStatus
from app.core.placeholders import render, format_numbers
from app.core.services import abuse
from app.core.services import app_settings as app_settings_svc
from app.core.services.participants import parse_phone, parse_name_and_phone, upsert_participant
from app.core.services.numbers import count_posters, assign_unique, free_numbers, NumbersExhausted
from app.core.services.purchases import decide_after_ocr, evaluate_payment, approve, reject, can_approve
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


# 7. free_numbers / reject -------------------------------------------------------

async def test_reject_frees_numbers_and_reassign(session):
    event = await make_event(session, number_min=1, number_max=5)
    participant = await make_participant(session, event.id)
    purchase = await make_purchase(session, event.id, participant.id)

    numbers = await assign_unique(session, event.id, participant.id, purchase.id, 3)
    await session.commit()

    freed = await reject(session, purchase, moderated_by="admin")
    await session.commit()

    assert freed == 3
    assert purchase.status == PurchaseStatus.rejected
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


async def test_approve_resets_stale_assigned_flag(session):
    event = await make_event(session, number_min=1, number_max=5, price=Decimal("250"))
    participant = await make_participant(session, event.id)
    purchase = await make_purchase(
        session,
        event.id,
        participant.id,
        status=PurchaseStatus.approved,
        amount=Decimal("500"),
        numbers_assigned=True,
    )
    await session.commit()

    await approve(session, purchase, event=event)
    await session.commit()

    assert purchase.numbers_assigned is False
    assert purchase.posters_count == 2

    purchase2 = await make_purchase(
        session,
        event.id,
        participant.id,
        status=PurchaseStatus.approved,
        amount=Decimal("500"),
        numbers_assigned=False,
    )
    await assign_unique(session, event.id, participant.id, purchase2.id, 2)
    purchase2.numbers_assigned = True
    await session.commit()

    await approve(session, purchase2, event=event)
    await session.commit()

    assert purchase2.numbers_assigned is True


def test_can_approve():
    event = type("E", (), {"price": Decimal("250")})()
    purchase_none = type("P", (), {"amount": None})()
    purchase_low = type("P", (), {"amount": Decimal("100")})()
    purchase_ok = type("P", (), {"amount": Decimal("250")})()
    purchase_more = type("P", (), {"amount": Decimal("600")})()

    assert can_approve(purchase_none, event) is False
    assert can_approve(purchase_low, event) is False
    assert can_approve(purchase_ok, event) is True
    assert can_approve(purchase_more, event) is True


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

    status = await decide_after_ocr(
        session, purchase, event, recipient_found=True, receipt_date=date.today()
    )
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


# 9b. evaluate_payment (без требования кратности) -----------------------------------

def test_evaluate_payment_covers_one_ticket():
    assert evaluate_payment(Decimal("500"), Decimal("250"), True) is True


def test_evaluate_payment_non_multiple_ok():
    # сумма НЕ кратна цене, но покрывает билет — теперь True (остаток игнорируем)
    assert evaluate_payment(Decimal("300"), Decimal("250"), True) is True


def test_evaluate_payment_below_price():
    assert evaluate_payment(Decimal("200"), Decimal("250"), True) is False


def test_evaluate_payment_wrong_recipient():
    assert evaluate_payment(Decimal("500"), Decimal("250"), False) is False


def test_evaluate_payment_none_amount():
    assert evaluate_payment(None, Decimal("250"), True) is False


# 9c. abuse.is_date_fresh -----------------------------------------------------------

_NOW = datetime(2026, 6, 27, 9, 0, tzinfo=timezone.utc)
_TODAY = timeutil.to_local(_NOW).date()


def test_is_date_fresh_today():
    assert abuse.is_date_fresh(_TODAY, _NOW, max_age_days=3) is True


def test_is_date_fresh_within_window():
    assert abuse.is_date_fresh(_TODAY - timedelta(days=2), _NOW, max_age_days=3) is True


def test_is_date_fresh_too_old():
    assert abuse.is_date_fresh(_TODAY - timedelta(days=10), _NOW, max_age_days=3) is False


def test_is_date_fresh_future():
    assert abuse.is_date_fresh(_TODAY + timedelta(days=1), _NOW, max_age_days=3) is False


def test_is_date_fresh_none_disallowed():
    assert abuse.is_date_fresh(None, _NOW, allow_without_date=False) is False


def test_is_date_fresh_none_allowed():
    assert abuse.is_date_fresh(None, _NOW, allow_without_date=True) is True


# 9d. abuse.is_duplicate_global -----------------------------------------------------

async def test_is_duplicate_global_same_hash_active(session):
    event = await make_event(session)
    p1 = await make_participant(session, event.id, vk_user_id=111)
    p2 = await make_participant(session, event.id, vk_user_id=222)
    other = await make_purchase(
        session, event.id, p1.id, receipt_hash="h1", status=PurchaseStatus.approved
    )
    current = await make_purchase(
        session, event.id, p2.id, receipt_hash="h1", status=PurchaseStatus.pending_ocr
    )
    assert await abuse.is_duplicate_global(
        session, "h1", exclude_purchase_id=current.id
    ) is True
    _ = other


async def test_is_duplicate_global_rejected_does_not_count(session):
    event = await make_event(session)
    p1 = await make_participant(session, event.id, vk_user_id=111)
    p2 = await make_participant(session, event.id, vk_user_id=222)
    await make_purchase(
        session, event.id, p1.id, receipt_hash="h2", status=PurchaseStatus.rejected
    )
    current = await make_purchase(
        session, event.id, p2.id, receipt_hash="h2", status=PurchaseStatus.pending_ocr
    )
    assert await abuse.is_duplicate_global(
        session, "h2", exclude_purchase_id=current.id
    ) is False


async def test_is_duplicate_global_same_signature(session):
    event = await make_event(session)
    p1 = await make_participant(session, event.id, vk_user_id=111)
    p2 = await make_participant(session, event.id, vk_user_id=222)
    await make_purchase(
        session, event.id, p1.id, receipt_signature="OP123", status=PurchaseStatus.approved
    )
    current = await make_purchase(
        session, event.id, p2.id, receipt_signature="OP123", status=PurchaseStatus.pending_ocr
    )
    assert await abuse.is_duplicate_global(
        session, None, "OP123", exclude_purchase_id=current.id
    ) is True


async def test_is_duplicate_global_unique(session):
    event = await make_event(session)
    p1 = await make_participant(session, event.id, vk_user_id=111)
    current = await make_purchase(
        session, event.id, p1.id, receipt_hash="uniq", status=PurchaseStatus.pending_ocr
    )
    assert await abuse.is_duplicate_global(
        session, "uniq", exclude_purchase_id=current.id
    ) is False


# 9e. abuse.load_gate_config --------------------------------------------------------

async def test_load_gate_config_defaults(session):
    max_age, allow = await abuse.load_gate_config(session)
    assert max_age == 3
    assert allow is False


async def test_load_gate_config_custom(session):
    await app_settings_svc.set_setting(
        session, app_settings_svc.KEY_RECEIPT_MAX_AGE_DAYS, "7"
    )
    await app_settings_svc.set_setting(
        session, app_settings_svc.KEY_AUTOCONFIRM_WITHOUT_DATE, "true"
    )
    await session.commit()
    max_age, allow = await abuse.load_gate_config(session)
    assert max_age == 7
    assert allow is True


# 9f. decide_after_ocr + abuse-гейт -------------------------------------------------

async def _auto_event(session):
    return await make_event(session, auto_confirm=True, price=Decimal("250"))


async def test_decide_auto_fresh_date_approved(session):
    event = await _auto_event(session)
    p = await make_participant(session, event.id)
    purchase = await make_purchase(
        session, event.id, p.id, ocr_amount=Decimal("500"), receipt_hash="d1"
    )
    status = await decide_after_ocr(
        session, purchase, event, recipient_found=True,
        receipt_date=_TODAY, now=_NOW,
    )
    await session.commit()
    assert status == PurchaseStatus.approved
    assert purchase.posters_count == 2
    assert purchase.needs_attention is False


async def test_decide_auto_future_date_flagged(session):
    event = await _auto_event(session)
    p = await make_participant(session, event.id)
    purchase = await make_purchase(
        session, event.id, p.id, ocr_amount=Decimal("500"), receipt_hash="d2"
    )
    status = await decide_after_ocr(
        session, purchase, event, recipient_found=True,
        receipt_date=_TODAY + timedelta(days=2), now=_NOW,
    )
    await session.commit()
    assert status == PurchaseStatus.manual_review
    assert purchase.needs_attention is True


async def test_decide_auto_old_date_flagged(session):
    event = await _auto_event(session)
    p = await make_participant(session, event.id)
    purchase = await make_purchase(
        session, event.id, p.id, ocr_amount=Decimal("500"), receipt_hash="d3"
    )
    status = await decide_after_ocr(
        session, purchase, event, recipient_found=True,
        receipt_date=_TODAY - timedelta(days=30), now=_NOW,
    )
    await session.commit()
    assert status == PurchaseStatus.manual_review
    assert purchase.needs_attention is True


async def test_decide_auto_no_date_disallowed_flagged(session):
    event = await _auto_event(session)
    p = await make_participant(session, event.id)
    purchase = await make_purchase(
        session, event.id, p.id, ocr_amount=Decimal("500"), receipt_hash="d4"
    )
    status = await decide_after_ocr(
        session, purchase, event, recipient_found=True,
        receipt_date=None, now=_NOW, allow_without_date=False,
    )
    await session.commit()
    assert status == PurchaseStatus.manual_review
    assert purchase.needs_attention is True


async def test_decide_auto_no_date_allowed_approved(session):
    event = await _auto_event(session)
    p = await make_participant(session, event.id)
    purchase = await make_purchase(
        session, event.id, p.id, ocr_amount=Decimal("500"), receipt_hash="d5"
    )
    status = await decide_after_ocr(
        session, purchase, event, recipient_found=True,
        receipt_date=None, now=_NOW, allow_without_date=True,
    )
    await session.commit()
    assert status == PurchaseStatus.approved


async def test_decide_auto_local_duplicate_flagged(session):
    event = await _auto_event(session)
    p = await make_participant(session, event.id)
    purchase = await make_purchase(
        session, event.id, p.id, ocr_amount=Decimal("500"), receipt_hash="d6"
    )
    status = await decide_after_ocr(
        session, purchase, event, recipient_found=True,
        receipt_date=_TODAY, now=_NOW, is_duplicate=True,
    )
    await session.commit()
    assert status == PurchaseStatus.manual_review
    assert purchase.needs_attention is True


async def test_decide_auto_global_duplicate_flagged(session):
    event = await _auto_event(session)
    p1 = await make_participant(session, event.id, vk_user_id=111)
    p2 = await make_participant(session, event.id, vk_user_id=222)
    await make_purchase(
        session, event.id, p1.id, receipt_hash="dup", status=PurchaseStatus.approved
    )
    purchase = await make_purchase(
        session, event.id, p2.id, ocr_amount=Decimal("500"), receipt_hash="dup"
    )
    status = await decide_after_ocr(
        session, purchase, event, recipient_found=True,
        receipt_date=_TODAY, now=_NOW,
    )
    await session.commit()
    assert status == PurchaseStatus.manual_review
    assert purchase.needs_attention is True


async def test_decide_no_auto_confirm_no_flag(session):
    event = await make_event(session, auto_confirm=False, price=Decimal("250"))
    p = await make_participant(session, event.id)
    purchase = await make_purchase(
        session, event.id, p.id, ocr_amount=Decimal("500"), receipt_hash="d7"
    )
    status = await decide_after_ocr(
        session, purchase, event, recipient_found=True,
        receipt_date=_TODAY, now=_NOW,
    )
    await session.commit()
    assert status == PurchaseStatus.manual_review
    assert purchase.needs_attention is False


async def test_decide_wrong_recipient_no_flag(session):
    event = await _auto_event(session)
    p = await make_participant(session, event.id)
    purchase = await make_purchase(
        session, event.id, p.id, ocr_amount=Decimal("500"), receipt_hash="d8"
    )
    status = await decide_after_ocr(
        session, purchase, event, recipient_found=False,
        receipt_date=_TODAY, now=_NOW,
    )
    await session.commit()
    assert status == PurchaseStatus.manual_review
    assert purchase.needs_attention is False


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

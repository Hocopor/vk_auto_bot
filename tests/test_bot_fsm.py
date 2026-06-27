"""Тесты этапа 8.4: FSM-диалог бота — стадии, резолвер публичного имени, детектор контактов."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core import models  # noqa: F401  (наполняет Base.metadata)
from app.core.db import Base
from app.core.defaults import DEFAULT_TEXTS
from app.core.models import BotDialogState, Participant, PosterNumber, Purchase, PurchaseStatus
from app.core.services.events import create_event
from app.core.services.participants import (
    looks_like_contacts,
    resolve_public_name,
    upsert_participant,
)
from app.core.services import public_table
from app.sheets import sync as sheets_sync
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


def _make_participant(**overrides):
    class FakeParticipant:
        pass

    p = FakeParticipant()
    p.public_name = overrides.get("public_name")
    p.vk_first_name = overrides.get("vk_first_name")
    p.provided_name = overrides.get("provided_name")
    p.vk_name = overrides.get("vk_name")
    return p


# 1. resolve_public_name --------------------------------------------------------

def test_resolve_public_name_prefers_public_name_override():
    p = _make_participant(
        public_name="Админ Имя",
        vk_first_name="Вася",
        provided_name="Иван Иванов",
        vk_name="Иван Петров",
    )
    assert resolve_public_name(p) == "Админ Имя"


def test_resolve_public_name_falls_back_to_vk_first_name():
    p = _make_participant(
        public_name=None,
        vk_first_name="Вася",
        provided_name="Иван Иванов",
        vk_name="Иван Петров",
    )
    assert resolve_public_name(p) == "Вася"


def test_resolve_public_name_falls_back_to_provided_name_first_token():
    p = _make_participant(
        public_name=None,
        vk_first_name=None,
        provided_name="Иван Иванов",
        vk_name="Иван Петров",
    )
    assert resolve_public_name(p) == "Иван"


def test_resolve_public_name_falls_back_to_vk_name():
    p = _make_participant(
        public_name=None,
        vk_first_name=None,
        provided_name=None,
        vk_name="Иван Петров",
    )
    assert resolve_public_name(p) == "Иван Петров"


def test_resolve_public_name_none_when_all_empty():
    p = _make_participant(public_name=None, vk_first_name=None, provided_name=None, vk_name=None)
    assert resolve_public_name(p) is None


def test_resolve_public_name_blank_strings_treated_as_empty():
    p = _make_participant(public_name="   ", vk_first_name="  ", provided_name="  ", vk_name="Иван")
    assert resolve_public_name(p) == "Иван"


# 2. looks_like_contacts ---------------------------------------------------------

def test_looks_like_contacts_phone_present():
    assert looks_like_contacts("+79991234567") is True


def test_looks_like_contacts_two_words():
    assert looks_like_contacts("Иван Иванов") is True


def test_looks_like_contacts_single_word_false():
    assert looks_like_contacts("Иван") is False


def test_looks_like_contacts_empty_false():
    assert looks_like_contacts("") is False


def test_looks_like_contacts_phone_with_dashes():
    assert looks_like_contacts("8 900 123-45-67") is True


# 3. set_dialog / get_dialog / set_stage -----------------------------------------

async def test_set_dialog_default_stage_awaiting_receipt(session):
    event = await make_event(session, keyword="word1")
    await dialog.set_dialog(session, 100, event.id)
    await session.commit()

    state = await dialog.get_dialog(session, 100)
    assert state is not None
    assert state.stage == "awaiting_receipt"


async def test_set_dialog_new_event_resets_stage(session):
    event1 = await make_event(session, keyword="word1")
    event2 = await make_event(session, keyword="word2")

    await dialog.set_dialog(session, 101, event1.id)
    await session.commit()
    await dialog.set_stage(session, 101, "awaiting_contacts")
    await session.commit()

    state = await dialog.get_dialog(session, 101)
    assert state.stage == "awaiting_contacts"

    # переключение на новое кодовое слово -> новое событие, стадия сброшена
    await dialog.set_dialog(session, 101, event2.id)
    await session.commit()

    state = await dialog.get_dialog(session, 101)
    assert state.event_id == event2.id
    assert state.stage == "awaiting_receipt"


async def test_set_stage_changes_stage(session):
    event = await make_event(session, keyword="word1")
    await dialog.set_dialog(session, 102, event.id)
    await session.commit()

    await dialog.set_stage(session, 102, "done")
    await session.commit()

    state = await dialog.get_dialog(session, 102)
    assert state.stage == "done"


async def test_get_dialog_returns_none_when_missing(session):
    assert await dialog.get_dialog(session, 999999) is None


async def test_set_stage_noop_when_state_missing(session):
    await dialog.set_stage(session, 999999, "done")  # не должно бросать


# 4. upsert_participant с vk_first_name -------------------------------------------

async def test_upsert_participant_saves_vk_first_name(session):
    event = await make_event(session, keyword="word1")
    participant = await upsert_participant(
        session, event.id, 200, vk_name="Иван Иванов", vk_first_name="Иван"
    )
    await session.commit()
    assert participant.vk_first_name == "Иван"


async def test_upsert_participant_update_does_not_clear_vk_first_name(session):
    event = await make_event(session, keyword="word1")
    await upsert_participant(session, event.id, 201, vk_name="Иван Иванов", vk_first_name="Иван")
    await session.commit()

    updated = await upsert_participant(
        session, event.id, 201, provided_name="Иван Иванов", phone="+79001234567"
    )
    await session.commit()

    assert updated.vk_first_name == "Иван"
    assert updated.provided_name == "Иван Иванов"
    assert updated.phone == "+79001234567"


# 5. public_table / sheets resolver integration ------------------------------------

async def _seed_approved_with_number(session, event_id, *, vk_first_name=None, provided_name=None,
                                       public_name=None, vk_name=None, number=7, vk_user_id=300):
    participant = Participant(
        event_id=event_id,
        vk_user_id=vk_user_id,
        vk_name=vk_name,
        provided_name=provided_name,
        vk_first_name=vk_first_name,
        public_name=public_name,
    )
    session.add(participant)
    await session.flush()
    purchase = Purchase(
        event_id=event_id, participant_id=participant.id, status=PurchaseStatus.approved,
    )
    session.add(purchase)
    await session.flush()
    session.add(
        PosterNumber(event_id=event_id, participant_id=participant.id, purchase_id=purchase.id, number=number)
    )
    await session.commit()
    return participant


async def test_public_table_uses_vk_first_name_over_provided_name(session):
    event = await make_event(session, keyword="word1", number_max=10)
    await _seed_approved_with_number(
        session, event.id, vk_first_name="Вася", provided_name="Иван Иванов", number=3
    )

    records = await public_table.collect_records(session, event.id)
    assert len(records) == 1
    assert records[0] == (3, "Вася")


async def test_sheets_collect_uses_vk_first_name_over_provided_name(session):
    event = await make_event(session, keyword="word1", number_max=10)
    await _seed_approved_with_number(
        session, event.id, vk_first_name="Вася", provided_name="Иван Иванов", number=4
    )

    records = await sheets_sync.collect_approved_records(session, event.id)
    assert len(records) == 1
    assert records[0] == (4, "Вася")


async def test_public_table_uses_public_name_override(session):
    event = await make_event(session, keyword="word1", number_max=10)
    await _seed_approved_with_number(
        session, event.id, public_name="Особое Имя", vk_first_name="Вася",
        provided_name="Иван Иванов", number=5,
    )

    records = await public_table.collect_records(session, event.id)
    assert records[0] == (5, "Особое Имя")


# 6. defaults ----------------------------------------------------------------------

def test_default_texts_has_msg_contacts_saved():
    assert "msg_contacts_saved" in DEFAULT_TEXTS
    assert DEFAULT_TEXTS["msg_contacts_saved"]


async def test_create_event_sets_msg_contacts_saved_default(session):
    event = await make_event(session, keyword="word1")
    assert event.msg_contacts_saved == DEFAULT_TEXTS["msg_contacts_saved"]
    assert event.send_contacts_saved is True

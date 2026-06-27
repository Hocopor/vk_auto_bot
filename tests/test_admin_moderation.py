import os
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.admin.deps import get_session, require_login
from app.admin.main import app
from app.admin.routes.moderation import COLUMN_LIMIT
from app.core import models  # noqa: F401
from app.core.db import Base
from app.core.models import Participant, PosterNumber, Purchase, PurchaseStatus
from app.core.services import app_settings
from app.core.services.events import create_event


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
def maker(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def client(maker):
    async def _get_session_override():
        async with maker() as session:
            yield session

    async def _require_login_override():
        return "admin"

    app.dependency_overrides[get_session] = _get_session_override
    app.dependency_overrides[require_login] = _require_login_override

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(require_login, None)


async def make_event(maker, **overrides):
    defaults = dict(
        name="Тест", keyword="тест", price=Decimal("250"),
        number_min=1, number_max=10, winners_count=1, auto_confirm=False,
    )
    defaults.update(overrides)
    async with maker() as session:
        event = await create_event(session, **defaults)
        await session.commit()
        return event.id


async def make_participant(maker, event_id, **overrides):
    defaults = dict(vk_user_id=111, vk_name="Иван", vk_link="https://vk.com/id111")
    defaults.update(overrides)
    async with maker() as session:
        p = Participant(event_id=event_id, **defaults)
        session.add(p)
        await session.flush()
        await session.commit()
        return p.id


async def make_purchase(maker, event_id, participant_id, **overrides):
    defaults = dict(status=PurchaseStatus.manual_review, amount=Decimal("1000"))
    defaults.update(overrides)
    async with maker() as session:
        purchase = Purchase(event_id=event_id, participant_id=participant_id, **defaults)
        session.add(purchase)
        await session.flush()
        await session.commit()
        return purchase.id


async def test_queue_lists_manual_review(client, maker):
    event_id = await make_event(maker)
    participant_id = await make_participant(maker, event_id, provided_name="Иван Петров")
    await make_purchase(maker, event_id, participant_id, status=PurchaseStatus.manual_review)

    resp = await client.get("/moderation", params={"status": "manual_review", "view": "list"})
    assert resp.status_code == 200
    assert "Иван Петров" in resp.text


async def test_detail_shows_full_info(client, maker):
    event_id = await make_event(maker)
    participant_id = await make_participant(
        maker, event_id, vk_link="https://vk.com/id111", provided_name="Пётр Иванов"
    )
    purchase_id = await make_purchase(maker, event_id, participant_id, amount=Decimal("1000"))

    resp = await client.get(f"/moderation/{purchase_id}")
    assert resp.status_code == 200
    assert "https://vk.com/id111" in resp.text
    assert "Пётр Иванов" in resp.text
    assert "1000" in resp.text


async def test_approve(client, maker):
    event_id = await make_event(maker)
    participant_id = await make_participant(maker, event_id)
    purchase_id = await make_purchase(maker, event_id, participant_id)

    resp = await client.post(f"/moderation/{purchase_id}/approve", follow_redirects=False)
    assert resp.status_code == 303

    async with maker() as session:
        purchase = await session.get(Purchase, purchase_id)
        assert purchase.status == PurchaseStatus.approved
        assert purchase.moderated_by == "admin"


async def test_reject(client, maker):
    event_id = await make_event(maker)
    participant_id = await make_participant(maker, event_id)
    purchase_id = await make_purchase(maker, event_id, participant_id)

    resp = await client.post(f"/moderation/{purchase_id}/reject", follow_redirects=False)
    assert resp.status_code == 303

    async with maker() as session:
        purchase = await session.get(Purchase, purchase_id)
        assert purchase.status == PurchaseStatus.rejected
        assert purchase.moderated_by == "admin"


async def test_reject_frees_numbers(client, maker):
    event_id = await make_event(maker)
    participant_id = await make_participant(maker, event_id)
    purchase_id = await make_purchase(
        maker, event_id, participant_id, status=PurchaseStatus.approved, numbers_assigned=True
    )

    async with maker() as session:
        for n in (1, 2, 3):
            session.add(
                PosterNumber(
                    event_id=event_id,
                    participant_id=participant_id,
                    purchase_id=purchase_id,
                    number=n,
                )
            )
        await session.commit()

    resp = await client.post(f"/moderation/{purchase_id}/reject", follow_redirects=False)
    assert resp.status_code == 303

    async with maker() as session:
        result = await session.execute(
            select(PosterNumber).where(PosterNumber.purchase_id == purchase_id)
        )
        assert result.scalars().all() == []

        purchase = await session.get(Purchase, purchase_id)
        assert purchase.status == PurchaseStatus.rejected
        assert purchase.numbers_assigned is False


async def test_approve_blocked_without_amount(client, maker):
    event_id = await make_event(maker, price=Decimal("250"))
    participant_id = await make_participant(maker, event_id)
    purchase_id = await make_purchase(
        maker, event_id, participant_id, status=PurchaseStatus.manual_review, amount=None
    )

    resp = await client.post(f"/moderation/{purchase_id}/approve", follow_redirects=False)
    assert resp.status_code == 303
    assert "error=amount" in resp.headers["location"]

    async with maker() as session:
        purchase = await session.get(Purchase, purchase_id)
        assert purchase.status == PurchaseStatus.manual_review


async def test_approve_with_amount_works(client, maker):
    event_id = await make_event(maker, price=Decimal("250"))
    participant_id = await make_participant(maker, event_id)
    purchase_id = await make_purchase(
        maker, event_id, participant_id, status=PurchaseStatus.manual_review, amount=Decimal("500")
    )

    resp = await client.post(f"/moderation/{purchase_id}/approve", follow_redirects=False)
    assert resp.status_code == 303

    async with maker() as session:
        purchase = await session.get(Purchase, purchase_id)
        assert purchase.status == PurchaseStatus.approved
        assert purchase.posters_count == 2


async def test_reject_then_approve_redelivers(client, maker):
    event_id = await make_event(maker, price=Decimal("250"))
    participant_id = await make_participant(maker, event_id)
    purchase_id = await make_purchase(
        maker,
        event_id,
        participant_id,
        status=PurchaseStatus.approved,
        amount=Decimal("500"),
        numbers_assigned=True,
    )

    async with maker() as session:
        for n in (1, 2):
            session.add(
                PosterNumber(
                    event_id=event_id,
                    participant_id=participant_id,
                    purchase_id=purchase_id,
                    number=n,
                )
            )
        await session.commit()

    resp = await client.post(f"/moderation/{purchase_id}/reject", follow_redirects=False)
    assert resp.status_code == 303

    resp = await client.post(f"/moderation/{purchase_id}/approve", follow_redirects=False)
    assert resp.status_code == 303

    async with maker() as session:
        purchase = await session.get(Purchase, purchase_id)
        assert purchase.status == PurchaseStatus.approved
        assert purchase.numbers_assigned is False


async def test_set_amount_recalculates(client, maker):
    event_id = await make_event(maker, price=Decimal("250"))
    participant_id = await make_participant(maker, event_id)
    purchase_id = await make_purchase(maker, event_id, participant_id)

    resp = await client.post(
        f"/moderation/{purchase_id}/amount", data={"amount": "500"}, follow_redirects=False
    )
    assert resp.status_code == 303

    async with maker() as session:
        purchase = await session.get(Purchase, purchase_id)
        assert purchase.posters_count == 2


async def test_edit_contacts(client, maker):
    event_id = await make_event(maker)
    participant_id = await make_participant(maker, event_id)
    purchase_id = await make_purchase(maker, event_id, participant_id)

    resp = await client.post(
        f"/moderation/{purchase_id}/contacts",
        data={"provided_name": "Пётр", "phone": "+79990001122", "public_name": "Ваня"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    async with maker() as session:
        purchase = await session.get(Purchase, purchase_id)
        participant = await session.get(Participant, purchase.participant_id)
        assert participant.provided_name == "Пётр"
        assert participant.phone == "+79990001122"
        assert participant.public_name == "Ваня"


async def test_contacts_public_name_prefilled_from_resolver(client, maker):
    event_id = await make_event(maker)
    participant_id = await make_participant(
        maker, event_id, vk_first_name="Иван", public_name=None
    )
    purchase_id = await make_purchase(maker, event_id, participant_id)

    resp = await client.get(f"/moderation/{purchase_id}")
    assert resp.status_code == 200
    assert 'value="Иван"' in resp.text


async def test_contacts_clear_public_name_resets(client, maker):
    event_id = await make_event(maker)
    participant_id = await make_participant(maker, event_id, public_name="X")
    purchase_id = await make_purchase(maker, event_id, participant_id)

    resp = await client.post(
        f"/moderation/{purchase_id}/contacts",
        data={"provided_name": "", "phone": "", "public_name": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    async with maker() as session:
        participant = await session.get(Participant, participant_id)
        assert participant.public_name is None


async def test_amount_prefilled_from_ocr(client, maker):
    event_id = await make_event(maker)
    participant_id = await make_participant(maker, event_id)
    purchase_id = await make_purchase(
        maker, event_id, participant_id, amount=None, ocr_amount=Decimal("750")
    )

    resp = await client.get(f"/moderation/{purchase_id}")
    assert resp.status_code == 200
    assert "750" in resp.text


async def test_search_by_phone(client, maker):
    event_id = await make_event(maker)
    participant_id = await make_participant(maker, event_id, phone="+79991234567")
    purchase_id = await make_purchase(maker, event_id, participant_id)

    resp = await client.get("/moderation", params={"q": "+79991234567", "view": "list"})
    assert resp.status_code == 200
    assert f"/moderation/{purchase_id}" in resp.text


async def test_receipt_404_when_missing(client, maker):
    event_id = await make_event(maker)
    participant_id = await make_participant(maker, event_id)
    purchase_id = await make_purchase(maker, event_id, participant_id)

    resp = await client.get(f"/moderation/{purchase_id}/receipt")
    assert resp.status_code == 404


async def test_vk_chat_link_uses_gim_format_when_group_id_set(client, maker):
    event_id = await make_event(maker)
    participant_id = await make_participant(maker, event_id, vk_user_id=777)
    purchase_id = await make_purchase(maker, event_id, participant_id)

    async with maker() as session:
        await app_settings.set_setting(session, app_settings.KEY_VK_GROUP_ID, "123456")
        await session.commit()

    resp_list = await client.get("/moderation", params={"view": "list"})
    assert resp_list.status_code == 200
    assert "gim123456?sel=777" in resp_list.text
    assert "write-" not in resp_list.text

    resp_detail = await client.get(f"/moderation/{purchase_id}")
    assert resp_detail.status_code == 200
    assert "gim123456?sel=777" in resp_detail.text
    assert "write-" not in resp_detail.text


async def test_vk_chat_link_absent_when_group_id_not_set(client, maker):
    event_id = await make_event(maker)
    participant_id = await make_participant(maker, event_id, vk_user_id=777)
    purchase_id = await make_purchase(maker, event_id, participant_id)

    resp_list = await client.get("/moderation", params={"view": "list"})
    assert resp_list.status_code == 200
    assert "gim" not in resp_list.text
    assert "write-" not in resp_list.text

    resp_detail = await client.get(f"/moderation/{purchase_id}")
    assert resp_detail.status_code == 200
    assert "gim" not in resp_detail.text
    assert "write-" not in resp_detail.text


async def test_manual_form_renders(client, maker):
    event_id = await make_event(maker, name="Розыгрыш Х")

    resp = await client.get("/moderation/manual")
    assert resp.status_code == 200
    assert 'name="event_id"' in resp.text
    assert "Розыгрыш Х" in resp.text or f"#{event_id}" in resp.text


async def test_manual_create_with_vk_link(client, maker):
    event_id = await make_event(maker)

    resp = await client.post(
        "/moderation/manual",
        data={
            "event_id": event_id,
            "vk_link": "https://vk.com/id555",
            "provided_name": "Иван Петров",
            "phone": "+79990001122",
            "public_name": "Иван",
            "amount": "500",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    async with maker() as session:
        result = await session.execute(
            select(Participant).where(Participant.vk_user_id == 555)
        )
        participant = result.scalar_one()
        assert participant.public_name == "Иван"

        result = await session.execute(
            select(Purchase).where(Purchase.participant_id == participant.id)
        )
        purchase = result.scalar_one()
        assert purchase.status == PurchaseStatus.manual_review
        assert purchase.amount == Decimal("500")
        assert purchase.posters_count == 2


async def test_manual_create_synthetic_id(client, maker):
    event_id = await make_event(maker)

    resp1 = await client.post(
        "/moderation/manual",
        data={"event_id": event_id, "provided_name": "Первый Псевдоучастник"},
        follow_redirects=False,
    )
    assert resp1.status_code == 303

    resp2 = await client.post(
        "/moderation/manual",
        data={"event_id": event_id, "provided_name": "Второй Псевдоучастник"},
        follow_redirects=False,
    )
    assert resp2.status_code == 303

    async with maker() as session:
        result = await session.execute(
            select(Participant).where(Participant.event_id == event_id)
        )
        participants = result.scalars().all()
        vk_ids = sorted(p.vk_user_id for p in participants)
        assert len(vk_ids) == 2
        assert all(v < 0 for v in vk_ids)
        assert vk_ids[0] != vk_ids[1]
        assert vk_ids == [-2, -1]


async def test_manual_create_with_receipt_file(client, maker):
    event_id = await make_event(maker)

    resp = await client.post(
        "/moderation/manual",
        data={
            "event_id": event_id,
            "vk_link": "https://vk.com/id556",
            "provided_name": "Чек Тестов",
            "amount": "500",
        },
        files={"receipt": ("check.jpg", b"\xff\xd8fakejpeg", "image/jpeg")},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    file_path = None
    async with maker() as session:
        result = await session.execute(
            select(Participant).where(Participant.vk_user_id == 556)
        )
        participant = result.scalar_one()
        result = await session.execute(
            select(Purchase).where(Purchase.participant_id == participant.id)
        )
        purchase = result.scalar_one()
        file_path = purchase.receipt_file_path
        assert file_path is not None
        assert os.path.exists(file_path)

    if file_path and os.path.exists(file_path):
        os.remove(file_path)


async def test_manual_create_unknown_event_404(client, maker):
    resp = await client.post(
        "/moderation/manual",
        data={"event_id": 99999, "provided_name": "Никто"},
        follow_redirects=False,
    )
    assert resp.status_code == 404


async def test_manual_then_approve(client, maker):
    event_id = await make_event(maker, price=Decimal("250"))

    resp = await client.post(
        "/moderation/manual",
        data={
            "event_id": event_id,
            "vk_link": "https://vk.com/id557",
            "provided_name": "Подтверждён Будет",
            "amount": "500",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    purchase_id = int(resp.headers["location"].rstrip("/").split("/")[-1])

    resp_approve = await client.post(f"/moderation/{purchase_id}/approve", follow_redirects=False)
    assert resp_approve.status_code == 303

    async with maker() as session:
        purchase = await session.get(Purchase, purchase_id)
        assert purchase.status == PurchaseStatus.approved


async def test_board_is_default_view(client, maker):
    resp = await client.get("/moderation")
    assert resp.status_code == 200
    assert "На проверке" in resp.text
    assert "Подтверждено" in resp.text
    assert "Отклонено" in resp.text


async def test_board_groups_statuses_into_columns(client, maker):
    event_id = await make_event(maker)
    participant_id = await make_participant(maker, event_id)
    pending_id = await make_purchase(
        maker, event_id, participant_id, status=PurchaseStatus.manual_review
    )
    approved_id = await make_purchase(
        maker, event_id, participant_id, status=PurchaseStatus.approved
    )
    rejected_id = await make_purchase(
        maker, event_id, participant_id, status=PurchaseStatus.rejected
    )

    resp = await client.get("/moderation")
    assert resp.status_code == 200
    assert f"/moderation/{pending_id}" in resp.text
    assert f"/moderation/{approved_id}" in resp.text
    assert f"/moderation/{rejected_id}" in resp.text


async def test_board_shows_needs_attention_flag(client, maker):
    event_id = await make_event(maker)
    participant_id = await make_participant(maker, event_id)
    await make_purchase(
        maker,
        event_id,
        participant_id,
        status=PurchaseStatus.manual_review,
        needs_attention=True,
    )

    resp = await client.get("/moderation")
    assert resp.status_code == 200
    assert "board-flag" in resp.text


async def test_board_filters_by_event(client, maker):
    event1_id = await make_event(maker, name="Событие 1", keyword="событие1")
    event2_id = await make_event(maker, name="Событие 2", keyword="событие2")
    participant1_id = await make_participant(maker, event1_id, vk_user_id=201)
    participant2_id = await make_participant(maker, event2_id, vk_user_id=202)
    purchase1_id = await make_purchase(maker, event1_id, participant1_id)
    purchase2_id = await make_purchase(maker, event2_id, participant2_id)

    resp = await client.get("/moderation", params={"event_id": event1_id})
    assert resp.status_code == 200
    assert f"/moderation/{purchase1_id}" in resp.text
    assert f"/moderation/{purchase2_id}" not in resp.text


async def test_view_list_renders_table(client, maker):
    event_id = await make_event(maker)
    participant_id = await make_participant(maker, event_id)
    await make_purchase(maker, event_id, participant_id)

    resp = await client.get("/moderation", params={"view": "list"})
    assert resp.status_code == 200
    assert "<table" in resp.text


async def test_board_has_switch_to_list_link(client, maker):
    resp = await client.get("/moderation")
    assert resp.status_code == 200
    assert "view=list" in resp.text


async def test_list_switch_to_board_link_preserves_event_id(client, maker):
    event_id = await make_event(maker)

    resp = await client.get(
        "/moderation", params={"view": "list", "event_id": event_id}
    )
    assert resp.status_code == 200
    assert f"event_id={event_id}" in resp.text


async def test_board_column_has_more_marker(client, maker):
    event_id = await make_event(maker)
    participant_id = await make_participant(maker, event_id)
    for _ in range(COLUMN_LIMIT + 1):
        await make_purchase(
            maker, event_id, participant_id, status=PurchaseStatus.manual_review
        )

    resp = await client.get("/moderation")
    assert resp.status_code == 200
    assert "Показаны первые" in resp.text

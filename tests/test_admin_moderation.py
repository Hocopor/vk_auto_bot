from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.admin.deps import get_session, require_login
from app.admin.main import app
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

    resp = await client.get("/moderation", params={"status": "manual_review"})
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


async def test_revoke_frees_numbers(client, maker):
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

    resp = await client.post(f"/moderation/{purchase_id}/revoke", follow_redirects=False)
    assert resp.status_code == 303

    async with maker() as session:
        result = await session.execute(
            select(PosterNumber).where(PosterNumber.purchase_id == purchase_id)
        )
        assert result.scalars().all() == []

        purchase = await session.get(Purchase, purchase_id)
        assert purchase.status == PurchaseStatus.revoked
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
        data={"provided_name": "Пётр", "phone": "+79990001122"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    async with maker() as session:
        purchase = await session.get(Purchase, purchase_id)
        participant = await session.get(Participant, purchase.participant_id)
        assert participant.provided_name == "Пётр"
        assert participant.phone == "+79990001122"


async def test_search_by_phone(client, maker):
    event_id = await make_event(maker)
    participant_id = await make_participant(maker, event_id, phone="+79991234567")
    purchase_id = await make_purchase(maker, event_id, participant_id)

    resp = await client.get("/moderation", params={"q": "+79991234567"})
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

    resp_list = await client.get("/moderation")
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

    resp_list = await client.get("/moderation")
    assert resp_list.status_code == 200
    assert "gim" not in resp_list.text
    assert "write-" not in resp_list.text

    resp_detail = await client.get(f"/moderation/{purchase_id}")
    assert resp_detail.status_code == 200
    assert "gim" not in resp_detail.text
    assert "write-" not in resp_detail.text

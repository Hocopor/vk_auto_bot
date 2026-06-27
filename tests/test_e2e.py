"""End-to-end tests: full flow from event creation to public table.

Uses SQLite in-memory, httpx ASGITransport for admin routes,
and direct calls to dialog/worker for bot logic.
"""

from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.admin.deps import get_session, require_login
from app.admin.main import app
from app.bot import dialog
from app.bot.worker import process_pending
from app.core import models  # noqa: F401
from app.core.db import Base
from app.core.models import (
    Event,
    Participant,
    PosterNumber,
    Purchase,
    PurchaseStatus,
)
from app.core.services import public_table


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
async def admin_client(maker):
    """httpx client for admin routes with auth override."""

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


def event_data(**overrides):
    data = {
        "name": "Розыгрыш",
        "keyword": "постер",
        "price": "250",
        "number_min": "1",
        "number_max": "50",
        "winners_count": "3",
        "starts_at": "",
        "ends_at": "",
        "expected_recipient": "",
        "msg_instruction": "",
        "msg_after_payment": "",
        "msg_receipt_received": "",
        "msg_need_contacts": "",
        "google_sheet_url": "",
    }
    data.update(overrides)
    return data


# ── E2E 1: Полный флоу (создание → бот → чек → воркер → публичная таблица) ──


async def test_full_flow_admin_creates_event(admin_client, maker):
    """Admin creates event, it appears in list."""
    resp = await admin_client.post(
        "/events", data=event_data(name="Тест E2E"), follow_redirects=False
    )
    assert resp.status_code == 303

    resp = await admin_client.get("/events")
    assert resp.status_code == 200
    assert "Тест E2E" in resp.text

    async with maker() as session:
        result = await session.execute(select(Event))
        event = result.scalars().one()
        assert event.name == "Тест E2E"
        assert event.keyword == "постер"
        assert event.price == Decimal("250")


async def test_full_flow_keyword_then_receipt_then_worker(maker, tmp_path, monkeypatch):
    """Simulate: keyword → dialog → receipt → worker assigns numbers."""
    monkeypatch.setattr(
        __import__("app.core.config", fromlist=["settings"]).settings,
        "receipts_dir", str(tmp_path),
    )
    async with maker() as session:
        event = Event(
            name="E2E Розыгрыш",
            keyword="роза",
            is_active=True,
            price=Decimal("100"),
            number_min=1,
            number_max=20,
            winners_count=2,
            msg_after_payment="Ваши номера: {numbers} ({count})",
            msg_need_contacts="Пришлите контакты",
            send_after_payment=True,
            send_need_contacts=True,
        )
        session.add(event)
        await session.commit()
        event_id = event.id

    # Step 1: User sends keyword
    async with maker() as session:
        matched = await dialog.find_matching_event(session, "роза")
        assert matched is not None
        assert matched.id == event_id

        await dialog.set_dialog(session, vk_user_id=1001, event_id=event_id)
        await session.commit()

    # Step 2: User sends receipt
    receipt_path = tmp_path / "receipt.jpg"
    receipt_path.write_bytes(b"fake-receipt-bytes")

    async with maker() as session:
        event = await session.get(Event, event_id)
        purchase = await dialog.process_receipt(
            session,
            event=event,
            vk_user_id=1001,
            vk_name="Тест Тестов",
            vk_link="https://vk.com/id1001",
            message_text="Тест Тестов +79001234567",
            receipt_file_path=str(receipt_path),
            receipt_hash="abc123hash",
            ocr_amount=None,
            ocr_raw_text=None,
            recipient_found=False,
            is_duplicate=False,
        )
        assert purchase is not None
        assert purchase.status in (PurchaseStatus.pending_ocr, PurchaseStatus.manual_review)

        # Simulate admin approval
        purchase.status = PurchaseStatus.approved
        purchase.amount = Decimal("300")
        purchase.posters_count = 3
        await session.commit()

    # Step 3: Worker processes
    sent_messages = []

    async def mock_send(vk_user_id, text, attachment=None):
        sent_messages.append((vk_user_id, text))

    async with maker() as session:
        processed = await process_pending(session, send_message=mock_send)
        assert processed == 1

    # Verify: numbers assigned
    async with maker() as session:
        purchase = await session.get(Purchase, purchase.id)
        assert purchase.numbers_assigned is True

        nums = (
            await session.execute(
                select(PosterNumber.number).where(PosterNumber.event_id == event_id)
            )
        ).scalars().all()
        assert len(nums) == 3
        assert len(set(nums)) == 3
        assert all(1 <= n <= 20 for n in nums)

    # Verify: message sent with numbers
    assert len(sent_messages) == 1
    vk_id, text = sent_messages[0]
    assert vk_id == 1001
    assert any(str(n) in text for n in nums)

    # Step 4: Public table shows data
    async with maker() as session:
        records = await public_table.collect_records(session, event_id)
        assert len(records) == 3
        numbers = [r[0] for r in records]
        assert sorted(numbers) == sorted(nums)
        names = [r[1] for r in records]
        # resolve_public_name: без vk_first_name публичное имя — первый токен ФИО
        assert all(n == "Тест" for n in names)


# ── E2E 2: Публичная таблица через HTTP ──


async def test_public_table_http(admin_client, maker):
    """Public table endpoint returns 200 with data, 404 for nonexistent."""
    async with maker() as session:
        event = Event(
            name="Публичный тест",
            keyword="пуб",
            is_active=True,
            price=Decimal("500"),
            number_min=1,
            number_max=10,
            winners_count=1,
        )
        session.add(event)
        await session.flush()

        participant = Participant(
            event_id=event.id, vk_user_id=2001, vk_name="Публичный",
            provided_name="Алексей",
        )
        session.add(participant)
        await session.flush()

        purchase = Purchase(
            event_id=event.id,
            participant_id=participant.id,
            status=PurchaseStatus.approved,
            posters_count=2,
        )
        session.add(purchase)
        await session.flush()

        for n in [3, 7]:
            session.add(PosterNumber(
                event_id=event.id,
                participant_id=participant.id,
                purchase_id=purchase.id,
                number=n,
            ))
        await session.commit()
        event_id = event.id

    # GET /p/{event_id}
    resp = await admin_client.get(f"/p/{event_id}")
    assert resp.status_code == 200
    assert "Публичный тест" in resp.text
    assert "Алексей" in resp.text
    assert "3" in resp.text
    assert "7" in resp.text

    # 404 for nonexistent
    resp = await admin_client.get("/p/99999")
    assert resp.status_code == 404


# ── E2E 3: Google Sheets sync (mocked) ──


async def test_e2e_google_sheet_sync_triggers(maker, tmp_path, monkeypatch):
    """When event has google_sheet_url, sync is called after worker processes."""
    sync_calls = []

    async def mock_sync(session, event_id, url):
        sync_calls.append((event_id, url))

    monkeypatch.setattr("app.sheets.sync.sync_event_to_sheet", mock_sync)

    async with maker() as session:
        event = Event(
            name="GS Test",
            keyword="гугл",
            is_active=True,
            price=Decimal("100"),
            number_min=1,
            number_max=10,
            winners_count=1,
            google_sheet_url="https://docs.google.com/spreadsheets/d/abc123/edit",
            send_after_payment=True,
        )
        session.add(event)
        await session.flush()

        participant = Participant(event_id=event.id, vk_user_id=3001, provided_name="GS User")
        session.add(participant)
        await session.flush()

        purchase = Purchase(
            event_id=event.id,
            participant_id=participant.id,
            status=PurchaseStatus.approved,
            posters_count=1,
        )
        session.add(purchase)
        await session.commit()

    sent = []

    async def mock_send(uid, txt, attachment=None):
        sent.append((uid, txt))

    async with maker() as session:
        processed = await process_pending(session, send_message=mock_send)
        assert processed == 1

    assert len(sync_calls) == 1
    assert sync_calls[0][1] == "https://docs.google.com/spreadsheets/d/abc123/edit"


# ── E2E 4: Отзыв номеров (revoke) ──


async def test_e2e_reject_frees_numbers(maker):
    """Rejecting a purchase frees its numbers for reuse."""
    async with maker() as session:
        event = Event(
            name="Revoke Test",
            keyword="отзыв",
            is_active=True,
            price=Decimal("100"),
            number_min=1,
            number_max=5,
            winners_count=1,
        )
        session.add(event)
        await session.flush()

        p1 = Participant(event_id=event.id, vk_user_id=4001, provided_name="User1")
        session.add(p1)
        await session.flush()

        purchase1 = Purchase(
            event_id=event.id, participant_id=p1.id,
            status=PurchaseStatus.approved, posters_count=2,
        )
        session.add(purchase1)
        await session.flush()

        for n in [1, 2]:
            session.add(PosterNumber(
                event_id=event.id, participant_id=p1.id,
                purchase_id=purchase1.id, number=n,
            ))
        await session.commit()

    # Reject via service
    async with maker() as session:
        from app.core.services.purchases import reject
        purchase = await session.get(Purchase, purchase1.id)
        freed = await reject(session, purchase, moderated_by="admin")
        await session.commit()
        assert freed == 2
        assert purchase.status == PurchaseStatus.rejected

    # Verify numbers freed
    async with maker() as session:
        nums = (
            await session.execute(
                select(PosterNumber.number).where(PosterNumber.event_id == event.id)
            )
        ).scalars().all()
        assert nums == []

        # New participant can get those numbers
        p2 = Participant(event_id=event.id, vk_user_id=4002, provided_name="User2")
        session.add(p2)
        await session.flush()

        purchase2 = Purchase(
            event_id=event.id, participant_id=p2.id,
            status=PurchaseStatus.approved, posters_count=2,
        )
        session.add(purchase2)
        await session.flush()

        from app.core.services.numbers import assign_unique
        new_nums = await assign_unique(session, event.id, p2.id, purchase2.id, 2)
        assert len(new_nums) == 2
        assert all(1 <= n <= 5 for n in new_nums)


# ── E2E 5: Каскадное удаление мероприятия ──


async def test_e2e_cascade_delete(admin_client, maker):
    """Deleting event removes all related data."""
    async with maker() as session:
        event = Event(
            name="Каскад",
            keyword="удалить",
            is_active=True,
            price=Decimal("100"),
            number_min=1,
            number_max=10,
            winners_count=1,
        )
        session.add(event)
        await session.flush()

        p = Participant(event_id=event.id, vk_user_id=5001)
        session.add(p)
        await session.flush()

        purch = Purchase(event_id=event.id, participant_id=p.id, status=PurchaseStatus.approved)
        session.add(purch)
        await session.flush()

        pn = PosterNumber(event_id=event.id, participant_id=p.id, purchase_id=purch.id, number=4)
        session.add(pn)
        await session.commit()
        event_id = event.id

    resp = await admin_client.post(f"/events/{event_id}/delete", follow_redirects=False)
    assert resp.status_code == 303

    async with maker() as session:
        assert await session.get(Event, event_id) is None
        result = await session.execute(
            select(Participant).where(Participant.event_id == event_id)
        )
        assert result.scalars().all() == []
        result = await session.execute(
            select(PosterNumber).where(PosterNumber.event_id == event_id)
        )
        assert result.scalars().all() == []


# ── E2E 6: Настройки (admin_title, winners_tab) ──


async def test_e2e_settings_update(admin_client, maker):
    """Admin can update settings and they take effect."""
    from app.core.services import app_settings as s

    resp = await admin_client.get("/settings")
    assert resp.status_code == 200

    resp = await admin_client.post(
        "/settings",
        data={
            "admin_title": "Мой Бот",
            "winners_tab_enabled": "true",
            "vk_token": "",
            "vk_group_id": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200

    async with maker() as session:
        title = await s.get_setting(session, s.KEY_ADMIN_TITLE)
        assert title == "Мой Бот"


# ── E2E 7: Несколько участников, разные события ──


async def test_e2e_multiple_participants(maker):
    """Multiple participants in same event get unique numbers."""
    async with maker() as session:
        event = Event(
            name="Multi",
            keyword="мульти",
            is_active=True,
            price=Decimal("100"),
            number_min=1,
            number_max=100,
            winners_count=1,
            send_after_payment=True,
        )
        session.add(event)
        await session.flush()

        for i in range(5):
            p = Participant(event_id=event.id, vk_user_id=6000 + i, provided_name=f"User{i}")
            session.add(p)
            await session.flush()
            purch = Purchase(
                event_id=event.id, participant_id=p.id,
                status=PurchaseStatus.approved, posters_count=2,
            )
            session.add(purch)
        await session.commit()

    sent = []

    async def mock_send(uid, txt, attachment=None):
        sent.append((uid, txt))

    async with maker() as session:
        processed = await process_pending(session, send_message=mock_send)
        assert processed == 5

    async with maker() as session:
        all_nums = (
            await session.execute(
                select(PosterNumber.number).where(PosterNumber.event_id == event.id)
            )
        ).scalars().all()
        assert len(all_nums) == 10
        assert len(set(all_nums)) == 10

    assert len(sent) == 5

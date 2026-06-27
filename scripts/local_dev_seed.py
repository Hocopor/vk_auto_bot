"""Локальный сид для визуальной проверки админки в браузере (SQLite, без PG).

НЕ для продакшена. Создаёт ./data/local_dev.db, таблицы и демо-данные, чтобы
agent-browser мог отрисовать все страницы с реалистичным контентом.

Запуск:
    DATABASE_URL=sqlite+aiosqlite:///./data/local_dev.db python scripts/local_dev_seed.py

Те же env-переменные надо передать uvicorn (см. scripts/local_dev_run.* / README).
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone

# env по умолчанию ДО импорта app.* (pydantic читает env при импорте config)
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./data/local_dev.db")
os.environ.setdefault("SECRETS_KEY", "KWKemCFNp82F1Mv-7gEMqXCmYomSOFsVp7cLYjphEj8=")
os.environ.setdefault("ADMIN_LOGIN", "admin")
os.environ.setdefault(
    "ADMIN_PASSWORD_HASH",
    "$2b$12$Umdlg/hPdssbR9OJE4Iz3uwE5MwlJnHMSpggMNBSc9hyrzoEvXAr2",
)
os.environ.setdefault("SESSION_SECRET", "local-dev-session-secret")
os.environ.setdefault("PUBLIC_BASE_URL", "http://localhost:8000")

from decimal import Decimal  # noqa: E402

from app.core.db import Base, async_session_maker, engine  # noqa: E402
from app.core.defaults import DEFAULT_TEXTS  # noqa: E402
from app.core.models import (  # noqa: E402
    AppSetting,
    Event,
    Participant,
    PosterNumber,
    Purchase,
    PurchaseStatus,
)


def _now():
    return datetime.now(timezone.utc)


async def main() -> None:
    os.makedirs("./data", exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_maker() as s:
        # настройки приложения
        s.add(AppSetting(key="vk_group_id", value="222333444"))
        s.add(AppSetting(key="admin_title", value="Розыгрыши"))
        s.add(AppSetting(key="winners_tab_enabled", value="true"))

        # --- Мероприятие 1: активное, с Google-таблицей ---
        ev1 = Event(
            name="Постеры «Сигма» — июнь",
            keyword="сигма",
            is_active=True,
            price=Decimal("300.00"),
            number_min=1,
            number_max=500,
            winners_count=3,
            starts_at=_now() - timedelta(days=2),
            ends_at=_now() + timedelta(days=5),
            msg_instruction=DEFAULT_TEXTS["msg_instruction"],
            msg_after_payment=DEFAULT_TEXTS["msg_after_payment"],
            msg_receipt_received=DEFAULT_TEXTS["msg_receipt_received"],
            msg_need_contacts=DEFAULT_TEXTS["msg_need_contacts"],
            auto_confirm=False,
            expected_recipient="ООО «Ромашка»",
            google_sheet_url="https://docs.google.com/spreadsheets/d/ABC123demo/edit",
            send_need_contacts=False,
        )
        # --- Мероприятие 2: остановленное, локальная таблица ---
        ev2 = Event(
            name="Билеты на концерт — весна",
            keyword="концерт",
            is_active=False,
            price=Decimal("500.00"),
            number_min=1,
            number_max=100,
            winners_count=1,
            msg_instruction=DEFAULT_TEXTS["msg_instruction"],
            msg_after_payment=DEFAULT_TEXTS["msg_after_payment"],
            msg_receipt_received=DEFAULT_TEXTS["msg_receipt_received"],
            msg_need_contacts="",
            auto_confirm=True,
            expected_recipient="ИП Иванов И.И.",
            send_need_contacts=False,
        )
        s.add_all([ev1, ev2])
        await s.flush()

        # Аня участвует и во втором мероприятии (для проверки агрегации "Все мероприятия")
        ann_ev2 = Participant(
            event_id=ev2.id,
            vk_user_id=100200301,
            vk_name="Анна Соколова",
            vk_link="https://vk.com/id100200301",
            provided_name="Аня",
            phone="+7 912 345-67-89",
        )
        s.add(ann_ev2)
        await s.flush()

        ann_purchase = Purchase(
            event_id=ev2.id, participant_id=ann_ev2.id, amount=Decimal("500.00"),
            ocr_amount=Decimal("500.00"), posters_count=1,
            status=PurchaseStatus.approved, numbers_assigned=True,
            moderated_by="admin",
        )
        s.add(ann_purchase)
        await s.flush()

        for n in (5, 9):
            s.add(PosterNumber(
                event_id=ev2.id, participant_id=ann_ev2.id,
                purchase_id=ann_purchase.id, number=n,
            ))

        # участники ev1
        people = [
            ("Аня", "+7 912 345-67-89", "Анна Соколова", 100200301),
            ("Дмитрий", "+7 903 111-22-33", "Дмитрий Орлов", 100200302),
            ("kate_v", None, "Екатерина Власова", 100200303),
            ("Павел", "+7 921 777-88-99", "Павел Кузнецов", 100200304),
        ]
        parts = []
        for provided, phone, vk_name, uid in people:
            p = Participant(
                event_id=ev1.id,
                vk_user_id=uid,
                vk_name=vk_name,
                vk_link=f"https://vk.com/id{uid}",
                provided_name=provided,
                phone=phone,
            )
            parts.append(p)
        s.add_all(parts)
        await s.flush()

        # покупки разных статусов
        # 1) approved + номера присвоены
        pu1 = Purchase(
            event_id=ev1.id, participant_id=parts[0].id, amount=Decimal("900.00"),
            ocr_amount=Decimal("900.00"), posters_count=3,
            status=PurchaseStatus.approved, numbers_assigned=True,
            moderated_by="admin", receipt_file_path=None,
        )
        # 2) manual_review (на проверке)
        pu2 = Purchase(
            event_id=ev1.id, participant_id=parts[1].id, amount=None,
            ocr_amount=Decimal("300.00"), posters_count=1,
            status=PurchaseStatus.manual_review, numbers_assigned=False,
        )
        # 3) manual_review с частичной оплатой (250 < 300)
        pu3 = Purchase(
            event_id=ev1.id, participant_id=parts[2].id, amount=Decimal("250.00"),
            ocr_amount=Decimal("250.00"), posters_count=0,
            status=PurchaseStatus.manual_review, numbers_assigned=False,
        )
        # 4) rejected
        pu4 = Purchase(
            event_id=ev1.id, participant_id=parts[3].id, amount=Decimal("300.00"),
            ocr_amount=Decimal("300.00"), posters_count=1,
            status=PurchaseStatus.rejected, numbers_assigned=False,
            moderated_by="admin",
        )
        s.add_all([pu1, pu2, pu3, pu4])
        await s.flush()

        # номера для approved-покупки
        for n in (7, 42, 128):
            s.add(PosterNumber(
                event_id=ev1.id, participant_id=parts[0].id,
                purchase_id=pu1.id, number=n,
            ))

        await s.commit()

    await engine.dispose()
    print("Seeded ./data/local_dev.db — login admin / admin")


if __name__ == "__main__":
    asyncio.run(main())

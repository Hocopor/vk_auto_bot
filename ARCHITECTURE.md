# ARCHITECTURE.md — техническая архитектура

> Дополняет `ТЗ_ИТОГ.md` (что делаем) → описывает КАК. Структура репозитория,
> модули, ключевые технические решения, переменные окружения, команды.

---

## 1. Стек (зафиксировано)

- **Python 3.12**, async везде где есть I/O.
- Бот: **vkbottle** (Bot Long Poll).
- Админка: **FastAPI** + **Jinja2** (server-rendered) + `python-multipart`
  (загрузка QR), сессии через signed cookie.
- БД: **PostgreSQL**, ORM **SQLAlchemy 2.x (async)** + **asyncpg**, миграции
  **Alembic**.
- OCR: **Tesseract** (`pytesseract`) + **Pillow** (препроцессинг), языки `rus+eng`.
- Sheets: **gspread** + `google-auth` (service account).
- Пароль: **passlib[bcrypt]**. Конфиг: **pydantic-settings** (`.env`).

---

## 2. Процессы (2 шт. на сервере)

| Процесс | Запуск | Назначение |
|---------|--------|-----------|
| `vk-bot` | `python -m app.bot.main` | Long Poll + фоновый воркер присвоения номеров |
| `admin-web` | `uvicorn app.admin.main:app --host 0.0.0.0 --port 8000` | Веб-админка |

- Оба читают один `.env` и одну БД. Общение бот↔админка — **только через БД**.
- **Воркер** живёт внутри процесса бота как asyncio-задача: раз в ~5 сек выбирает
  покупки `status=approved AND numbers_assigned=false`, присваивает номера, шлёт
  2-е сообщение, ставит `numbers_assigned=true`. (Простой надёжный polling; при
  желании позже можно заменить на Postgres LISTEN/NOTIFY.)
- Caddy — reverse proxy на `admin-web` (доступ по IP сервера, отдельный порт 8080).
  Подключается к уже работающему на сервере Caddy через `import` отдельным
  фрагментом — существующие сайты не затрагиваются.

---

## 3. Структура репозитория

```
vk_auto_bot/
├── app/
│   ├── core/
│   │   ├── config.py         # pydantic-settings: чтение .env
│   │   ├── db.py             # async engine, session-фабрика
│   │   ├── models.py         # SQLAlchemy-модели (см. ТЗ §6)
│   │   ├── defaults.py       # дефолтные шаблоны текстов (болванки)
│   │   ├── placeholders.py   # безопасный рендер {name}/{numbers}/...
│   │   └── services/
│   │       ├── events.py        # CRUD, create(+sheet), delete(каскад+лист)
│   │       ├── purchases.py     # переходы статусов: approve/reject/revoke
│   │       ├── numbers.py       # assign_unique() / free()
│   │       ├── participants.py  # upsert, парс имени/телефона
│   │       └── winners.py       # выбор winners_count из оплаченных
│   ├── bot/
│   │   ├── main.py           # entrypoint: bot + запуск воркера
│   │   ├── handlers.py       # кодовое слово; приём чека+имя+телефон
│   │   ├── fsm.py            # bot_dialog_state (контекст мероприятия)
│   │   └── worker.py         # цикл присвоения номеров + отправка 2-го сообщения
│   ├── ocr/
│   │   ├── recognize.py      # Pillow-препроцессинг + pytesseract (to_thread)
│   │   └── parse.py          # извлечение суммы и получателя (regex)
│   ├── sheets/
│   │   ├── client.py         # gspread auth (service account)
│   │   └── sync.py           # create_sheet / upsert_row / remove_row / rebuild
│   └── admin/
│       ├── main.py           # FastAPI app, подключение роутов
│       ├── auth.py           # вход по .env (login + bcrypt hash), сессия
│       ├── deps.py           # require_login, get_session
│       ├── routes/
│       │   ├── events.py        # список/создание/редактирование/стоп/удаление
│       │   ├── moderation.py    # очередь чеков, статусы, отзыв, поиск
│       │   ├── participants.py  # участники + номера
│       │   └── winners.py       # генератор победителей
│       ├── templates/        # Jinja2
│       └── static/
├── alembic/                  # миграции
├── scripts/
│   └── gen_password_hash.py  # утилита: пароль → bcrypt-хэш для .env
├── systemd/                  # vk-bot.service, admin-web.service
├── caddy/                    # vk_admin.caddy (фрагмент для Caddy)
├── tests/
├── .env.example
├── requirements.txt
└── README.md
```

---

## 4. Ключевые технические решения

### 4.1 Присвоение уникальных номеров (`services/numbers.py`)
- Уникальный индекс `(event_id, number)` на `poster_numbers`.
- `assign_unique(event_id, count)` в одной транзакции (реализация на Python —
  переносимо PG/SQLite, тестируемо; диапазоны билетов малы — сотни/тысячи):
  - загрузить занятые: `SELECT number FROM poster_numbers WHERE event_id=:id` → set.
  - `свободные = set(range(min, max+1)) - занятые`; если `len(свободные) < count` →
    не присваивать, поднять `NumbersExhausted` (алерт админу: лог + пометка).
  - выбрать `random.sample(sorted(свободные), count)`; вставить строки.
  - уникальный индекс `(event_id, number)` страхует от гонок (на IntegrityError —
    откат и повтор выборки).
- `free(purchase_id)` (отзыв): удалить строки `poster_numbers` покупки → номера
  снова свободны для будущих выдач.

### 4.2 OCR (`ocr/`)
- `recognize.py`: Pillow — grayscale, autocontrast, upscale → `pytesseract`
  `lang="rus+eng"`; вызов через `asyncio.to_thread` (блокирующий).
- `parse.py`:
  - **сумма** — regex по денежным паттернам (`\d[\d\s]*[.,]?\d*\s*(?:₽|руб|р\.)`),
    приоритет ключевым словам «Итого/Сумма/Перевод»; берём максимально правдоподобную.
  - **получатель** — нечёткий поиск `expected_recipient` в тексте (нормализация:
    lower, убрать кавычки/ООО/пробелы).
- Результат: `ocr_amount`, `ocr_confidence`, флаг «получатель найден».

### 4.3 Автоподтверждение (`services/purchases.py`)
- `auto_confirm=true` И сумма распознана и достаточна (кратна `price`) И получатель
  найден → `approved`. Иначе → `manual_review`. При `auto_confirm=false` всегда
  `manual_review`. Частичная/неверная оплата → `manual_review`.

### 4.4 Тексты и плейсхолдеры (`core/defaults.py`, `core/placeholders.py`)
- Дефолтные шаблоны — константы в `defaults.py`; копируются в поля мероприятия при
  создании, далее живут в БД и редактируются.
- `render(template, ctx)` — безопасная подстановка известных токенов
  (`{name}`,`{numbers}`,`{count}`,`{price}`,`{sheet_url}`); неизвестные `{...}`
  не ломают рендер (не используем сырой `str.format`).

### 4.5 Сбор имени/телефона (`services/participants.py`)
- Телефон — regex РФ-форматов (`(?:\+7|7|8)?[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}`).
- Имя — текст сообщения без телефона (очищенный); хранится `provided_name`.
- Оба правятся в админке. Отсутствие не блокирует присвоение (шлём `msg_need_contacts`).

### 4.6 Google Sheets (`sheets/`)
- gspread — синхронный, вызовы через `to_thread`, запись батчами + ретраи.
- При создании мероприятия: создать лист (колонки `Номер | Имя | Оплачено`),
  открыть доступ «по ссылке на чтение», сохранить `sheet_id`.
- Синк: при присвоении номера — добавить строки; при отзыве/откате — удалить;
  кнопка «пересобрать из БД». Падение Sheets не ломает основную логику.

### 4.7 Удаление мероприятия
- FK дочерних таблиц на `event_id` с `ON DELETE CASCADE`. Удаление события стирает
  его участия/покупки/чеки/номера/диалоги; отдельно удаляется Google-лист. Файлы
  чеков мероприятия — чистятся сервисом удаления. Другие события не затрагиваются.

---

## 5. Переменные окружения (`.env.example`)

```
VK_TOKEN=                 # fallback токена; основное значение — в админке (БД)
VK_GROUP_ID=              # пусто можно (валидатор → 0); основное — в админке
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/vk_auto_bot
GOOGLE_SA_JSON=./secrets/service_account.json  # разовый шаг при деплое
ADMIN_LOGIN=admin             # открыто
ADMIN_PASSWORD_HASH=          # bcrypt-хэш (из scripts/gen_password_hash.py)
SESSION_SECRET=               # секрет подписи cookie
SECRETS_KEY=                  # Fernet-ключ шифрования секретов в БД (gen_secrets_key.py)
RECEIPTS_DIR=./data/receipts  # хранение файлов чеков
WORKER_INTERVAL_SEC=5
```

### 5.1 Настройки заказчика в БД (таблица `app_settings`)

VK-токен, VK group id и почта владельца Google-таблиц настраиваются заказчиком в
админке (`/settings`) и хранятся в `app_settings` (key/value), а НЕ в `.env`:
- `vk_token` — **шифруется** (`core/crypto.py`, Fernet, ключ `SECRETS_KEY`); в HTML
  не отдаётся (показываем только «задан/не задан»).
- `vk_group_id`, `sheets_owner_email` — открыто.
- Бот читает токен из БД с fallback на `.env`; смена токена требует перезапуска бота.
- Проверка подключений: «Проверить VK» (`bot/vk_check.py` → `groups.getById`),
  «Проверить Google Sheets» (`sheets/sync.test_connection` — создаёт/шарит/удаляет
  временный лист). При создании мероприятия лист авто-шарится на `sheets_owner_email`
  как «редактор» (оригинал в Drive заказчика; владелец — service account).

---

## 6. Команды

```bash
# Установка (Ubuntu)
sudo apt install -y tesseract-ocr tesseract-ocr-rus postgresql
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# Хэш пароля админа (вписать в .env)
python scripts/gen_password_hash.py

# Миграции
alembic upgrade head

# Запуск (dev)
python -m app.bot.main
uvicorn app.admin.main:app --host 0.0.0.0 --port 8000

# Тесты
pytest

# Прод — через systemd (systemd/*.service) + Caddy (caddy/vk_admin.caddy), ручной деплой по README
```

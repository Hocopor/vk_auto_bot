# ВК-бот «Розыгрыш постеров» + админка

ВК-бот + веб-админка для розыгрышей постеров/билетов. Бот реагирует на кодовое слово, выдаёт инструкцию с QR-кодом оплаты, принимает чек + имя + телефон, проверяет оплату (OCR Tesseract + ручная модерация), присваивает участнику случайные уникальные номера и фиксирует его в публичной Google-таблице. По окончании мероприятия генератор выбирает победителей. Всё настраивается в админке на каждое мероприятие (цена, кол-во билетов, кол-во победителей, сроки, тексты, QR, получатель).

## Стек

- **Python 3.12**
- **Бот:** vkbottle (Long Poll), асинхронная обработка сообщений
- **Админка:** FastAPI + Jinja2, sessionMiddleware-аутентификация
- **БД:** PostgreSQL, SQLAlchemy async + asyncpg, миграции Alembic
- **OCR:** Tesseract локально (pytesseract, русский + английский)
- **Google Sheets:** gspread для создания и синхронизации публичных таблиц

## Локальная разработка

### Подготовка окружения

```bash
# Виртуальное окружение
python -m venv .venv
source .venv/bin/activate              # На Windows: .venv\Scripts\activate

# Зависимости
pip install -r requirements.txt

# Конфигурация
cp .env.example .env                   # Отредактировать значения: VK_TOKEN, VK_GROUP_ID, DATABASE_URL, GOOGLE_SA_JSON, ADMIN_LOGIN, ADMIN_PASSWORD_HASH, SESSION_SECRET

# Хэш пароля админа
python scripts/gen_password_hash.py    # Вывести bcrypt-хэш, скопировать в .env → ADMIN_PASSWORD_HASH
```

### Системные пакеты (для OCR)

```bash
# На Ubuntu/Debian
sudo apt install -y tesseract-ocr tesseract-ocr-rus

# На macOS
brew install tesseract

# На Windows
# Скачать установщик с https://github.com/UB-Mannheim/tesseract/wiki
```

### Запуск

```bash
# Миграции БД
alembic upgrade head

# В отдельных терминалах:
python -m app.bot.main                                      # Бот (Long Poll + воркер)
uvicorn app.admin.main:app --host 0.0.0.0 --port 8000    # Админка (http://localhost:8000)

# Тесты
pytest
```

## Развёртывание на сервере (Ubuntu 20.04+, cloud.ru)

### 1. Системные пакеты

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip postgresql \
    tesseract-ocr tesseract-ocr-rus git curl
```

> Caddy уже установлен и работает на сервере (через него проксируются другие
> сайты) — отдельно ставить и трогать его НЕ нужно. Админку подключим к нему
> отдельным фрагментом на отдельном порту (см. §7).

### 2. Создание пользователя и каталога

```bash
# Пользователь для приложения
sudo useradd -r -m -d /opt/vk_auto_bot vkbot 2>/dev/null || true

# Каталог приложения
sudo mkdir -p /opt/vk_auto_bot
cd /tmp  # или другая рабочая директория

# Скачать/скопировать код проекта в /opt/vk_auto_bot
# (например: git clone <repo> /opt/vk_auto_bot)

# Установить владельца
sudo chown -R vkbot:vkbot /opt/vk_auto_bot
```

### 3. Подготовка PostgreSQL

```bash
# Создать пользователя БД
sudo -u postgres psql -c "CREATE USER vkbot WITH PASSWORD 'СМЕНИТЕ_ПАРОЛЬ';"

# Создать базу
sudo -u postgres psql -c "CREATE DATABASE vk_auto_bot OWNER vkbot;"

# Проверить подключение (опционально)
psql -U vkbot -d vk_auto_bot -h localhost -c "SELECT 1;"
```

### 4. Конфигурация приложения

Заполнить `/opt/vk_auto_bot/.env`:

```bash
# Пример .env (заполнить реальными значениями)
VK_TOKEN=your_vk_token
VK_GROUP_ID=your_group_id
DATABASE_URL=postgresql+asyncpg://vkbot:ПАРОЛЬ@localhost/vk_auto_bot
GOOGLE_SA_JSON=/opt/vk_auto_bot/secrets/google-sa.json

ADMIN_LOGIN=admin
ADMIN_PASSWORD_HASH=bcrypt_hash_from_scripts/gen_password_hash.py
SESSION_SECRET=very_long_random_string_at_least_32_chars

TESSERACT_PATH=/usr/bin/tesseract
```

**Получить `ADMIN_PASSWORD_HASH`:**

```bash
cd /opt/vk_auto_bot
sudo -u vkbot python3 scripts/gen_password_hash.py
# Ввести пароль, скопировать хэш в .env
```

**Google Sheets** — положить service-account JSON в `/opt/vk_auto_bot/secrets/google-sa.json`:

```bash
sudo mkdir -p /opt/vk_auto_bot/secrets
sudo cp /path/to/google-sa.json /opt/vk_auto_bot/secrets/
sudo chown vkbot:vkbot /opt/vk_auto_bot/secrets/google-sa.json
sudo chmod 600 /opt/vk_auto_bot/secrets/google-sa.json
```

### 5. Установка Python-окружения и миграции

```bash
# От пользователя vkbot (как системный пользователь, не sudo)
sudo -u vkbot bash << 'EOF'
cd /opt/vk_auto_bot
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
alembic upgrade head
EOF
```

### 6. systemd-сервисы

Скопировать файлы сервисов и перезагрузить systemd:

```bash
sudo cp /opt/vk_auto_bot/systemd/vk-bot.service /etc/systemd/system/
sudo cp /opt/vk_auto_bot/systemd/admin-web.service /etc/systemd/system/
sudo systemctl daemon-reload

# Включить в автозапуск и запустить
sudo systemctl enable vk-bot.service admin-web.service
sudo systemctl start vk-bot.service admin-web.service
```

Проверить статус:

```bash
sudo systemctl status vk-bot.service
sudo systemctl status admin-web.service

# Логи (real-time)
journalctl -u vk-bot -f
journalctl -u admin-web -f
```

### 7. Caddy (доступ к админке)

На сервере Caddy уже запущен и проксирует другие сайты. Подключаем админку
**отдельным фрагментом на отдельном порту 8080**, не трогая существующие сайты.
Конфиг лежит в репозитории: `caddy/vk_admin.caddy`.

**7.1. Включить подгрузку фрагментов в основном Caddyfile (один раз).**
Проверить, есть ли в `/etc/caddy/Caddyfile` строка `import`:

```bash
grep -n "import /etc/caddy/conf.d" /etc/caddy/Caddyfile
```

Если строки НЕТ — дописать её в КОНЕЦ файла (существующие сайты не затрагиваются):

```bash
sudo mkdir -p /etc/caddy/conf.d
echo 'import /etc/caddy/conf.d/*.caddy' | sudo tee -a /etc/caddy/Caddyfile
```

**7.2. Положить фрагмент админки:**

```bash
sudo cp /opt/vk_auto_bot/caddy/vk_admin.caddy /etc/caddy/conf.d/vk_admin.caddy
```

**7.3. Проверить и применить (graceful reload — другие сайты не падают):**

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

**7.4. Открыть порт 8080** в firewall сервера и в security group cloud.ru:

```bash
sudo ufw allow 8080/tcp   # если используется UFW
```

> Порт можно сменить: поправить `:8080` в `/etc/caddy/conf.d/vk_admin.caddy`,
> затем повторить 7.3.

### 8. Проверка и доступ

Открыть в браузере: **`http://<IP-сервера>:8080/`**

- Страница входа админки
- Логин: `ADMIN_LOGIN` (из .env)
- Пароль: то же значение, которое хэшировали в `gen_password_hash.py`

Логи приложения:

```bash
# Бот
journalctl -u vk-bot -f --since "30 min ago"

# Админка
journalctl -u admin-web -f --since "30 min ago"

# Или все логи сразу
journalctl -e
```

## Обновление на сервере (ручной деплой)

Копипаст по шагам. Шаги 1–3 — от пользователя `vkbot`, шаг 4 — с sudo.

```bash
# 1. Обновить код
cd /opt/vk_auto_bot
sudo -u vkbot git pull --ff-only        # если код из git; иначе скопировать новые файлы

# 2. Зависимости + миграции (в venv, от vkbot)
sudo -u vkbot bash << 'EOF'
cd /opt/vk_auto_bot
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
EOF

# 3. (Только если менялся caddy/vk_admin.caddy)
sudo cp /opt/vk_auto_bot/caddy/vk_admin.caddy /etc/caddy/conf.d/vk_admin.caddy
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy

# 4. Перезапустить сервисы приложения
sudo systemctl restart vk-bot.service admin-web.service

# 5. Проверить, что поднялись
sudo systemctl status vk-bot.service admin-web.service --no-pager
```

## Структура проекта

```
/opt/vk_auto_bot/
├── .env                          # Конфигурация (не коммитить)
├── .venv/                        # Виртуальное окружение
├── requirements.txt              # Python-зависимости
├── app/
│   ├── core/                     # Ядро: модели, сервисы, конфиг
│   ├── bot/                      # Бот (vkbottle): диалог, воркер, обработчики
│   ├── ocr/                      # OCR (Tesseract): распознавание, парсинг
│   ├── sheets/                   # Google Sheets: синхронизация
│   └── admin/                    # Админка (FastAPI): маршруты, шаблоны
├── alembic/                      # Миграции PostgreSQL
├── tests/                        # Unit-тесты (pytest)
├── scripts/                      # Утилиты (gen_password_hash.py)
├── systemd/                      # systemd-сервисы (vk-bot, admin-web)
├── caddy/                        # Caddy-фрагмент админки (vk_admin.caddy)
└── secrets/                      # Ключи Google (не коммитить)
```

## Безопасность

- **`.env`** и **`secrets/`** — НЕ коммитить в git (уже в `.gitignore`)
- **HTTPS** опционально: при наличии домена Caddy выпустит Let's Encrypt автоматически — заменить `:8080` на имя домена в `caddy/vk_admin.caddy`
- **Админка по IP** — порт 8080 ограничить брандмауэром/security group до доверенных IP
- **PostgreSQL** — локальный сокет или VPC, слушает только localhost

## Частые вопросы

**Q: Бот не реагирует на сообщения**  
A: Проверить токен и group_id в `.env`, статус бота в `journalctl -u vk-bot`, наличие активного мероприятия.

**Q: Админка недоступна по IP**  
A: Проверить `journalctl -u admin-web`, конфиг Caddy (`sudo caddy validate --config /etc/caddy/Caddyfile`), логи Caddy (`journalctl -u caddy`), firewall сервера и security group cloud.ru (порт 8080 открыт?).

**Q: Ошибки OCR — Tesseract не найден**  
A: Установить пакет: `sudo apt install tesseract-ocr tesseract-ocr-rus`, путь в `.env` → `TESSERACT_PATH`.

**Q: БД не подключается**  
A: Проверить PostgreSQL (`sudo systemctl status postgresql`), пароль в `.env`, наличие БД и пользователя.

## Разработка

Все команды через виртуальное окружение:

```bash
source .venv/bin/activate

# Тесты с покрытием
pytest --cov=app tests/

# Миграция (после изменения моделей)
alembic revision --autogenerate -m "Description"
alembic upgrade head

# Линтер (если настроен)
ruff check app/ tests/
```

## Лицензия

Приватный проект.

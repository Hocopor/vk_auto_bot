# STATE.md — состояние работы (обновляется каждой сессией)

## Текущая точка

- **2026-06-28. ✅ СЕРВЕР ПЕРЕКЛЮЧЁН НА РАБОЧИЙ IP `84.54.57.141` (коммит `c2cd602`).** Заказчик
  перебирал IP cloud.ru; диапазон `84.54.56.0/22` глухо режется ТСПУ с моего канала (5 IP подряд
  мертвы: .57.101/.56.195/.57.243/.56.181/.57.109 — 22/443 таймаут), но **`84.54.57.141` ЖИВОЙ**
  (SSH ok, vm-20ac28/auto). Прошёл runbook: правка `caddy/vk_admin.caddy` (адрес сайта +
  default_sni `37.230.192.61`→`84.54.57.141`) → commit/push `c2cd602` → `git pull --ff-only` /opt
  (от vkbot) → `caddy validate` ok → `install` репо-конфига в `/etc/caddy/Caddyfile` → `reload
  caddy` (active). Smoke: изнутри `/login=200` `/p/1=404`; **снаружи `/login=200` ×3**. Сервисы
  admin-web/vk-bot/caddy = active. `.env` не трогал (PUBLIC_BASE_URL пустой). Диагностика с консоли
  сервера подтвердила: VM исправна (sshd up, ufw/iptables allow 22/443, listening) — дело только в
  ТСПУ-фильтре на публичном IP (брутфорсеры с чужих сетей в логах долетали). **ОСТАЛОСЬ ЗАКАЗЧИКУ:**
  зайти `https://84.54.57.141` (admin/пароль), принять самоподписанный серт; в `/settings` ввести
  VK-токен + Google. ГРАБЛИ: прямой `sudo sed` по `/etc/caddy/Caddyfile` блокирует auto-классификатор
  (обход git-only) → деплой Caddy ТОЛЬКО через репо: правка `caddy/vk_admin.caddy` → push → pull →
  `sudo install -m644 .../caddy/vk_admin.caddy /etc/caddy/Caddyfile` → validate → reload.
  **NB:** ssh-helper `/tmp/rssh.sh` (HOST=84.54.57.141, ретраи) пересоздать в новой сессии.

- **2026-06-28. ⚑(ЗАКРЫТО ВЫШЕ) ПЕРЕБОР IP боевого сервера cloud.ru (ТСПУ/РКН блокирует IP).**
  Поддержка cloud.ru подтвердила: внешний доступ режет **ТСПУ РКН** (DPI), а не конфиг/security
  group. Решение — заказчик МЕНЯЕТ публичный IP на cloud.ru, ищем незаблокированный; ассистент на
  КАЖДЫЙ новый IP переключает сервер. Это та же ОДНА VM (`hostname vm-20ac28`, user `auto`), меняется
  только публичный IP. **Хронология IP:** `37.230.192.61` (1-й, развёрнут, ТСПУ заблокировал) →
  `176.123.163.183` (2-й, тоже недоступен снаружи) → далее заказчик даёт новый.
  **NB:** мой исходящий IP из среды ассистента (на 2026-06-28) = `77.239.102.106`, стабилен; до РФ
  хожу нормально (ya.ru/github ок), но заблокированные ТСПУ IP «тёмные» (ping 0%, все порты таймаут).
  Если новый IP недоступен И мне, И заказчику → дело в IP/привязке; если только мне → возможно
  фильтр на мой адрес (тогда заказчику открыть 22 на `0.0.0.0/0` или добавить мой IP).

  **▶ RUNBOOK «переключить сервер на новый IP» (выполнять в новой сессии, НИЧЕГО не переизучать):**
  1. **Доступ:** ключ `A:\DevAI\Zakazi\ыыр\auto_bot\id_rsa` → `cp` в `/tmp/vk_id_rsa` + `chmod 600`.
     Подключение: `ssh -i /tmp/vk_id_rsa -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no
     -o LogLevel=ERROR auto@<NEW_IP>`. User `auto`, **sudo беспарольный**. Сеть ФЛАПАЕТ → все
     ssh/git/curl в РЕТРАИ (см. helper `/tmp/rssh.sh` в «Нюансы» — пересоздать с нужным HOST).
  2. **Проверить доступность нового IP** (с моей стороны и попросить заказчика проверить со своей):
     порты `22/80/443` (`/dev/tcp` probe + ssh). Недоступен мне, но доступен заказчику → фильтр ТСПУ
     на мой IP, продолжать НЕ смогу до открытия доступа. Доступен → шаг 3.
  3. **Поменять IP в Caddy:** `/etc/caddy/Caddyfile` — заменить в адресе сайта `https://<OLD_IP>` и в
     `default_sni <OLD_IP>` на `<NEW_IP>` (default_sni ОБЯЗАТЕЛЕН — браузер не шлёт SNI для голого
     IP). `sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile` → `sudo systemctl
     reload caddy` (Caddy сам выпустит самоподписанный серт под новый IP).
  4. **Синхронизировать репозиторий:** локально заменить IP в `caddy/vk_admin.caddy` (адрес сайта +
     default_sni) → commit + push → на сервере `git -C /opt/vk_auto_bot pull --ff-only` (в РЕТРАЯХ;
     ⚠️ если pull упал — НЕ копировать clone→/etc/caddy, затрёшь рабочий конфиг старым).
  5. **`.env`:** `PUBLIC_BASE_URL` ПУСТОЙ и таким остаётся (внутренние `/p/` отключены, таблицы только
     Google) — IP там НЕ нужен. Менять в .env ничего не надо.
  6. **Smoke:** локально `curl -sk --resolve <NEW_IP>:443:127.0.0.1 https://<NEW_IP>/login` = 200;
     снаружи `curl -k https://<NEW_IP>/login` = 200. Если снаружи таймаут, а локально 200 → IP опять
     режет ТСПУ → заказчик меняет IP снова (повтор runbook).
  7. **Зафиксировать** рабочий IP в STATE (хронология выше) и памяти `new-prod-server-cloudru`.

  **ЧТО УЖЕ ЕСТЬ НА СЕРВЕРЕ (НЕ переразворачивать!):** Ubuntu 22.04; Python 3.12 venv в
  `/opt/vk_auto_bot/.venv`; PostgreSQL 14 (роль+база `vk_auto_bot`, чистая, alembic head
  `0010_numbers_shortfall`, только 127.0.0.1); `/opt/vk_auto_bot/.env` (600, vkbot) со ВСЕМИ
  секретами (DATABASE_URL, SESSION_SECRET, SECRETS_KEY, ADMIN_PASSWORD_HASH, GOOGLE_SA_JSON в
  `/opt/vk_auto_bot/secrets/`); systemd `admin-web`+`vk-bot` (enabled, active; у бота супервизор сам
  подхватит VK-токен из БД); **ufw** (allow 22/80/443); **fail2ban** (jail sshd); SSH хардненинг
  (только ключ, root-login off, x11 off). Код в `/opt/vk_auto_bot` (owner `vkbot`). Caddy: `:443 tls
  internal` + `default_sni`, `/p/*`→404. Логин админки: `admin` / пароль задан заказчиком (plaintext
  НЕ хранится). VK-токен и Google заказчик вводит в `/settings` после того, как IP заработает.
  Старый сервер 185.228.72.118 — бот уже удалён (см. ниже).

- **2026-06-28. ПЕНТЕСТ НОВОГО СЕРВЕРА + ХАРДНЕНИНГ + УДАЛЕНИЕ СТАРОГО БОТА (по запросу заказчика).**
  - **❗ГЛАВНОЕ (операционный блокер, НЕ конфиг): внешний доступ к новой VM cloud.ru НЕСТАБИЛЕН.**
    Серия из 8 внешних HTTPS-запросов к `https://37.230.192.61/login`: прошло 3, таймаут 5;
    порт 22 так же (1 из 3). Локально сервер ВСЕГДА 200, сервисы active, NIC `enp3s0` — 0 ошибок/
    0 dropped, нагрузка ~0, syncookies on. Вывод: пакеты теряются на пути интернет→VM (сеть/security
    group/edge cloud.ru), VM их не видит. Это и есть причина «таймаут, не заходит в админку».
    **Лечится только со стороны заказчика/cloud.ru:** проверить security group (443/22 source
    0.0.0.0/0, нет rate-limit), переотвязать floating IP, проверить «защиту от DDoS» на тарифе,
    при необходимости тикет в поддержку cloud.ru. Из кода/сервера НЕ чинится.
  - **ПЕНТЕСТ — критичных/высоких дыр НЕ найдено.** Снаружи открыты только 22/80/443 (5432/8000/
    8080 закрыты). Проверено (атаки через localhost сервера, чтобы не долбить публичный порт):
    rate-limit логина 5×401→429 (брутфорс закрыт); `/docs`/`/redoc`/`/openapi`=404; защищённые
    роуты=303; path traversal на `/static`=404; чувствительные пути (`.env`,`.git`,secrets,исходники)
    =404; SQLi на логине безвреден (строковое сравнение + bcrypt, SQL нет); TRACE/PUT/DELETE=405;
    TLS1.0/1.1 выключены, TLS1.2/1.3 ок. Конфиг уже был крепкий: SSH только по ключу
    (`passwordauthentication no`), postgres только 127.0.0.1 (scram), `.env`/SA-json `600`,
    unattended-upgrades on.
  - **ХАРДНЕНИНГ ПРИМЕНЁН (доступ проверен — не потерян):** SSH drop-in
    `/etc/ssh/sshd_config.d/99-hardening.conf` (`PermitRootLogin no`, `X11Forwarding no`,
    `MaxAuthTries 3`, password auth off); **ufw** active (allow 22/80/443, deny rest);
    **fail2ban** active (jail sshd, bantime 1h). 
  - **ОСТАТОЧНЫЕ РИСКИ (за заказчиком):** самоподписанный TLS (нужен домен для доверенного);
    порты 22/80/443 открыты всему миру (22 — только по ключу, риск низкий; при желании ограничить
    source в security group cloud.ru); `auto` имеет NOPASSWD sudo (дефолт cloud-init, риск низкий
    при key-only SSH).
  - **СТАРЫЙ СЕРВЕР 185.228.72.118 — БОТ УДАЛЁН.** `vk-bot`+`admin-web` stop+disable (inactive),
    unit-файлы удалены, caddy-фрагмент `conf.d/vk_admin.caddy` снят (caddy reload, прочие сайты
    целы), код `/opt/vk_auto_bot`+`/root/vk_auto_bot` удалён (вместе с `.env` и Google SA-json),
    портов 8000/8080 нет. **VK-токен освобождён** (конфликт Long Poll исключён). ОСТАЛОСЬ на старом
    (не трогал): PostgreSQL-база `vk_auto_bot` со старыми данными/ПДн и системные пакеты — умрут при
    удалении VM заказчиком в консоли cloud.ru.
- **2026-06-28. РАЗВЁРНУТ НОВЫЙ БОЕВОЙ СЕРВЕР cloud.ru С НУЛЯ (заменяет старый 185.228.72.118).**
  Заказчик создал чистую VM на cloud.ru и попросил задеплоить туда. Полностью провизионинг
  с нуля (не инкрементальный git-pull). **Коммиты этой сессии:** `c885791` (https_only=True),
  `0719fc1` (Caddy default_sni), `5b7891d` (uvicorn --proxy-headers/--no-server-header),
  `d5e6fe0` (фикс auth-теста под Secure-cookie).
  - **Сервер:** `auto@37.230.192.61`, Ubuntu 22.04.5, sudo БЕСПАРОЛЬНЫЙ. SSH-ключ:
    `A:\DevAI\Zakazi\ыыр\auto_bot\id_rsa` (НЕ в `ssh.md` — там старый сервер). Доступ к серверу
    из этой среды ФЛАПАЕТ (порт 22 то отвечает, то таймаут; github/apt с сервера тоже временами
    отваливаются) — все ssh/git-команды оборачивать в РЕТРАИ (см. «Нюансы»).
  - **Что сделано (по порядку):** apt-зеркало переключено на `https://archive.ubuntu.com` +
    `ForceIPv4` (штатный `mirror.yandex.ru:80` и IPv6 недоступны); поставлены postgresql-14,
    tesseract-ocr+rus, build-essential, caddy (офиц. репо). **Python 3.12.13** — deadsnakes PPA
    (add-apt-repository падает: api.launchpad.net закрыт → ключ+source добавлены ВРУЧНУЮ, см.
    «Нюансы»). Системный юзер `vkbot`, репо в `/opt/vk_auto_bot` (git clone, HEAD на момент =
    `d5e6fe0`), venv + requirements. PostgreSQL: роль `vkbot` + база `vk_auto_bot` (только
    127.0.0.1), пароль БД в `.env`. `.env` собран (DATABASE_URL, свежие SESSION_SECRET/SECRETS_KEY,
    ADMIN_PASSWORD_HASH из пароля, заданного заказчиком (plaintext НЕ храним), GOOGLE_SA_JSON залит в
    `/opt/vk_auto_bot/secrets/`, PUBLIC_BASE_URL ПУСТОЙ — внутренние таблицы отключены). `alembic
    upgrade head` = **0010_numbers_shortfall** на чистой БД (8 таблиц). systemd `admin-web`+`vk-bot`
    (enable+start, оба active; у бота супервизор сам подхватит VK-токен из БД, интервал 10с).
  - **TLS-РЕШЕНИЕ ЗАКАЗЧИКА (важно):** домена НЕТ; «только админка, максимально безопасно, через
    HTTPS». Публичные таблицы — ТОЛЬКО Google Sheets, внутренние `/p/` ОТКЛЮЧЕНЫ. Caddy на **:443
    с `tls internal`** (самоподписанный серт; браузер 1 раз ругнётся → «всё равно перейти»),
    `default_sni 37.230.192.61` (ОБЯЗАТЕЛЬНО — браузер/curl не шлют SNI для голого IP, без этого
    handshake = `internal error`), `handle /p/* { respond 404 }`. В коде `https_only=True`.
    `/etc/caddy/Caddyfile` = копия `caddy/vk_admin.caddy` из репо. **Открыт только порт 443** (22
    для админа; 80 Caddy слушает для авто-редиректа, но снаружи закрыт — не нужен).
  - **ПРОВЕРЕНО (smoke по HTTPS, curl --resolve на 127.0.0.1):** `GET /login`=200; реальный вход
    `POST /login` (admin/пароль)=303, cookie `session=…; httponly; samesite=lax; Secure`;
    авторизованный `GET /`=200; неверный пароль=401; `/p/1`=404; security-заголовки на месте
    (CSP, X-Frame-Options SAMEORIGIN, nosniff, referrer/permissions-policy); один `Server: web`.
    Сертификат — `Caddy Local Authority`. Сервисы admin-web/caddy/vk-bot = active.
  - **❗ОСТАЛОСЬ ЗАКАЗЧИКУ (передать):** (1) ОСТАНОВИТЬ старый сервер 185.228.72.118 (бот!) ДО ввода
    VK-токена здесь — один токен нельзя слушать двумя ботами (конфликт Long Poll); (2) зайти на
    `https://37.230.192.61` (логин `admin`, пароль — тот, что заказчик задал при деплое), принять самоподписанный серт;
    (3) в `/settings` ввести VK-токен + Google (sheets_owner_email) и нажать «Проверить»; бот
    подхватит токен сам. (4) ДАННЫЕ НЕ переносились — БД чистая (по решению заказчика).
  - **ОСТАТОЧНЫЕ РИСКИ (за заказчиком):** самоподписанный TLS (для доверенного — нужен домен);
    SSH — парольная/ключевая auth и ограничение порта 22 на IP в security group cloud.ru;
    fail2ban на новом сервере НЕ ставился (был на старом) — при желании поставить.
- **2026-06-28. ФИКС (коммит `5e2db44`): харднинг сломал превью PDF-чека в модерации.**
  `X-Frame-Options=DENY` + CSP `frame-ancestors 'none'` блокировали `<iframe src="/moderation/{id}/receipt">`
  (браузер: «отказано в подключении»). Исправлено на `SAMEORIGIN` / `frame-ancestors 'self'` (свой
  origin фреймит свои страницы; чужой clickjacking по-прежнему закрыт). Проверено: остальной CSP
  ничего не ломает — `admin.js` только `data:`-превью (FileReader), внешнее = `<a href>` на vk.com
  (навигация, не ресурс), картинки-чеки = `<img>` (img-src 'self', не страдали). 315/2 зелёные,
  задеплоено. ГРАБЛИ на будущее: при добавлении `<iframe>`/встраивания держать `frame-ancestors 'self'`.
- **2026-06-28. ДЕПЛОЙ ФАЗЫ 9 + SECURITY-АУДИТ И ХАРДНИНГ БОЕВОГО — ЗАВЕРШЕНО (коммит `3689aba`).**
  Деплой Фазы 9 (`71678b8`, миграция 0010) выполнен (см. ниже), затем проведён аудит на взлом и
  закрыты дыры. Все 315 тестов зелёные (+5 security), харднинг проверен на боевом снаружи.
  - **СДЕЛАНО (задеплоено и проверено на проде):**
    1. `app/admin/security.py` (НОВЫЙ): `SecurityHeadersMiddleware` — на КАЖДЫЙ ответ
       `X-Frame-Options=DENY`, `X-Content-Type-Options=nosniff`, `Referrer-Policy=same-origin`,
       `Permissions-Policy`, `Cross-Origin-Opener-Policy`, **CSP** (`default-src 'self'` + Google
       Fonts; `frame-ancestors 'none'`, `form-action 'self'`, `base-uri 'self'`), скрыт `Server`.
    2. **Rate-limit `/login`**: 5 неудач за 5 мин по IP (последний `X-Forwarded-For` от Caddy —
       не подделать) → HTTP 429, даже с верным паролем. In-memory (admin-web = 1 процесс).
       Проверено на проде: `401 401 401 401 401 429 429`.
    3. `main.py`: отключены `/docs`,`/redoc`,`/openapi.json` (404 на проде); SessionMiddleware
       `max_age=7д`, `same_site=lax` (CSRF-базис), httponly (дефолт). `https_only=False` (HTTP).
    4. **Сервер: fail2ban** установлен+включён, jail `sshd` (maxretry 4, bantime 4ч, эскалация до
       7д). Закрывает АКТИВНЫЙ брутфорс SSH (было **15514 неудач/сутки**). Сразу забанил 3 IP.
    5. uvicorn `--no-server-header` в unit admin-web → `Server: web` (убрана идентификация софта).
  - **АУДИТ (проверено, дыр НЕ найдено):** все админ-роуты + отдача файлов (QR/чеки/картинки)
    под `require_login` (аноним → 303 `/login`, проверено на проде поштучно); публичная `/p/{id}`
    отдаёт только (номер, имя) — без телефонов/ФИО (ПДн-безопасно); path traversal невозможен
    (пути файлов из БД, имена uuid/hash, не из ввода); SQLi нет (ORM-bound params; аноним-поверхность
    = только `/p/{id:int}` + сравнение в логине); секреты сильные (SESSION_SECRET 64, SECRETS_KEY 43);
    Postgres и uvicorn слушают только 127.0.0.1; `/p/9999`→404 без утечки.
  - **ОСТАТОЧНЫЕ РИСКИ (требуют действий заказчика / доступа к консоли cloud.ru — НЕ закрыть из кода):**
    - **TLS:** админка = plain HTTP на :8080 → пароль и cookie сессии перехватываемы в сети. Нужен
      ДОМЕН → Caddy сам поднимет HTTPS, тогда в `main.py` поставить `https_only=True`.
    - **SSH:** root-login + парольная аутентификация включены (fail2ban смягчает, но не убирает).
      Best: SSH-ключи + `PasswordAuthentication no` + ограничить порт 22 на IP заказчика в security
      group cloud.ru.
    - **Порт 8080** открыт всему интернету в security group cloud.ru. Админка — на 1 пользователя →
      ограничить 8080 на IP заказчика (убирает всю внешнюю поверхность админки). Консоль cloud.ru.
  - **ФУНКЦИОНАЛЬНЫЙ E2E НА ПРОДЕ:** read-only-проверка (auth-стена, публичные страницы, здоровье
    сервисов, smoke) — ПРОЙДЕНА. Аутентифицированный click-through НЕ делал: (а) нужен админ-пароль
    заказчика (в `.env`, plaintext у меня нет); (б) деструктивные CRUD-флоу на ЖИВОМ активном
    мероприятии «автохайп» (#11) недопустимы. Мутирующие флоу покрыты 315 тестами + per-phase
    agent-browser QA на локальной SQLite. Если нужен аутентиф. read-only обход прода — за паролем.

- **2026-06-28. ФАЗА 9 (контроль лимита номеров / overselling + стоп-бота по исчерпанию) —
  ✅ ЗАВЕРШЕНА И ЗАДЕПЛОЕНА (коммит `71678b8`).** Деплой выполнен (SSH_PASS из `ssh.md`):
  git pull --ff-only /opt+/root (`c871e9a`→`71678b8`) → `alembic upgrade head`
  (`0009`→**`0010_numbers_shortfall`**, колонка `purchases.numbers_shortfall` создана —
  подтверждено в боевой PG) → restart admin-web+vk-bot (оба active) → smoke `:8080/login=200`,
  `/events=303`. vk-bot стартовал чисто (BotPolling + Worker); **спам `Numbers exhausted`
  ИСЧЕЗ** (0 совпадений за 5 мин — overselling закрыт на боевом). Историческая запись по
  коду/тестам — ниже. Реализацию делал ОРКЕСТРАТОР сам (критичное ядро
  статусной машины присвоения/освобождения — opus-уровень по плану; холодные сабагенты
  перечитали бы те же файлы = трата токенов). Развилки ⚑ закрыты заказчиком (AskUserQuestion):
  ёмкость ПРОГНОЗНАЯ (бронь), при нехватке — ЧАСТИЧНОЕ присвоение + возврат части денег, при
  исчерпании — МОЛЧАТЬ.
  - **Реализация:**
    - `numbers.py`: `OPEN_PURCHASE_STATUSES`; `assigned_count`; `reserved_open` (Σ max(1,
      posters_count) по живым покупкам без номеров); `event_capacity` → `{capacity, assigned,
      reserved, free, free_projected}`; `assign_available` (частичное, ДО count, не всё-или-ничего);
      `purchase_numbers`; `recover_event_capacity` (сброс латча у одобренных shortfall-покупок).
      `assign_unique`/`NumbersExhausted` ОСТАВЛЕНЫ (используются в test_services/test_e2e).
    - `dialog.py`: `is_event_accepting` (= is_event_open AND free_projected>0); `find_matching_event`
      пропускает исчерпанные события → бот молчит. `resolve_event_for_receipt` НЕ гейтим по
      ёмкости (юзер уже в диалоге — оплату принимаем, не теряем).
    - `worker.py::process_pending`: `needed = posters_count − уже_присвоено` → `assign_available`;
      ЛАТЧ `numbers_assigned=True` всегда; при недостаче `numbers_shortfall`+`needs_attention`+1
      warning (конец спама каждые 5с); after_payment шлётся с полным актуальным набором номеров
      (только если total>0); переобработка после recovery не дублирует номера.
    - `purchases.py::reject`: после `free_numbers` чистит свой shortfall + зовёт
      `recover_event_capacity(event_id)` (освободилась ёмкость → воркер дозаполнит другие).
    - `routes/events.py`: список+форма показывают ёмкость; `update_event` запрещает сузить
      диапазон ниже присвоенных номеров (min/max PosterNumber → форма 400) и при расширении
      (`new_capacity>old_capacity`) зовёт `recover_event_capacity`.
    - Модель `Purchase.numbers_shortfall` (Int nullable), миграция **0010_numbers_shortfall**
      (down=0009). UI-бейджи: events_list (ИСЧЕРПАНО + выдано/ёмкость), event_form (подсказка),
      purchase_detail (красный баннер + строка), moderation_board/list (флаг «!» + «не хватило N»).
  - **РЕЗУЛЬТАТ:** pytest **310 passed, 2 skipped** (было 299/2; +11 тестов:
    `tests/test_phase9_capacity.py` + адаптация test_worker + 2 теста в test_admin_events).
    alembic head = `0010_numbers_shortfall` (единственный). Шаблоны провалидированы httpx-
    тестами (рендерят реальный Jinja через ASGI). Живой бот-флоу (молчание при исчерпании,
    частичное присвоение) — юнит/интеграц. тестами + ручной прогон заказчика.
  - **ДЕПЛОЙ НЕ ВЫПОЛНЕН:** в окружении НЕТ `SSH_PASS`. Когда будет: push (сделан ассистентом)
    → `git pull --ff-only` /opt+/root → **`alembic upgrade head` (0010! иначе боевая БД упадёт —
    нет колонки `numbers_shortfall`)** → restart admin-web+vk-bot → smoke `:8080/login=200`.
  - **ПОБОЧНО (по запросу заказчика):** исправлена причина «сабагенты плодят сабагентов» — в
    `.claude/agents/*.md` не было `tools:` → наследовали инструмент `Agent`. Добавлен явный
    `tools:` без `Agent` + запрет делегирования в теле всех трёх агентов. Память
    `subagents-no-delegation-tools-fix`. **Это закрывает баг overselling из памяти
    `bug-number-limit-not-enforced` — спам `Numbers exhausted` в логе vk-bot уйдёт после деплоя.**
- **2026-06-28. ЭТАП 8.14 (картинки-вложения к 3 сообщениям бота) — ЗАВЕРШЁН (деплой ниже).**
  Группа P4. Оркестратор спроектировал полное ТЗ, код писал coder-сабагент (sonnet, TDD+
  fastapi-patterns+design-taste-frontend), оркестратор верифицировал + e2e + деплой.
  - **Реализация:** новая таблица `EventMessageImage` (id/event_id FK CASCADE/message_key/
    image_path/attachment/attachment_error/created_at, unique (event_id,message_key)), миграция
    **0009** (down=0008), `Event.message_images` relationship, константа `MESSAGE_IMAGE_KEYS`.
    `settings.message_images_dir=./data/message_images`. `events.py`: хелперы
    `_save_message_image_file`/`_process_message_image`/`_event_msg_image_keys`, превью-роут
    `GET /events/{id}/message-image/{key}` (404-гард), интеграция в create/update (после
    миграции таблицы, до commit) и delete (сбор путей + физ. удаление файлов после commit);
    `services/events.py::delete_event` + `selectinload(Event.message_images)`. Форма
    `event_form.html`: у 3 блоков (receipt_received/contacts_saved/after_payment) поле
    «Прикрепить изображение» + превью + чекбокс «Удалить»; у «Инструкции» — НЕТ (там QR).
    `admin.js`: generic FileReader-превью `.msg-image-input[data-preview]`. Бот:
    `handlers.resolve_message_attachment` (копия QR-механики: кэш attachment в строке,
    выделенный upload_api, best-effort), проброшен в `_handle_receipt`/`_handle_contacts`;
    воркер шлёт after_payment-картинку — `upload_api` протащен в `worker_loop`/`run_once`/
    `process_pending`, колбэк `send_message(vk_user_id, text, attachment=None)`, `main._run_bot`
    передаёт upload_api.
  - **РЕЗУЛЬТАТ:** pytest **299 passed, 2 skipped** (+13 тестов `tests/test_message_images.py`;
    адаптированы сигнатуры моков send_message в test_worker/test_e2e). e2e на ЖИВОМ сервере
    (SQLite-QA, uvicorn :8003, авторизованная curl-сессия): форма у 3 сообщений имеет поле
    картинки, у «Инструкции» НЕТ (`image_instruction` отсутствует); загрузка к after_payment →
    303, превью-роут 200 image/png; замена → старый файл с диска стёрт, остался 1 новый;
    удаление (чекбокс) → файл физически стёрт (папка пуста), превью 404. Миграция 0009 валидна
    (down=0008).
  - **ЗАДЕПЛОЕНО (коммит `c871e9a`):** push origin main → `git pull --ff-only` /opt+/root
    (`6cfa240`→`c871e9a`) → `alembic upgrade head` (0008→**0009**, таблица `event_message_images`
    создана — подтверждено `to_regclass` в боевой PG) → restart admin-web+vk-bot (оба active;
    `:8080/login=200`, `/events=303`; vk-bot чисто — BotPolling + Worker). **Живой прогон в ВК —
    за заказчиком:** прикрепить картинки к сообщениям в админке, проверить, что доходят участнику
    с соответствующим сообщением.
- **2026-06-28. ЭТАП 8.13 (смена ссылки/режима таблицы у идущего мероприятия + миграция) — ЗАВЕРШЁН И ЗАДЕПЛОЕН.**
  Группа P4, фидбек 2026-06-28. Оркестратор спроектировал ТЗ, код писал coder-сабагент (sonnet,
  TDD+fastapi-patterns), оркестратор верифицировал + e2e + деплой. Миграций схемы НЕТ
  (`google_sheet_url` уже был).
  - **Реализация:** `sheets/sync.py::sync_event_to_sheet` — новый kwarg `raise_on_error=False`
    (при True пробрасывает исключение после лога; воркер зовёт без флага — поведение прежнее).
    `routes/events.py::update_event_submit` — захват `old_sheet_url` ДО мутаций (стр. 310);
    при `new_sheet_url is not None and != old` (HTML→Google или Google→другой Google) ПЕРЕД
    commit синхронно зовётся `sync_event_to_sheet(..., raise_on_error=True)` (ленивый импорт):
    успех → обычный commit/redirect; ошибка → `session.rollback()` + форма 400 «Не удалось
    записать в новую таблицу…» (атомарно: НИЧЕГО не сохраняется, старая ссылка остаётся).
    Очистка url (Google→HTML) и неизменный url → миграции НЕТ. `event_form.html` — подсказка
    у поля ссылки (шаринг SA + перенос данных при смене).
  - **Семантика (готовый `sync_event_to_sheet` = полный rebuild из БД, поэтому новая таблица
    заполняется СРАЗУ; участнику новая ссылка уходит на лету через `reader_url`/`/p/{id}` —
    отдельного кода не нужно).**
  - **РЕЗУЛЬТАТ:** pytest **286 passed, 2 skipped** (+5 тестов: вызов миграции с
    raise_on_error=True при смене; нет вызова при очистке/неизменном url; ошибка миграции →
    400 + откат; юнит на raise_on_error True/False). e2e на ЖИВОМ сервере (SQLite-QA, uvicorn
    :8002, авторизованная curl-сессия): подсказка у поля на месте; смена ссылки без живого SA →
    HTTP 400 + «Не удалось записать в новую таблицу», в БД осталась старая ссылка (откат);
    очистка ссылки → 303, `google_sheet_url` стал пустым (Google→HTML, без миграции). Happy-path
    реальной записи в Google — мок-юнитами (живого SA локально нет).
  - **ЗАДЕПЛОЕНО (коммит `6cfa240`):** push origin main → `git pull --ff-only` /opt+/root
    (`cba3bc0`→`6cfa240`, fast-forward) → restart admin-web+vk-bot (оба active; транзиентный 502
    от Caddy на первом curl, после паузы — `:8080/login=200`, `/events=303`). Миграций не было.
- **2026-06-28. ЭТАП 8.11 (поиск во вкладке «Участники») — КОД+ТЕСТЫ+E2E ГОТОВЫ, деплой ниже.**
  Группа P5, edit.md #10/#18. Оркестратор спроектировал ТЗ, код писал coder-сабагент (sonnet,
  скилы TDD+fastapi-patterns). Оркестратор верифицировал правки, прогнал e2e и деплой.
  - **Реализация:** `routes/participants.py` — параметр `q`, хелпер `_text_conditions`
    (ilike по provided_name/vk_name/phone); int(q) → `vk_user_id==n` в ОБОИХ режимах +
    подзапрос `PosterNumber.number==n` ТОЛЬКО в event-режиме (поиск по номеру билета).
    `or_(*conditions)` применён к count- и data-запросам: в event — как доп. `.where` к
    `event_id`-фильтру; в «Все» — `.where(...)` до `group_by(vk_user_id)` (совпадение в любой
    строке агрегата). `participants_list.html` — поле поиска `q` в ОДНОЙ форме с select
    (смена мероприятия сохраняет q и наоборот), placeholder по режиму (в event добавлено
    «номер»), кнопка «Сбросить», `q|urlencode` в пагинации, empty-state «Ничего не найдено
    по запросу…».
  - **РЕЗУЛЬТАТ:** pytest **281 passed, 2 skipped** (было ~273; +9 тестов). e2e на ЖИВОМ
    сервере (локальная SQLite-QA, uvicorn :8001, авторизованная curl-сессия + agent-browser
    скрины): «Все» q=Соколова→Анна (агрегат, оба мероприятия), q=42→«Ничего не найдено»
    (по номеру в «Все» НЕ ищет); event_id=1 q=42→Аня по билету (номера 7,42,128),
    q=Орлов→Дмитрий. Скрины `data/screens/8_11_search_all.png`, `8_11_search_event.png`
    (обе страницы отрисованы чисто, тулбар выровнен). Миграций НЕТ (схема не менялась).
  - **ЗАДЕПЛОЕНО (коммит `cba3bc0`):** push origin main → `git pull --ff-only` /opt+/root
    (`175745a`→`cba3bc0`, fast-forward) → restart admin-web+vk-bot (оба active; первый curl
    поймал транзиентный 502 от Caddy, после паузы — `:8080/login=200`, `/participants=303`) →
    vk-bot стартовал чисто (BotPolling + Worker). Миграций не было.
- **2026-06-28. ПЛАНИРОВАНИЕ: добавлены 2 новые фичи в `PLAN.md → Фаза 8` (8.13 переписан, 8.14 новый).**
  Фидбек заказчика (2026-06-28). Оркестратор спроектировал реализацию, расставил приоритеты,
  определил место в плане; кода НЕ писал (это план-сессия). Развилки уточнены у заказчика
  (AskUserQuestion):
  - **8.13 (P4) Смена ссылки/режима таблицы у идущего мероприятия + миграция.** Менять
    `google_sheet_url` и режим (HTML `/p/{id}` ⇄ Google) у идущего мероприятия; при сохранении
    новая таблица СРАЗУ заполняется из БД (`sync_event_to_sheet` уже это умеет — полный rebuild),
    старая просто отвязывается (внешний Google-док НЕ трогаем). Добавить `raise_on_error` в синк
    для синхронной валидации доступа в форме + ветвление в `update_event`. Участнику новая ссылка
    уходит автоматически (`reader_url`/`/p/{id}` читаются на лету).
  - **8.14 (P4) Картинки-вложения к 3 сообщениям** (receipt_received/contacts_saved/after_payment;
    «Инструкция» НЕ трогаем — там QR). Механика = копия QR: отдельная таблица `EventMessageImage`
    (миграция 0009), `settings.message_images_dir`, обобщённый `resolve_message_attachment`,
    отправка через выделенный `upload_api` (в воркер его НАДО протащить — он шлёт after_payment;
    колбэк `send_message` расширить `attachment`). UI у каждого сообщения: прикрепить/заменить/
    удалить + превью; при замене/удалении старый файл стирается с диска; при удалении события —
    файлы чистятся явно, строки каскадом.
  - **Порядок:** 8.11 → 8.13 → 8.14 → 8.12 (финальная приёмка, последней) → Фаза 9. Журнал
    решений PLAN.md пополнен.
- **2026-06-27. ЭТАП 8.10 (вкладка «Участники»: «Все мероприятия» + карточка) — ЗАВЕРШЁН И ЗАДЕПЛОЕН (коммит `2eb29a8`).**
  Группа P5, edit.md #9. Проектировал ОРКЕСТРАТОР, код писал coder-сабагент (sonnet,
  скилы TDD+fastapi-patterns+design-taste-frontend).
  - **8.10.1 Список** `app/admin/routes/participants.py` переписан. Дефолт «Все мероприятия»
    (event_id None): агрегация по `vk_user_id` (один человек = одна строка + список его
    мероприятий, вкл. остановленные). Серверная offset-пагинация `PAGE_SIZE=50` (вычисление
    `has_prev`/`has_next`/`total`). vk_ids страницы: `group_by(vk_user_id).order_by(func.max(id).desc())
    .limit.offset`, представитель = строка с max(id). Конкретное мероприятие (mode="event") —
    как раньше, с номерами (PosterNumber по page_ids). Строки кликабельны (`tr.row-link` +
    onclick) → карточка. Индекс `ix_participants_vk_user_id` (`Participant.vk_user_id index=True`,
    миграция **0008**).
  - **8.10.2 Карточки** (хелпер `_build_person(parts)`): `/participants/vk/{vk_user_id}`
    (агрегат по событиям, scope="all") объявлен ВЫШЕ `/participants/{participant_id}`
    (конкретный, scope="event"). Новый шаблон `participant_card.html`: панель данных
    (VK id/имя/ссылка-или-gim-чат/ФИО/телефон/публичное имя через `resolve_public_name`) +
    по каждому мероприятию билеты (кол-во+номера) и чеки (#/сумма/билетов/статус-бейдж/«Открыть»
    → `/moderation/{id}`). CSS: `.row-link`, `.pager` на существующих spacing-токенах.
  - **РЕЗУЛЬТАТ:** pytest **273 passed, 2 skipped** (было 264/2; +9 тестов participants).
    e2e agent-browser на локальной SQLite-QA (обе темы): «Все мероприятия» — Аня (vk 100200301,
    добавлена в оба события в сиде) одной строкой с двумя мероприятиями; агрегатная карточка
    `/participants/vk/100200301` — обе группы (билеты 5,9 и 7,42,128, оба чека «Одобрено»);
    конкретное мероприятие `?event_id=1` — участники с номерами; тёмная тема выровнена. Скрины
    `data/screens/8_10_participants_all_light.png`, `8_10_card_dark.png`. **ЗАДЕПЛОЕНО:** push
    `2eb29a8` → git pull --ff-only /opt+/root → `alembic upgrade head` (миграция **0008**,
    `0007`→`0008`, индекс) → restart admin-web+vk-bot (оба active; первый curl поймал
    транзиентный 502 от Caddy, после — `:8080/login=200`, `/participants=303`).
- **2026-06-27. БАГФИКС 8.9.1 (event_id="" → 422) — ИСПРАВЛЕН И ЗАДЕПЛОЕН (коммит `078a91f`).**
  Заказчик: при возврате дропдауна на «Все мероприятия» — чёрный экран с JSON
  `int_parsing ... event_id ... unable to parse "" as integer` (422). Корень: HTML-`<select>`
  всегда шлёт value выбранного пункта; «Все мероприятия»/«— выберите —» имеют value="" →
  параметр `event_id: int | None` падает на пустой строке. Та же мина была в `/participants`
  и `/winners` (тоже дропдаун с пустым value). **Фикс:** новый переиспользуемый тип
  `app/admin/deps.py::OptionalInt = Annotated[int|None, BeforeValidator(_empty_to_none)]`
  («"» → None), применён в `moderation_list`/`participants_list`/`winners_page`. **РЕЗУЛЬТАТ:**
  pytest **264 passed, 2 skipped** (+4 регресс-теста: пустой event_id в board/list/participants/
  winners → 200). e2e agent-browser: реальный флоу (выбрать мероприятие → вернуть «Все») на
  всех трёх экранах → 200, не 422; проверены поиск на доске (q=Аня → только #1) и переключатель
  Доской↔Списком с сохранением q. **ЗАДЕПЛОЕНО:** push → git pull /opt+/root → restart → smoke.
  Миграций нет.
- **2026-06-27. ЭТАП 8.9 (модерация-канбан: 3 колонки + фильтр + Доской/Списком + флаг) — ЗАВЕРШЁН И ЗАДЕПЛОЕН (коммит `936c753`).**
  Группа P4, edit.md #11/#19. Проектировал ОРКЕСТРАТОР, код писал coder-сабагент (sonnet,
  скилы TDD+fastapi-patterns+design-taste-frontend+frontend-design-direction).
  - **8.9.1 Бэкенд** `app/admin/routes/moderation.py`: в `moderation_list` параметр
    `view=board|list` (дефолт board). Константы `COLUMN_LIMIT=50` + `BOARD_COLUMNS` (3 ведра:
    pending={pending_ocr,manual_review}, confirmed={approved,auto_confirmed}, rejected=
    {rejected,revoked} — все 6 статусов покрыты). Хелперы `_purchase_base_stmt`/
    `_apply_event_filter`/`_apply_search` (вынос текущей логики поиска). board: 3 запроса по
    `status.in_(ведро)` с `limit(51)`, `has_more` при >50, в шаблон `column_limit`. Дропдаун
    мероприятий (все события, дефолт «Все»=event_id None, остановленные помечены). Роуты
    /manual и /{id} объявлены ниже (порядок сохранён). В board `status` из URL игнорируется
    (колонка = статус).
  - **8.9.2 Фронт** новый `moderation_board.html` (3 колонки .board/.board-col/.board-card,
    обе темы, БЕЗ инлайн-стилей), переключатель Доской/Списком с сохранением event_id+q,
    красный флаг `needs_attention` в колонке «На проверке», badge «частично», индикатор
    has_more. CSS-блок канбана в style.css (только существующие токены). В
    `moderation_list.html` добавлен тот же дропдаун + переключатель «Доской» + `view=list`
    во всех ссылках/пилюлях.
  - **РЕЗУЛЬТАТ:** pytest **260 passed, 2 skipped** (было 252/2; +8 тестов доски, адаптированы
    4 теста под новый дефолт — добавлен `?view=list`). e2e agent-browser на локальной SQLite-QA
    (обе темы): доска по умолчанию, 3 колонки с верной группировкой (#2/#3→На проверке,
    #1→Подтверждено, #4→Отклонено), дропдаун (остановленное помечено), фильтр `event_id=2`
    (пусто, «Списком» сохраняет event_id), переключатель Доской/Списком, список со
    статус-пилюлями несёт `view=list`. Скрины `data/screens/8_9_board_light.png` и
    `8_9_board_dark.png`. **ЗАДЕПЛОЕНО:** push → git pull --ff-only /opt+/root → restart
    admin-web+vk-bot → smoke `:8080/login=200`. Миграций НЕТ (схема не менялась).
- **2026-06-27. ЭТАП 8.8 (кнопка «Добавить вручную» в модерации) — ЗАВЕРШЁН И ЗАДЕПЛОЕН (коммит `9935297`).**
  Группа P3, edit.md #13 + уточнение. Проектировал ОРКЕСТРАТОР, код писал coder-сабагент
  (TDD+fastapi-patterns). Админ вручную создаёт чек+псевдоучастника, когда оплата пришла мимо бота.
  - **Реализация:**
    - `participants.py`: `parse_vk_user_id(link)` (число / `vk.com/id<N>` → int, иначе None);
      `next_synthetic_vk_id(session, event_id)` (уникальный отрицательный id для псевдоучастника
      в рамках события: `min(vk_user_id) - 1` или -1).
    - `routes/moderation.py`: `GET /moderation/manual` (форма со списком всех мероприятий) +
      `POST /moderation/manual` (создание). **Оба объявлены ВЫШЕ `moderation_detail`
      (`/moderation/{purchase_id}`)** — иначе "manual" уходит в int-параметр и FastAPI отдаёт 422.
      POST: парсит vk id (иначе синтетический), upsert участника + `public_name`, опциональный
      файл чека (UploadFile → `settings.receipts_dir`, имя `{event}_{vk}_{hash[:12]}.{ext}`),
      `Purchase(status=manual_review, amount, posters_count=count_posters(amount,price))`, редирект
      на карточку `/moderation/{id}`. Дальше обычные «Одобрить»/«Отклонить».
    - `manual_add.html` (НОВЫЙ): форма (мероприятие/vk_link/ФИО/телефон/публичное имя/сумма/файл),
      multipart. Кнопка «+ Добавить вручную» в тулбаре `moderation_list.html`.
  - **РЕЗУЛЬТАТ:** pytest **252 passed, 2 skipped** (было 246/2; +6 тестов: форма рендерится,
    создание по vk-ссылке, синтетический id (два псевдоучастника -1/-2), файл чека сохраняется,
    404 на неизвестное мероприятие, manual→approve). e2e agent-browser на локальной SQLite-QA:
    форма с выпадающим списком (2 события, остановленное помечено) → создание покупки #5
    (vk_link id777 распознан, сумма 600 → 2 билета, public_name «Сергей») → карточка
    manual_review → «Одобрить» → «Одобрено» (скрин `data/screens/8_8_manual_card.png`; номера
    присвоит воркер, в QA он не запущен). **ЗАДЕПЛОЕНО:** push `9935297` → git pull --ff-only
    /opt+/root → restart admin-web+vk-bot (оба active) → smoke `:8080/login=200`,
    `/moderation/manual=303` (редирект на логин — роут есть и защищён). Миграций нет.
- **2026-06-27. ЭТАП 8.6+8.7 (автоподстановка OCR-суммы + контактов + поле «Публичное имя») — ЗАВЕРШЁН И ЗАДЕПЛОЕН (коммит `846cd65`).**
  Группа P3, edit.md #6 + #7. Объединены в один этап (оба правят карточку модерации).
  Проектировал ОРКЕСТРАТОР, код писал coder-сабагент (TDD+fastapi-patterns).
  - **8.6:** `purchase_detail.html` поле «Сумма» (форма set_amount) →
    `value = amount or ocr_amount or ''` (при amount=None подставляется ocr_amount).
  - **8.7:** форма контактов в `purchase_detail.html` — новое поле «Публичное имя»
    (`name=public_name` → `participant.public_name`, пустая строка → None=сброс к резолверу),
    предзаполнение из `resolve_public_name(participant)` (новый ключ контекста
    `public_name_value` в `moderation_detail`); метка provided_name переименована в
    «ФИО (полное)»; подсказка «Публичное имя уходит в публичную таблицу — только имя, не ФИО».
    Роут `moderation_set_contacts` принял `public_name: str = Form("")`. Телефон уже
    предзаполнялся ранее. **Sheets:** HTML-таблица `/p/{id}` читается из БД на лету (правка
    public_name видна сразу); Google-Sheets зеркало обновится при следующем синке номеров
    (существующее ограничение, не блокер — sync не трогал).
  - **РЕЗУЛЬТАТ:** pytest **246 passed, 2 skipped** (было 243/2; +3 теста: prefill публичного
    имени из резолвера, сброс public_name пустым значением, prefill суммы из ocr_amount;
    обновлён test_edit_contacts). e2e agent-browser на локальной SQLite-QA: карточка #2
    (amount=None, ocr_amount=300, участник «Дмитрий») — «Сумма»=300.00, «Публичное имя»=
    «Дмитрий» (резолвер из provided_name), метка «ФИО (полное)», подсказка на месте (скрин
    `data/screens/8_6_7_moderation_prefill.png`). **ЗАДЕПЛОЕНО:** push `846cd65` → git pull
    --ff-only /opt+/root → restart admin-web+vk-bot (оба active; первый curl поймал
    транзиентный 502 от Caddy, после — `:8080/login=200`). Миграций нет (схема не менялась).
- **2026-06-27. ЭТАП 8.5 (объединить Отклонить/Отозвать + фикс статусной машины модерации) — ЗАВЕРШЁН И ЗАДЕПЛОЕН (коммит `071800a`).**
  Деплой выполнен в начале этой сессии (SSH_PASS из `ssh.md`): git pull --ff-only /opt+/root
  (`5da070d`→`071800a`, fast-forward, миграций нет) → restart admin-web+vk-bot (оба active) →
  smoke `:8080/login=200`, vk-bot стартовал чисто (supervisor + BotPolling + Worker). NB: в логе
  vk-bot продолжается спам `Numbers exhausted for event 7` — косяк overselling (Фаза 9), не 8.5.
  Историческая запись по коду/тестам/e2e 8.5 — ниже (КОД+ТЕСТЫ+E2E ГОТОВЫ).
- **2026-06-27. ЭТАП 8.5 (КОД+ТЕСТЫ+E2E, запись на момент разработки).**
  P3, edit.md #5 + косяк `bug-moderation-status-churn-no-delivery` (закрыт). Решены ВМЕСТЕ.
  Проектировал ОРКЕСТРАТОР, код писал coder-сабагент (TDD). **Фаза 9 (overselling/ёмкость)
  в этот этап НЕ входит — отложена в конец плана.**
  - **Реализация:**
    - `numbers.py`: новый хелпер `assigned_count_for_purchase(session, purchase_id)` (COUNT
      PosterNumber по покупке) + импорт `func`.
    - `purchases.py`: УДАЛЁН `revoke()`; `reject()` теперь = освобождает номера (`free_numbers`)
      + статус `rejected` + `numbers_assigned=False` + возвращает freed (то, что делал revoke,
      но статус rejected — снимает «латч» недоставки). `approve()` — всегда пересчитывает
      `posters_count` из amount при event; safety-сброс залипшего флага (numbers_assigned=True,
      но номеров фактически 0 → сброс, чтобы воркер переприсвоил после reject/чехарды). Новый
      чистый хелпер `can_approve(purchase, event)` (amount задана И покрывает ≥1 билет).
    - `routes/moderation.py`: удалён роут `/revoke`; `approve` гейтит по `can_approve` (нет
      суммы → redirect `?error=amount`, статус не меняется); `detail` принимает `error` и отдаёт
      в шаблон `can_approve`+`error`.
    - `purchase_detail.html`: баннер `error=amount` «Укажите сумму перед одобрением»; кнопка
      «Одобрить» `disabled` + подсказка «Укажите сумму» когда `not can_approve`; удалена форма
      «Отозвать номера»; confirm reject → «Отклонить покупку и освободить номера?».
    - Тесты адаптированы (revoke→reject в test_services/test_admin_moderation/test_e2e) + новые:
      approve без суммы блокируется, reject→approve переподхватывает, approve сбрасывает залипший
      флаг, can_approve.
  - **РЕЗУЛЬТАТ:** pytest **243 passed, 2 skipped** (было 238/2; +5 тестов). e2e agent-browser
    на локальной SQLite-QA: карточка #2 (amount=None) — кнопка «Одобрить» disabled + подсказка
    «Укажите сумму» + баннер при `?error=amount`; карточка #1 (approved, есть сумма) — «Одобрить»
    активна, кнопки «Отозвать» НЕТ нигде; «Отклонить» на месте (скрин
    `data/screens/8_5_moderation_no_amount.png`). Косяк недоставки закрыт: reject сбрасывает
    `numbers_assigned` → reject→approve снова даёт воркеру переприсвоить номера.
  - **КОММИТ `071800a` ЗАПУШЕН в main.** **ДЕПЛОЙ НА СЕРВЕР НЕ ВЫПОЛНЕН:** в окружении НЕТ
    `SSH_PASS`. Миграций нет (схема не менялась). Нужно (когда будет SSH_PASS): `git pull
    --ff-only` /opt+/root → restart admin-web+vk-bot → smoke `:8080/login=200`.
- **2026-06-27. ЭТАП 8.4 (FSM-диалог бота: ФИО+телефон после чека) — КОД+ТЕСТЫ+E2E ГОТОВЫ.**
  edit.md #4, группа P2. Проектировал ОРКЕСТРАТОР, код писал coder-сабагент (TDD).
  - **Флоу:** keyword → msg_instruction(+QR) [stage=awaiting_receipt] → ЧЕК →
    msg_receipt_received (теперь просит ФИО+телефон) [stage=awaiting_contacts] → текст
    ФИО+тел → **новое** msg_contacts_saved («данные приняты») [stage=done] → (после
    модерации) msg_after_payment с номерами (воркер, без изменений).
  - **Реализация:**
    - Модели: `BotDialogState.stage` (Text, server_default `'awaiting_receipt'`);
      `Participant.public_name` (админ-override) + `Participant.vk_first_name` (из VK
      users.get); `Event.msg_contacts_saved` + `Event.send_contacts_saved`. Миграция
      **`0007_dialog_fsm_contacts`** (down=0006, 5 колонок).
    - `dialog.py`: `set_dialog(stage=...)` (переключение на новое кодовое слово сбрасывает
      стадию), новые `get_dialog`, `set_stage`; `process_receipt(vk_first_name=...)`.
    - `handlers.py`: РОУТИНГ по стадии в `_handle_message` — вложение→чек (ставит
      awaiting_contacts); иначе текст матчит активный keyword→`_handle_keyword`
      (переключение даже из awaiting_contacts, сброс стадии); иначе→`_handle_contacts`
      (только в awaiting_contacts И `looks_like_contacts` И событие открыто → парсит
      ФИО+тел, upsert, msg_contacts_saved, stage=done; мусор → молчит, стадию не теряет).
      `_get_vk_identity` теперь отдаёт и `vk_first_name`.
    - `participants.py`: `upsert_participant(vk_first_name=...)`; `resolve_public_name(p)`
      = public_name > vk_first_name > 1-й токен provided_name > vk_name; `looks_like_contacts`
      (есть телефон ИЛИ ≥2 слов).
    - Публичное имя через резолвер: `public_table.collect_records`,
      `sheets.sync.collect_approved_records`, `worker` ctx `name` — теперь
      `resolve_public_name` (публичное = VK first_name; полное ФИО (provided_name) остаётся
      в карточке/модерации).
    - `defaults.py`: переформулирован `DEFAULT_MSG_RECEIPT_RECEIVED` (просит ФИО+тел) +
      новый `DEFAULT_MSG_CONTACTS_SAVED`. Форма события: новый msg-блок «Данные приняты»
      (тумблер `send_contacts_saved` + textarea `msg_contacts_saved`). routes/services
      events — поля проброшены в create/update.
  - **РЕЗУЛЬТАТ:** pytest **238 passed, 2 skipped** (было 213/2; +25 тестов FSM/резолвер/
    форма; адаптированы test_handlers_gating/test_admin_events/test_e2e под новые сигнатуры).
    **e2e** agent-browser на локальной SQLite-QA: форма `/events/new` рендерит новый блок
    «Данные приняты» (поля `send_contacts_saved` INPUT + `msg_contacts_saved` TEXTAREA),
    msg_receipt_received переформулирован (скрин `data/screens/8_4_contacts_saved_form.png`).
    **ЗАДЕПЛОЕНО (коммит `5da070d`):** push → git pull --ff-only /opt+/root → `alembic
    upgrade head` (миграция **0007**, `0006`→`0007 (head)`, 5 колонок) → restart admin-web+
    vk-bot (оба active; первый curl поймал транзиентный 502 от Caddy, после — `:8080/login=
    200`) → vk-bot чисто: supervisor + BotPolling + Worker. **Живой прогон в ВК — за
    заказчиком** (кодовое слово → чек → прислать ФИО+телефон → проверить, что приходит
    «данные приняты»).
- **2026-06-27. ЭТАП 8.3 — ЗАВЕРШЁН И ЗАДЕПЛОЕН** (коммиты `b891fdd`+`310efda`).
  Деплой выполнен в этой сессии: `git pull --ff-only` /opt+/root → `310efda`; **`alembic
  upgrade head` применил миграцию 0006** (`0005_qr_attachment` → `0006_receipt_date_abuse
  (head)`, 3 колонки в purchases: receipt_date/receipt_signature/needs_attention) →
  `restart admin-web vk-bot` (оба active) → smoke `:8080/login=200` (первый curl поймал
  транзиентный 502 от Caddy — admin стартует ~5с, после повторного 200). vk-bot стартовал
  чисто: supervisor + BotPolling + Worker. **NB:** в логе vk-bot продолжается спам
  `Numbers exhausted for event 7: requested 6, available 5` — это косяк overselling (Фаза 9),
  не 8.3.
- **2026-06-27. ЭТАП 8.3 (Авто-подтверждение + abuse + дата чека) — КОД+ТЕСТЫ.**
  P1, ядро платёжного конвейера. edit.md #3, #12. **Делал ОРКЕСТРАТОР РУКАМИ** — сабагенты
  (coder) легли по лимиту сессии Anthropic; реализация по уже готовому ТЗ оркестратора.
  - **Решения заказчика (AskUserQuestion 2026-06-27) ДО кода:** (1) окно свежести чека =
    ОБЩАЯ настройка `/settings`, дефолт **3 дня** (не .env, не пер-ивент); (2) добавлена
    галочка «авто-подтверждать чеки без распознанной даты» (дефолт ВЫКЛ → без даты в ручную).
  - **Реализация:**
    - `evaluate_payment` (`purchases.py`): убрано `amount % price == 0` — auto-approve при
      `amount >= price AND recipient_found` (+ abuse-гейт), posters = floor.
    - `ocr/parse.py`: `parse_receipt_date` (dd.mm.yyyy/yy, ISO, «dd месяц yyyy» рус., первая
      валидная по позиции) + `parse_receipt_signature` (номер операции/документа/чека/
      квитанции, требует ≥1 цифры, upper). `parse_receipt` теперь отдаёт `receipt_date` и
      `signature`.
    - `core/services/abuse.py` (НОВЫЙ): `is_duplicate_global(session, hash, signature,
      exclude_purchase_id)` — другой НЕ rejected/revoked Purchase с тем же хэшем ИЛИ подписью
      в ЛЮБОМ мероприятии; `is_date_fresh(receipt_date, now, max_age_days, allow_without_date)`
      (по локальной TZ через `timeutil.to_local`); `load_gate_config` (читает app_settings).
    - `decide_after_ocr` (`purchases.py`): новые kwargs `is_duplicate/receipt_date/now/
      max_age_days/allow_without_date`. При auto_confirm И валидном платеже → abuse-гейт; если
      дубль (локальный/глобальный) ИЛИ несвежая/нет даты → manual_review + `needs_attention=True`.
      Иначе approved. Если auto off / получатель не найден → manual_review БЕЗ флага.
    - `dialog.process_receipt`: прокидывает receipt_date/receipt_signature в Purchase, читает
      `abuse.load_gate_config`, всегда зовёт `decide_after_ocr` (ветка is_duplicate больше не
      обходит decide — флаг ставится единообразно).
    - `handlers._handle_receipt`: из OCR берёт receipt_date/signature, прокидывает в process_receipt.
    - Модель `Purchase`: +`receipt_date`(Date), +`receipt_signature`(Text,index),
      +`needs_attention`(Bool, server_default false, index). Миграция `0006_receipt_date_abuse`.
    - `app_settings.py`: ключи `KEY_RECEIPT_MAX_AGE_DAYS`, `KEY_AUTOCONFIRM_WITHOUT_DATE`.
    - `/settings` (route+settings.html): поле «макс. возраст чека (дней)» (дефолт 3) +
      галочка «авто-подтверждать без даты» (дефолт выкл).
  - **РЕЗУЛЬТАТ:** pytest **213 passed, 2 skipped** (было 172/2 на 8.2; +41 тест: даты/подпись
    OCR, abuse-функции, decide-гейт все ветки, settings). Импорты без циклов
    (abuse не тянет purchases). Миграция 0006 валидна (down=0005). **e2e:** UI настроек
    покрыт httpx-тестами (поля рендерятся); сама логика конвейера — бот-сторона, без живого
    ВК проверяется юнит/интеграц. тестами (live-прогон — заказчику). **ДЕПЛОЙ НЕ ВЫПОЛНЕН:**
    в окружении НЕТ `SSH_PASS` → нужно: push (сделан) → `git pull` /opt+/root → `alembic
    upgrade head` (0006!) → restart admin-web+vk-bot → smoke. Сделать в начале след. сессии,
    когда будет SSH_PASS.
  - **ВАЖНО для деплоя:** миграция 0006 добавляет 3 колонки в `purchases` — БЕЗ `alembic
    upgrade head` боевая БД упадёт (нет колонок). Не забыть.
- **2026-06-27. ЭТАП 8.2 (PDF-чеки: OCR + превью) — ЗАВЕРШЁН И ЗАДЕПЛОЕН (коммит `0f57d5b`).**
  edit.md #8. OCR теперь читает чеки в PDF, админка показывает превью PDF.
  - **Реализация (coder-сабагент по ТЗ оркестратора, скилы TDD+fastapi-patterns):**
    - `requirements.txt` — `pypdfium2>=4.0` (чистый бинарный wheel, без системных
      зависимостей; локально встал `pypdfium2-5.10.1`).
    - `app/ocr/recognize.py` — рефактор: `_is_pdf(path)` (детект по расширению ИЛИ
      сигнатуре `%PDF-` в первых байтах), `_render_pdf_first_page(path)` (pypdfium2,
      `PdfDocument`→`page.render(scale=2.5)`→`to_pil().convert("RGB")`), `_open_image(path)`
      (диспетчер PDF/картинка). `_preprocess` теперь принимает `PIL.Image`, а не путь;
      `recognize_text_sync = _preprocess(_open_image(path))`. Бот (`handlers`) уже
      сохраняет PDF с расширением `.pdf` (doc.ext) — менять не пришлось.
    - `app/admin/routes/moderation.py::moderation_receipt` — `media_type="application/pdf"`
      для .pdf (FileResponse без filename = inline).
    - `app/admin/templates/purchase_detail.html` — блок «Чек» ветвится: PDF →
      `<iframe class="receipt-pdf">` + ссылка «Открыть PDF в новой вкладке», иначе `<img>`.
    - `app/admin/static/style.css` — `.receipt-pdf { width:100%; height:600px; border:0; }`.
    - `tests/test_ocr_recognize.py` — +5 тестов (генерация PDF через Pillow
      `img.save(p,"PDF")`, детект по расширению/сигнатуре, рендер `_open_image`,
      реальный OCR PDF под guard tesseract).
  - **РЕЗУЛЬТАТ:** pytest **172 passed, 2 skipped** (скип — только реальный Tesseract,
    бинаря нет на машине; `test_open_image_renders_pdf` РЕАЛЬНО прошёл — pypdfium2 рендерит).
    e2e agent-browser на локальной SQLite-QA: покупке #2 прописан сгенерённый PDF-чек,
    карточка `/moderation/2` показывает встроенный `<iframe>` с PDF + ссылку; роут
    `/moderation/2/receipt` отдаёт `Content-Type: application/pdf` inline (8346 байт).
    Скрин `data/screens/8_2_pdf_receipt.png`.
    **ДЕПЛОЙ:** push `0f57d5b` → git pull --ff-only /opt+/root → `pip install
    pypdfium2>=4.0` в `/opt/vk_auto_bot/.venv` (импортится; в этой сборке нет
    `__version__`, но это не важно) → restart admin-web+vk-bot (оба active; admin
    стартует ~5с, первый curl ловил транзиентный 502 от Caddy, после — `:8080/login=200`)
    → vk-bot чисто: BotPolling + Worker. Миграций нет (схема не менялась).
    **ЗАМЕЧЕНО на боевом (НЕ мой этап):** vk-bot спамит каждые 5с
    `Numbers exhausted for event 7: requested 6, available 5` — у одобренной покупки
    запрошено 6 номеров, в диапазоне свободно 5; воркер бесконечно ретраит. Это симптом
    БОЛЬШОГО косяка: **лимит номеров не соблюдается (overselling)** — бот принимает оплаты
    сверх диапазона, при нехватке воркер только спамит лог, админ не видит. Заказчик
    потребовал: не превышать лимит / заметно помечать админу / бот перестаёт реагировать
    на кодовое слово по исчерпании. Оформлено в `PLAN.md → Фаза 9` (после Фазы 8) + память
    `bug-number-limit-not-enforced`. Пересекается с багом статусной машины модерации.
- **2026-06-27. ЭТАП 8.1 (дубль кодового слова → дружелюбная ошибка) — ЗАВЕРШЁН И ЗАДЕПЛОЕН (коммит `54de8ec`).**
  edit.md #1. При создании/редактировании мероприятия с keyword, занятым другим
  АКТИВНЫМ мероприятием, форма повторно рендерится с понятным сообщением «Кодовое слово
  уже используется в мероприятии «<name>» (#id). Выберите другое слово или остановите
  то мероприятие.» — вместо Internal Server Error 500.
  - **Реализация (coder-сабагент по ТЗ оркестратора, скилы TDD+fastapi-patterns):**
    `services/events.py::find_active_event_by_keyword(session, keyword, *, exclude_id)`;
    в `routes/events.py` — pre-check конфликта в create/update (DB-агностично, через
    SELECT) + страховка `try/except IntegrityError` вокруг `commit`; helper
    `_keyword_conflict_message`. В update проверка только если мероприятие активно
    (частичный индекс `uq_event_keyword_active` бьёт только активные). keyword
    нормализуется `.strip().lower()`.
  - **РЕЗУЛЬТАТ:** pytest **169 passed, 1 skipped** (+3 теста в test_admin_events.py);
    e2e agent-browser на локальной SQLite-QA — создание мероприятия с занятым словом
    «сигма» отдаёт форму с ошибкой «…мероприятии «Постеры «Сигма» — июнь» (#1)…», не 500
    (скрин `data/screens/8_1_dup_keyword.png`). Задеплоено: push `54de8ec` → git pull
    --ff-only /opt+/root → restart admin-web+vk-bot (оба active) → smoke :8080/login=200.
    Миграций нет (схема не менялась).
- **НОВЫЙ КОСЯК (зафиксирован, чинить ПОСЛЕ P1):** при чехарде статусов чека в модерации
  (отклонил→одобрил без суммы→отклонил→сумма+одобрил→сменил сумму+одобрил) участнику в
  ВК НИЧЕГО не приходит, хотя в админке статусы меняются. КОРЕНЬ найден по коду (детали
  и план фикса — в памяти `bug-moderation-status-churn-no-delivery.md`): `reject()` не
  освобождает номера и не сбрасывает `numbers_assigned`; латч `numbers_assigned` навсегда
  выключает повторную доставку воркером; `set_amount` не меняет статус; approve без суммы
  → posters_count=0 → воркер молча скипает. Сделать approve/reject/revoke явной
  идемпотентной статусной машиной. **ДОП. ТРЕБОВАНИЕ ЗАКАЗЧИКА (2026-06-27):** без
  указанной суммы кнопка «Одобрить» не должна срабатывать (блокировать approve), рядом —
  пометка-hint «Укажите сумму».
- **2026-06-27. ФАЗА 8 — большой фидбек заказчика (edit.md, 13 пунктов). ИДЁТ.**
  План и проектирование всех пунктов — `PLAN.md → Фаза 8`. Приоритизация P0→P5
  (платёжный конвейер → диалог/данные → UX модерации → канбан → участники).
  - **РАБОЧЕЕ СОГЛАШЕНИЕ ЗАКАЗЧИКА: 1 ЭТАП = 1 СЕССИЯ.** После каждого этапа заказчик
    стартует НОВУЮ сессию с чистым контекстом. ⇒ в конце КАЖДОГО этапа всё фиксировать
    в STATE/PLAN. Деплой — инкрементальный по группам. Идём строго сверху вниз.
    **ЗАФИКСИРОВАНО (2026-06-27) в `CLAUDE.md → «Рабочее соглашение»`** (грузится в
    контекст каждой сессии) + в памяти проекта — чтобы на «продолжаем» продолжать без
    повторных объяснений процесса.
  - **Уточнения заказчика (зафиксированы в PLAN.md, Фаза 8, шапка):** публичное имя =
    всегда имя из ВК (first_name), полное ФИО — в карточку/модерацию; автоподтверждение =
    сумма≥цены + получатель (floor, НЕ точная кратность); abuse = глобальный дедуп +
    получатель + дата; «ручная бронь» = кнопка «Добавить вручную» в модерации (создаёт
    чек+псевдоучастника, поля: vk_link/ФИО/тел/файл чека/сумма/публичное имя, одобрение
    присваивает номера).
  - **ЭТАП 8.0 (баг #2: QR/картинка не всегда отправляется) — ЗАВЕРШЁН И ЗАДЕПЛОЕН (коммит `1e74c3f`).**
    **ДИАГНОСТИКА (на боевом, по логам vk-bot) — корень найден:** загрузка QR в VK
    падает интермиттентно (`json.JSONDecodeError: Expecting value line1 col1` и
    `VKAPIError_100: photo is undefined`) на шаге upload_files, потому что фото грузится
    через ОБЩИЙ с Long Poll http-клиент `bot.api` → конкуренция за aiohttp-сессию.
    Эмпирически подтверждено: тот же QR тем же токеном через ОТДЕЛЬНЫЙ `API(token)` =
    5/5 успешно (attachment вид `photo-237180199_457239022_...`). Старая ошибка из логов
    `VKAPIError_15 scopes` — это БЫЛО до выдачи токену права «Фото»; сейчас право ЕСТЬ
    (заказчик подтвердил), версия про токен ОТПАЛА.
    **ФИКС (проектирование оркестратора, код — coder-сабагент):** (1) грузить QR через
    выделенный `API(token)` (свой http-клиент, в `main._run_bot`, проброс в
    `register_handlers(bot, upload_api)`); (2) кэшировать attachment-строку в новой
    колонке `Event.qr_attachment` (грузим в VK ОДИН раз, дальше переиспользуем); сброс
    кэша при загрузке нового QR в админке; (3) НЕ глотать ошибку — колонка
    `Event.qr_last_error` (текст+дата), показ админу в events_list (бейдж «QR не ушёл»)
    и event_form (предупреждение). Чистая логика — `handlers.resolve_qr_attachment(event,
    upload_api, *, uploader_cls, retries=3)`. Миграция `0005_qr_attachment`.
    **РЕЗУЛЬТАТ:** код написан coder-сабагентом по ТЗ оркестратора; pytest **166 passed,
    1 skipped** (+5 тестов `test_qr_attachment.py`); e2e agent-browser — бейдж «QR не ушёл»
    и предупреждение в форме рендерятся (локальная SQLite-QA). Задеплоено: push `1e74c3f`
    → git pull /opt+/root (ff) → `alembic upgrade head` (0005, колонки qr_attachment/
    qr_last_error в БД подтверждены) → restart admin-web+vk-bot (оба active, smoke
    :8080/login=200, vk-bot стартовал чисто: BotPolling + Worker). События 2,6:
    send_qr=t, qr_attachment пуст → на след. кодовом слове бот зальёт QR через
    выделенный API и закэширует. **Живой прогон в ВК — за заказчиком** (отправить
    кодовое слово, проверить, что картинка дошла).
  - **ПОДТВЕРЖДЕНО В ЛОГАХ (для след. этапов):** баг #8 (PDF) реален —
    `PIL.UnidentifiedImageError: cannot identify image file ...pdf` (OCR не умеет PDF).
    Это этап P1/8.2.
- **2026-06-26. ФАЗА 7 — фидбек заказчика (QR/PDF/мелочи). ИДЁТ.** План — `PLAN.md → Фаза 7`.
  - **7.1 QR не уходит в бот + битое превью — ИСПРАВЛЕНО В КОДЕ (ждёт push+deploy).**
    Корень: при реврайте фронта Фазы 6 из `event_form.html` ВЫПАЛ тумблер `send_qr`,
    а бэкенд читает `send_qr=Form(None)` → раз поля нет, всегда `bool(None)=False`.
    Поэтому старое мероприятие (id=2, создано старой формой, send_qr=t) шлёт QR, а
    новые (id=4, send_qr=f) — нет. Второй баг: превью просило `/static/qr/<file>`,
    но статика смонтирована на `app/admin/static` (папки qr нет), файлы лежат в
    `data/qr` → битая картинка. Сделано: (1) вернул тумблер `send_qr` в блок «QR-код
    для оплаты» формы (default checked на создании); (2) добавил auth-роут
    `GET /events/{id}/qr` (FileResponse) в `events.py`, превью переключено на него;
    (3) регресс-тесты в `test_admin_events.py` (форма содержит send_qr; send_qr=on
    сохраняется). Тесты **161 passed, 1 skipped**. Файлы на сервере (data/qr) на
    месте, пути абсолютные — бот их найдёт. **Осталось:** пользователь push в GitHub
    → `git pull` на сервере (/opt и /root) → restart admin-web+vk-bot → smoke →
    `UPDATE events SET send_qr=true WHERE id=4` (чтобы текущее мероприятие заработало
    без пересохранения формы) → проверить отправку QR ботом.
  - **7.2 PDF-чеки (СЛЕДУЮЩЕЕ, после деплоя 7.1):** OCR должен читать чеки в PDF
    (приходят в основном PDF) + превью PDF в админке. Спроектировать: рендер первой
    страницы PDF в изображение (pdf2image/pypdfium2) перед Tesseract; в `_extract_receipt_attachment`
    PDF-документы уже подхватываются (doc.ext); добавить ветку pdf→image в OCR-пайплайн;
    превью чека в `purchase_detail.html` для application/pdf (iframe/embed или рендер).
  - **Пометки на будущее (не срочно, НЕ блокеры):**
    - Создание мероприятия с УЖЕ существующим кодовым словом → Internal Server Error
      (вероятно нарушение уникального индекса keyword). Надо отдавать понятную ошибку
      в форме, а не 500.
    - Если участник прислал чек БЕЗ имени, в публичную таблицу идёт пустое имя; при
      последующем дослании имени/телефона (без новой покупки) таблица НЕ обновляется —
      имя апдейтится только при новой подтверждённой покупке. Сделать апдейт строки
      таблицы при изменении контактов участника.
- **2026-06-26. ФАЗА 6 — ЗАВЕРШЕНА И ЗАДЕПЛОЕНА.** Все пункты 6.1–6.4 закрыты,
  коммит `de05025` запушен в GitHub и раскатан на боевой сервер. Тесты **159 passed,
  1 skipped**. Сервисы vk-bot/admin-web active, smoke :8080 /login=200, новый фронт
  отрисовывается на боевом (проверено agent-browser). Заказчик уже ходит по живой
  админке (200 в логах admin-web).
  - **6.3 (реврайт фронта) ЗАВЕРШЁН и ВИЗУАЛЬНО ПРИНЯТ.** architect(opus) + дизайн-скилы:
    новая токен-система (шкала отступов 8px, одна шкала радиусов, семантические токены
    обе темы, акцент indigo, НОЛЬ инлайн-стилей — было 20), все 10 шаблонов переверстаны,
    активная навигация из `request.url.path`. Визуальная QA в реальном браузере
    (agent-browser, обе темы, локально на SQLite): все страницы выровнены, панели с
    рамками, формы/таблицы аккуратные, тёмная тема корректна. Точечный фикс: запрет
    переноса кнопок в колонке действий (`td.col-actions .btn-row{flex-wrap:nowrap}`).
  - **ДЕПЛОЙ-нюанс:** на сервере /opt был на старом коммите с незакоммиченными
    SFTP-правками Phase 5 (фронт заливали файлами, не через git) → чистый `git pull`
    не проходил. По согласованию с заказчиком сделан `git reset --hard origin/main`
    на /opt и /root (отбрасываемое полностью содержится в `de05025`; .env/secrets/.venv
    сохранены — untracked). Впредь сервер обновлять ТОЛЬКО через git (не SFTP), иначе
    снова разойдётся.
  - **6.1 (backend-баги) ЗАВЕРШЕНА** (coder-агент, TDD, скилы fastapi-patterns +
    test-driven-development): (1) VK-ссылка на чат теперь `vk.com/gim{group_id}?sel={uid}`
    (group_id из app_settings, прокинут в контекст роутов модерации; формат `write-`
    выпилен полностью); (2) `{sheet_url}` по режиму — добавлен `sync.reader_url()`
    (`/preview`), хелперы `_resolve_sheet_url` в `worker.py` и `handlers.py` (ленивый
    импорт, фолбэк на public_table); (3) сообщение «просьба контактов» убрано —
    4-й msg-блок удалён из `event_form.html`, дефолт `send_need_contacts=False`.
    Тесты: **159 passed, 1 skipped** (+8 новых).
  - **6.3 (фронт) — ПОЛНЫЙ РЕВРАЙТ С НУЛЯ, ИДЁТ.** Заказчик забраковал текущую
    токен-систему Фазы 5 как «кривую» (рассыпанные инлайн-стили, плохое
    выравнивание) и потребовал переделку с нуля с использованием скилов. Запущен
    architect(opus)-агент со скилами `frontend-design-direction` +
    `design-taste-frontend`: новая дизайн-система (шкала отступов 8px, одна шкала
    радиусов, семантические токены обе темы, акцент indigo, НОЛЬ инлайн-стилей,
    выровненные формы/таблицы, активная навигация из `request.url.path`). Жёсткие
    контракты сохранены (theme-toggle/data-theme/localStorage, var-chips, QR-ids,
    `<b id="count">`, name=/action= форм, gim-ссылка, get_admin_title/is_winners_enabled).
  - **Локальная QA-среда поднята:** `scripts/local_dev_seed.py` (SQLite
    `./data/local_dev.db` + демо-данные), запуск uvicorn на :8000 с env
    (DATABASE_URL=sqlite+aiosqlite, login admin/admin). **agent-browser** установлен
    (v0.31.0, `A:\DevAI\agent-browser.cmd`) + движок браузера — связка
    браузер→CDP→скриншот ПРОВЕРЕНА. Визуальная проверка обеих тем + мобилы —
    после завершения реврайта.
  - **Дальше:** дождаться реврайт-агента → визуальная QA (agent-browser, обе темы) →
    починить найденное → pytest → деплой (GitHub push → git pull на сервере → restart
    → smoke) → финальная браузер-проверка на боевом.
- **2026-06-26. ФАЗА 6 (исходный план) — доводка фидбека + ПОЛНЫЙ редизайн фронтенда.**
  Повторная ревизия `edit.md` (по запросу заказчика) выявила
  3 недоделки + требование полностью переделать фронт. План — `PLAN.md → Фаза 6`.
  - **6.1 Баги поведения (чинить):** (1) VK-ссылка на чат сломана — в
    `moderation_list.html:63` / `purchase_detail.html:45` стоит
    `vk.com/write-{event_id}&vk_user_id=` (event_id ≠ group_id, формат невалиден);
    надо `https://vk.com/gim{group_id}?sel={vk_user_id}`, group_id из app_settings
    (`KEY_VK_GROUP_ID`), прокинуть в контекст роутов модерации. (2) `{sheet_url}`
    всегда `/p/{id}` (`worker.py:77`, `handlers.py:60`) — в режиме Google Sheets
    участнику не уходит ссылка на таблицу; добавить `sync.reader_url()` →
    `/preview`, выбирать по `event.google_sheet_url`. (3) Сообщение «просьба
    контактов» (msg_need_contacts) не убрано — убрать блок из формы, default
    `send_need_contacts=False`.
  - **6.2 Документация** решений (второй режим = поле на ивент; права доступа к
    таблице) — ЗАПИСАНО в Журнал решений PLAN.md.
  - **6.3 Редизайн фронта** как токен-система (скилы frontend-design-direction +
    design-taste-frontend подключены при проектировании). Диалы VARIANCE 3 /
    MOTION 2 / DENSITY 6, ванильный CSS/Jinja2, светлая+тёмная темы, единый акцент
    indigo. Перевёрстка всех 10 шаблонов.
  - **6.4 Тесты + деплой.**
  - Дизайн-направление и ТЗ по каждому пункту — в `PLAN.md → Фаза 6`.
- **2026-06-26. ФАЗА 5 — фидбек заказчика (edit.md). ЗАВЕРШЕНА.**
  - **Backend Фазы 4 ЗАВЕРШЁН** (123 passed, 1 skip): таймзона, тумблеры,
    гейтинг, QR best-effort.
  - **Frontend Фазы 5 ЗАВЕРШЁН** — CSS dark theme, редизайн ВСЕХ шаблонов,
    звёздочки, QR-превью, единый блок сообщений, VK-ссылки на чат,
    настройки (название, вкладка победителей), google_sheet_url + миграция 0004.
  - **5.5.2 + 5.5.3 ЗАВЕРШЕНЫ** — sync-логика Google Sheets восстановлена:
    `app/sheets/client.py` (ленitive gspread), `app/sheets/sync.py`
    (`sync_event_to_sheet`: шапка, upsert, удаление лишних строк). Воркер
    вызывает sync best-effort если `event.google_sheet_url` задан. Tests: 9 в
    `test_sheets_sync.py` + 3 в `test_worker.py` (итого ~135+ passed).
  - **5.6 ЗАВЕРШЕНЫ** — E2E тесты (7: полный флоу, публичная таблица HTTP,
    Google Sheets sync, отзыв номеров, каскадное удаление, настройки,
    несколько участников) + тесты тёмной темы (5: theme toggle, admin.js,
    settings page) + обновлены тесты admin_events под google_sheet_url.
  - **5.7 ЗАВЕРШЁН** — деплой на сервер: 152 passed, оба сервиса active.
  - Доступ к боевому серверу: root@185.228.72.118, проект `/opt/vk_auto_bot`
    (рантайм) + `/root/vk_auto_bot` (git-checkout). Коннект — paramiko
    (`scripts/_ssh_run.py`, пароль в env `SSH_PASS`, в код НЕ писать).
- **2026-06-26. Google Sheets ВОССТАНОВЛЕН как опциональный 2-й режим.** Причина:
  заказчик хочет дать возможность тестировать оба режима (своя HTML-таблица vs
  Google Sheets). Сделано:
  - **`app/sheets/client.py`** — ленивый gspread-клиент через service account.
  - **`app/sheets/sync.py`** — `sync_event_to_sheet(session, event_id, url)`:
    идемпотентная: создаёт шапку если пусто, проверяет/корректирует формат,
    upsert approved-номеров, удаление лишних строк. Best-effort (try/except).
  - **`worker.py`** — после присвоения номеров, если `event.google_sheet_url`
    задан → вызов `sync_event_to_sheet` (best-effort, не падает воркер).
  - **`requirements.txt`** — добавлены `gspread>=6.0`, `google-auth>=2.0`.
  - **Тесты**: `test_sheets_sync.py` (9 tests: URL parsing + sync logic с моками),
    `test_worker.py` (+3 tests: sync called / not called / failure resilient).
  - Два режима: (1) HTML `/p/{id}` — по дефолту, (2) Google Sheets — если
    `event.google_sheet_url` задан в форме мероприятия. Ссылка для участников
    определяется автоматически.
- **2026-06-26. Авто-подхват VK-токена без рестарта + грабли Google API.**
  1. **`app/bot/main.py` переписан как СУПЕРВИЗОР.** Раньше токен читался один раз
     при старте → смена в админке требовала `systemctl restart vk-bot`. Теперь
     `_amain` — цикл: каждые `RELOAD_INTERVAL_SEC=10` сек перечитывает токен из БД;
     если изменился (появился/сменился/очищен) — отменяет текущий
     polling+worker-таск (`_run_bot` через `asyncio.Task` + `_stop_task`) и
     пересоздаёт с новым токеном. Если polling сам упал — сбрасывает и пересоздаёт.
     Процесс больше не завершается при отсутствии токена, а ждёт ввода. Итог: ввод/
     смена токена в `/settings` подхватывается за ~10 сек, рестарт НЕ нужен.
     Сообщение в `admin/routes/settings.py` и подсказку в `settings.html` обновил.
     Проверено на сервере: логи `Bot supervisor started ... → Starting BotPolling →
     Worker started`, оба сервиса active, :8080/login=200. Пользователь запушил правки
     в GitHub (коммит `5f10cbb`); на сервере `/opt` и `/root` приведены к origin/main
     через `git reset --hard origin/main` (рабочее дерево == origin, локальных
     расхождений НЕТ; .env/.venv/secrets — untracked, не тронуты). pip — no-op,
     alembic на head. Сервисы перезапущены и проверены.
  2. **Грабли Google: `APIError [403] Google Drive API has not been used in project
     ... or it is disabled`.** В GCP-проекте нового service-account (`vkautobot`,
     `first-720@...`) НЕ включены Drive/Sheets API. gspread требует ОБА. Лечится в
     консоли (НЕ код): включить Google Drive API и Google Sheets API для проекта,
     подождать пару минут. Передано заказчику. (Ранний test-sheets=200 в 08:32 был,
     видимо, на прежнем SA — после замены json всплыло.)
- **2026-06-26. ОБНОВЛЕНИЕ + ДОВОДКА ДЕПЛОЯ (git pull на сервере).** На сервере
  сделан `git pull` /opt и /root до `origin/main` 520be6f (fast-forward; локальные
  правки requirements.txt/systemd были тем же деплой-фиксом, но в кривой кодировке —
  отброшены в пользу чистого UTF-8 из origin). `pip install` — no-op (пины те же),
  `alembic` уже на head (0002). **Google SA-json подключён:** заказчик положил
  `secrets/vkautobot-ad8c45a7a241.json`, но `.env` ждал `service_account.json` —
  сделана копия `secrets/service_account.json` (owner vkbot, chmod 600, валидный
  service_account, client_email `first-720@vkautobot.iam.gserviceaccount.com`).
  Сервисы перезапущены: **admin-web active** (:8080 /login=200, /,/events,/settings=303,
  публичный IPv4 :8080=200), **vk-bot active running** — Long Poll стартовал, worker
  interval=5s. **Бот ЖИВОЙ:** VK-токен/group_id/почта Sheets уже введены заказчиком
  через админку ранее (в логах test-vk=200 и test-sheets=200 в 08:32). Деплой
  полностью функционален. (Подключение к серверу делал через paramiko из-за отсутствия
  sshpass/plink на Windows; временный helper-скрипт с паролем удалён.)
- **2026-06-26. БОЕВОЙ ДЕПЛОЙ выполнен** (сервер cloud.ru, root@185.228.72.118,
  Ubuntu 24, Python 3.12.3). Рантайм — **`/opt/vk_auto_bot`** (НЕ `/root/vk_auto_bot`:
  `/root` имеет права 700, служба от vkbot туда не зайдёт; копия проекта развёрнута в
  /opt, владелец vkbot, копия в /root оставлена как git-checkout). Сделано: venv +
  зависимости; роль PG `vkbot` (пароль задан, в `.env`); `.env` создан (сгенерированы
  `SECRETS_KEY`, `SESSION_SECRET`, `ADMIN_PASSWORD_HASH`; VK_TOKEN/GROUP_ID пустые —
  через админку); `alembic upgrade head` (0001+0002, все таблицы); systemd
  `admin-web`(active)/`vk-bot`(idle до токена) enabled; Caddy-фрагмент в
  `/etc/caddy/conf.d/vk_admin.caddy` + `import` дописан в Caddyfile, reload (старые
  сайты целы), слушает :8080. Проверено: `/login`,`/`,`/events`,`/settings` = 200,
  неверный пароль = 401, статика и публичный IPv4 :8080 = 200. Логин/пароль админа
  переданы пользователю в чате (в репозиторий/STATE НЕ пишем). **Осталось на стороне
  заказчика/владельца сервера:** (1) открыть порт **8080** в security group cloud.ru;
  (2) положить Google SA-json в `/opt/vk_auto_bot/secrets/service_account.json`;
  (3) в админке `/settings` ввести VK-токен/group_id/почту → `systemctl restart vk-bot`.
- **2026-06-26. Фаза 3 (UX-конфигурация для заказчика) — ЗАВЕРШЕНА, тесты зелёные
  118 passed / 1 skipped.** Цель: заказчик настраивает всё из админки, без «кишок».
  Реализовано (кодер-сабагент по полному ТЗ оркестратора):
  1. **Настройки в БД, не в `.env`:** новая таблица `app_settings` (key/value,
     модель `AppSetting`, миграция `0002_app_settings`). Сервис
     `core/services/app_settings.py` (`get_setting/set_setting/is_set`, константы
     ключей `KEY_VK_TOKEN/KEY_VK_GROUP_ID/KEY_SHEETS_OWNER_EMAIL`).
  2. **Шифрование секретов:** `core/crypto.py` (Fernet), ключ `SECRETS_KEY` в `.env`,
     генератор `scripts/gen_secrets_key.py`. Шифруется только `vk_token`
     (`SECRET_KEYS`). В HTML токен не отдаётся (поле password пустое, показываем
     «задан/не задан»).
  3. **Бот** (`bot/main.py`): VK-токен грузится из БД с fallback на `.env`; `Bot`
     создаётся внутри `_amain` (модульного `bot` больше нет).
  4. **Sheets** (`sheets/sync.py`): `create_sheet(title, owner_email=None)` шарит
     лист владельцу как редактору (notify=False), если email задан — заказчик видит
     ОРИГИНАЛ (не копию) в своём Drive; формально владелец остаётся service account.
     Решение по владению: «авто-создание + авто-шар заказчику» (OAuth отклонён из-за
     верификации Google под scope `spreadsheets`). `events.py` передаёт owner_email
     из настроек.
  5. **Админка**: страница `/settings` (`admin/routes/settings.py` + `settings.html`
     + ссылка в base-nav) — ввод токена/group_id/почты + кнопки «Проверить VK»
     (`bot/vk_check.py` → `groups.getById`) и «Проверить Google Sheets»
     (`sync.test_connection` — создаёт/шарит/удаляет временный лист). Тест-кнопки
     работают на СОХРАНЁННЫХ значениях.
  - Что осталось ОДНОРАЗОВЫМ на стороне разработчика при деплое (НЕ заказчик):
    создать Google service account + положить JSON; сгенерировать `SECRETS_KEY`.
    Дальше VK-токен/group_id/почту заказчик вводит и проверяет сам из админки.
- **2026-06-25 (правка деплоя).** По требованию заказчика reverse proxy переведён с
  nginx на **Caddy** (на сервере уже крутится Caddy с другими сайтами — подключаемся
  отдельным фрагментом `caddy/vk_admin.caddy` на порту 8080 через `import`, чужое не
  трогаем). Автодеплой `scripts/deploy.sh` удалён — деплой теперь руками по
  копипаст-инструкции в README (§7 Caddy, раздел «Обновление на сервере»). Файлы
  `nginx/admin.conf` и `scripts/deploy.sh` удалены; README/ARCHITECTURE/PLAN обновлены.
- **2026-06-25. Фаза 2 идёт. Этапы 2.1–2.12 ЗАВЕРШЕНЫ и приняты.** Каркас + config/db
  + Alembic. Модели. Сервисы core. OCR. Sheets. Бот-диалог (dialog/handlers/main).
  Воркер: `bot/worker.py` — `process_pending` (DI-колбэки send/sync) присваивает
  номера approved&!assigned (идемпотентно: numbers_assigned до отправки),
  msg_after_payment+msg_need_contacts, синк add_rows; NumbersExhausted→лог-алерт не
  падает; `worker_loop` запускается в main.py рядом с Long Poll. Серверная часть
  (бот+воркер+ядро) ГОТОВА. Админка-auth: `admin/{auth,deps,main}.py` (FastAPI +
  SessionMiddleware, bcrypt-вход из .env, require_login, шаблоны base/login/index +
  CSS), `scripts/gen_password_hash.py`. Админка-мероприятия: `admin/routes/events.py`
  (список/создание+QR+авто-Google-лист/правка/toggle/каскад-удаление) + шаблоны
  events_list/event_form; `sheets.sync.delete_sheet`, `qr_dir` в config, пин
  `bcrypt<4.1`. Админка-модерация: `admin/routes/moderation.py` (очередь+фильтр+поиск,
  карточка, чек FileResponse, approve↔reject, revoke+rebuild_sheet, set_amount, правка
  контактов) + шаблоны. Админка-участники/победители: `admin/routes/participants.py`
  (список+номера), `admin/routes/winners.py` (pick_winners display-only) + шаблоны.
  Вся функциональность готова. Деплой: systemd×2 (vk-bot/admin-web), Caddy-фрагмент
  `caddy/vk_admin.caddy` (по IP, порт 8080, подключается к существующему Caddy через
  `import`), расширенный README с ручной копипаст-инструкцией. **ФАЗА 2 ЗАВЕРШЕНА — этапы 2.1–2.13
  приняты.** Приёмка по `ТЗ_ИТОГ §15`: все 9 критериев покрыты кодом и тестами (п.1–8
  автотестами+ревью; п.9 — конфиги деплоя готовы, фактическое развёртывание — на
  боевом сервере заказчика). Тесты: **105 passed, 1 skipped** (реальный OCR без
  бинаря). Проект готов к передаче/развёртыванию.

## Принятые решения (кратко, детали в ТЗ_ИТОГ.md §4)

- Стек: **Python 3.12** — бот `vkbottle/vk_api` (Long Poll), админка FastAPI+Jinja2,
  SQLAlchemy(async)+asyncpg, **PostgreSQL**.
- OCR: **Tesseract** локально (rus+eng), без облака.
- Проверка оплаты: OCR + тумблер автоподтверждения на мероприятие; «непонятные» —
  в ручную очередь; смена статусов в обе стороны; просмотр чека + привязка к юзеру
  + поиск.
- Кол-во постеров = floor(сумма / цена билета). Скрины (`tz/photo_*.jpg`) — это
  КОНКУРЕНТ; копируем механику, НЕ данные. «СИГМА» — их получатель, у заказчика свой.
- Всё настраивается в админке на каждое мероприятие: кодовое слово, цена билета,
  кол-во билетов (диапазон), **кол-во победителей**, **сроки (начало/конец)**,
  шаблоны, QR, получатель для OCR-сверки, автоподтверждение. Ничего не захардкожено.
- Участник присылает **чек + имя + телефон** (только имя, без ФИО). Собираем
  (регэксп на телефон), храним, админ правит. Оплата без имени/телефона НЕ блокирует
  присвоение номеров — выдаём + напоминаем участнику дослать.
- Сверка OCR = получатель платежа (поле `expected_recipient`, организация заказчика)
  + сумма.
- **Несколько мероприятий параллельно** (разные кодовые слова). Вне сценария бот
  молчит. Остановка = бот не реагирует. Удаление = каскадно чистит ТОЛЬКО данные
  этого мероприятия (ON DELETE CASCADE) + его Google-лист.
- **Админ — 1 аккаунт**, логин/хэш пароля из `.env` (ADMIN_LOGIN открыто,
  ADMIN_PASSWORD_HASH — bcrypt). Таблицы admins нет.
- Данные: Postgres — источник, Google Sheets — зеркало; таблица авто-создаётся при
  создании мероприятия и привязывается.
- **Публичная таблица: только `Номер | Имя | Оплачено`, только оплаченные номера,
  без пустых, имя — только имя.** Подробность (vk_id, ссылка, телефон) — в админке.
- Победители — `winners_count` штук, только из оплаченных (присвоенных) номеров.
- Отзыв номеров через админку (статус `revoked`) — освобождает номера. Все тексты
  бота настраиваются на мероприятие (дефолт при создании, потом редактируется).
- Инфра: ВК-сообщество и токен есть, Google-аккаунт есть; админка заказчика — по IP
  (без домена), демо разработчика — по своему домену. Хостинг cloud.ru.

## Следующий шаг

- **⚑ АКТИВНО: ПЕРЕБОР IP сервера cloud.ru (ТСПУ/РКН блокирует).** Заказчик меняет публичный IP на
  cloud.ru → ассистент переключает сервер на новый IP по **RUNBOOK в «Текущая точка» (верхний блок
  от 2026-06-28)**. Это та же VM, всё уже развёрнуто — нужно только сменить IP в Caddy
  (`/etc/caddy/Caddyfile`: адрес сайта + `default_sni`) и в репо `caddy/vk_admin.caddy`, reload, smoke.
  На старте новой сессии: спросить у заказчика новый IP, открыть runbook, выполнить шаги 1–7.
  Полный пошаговый рецепт и список «что уже есть на сервере» — там же. См. также PLAN.md → Фаза 10.
- **✅ НОВЫЙ БОЕВОЙ СЕРВЕР cloud.ru РАЗВЁРНУТ С НУЛЯ (2026-06-28)** — `https://37.230.192.61`,
  HTTPS (tls internal), pytest зелёный, smoke по HTTPS пройден. См. «Текущая точка».
  **ЖДЁМ ДЕЙСТВИЙ ЗАКАЗЧИКА:** (1) остановить старый бот на 185.228.72.118 (конфликт Long Poll);
  (2) войти в админку и ввести VK-токен + Google в `/settings`; (3) после проверки — старый сервер
  можно гасить полностью. БД на новом — чистая (данные не переносили по решению заказчика).
- **✅ ДЕПЛОЙ ФАЗЫ 9 ВЫПОЛНЕН (2026-06-28)** — миграция 0010 применена, спам `Numbers exhausted`
  исчез на проде. **✅ SECURITY-АУДИТ И ХАРДНИНГ ВЫПОЛНЕНЫ** (коммит `3689aba`, см. «Текущая точка»).
- **ОСТАТОЧНЫЕ РИСКИ БЕЗОПАСНОСТИ — за заказчиком (требуют домена/консоли cloud.ru):** (1) подключить
  ДОМЕН → HTTPS (Caddy авто-TLS) + `https_only=True`; (2) SSH-ключи + выключить парольную auth +
  ограничить порт 22 на IP заказчика; (3) ограничить порт 8080 на IP заказчика в security group.
  Подробности и обоснование — «Текущая точка».
- **(опц.) Аутентифицированный read-only e2e-обход прода** — если заказчик даст админ-пароль
  (деструктивные CRUD на живом мероприятии #11 «автохайп» НЕ запускать).
- **ЭТАП 8.12 / финальная приёмка.** Полный `pytest` зелёный (сейчас **315/2**), alembic head на
  боевом (0010), сквозная smoke + agent-browser ключевых экранов в обеих темах, передача заказчику
  для ручного прогона бот-сценария в ВК (бот молчит при исчерпании; нехватка номеров → красная
  пометка «не хватило N»; картинки к сообщениям; смена ссылки таблицы у идущего мероприятия).
- **ЭТАП 8.12 / финальная приёмка (после деплоя Фазы 9).** Полный `pytest` зелёный (сейчас 310/2),
  alembic head на боевом, сквозная smoke + agent-browser проверка ключевых экранов в обеих темах,
  передача заказчику для ручного прогона бот-сценария в ВК (в т.ч. живая проверка: бот молчит при
  исчерпании номеров; при нехватке номеров админ видит красную пометку «не хватило N» и возвращает
  часть денег; картинки к сообщениям доходят; смена ссылки таблицы у идущего мероприятия).
- **ФАЗА 9 (overselling/контроль лимита) — КОД+ТЕСТЫ ГОТОВЫ, деплой ждёт SSH_PASS** (см. «Текущая точка»).
- **8.14 ЗАВЕРШЁН И ЗАДЕПЛОЕН** этой сессией (картинки к сообщениям, миграция 0009; см. «Текущая точка»).
- **8.13 ЗАВЕРШЁН И ЗАДЕПЛОЕН** этой сессией (`6cfa240`).
- **8.11 ЗАВЕРШЁН И ЗАДЕПЛОЕН** (`cba3bc0`).
  По плану `PLAN.md → Фаза 8, 8.11` (edit.md #10/#18). Поиск по выбранному scope: по имени ВК,
  ФИО, телефону, vk id — ВСЕГДА (и в «Все», и в конкретном). По НОМЕРУ билета — ТОЛЬКО при
  выбранном конкретном мероприятии (при «Все» поиск по номеру отключён). Добавить поле поиска `q`
  в тулбар `participants_list.html` (как в модерации), параметр `q` в роут `participants_list`,
  применять фильтр к обоим режимам (в «Все» — фильтр по vk_user_id-агрегату: подзапрос на
  совпадение в любой строке Participant; в конкретном — join PosterNumber для номера). Сохранять
  `q` при пагинации и смене scope. Скилы: fastapi-patterns + agent-browser. Агент: coder (sonnet).
  Порядок дальше: **8.11 → 8.13 → 8.14 → 8.12 (финальная приёмка) → Фаза 9 (overselling).**
- **8.13 и 8.14 СПРОЕКТИРОВАНЫ (2026-06-28), развилки с заказчиком закрыты** — готовы к
  реализации по ТЗ в `PLAN.md → Фаза 8` (см. «Текущая точка»). 8.13 — смена ссылки/режима таблицы
  у идущего мероприятия с немедленной миграцией данных; 8.14 — картинки-вложения к 3 сообщениям.
  Оба P4. **Деплой каждого этапа делает ассистент:** push в GitHub → коннект по `ssh.md`
  (root@185.228.72.118, paramiko `scripts/_ssh_run.py`, пароль в env `SSH_PASS`) → git pull
  /opt+/root → `alembic upgrade head` (8.14 несёт миграцию 0009) → restart admin-web+vk-bot → smoke.
- **ЭТАП 8.9 (модерация-канбан) — ЗАВЕРШЁН И ЗАДЕПЛОЕН** (`936c753`, см. «Текущая точка»).
- **ЭТАП 8.8 (кнопка «Добавить вручную») — ЗАВЕРШЁН И ЗАДЕПЛОЕН** (`9935297`, см. «Текущая точка»).
- **ЭТАП 8.6+8.7 (автоподстановка суммы/контактов + публичное имя) — ЗАВЕРШЁН И ЗАДЕПЛОЕН**
  (`846cd65`).
- **ЭТАП 8.5 (Отклонить/Отозвать + статусная машина) — ЗАВЕРШЁН И ЗАДЕПЛОЕН** (`071800a`).
  Косяк недоставки `bug-moderation-status-churn-no-delivery` закрыт этим этапом.
- **ЭТАП 8.4 (FSM-диалог: ФИО+телефон) — ЗАВЕРШЁН И ЗАДЕПЛОЕН** (`5da070d`). Ждём живой
  прогон заказчика в ВК.
- **ЭТАП 8.3 (Авто-подтверждение + abuse) — ЗАВЕРШЁН И ЗАДЕПЛОЕН** (`310efda`).
- **ЭТАП 8.2 (PDF-чеки) — ЗАВЕРШЁН И ЗАДЕПЛОЕН** (`0f57d5b`).
- **ВАЖНО — после P1 (8.2, 8.3) чинить НОВЫЙ КОСЯК модерации** (см. «Текущая точка» и
  память `bug-moderation-status-churn-no-delivery.md`): статусная машина модерации не
  доставляет номера после чехарды статусов. Это перекликается с 8.3 (авто-подтверждение)
  и edit.md (объединение «отклонить»/«отозвать» в одну кнопку, авто-подстановка суммы/
  имени) — возможно решать вместе.
- **Этап 8.1 (дубль кодового слова) — ЗАВЕРШЁН И ЗАДЕПЛОЕН** (`54de8ec`).
- **Этап 8.0 (QR) — ЗАВЕРШЁН И ЗАДЕПЛОЕН** (`1e74c3f`). Ждём живой прогон заказчика в ВК.
- **Фаза 6 завершена и задеплоена. Ждём фидбек заказчика по новому фронту.** Если
  нужны правки дизайна — итерировать через локальную SQLite-QA (`scripts/local_dev_seed.py`
  + uvicorn :8000) и agent-browser, затем коммит → push → `git reset --hard` на сервере.
  Локальный uvicorn для QA мог остаться запущен на :8000 (фоновый) — при необходимости
  остановить.

## Нюансы (грабли, лимиты, особенности — пополняется по ходу)

- **НОВЫЙ БОЕВОЙ СЕРВЕР cloud.ru (2026-06-28) — рецепты деплоя/доступа:**
  - **Доступ:** `ssh -i "A:\DevAI\Zakazi\ыыр\auto_bot\id_rsa" auto@37.230.192.61`, sudo
    БЕСПАРОЛЬНЫЙ (`sudo` напрямую, без `sudo su`). Ключ копировать в `/tmp/vk_id_rsa` + `chmod 600`
    (домашний путь с кириллицей ломает known_hosts — добавлять `-o UserKnownHostsFile=/dev/null
    -o StrictHostKeyChecking=no`). **Старый `ssh.md`/`scripts/_ssh_run.py` — про СТАРЫЙ сервер
    185.228.72.118, тут НЕ применимы.**
  - **СЕТЬ ФЛАПАЕТ:** и SSH (порт 22 то ок, то таймаут), и исходящий с сервера (github/apt/
    keyserver временами отваливаются по таймауту). ВСЕ ssh- и git-команды оборачивать в ретраи
    (на сервере: `for i in 1..6; do git pull && break; sleep 5; done`). ⚠️ ГРАБЛИ: если `git pull`
    упал, НЕ копировать `caddy/vk_admin.caddy`→`/etc/caddy/Caddyfile` (затрёшь рабочий конфиг
    старой версией). Перед `cp` проверять `git rev-parse --short HEAD` == целевой коммит.
  - **apt:** штатное зеркало `mirror.yandex.ru:80` НЕДОСТУПНО (порт 80) → переключено на
    `https://archive.ubuntu.com` (`/etc/apt/sources.list`); IPv6 нет → `Acquire::ForceIPv4`
    в `/etc/apt/apt.conf.d/99force-ipv4`. Предуст. cloud.ru-репо `vmmanager-osconfig` таймаутит —
    безвредно (apt игнорит).
  - **Python 3.12 через deadsnakes ВРУЧНУЮ:** `add-apt-repository ppa:deadsnakes/ppa` ПАДАЕТ
    (лезет в `api.launchpad.net` — закрыт), хотя контент `ppa.launchpadcontent.net` (443) открыт.
    Решение: ключ `curl "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0xF23C5A6CF475977595C89F51BA6932366A755776" | gpg --dearmor -o /etc/apt/keyrings/deadsnakes.gpg`
    + `deb [signed-by=…] https://ppa.launchpadcontent.net/deadsnakes/ppa/ubuntu/ jammy main`.
  - **Caddy `tls internal` на голом IP:** ОБЯЗАТЕЛЕН `default_sni 37.230.192.61` в глобальном
    блоке Caddyfile — браузер/curl не шлют SNI для IP (RFC 6066), без него handshake = TLS
    `internal error`. Тестить: `curl -k --resolve 37.230.192.61:443:127.0.0.1 https://37.230.192.61/...`.
- **SECURITY-харднинг (2026-06-28):** защита админки — `app/admin/security.py`
  (`SecurityHeadersMiddleware` + in-memory rate-limit логина по IP). CSP включает
  `'unsafe-inline'` для script/style — в шаблонах есть инлайн-`onclick` (тема, клик по строке
  участника) и Google Fonts; если уберут инлайн — ужать CSP. Rate-limit берёт IP из ПОСЛЕДНЕГО
  `X-Forwarded-For` (его ставит наш Caddy из реального пира; первые элементы подделываемы). Счётчик
  `_failures` — модульный глобал, в тестах сбрасывается autouse-фикстурой в `tests/conftest.py`.
  uvicorn запущен с `--no-server-header` (правка в unit admin-web). `/docs`/`/openapi.json`
  отключены (`docs_url=None` и т.д. в `FastAPI(...)`). **fail2ban** на сервере: jail `sshd`
  (`/etc/fail2ban/jail.local`, эскалация бана до 7д) — против активного SSH-брутфорса. Проверка
  бана: `fail2ban-client status sshd`. **ОСТАЛОСЬ (заказчику):** TLS через домен (тогда
  `https_only=True`), SSH-ключи + off парольной auth, ограничить порты 22/8080 на IP в security
  group cloud.ru.

- **8.14 картинки к сообщениям (`EventMessageImage`):** механика = копия QR (кэш VK-attachment
  в строке таблицы, выделенный `upload_api`, best-effort). Грабли: (1) дефолтный
  `uploader_cls=PhotoMessageUploader` биндится при объявлении `resolve_message_attachment` —
  для подмены в тестах патчить САМУ функцию `resolve_message_attachment`, не класс. (2)
  `_handle_receipt`/`_handle_contacts` в тестах зовут с `bot=None` → используется
  `upload_api or getattr(bot, "api", None)`. (3) Сироты файлов возможны только в редкой ветке
  IntegrityError-конфликта keyword при update (картинки пишутся на диск до финального commit;
  обработка картинок стоит ПОСЛЕ миграции таблицы, чтобы её rollback не оставлял сирот). (4)
  «Инструкцию» картинкой НЕ снабжали — там штатный QR.
- **curl на Windows (Git Bash) + `-F field=@file`:** `curl.exe` — НАТИВНЫЙ Windows-бинарь, НЕ
  понимает bash-путь `/tmp/...` для загрузки файла → молча падает (exit 26), запрос НЕ доходит
  до сервера, `-w %{http_code}` показывает `000`, в логе сервера запроса нет. Для multipart-аплоада
  в e2e класть файл в проектную папку и давать ОТНОСИТЕЛЬНЫЙ путь (`-F "f=@data/x.png"`) либо
  `cygpath -w`. GET-запросы без файлов так не страдают.
- **Локальная QA: занятый порт.** Перед стартом uvicorn проверять порт
  (`Get-NetTCPConnection -LocalPort N -State Listen`) и убивать висящий старый процесс
  (`Stop-Process -Force`) — иначе новый сервер не забиндится (бывало на :8000/:8001), а старый
  отдаёт УСТАРЕВШУЮ схему/код. Уведомление о фоновом uvicorn может прийти со статусом «failed
  exit 127/1» после штатного kill — это нормально, ориентироваться на реальную проверку порта.
- **8.11 поиск в «Участниках» — ILIKE без экранирования `%`/`_`.** `_text_conditions` строит
  `ilike(f"%{qs}%")` без эскейпа спецсимволов LIKE. Если заказчик введёт `%` или `_` в строку
  поиска — они трактуются как wildcard (неожиданно широкая выдача). Не критично для текущего
  объёма; при необходимости — `.ilike(..., escape='\\')` + экранирование qs. Та же необэскейпленная
  схема в `moderation._apply_search` (общий паттерн).
- **8.10 агрегация участников по `vk_user_id` (режим «Все мероприятия»):** один человек
  склеивается в одну строку/одну карточку (`/participants/vk/{vk}`) по `vk_user_id`. ГРАБЛИ:
  у псевдоучастников, добавленных вручную в модерации (этап 8.8), `vk_user_id` ОТРИЦАТЕЛЬНЫЙ и
  уникален лишь в рамках события (`-1`, `-2` на событие). Если в двух разных мероприятиях есть
  псевдоучастники с одинаковым отрицательным id (оба `-1`) — в режиме «Все» они склеятся в одну
  строку/карточку, хотя это разные люди. Принятое ограничение (редкий ручной кейс; реальные ВК-id
  положительны и глобально уникальны). При выборе КОНКРЕТНОГО мероприятия карточка по
  `participant.id` — корректна всегда. Если понадобится развести — в «Все» агрегировать только
  `vk_user_id > 0`, отрицательные показывать пер-ивент.

- **HTML-`<select>` + `int|None` query-параметр = 422 на пустом value.** Пункт-плейсхолдер
  (value="") всегда отправляется формой → FastAPI не парсит "" как int. Для ЛЮБОГО
  опционального int-параметра из дропдаунов использовать `app/admin/deps.py::OptionalInt`
  (Annotated + BeforeValidator: "" → None). Сейчас так в moderation/participants/winners. При
  добавлении новых фильтров-дропдаунов (8.10/8.11) — брать `OptionalInt`, не голый `int | None`.

- **Локальная браузерная QA без PG:** `engine` в `db.py` берёт `settings.database_url`
  при импорте → локально гоняем на SQLite, задав env `DATABASE_URL=sqlite+aiosqlite:///./data/local_dev.db`.
  Сид: `PYTHONPATH=. DATABASE_URL=... python scripts/local_dev_seed.py` (drop+create_all +
  демо-данные, login admin/admin). Запуск: тот же набор env (DATABASE_URL, SECRETS_KEY,
  ADMIN_LOGIN, ADMIN_PASSWORD_HASH, SESSION_SECRET, PUBLIC_BASE_URL) + `python -m uvicorn
  app.admin.main:app --host 127.0.0.1 --port 8000`. Скрипт `scripts/local_dev_seed.py`
  держит env-дефолты вверху ДО импорта app.* . `./data/local_dev.db` в .gitignore.
- **agent-browser на Windows:** CLI = `A:\DevAI\agent-browser.cmd` (v0.31.0, npm global
  prefix у пользователя = `A:\DevAI`, НЕ в PATH этой сессии — звать по полному пути).
  Гайд: `agent-browser skills get core`. Грабли PowerShell: native exe пишет статус в
  stderr («[agent-browser] launched browser»), а `2>&1 | Select` оборачивает это в
  NativeCommandError и рвёт цепочку команд — вызывать `open`/`screenshot` БЕЗ `2>&1`,
  отдельными вызовами (сессия браузера живёт между командами). Связка
  браузер→CDP→скриншот проверена (`data/screens/`). Команды вьюпорта/ресайза:
  `viewport <w> <h>` принимается НЕ как топ-левел (давало Unknown command) — мобилу
  проверять отдельно, адаптив в CSS стандартный (бургер <820px).
- **ГРАБЛИ браузерной QA — кэш CSS.** При итерации дизайна браузер кэширует
  `/static/style.css`. Если переименовать классы (старый кэш ⇄ новые шаблоны) —
  страницы выглядят «сломанными»/невыстроенными, ХОТЯ CSS и разметка верные. Это
  дало ложные «косяки» при первом прогоне. Лечение: `agent-browser close --all` +
  заново открыть (свежий запуск браузера = без кэша); `reload` обычным кэшем не
  всегда сбрасывает. Перед выводами о вёрстке — убедиться, что отдаётся свежий CSS.


- **ГРАБЛИ загрузки фото в VK (Фаза 8.0): НЕ грузить через `bot.api`** — он шарит один
  aiohttp http-клиент с Long Poll, и конкуренция рвёт upload (пустой ответ сервера
  загрузки → `json.JSONDecodeError: Expecting value line1 col1` / `VKAPIError_100: photo
  is undefined`), интермиттентно. Грузить через ОТДЕЛЬНЫЙ `API(token)` (свой http-клиент;
  создаётся в `main._run_bot`, прокидывается в `register_handlers(bot, upload_api)`).
  Плюс: после первой успешной загрузки attachment-строка кэшируется в `Event.qr_attachment`
  (грузим в VK один раз; сброс при загрузке нового QR в админке). Ошибки больше не
  глотаются молча — `Event.qr_last_error` показывается админу (бейдж в списке,
  предупреждение в форме). Логика — `handlers.resolve_qr_attachment`.
- **VK Error 15 (subcode 1133) на `photos.getMessagesUploadServer` = у токена
  сообщества нет права «Фотографии».** Лечится пересозданием ключа сообщества в ВК
  с галкой «Фотографии» (не код). В коде — загрузка QR теперь best-effort
  (`handlers.py:_handle_keyword`, try/except): инструкция шлётся даже без QR. ЛЮБУЮ
  отправку с attachment держать устойчивой — иначе падает весь обработчик и бот
  «молчит».
- **Боевой сервер:** root@185.228.72.118, проект `/opt/vk_auto_bot` (рантайм, owner
  vkbot) + `/root/vk_auto_bot` (git-checkout). Коннект с Windows — paramiko
  (`scripts/_ssh_run.py`, пароль в env `SSH_PASS`, в код/STATE НЕ писать). PG —
  `sudo -u postgres psql -d vk_auto_bot`. Сервисы systemd: vk-bot, admin-web.
  Деплой файлов — SFTP в /opt + `chown vkbot:vkbot` + `systemctl restart`. Helper
  `_ssh_run.py` временный — удалить по завершении Фазы 4.
- **ФОРМА `datetime-local` = наивное локальное время (МСК).** Хранить как UTC-aware
  (`timeutil.parse_local_datetime`), показывать обратно фильтром `localdt`. Иначе
  `is_event_open` (сравнивает с UTC now) глушит бота на разницу часовых поясов.

- **8.4 резолвер публичного имени (`resolve_public_name`):** публичная таблица/Google Sheet
  теперь показывают VK first_name (`vk_first_name`), а не полное ФИО (`provided_name`).
  Приоритет: `public_name` (админ-override) > `vk_first_name` > 1-й токен `provided_name` >
  `vk_name`. ГРАБЛИ для участников, созданных ДО миграции 0007 (у них `vk_first_name` пуст):
  до следующего взаимодействия с ботом (когда бот захватит `vk_first_name` через VK
  `users.get`) в таблице покажется 1-й токен старого ФИО. Не деструктивно, но при сравнении
  со старыми записями заказчик может заметить смену имени. Полное ФИО остаётся в карточке
  модерации (`provided_name`).
- Статичный QR один на всех → автосверку платежа с конкретным человеком через банк
  делать НЕ будем; проверка = OCR суммы/реквизитов + ручная модерация.
- Бот и админка общаются только через БД; подтверждение чека → воркер бота
  подхватывает (polling раз ~5 сек) и присваивает номера/шлёт 2-е сообщение.
- Номера уникальны в рамках мероприятия (уникальный индекс (event_id, number)),
  при исчерпании диапазона — алерт админу.
- Обвязка переносимая: пути нигде не захардкожены (хук берёт корень из payload `cwd`
  / `$env:CLAUDE_PROJECT_DIR`).
- Stop-хук блокирует завершение ответа, если файлы проекта изменены позже STATE.md —
  держать STATE.md свежим после каждого цикла.
- **Окружение Windows:** `python` резолвится в `C:\Python314\python.exe` (не 3.12),
  пакеты ставятся в user site-packages Python 3.14. Использовать `python -m pip
  install ...` (не голый `pip`), иначе возможен рассинхрон версий. Сабагентам это
  указывать.
- **PostgreSQL локально НЕ запущен** (ConnectionRefused при alembic upgrade) —
  полноценные миграции/интеграц. проверки с живой БД на этой машине не прогнать.
  Корректность моделей валидируем через `aiosqlite` (in-memory `create_all`).
- **Деплой = Caddy, не nginx.** Reverse proxy — фрагмент `caddy/vk_admin.caddy`,
  слушает **порт 8080**, подключается к существующему серверному Caddy через
  `import /etc/caddy/conf.d/*.caddy` (строку дописать в конец `/etc/caddy/Caddyfile`,
  если её нет) — чужие сайты не трогаем. Без домена TLS НЕ выпускается (HTTP на :8080);
  появится домен — заменить `:8080` на имя домена, Caddy сам поднимет HTTPS. Порт 8080
  открыть в security group cloud.ru. Деплой/обновление — руками по README (копипаст),
  автоскрипта больше нет.
- **Async ORM-каскад при `session.delete(obj)`:** relationships с `cascade="all,
  delete-orphan"` НЕ удаляются каскадно, если коллекции не загружены — в async
  ленивый load не срабатывает. Правило: перед `session.delete()` подгружать связи
  через `selectinload` (см. `services/events.py:delete_event`). На PG db-level
  `ondelete=CASCADE` подстрахует, но не полагаться только на это.
- **Тесты:** `pytest.ini` с `asyncio_mode=auto`; фикстура — SQLite in-memory
  (`Base.metadata.create_all`). Сервисы делают `flush`, commit — на вызывающем.
- **Windows-консоль искажает кириллицу в трейсбеках** — при дебаге через bash
  форсировать `PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8`, иначе текст ошибок нечитаем.
- **regex `\b` (word boundary) — zero-width**, квантификатор после него (`\b?`)
  даёт `re.error: nothing to repeat`. Грабли при денежных/граничных паттернах.
- **Tesseract-бинарь на машине НЕ установлен** (`tesseract_available()`→False),
  реальный OCR-тест skip. Парсинг (`ocr/parse.py`) от бинаря не зависит.
- **vkbottle 4.10 API:** класс загрузчика фото — `PhotoMessageUploader` (НЕ
  `PhotoToMessagesUploader`, такого нет). `.upload(file_source=path)` → attachment-
  строка для `message.answer(attachment=...)`. vkbottle ставится `python -m pip
  install vkbottle`. `bot/dialog.py` НЕ импортирует vkbottle (тесты логики без него).
- **Бот↔воркер:** оба внутри процесса `app.bot.main`; воркер — asyncio-задача рядом
  с Long Poll. Ядро воркера `process_pending` принимает колбэки send/sync — тест без
  vkbottle/Sheets/PG (мок), на SQLite.
- **bcrypt/passlib:** passlib 1.7.4 (не обновлялся с 2020) НЕсовместим с bcrypt>=4.1
  (`AttributeError __about__`, затем 72-byte ошибка). В `requirements.txt` закреплён
  `bcrypt>=4.0,<4.1`. Локально стоит bcrypt 4.0.1. На сервере не снимать верхнюю
  границу, пока не заменён passlib.
- **ДЕПЛОЙ-грабли (важно для повторных установок):**
  - **Незапиненный FastAPI/Starlette сломал админку (HTTP 500, `TypeError:
    unhashable type: 'dict'`).** На сервере по `>=` встал starlette 1.3.1 / fastapi
    0.138.1, где убрана старая сигнатура `TemplateResponse(name, context)` (теперь 1-й
    позиционный — `request`, имя шаблона = dict → краш). Локально рабочий набор —
    starlette 0.48 / fastapi 0.116.2. Починено пином в `requirements.txt`:
    `fastapi==0.116.2`, `starlette==0.48.0`, `uvicorn[standard]==0.35.0`. Либо когда-нибудь
    мигрировать ВСЕ `TemplateResponse(name, {...})` на новую сигнатуру
    `TemplateResponse(request, name, {...})`.
  - **vk-bot без токена = чистый exit 0 → с `Restart=always` бесконечный цикл
    рестартов.** Исправлено на `Restart=on-failure` (systemd/vk-bot.service): без токена
    служба штатно стоит inactive, реальный сбой перезапустит. После ввода токена в
    админке — `systemctl restart vk-bot`.
  - Рантайм в `/opt/vk_auto_bot` (vkbot), не в `/root/...` (700, недоступно службе).
  - Caddy: фрагмент в `/etc/caddy/conf.d/*.caddy`, в `Caddyfile` дописана строка
    `import /etc/caddy/conf.d/*.caddy`; перед reload — `caddy validate` (не сломать
    чужие сайты kwork/admin на :80/:443).
  - Порт 8080 на хосте открыт (ufw нет, iptables ACCEPT) — гейт только в security
    group cloud.ru (внешний, через SSH не настроить).
- **Секреты-конфиг:** настройки заказчика (VK-токен/group_id/почта Sheets) — в
  таблице `app_settings`, НЕ в `.env`. Токен шифруется Fernet (`core/crypto.py`),
  мастер-ключ `SECRETS_KEY` в `.env` (генерить `scripts/gen_secrets_key.py`) —
  одинаковый для процессов бота и админки. Смена VK-токена через админку требует
  ПЕРЕЗАПУСКА бота (`systemctl restart vk-bot`) — горячей перезагрузки нет.
- **`VK_GROUP_ID=` пустой в .env ронял ВЕСЬ pytest** на этапе collection
  (pydantic-settings не парсит "" в int). Починено `field_validator` в `config.py`
  (пусто/None → 0). Если в боевом `.env` поле пустое — теперь не падает.
- **Sheets-владение:** лист создаёт service account (он владелец), заказчику даётся
  доступ редактора через `share(owner_email, role="writer", notify=False)` — это тот
  же оригинальный файл (в Drive заказчика «Доступные мне»), НЕ копия. Истинного
  владения без OAuth не сделать; OAuth отклонён (верификация Google под scope
  `spreadsheets`).
- **Админка-тесты:** httpx `ASGITransport(app=app)` + `AsyncClient`; сессия-cookie
  переносится в рамках одного клиента; `follow_redirects=False` для проверки 303.
  `verify_credentials` читает `settings` динамически → в тестах monkeypatch
  `settings.admin_login`/`admin_password_hash`.
- **`on_event("startup")` Deprecated** в FastAPI 0.116+ — используется для кэша
  настроек (`admin_title`, `winners_tab_enabled`) в `main.py`. Работает, но при
  обновлении FastAPI мигрировать на `lifespan` context manager. Пока пин
  `fastapi==0.116.2` держит совместимость.

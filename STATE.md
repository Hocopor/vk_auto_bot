# STATE.md — состояние работы (обновляется каждой сессией)

## Текущая точка

- **2026-06-26. ФАЗА 4 — фидбек заказчика после демо. В РАБОТЕ.** Доступ к боевому
  серверу получен (root@185.228.72.118, проект в `/opt/vk_auto_bot`, копия в
  `/root/vk_auto_bot`). Коннект — paramiko из `scripts/_ssh_run.py` (пароль в env
  `SSH_PASS`, в код НЕ писать; helper временный, удалить после фазы).
  - **Корневой баг «бот не реагирует на кодовое слово» НАЙДЕН и захотфикшен.** Бот
    НА САМОМ ДЕЛЕ реагировал: находил событие, но падал на отправке QR —
    `VK API Error 15: Access denied ... current scopes` на
    `photos.getMessagesUploadServer`. **У VK-токена сообщества нет права
    «Фотографии».** Загрузка QR не была обёрнута в try/except → падал ВЕСЬ
    обработчик `_handle_keyword`, участник не получал даже текст инструкции.
    **Хотфикс залит и в бою:** `handlers.py:_handle_keyword` теперь шлёт текст
    всегда, QR — best-effort в try/except (`attachment=None` при ошибке). Бот
    перезапущен, active. Чтобы прикреплялся QR — заказчику пересоздать ключ
    сообщества с правом «Фотографии».
  - Данные на сервере: 1 событие (active, keyword задан, starts_at/ends_at = NULL —
    таймзона на ЭТОТ инцидент не влияла), alembic на `0002` (head), оба сервиса active.
  - **Латентный баг таймзоны (чиню в Фазе 4):** `datetime-local` в форме даёт наивное
    локальное время, а `is_event_open` сравнивает с `datetime.now(utc)` → если задать
    «Начало = сейчас» по МСК, бот молчал бы 3 часа. Фикс: трактовать ввод как
    Europe/Moscow, хранить UTC-aware, показывать обратно в МСК.
  - **Backend-агент ЗАВЕРШЁН (123 passed, 1 skip):** timeutil.py (Europe/Moscow,
    parse_local_datetime/to_local/format_local_input), config `display_timezone`,
    events.py на parse_local_datetime; общий `app/admin/templating.py` (единый
    `templates`, фильтр `localdt`, глобал `VAR_LABELS`) — все route-модули переведены
    на него; миграция `alembic/versions/0003_message_toggles.py`
    (down_revision=`0002_app_settings`) + 5 bool-колонок в Event; гейтинг в
    handlers/worker; в worker ctx добавлен `event_name`. Миграции лежат в
    `alembic/versions/` (НЕ `app/alembic/versions/`).
  - **Frontend-агент ЕЩЁ РАБОТАЕТ** (фоном правит шаблоны `app/admin/templates/*` и
    `static/*` — их mtime новее STATE, это норма). Дождаться его, затем: полный
    pytest → деплой кода+шаблонов на сервер → `alembic upgrade head` (0003) →
    рестарт сервисов → smoke + боевой прогон кодового слова.
  - **План Фазы 4** (см. PLAN.md «Фаза 4»): (1) backend-агент — устойчивость QR
    (сделано хотфиксом, закрепить), таймзона, тумблеры типов сообщений
    (миграция 0003: send_instruction/send_receipt_received/send_after_payment/
    send_need_contacts/send_qr, default TRUE), гейтинг в handlers/worker, чтение
    чекбоксов в events.py, обновление create_event + тестов; (2) frontend-агент со
    скилом `design-taste-frontend` — полный редизайн всех шаблонов+CSS, дружелюбные
    «чипы вставки переменных» вместо сырых `{name}/{numbers}`, секция тумблеров,
    индикатор «Сохранение…» на submit (лечит ощущение «вечной загрузки»). Деплой +
    `alembic upgrade head` + pytest делает оркестратор после обоих агентов.
- **2026-06-26. Google Sheets ПОЛНОСТЬЮ ВЫПИЛЕН — публичная таблица теперь на своём
  сервере (HTML-страница).** Причина: сервис-аккаунт Google не может владеть файлами
  в Drive (квота=0) → `client.create()` падал то `Drive API disabled`, то `storage
  quota exceeded`. Решение по согласованию с заказчиком: «нахрен Google», список
  отдаёт сам сервер. Сделано:
  - **Публичная страница `GET /p/{event_id}`** (без авторизации) — `app/admin/routes/public.py`
    + шаблон `public_table.html` (standalone, свой CSS, **поиск по имени/номеру** на
      JS — люди находят себя в списке). Данные берутся из Postgres на лету
      (`app/core/services/public_table.py: collect_records` — только approved-номера,
      сортировка по номеру). Источник истины — БД, синхронизировать нечего.
  - **Ссылку на страницу бот шлёт участнику** после оплаты. Новая настройка
    `PUBLIC_BASE_URL` в `.env` (на сервере = `http://185.228.72.118:8080`), хелпер
    `public_table.public_table_url(event_id)`. Плейсхолдер `{sheet_url}` теперь =
    эта ссылка (в `worker.py` и `handlers.py`).
  - **Удалено:** пакет `app/sheets/` (sync.py, client.py), `tests/test_sheets.py`,
    зависимости `gspread`/`google-auth` из requirements, секция «Google Sheets» и
    кнопка «Проверить Google Sheets» в `/settings`, `KEY_SHEETS_OWNER_EMAIL`, все
    вызовы Sheets в `events.py` (create/delete листа), `moderation.py` (rebuild при
    revoke — страница живая), синк в `worker.py` (`process_pending` больше БЕЗ
    `sync_sheet`). Колонка `Event.sheet_id` оставлена в модели (всегда None, без
    миграции). В `events_list.html` колонка «Google-лист» → «Список» со ссылкой `/p/{id}`.
  - **Тесты переписаны** под отсутствие Google (worker/admin_events/admin_moderation/
    settings) + новый `tests/test_public.py`. На сервере: **115 passed**. Живой smoke
    на боевой БД: создал временное мероприятие+участника+3 номера → `/p/{id}`=200, имя/
    счётчик/поиск на странице, после удаления =404. Мусор убран, БД пустая.
  - Деплой: файлы залиты по SFTP в `/opt` и `/root`, `PUBLIC_BASE_URL` дописан в
    `/opt/.env`, сервисы перезапущены (оба active). google-libs на сервере остались
    установленными (не удаляются из venv автоматически) — безвредно, не импортируются.
  - **NB:** локальные правки НЕ закоммичены в GitHub (коммитит пользователь). На
    сервере файлы лежат впереди origin — при следующем `git pull` сделать
    `git reset --hard origin/main` ПОСЛЕ того как пользователь запушит эти изменения.
  - Старые «грабли Sheets-владения/OAuth» ниже в этом файле — ИСТОРИЯ, более неактуальны.
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

- **Разработка завершена (включая Фазу 3 — конфигурация из админки).** Остались
  задачи вне кода (на стороне заказчика/боевого окружения):
  1. Развернуть на сервере cloud.ru по README (Ubuntu): PostgreSQL, `.env`
     (DATABASE_URL, GOOGLE_SA_JSON, ADMIN_PASSWORD_HASH через
     `scripts/gen_password_hash.py`, SESSION_SECRET, **SECRETS_KEY** через
     `scripts/gen_secrets_key.py`; VK_TOKEN/VK_GROUP_ID можно НЕ заполнять — заказчик
     введёт в админке `/settings`), `alembic upgrade head` (поднимет и `0002_app_settings`),
     systemd, Caddy (фрагмент `caddy/vk_admin.caddy` → `/etc/caddy/conf.d/`, порт 8080,
     открыть в security group). Tesseract (`tesseract-ocr tesseract-ocr-rus`) для OCR.
  1a. Заказчик в админке `/settings` вводит VK-токен/group_id/почту Google и жмёт
     «Проверить VK» / «Проверить Google Sheets». После ввода токена — рестарт бота.
  2. Ручной прогон полного сценария в реальном ВК (кодовое слово → чек → модерация →
     номера → таблица → розыгрыш) — единственное, что не покрыть локально без токена.
  3. Опц.: отправить заказчику открытые вопросы `ТЗ_ИТОГ §16` (помечено в Фазе 0).
- Возможные доработки по фидбеку после демо: тонкая настройка OCR-регэкспов под
  реальные банки-чеки заказчика; UI-полировка админки.

## Нюансы (грабли, лимиты, особенности — пополняется по ходу)

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

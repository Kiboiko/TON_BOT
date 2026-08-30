# TON Site Builder — Backend (Разработчик A)

Реализация роли **Разработчик A** из `TON_Site_Builder_TZ.md`: сервер, БД,
блокчейн-интеграция, оплата, подписки, публикация, бот и админ-API.

* Развёртывание на сервере — [docs/DEPLOY.md](../docs/DEPLOY.md)
* API-контракт — [docs/API.md](../docs/API.md), схема — [docs/openapi.json](../docs/openapi.json)
* Структура `content_json` (контракт с фронтом) — [docs/content_json.md](../docs/content_json.md)

## Быстрый старт локально (без Docker)

```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate   # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Минимальный `.env` для локальной работы без внешних сервисов:

```ini
ENV=dev
DATABASE_URL=sqlite+aiosqlite:///./dev.db
QUEUE_MODE=memory
SUBDOM_MODE=fake
TON_VERIFY_MODE=mock
TON_STORAGE_MODE=local
SITES_BUILD_DIR=./.sites
TELEGRAM_BOT_TOKEN=<токен тестового бота>
ADMIN_TELEGRAM_IDS=<ваш telegram_id>
```

```bash
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload
```

Документация API поднимется на http://localhost:8000/api/docs.

Для полного окружения (Postgres + Redis + воркеры + бот) используйте
`docker compose up -d` из корня репозитория.

## Процессы

| Команда | Назначение |
|---|---|
| `uvicorn app.main:app` | HTTP API |
| `python -m app.workers.publish_worker` | публикация сайтов (очередь) |
| `python -m app.workers.scheduler` | статусы подписок, снятие с публикации |
| `python -m app.bot.main` | Telegram-бот и уведомления |
| `python -m app.seed` | начальные тарифы, назначение админов |
| `python -m app.export_openapi` | выгрузка OpenAPI для фронта |

## Структура

```
app/
  main.py                 сборка FastAPI, CORS, обработчики ошибок, health
  models.py               модели данных (раздел 3 ТЗ)
  schemas.py              Pydantic-схемы = API-контракт (раздел 4)
  seed.py                 начальные тарифы
  core/
    config.py             все настройки из .env
    db.py                 async-движок и сессии
    errors.py             единый формат ошибки
    telegram_auth.py      валидация подписи initData
  api/
    deps.py               авторизация, проверка is_admin
    user.py sites.py domains.py subscriptions.py admin.py
  services/
    subdom_client.py      A2 — изоляция внешнего доменного API
    ton.py                A3 — ton_proof и проверка транзакций on-chain
    renderer.py           A4 — content_json → статический HTML
    storage.py            A4 — заливка в TON Storage
    dns.py                A4 — транзакция привязки bag id к домену
    publishing.py         A4 — фоновая публикация
    payments.py           A5 — платежи
    subscriptions.py      A5 — сроки, лимиты, триал, планировщик
    notifications.py      A6 — уведомления
  workers/
    queue.py              очередь (Redis / память)
    publish_worker.py     воркер публикации
    scheduler.py          планировщик подписок
  bot/main.py             aiogram-бот
```

## Тесты

```bash
pytest -q            # весь набор
pytest tests/test_full_cycle.py -q   # сквозной сценарий
```

Тесты идут на SQLite с заглушками внешних сервисов, поэтому не требуют ни
Postgres, ни Redis, ни доступа в сеть. Проверка платежей при этом **включена**
(`TON_VERIFY_MODE=onchain` против мок-клиента блокчейна) — иначе тест оплаты не
проверял бы главное правило системы.

## Три принципа, на которых держится код

1. **Изоляция subdom API.** Вся работа с внешним доменным сервисом — только в
   `services/subdom_client.py`, наружу торчит интерфейс `DomainService` в наших
   типах. Смена сервиса = новая реализация этого интерфейса, остальной код не
   трогается. То же сделано для блокчейна (`TonClient`), хранилища (`SiteStorage`)
   и уведомлений (`NotificationTransport`).
2. **Оплата подтверждается только on-chain.** Фронт присылает `tx_hash`, backend
   идёт в блокчейн и ищет входящий платёж на адрес казначейства с нужной суммой и
   нашим комментарием-нонсом. Один хэш нельзя использовать дважды.
3. **Данные у нас.** Пользователи, сайты, подписки, платежи — в нашей БД. При
   недоступности subdom API или storage-daemon теряется только соответствующая
   операция, но не данные.

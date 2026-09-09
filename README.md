# TON Site Builder

Telegram Mini App для создания и публикации мини-сайтов на доменах сети TON:
конструктор, оплата через TON Connect, подписки, публикация в TON Storage, админка.

Техническое задание: [TON_Site_Builder_TZ.md](TON_Site_Builder_TZ.md).

| Роль | Статус | Где |
|---|---|---|
| Разработчик A — Backend / Blockchain | реализовано | [backend/](backend/) |
| Разработчик B — Frontend / Mini App | реализовано | [frontend/](frontend/) |

## Документация

* [docs/DEPLOY.md](docs/DEPLOY.md) — развёртывание на чистом сервере, пошагово
* [docs/QUICKSTART_SERVER.md](docs/QUICKSTART_SERVER.md) — короткий прогон на сервере за двое суток: где взять сервер, домен и `.ton`
* [docs/API.md](docs/API.md) — API-контракт, коды ошибок, отличия от ТЗ
* [docs/content_json.md](docs/content_json.md) — структура content_json всех 6 шаблонов
* [docs/openapi.json](docs/openapi.json) — OpenAPI-схема для мок-сервера фронта
* [docs/TESTING.md](docs/TESTING.md) — чеклист ручного тестирования и приёмки
* [backend/README.md](backend/README.md) — запуск backend, структура кода, тесты
* [frontend/README.md](frontend/README.md) — запуск Mini App, структура, мок-режим

## Запуск

```bash
cp .env.example .env                   # пароль БД и адреса узлов TON
cp backend/.env.example backend/.env   # настройки приложения
docker compose up -d --build           # backend, воркеры, бот, БД, nginx
curl localhost/health

cd frontend && npm ci && npm run build # Mini App → frontend/dist, его отдаёт nginx
```

Полное развёртывание на своём сервере, со всеми шагами и приёмкой —
[docs/DEPLOY.md](docs/DEPLOY.md).

Посмотреть интерфейс без backend: `cd frontend && npm install && npm run dev` —
приложение поднимется против встроенного мока API-контракта.

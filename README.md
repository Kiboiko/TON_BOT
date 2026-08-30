# TON Site Builder

Telegram Mini App для создания и публикации мини-сайтов на доменах сети TON:
конструктор, оплата через TON Connect, подписки, публикация в TON Storage, админка.

Техническое задание: [TON_Site_Builder_TZ.md](TON_Site_Builder_TZ.md).

| Роль | Статус | Где |
|---|---|---|
| Разработчик A — Backend / Blockchain | реализовано | [backend/](backend/) |
| Разработчик B — Frontend / Mini App | ожидается | `frontend/` |

## Документация

* [docs/DEPLOY.md](docs/DEPLOY.md) — развёртывание на чистом сервере, пошагово
* [docs/API.md](docs/API.md) — API-контракт, коды ошибок, отличия от ТЗ
* [docs/content_json.md](docs/content_json.md) — структура content_json всех 6 шаблонов
* [docs/openapi.json](docs/openapi.json) — OpenAPI-схема для мок-сервера фронта
* [backend/README.md](backend/README.md) — запуск, структура кода, тесты

## Запуск

```bash
cp backend/.env.example backend/.env   # заполнить значения
docker compose up -d --build
curl localhost/health
```

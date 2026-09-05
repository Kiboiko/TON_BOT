# API-контракт (раздел 4 ТЗ) — что реализовано

Машиночитаемая схема: `GET /api/openapi.json`, интерактивная — `/api/docs`.
Экспорт схемы в файл (для мок-сервера Разработчика B):

```bash
cd backend && python -m app.export_openapi ../docs/openapi.json
```

## Авторизация

Все запросы к `/api/*` (кроме `/api/health`) требуют заголовок:

```
X-Telegram-Init-Data: <initData из Telegram Web App>
```

Backend проверяет HMAC-подпись initData по bot token и её возраст. Для
`/api/admin/*` дополнительно проверяется `is_admin`.

## Формат ошибки — единый для всех эндпоинтов

```json
{ "error": { "code": "STRING_CODE", "message": "human readable", "details": {} } }
```

`details` необязателен. Коды, на которые фронту стоит реагировать отдельно:

| HTTP | code | Когда |
|---|---|---|
| 401 | `INIT_DATA_MISSING` / `INIT_DATA_INVALID` / `INIT_DATA_EXPIRED` | проблема с initData |
| 401 | `WALLET_NOT_CONNECTED` | операция требует подключённого кошелька |
| 401 | `TONPROOF_INVALID` / `TONPROOF_EXPIRED` | не подтверждено владение кошельком |
| 403 | `ADMIN_REQUIRED` | не админ |
| 403 | `LIMIT_EXCEEDED` | исчерпан лимит сайтов по тарифу (в `details`: `limit`, `used`) |
| 402 | `SUBSCRIPTION_REQUIRED` | публикация без активной подписки |
| 402 | `CUSTOM_CODE_NOT_PAID` | загрузка кода до оплаты премиум-блока |
| 400 | `PAYMENT_NOT_CONFIRMED` | транзакция не найдена в блокчейне или сумма меньше цены |
| 409 | `TX_ALREADY_USED` | этим хэшем уже оплачена другая покупка |
| 409 | `DOMAIN_TAKEN` | домен занят другим владельцем |
| 404 | `SITE_NOT_FOUND` / `TARIFF_NOT_FOUND` / `USER_NOT_FOUND` | объект не найден или чужой |
| 400 | `CONTENT_TOO_LARGE` / `CUSTOM_CODE_TOO_LARGE` | превышен лимит размера |
| 502 | `SUBDOM_ERROR` | недоступен доменный сервис |
| 502 | `STORAGE_ERROR` | недоступен TON Storage |
| 502 | `TON_API_ERROR` | недоступен TON API |

## Эндпоинты

### Пользователь и кошелёк

| Метод | Путь | Ответ |
|---|---|---|
| POST | `/api/user/auth` | `{ user, is_admin }` |
| GET | `/api/user/ton-proof-payload` | `{ payload, expires_at }` — **дополнение к ТЗ**, см. ниже |
| POST | `/api/user/connect-wallet` | `{ success, wallet_address }` |
| PATCH | `/api/user/settings` | `{ success }` |
| GET | `/api/user/me` | `{ user }` |

**Про `ton-proof-payload`.** В ТЗ его нет, но без серверного одноразового nonce
подпись кошелька можно переиспользовать. Порядок такой: фронт запрашивает
payload → передаёт его в TON Connect как `tonProof` → присылает результат в
`/api/user/connect-wallet`. Payload одноразовый и живёт 10 минут.

### Сайты

| Метод | Путь | Ответ |
|---|---|---|
| GET | `/api/sites` | `[ { id, type, title, domain, status, ... } ]` |
| POST | `/api/sites` | `{ site }` (201) |
| GET | `/api/sites/{id}` | `{ site }` |
| PATCH | `/api/sites/{id}` | `{ site }` |
| DELETE | `/api/sites/{id}` | `{ success }` |
| POST | `/api/sites/{id}/preview` | `{ preview_html }` |
| POST | `/api/sites/{id}/publish` | `{ status: "publishing", job_id }` |
| GET | `/api/sites/{id}/publish-status` | `{ status, storage_bag_id?, published_at?, error? }` |
| POST | `/api/sites/{id}/dns-bind` | `{ transaction }` — **дополнение**, привязка bag id к домену |

Публикация асинхронная: после `publish` опрашивайте `publish-status`, пока
статус не станет `published` или `publish_error` (интервал ~2–3 с).

### Домены (субдомены в зоне платформы)

Модель subdom: платформа владеет одним доменом `.ton` и один раз разворачивает
на нём зону субдоменов; пользователи получают адреса `имя.домен.ton` внутри неё.
Разворот зоны — операция администратора, см. раздел админки.

| Метод | Путь | Ответ |
|---|---|---|
| GET | `/api/domains/check?name=` | `{ available, status, domain, zone, item_address?, owner? }` |
| POST | `/api/domains/claim` | `{ transaction, domain }` |
| POST | `/api/domains/confirm` | `{ status: "publishing" \| "pending", domain }` |

Занятость имени проверяется резолвом в блокчейне — у subdom такого эндпоинта нет.
`confirm` возвращает `pending`, если субдомен ещё не виден в сети: это не ошибка,
повторите запрос через несколько секунд.

### Загрузка изображений

| Метод | Путь | Ответ |
|---|---|---|
| POST | `/api/uploads` (multipart, поле `file`) | `{ url, size, mime }` |

Принимаются PNG, JPEG, GIF и WEBP до 5 МБ. Тип определяется по сигнатуре файла,
а не по заголовку; SVG не принимается — внутри него исполняется скрипт.
Загруженные файлы отдаются по `/u/{имя}` без авторизации.

### Тарифы и подписки

| Метод | Путь | Ответ |
|---|---|---|
| GET | `/api/tariffs` | `[ { id, name, sites_limit, duration, price_ton, kind } ]` |
| POST | `/api/subscriptions/purchase` | `{ transaction, payment_id }` |
| POST | `/api/subscriptions/confirm` | `{ subscription }` |
| GET | `/api/subscriptions` | `[ { id, tariff, expires_at, status, ... } ]` |

`price_ton` — строка без хвостовых нулей (`"9.5"`), чтобы не терять точность
в JS. `transaction` передаётся в TON Connect как есть.

### Проект «Свой код»

Отдельный тип сайта (`type: "custom_code"`), а не блок внутри другого проекта.
Создание такого сайта и загрузка кода требуют активной подписки — пробного
периода недостаточно.

| Метод | Путь | Ответ |
|---|---|---|
| POST | `/api/sites/{id}/custom-code` | `{ success }` |

Ошибки: `402 SUBSCRIPTION_REQUIRED` — нет подписки; `400 NOT_A_CUSTOM_CODE_SITE` —
сайт другого типа; `400 CUSTOM_CODE_TOO_LARGE` — превышен лимит размера.

### Админка

| Метод | Путь | Ответ |
|---|---|---|
| GET | `/api/admin/users?search=&page=&per_page=` | `{ users, total, page, per_page }` |
| GET | `/api/admin/users/{id}` | `{ user, sites, subscriptions, payments }` |
| POST | `/api/admin/users/{id}/grant-access` | `{ subscription }` |
| POST | `/api/admin/users/{id}/revoke-access` | `{ success }` |
| GET | `/api/admin/tariffs` | `[ tariff ]` |
| POST | `/api/admin/tariffs` | `{ tariff }` (201) |
| PATCH | `/api/admin/tariffs/{id}` | `{ tariff }` |
| DELETE | `/api/admin/tariffs/{id}` | `{ success }` |
| GET | `/api/admin/domains` | `[ { domain, status, site_id, site_title, user_id, telegram_id } ]` |
| GET | `/api/admin/zone` | `{ domain, dns_item_address, collection_address, mode, configured, deployable }` |
| PATCH | `/api/admin/zone` | `{ ...zone }` — настройка домена платформы и адреса коллекции |
| POST | `/api/admin/zone/deploy` | `{ transaction, domain }` — разовый разворот зоны, подписывает владелец домена |
| GET | `/api/admin/stats` | `{ total_users, total_sites, published_sites, active_subscriptions, revenue, revenue_last_30d, payments_confirmed }` |
| GET | `/api/admin/actions` | журнал действий админов (аудит) |

`grant-access` принимает либо `tariff_id` (+ опционально `duration`), либо пару
`sites_limit` + `duration` — во втором случае создаётся служебный тариф вне витрины.

Тариф с историей подписок при `DELETE` не удаляется физически, а деактивируется:
иначе порвалась бы связь в аудите и в карточках пользователей.

## Отличия от текста ТЗ

Контракт реализован целиком; добавлены эндпоинты, без которых схема была бы
небезопасной или незавершённой:

1. `GET /api/user/ton-proof-payload` — одноразовый nonce для ton_proof.
3. `POST /api/sites/{id}/dns-bind` — транзакция привязки опубликованного контента
   к домену (её подписывает владелец домена, backend лишь собирает тело).
4. `POST /api/uploads` и `GET /u/{имя}` — загрузка изображений из ТЗ (пункт B2)
   не имела эндпоинта в разделе 4.
5. `GET /s/{site_id}` — опубликованный сайт по обычной ссылке: домен `.ton`
   открывается только TON-браузером, а увидеть результат нужно сразу.
6. `/api/admin/zone*` — настройка и разворот зоны субдоменов.

**Изменён по сравнению с ТЗ доменный флоу.** В разделе 4 предполагалось, что
пользователь разворачивает зону на своём домене (`POST /api/domains/deploy-zone`).
Реальный subdom API устроен иначе: зона разворачивается один раз на домене
платформы, а пользователи минтят субдомены внутри неё. Поэтому `deploy-zone`
переехал в админку, а пользовательский путь стал `check` → `claim` → `confirm`.

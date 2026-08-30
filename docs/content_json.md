# Структура `content_json` — контракт между backend (A) и frontend (B)

Раздел 7 ТЗ, «День 1»: точная структура JSON каждого шаблона. Это описание —
источник истины; backend рендерит ровно то, что здесь описано
(`backend/app/services/renderer.py`), остальное молча игнорирует.

## Общая форма

```jsonc
{
  "version": 1,
  "meta":  { "title": "Ирина Ветрова", "description": "Дизайнер интерфейсов", "lang": "ru" },
  "theme": { "preset": "aurora", "accent": "#0098ea", "background": "" },
  "blocks": [
    { "id": "b1", "type": "hero", "props": { "title": "Ирина", "subtitle": "Дизайнер" } },
    { "id": "b2", "type": "links", "props": { "items": [ ... ] } }
  ]
}
```

Правила:

* Порядок блоков в массиве = порядок на странице. Перетаскивание в конструкторе
  меняет только порядок элементов массива.
* `id` — стабильный идентификатор блока на стороне фронта (для React key и undo).
  Backend его не интерпретирует.
* `"hidden": true` у блока — блок сохраняется, но не рендерится.
* Неизвестный `type` пропускается: старая сборка backend-а не сломается о новый
  блок фронта.
* Плоский вариант блока (`{"type":"hero","title":"..."}` без `props`) тоже
  поддерживается — всё, кроме `id`/`type`/`hidden`, считается props.
* Лимит размера: `MAX_CONTENT_JSON_BYTES` (по умолчанию 500 КБ), иначе
  `400 CONTENT_TOO_LARGE`.

### theme

| Поле | Значения | Комментарий |
|---|---|---|
| `preset` | `light`, `dark`, `aurora`, `sunrise`, `mint`, `ton` | набор фонов «на выбор с предпросмотром» из B2 |
| `accent` | `#rrggbb`, `rgb()/rgba()` | цвет кнопок и ссылок; некорректное значение → `#0098ea` |
| `background` | CSS-цвет / `linear-gradient(...)` / `url(https://...)` | перекрывает фон пресета; `javascript:`, `@import`, разметка — отбрасываются |

### Безопасность (backend, не полагайтесь на фронт)

* Весь текст экранируется при рендере — HTML в текстовых полях станет видимым текстом.
* Ссылки допускаются только со схемами `http`, `https`, `mailto`, `tel`, `tg`, `ton`;
  `javascript:` и `data:` вырезаются. Строка без схемы (`t.me/durov`) → `https://`.
* Блок «Свой код» рендерится в `<iframe sandbox="allow-scripts">` — у него нет
  доступа к странице-хосту.

---

## Словарь блоков

| `type` | props | Где используется |
|---|---|---|
| `hero` | `title`, `subtitle`, `image` | все шаблоны |
| `text` (алиас `about`) | `title`, `text` | визитка, портфолио, TON-проект |
| `links` | `items[]`: `title`, `url`, `subtitle?`, `icon?` | ссылки, TON-проект |
| `buttons` | `items[]`: `title`, `url`, `style: "primary"\|"secondary"` | визитка |
| `socials` | `items[]`: `network`, `url`, `icon?` | визитка, ссылки |
| `contacts` | `items[]`: `label`, `value`, `url?` | все |
| `features` (алиас `advantages`) | `title?`, `items[]`: `icon?`, `title`, `text` | лендинг |
| `product` | `title`, `description`, `price`, `image`, `button_title`, `button_url` | лендинг |
| `cta` | `title`, `text`, `button_title`, `url` | лендинг, события |
| `gallery` (алиас `works`) | `title?`, `items[]`: `image`, `title?` | портфолио |
| `event_info` | `title`, `poster`, `date`, `time`, `place`, `address` | события |
| `schedule` | `title?`, `items[]`: `time`, `title`, `text?` | события |
| `ton_info` | `title?`, `ticker`, `contract_address`, `network`, `supply` | TON-проект |
| `jetton` | `title?`, `jetton_address`, `dex_url`, `explorer_url` | TON-проект |
| `image` | `image`, `alt?` | все |
| `divider` | — | все |

Изображения передаются как URL (`https://…` или `data:`-URL не допускается —
загрузку файлов фронт делает через своё хранилище и кладёт сюда ссылку).

---

## Наборы блоков по типам шаблонов

Backend создаёт этот скелет, если `POST /api/sites` пришёл без `content_json`
(`default_content_for`):

| Тип сайта | Блоки по умолчанию |
|---|---|
| `visitka` | hero, text, buttons, socials, contacts |
| `links` | hero, links, socials |
| `landing` | hero, features, product, cta, contacts |
| `portfolio` | hero, text, gallery, contacts |
| `events` | hero, event_info, schedule, cta, contacts |
| `ton_project` | hero, text, ton_info, jetton, links, socials |

Набор — стартовая точка, а не ограничение: пользователь может добавить любой
блок из словаря в любой шаблон, число элементов в `items[]` не ограничено
(кроме общего лимита размера).

---

## Примеры

### Визитка

```json
{
  "version": 1,
  "meta": { "title": "Ирина Ветрова", "description": "Дизайнер интерфейсов", "lang": "ru" },
  "theme": { "preset": "sunrise", "accent": "#e0559a" },
  "blocks": [
    { "id": "b1", "type": "hero", "props": {
        "title": "Ирина Ветрова", "subtitle": "Дизайнер интерфейсов\n8 лет в продуктовом дизайне",
        "image": "https://cdn.example.com/ira.jpg" } },
    { "id": "b2", "type": "buttons", "props": { "items": [
        { "title": "Написать в Telegram", "url": "https://t.me/ira", "style": "primary" },
        { "title": "Посмотреть портфолио", "url": "https://ira.design", "style": "secondary" } ] } },
    { "id": "b3", "type": "socials", "props": { "items": [
        { "network": "Telegram", "icon": "✈️", "url": "https://t.me/ira" },
        { "network": "Behance", "icon": "🎨", "url": "https://behance.net/ira" } ] } },
    { "id": "b4", "type": "contacts", "props": { "title": "Контакты", "items": [
        { "label": "Почта", "value": "ira@example.com", "url": "mailto:ira@example.com" },
        { "label": "Телефон", "value": "+7 900 000-00-00", "url": "tel:+79000000000" } ] } }
  ]
}
```

### Страница ссылок

```json
{
  "version": 1,
  "meta": { "title": "TON Community", "lang": "ru" },
  "theme": { "preset": "ton", "accent": "#0098ea" },
  "blocks": [
    { "id": "b1", "type": "hero", "props": { "title": "TON Community", "image": "https://cdn.example.com/cover.png" } },
    { "id": "b2", "type": "links", "props": { "items": [
        { "title": "Наш канал", "subtitle": "Новости каждый день", "icon": "📣", "url": "https://t.me/toncommunity" },
        { "title": "Чат",       "icon": "💬", "url": "https://t.me/tonchat" },
        { "title": "Сайт",      "icon": "🌐", "url": "https://ton.org" } ] } }
  ]
}
```

### TON-проект

```json
{
  "version": 1,
  "meta": { "title": "MyJetton", "lang": "en" },
  "theme": { "preset": "ton", "accent": "#0098ea" },
  "blocks": [
    { "id": "b1", "type": "hero", "props": { "title": "MyJetton", "subtitle": "Community-driven jetton on TON" } },
    { "id": "b2", "type": "ton_info", "props": {
        "title": "О проекте", "ticker": "MJT",
        "contract_address": "EQD...", "network": "mainnet", "supply": "100 000 000" } },
    { "id": "b3", "type": "jetton", "props": {
        "jetton_address": "EQD...", "dex_url": "https://dedust.io/swap/MJT",
        "explorer_url": "https://tonviewer.com/EQD..." } }
  ]
}
```

Остальные три шаблона (лендинг, портфолио, события) собираются из тех же блоков
по таблице выше.

---

## Премиум-блок «Свой код»

Хранится **отдельно** от `content_json` — в поле `custom_code` сайта:

```json
{ "html": "<div class='promo'>…</div>", "css": ".promo{…}", "js": "console.log(1)" }
```

* Загружается через `POST /api/sites/{id}/custom-code` и только после
  подтверждённой оплаты, иначе `402 CUSTOM_CODE_NOT_PAID`.
* Суммарный лимит — `MAX_CUSTOM_CODE_BYTES` (256 КБ), иначе `400 CUSTOM_CODE_TOO_LARGE`.
* В опубликованном сайте и в превью рендерится в изолированном iframe и всегда
  идёт последним блоком страницы.

# TON Site Builder — Mini App (Разработчик B)

Реализация роли **Разработчик B** из `TON_Site_Builder_TZ.md`: Telegram Mini App —
конструктор сайтов, шесть шаблонов, предпросмотр, оплата через TON Connect,
подписки и админ-панель.

React 18 + TypeScript + Vite, состояние — Zustand, локализация — i18next (RU/EN),
стили — собственные CSS-токены со светлой и тёмной темой.

## Запуск

```bash
cd frontend
npm install
cp .env.example .env
npm run dev          # http://localhost:5173
```

Без backend приложение само поднимется против **встроенного мока контракта**
(`src/api/mock.ts`) — можно смотреть весь UI, создавать сайты, «оплачивать»
подписки и публиковать. Принудительно: `VITE_USE_MOCK=1`.

С реальным backend: поднимите его на `localhost:8000` — dev-сервер проксирует
`/api` туда (`VITE_API_PROXY`). Учтите, что вне Telegram настоящий backend
отклонит запросы: `initData` пустой, подпись проверить нечем.

```bash
npm run build        # сборка в dist/ (её отдаёт nginx)
npm run typecheck    # строгая проверка типов
npm test             # vitest
```

## Структура

```
src/
  api/
    types.ts        типы контракта (раздел 4 ТЗ)
    client.ts       транспорт: X-Telegram-Init-Data, единый разбор ошибок
    endpoints.ts    обёртки над эндпоинтами backend
    mock.ts         мок-сервер того же контракта
  telegram/webapp.ts   Telegram Web App SDK: initData, тема, кнопки, haptics
  store/
    app.ts          пользователь, тема, язык, тосты
    editor.ts       конструктор: блоки, автосохранение, undo/redo
  i18n/             ru.ts / en.ts
  templates/catalog.ts  словарь блоков и шесть шаблонов
  components/ui.tsx     UI-кит
  features/
    sites/          список сайтов, создание по шаблону
    editor/         конструктор блоков, оформление, «Свой код»
    preview/        рендер content_json и экран предпросмотра
    publish/        домен, деплой зоны, публикация с поллингом
    subscriptions/  витрина тарифов, мои подписки
    payments/       общий флоу оплаты TON Connect
    admin/          статистика, пользователи, тарифы, домены
    settings/       кошелёк (ton_proof), язык, тема
  styles/index.css  дизайн-система, светлая и тёмная темы
```

## Как устроены ключевые вещи

**Оплата.** `useTonPayment` — один сценарий для подписки, премиум-блока и домена:
backend отдаёт транзакцию → кошелёк подписывает → отправляем результат обратно →
backend проверяет платёж в блокчейне. Если платёж ещё не виден в сети
(`PAYMENT_NOT_CONFIRMED`), подтверждение повторяется автоматически.

**Кошелёк.** Перед подключением берём одноразовый payload у backend и передаём
его в TON Connect как `tonProof`; после подключения доказательство уходит на
`/api/user/connect-wallet`, и только тогда адрес считается подтверждённым.

**Предпросмотр.** `features/preview/render.ts` повторяет backend-рендер, поэтому
превью в конструкторе обновляется мгновенно, без запроса на каждый символ.
Переключатель «Рендер сервера» показывает именно тот HTML, что уйдёт в TON Storage.

**Безопасность.** Клиентский рендер экранирует пользовательский текст, отбрасывает
`javascript:`/`data:`-ссылки и опасные CSS-фоны, а премиум-блок «Свой код»
показывается только внутри `<iframe sandbox="allow-scripts">` — как и на backend.

## Соглашения с Разработчиком A

* Структура `content_json` — `docs/content_json.md`, словарь блоков в
  `src/templates/catalog.ts` совпадает с ним один в один.
* Пути и коды ошибок — `docs/API.md`; типы соответствуют `docs/openapi.json`.
* Все 34 вызова фронта проверены на совпадение с реальной схемой backend.

# Развёртывание TON Site Builder на чистом сервере

Пошаговая инструкция: от голой Ubuntu до работающего Mini App. Все команды —
от пользователя с sudo. Ориентировочное время: 30–40 минут.

Требования к серверу: Ubuntu 22.04+, 2 vCPU, 4 ГБ RAM, 40 ГБ диска, публичный IP
и домен с A-записью на него (Telegram пускает Mini App только по https).

---

## Шаг 1. Установка Docker

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER && newgrp docker
```

Проверка: `docker --version && docker compose version`.

## Шаг 2. Клонирование проекта

```bash
git clone <URL_РЕПОЗИТОРИЯ> /opt/ton-site-builder
cd /opt/ton-site-builder
```

## Шаг 3. Создание бота в Telegram

1. В [@BotFather](https://t.me/BotFather): `/newbot` → получите **TELEGRAM_BOT_TOKEN**.
2. `/newapp` → привяжите Mini App к боту, URL: `https://ВАШ_ДОМЕН`.
3. Узнайте свой `telegram_id` (например, через @userinfobot) — он пойдёт
   в **ADMIN_TELEGRAM_IDS**, чтобы у вас открылась админка.

## Шаг 4. Кошелёк проекта и ключ TON API

1. Создайте кошелёк (Tonkeeper), скопируйте адрес → **TREASURY_ADDRESS**.
   На бою рекомендуется мультисиг: приватный ключ backend-у не нужен, он только
   проверяет входящие платежи.
2. Получите ключ у [@tonapibot](https://t.me/tonapibot) → **TON_API_KEY**.
   Без ключа toncenter жёстко ограничивает частоту запросов.

## Шаг 5. Заполнение .env

```bash
cp backend/.env.example backend/.env
nano backend/.env
```

Минимум для боевого запуска:

```ini
ENV=prod
DEBUG=false
CORS_ORIGINS=https://ВАШ_ДОМЕН
DATABASE_URL=postgresql+asyncpg://ton:СИЛЬНЫЙ_ПАРОЛЬ@postgres:5432/ton_builder
TELEGRAM_BOT_TOKEN=...
MINI_APP_URL=https://ВАШ_ДОМЕН
ALLOW_INSECURE_AUTH=false
ADMIN_TELEGRAM_IDS=123456789
TON_NETWORK=mainnet
TON_API_BASE=https://toncenter.com/api/v2
TON_API_KEY=...
TREASURY_ADDRESS=EQ...
TON_VERIFY_MODE=onchain
TONCONNECT_DOMAIN=ВАШ_ДОМЕН
SUBDOM_MODE=http
SUBDOM_API_KEY=...
TON_STORAGE_MODE=daemon
```

Тот же пароль БД пропишите в корневой `.env` для docker-compose:

```bash
printf 'POSTGRES_USER=ton\nPOSTGRES_PASSWORD=СИЛЬНЫЙ_ПАРОЛЬ\nPOSTGRES_DB=ton_builder\n' > .env
```

При `ENV=prod` backend на старте сам проверит конфиг и откажется подниматься,
если оставлены dev-значения (`ALLOW_INSECURE_AUTH=true`, `TON_VERIFY_MODE=mock`,
пустые токен или адрес казначейства).

## Шаг 6. Сертификат TLS

```bash
sudo apt install -y certbot
sudo certbot certonly --standalone -d ВАШ_ДОМЕН
mkdir -p nginx/certs
sudo cp /etc/letsencrypt/live/ВАШ_ДОМЕН/fullchain.pem nginx/certs/
sudo cp /etc/letsencrypt/live/ВАШ_ДОМЕН/privkey.pem  nginx/certs/
sudo chown $USER nginx/certs/*
```

Продление (раз в 60 дней) — в cron:
`0 3 1 */2 * certbot renew --quiet && docker compose restart nginx`.

## Шаг 7. TON Storage daemon

Официального публичного образа может не быть — тогда соберите сам демон:

```bash
git clone --recurse-submodules https://github.com/ton-blockchain/ton.git /opt/ton
cd /opt/ton && mkdir build && cd build
cmake -DCMAKE_BUILD_TYPE=Release .. && make -j$(nproc) storage-daemon
curl -o /opt/ton-site-builder/storage/global.config.json \
  https://ton.org/global-config.json    # для testnet: global.config.json из testnet
```

Затем либо соберите образ и укажите его в `TON_STORAGE_IMAGE`, либо запустите
демон на хосте и укажите его адрес в `TON_STORAGE_API`. Каталог `SITES_BUILD_DIR`
должен быть виден и backend-у, и демону — в compose это общий том `sites_data`.

Пока демон не готов, оставьте `TON_STORAGE_MODE=local`: система работает целиком,
кроме реальной раздачи контента из сети TON.

## Шаг 8. Запуск

```bash
cd /opt/ton-site-builder
docker compose up -d --build                    # без storage-daemon
docker compose --profile storage up -d --build  # вместе с storage-daemon
```

Поднимутся: postgres, redis, migrate (миграции + тарифы), backend, worker,
scheduler, bot, nginx.

Проверка:

```bash
docker compose ps
curl -fsS https://ВАШ_ДОМЕН/health
docker compose logs -f backend
```

## Шаг 9. Фронтенд Mini App

```bash
sudo apt install -y nodejs npm      # либо nvm с Node 20+
cd /opt/ton-site-builder/frontend
cp .env.example .env                # VITE_API_BASE оставьте пустым: тот же origin
nano .env                           # VITE_TONCONNECT_MANIFEST=/tonconnect-manifest.json
npm ci
npm run build                       # результат в frontend/dist
cd .. && docker compose restart nginx
```

nginx отдаёт `frontend/dist` с корня домена, а `/api/*` проксирует в backend.

Отредактируйте `frontend/public/tonconnect-manifest.json` перед сборкой: поля
`url` и `iconUrl` должны указывать на ваш боевой домен, иначе кошельки откажутся
подключаться.

## Шаг 10. Приёмка

1. Откройте бота → кнопка «Открыть конструктор» → Mini App запускается.
2. Ваш `telegram_id` в `ADMIN_TELEGRAM_IDS` → в приложении доступна админка.
3. В админке проверьте тарифы (созданы сидом), при необходимости поправьте цены.
4. Создайте сайт → «Опубликовать»: первый сайт публикуется бесплатно на 7 дней,
   в Telegram приходит уведомление о публикации.
5. Купите подписку с тестового кошелька: подписка активируется только после
   того, как платёж найден в блокчейне.

---

## Эксплуатация

```bash
docker compose logs -f backend worker scheduler bot   # логи
docker compose exec backend alembic upgrade head      # миграции вручную
docker compose exec backend python -m app.seed        # досоздать тарифы
docker compose restart backend                        # перезапуск API
```

Бэкап БД:

```bash
docker compose exec -T postgres pg_dump -U ton ton_builder | gzip > backup-$(date +%F).sql.gz
```

Восстановление:

```bash
gunzip -c backup-2026-01-01.sql.gz | docker compose exec -T postgres psql -U ton ton_builder
```

Обновление версии:

```bash
git pull && docker compose up -d --build && docker compose logs -f backend
```

## Диагностика

| Симптом | Причина и решение |
|---|---|
| `401 INIT_DATA_INVALID` | `TELEGRAM_BOT_TOKEN` не от того бота, из которого открыт Mini App |
| `401 INIT_DATA_EXPIRED` | Расходятся часы сервера: `timedatectl set-ntp true` |
| `401 TONPROOF_INVALID` | `TONCONNECT_DOMAIN` не совпадает с доменом, где открыт Mini App |
| `400 PAYMENT_NOT_CONFIRMED` | Транзакция ещё не в блокчейне, либо сумма/адрес не совпали. Проверьте `TREASURY_ADDRESS` и `TON_API_KEY` |
| `502 SUBDOM_ERROR` | Недоступен subdom API. Данные не теряются — недоступен только выпуск новых доменов |
| `502 STORAGE_ERROR` | Не отвечает storage-daemon: `docker compose logs storage-daemon` |
| Сайт «publishing» и не двигается | Не запущен воркер: `docker compose ps worker`, `docker compose logs worker` |
| Не приходят уведомления | Пользователь не нажал /start у бота — Telegram запрещает писать первым |

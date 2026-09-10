# Запуск на сервере за два дня — минимальными деньгами

Инструкция для короткого боевого прогона: постоянный адрес вместо туннеля,
настоящий https, работающий Mini App и, если нужно, домен `.ton` для зоны
субдоменов. Ориентир по деньгам — **100–150 ₽ за двое суток** плюс отдельно
домен `.ton`, если решите его брать.

Полная версия развёртывания — [DEPLOY.md](DEPLOY.md), здесь только короткий путь.

---

## 1. Сервер — от 30 ₽ в сутки

Нужен VPS с почасовой или посуточной тарификацией: платите за двое суток, а не
за месяц. Все три провайдера принимают российские карты и не требуют документов.

| Провайдер | Тарификация | Ориентир для 2 vCPU / 4 ГБ | Заметка |
|---|---|---|---|
| [Timeweb Cloud](https://timeweb.cloud/services/cloud-servers) | почасовая | ~70 ₽/сутки | конструктор: 10 ₽/сутки за ядро, 8 ₽ за ГБ RAM, 0.55 ₽ за ГБ диска |
| [VDSina](https://vdsina.ru) | посуточная | ~25–40 ₽/сутки | дешевле всех, тарифы от 150 ₽/мес |
| [Aeza](https://aeza.net) | почасовая | ~€0.2/сутки | оплата в евро и криптой |

**Что заказывать:** 2 vCPU, 4 ГБ RAM, 40 ГБ NVMe, **Ubuntu 24.04**, локация
любая. Меньше 2 ГБ RAM не берите: в стеке восемь контейнеров, включая Postgres
и storage-daemon.

**Порядок:**

1. Зарегистрируйтесь, пополните баланс на 200–300 ₽.
2. Создайте сервер: Ubuntu 24.04, тариф выше.
3. Добавьте свой SSH-ключ (или запомните root-пароль из письма).
4. Запишите **IP-адрес** — он понадобится на следующем шаге.

Выключенный сервер у большинства провайдеров всё равно тарифицируется за диск
и IP — после теста сервер **удаляйте**, а не останавливайте.

## 2. Домен — бесплатно

Покупать домен на два дня незачем: они продаются минимум на год. Для https
достаточно бесплатного поддомена, сертификат Let's Encrypt на нём выпускается
как на обычный домен, и Telegram такой Mini App принимает.

**DuckDNS** (проверено, работает):

1. Откройте [duckdns.org](https://www.duckdns.org), войдите через GitHub, Google
   или Telegram-независимый аккаунт — регистрация не нужна.
2. В поле `sub domain` впишите имя, например `mysites`, нажмите **add domain**.
3. В строке появившегося домена впишите **IP вашего сервера** и нажмите **update ip**.
4. Ваш адрес: `mysites.duckdns.org` — дальше в командах он обозначен как `ВАШ_ДОМЕН`.

Проверьте, что имя резолвится (с любого компьютера):

```bash
ping ВАШ_ДОМЕН
```

Если нужен «настоящий» домен — дешевле всего `.ru` на [reg.ru](https://reg.ru)
или [beget.com](https://beget.com), около 200 ₽ за год. Для двухдневного теста
это лишняя трата.

## 3. Развёртывание — 20 минут

Все команды выполняются на сервере по SSH: `ssh root@IP_СЕРВЕРА`.

### 3.1. Docker

```bash
apt update && apt upgrade -y
apt install -y ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list
apt update && apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

### 3.2. Проект и сертификат

```bash
# архив проекта уже загружен в /opt — как это сделать, см. docs/DEPLOY.md, шаг 2
apt install -y unzip
cd /opt && unzip ton-site-builder-1.0.zip && mv ton-site-builder tsb && cd /opt/tsb

# сертификат Let's Encrypt (домен уже должен указывать на этот сервер)
apt install -y certbot
certbot certonly --standalone -d ВАШ_ДОМЕН --agree-tos -m ваша@почта --non-interactive
mkdir -p nginx/certs
cp /etc/letsencrypt/live/ВАШ_ДОМЕН/fullchain.pem nginx/certs/
cp /etc/letsencrypt/live/ВАШ_ДОМЕН/privkey.pem  nginx/certs/
```

> Выпуск в режиме `--standalone` здесь работает, потому что nginx ещё не
> запущен. Продлить сертификат так же не получится — порт 80 будет занят.
> Автопродление настройте по шагу 6 из [DEPLOY.md](DEPLOY.md): переключение на
> webroot и хук, копирующий новый сертификат для nginx.

### 3.3. Конфигурация

```bash
cp backend/.env.example backend/.env
nano backend/.env
```

Заполните (остальное можно оставить как есть):

```ini
ENV=prod
DEBUG=false
CORS_ORIGINS=https://ВАШ_ДОМЕН
DATABASE_URL=postgresql+asyncpg://ton:СИЛЬНЫЙ_ПАРОЛЬ@postgres:5432/ton_builder
TELEGRAM_BOT_TOKEN=токен_от_BotFather
MINI_APP_URL=https://ВАШ_ДОМЕН
ADMIN_TELEGRAM_IDS=ваш_telegram_id
TON_NETWORK=testnet
TON_API_BASE=https://testnet.toncenter.com/api/v2
TON_API_KEY=ключ_от_@tonapibot
TREASURY_ADDRESS=адрес_вашего_кошелька
TON_VERIFY_MODE=onchain
TONCONNECT_DOMAIN=ВАШ_ДОМЕН
SUBDOM_MODE=http
TON_STORAGE_MODE=daemon
```

Пароль БД продублируйте в корневой `.env`:

```bash
printf 'POSTGRES_USER=ton\nPOSTGRES_PASSWORD=СИЛЬНЫЙ_ПАРОЛЬ\nPOSTGRES_DB=ton_builder\n' > .env
```

Манифест TON Connect и адрес возврата для Mini App:

```bash
cat > frontend/public/tonconnect-manifest.json <<'JSON'
{
  "url": "https://ВАШ_ДОМЕН",
  "name": "TON Site Builder",
  "iconUrl": "https://ВАШ_ДОМЕН/icon-192.png"
}
JSON
echo 'VITE_TWA_RETURN_URL=https://t.me/ИМЯ_ВАШЕГО_БОТА' > frontend/.env
```

### 3.4. Конфиг сети TON для storage-daemon

```bash
curl -o storage/global.config.json https://ton.org/testnet-global.config.json
# для mainnet: https://ton.org/global-config.json
```

### 3.5. Сборка и запуск

```bash
# фронтенд
apt install -y nodejs npm
cd frontend && npm ci && npm run build && cd ..

# весь стек, включая storage-daemon
docker compose --profile storage up -d --build
```

Проверка:

```bash
docker compose ps                                   # все сервисы Up
curl https://ВАШ_ДОМЕН/health      # {"status":"ok"}
python3 scripts/smoke_test.py https://ВАШ_ДОМЕН/api ТОКЕН_БОТА
```

### 3.6. Привязка к боту

В @BotFather: `/mybots` → ваш бот → **Bot Settings → Menu Button → Configure menu
button** → адрес `https://ВАШ_ДОМЕН`.

Готово: открывайте бота, жмите кнопку меню.

## 4. Домен `.ton` для зоны субдоменов

Нужен, только если тестируете выдачу субдоменов пользователям. Всё остальное —
конструктор, оплата, публикация в TON Storage, подписки, админка — работает без него.

### Вариант А: вторичный рынок — мгновенно

Единственный вариант, который укладывается в два дня.

1. Откройте [Getgems, коллекция TON DNS Domains](https://getgems.io/collection/EQC3dNlesgVD8YbAazcauIrXBPfiVhMMr5YYk2in0Mtsz0Bz).
2. Отсортируйте по цене по возрастанию — длинные непопулярные имена уходят
   дешевле всего.
3. Купите кошельком Tonkeeper. Домен придёт как NFT на ваш кошелёк сразу.

Это **mainnet и реальные деньги**. Цена зависит от рынка: осмысленные короткие
имена стоят десятки и сотни TON, случайные длинные — единицы.

### Вариант Б: аукцион — от 1 TON, но неделя

1. Откройте [dns.ton.org](https://dns.ton.org), подключите кошелёк.
2. Введите имя. Минимальная ставка зависит от длины: **имена от 11 символов
   стартуют с 1 TON**, короткие — дороже, вплоть до сотен TON.
3. Сделайте ставку. Аукцион идёт **7 дней** с момента первой ставки; если в
   последний час кто-то перебьёт, он продлевается ещё на час.
4. Домен ваш после завершения аукциона.

Свободные имена длиной 11+ символов, которые я проверил (значит, стартуют с 1 TON):

| Имя | Длина | Статус |
|---|---|---|
| `mysitesdemo.ton` | 11 | свободно |
| `tonpagesdemo.ton` | 12 | свободно |
| `tonsitesbuilder.ton` | 15 | свободно |

Проверить любое другое имя можно так:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://tonapi.io/v2/dns/ИМЯ.ton
# 404 — свободно, 200 — занято
```

Домен нужно продлевать раз в год, отправляя на его контракт минимальную сумму,
иначе он уходит обратно на аукцион.

### Настройка зоны после покупки

1. Узнайте адрес DNS-item купленного домена:

   ```bash
   curl -s https://tonapi.io/v2/dns/ВАШДОМЕН.ton | grep -o '"address":"[^"]*"' | head -1
   ```

2. В Mini App: **Админка → Зона** — впишите домен и этот адрес, сохраните.
3. Нажмите **Развернуть зону** и подпишите транзакцию кошельком, которому
   принадлежит домен. Операция разовая.
4. После разворота найдите адрес появившейся коллекции субдоменов
   (в Tonkeeper или на tonviewer в исходящих транзакциях домена) и впишите его
   в поле **Адрес коллекции субдоменов**.
5. Готово: пользователи получают адреса вида `имя.вашдомен.ton`.

## 5. Смета

| Статья | Стоимость |
|---|---|
| Сервер, двое суток | 60–150 ₽ |
| Домен для https | 0 ₽ (DuckDNS) |
| Оплата подписок в тесте | 0 ₽ (testnet) |
| Домен `.ton`, вторичный рынок | от нескольких TON, по рынку |
| Домен `.ton`, аукцион | от 1 TON, но 7 дней |

Без домена `.ton` двухдневный прогон обойдётся примерно в **сто рублей**.

## 6. После теста

```bash
docker compose down -v      # остановить и удалить данные
```

Затем **удалите сервер** в панели провайдера — остановленный продолжает
тарифицироваться за диск и IP. Поддомен DuckDNS можно оставить, он бесплатный.

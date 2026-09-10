# Развёртывание TON Site Builder на своём сервере

Пошаговая инструкция: от пустой Ubuntu до работающего Mini App с оплатой в TON
и сайтами на доменах `.ton`. Все команды выполняются на сервере от `root`
(или через `sudo`).

**Сколько времени:** 40–60 минут, если домен и бот уже готовы.
Отдельно ждём выпуск TLS-сертификата (пара минут) и распространение DNS.

---

## Содержание

1. [Из чего состоит система](#1-из-чего-состоит-система)
2. [Что подготовить заранее](#2-что-подготовить-заранее)
3. [Шаг 1. Сервер и Docker](#шаг-1-сервер-и-docker)
4. [Шаг 2. Код проекта](#шаг-2-код-проекта)
5. [Шаг 3. Бот и Mini App в Telegram](#шаг-3-бот-и-mini-app-в-telegram)
6. [Шаг 4. Кошелёк проекта и ключи API](#шаг-4-кошелёк-проекта-и-ключи-api)
7. [Шаг 5. Конфигурация](#шаг-5-конфигурация)
8. [Шаг 6. TLS-сертификат и автопродление](#шаг-6-tls-сертификат-и-автопродление)
9. [Шаг 7. Конфиг сети TON](#шаг-7-конфиг-сети-ton)
10. [Шаг 8. Сборка Mini App](#шаг-8-сборка-mini-app)
11. [Шаг 9. Первый запуск](#шаг-9-первый-запуск)
12. [Шаг 10. Адрес TON-сайта (ADNL)](#шаг-10-адрес-ton-сайта-adnl)
13. [Шаг 11. Файрвол](#шаг-11-файрвол)
14. [Шаг 12. Настройка через админку](#шаг-12-настройка-через-админку)
15. [Шаг 13. Приёмка](#шаг-13-приёмка)
16. [Эксплуатация](#эксплуатация)
17. [Диагностика](#диагностика)
18. [Приложение: переменные окружения](#приложение-переменные-окружения)

---

## 1. Из чего состоит система

Всё поднимается одной командой `docker compose`. Контейнеры:

| Сервис | Зачем | Порты |
|---|---|---|
| `nginx` | TLS, отдача Mini App, проксирование `/api`, отдача сайтов в домены `.ton` | 80, 443 |
| `backend` | API: конструктор, платежи, домены, админка | внутренний |
| `worker` | публикация сайтов: рендер и заливка в TON Storage | — |
| `scheduler` | подписки: напоминания, снятие с публикации по истечении | — |
| `bot` | уведомления в Telegram | — |
| `migrate` | миграции БД и тарифы, отрабатывает один раз при запуске | — |
| `postgres` | база данных | внутренний |
| `redis` | очередь задач публикации | внутренний |
| `storage-daemon` | раздача опубликованных сайтов в сеть TON | 3333/udp |
| `ton-site` | приём запросов из сети TON по ADNL — домены `.ton` открываются напрямую | 3335/udp |

Два последних включаются профилем `--profile storage`.

**Как это работает вместе.** Пользователь собирает сайт в Mini App, платит
подписку через TON Connect, нажимает «Опубликовать». Воркер рендерит HTML,
заливает его в TON Storage и записывает bag id. Пользователь получает субдомен
в зоне платформы (или привязывает свой домен `.ton`) и подписывает DNS-запись,
которая направляет домен на наш сервер. После этого `имя.домен.ton` открывается
в любом TON-браузере.

---

## 2. Что подготовить заранее

Чеклист. Без этих пунктов дальше идти некуда:

- [ ] **VPS**: Ubuntu 22.04 или 24.04, минимум 2 vCPU / 4 ГБ RAM / 40 ГБ диска,
      публичный IP. Меньше 4 ГБ не берите: контейнеров девять, включая Postgres
      и два узла сети TON.
- [ ] **Домен для Mini App** (обычный, не `.ton`) с A-записью на IP сервера.
      Telegram открывает Mini App только по https, поэтому домен обязателен.
- [ ] **Бот в Telegram** — создаётся за минуту, шаг 3.
- [ ] **Кошелёк TON** для приёма платежей — шаг 4.
- [ ] **Домен `.ton`** — нужен, только если хотите выдавать пользователям
      субдомены вида `имя.вашдомен.ton`. Покупается на
      [dns.ton.org](https://dns.ton.org). Без него платформа работает, но
      пользователи смогут привязывать только собственные домены.

Секреты, которые появятся по ходу, держите в надёжном месте: токен бота,
пароль БД, приватный ключ ADNL (см. шаг 10).

---

## Шаг 1. Сервер и Docker

```bash
apt update && apt upgrade -y
apt install -y ca-certificates curl git

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Проверка:

```bash
docker --version && docker compose version
```

Убедитесь, что часы сервера идут точно — иначе Telegram сочтёт подпись
авторизации просроченной:

```bash
timedatectl set-ntp true && timedatectl
```

## Шаг 2. Код проекта

Проект передаётся архивом `ton-site-builder-1.0.zip`. Его нужно загрузить на
сервер и распаковать в `/opt/tsb`.

**Загрузка с Windows.** В Windows 10 и 11 уже есть `scp` — откройте PowerShell в
папке с архивом:

```powershell
scp ton-site-builder-1.0.zip root@IP_СЕРВЕРА:/opt/
```

Если удобнее мышкой — подключитесь к серверу через
[WinSCP](https://winscp.net) или FileZilla по протоколу SFTP (тот же логин и
пароль, что для SSH) и перетащите архив в `/opt`.

**Распаковка на сервере:**

```bash
apt install -y unzip
cd /opt
unzip ton-site-builder-1.0.zip
mv ton-site-builder tsb
cd /opt/tsb
```

Дальше все команды выполняются из `/opt/tsb`.

> Если проект лежит у вас в собственном git-репозитории, вместо архива можно
> сделать `git clone <адрес вашего репозитория> /opt/tsb` — дальше всё
> одинаково.

## Шаг 3. Бот и Mini App в Telegram

1. Откройте [@BotFather](https://t.me/BotFather) → `/newbot` → задайте имя и
   username. Полученный токен — это **`TELEGRAM_BOT_TOKEN`**.
2. `/newapp` → выберите бота → заполните название, описание, картинку.
   В поле **Web App URL** укажите `https://ВАШ_ДОМЕН`.
3. `/setmenubutton` → выберите бота → тот же URL. Так приложение открывается
   кнопкой рядом с полем ввода.
4. Узнайте свой числовой `telegram_id` — например, написав
   [@userinfobot](https://t.me/userinfobot). Он пойдёт в
   **`ADMIN_TELEGRAM_IDS`**, чтобы у вас открылась админка.

> Токен бота — это полный доступ к боту. Не публикуйте его и не храните в
> репозитории. Если засветили — `/revoke` у BotFather.

## Шаг 4. Кошелёк проекта и ключи API

**Кошелёк.** Заведите отдельный кошелёк (Tonkeeper, Tonhub) — на него будут
приходить платежи за подписки и за «Свой код». Скопируйте адрес → это
**`TREASURY_ADDRESS`**. Приватный ключ серверу не нужен: backend только
проверяет входящие переводы, распоряжаться деньгами он не может. Для боевого
проекта лучше мультисиг.

**Ключ toncenter.** Получите у [@tonapibot](https://t.me/tonapibot) →
**`TON_API_KEY`**. Без ключа toncenter жёстко ограничивает частоту запросов, и
подтверждение платежей начнёт подвисать под нагрузкой.

**subdom.zone.** Ключ нужен только для выдачи субдоменов в вашей зоне `.ton`.
Запрашивается на [subdom.zone](https://subdom.zone) → **`SUBDOM_API_KEY`**.

## Шаг 5. Конфигурация

Два файла: один читает docker compose, другой — само приложение.

```bash
cp .env.example .env                    # compose: пароль БД, адреса в сети TON
cp backend/.env.example backend/.env    # приложение
```

### Корневой `.env`

```ini
POSTGRES_USER=ton
POSTGRES_PASSWORD=ДЛИННЫЙ_СЛУЧАЙНЫЙ_ПАРОЛЬ
POSTGRES_DB=ton_builder

# публичный IP сервера — эти адреса объявляются в сети TON
STORAGE_ADNL_ADDR=203.0.113.10:3333
TON_SITE_ADNL_ADDR=203.0.113.10:3335
```

> Оставите `0.0.0.0` — публикация будет проходить, домен будет указывать на
> нужный bag, но открыть сайт не получится: узлы сети не смогут к вам
> достучаться. Подставьте настоящий IP.

Сгенерировать пароль: `openssl rand -base64 24`.

### `backend/.env`

Минимальный боевой набор:

```ini
ENV=prod
DEBUG=false
CORS_ORIGINS=https://ВАШ_ДОМЕН

DATABASE_URL=postgresql+asyncpg://ton:ТОТ_ЖЕ_ПАРОЛЬ@postgres:5432/ton_builder

TELEGRAM_BOT_TOKEN=123456:AA...
MINI_APP_URL=https://ВАШ_ДОМЕН
ALLOW_INSECURE_AUTH=false
ADMIN_TELEGRAM_IDS=123456789

TON_NETWORK=mainnet
TON_API_BASE=https://toncenter.com/api/v2
TON_API_KEY=...
TREASURY_ADDRESS=UQ...
TON_VERIFY_MODE=onchain

TONCONNECT_DOMAIN=ВАШ_ДОМЕН
TONPROOF_SECRET=ЕЩЁ_ОДНА_СЛУЧАЙНАЯ_СТРОКА

SUBDOM_MODE=http
SUBDOM_API_KEY=...

TON_STORAGE_MODE=daemon
PUBLIC_SITE_BASE_URL=https://ВАШ_ДОМЕН
```

Пароль в `DATABASE_URL` обязан совпадать с `POSTGRES_PASSWORD` из корневого
`.env` — это одна и та же база.

При `ENV=prod` backend на старте сам проверяет конфиг и отказывается
подниматься с опасными значениями: включённым `ALLOW_INSECURE_AUTH`, режимом
`TON_VERIFY_MODE=mock`, пустым токеном бота или адресом кошелька. Это защита от
случайного запуска боевого сервера с настройками разработки.

Полный список переменных с пояснениями — в [приложении](#приложение-переменные-окружения)
и в комментариях `backend/.env.example`.

## Шаг 6. TLS-сертификат и автопродление

Сертификат выпускается через Let's Encrypt. Сначала поднимем nginx, чтобы он
отдавал проверочный файл, потом выпустим сертификат.

```bash
mkdir -p nginx/certs nginx/certbot
# временный самоподписанный, чтобы nginx смог стартовать
openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
  -keyout nginx/certs/privkey.pem -out nginx/certs/fullchain.pem \
  -subj "/CN=ВАШ_ДОМЕН"

docker compose up -d nginx
apt install -y certbot
certbot certonly --webroot -w /opt/tsb/nginx/certbot -d ВАШ_ДОМЕН \
  --agree-tos -m ваша@почта --no-eff-email

cp /etc/letsencrypt/live/ВАШ_ДОМЕН/fullchain.pem nginx/certs/
cp /etc/letsencrypt/live/ВАШ_ДОМЕН/privkey.pem   nginx/certs/
docker compose restart nginx
```

### Автопродление — обязательный шаг

Certbot продлевает сертификат сам (systemd-таймер `certbot.timer`), но кладёт
новый файл в `/etc/letsencrypt`. Nginx в контейнере читает **копии** из
`nginx/certs`, и без хука продление проходит успешно, а наружу продолжает
уезжать старый сертификат — до самого дня истечения, после чего Telegram
перестаёт открывать Mini App.

Создайте хук:

```bash
cat > /etc/letsencrypt/renewal-hooks/deploy/tsb-nginx.sh <<'EOF'
#!/bin/sh
set -e
DOMAIN=ВАШ_ДОМЕН
PROJECT=/opt/tsb
cp "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" "$PROJECT/nginx/certs/fullchain.pem"
cp "/etc/letsencrypt/live/$DOMAIN/privkey.pem"   "$PROJECT/nginx/certs/privkey.pem"
docker compose -f "$PROJECT/docker-compose.yml" restart nginx
EOF
chmod +x /etc/letsencrypt/renewal-hooks/deploy/tsb-nginx.sh
```

Проверьте, что продление вообще работает:

```bash
certbot renew --dry-run
systemctl list-timers | grep certbot   # таймер должен быть активен
```

> **Важно про способ проверки.** Выпускать сертификат нужно именно в режиме
> `--webroot`, как выше. Режим `--standalone` требует свободный порт 80, а его
> занимает nginx, поэтому продление молча провалится. Если сертификат уже был
> выпущен в standalone, поправьте `/etc/letsencrypt/renewal/ВАШ_ДОМЕН.conf`:
> `authenticator = webroot` и `webroot_path = /opt/tsb/nginx/certbot,`.

## Шаг 7. Конфиг сети TON

`storage-daemon` и `ton-site` должны работать в той же сети, где живут домены
`.ton`, то есть в **mainnet**.

```bash
curl -o storage/global.config.json https://ton.org/global.config.json
```

Обязательно проверьте, что скачался конфиг нужной сети:

```bash
python3 -c "import json;print(json.load(open('storage/global.config.json'))['validator']['zero_state']['file_hash'])"
# mainnet: XplPz01CXAps5qeSWUtxcyBfdAo5zVb1N979KLSKD24=
```

> Ошибка в этом месте отлаживается тяжелее всего: с конфигом testnet всё
> выглядит рабочим — сайт публикуется, bag создаётся, ADNL-адрес поднимается, —
> но объявляются они в testnet-DHT, а браузеры и шлюзы ищут в mainnet-DHT и не
> находят. Домен просто не открывается, и никакой ошибки нигде нет.
>
> Для тестового стенда берётся `https://ton.org/testnet-global.config.json`.

## Шаг 8. Сборка Mini App

Интерфейс собирается в статику, которую отдаёт nginx.

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs

cd /opt/tsb/frontend
cp .env.example .env
```

В `frontend/.env` заполните:

```ini
VITE_API_BASE=
VITE_TONCONNECT_MANIFEST=/tonconnect-manifest.json
VITE_TWA_RETURN_URL=https://t.me/ИМЯ_ВАШЕГО_БОТА
```

`VITE_API_BASE` оставьте пустым — API живёт на том же домене.
`VITE_TWA_RETURN_URL` обязателен: без него кошелёк не знает, куда вернуть
пользователя после подписи, и подтверждение зависает.

Отредактируйте `frontend/public/tonconnect-manifest.json` — поля `url` и
`iconUrl` должны указывать на ваш домен, иначе кошельки откажутся подключаться:

```json
{
  "url": "https://ВАШ_ДОМЕН",
  "name": "TON Site Builder",
  "iconUrl": "https://ВАШ_ДОМЕН/icon-192.png"
}
```

Соберите:

```bash
npm ci
npm run build      # результат в frontend/dist, его отдаёт nginx
cd /opt/tsb
```

## Шаг 9. Первый запуск

```bash
docker compose --profile storage up -d --build
```

Поднимутся все девять сервисов. Первая сборка занимает несколько минут.

Проверка:

```bash
docker compose ps                       # все, кроме migrate, должны быть running
curl -fsS https://ВАШ_ДОМЕН/health      # {"status":"ok"}
docker compose logs --tail=50 backend
```

`migrate` со статусом `Exited (0)` — это норма: он отрабатывает миграции и
тарифы один раз и завершается.

Откройте бота в Telegram и нажмите кнопку меню — должно открыться приложение.

## Шаг 10. Адрес TON-сайта (ADNL)

Чтобы домены `.ton` открывались напрямую с вашего сервера, нужен его адрес в
сети TON. Сервис `ton-site` генерирует ключ при первом старте и печатает адрес
в лог:

```bash
docker logs ton-site-builder-ton-site-1 | grep TON_SITE_ADNL
# TON_SITE_ADNL=3vp4dqkfjhk...  (ровно 55 символов)
```

Впишите его в `backend/.env` и перезапустите backend:

```bash
echo "TON_SITE_ADNL=<адрес из лога>" >> backend/.env
docker compose up -d --force-recreate backend
```

> **Ключ нельзя терять и нельзя пересоздавать.** Он лежит в томе
> `ton_site_data`. Этот адрес пользователи прописывают в DNS своих доменов
> собственной подписью — после смены ключа каждому владельцу домена придётся
> подписывать запись заново. Включите том в бэкап (см. [Эксплуатацию](#эксплуатация)).

После этого в разделе публикации появляется кнопка «Включить прямую отдачу»:
она собирает транзакцию смены DNS-записи `site`, которую подписывает владелец
домена. Подпись нужна **один раз на каждый домен** — адрес прокси не меняется.

## Шаг 11. Файрвол

Наружу должны смотреть только четыре порта:

| Порт | Протокол | Зачем |
|---|---|---|
| 80 | tcp | редирект на https и проверка Let's Encrypt |
| 443 | tcp | Mini App и API |
| 3333 | udp | storage-daemon: раздача сайтов в сеть TON |
| 3335 | udp | ton-site: приём запросов из сети TON |

Порт **5555/tcp** — управляющий канал storage-daemon. Он слушает на хосте
(сервисы работают в сети хоста ради UDP), и доступ к нему даёт полный контроль
над раздачей сайтов. Закрываем его службой systemd, которая ставит правила при
каждой загрузке сервера:

```bash
cat > /usr/local/sbin/tsb-firewall.sh <<'EOF'
#!/bin/sh
# Управляющий порт storage-daemon (5555/tcp) доступен только локально и из
# контейнеров. Демон работает в сети хоста, поэтому порт слушает на всех
# интерфейсах, а доступ к нему даёт полный контроль над раздачей сайтов.
#
# Правила ставит systemd при каждой загрузке. netfilter-persistent здесь не
# используется намеренно: он сохранил бы и цепочки Docker со старыми адресами
# контейнеров, а после перезагрузки восстановил бы их поверх свежих.
set -e

for rule in \
  "-s 127.0.0.1/32 -p tcp --dport 5555 -j ACCEPT" \
  "-s 172.16.0.0/12 -p tcp --dport 5555 -j ACCEPT" \
  "-p tcp --dport 5555 -j DROP"
do
  # снимаем прежние копии, чтобы порядок ACCEPT → DROP всегда был верным
  while iptables -D INPUT $rule 2>/dev/null; do :; done
done

iptables -A INPUT -s 127.0.0.1/32 -p tcp --dport 5555 -j ACCEPT
iptables -A INPUT -s 172.16.0.0/12 -p tcp --dport 5555 -j ACCEPT
iptables -A INPUT -p tcp --dport 5555 -j DROP
EOF
chmod 755 /usr/local/sbin/tsb-firewall.sh

cat > /etc/systemd/system/tsb-firewall.service <<'EOF'
[Unit]
Description=TON Site Builder: закрыть управляющий порт storage-daemon снаружи
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/tsb-firewall.sh

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now tsb-firewall.service
iptables -S INPUT | grep 5555     # должно быть три правила: два ACCEPT и DROP
```

Подсеть `172.16.0.0/12` оставлена открытой намеренно: через неё к демону
обращается контейнер backend. Закроете её — публикация сайтов перестанет
работать.

> **Почему не netfilter-persistent.** Он сохраняет все правила разом, включая
> цепочки Docker с адресами контейнеров, и после перезагрузки восстанавливает
> их поверх свежих — сеть контейнеров может перестать работать. Служба выше
> трогает только правила порта 5555.
>
> **Если решите включить ufw**, сначала выполните `ufw allow OpenSSH` — иначе
> потеряете доступ к серверу — и разрешите подсеть Docker к порту 5555:
> `ufw allow from 172.16.0.0/12 to any port 5555 proto tcp`.

## Шаг 12. Настройка через админку

Откройте Mini App своим аккаунтом (его `telegram_id` в `ADMIN_TELEGRAM_IDS`) —
внизу появится вкладка «Админка».

### Тарифы

Сид создаёт готовую сетку: Basic / Pro / Business / Max на 1, 3, 6, 12 месяцев
и бессрочно. Цены редактируются в разделе «Тарифы» — правьте под себя.

Отдельной строкой лежит **«Свой код»** с бейджем «разово». Это не подписка:
столько стоит возможность загрузить свой HTML/CSS/JS для одного сайта, платится
один раз. По умолчанию 5 Gram, меняется там же.

### Зона субдоменов

Нужна, чтобы выдавать пользователям адреса `имя.вашдомен.ton`. Если домена
`.ton` нет, пропустите — пользователи смогут привязывать свои домены.

1. Купите домен на [dns.ton.org](https://dns.ton.org) кошельком, который
   подключите к приложению.
2. Вкладка **«Зона»**:
   - **Домен платформы** — `вашдомен.ton`;
   - **Адрес DNS-item домена** — адрес NFT этого домена. Виден в эксплорере
     (tonviewer, tonscan) на странице домена;
   - **Тип зоны**: *мгновенная выдача* (SBT) — имя выдаётся сразу за
     фиксированную плату; *аукцион* (proxy) — имя разыгрывается. Для
     конструктора обычно нужна мгновенная выдача.
3. Нажмите **«Сохранить»**, затем **«Развернуть зону»** и подпишите транзакцию
   кошельком-владельцем домена. Операция разовая.
4. Адрес коллекции подставится в форму сам — сохраните ещё раз. Статус зоны
   должен стать «Готова».

### Об авторе

Вкладка **«Об авторе»** — заголовок, текст и ссылка, которые пользователи видят
в профиле. Заполните под себя.

## Шаг 13. Приёмка

Пройдите этот список — он покрывает все основные сценарии:

- [ ] Бот открывает Mini App, приложение загружается без ошибок.
- [ ] Видна вкладка «Админка» (у аккаунта из `ADMIN_TELEGRAM_IDS`).
- [ ] В «Профиле» подключается кошелёк через TON Connect, адрес отображается.
- [ ] Создаётся сайт по шаблону, блоки добавляются и редактируются,
      загружается фотография.
- [ ] Предпросмотр показывает страницу.
- [ ] «Опубликовать» → статус меняется на «Опубликован», в Telegram приходит
      уведомление. Первый сайт публикуется бесплатно на 7 дней.
- [ ] Получение субдомена: имя проверяется, транзакция подписывается, домен
      закрепляется за сайтом.
- [ ] «Включить прямую отдачу» → подпись → домен `имя.вашдомен.ton`
      открывается в TON-браузере.
- [ ] Покупка подписки с реального кошелька: активируется только после того,
      как платёж найден в блокчейне.
- [ ] Проект «Свой код»: до оплаты код не сохраняется, после оплаты 5 Gram —
      сохраняется и публикуется.
- [ ] Тёмная и светлая темы, русский и английский язык.

Подробный сценарий ручного тестирования — [docs/TESTING.md](TESTING.md).

---

## Эксплуатация

### Логи

```bash
docker compose logs -f backend worker scheduler bot
docker compose logs --tail=100 ton-site storage-daemon
```

### Обновление версии

Загрузите новый архив в `/opt` так же, как в [шаге 2](#шаг-2-код-проекта), и
распакуйте поверх существующей установки:

```bash
cd /opt
unzip -o ton-site-builder-НОВАЯ_ВЕРСИЯ.zip
cp -r ton-site-builder/. tsb/ && rm -rf ton-site-builder
cd /opt/tsb
cd frontend && npm ci && npm run build && cd ..
docker compose build
docker compose run --rm migrate
docker compose --profile storage up -d
```

Ваши настройки при этом не затираются: в архиве нет файлов `.env`,
сертификатов и конфига сети TON, поэтому `backend/.env`, `frontend/.env`,
`.env`, `nginx/certs/` и `storage/global.config.json` остаются как были. Если
ставили через git — вместо первых трёх команд достаточно `git pull`.

> Код backend вшивается в образ, поэтому после обновления обязателен
> `docker compose build` — одного перезапуска контейнера недостаточно.
>
> Файлы интерфейса имеют хэш в имени и кэшируются навсегда, а `index.html`
> отдаётся с `no-cache` и перечитывается при каждом открытии — обновление
> доезжает до пользователей само.

### Бэкап

База данных:

```bash
docker compose exec -T postgres pg_dump -U ton ton_builder | gzip > db-$(date +%F).sql.gz
```

Загруженные картинки и ключи узлов TON (тома Docker):

```bash
docker run --rm -v ton-site-builder_uploads_data:/data -v $PWD:/backup alpine \
  tar czf /backup/uploads-$(date +%F).tgz -C /data .
docker run --rm -v ton-site-builder_ton_site_data:/data -v $PWD:/backup alpine \
  tar czf /backup/ton-site-key-$(date +%F).tgz -C /data .
docker run --rm -v ton-site-builder_storage_data:/data -v $PWD:/backup alpine \
  tar czf /backup/storage-$(date +%F).tgz -C /data .
```

`ton_site_data` — тот самый ключ ADNL. Потеряете его — все пользователи
получат неработающие домены, пока каждый не подпишет запись заново.

Восстановление базы:

```bash
gunzip -c db-2026-01-01.sql.gz | docker compose exec -T postgres psql -U ton ton_builder
```

### Полезные команды

```bash
docker compose exec backend alembic upgrade head   # миграции вручную
docker compose exec backend python -m app.seed     # досоздать тарифы
docker compose restart backend                     # перезапуск API
docker compose --profile storage up -d             # поднять всё, включая узлы TON
```

---

## Диагностика

| Симптом | Причина и решение |
|---|---|
| Mini App не открывается, «не удалось подключиться» | Истёк сертификат либо не настроено автопродление — см. [шаг 6](#шаг-6-tls-сертификат-и-автопродление). Проверка: `echo \| openssl s_client -connect ВАШ_ДОМЕН:443 2>/dev/null \| openssl x509 -noout -dates` |
| `401 INIT_DATA_INVALID` | `TELEGRAM_BOT_TOKEN` не от того бота, из которого открыто приложение |
| `401 INIT_DATA_EXPIRED` | Разъехались часы сервера: `timedatectl set-ntp true` |
| `401 TONPROOF_INVALID` | `TONCONNECT_DOMAIN` не совпадает с доменом, на котором открыт Mini App |
| Кошелёк не подключается | В `tonconnect-manifest.json` чужой домен, либо файл не пересобран после правки |
| Подтверждение платежа зависает в кошельке | Не задан `VITE_TWA_RETURN_URL` при сборке интерфейса |
| `400 PAYMENT_NOT_CONFIRMED` | Транзакция ещё не в блокчейне, либо не совпали сумма или адрес. Проверьте `TREASURY_ADDRESS` и `TON_API_KEY` |
| Сайт завис в статусе «публикуется» | Не запущен воркер: `docker compose ps worker`, `docker compose logs worker` |
| Сайт опубликован, но домен `.ton` не открывается | Чаще всего конфиг сети — [шаг 7](#шаг-7-конфиг-сети-ton). Затем: заполнен ли `TON_SITE_ADNL`, открыт ли UDP 3335, подписал ли владелец домена «прямую отдачу» |
| Домен открывается пустой страницей | Сайт в черновике: опубликуйте его. Прямая отдача берёт последнюю опубликованную версию |
| `502 SUBDOM_ERROR` | Недоступен subdom API. Уже выданные домены работают, недоступен только выпуск новых |
| `502 STORAGE_ERROR` | Не отвечает storage-daemon: `docker compose logs storage-daemon` |
| Уведомления не приходят | Пользователь не нажал `/start` у бота — Telegram запрещает писать первым |
| Правки интерфейса не видны | Пересоберите фронтенд (`npm run build`) и перезапустите приложение в Telegram: зажать в списке → «Перезапустить» |
| `ton-site` перезапускается по кругу | В логе «Wrong length of adnl id»: удалите том `ton_site_data` и дайте сгенерировать ключ заново — **только если домены ещё никому не выданы** |
| Порт 5555 открыт наружу после перезагрузки | Не включена служба файрвола: `systemctl enable --now tsb-firewall.service` — см. шаг 11 |

---

## Приложение: переменные окружения

Полный список с комментариями — в `backend/.env.example` и `.env.example`.
Здесь только то, что обязательно задать самому.

### Корневой `.env` (docker compose)

| Переменная | Значение |
|---|---|
| `POSTGRES_PASSWORD` | пароль БД, тот же, что в `DATABASE_URL` |
| `STORAGE_ADNL_ADDR` | `публичный_IP:3333` |
| `TON_SITE_ADNL_ADDR` | `публичный_IP:3335` |

### `backend/.env` (приложение)

| Переменная | Боевое значение |
|---|---|
| `ENV` | `prod` |
| `DEBUG` | `false` |
| `CORS_ORIGINS` | `https://ВАШ_ДОМЕН` |
| `DATABASE_URL` | `postgresql+asyncpg://ton:ПАРОЛЬ@postgres:5432/ton_builder` |
| `TELEGRAM_BOT_TOKEN` | токен от BotFather |
| `MINI_APP_URL` | `https://ВАШ_ДОМЕН` |
| `ALLOW_INSECURE_AUTH` | `false` — иначе авторизацию можно подделать |
| `ADMIN_TELEGRAM_IDS` | ваш `telegram_id`, несколько — через запятую |
| `TON_NETWORK` | `mainnet` |
| `TON_API_BASE` | `https://toncenter.com/api/v2` |
| `TON_API_KEY` | ключ от @tonapibot |
| `TREASURY_ADDRESS` | адрес кошелька для приёма платежей |
| `TON_VERIFY_MODE` | `onchain` — реальная проверка платежей |
| `TONCONNECT_DOMAIN` | домен без схемы, например `app.example.com` |
| `TONPROOF_SECRET` | случайная строка |
| `SUBDOM_MODE` | `http` |
| `SUBDOM_API_KEY` | ключ subdom.zone |
| `TON_STORAGE_MODE` | `daemon` |
| `TON_SITE_ADNL` | адрес из лога `ton-site`, 55 символов |
| `PUBLIC_SITE_BASE_URL` | `https://ВАШ_ДОМЕН` |

### `frontend/.env` (сборка интерфейса)

| Переменная | Значение |
|---|---|
| `VITE_API_BASE` | пусто — API на том же домене |
| `VITE_TONCONNECT_MANIFEST` | `/tonconnect-manifest.json` |
| `VITE_TWA_RETURN_URL` | `https://t.me/ИМЯ_БОТА` |

---

## Что дальше

* [docs/TESTING.md](TESTING.md) — сценарии ручного тестирования
* [docs/API.md](API.md) — API-контракт и коды ошибок
* [docs/QUICKSTART_SERVER.md](QUICKSTART_SERVER.md) — короткий прогон на
  арендованном сервере, если нужно просто показать работу
* [backend/README.md](../backend/README.md), [frontend/README.md](../frontend/README.md)
  — запуск частей проекта локально

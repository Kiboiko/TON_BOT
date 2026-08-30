# TON Storage daemon

Сюда положите `global.config.json` сети TON — его монтирует сервис
`storage-daemon` в docker-compose (профиль `storage`).

```bash
# mainnet
curl -o global.config.json https://ton.org/global-config.json
# testnet
curl -o global.config.json https://ton.org/testnet-global.config.json
```

Файл не хранится в репозитории: сеть выбирается на конкретном сервере.
Подробности — docs/DEPLOY.md, шаг 7.

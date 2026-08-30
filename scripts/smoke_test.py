"""Дымовой тест поднятого стека: auth -> сайт -> оплата -> публикация -> админка.

Бьёт по живому API через nginx и проверяет то, чего не видят юнит-тесты: миграции
на Postgres, очередь Redis, воркер публикации, отдачу через nginx.

    python scripts/smoke_test.py [BASE_URL] [BOT_TOKEN]

По умолчанию https://localhost/api и токен из локального backend/.env.
Каждый запуск заводит нового пользователя, поэтому прогон повторяем.
Требует, чтобы telegram_id 777000 был в ADMIN_TELEGRAM_IDS.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

import httpx
from app.core.telegram_auth import build_init_data

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://localhost/api").rstrip("/")
TOKEN = sys.argv[2] if len(sys.argv) > 2 else "123456:LOCAL-TEST-BOT-TOKEN"

ok = 0
fail = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global ok, fail
    if condition:
        ok += 1
        print(f"  [OK]   {name}")
    else:
        fail += 1
        print(f"  [FAIL] {name} {detail}")


def headers(tg_id: int, username: str) -> dict[str, str]:
    return {
        "X-Telegram-Init-Data": build_init_data(
            TOKEN, {"id": tg_id, "username": username, "first_name": "Test", "language_code": "ru"}
        )
    }


client = httpx.Client(verify=False, timeout=30.0)
# новый пользователь на каждый прогон: БД между запусками не чистится
RUN = int(time.time()) % 100000
USER_ID = 100000 + RUN
USER_NAME = f"e2e_user_{RUN}"
user = headers(USER_ID, USER_NAME)
admin = headers(777000, "e2e_admin")

print("\n== 1. Авторизация и права ==")
r = client.post(f"{BASE}/user/auth", headers=user, json={})
check("POST /user/auth 200", r.status_code == 200, r.text[:120])
check("обычный пользователь не админ", r.json()["is_admin"] is False)
check("telegram_id совпадает", r.json()["user"]["telegram_id"] == USER_ID)

r = client.post(f"{BASE}/user/auth", headers=admin, json={})
check("админ распознан по ADMIN_TELEGRAM_IDS", r.json()["is_admin"] is True)

r = client.get(f"{BASE}/sites")
check("без initData -> 401", r.status_code == 401, r.text[:120])
check("единый формат ошибки", r.json().get("error", {}).get("code") == "INIT_DATA_MISSING")

r = client.get(f"{BASE}/sites", headers={"X-Telegram-Init-Data": "user=%7B%22id%22%3A1%7D&hash=deadbeef"})
check("подделанная подпись -> 401", r.status_code == 401)

print("\n== 2. Настройки пользователя ==")
r = client.patch(f"{BASE}/user/settings", headers=user, json={"language": "en", "theme": "dark"})
check("PATCH /user/settings", r.json() == {"success": True})
r = client.get(f"{BASE}/user/me", headers=user)
check("настройки сохранились", r.json()["language"] == "en" and r.json()["theme"] == "dark")
client.patch(f"{BASE}/user/settings", headers=user, json={"language": "ru"})

print("\n== 3. Тарифы (сид) ==")
r = client.get(f"{BASE}/tariffs", headers=user)
tariffs = r.json()
check("витрина тарифов не пуста", len(tariffs) >= 3, str(tariffs)[:120])
check("цена без хвостовых нулей", all("." not in t["price_ton"] or t["price_ton"][-1] != "0" for t in tariffs))
check("custom_code скрыт из витрины", all(t["kind"] != "custom_code" for t in tariffs))

print("\n== 4. Сайты: создание, лимит, превью ==")
r = client.post(f"{BASE}/sites", headers=user, json={"type": "visitka", "title": "Моя визитка"})
check("POST /sites 201", r.status_code == 201, r.text[:160])
site = r.json()["site"]
site_id = site["id"]
check("скелет шаблона проставлен", len(site["content_json"]["blocks"]) > 0)
check("статус draft", site["status"] == "draft")

r = client.post(f"{BASE}/sites", headers=user, json={"type": "links", "title": "Второй"})
check("второй сайт без подписки -> 403 LIMIT_EXCEEDED",
      r.status_code == 403 and r.json()["error"]["code"] == "LIMIT_EXCEEDED", r.text[:120])

content = {
    "version": 1,
    "meta": {"title": "Ирина", "description": "Дизайнер", "lang": "ru"},
    "theme": {"preset": "aurora", "accent": "#ff6600"},
    "blocks": [
        {"id": "b1", "type": "hero", "props": {"title": "Ирина", "subtitle": "Дизайнер"}},
        {"id": "b2", "type": "links", "props": {"items": [
            {"title": "Telegram", "url": "https://t.me/ton"},
            {"title": "XSS", "url": "javascript:alert(1)"},
        ]}},
        {"id": "b3", "type": "text", "props": {"title": "<script>alert(1)</script>", "text": "Привет"}},
    ],
}
r = client.patch(f"{BASE}/sites/{site_id}", headers=user, json={"content_json": content, "title": "Визитка v2"})
check("PATCH /sites/{id}", r.status_code == 200 and r.json()["site"]["title"] == "Визитка v2")

r = client.post(f"{BASE}/sites/{site_id}/preview", headers=user)
html = r.json()["preview_html"]
check("превью отдаёт HTML", html.startswith("<!DOCTYPE html>"))
check("текст пользователя экранирован", "<script>alert(1)</script>" not in html)
check("javascript:-ссылка вырезана", "javascript:" not in html)
check("нормальная ссылка осталась", "https://t.me/ton" in html)

r = client.get(f"{BASE}/sites/{site_id}", headers=headers(999000 + RUN, "stranger"))
check("чужой сайт недоступен -> 404", r.status_code == 404 and r.json()["error"]["code"] == "SITE_NOT_FOUND")

print("\n== 5. Оплата подписки и рост лимита ==")
pro = next(t for t in tariffs if t["sites_limit"] >= 5)
r = client.post(f"{BASE}/subscriptions/purchase", headers=user, json={"tariff_id": pro["id"]})
check("purchase отдаёт транзакцию", r.status_code == 200 and "transaction" in r.json(), r.text[:160])
tx = r.json()["transaction"]
payment_id = r.json()["payment_id"]
check("адрес казначейства в транзакции", tx["messages"][0]["address"].startswith("0:1111"))
check("сумма в нанотонах", tx["messages"][0]["amount"] == str(int(float(pro["price_ton"]) * 1e9)))
check("validUntil в будущем", tx["validUntil"] > int(time.time()))

r = client.post(f"{BASE}/subscriptions/confirm", headers=user,
                json={"payment_id": payment_id, "tx_hash": f"e2e-sub-{RUN}"})
check("confirm активирует подписку", r.status_code == 200, r.text[:160])
sub = r.json()["subscription"]
check("подписка активна", sub["status"] == "active")
check("лимит тарифа виден", sub["tariff"]["sites_limit"] == pro["sites_limit"])

created = [site_id]
for i in range(2, 6):
    r = client.post(f"{BASE}/sites", headers=user, json={"type": "landing", "title": f"Сайт {i}"})
    if r.status_code == 201:
        created.append(r.json()["site"]["id"])
check(f"лимит вырос до {pro['sites_limit']}", len(created) == 5, f"создано {len(created)}")
r = client.post(f"{BASE}/sites", headers=user, json={"type": "links", "title": "Лишний"})
check("сверх лимита -> 403", r.status_code == 403)

r = client.get(f"{BASE}/subscriptions", headers=user)
check("GET /subscriptions", r.status_code == 200 and len(r.json()) >= 1)

print("\n== 6. Домены ==")
r = client.get(f"{BASE}/domains/check", headers=user, params={"name": "mysite", "tld": "ton"})
check("свободный домен", r.status_code == 200 and r.json()["available"] is True, r.text[:120])
r = client.get(f"{BASE}/domains/check", headers=user, params={"name": "takenname", "tld": "ton"})
check("занятый домен", r.json()["available"] is False)
r = client.get(f"{BASE}/domains/check", headers=user, params={"name": "ab", "tld": "ton"})
check("короткое имя -> 400", r.status_code == 400 and r.json()["error"]["code"] == "INVALID_DOMAIN_NAME")
r = client.post(f"{BASE}/domains/deploy-zone", headers=user,
                json={"site_id": site_id, "domain": "mysite", "tld": "ton", "mode": "proxy"})
check("без кошелька deploy-zone -> 401 WALLET_NOT_CONNECTED",
      r.status_code == 401 and r.json()["error"]["code"] == "WALLET_NOT_CONNECTED", r.text[:120])

print("\n== 7. Публикация через Redis + воркер ==")
r = client.post(f"{BASE}/sites/{site_id}/publish", headers=user)
check("publish ставит задачу", r.status_code == 200 and r.json()["status"] == "publishing", r.text[:160])
job_id = r.json().get("job_id")
check("job_id получен", bool(job_id))

status, bag, err = None, None, None
for _ in range(30):
    time.sleep(1)
    s = client.get(f"{BASE}/sites/{site_id}/publish-status", headers=user).json()
    status, bag, err = s["status"], s.get("storage_bag_id"), s.get("error")
    if status != "publishing":
        break
check("воркер довёл публикацию до published", status == "published", f"status={status} error={err}")
check("получен storage_bag_id", bool(bag), str(bag))

print("\n== 8. Премиум-блок «Свой код» ==")
r = client.post(f"{BASE}/sites/{site_id}/custom-code", headers=user, json={"html": "<b>x</b>", "css": "", "js": ""})
check("до оплаты -> 402", r.status_code == 402 and r.json()["error"]["code"] == "CUSTOM_CODE_NOT_PAID")
r = client.post(f"{BASE}/sites/{site_id}/custom-code/purchase", headers=user)
check("purchase премиум-блока", r.status_code == 200, r.text[:160])
cc_payment = r.json()["payment_id"]
r = client.post(f"{BASE}/sites/{site_id}/custom-code/confirm", headers=user,
                json={"payment_id": cc_payment, "tx_hash": f"e2e-cc-{RUN}"})
check("оплата подтверждена", r.status_code == 200, r.text[:160])
r = client.post(f"{BASE}/sites/{site_id}/custom-code", headers=user,
                json={"html": "<b>promo</b>", "css": "b{color:red}", "js": "console.log(1)"})
check("после оплаты код сохраняется", r.status_code == 200, r.text[:160])
html = client.post(f"{BASE}/sites/{site_id}/preview", headers=user).json()["preview_html"]
check("код изолирован в sandbox-iframe", '<iframe class="custom-frame" sandbox="allow-scripts"' in html)

print("\n== 9. Админка ==")
r = client.get(f"{BASE}/admin/stats", headers=user)
check("не админ -> 403 ADMIN_REQUIRED", r.status_code == 403 and r.json()["error"]["code"] == "ADMIN_REQUIRED")

r = client.get(f"{BASE}/admin/stats", headers=admin)
stats = r.json()
check("статистика отдаётся", r.status_code == 200 and stats["total_users"] >= 2, str(stats)[:160])
check("опубликованные сайты посчитаны", stats["published_sites"] >= 1)
check("оборот посчитан", float(stats["revenue"]) > 0, str(stats.get("revenue")))

r = client.get(f"{BASE}/admin/users", headers=admin, params={"search": USER_NAME})
check("поиск пользователей", r.json()["total"] == 1, r.text[:160])
target = r.json()["users"][0]
check("счётчики в списке", target["sites_count"] == 5 and target["active_subscriptions"] >= 1)

r = client.get(f"{BASE}/admin/users/{target['id']}", headers=admin)
detail = r.json()
check("карточка пользователя", len(detail["sites"]) == 5 and len(detail["payments"]) >= 2)

r = client.post(f"{BASE}/admin/tariffs", headers=admin,
                json={"name": "E2E Test", "sites_limit": 3, "duration": "month",
                      "price_ton": "3", "kind": "pro", "is_active": True})
check("создание тарифа", r.status_code == 201, r.text[:160])
new_tariff = r.json()
r = client.patch(f"{BASE}/admin/tariffs/{new_tariff['id']}", headers=admin, json={"price_ton": "4.5"})
check("изменение цены", r.json()["price_ton"] == "4.5", r.text[:120])
check("цена видна в витрине",
      any(t["price_ton"] == "4.5" for t in client.get(f"{BASE}/tariffs", headers=user).json()))

r = client.post(f"{BASE}/admin/users/{target['id']}/grant-access", headers=admin,
                json={"sites_limit": 10, "duration": "forever", "comment": "e2e"})
check("ручная выдача доступа", r.status_code == 200, r.text[:160])
granted = r.json()["subscription"]
check("granted_by_admin=true", granted["granted_by_admin"] is True and granted["is_forever"] is True)

r = client.post(f"{BASE}/admin/users/{target['id']}/revoke-access", headers=admin,
                json={"subscription_id": granted["id"]})
check("отзыв доступа", r.json() == {"success": True})

r = client.get(f"{BASE}/admin/actions", headers=admin)
actions = {a["action"] for a in r.json()}
check("аудит пишет действия", {"create_tariff", "change_price", "grant_access", "revoke_access"} <= actions, str(actions))

r = client.delete(f"{BASE}/admin/tariffs/{new_tariff['id']}", headers=admin)
check("удаление тарифа", r.json() == {"success": True})

r = client.get(f"{BASE}/admin/domains", headers=admin)
check("список доменов доступен", r.status_code == 200)

print("\n== 10. Удаление сайта ==")
r = client.delete(f"{BASE}/sites/{created[-1]}", headers=user)
check("DELETE /sites/{id}", r.json() == {"success": True})
check("сайт исчез из списка",
      all(s["id"] != created[-1] for s in client.get(f"{BASE}/sites", headers=user).json()))

print(f"\n=== ИТОГО: {ok} прошло, {fail} провалилось ===")
print(f"site_id для ручной проверки: {site_id}")
sys.exit(1 if fail else 0)

"""Перевод стенда на новый публичный адрес.

Быстрые туннели (trycloudflare, ngrok) выдают новый адрес при каждом запуске,
а адрес прописан в трёх местах: backend/.env, манифест TON Connect и кнопка
меню бота. Скрипт правит все три и подсказывает, что перезапустить.

    python scripts/set_public_url.py https://xxx.trycloudflare.com

Домен обязан совпадать во всех местах: ton_proof подписывается доменом, и при
расхождении backend отклонит подключение кошелька.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / "backend" / ".env"
MANIFEST = ROOT / "frontend" / "public" / "tonconnect-manifest.json"


def read_env_value(key: str) -> str:
    if not ENV.exists():
        return ""
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def patch_env(url: str, domain: str) -> None:
    lines = ENV.read_text(encoding="utf-8").splitlines()
    replacements = {
        "MINI_APP_URL": url,
        "TONCONNECT_DOMAIN": domain,
        "CORS_ORIGINS": url,
    }
    out = []
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else ""
        out.append(f"{key}={replacements[key]}" if key in replacements else line)
    ENV.write_text("\n".join(out), encoding="utf-8")
    print(f"  backend/.env: MINI_APP_URL, TONCONNECT_DOMAIN, CORS_ORIGINS -> {domain}")


def patch_manifest(url: str) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["url"] = url
    manifest["iconUrl"] = f"{url}/icon-192.png"
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  tonconnect-manifest.json -> {url}")


def patch_menu_button(url: str, token: str) -> None:
    """Обновляет кнопку меню и присылает админам сообщение с рабочей кнопкой.

    Кнопка меню выставляется и по умолчанию, и отдельно для каждого чата админа:
    настройка чата (например, сделанная руками в BotFather) перебивает дефолтную,
    поэтому без этого в чате остаётся старый адрес. Кнопки в уже отправленных
    сообщениях не обновляются никогда — адрес в них зашит при отправке, поэтому
    админу уходит свежее сообщение.
    """
    if not token:
        print("  кнопка меню: пропущена, TELEGRAM_BOT_TOKEN не задан")
        return
    import httpx

    api = f"https://api.telegram.org/bot{token}"
    button = {"type": "web_app", "text": "Конструктор", "web_app": {"url": url}}
    admins = [a.strip() for a in read_env_value("ADMIN_TELEGRAM_IDS").split(",") if a.strip().isdigit()]

    def call(method: str, payload: dict) -> dict:
        try:
            return httpx.post(f"{api}/{method}", json=payload, timeout=20.0).json()
        except Exception as exc:  # noqa: BLE001 - сеть не должна ронять скрипт
            return {"ok": False, "description": str(exc)}

    data = call("setChatMenuButton", {"menu_button": button})
    print("  кнопка меню (по умолчанию):", "обновлена" if data.get("ok") else data.get("description"))

    for chat_id in admins:
        data = call("setChatMenuButton", {"chat_id": int(chat_id), "menu_button": button})
        status = "обновлена" if data.get("ok") else data.get("description")
        print(f"  кнопка меню (чат {chat_id}): {status}")

        data = call("sendMessage", {
            "chat_id": int(chat_id),
            "text": "<b>TON Site Builder</b>\n\nАдрес стенда обновлён. Открывайте по кнопке ниже — "
                    "кнопки в старых сообщениях ведут на прошлый адрес.",
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": [[{"text": "🚀 Открыть конструктор",
                                                   "web_app": {"url": url}}]]},
        })
        if not data.get("ok") and "chat not found" not in str(data.get("description", "")).lower():
            print(f"  уведомление в чат {chat_id}: {data.get('description')}")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)

    url = sys.argv[1].rstrip("/")
    if not re.fullmatch(r"https://[\w.-]+", url):
        print("Адрес должен быть вида https://example.com (без пути)")
        sys.exit(2)
    domain = url.removeprefix("https://")

    print(f"Перевожу стенд на {url}")
    patch_env(url, domain)
    patch_manifest(url)
    patch_menu_button(url, os.environ.get("TELEGRAM_BOT_TOKEN") or read_env_value("TELEGRAM_BOT_TOKEN"))

    print(
        "\nОсталось применить:\n"
        "  cd frontend && npm run build && cd ..\n"
        "  docker compose -f docker-compose.yml -f docker-compose.tunnel.yml up -d backend bot"
    )


if __name__ == "__main__":
    main()

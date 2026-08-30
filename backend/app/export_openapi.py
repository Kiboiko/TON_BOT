"""Экспорт OpenAPI-схемы в файл — для мок-сервера и генерации типов фронта.

Запуск: python -m app.export_openapi [путь]  (по умолчанию ../docs/openapi.json)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    from app.main import app

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("../docs/openapi.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    schema = app.openapi()
    target.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    paths = len(schema.get("paths", {}))
    print(f"OpenAPI written to {target} ({paths} paths)")


if __name__ == "__main__":
    main()

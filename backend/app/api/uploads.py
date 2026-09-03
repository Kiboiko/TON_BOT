"""Загрузка изображений для конструктора (B2).

В блоках картинки задаются ссылкой, но пользователю неоткуда её взять — поэтому
файл загружается сюда, а в content_json попадает адрес вида /u/<имя>.

Хранилище намеренно простое: файлы лежат на диске рядом с отрендеренными сайтами.
Замена на объектное хранилище — это новая реализация `save_upload`, остальной код
не меняется.
"""
from __future__ import annotations

import logging
import secrets
from pathlib import Path

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser
from app.core.config import settings
from app.core.errors import BadRequest, NotFound
from app.schemas import UploadResponse

log = logging.getLogger(__name__)

router = APIRouter(tags=["uploads"])

# Тип определяем по сигнатуре файла, а не по присланному content-type:
# заголовок подделывается, содержимое — нет. SVG не принимаем совсем —
# это XML, внутри которого исполняется скрипт.
SIGNATURES: list[tuple[bytes, str, str]] = [
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"GIF87a", "gif", "image/gif"),
    (b"GIF89a", "gif", "image/gif"),
]


def detect_image(blob: bytes) -> tuple[str, str]:
    """Возвращает (расширение, mime) или отказывает, если это не картинка."""
    for signature, ext, mime in SIGNATURES:
        if blob.startswith(signature):
            return ext, mime
    # webp: "RIFF....WEBP"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "webp", "image/webp"
    raise BadRequest(
        "Only PNG, JPEG, GIF and WEBP images are supported", code="UNSUPPORTED_IMAGE"
    )


def uploads_dir() -> Path:
    path = Path(settings.UPLOADS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


@router.post("/api/uploads", response_model=UploadResponse)
async def upload_image(user: CurrentUser, file: UploadFile = File(...)) -> UploadResponse:
    blob = await file.read(settings.MAX_UPLOAD_BYTES + 1)
    if not blob:
        raise BadRequest("Empty file", code="EMPTY_FILE")
    if len(blob) > settings.MAX_UPLOAD_BYTES:
        raise BadRequest(
            f"File is too large (limit {settings.MAX_UPLOAD_BYTES // 1024 // 1024} MB)",
            code="FILE_TOO_LARGE",
        )

    ext, mime = detect_image(blob)
    name = f"{secrets.token_hex(16)}.{ext}"
    (uploads_dir() / name).write_bytes(blob)
    log.info("upload %s (%s bytes) by user %s", name, len(blob), user.telegram_id)

    base = (settings.PUBLIC_SITE_BASE_URL or settings.MINI_APP_URL or "").rstrip("/")
    return UploadResponse(url=f"{base}/u/{name}" if base else f"/u/{name}", size=len(blob), mime=mime)


@router.get("/u/{name}", include_in_schema=False)
async def serve_upload(name: str) -> FileResponse:
    """Отдаёт загруженный файл. Без авторизации: картинка нужна опубликованному сайту."""
    safe = Path(name).name  # никаких путей наружу каталога
    path = uploads_dir() / safe
    if not safe or not path.is_file():
        raise NotFound("File not found", code="FILE_NOT_FOUND")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})

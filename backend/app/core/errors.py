"""Единый формат ошибки API (раздел 4 ТЗ):

    { "error": { "code": "STRING_CODE", "message": "human readable" } }

Любая ошибка, уходящая наружу, проходит через эти обработчики — фронт всегда
получает одинаковую структуру и может держать один обработчик на весь клиент.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)


class AppError(Exception):
    """Базовая доменная ошибка приложения."""

    code = "INTERNAL_ERROR"
    status_code = 500
    message = "Internal server error"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        err: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            err["details"] = self.details
        return {"error": err}


# --- 4xx ---
class BadRequest(AppError):
    code, status_code, message = "BAD_REQUEST", 400, "Bad request"


class Unauthorized(AppError):
    code, status_code, message = "UNAUTHORIZED", 401, "Authorization required"


class Forbidden(AppError):
    code, status_code, message = "FORBIDDEN", 403, "Access denied"


class NotFound(AppError):
    code, status_code, message = "NOT_FOUND", 404, "Object not found"


class Conflict(AppError):
    code, status_code, message = "CONFLICT", 409, "Conflict"


class ValidationFailed(AppError):
    code, status_code, message = "VALIDATION_ERROR", 422, "Validation error"


class LimitExceeded(AppError):
    code, status_code, message = "LIMIT_EXCEEDED", 403, "Plan limit exceeded"


class PaymentRequired(AppError):
    code, status_code, message = "PAYMENT_REQUIRED", 402, "Payment required"


class PaymentNotConfirmed(AppError):
    code, status_code, message = "PAYMENT_NOT_CONFIRMED", 400, "Transaction is not confirmed on-chain"


# --- внешние сервисы ---
class ExternalServiceError(AppError):
    code, status_code, message = "EXTERNAL_SERVICE_ERROR", 502, "External service error"


class SubdomError(ExternalServiceError):
    code, message = "SUBDOM_ERROR", "Domain service is unavailable"


class TonApiError(ExternalServiceError):
    code, message = "TON_API_ERROR", "TON API is unavailable"


class StorageError(ExternalServiceError):
    code, message = "STORAGE_ERROR", "TON Storage is unavailable"


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            log.exception("AppError: %s", exc.message)
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            409: "CONFLICT",
            429: "RATE_LIMITED",
        }.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code, "message": str(exc.detail)}},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "details": {"errors": exc.errors()},
                }
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": "Internal server error"}},
        )

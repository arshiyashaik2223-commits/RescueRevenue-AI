"""
app/core/exceptions.py

Uniform error handling for the backend.

AppError is the exception every route in this codebase raises directly
for intentional, expected error conditions (404s, 409s, 422s, 429s,
502s) — it's already used throughout auth_routes.py, transaction_routes.py,
failed_payment_routes.py, webhook_routes.py, analytics_routes.py, and
security.py.

register_exception_handlers(app) wires up three handlers against the
FastAPI app instance (called from app/main.py, upcoming):
  - AppError            -> the exact {"error": {code, message, details}}
                           envelope documented in the approved API spec
  - RequestValidationError -> FastAPI's own built-in validation errors
                           (e.g. a query param failing its Query(..., le=100)
                           constraint) reshaped into the SAME envelope,
                           so a client never sees two different error
                           shapes depending on whether a route or FastAPI
                           itself rejected the request
  - Exception (catch-all)  -> any unhandled error becomes a generic
                           500 INTERNAL_ERROR rather than leaking a raw
                           traceback or Python exception message to the
                           client
"""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """
    Base application exception. Raised directly by routes/services for
    any expected error condition.

    Usage (as already used throughout the codebase):
        raise AppError(
            status_code=404,
            code="TRANSACTION_NOT_FOUND",
            message="No transaction found with this ID.",
        )

    `details` is optional and mirrors the API spec's error envelope's
    `details` field — typically a small dict pointing at which field(s)
    caused a validation failure.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


# ----------------------------------------------------------------------
# Convenience subclasses
# ----------------------------------------------------------------------
# Thin, optional shortcuts for the most common cases — routes are free
# to keep using the base AppError directly (as all currently-generated
# routes do) or switch to these for slightly more readable call sites.
# Both forms produce an identical response envelope.
class NotFoundError(AppError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, code=code, message=message, details=details)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Missing or invalid authorization header.", code: str = "UNAUTHORIZED") -> None:
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, code=code, message=message)


class ForbiddenError(AppError):
    def __init__(self, message: str = "You do not have permission to perform this action.", code: str = "FORBIDDEN") -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, code=code, message=message)


class ConflictError(AppError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, code=code, message=message, details=details)


class ValidationAppError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message=message,
            details=details,
        )


class RateLimitedError(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(status_code=status.HTTP_429_TOO_MANY_REQUESTS, code=code, message=message)


class RazorpaySignatureError(AppError):
    """Raised when an inbound Razorpay webhook fails HMAC verification."""

    def __init__(self, message: str = "Webhook signature verification failed.") -> None:
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, code="INVALID_SIGNATURE", message=message)


# ----------------------------------------------------------------------
# Response envelope builder
# ----------------------------------------------------------------------
def _error_envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Builds the exact error shape documented in
    RevenueRescue-AI-API-Specification.md's "Standard error envelope":
        { "error": { "code": ..., "message": ..., "details": {...} } }
    `details` is omitted entirely (not sent as null) when not provided,
    to keep successful-validation-detail responses lean.
    """
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"error": error}


# ----------------------------------------------------------------------
# Exception handlers
# ----------------------------------------------------------------------
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Handles every intentional AppError (and its subclasses) raised by routes/services."""
    logger.info(
        "AppError: %s %s -> %s %s (%s)",
        request.method,
        request.url.path,
        exc.status_code,
        exc.code,
        exc.message,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_envelope(exc.code, exc.message, exc.details),
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Reshapes FastAPI/Pydantic's built-in validation error format into
    the same envelope AppError produces, so callers never have to
    special-case "did the route reject this, or did FastAPI reject it
    before the route ran."
    """
    details: dict[str, Any] = {}
    for err in exc.errors():
        # err["loc"] looks like ("query", "page_size") or ("body", "email")
        field = ".".join(str(part) for part in err.get("loc", []) if part not in ("body", "query", "path"))
        details[field or "request"] = err.get("msg", "Invalid value.")

    logger.info("Validation error: %s %s -> %s", request.method, request.url.path, details)

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_error_envelope("VALIDATION_ERROR", "One or more fields failed validation.", details),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all for anything not deliberately raised as an AppError.
    Logs the full exception server-side (with stack trace) but returns
    only a generic message to the client — never leak internal error
    detail (stack traces, exception class names, DB error strings) to
    an API consumer.
    """
    logger.exception("Unhandled exception: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_error_envelope("INTERNAL_ERROR", "An unexpected error occurred."),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """
    Registers all three handlers against the FastAPI app instance.
    Called once from app/main.py during app construction:

        from app.core.exceptions import register_exception_handlers
        app = FastAPI(...)
        register_exception_handlers(app)
    """
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

"""Application-wide exception hierarchy and error envelope handler."""

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger

logger = get_logger(__name__)


class AppException(Exception):
    """Base for domain exceptions — carries no HTTP-specific concerns."""

    status_code: int = 500
    message: str = "Internal server error"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.message
        super().__init__(self.message)


class AdminAuthError(AppException):
    """Raised when the X-Admin-Key header is missing or doesn't match SSM."""

    status_code = 401
    message = "Invalid or missing admin key"


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    logger.error(
        exc.message,
        exc_info=exc.__cause__,
        extra={"path": request.url.path, "exception_type": type(exc).__name__},
    )
    return JSONResponse(status_code=exc.status_code, content={"error": exc.message})

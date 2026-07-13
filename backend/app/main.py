"""Application Factory and main Handler

Builds the application and delivers the factory to be used by
AWS Lambda via Mangum. This is the entry point for the application
when deployed.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mangum import Mangum

from app.core.exceptions import AppException, app_exception_handler
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.episodes.router import episodes_router
from app.shared.dynamodb import lifespan


settings = get_settings()
logger = get_logger(__name__)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled exception",
        exc_info=exc,
        extra={"path": request.url.path, "exception_type": type(exc).__name__},
    )
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="Backecast", version=settings.version, lifespan=lifespan)

    # Add CORS middleware to allow cross-origin requests
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Allow all origins for development; adjust for production
        allow_methods=["*"],  # Allow all HTTP methods
        allow_headers=["*"],  # Allow all headers
    )

    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    app.add_api_route(
        "/api/v1/health", lambda: {"status": "ok"}, methods=["GET"], tags=["Health"]
    )

    app.include_router(episodes_router)

    return app


handler = Mangum(create_app(), lifespan="on")

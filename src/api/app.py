"""FastAPI Application Factory.

See docs/architecture/02-foundation.md Section 7.1.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.api.responses import error
from src.api.routes import router
from src.core.errors import PlatformError


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Agent Platform",
        version="0.1.0",
        description="AI Agent Serving Platform",
    )

    # Register routes
    app.include_router(router)

    # Global error handler
    @app.exception_handler(PlatformError)
    async def platform_error_handler(request: Request, exc: PlatformError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error(exc.code, exc.message, details=exc.details),
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=error("INTERNAL_ERROR", str(exc)),
        )

    return app

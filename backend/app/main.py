"""SENTINEL-X OMEGA - FastAPI application entry point.

Run from the project root:

    uvicorn backend.app.main:app --reload

API docs: http://localhost:8000/docs   Dashboard: http://localhost:8000/
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.api.v1 import api_router
from backend.app.core.config import PROJECT_ROOT, Settings, get_settings
from backend.app.core.errors import AppError
from backend.app.core.logging import configure_logging
from backend.app.database.connection import init_db
from backend.app.services.detection_service import DetectionJobManager

logger = logging.getLogger("sentinel")

FRONTEND_DIR = PROJECT_ROOT / "frontend"


def _error(status: int, code: str, message: str, details=None, headers=None) -> JSONResponse:
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = jsonable_encoder(details)
    return JSONResponse(status_code=status, content=body, headers=headers)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_create_tables:
            init_db()
        settings.upload_path.mkdir(parents=True, exist_ok=True)
        logger.info("%s %s started (detector mode: %s)", settings.app_name, settings.app_version,
                    settings.detector_mode)
        yield
        app.state.job_manager.stop_all()
        logger.info("shutdown complete")

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Multi-hazard detection, risk assessment and incident management prototype. "
                    "Response actions are recommendations only; no emergency service is contacted.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.job_manager = DetectionJobManager(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return _error(exc.status_code, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        details = [{"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return _error(422, "VALIDATION_ERROR", "request validation failed", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 401: "NOT_AUTHENTICATED"}.get(exc.status_code,
                                                                                            f"HTTP_{exc.status_code}")
        return _error(exc.status_code, code, str(exc.detail), headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        logger.exception("unhandled error")
        return _error(500, "INTERNAL_ERROR", "an unexpected error occurred")

    app.include_router(api_router)

    if settings.serve_frontend and FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

    return app


app = create_app()

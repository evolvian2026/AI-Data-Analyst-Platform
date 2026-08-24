"""FastAPI application entry point."""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import routes_auth, routes_sessions, routes_system
from app.core.config import settings
from app.core.database import init_db
from app.engines.excel_parser import WorkbookError

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("app")

DESCRIPTION = """
Turn any Excel workbook into an AI data analyst: automatic profiling, data
quality scoring, KPI selection, trend and anomaly detection, ranked insights
with traceable evidence, a narrated Data Story, natural-language questions and
a professional PDF or Excel report.

**Every figure is calculated by the analytics engine.** Narration never invents
a number, and each finding carries the columns, calculation and record count
behind it.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    logger.info("started environment=%s storage=%s ai=%s",
                settings.environment, settings.storage_dir, settings.ai_provider)
    yield


app = FastAPI(
    title=settings.app_name,
    description=DESCRIPTION,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["Content-Disposition", "X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:  # noqa: BLE001 - converted to a clean 500 below
        logger.exception("unhandled error request_id=%s path=%s", request_id, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Something went wrong while processing the request.",
                     "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
    duration = (time.perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = request_id
    # Defensive headers: the API only ever returns JSON or a file download.
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if duration > 3000:
        logger.info("slow request %s %s %.0fms", request.method, request.url.path, duration)
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(p) for p in first.get("loc", [])[1:]) or "request"
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": f"{field}: {first.get('msg', 'is invalid')}",
                 "errors": exc.errors()[:10]},
    )


@app.exception_handler(WorkbookError)
async def workbook_error_handler(request: Request, exc: WorkbookError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": str(exc)})


app.include_router(routes_system.router, prefix=settings.api_prefix)
app.include_router(routes_auth.router, prefix=settings.api_prefix)
app.include_router(routes_sessions.router, prefix=settings.api_prefix)


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"name": settings.app_name, "docs": "/api/docs", "health": "/api/system/health"}

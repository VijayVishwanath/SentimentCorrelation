"""DEX Sentinel — FastAPI application entrypoint."""
from __future__ import annotations

import logging
import mimetypes
import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api import routes_admin, routes_ai, routes_analytics, routes_datasets, routes_remediation
from .api.deps import SafeJSONResponse, require_api_key
from .config import get_settings
from .data.store import init_store

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("dex_sentinel")


@asynccontextmanager
async def lifespan(_: FastAPI):
    t = time.perf_counter()
    init_store()
    from .copilot.retriever import get_kb
    get_kb()
    log.info("DEX Sentinel ready in %.2fs (env=%s)", time.perf_counter() - t, settings.environment)
    threading.Thread(target=_warm_cache, name="cache-warmup", daemon=True).start()
    yield


def _warm_cache() -> None:
    """Pre-compute the heaviest unfiltered views so the first dashboard load is instant."""
    from .api import routes_analytics as ra
    from .api.deps import Filters
    from .data.store import get_store
    from .engines import forecast, ml
    try:
        store, f = get_store(), Filters()
        ra.executive_dashboard(f, store)
        ra.outcome_report(None, None, store)
        ra.correlation_analysis(f, store, "frustration")
        ml.get_model(store)
        forecast.get_forecaster(store)  # predictive model: backtest + fit
        ra.roi_critical_few(f, store)  # Pareto view reuses the outcome report and forecaster above
        ra.command_center(f, store)  # landing page (also primes the outcome report behind Annual Benefits)
        log.info("cache warm-up complete")
    except Exception:
        log.exception("cache warm-up failed")


app = FastAPI(
    title="DEX Sentinel API",
    version=__version__,
    description="Outcome-based Digital Employee Experience analytics: sentiment x telemetry correlation, "
                "diagnosis assist, DEX Copilot and outcome reporting.",
    default_response_class=SafeJSONResponse,
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    start = time.perf_counter()
    # reject oversized uploads before the body is parsed
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and request.url.path.startswith("/api/") and \
            int(cl) > settings.max_upload_mb * settings.max_upload_files * 1024 * 1024 + 10 * 1024 * 1024:
        return SafeJSONResponse({"error": f"request too large (max {settings.max_upload_mb} MB per file)"}, status_code=413)
    try:
        response = await call_next(request)
    except Exception:
        log.exception("unhandled error rid=%s %s %s", rid, request.method, request.url.path)
        response = SafeJSONResponse({"error": "internal_error", "request_id": rid}, status_code=500)
    ms = (time.perf_counter() - start) * 1000
    response.headers["x-request-id"] = rid
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["x-frame-options"] = "DENY"
    response.headers["referrer-policy"] = "same-origin"
    if request.url.path.startswith("/api"):
        log.info("rid=%s %s %s -> %s %.0fms", rid, request.method, request.url.path, response.status_code, ms)
    return response


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return SafeJSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return SafeJSONResponse({"error": "validation_error", "details": exc.errors()}, status_code=422)


@app.get("/api/health", tags=["admin"])
def health():
    return {"status": "ok", "version": __version__}


secured = [Depends(require_api_key)]
app.include_router(routes_analytics.router, prefix="/api/v1", tags=["analytics"], dependencies=secured)
app.include_router(routes_ai.router, prefix="/api/v1", tags=["ai"], dependencies=secured)
app.include_router(routes_admin.router, prefix="/api/v1", tags=["admin"], dependencies=secured)
app.include_router(routes_datasets.router, prefix="/api/v1", tags=["datasets"], dependencies=secured)
app.include_router(routes_remediation.router, prefix="/api/v1", tags=["remediation"], dependencies=secured)

# ---- Serve the built React SPA (frontend/dist) from the same origin
# Windows registries often map .js to text/plain, which browsers reject for module scripts.
for _ext, _type in {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}.items():
    mimetypes.add_type(_type, _ext)
dist = settings.frontend_dist
if dist.exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return SafeJSONResponse({"error": f"unknown API route /{full_path}"}, status_code=404)
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")

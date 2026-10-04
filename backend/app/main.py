import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import (
    analytics, audit, auth, customers, dashboard, documents, employees, finance, health, inventory, library,
    monitoring, notifications, organizations, payments, products, purchases, reports, sales, security, service,
    suppliers,
)

settings = get_settings()
settings.validate_production()
logging.basicConfig(level=logging.INFO, format='{"t":"%(asctime)s","lvl":"%(levelname)s","msg":%(message)s}')
log = logging.getLogger("netcare")

def _notification_worker(stop: threading.Event) -> None:
    """Daily digests and email delivery, once a minute. One uvicorn worker is the supported setup; with more,
    digests are still not duplicated (dedupe keys) but emails could be picked up twice."""
    from .db import SessionLocal
    from .services.notify import sweep
    while not stop.wait(60):
        try:
            with SessionLocal() as db:
                sweep(db)
        except Exception:
            log.exception('"notification worker pass failed"')


@asynccontextmanager
async def lifespan(_app: FastAPI):
    stop = threading.Event()
    if settings.notifications_worker:
        threading.Thread(target=_notification_worker, args=(stop,), name="notifications", daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="NetCare Business Suite API", version="1.3.0", lifespan=lifespan,
              description="API v1. Send `Authorization: Bearer <token>` and `X-Organization-ID` headers.")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False,
                   allow_methods=["*"], allow_headers=["Authorization", "Content-Type", "X-Organization-ID"])


@app.middleware("http")
async def access_log(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    log.info('"%s %s %s %.1fms"', request.method, request.url.path, response.status_code,
             (time.perf_counter() - start) * 1000)
    return response


app.include_router(health.router)
for r in (auth, organizations, customers, products, inventory, suppliers, purchases, sales, payments, finance,
          reports, documents, library, analytics, monitoring, security, notifications, employees, service, dashboard, audit):
    app.include_router(r.router, prefix="/api/v1")

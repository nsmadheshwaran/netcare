import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import (
    analytics, audit, auth, customers, dashboard, documents, employees, finance, health, inventory, library,
    organizations, payments, products, purchases, reports, sales, service, suppliers,
)

settings = get_settings()
settings.validate_production()
logging.basicConfig(level=logging.INFO, format='{"t":"%(asctime)s","lvl":"%(levelname)s","msg":%(message)s}')
log = logging.getLogger("netcare")

app = FastAPI(title="NetCare Business Suite API", version="0.1.0",
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
          reports, documents, library, analytics, employees, service, dashboard, audit):
    app.include_router(r.router, prefix="/api/v1")

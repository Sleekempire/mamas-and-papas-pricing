"""
api/main.py — FastAPI application entrypoint.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
import os

from config import settings
from database.connection import init_db
from security.rate_limiter import limiter

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pricing_api")


# ── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s v%s (%s)", settings.APP_NAME, settings.APP_VERSION, settings.ENVIRONMENT)
    init_db()
    _seed_demo_data()
    yield
    logger.info("Shutting down %s", settings.APP_NAME)


def _seed_demo_data():
    """Seed a default admin user for development."""
    from database.connection import SessionLocal
    from database.models import User
    from security.auth import hash_password
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            users = [
                User(id="u-admin-001", email="admin@pricing.internal", hashed_password=hash_password("Admin123!"), role="Admin", is_active=True),
                User(id="u-analyst-001", email="analyst@pricing.internal", hashed_password=hash_password("Analyst123!"), role="Analyst", is_active=True),
                User(id="u-merch-001", email="merch@pricing.internal", hashed_password=hash_password("Merch123!"), role="Merchandiser", is_active=True),
                User(id="u-viewer-001", email="viewer@pricing.internal", hashed_password=hash_password("Viewer123!"), role="Viewer", is_active=True),
            ]
            for u in users:
                db.add(u)
            db.commit()
            logger.info("Seeded 4 demo users")
    finally:
        db.close()


# ── App creation ──────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/api/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/api/redoc" if settings.ENVIRONMENT != "production" else None,
    openapi_url="/api/openapi.json" if settings.ENVIRONMENT != "production" else None,
    lifespan=lifespan,
)

# ── Rate limiter state ────────────────────────────────────────────────────────
app.state.limiter = limiter

# ── Middleware ────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

if settings.ENVIRONMENT == "production":
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts_list)

# ── Exception handlers ────────────────────────────────────────────────────────
@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": "Rate limit exceeded. Please retry later."},
    )


@app.exception_handler(Exception)
async def _global_handler(request: Request, exc: Exception):
    # Never expose internal errors in production
    if settings.ENVIRONMENT == "production":
        logger.exception("Unhandled exception on %s", request.url)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An internal error occurred."},
        )
    raise exc


# ── Routers ───────────────────────────────────────────────────────────────────
from api.routers import auth, upload, training, optimisation, recommendations  # noqa: E402

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(upload.router, prefix="/api/v1", tags=["Data Ingestion"])
app.include_router(training.router, prefix="/api/v1", tags=["Model Training"])
app.include_router(optimisation.router, prefix="/api/v1", tags=["Optimisation"])
app.include_router(recommendations.router, prefix="/api/v1", tags=["Recommendations"])


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "version": settings.APP_VERSION, "env": settings.ENVIRONMENT}

# ── Serve Frontend ────────────────────────────────────────────────────────────
frontend_path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
else:
    logger.warning(f"Frontend directory not found at {frontend_path}. Static files will not be served.")

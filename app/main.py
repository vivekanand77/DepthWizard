"""
app/main.py
-----------
FastAPI application factory for the DepthWizard backend.

Startup sequence
----------------
1. Configure structured logging.
2. Initialise all SQLAlchemy table schemas in the configured database.
3. Register CORS middleware for the Next.js frontend.
4. Mount all API routers.

Adding a new router
-------------------
1. Create `app/routers/<name>.py` with an `APIRouter`.
2. Import it here and call `app.include_router(...)`.
"""

import logging
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine, Base

# --- Import models so SQLAlchemy registers them before create_all() ---
import app.models.user  # noqa: F401

# --- Import routers ---
from app.routers import auth, upload, infer, calibrate, export

# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
# Use a consistent format across all modules so logs are easy to grep.
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database initialisation
# ---------------------------------------------------------------------------
# create_all() is idempotent — it only creates tables that don't exist yet.
# For production use Alembic migrations instead of create_all().
Base.metadata.create_all(bind=engine)
logger.info("Database tables verified / created.")

# ---------------------------------------------------------------------------
# FastAPI application instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "**DepthWizard** — Monocular Elevation Estimation & Geospatial Processing API.\n\n"
        "Powered by Depth Anything V2 (ViT-B) for relative depth estimation, "
        "with absolute scale calibration via RANSAC against reference DEMs."
    ),
    version="1.0.0",
    # Swagger UI will show the Authorize button for JWT tokens
    openapi_tags=[
        {"name": "Authentication",       "description": "Register, login, and token management."},
        {"name": "Upload & Ingestion",   "description": "Upload GeoTIFF / image files and extract spatial metadata."},
        {"name": "Inference",            "description": "Trigger Depth Anything V2 disparity estimation (coming soon)."},
        {"name": "Calibration",          "description": "CSF ground filtering + RANSAC scale calibration (coming soon)."},
        {"name": "Export",               "description": "Download metric DSM GeoTIFF / 3-D mesh (coming soon)."},
        {"name": "Health Check",         "description": "Liveness and readiness probes."},
    ],
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

# CORS — allow the Next.js dev server (and production domain) to call the API.
# In production, replace "*" with the exact frontend origin, e.g.
# allow_origins=["https://depthwizard.ai", "https://www.depthwizard.ai"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(auth.router)      # /auth/register  /auth/login  /auth/me
app.include_router(upload.router)    # /api/v1/upload
app.include_router(infer.router)     # /api/v1/infer
app.include_router(calibrate.router) # /api/v1/calibrate
app.include_router(export.router)    # /api/v1/export

# ---------------------------------------------------------------------------
# Root health-check
# ---------------------------------------------------------------------------

@app.get("/", tags=["Health Check"], summary="API liveness probe")
def health_check():
    """
    Simple liveness probe.

    Returns basic info so operators can quickly verify the server is running
    and check which model variant is configured.
    """
    return {
        "status": "ok",
        "app_name": settings.APP_NAME,
        "version": "1.0.0",
        "model_variant": settings.DEPTH_MODEL_VARIANT,
        "debug": settings.DEBUG,
    }

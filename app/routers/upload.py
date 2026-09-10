"""
routers/upload.py
-----------------
Upload & Geospatial Ingestion Router — POST /api/v1/upload

This is the entry-point endpoint for the entire DepthWizard processing pipeline.

Flow
----
1. Client sends a multipart/form-data POST with the image file.
2. File bytes are validated and passed to gis_service.ingest_upload().
3. The GIS service extracts spatial metadata, slices tiles, and persists them.
4. A rich UploadResponse is returned with job_id, metadata, and tile manifest.
5. The frontend uses job_id in subsequent /infer and /calibrate calls.

Authentication
--------------
The endpoint is protected by the JWT bearer token dependency —
only registered users can upload files.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import JSONResponse

from app.models.user import User
from app.schemas.upload import UploadResponse
from app.services.auth import get_current_active_user
from app.services import gis_service

# ---------------------------------------------------------------------------
# Router setup
# ---------------------------------------------------------------------------

# All upload routes live under /api/v1/upload and are grouped in Swagger
# under the "Upload & Ingestion" tag.
router = APIRouter(prefix="/api/v1/upload", tags=["Upload & Ingestion"])

logger = logging.getLogger(__name__)

# Maximum accepted file size: 500 MB
# (Large satellite GeoTIFFs commonly exceed 100 MB; cap at a safe value)
MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024  # 500 MB


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a GeoTIFF or RGB image for processing",
    description=(
        "Upload a GeoTIFF, PNG, or JPEG file. "
        "The service validates the format, extracts geospatial metadata "
        "(CRS, bounding box, GSD), and slices the raster into 512×512 "
        "overlapping patches ready for depth inference.\n\n"
        "Returns a `job_id` to track subsequent `/infer` and `/calibrate` calls."
    ),
)
async def upload_image(
    file: UploadFile = File(
        ...,
        description="Raster file (GeoTIFF / PNG / JPEG) to ingest."
    ),
    current_user: User = Depends(get_current_active_user),  # JWT-protected
) -> UploadResponse:
    """
    Main upload handler.

    Parameters
    ----------
    file         : FastAPI UploadFile — the multipart file stream.
    current_user : User — injected by JWT dependency; ensures auth.

    Returns
    -------
    UploadResponse with job_id, metadata, and tile manifest.
    """
    logger.info(
        "Upload request from user %s: filename=%s, content_type=%s",
        current_user.email, file.filename, file.content_type
    )

    # --- Guard: filename must be present ---
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file has no filename."
        )

    # --- Read file bytes (streaming read to avoid OOM on huge files) ---
    try:
        file_bytes = await file.read()
    except Exception as exc:
        logger.error("Failed to read upload stream: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not read uploaded file: {exc}"
        )

    # --- Guard: enforce file size limit ---
    file_size = len(file_bytes)
    if file_size > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File too large ({file_size / 1024 / 1024:.1f} MB). "
                f"Maximum allowed is {MAX_FILE_SIZE_BYTES // 1024 // 1024} MB."
            )
        )

    # --- Guard: empty file ---
    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty."
        )

    # --- Delegate to GIS ingestion service ---
    try:
        job_id, file_type, metadata, tiles = gis_service.ingest_upload(
            file_bytes=file_bytes,
            filename=file.filename,
        )
    except ValueError as exc:
        # Validation errors (unsupported extension etc.)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc)
        )
    except RuntimeError as exc:
        # IO / rasterio errors
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc)
        )

    logger.info(
        "Ingestion complete: job_id=%s, %d tiles, georeferenced=%s",
        job_id, len(tiles), metadata.is_georeferenced
    )

    # Build and return the response
    return UploadResponse(
        job_id=job_id,
        filename=file.filename,
        file_type=file_type,
        metadata=metadata,
        tiles=tiles,
        tile_count=len(tiles),
        message=(
            f"Successfully ingested '{file.filename}' into {len(tiles)} tile(s). "
            f"Use job_id='{job_id}' to run inference."
        )
    )


@router.get(
    "/health",
    tags=["Health Check"],
    summary="Upload service health probe",
)
def upload_health():
    """
    Lightweight liveness probe for the upload service.
    Returns 200 OK if the router is reachable (no auth required).
    """
    return {"status": "ok", "service": "upload"}

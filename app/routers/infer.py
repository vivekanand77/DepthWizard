"""
routers/infer.py
-----------------
Depth Inference Router — POST /api/v1/infer

Triggers Depth Anything V2 (ViT-B) monocular depth estimation on all
512×512 tiles produced by a previous /upload call.

Flow
----
1. Client sends { job_id, model_variant?, input_size? } (JWT required).
2. We load the tile manifest from the job's upload directory.
3. depth_service.run_inference() runs the ViT model on every tile.
4. All per-tile disparity arrays are stitched into a single full-res map.
5. InferResponse is returned with job_id, tile stats, and output paths.
   The job_id is then passed to POST /api/v1/calibrate.
"""

import json
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import settings
from app.models.user import User
from app.schemas.infer import InferRequest, InferResponse
from app.schemas.upload import TileInfo
from app.services.auth import get_current_active_user
from app.services import depth_service

router = APIRouter(prefix="/api/v1/infer", tags=["Inference"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: load tile manifest written by the upload step
# ---------------------------------------------------------------------------

def _load_tile_manifest(job_id: str) -> dict:
    """
    Load the tile manifest JSON saved alongside the uploaded tiles.

    The manifest contains the full raster dimensions and TileInfo list needed
    to reconstruct the spatial layout during inference and stitching.

    Parameters
    ----------
    job_id : str  — Unique job identifier from the upload step.

    Returns
    -------
    dict  — Parsed manifest with keys: width, height, tiles.

    Raises
    ------
    HTTPException 404  — If the job directory or manifest file does not exist.
    """
    manifest_path = Path(settings.UPLOAD_DIR) / job_id / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Job '{job_id}' not found. "
                "Make sure you called POST /api/v1/upload first and used the returned job_id."
            )
        )
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=InferResponse,
    status_code=status.HTTP_200_OK,
    summary="Run Depth Anything V2 inference on an uploaded job",
    description=(
        "Triggers monocular depth estimation on all tiles from a previously uploaded image. "
        "Returns per-tile disparity statistics and the path to the stitched full-resolution "
        "disparity map. Pass the `job_id` to `/api/v1/calibrate` next.\n\n"
        "**Note:** First call loads model weights (~400 MB for ViT-B) — expect 10–30s on CPU."
    ),
)
def run_inference(
    request: InferRequest,
    current_user: User = Depends(get_current_active_user),  # JWT-protected
) -> InferResponse:
    """
    Main inference handler.

    Parameters
    ----------
    request      : InferRequest — Body with job_id, optional model_variant & input_size.
    current_user : User         — Injected by JWT dependency.

    Returns
    -------
    InferResponse with per-tile results, device info, timing, and output paths.
    """
    logger.info(
        "Inference request from user %s: job_id=%s variant=%s input_size=%d",
        current_user.email, request.job_id, request.model_variant, request.input_size
    )

    # --- Load the tile manifest saved during upload ---
    manifest = _load_tile_manifest(request.job_id)

    full_width  = manifest.get("width")
    full_height = manifest.get("height")
    raw_tiles   = manifest.get("tiles", [])

    if not raw_tiles:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No tiles found in manifest for job '{request.job_id}'."
        )

    # Reconstruct TileInfo objects from the manifest dict list
    tile_infos = [TileInfo(**t) for t in raw_tiles]
    logger.info("Loaded %d tiles for job %s (%dx%d)", len(tile_infos), request.job_id, full_width, full_height)

    # --- Run inference ---
    t0 = time.perf_counter()

    try:
        tile_results, stitched_path, actual_variant, device_str = depth_service.run_inference(
            job_id=request.job_id,
            tile_infos=tile_infos,
            full_width=full_width,
            full_height=full_height,
            model_variant=request.model_variant,
            input_size=request.input_size,
        )
    except FileNotFoundError as exc:
        # Model checkpoint not found
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc)
        )
    except Exception as exc:
        logger.exception("Inference failed for job %s: %s", request.job_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Inference failed: {exc}"
        )

    total_ms = (time.perf_counter() - t0) * 1000.0

    logger.info(
        "Inference complete for job %s: %d tiles in %.1f ms (device=%s)",
        request.job_id, len(tile_results), total_ms, device_str
    )

    return InferResponse(
        job_id=request.job_id,
        model_variant=actual_variant,
        device=device_str,
        tiles_processed=len(tile_results),
        total_ms=round(total_ms, 2),
        tile_results=tile_results,
        disparity_map_path=stitched_path,
        message=(
            f"Inference complete on {len(tile_results)} tile(s) using {actual_variant} "
            f"[{device_str}] in {total_ms / 1000:.2f}s. "
            f"Proceed with POST /api/v1/calibrate."
        )
    )


@router.get("/health", tags=["Health Check"], summary="Inference service health probe")
def infer_health():
    """Lightweight probe — no auth required."""
    return {"status": "ok", "service": "inference"}

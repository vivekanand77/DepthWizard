"""
routers/calibrate.py
--------------------
Absolute Scale Calibration Router — POST /api/v1/calibrate

Transforms dimensionless relative disparity maps from Depth Anything V2
into metric elevation models (Digital Surface Models / DSM in metres above datum)
using Cloth Simulation Filtering (CSF) and RANSAC linear fitting:
    d_metric = s · D_rel + t

Flow
----
1. Client sends { job_id, gcps?, csf_*, ransac_* } (JWT required).
2. We load the stitched relative disparity map and manifest for the job.
3. calibration_service.calibrate_disparity_map() runs CSF ground filtering and RANSAC.
4. Metric DSM .npy and optional georeferenced GeoTIFF are saved to disk.
5. CalibrateResponse returns scale factor s, translation shift t, accuracy metrics
   (RMSE, MAE, LE90), and output paths.
"""

import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import settings
from app.models.user import User
from app.schemas.calibrate import CalibrateRequest, CalibrateResponse
from app.services.auth import get_current_active_user
from app.services import calibration_service

router = APIRouter(prefix="/api/v1/calibrate", tags=["Calibration"])
logger = logging.getLogger(__name__)


@router.post(
    "",
    response_model=CalibrateResponse,
    status_code=status.HTTP_200_OK,
    summary="Calibrate relative disparity to metric Digital Surface Model (DSM)",
    description=(
        "Converts dimensionless disparity into true metric elevations in metres "
        "using Cloth Simulation Filtering (CSF) and RANSAC scale fitting ($d = s \\cdot D + t$).\n\n"
        "- If Ground Control Points (GCPs) are supplied, RANSAC fits directly against surveyed markers.\n"
        "- If no GCPs are supplied, CSF isolates ground points and fits a standardized terrain plane.\n"
        "- Returns ASPRS/NGA standard photogrammetric accuracy metrics: RMSE, MAE, and LE90."
    ),
)
def calibrate_scale(
    request: CalibrateRequest,
    current_user: User = Depends(get_current_active_user),  # JWT-protected
) -> CalibrateResponse:
    """
    Main scale calibration endpoint.

    Parameters
    ----------
    request      : CalibrateRequest — Job ID, optional GCPs, CSF & RANSAC hyperparameters.
    current_user : User             — Authenticated user from JWT bearer token.

    Returns
    -------
    CalibrateResponse containing scale parameters, RMSE/MAE/LE90 metrics, and file paths.
    """
    logger.info(
        "Calibration request from user %s for job %s (GCP count=%d)",
        current_user.email, request.job_id, len(request.gcps)
    )

    # Verify that the job upload folder exists
    job_upload_dir = Path(settings.UPLOAD_DIR) / request.job_id
    if not job_upload_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{request.job_id}' not found in upload storage. Please call POST /api/v1/upload first."
        )

    # Check for stitched disparity map
    job_output_dir = Path(settings.OUTPUT_DIR) / request.job_id
    possible_disp = [
        job_output_dir / "disparity_full.npy",
        job_output_dir / "disparity_stitched.npy",
        job_upload_dir / "disparity_full.npy",
        job_upload_dir / "disparity_stitched.npy",
    ]
    if not any(p.exists() for p in possible_disp):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Disparity map for job '{request.job_id}' not found. "
                "Make sure you called POST /api/v1/infer before calibrating."
            )
        )

    try:
        (
            scale_s,
            shift_t,
            metrics,
            dsm_npy_path,
            dsm_geotiff_path,
            elapsed_ms,
        ) = calibration_service.calibrate_disparity_map(
            job_id=request.job_id,
            gcps=request.gcps,
            csf_cloth_resolution=request.csf_cloth_resolution,
            csf_max_iterations=request.csf_max_iterations,
            csf_class_threshold=request.csf_class_threshold,
            ransac_max_trials=request.ransac_max_trials,
            ransac_residual_threshold=request.ransac_residual_threshold,
            ransac_min_samples=request.ransac_min_samples,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc)
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc)
        )
    except Exception as exc:
        logger.exception("Calibration failed for job %s: %s", request.job_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Calibration engine failure: {exc}"
        )

    gcp_desc = f"{len(request.gcps)} GCP(s)" if request.gcps else "CSF ground simulation"
    summary_msg = (
        f"Calibration succeeded in {elapsed_ms:.1f} ms using {gcp_desc}. "
        f"Fitted d_metric = {scale_s:.3f} · D_rel + {shift_t:.3f} m (RMSE: {metrics.rmse_metres} m, LE90: {metrics.le90_metres} m)."
    )

    return CalibrateResponse(
        job_id=request.job_id,
        scale_factor_s=round(scale_s, 6),
        shift_translation_t=round(shift_t, 6),
        metrics=metrics,
        dsm_npy_path=dsm_npy_path,
        dsm_geotiff_path=dsm_geotiff_path,
        calibration_ms=round(elapsed_ms, 2),
        message=summary_msg,
    )


@router.get("/health", tags=["Health Check"], summary="Calibration service health probe")
def calibrate_health():
    """Lightweight health probe — no auth required."""
    return {"status": "ok", "service": "calibration"}

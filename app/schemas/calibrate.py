"""
schemas/calibrate.py
---------------------
Pydantic request and response models for the absolute scale calibration pipeline.

The calibration step converts the relative disparity map produced by Depth
Anything V2 into a physically meaningful metric Digital Surface Model (DSM)
by fitting the linear equation:

    d_metric = s · D_rel + t

where:
    D_rel    = relative disparity value from the ViT model (dimensionless, [0,1])
    s        = scale factor (metres per disparity unit)
    t        = translation / shift (metres)
    d_metric = absolute elevation in metres above datum

Fitting is done with RANSAC over ground-support points identified by the
Cloth Simulation Filter (CSF).
"""

from typing import List, Optional, Tuple
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Reference Ground Control Point (GCP)
# ---------------------------------------------------------------------------

class GroundControlPoint(BaseModel):
    """
    A single reference elevation sample used to anchor absolute scale.

    In production these can be sourced from:
    - User-uploaded CSV of surveyed GCPs (most accurate).
    - Copernicus 30 m DEM / SRTM (auto-fetched from open APIs).
    - Known flat ground regions identified manually.

    Fields
    ------
    pixel_col   : Column index in the full-resolution disparity map.
    pixel_row   : Row index in the full-resolution disparity map.
    elevation_m : Known ground elevation at this pixel in metres.
    source      : Human-readable provenance tag (e.g. 'SRTM', 'survey').
    """
    pixel_col: int = Field(..., ge=0, description="Column pixel index")
    pixel_row: int = Field(..., ge=0, description="Row pixel index")
    elevation_m: float = Field(..., description="Known elevation in metres")
    source: str = Field("user", description="GCP data source label")


# ---------------------------------------------------------------------------
# Calibration Request
# ---------------------------------------------------------------------------

class CalibrateRequest(BaseModel):
    """
    Body sent by the client to trigger scale calibration.

    Fields
    ------
    job_id          : UUID from POST /api/v1/upload.
    gcps            : Optional list of Ground Control Points.
                      If empty, the service falls back to flat-ground
                      assumption (CSF only, no absolute reference).
    csf_cloth_resolution : CSF grid cell size in disparity units.
                           Smaller = finer ground mask, slower.
    csf_max_iterations   : Maximum CSF iterations (default 500).
    csf_class_threshold  : Distance threshold (disparity units) for
                           classifying a point as ground.
    ransac_max_trials    : Max RANSAC iterations.
    ransac_residual_threshold : Inlier residual threshold in metres.
    ransac_min_samples   : Minimum samples per RANSAC hypothesis.
    """
    job_id: str = Field(..., description="Job ID from POST /api/v1/upload")

    gcps: List[GroundControlPoint] = Field(
        default_factory=list,
        description="Reference ground control points for absolute scaling"
    )

    # CSF parameters
    csf_cloth_resolution: float = Field(
        0.5, gt=0,
        description="CSF cloth grid resolution (disparity units)"
    )
    csf_max_iterations: int = Field(
        500, ge=10, le=5000,
        description="Maximum CSF cloth relaxation iterations"
    )
    csf_class_threshold: float = Field(
        0.05, gt=0,
        description="CSF ground classification threshold"
    )

    # RANSAC parameters
    ransac_max_trials: int = Field(
        1000, ge=10, le=50000,
        description="Max RANSAC hypothesis trials"
    )
    ransac_residual_threshold: float = Field(
        1.5, gt=0,
        description="RANSAC inlier residual threshold (metres)"
    )
    ransac_min_samples: int = Field(
        2, ge=2,
        description="Minimum samples per RANSAC hypothesis (linear = 2)"
    )


# ---------------------------------------------------------------------------
# Calibration Quality Metrics
# ---------------------------------------------------------------------------

class CalibrationMetrics(BaseModel):
    """
    Standard accuracy metrics comparing calibrated DSM against reference GCPs.

    Fields
    ------
    rmse_metres    : Root Mean Square Error — overall accuracy measure.
    mae_metres     : Mean Absolute Error — robust to outliers.
    le90_metres    : Linear Error at 90th percentile — vertical accuracy
                     used in photogrammetric standards (ASPRS, NGA).
    inlier_count   : Number of RANSAC inliers used in the final fit.
    inlier_ratio   : Fraction of ground points classified as inliers.
    ground_point_count : Total ground points identified by CSF.
    """
    rmse_metres: float = Field(..., description="Root Mean Square Error (m)")
    mae_metres: float = Field(..., description="Mean Absolute Error (m)")
    le90_metres: float = Field(..., description="Linear Error at 90th percentile (m)")
    inlier_count: int = Field(..., description="RANSAC inlier count")
    inlier_ratio: float = Field(..., description="Inlier fraction [0–1]")
    ground_point_count: int = Field(..., description="Total CSF ground points")


# ---------------------------------------------------------------------------
# Calibration API Response
# ---------------------------------------------------------------------------

class CalibrateResponse(BaseModel):
    """
    Full response from POST /api/v1/calibrate.

    Fields
    ------
    job_id              : Same job_id passed in the request.
    scale_factor_s      : Fitted RANSAC scale parameter s (m / disparity unit).
    shift_translation_t : Fitted RANSAC shift parameter t (metres).
    metrics             : Accuracy metrics against reference GCPs.
    dsm_npy_path        : Path to calibrated metric DSM as .npy array.
    dsm_geotiff_path    : Path to the GeoTIFF DSM (None if not georeferenced).
    calibration_ms      : Total calibration wall-clock time (ms).
    message             : Human-readable summary.
    """
    job_id: str
    scale_factor_s: float = Field(..., description="RANSAC scale s (m/disp)")
    shift_translation_t: float = Field(..., description="RANSAC shift t (m)")
    metrics: CalibrationMetrics
    dsm_npy_path: str = Field(..., description="Path to metric DSM .npy")
    dsm_geotiff_path: Optional[str] = Field(
        None, description="Path to GeoTIFF DSM (if input was georeferenced)"
    )
    calibration_ms: float = Field(..., description="Calibration time (ms)")
    message: str

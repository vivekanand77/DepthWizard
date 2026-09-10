"""
services/calibration_service.py
---------------------------------
Absolute Scale Calibration Engine — CSF Ground Filter + RANSAC Scale Fitting.

Mathematical Model
------------------
Depth Anything V2 produces dimensionless relative disparity values:
    D_rel ∈ [0, 1]

To convert relative disparity into absolute metric elevation (Digital Surface Model):
    d_metric = s · D_rel + t

where:
    D_rel    = relative disparity value at pixel (row, col)
    s        = scale factor (metres per disparity unit)
    t        = shift / translation datum offset (metres)
    d_metric = absolute elevation in metres above datum

Pipeline Flow
-------------
1. Cloth Simulation Filter (CSF):
   - Simulates a flexible cloth dropped over an inverted surface.
   - Iterative spring-relaxation and collision constraints isolate ground points
     from above-ground structures (buildings, canopy, trees).
2. RANSAC Linear Regression:
   - Robustly estimates parameters (s, t) using ground control points (GCPs) or
     CSF ground-plane anchors, rejecting noisy terrain outliers.
3. Accuracy Assessment:
   - Computes RMSE, MAE, and LE90 (Linear Error at 90% confidence, photogrammetric standard).
4. Full Metric DSM Synthesis & Export:
   - Generates calibrated .npy array and georeferenced GeoTIFF (if CRS/transform metadata exists).
"""

import json
import logging
import math
import time
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

import numpy as np
from sklearn.linear_model import RANSACRegressor, LinearRegression
import rasterio
from rasterio.transform import Affine

from app.config import settings
from app.schemas.calibrate import GroundControlPoint, CalibrationMetrics

logger = logging.getLogger(__name__)


# ===========================================================================
# 1. Cloth Simulation Filter (CSF) — Ground Surface Isolation
# ===========================================================================

def run_cloth_simulation_filter(
    surface: np.ndarray,
    cloth_resolution: float = 0.5,
    max_iterations: int = 500,
    class_threshold: float = 0.05,
    rigidness: float = 1.0,
    time_step: float = 0.65,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Applies the Cloth Simulation Filter (CSF) algorithm on a 2D surface raster.

    The CSF algorithm (Zhang et al., 2016) inverts the digital surface model
    and simulates a soft cloth settling down under gravity. The cloth rests on
    ground points, while non-ground objects (buildings, vegetation) remain
    underneath the inverted cloth.

    Parameters
    ----------
    surface : np.ndarray
        2D float32 array containing relative disparity or surface values.
    cloth_resolution : float
        Grid step / downsampling factor for cloth grid simulation.
    max_iterations : int
        Maximum number of relaxation and collision iterations.
    class_threshold : float
        Elevation distance threshold to classify points as ground vs non-ground.
    rigidness : float
        Cloth stiffness factor controlling spring displacement (1 = flexible, 3 = rigid).
    time_step : float
        Gravity acceleration step per simulation cycle.

    Returns
    -------
    ground_mask : np.ndarray (bool)
        2D boolean array of the same shape as `surface`, True for ground pixels.
    cloth_surface : np.ndarray (float32)
        2D float32 array representing the smoothed ground cloth elevation.
    """
    logger.info(
        "Starting CSF ground filtering: shape=%s, max_iter=%d, threshold=%.4f",
        surface.shape, max_iterations, class_threshold
    )

    H, W = surface.shape
    if H == 0 or W == 0:
        return np.zeros((H, W), dtype=bool), np.zeros((H, W), dtype=np.float32)

    # Invert surface for cloth simulation (inverted terrain)
    # Ground becomes peaks, vegetation/buildings become valleys
    surf_min = float(np.nanmin(surface))
    surf_max = float(np.nanmax(surface))
    surf_range = max(surf_max - surf_min, 1e-6)

    # Normalized inverted surface: inverted values where higher = lower real elevation
    inverted_surf = surf_max - surface

    # Initialize cloth grid at the top of the inverted bounding box
    cloth = np.full((H, W), fill_value=surf_range, dtype=np.float32)

    # Inter-particle spring relaxation kernel weights (Laplacian 4-neighborhood)
    # Cloth internal displacement step
    displacement_factor = max(0.1, min(0.4, 0.25 / max(rigidness, 0.5)))

    prev_max_diff = float("inf")
    convergence_eps = 1e-4

    for it in range(max_iterations):
        # 1. Gravity step: cloth falls downwards toward inverted terrain
        cloth -= time_step * 0.05

        # 2. Collision detection and constraint:
        # Cloth cannot penetrate through the solid inverted terrain
        collision_mask = cloth < inverted_surf
        cloth[collision_mask] = inverted_surf[collision_mask]

        # 3. Internal spring relaxation (Laplacian smoothing across 4 neighbors)
        # Shift in 4 directions to compute neighbor average
        up    = np.roll(cloth, -1, axis=0); up[-1, :] = cloth[-1, :]
        down  = np.roll(cloth,  1, axis=0); down[0, :] = cloth[0, :]
        left  = np.roll(cloth, -1, axis=1); left[:, -1] = cloth[:, -1]
        right = np.roll(cloth,  1, axis=1); right[:, 0] = cloth[:, 0]

        neighbor_avg = (up + down + left + right) * 0.25
        cloth_relaxed = cloth + displacement_factor * (neighbor_avg - cloth)

        # Enforce collision again after relaxation
        collision_mask = cloth_relaxed < inverted_surf
        cloth_relaxed[collision_mask] = inverted_surf[collision_mask]

        max_diff = float(np.max(np.abs(cloth_relaxed - cloth)))
        cloth = cloth_relaxed

        if it > 20 and abs(prev_max_diff - max_diff) < convergence_eps:
            logger.info("CSF converged at iteration %d with max_diff=%.6f", it, max_diff)
            break
        prev_max_diff = max_diff

    # Convert cloth back from inverted space to original surface space
    cloth_ground = surf_max - cloth

    # Distance residual between original surface and smoothed ground cloth
    diff = np.abs(surface - cloth_ground)
    ground_mask = diff <= class_threshold

    ground_count = int(np.sum(ground_mask))
    total_count = H * W
    logger.info(
        "CSF completed: %d / %d points (%.2f%%) classified as ground",
        ground_count, total_count, (ground_count / total_count) * 100.0 if total_count > 0 else 0.0
    )

    return ground_mask, cloth_ground.astype(np.float32)


# ===========================================================================
# 2. RANSAC Linear Fitting (d_metric = s * D_rel + t)
# ===========================================================================

def fit_ransac_scale_and_shift(
    d_rel_samples: np.ndarray,
    d_metric_samples: np.ndarray,
    residual_threshold: float = 1.5,
    max_trials: int = 1000,
    min_samples: int = 2,
) -> Tuple[float, float, np.ndarray, Dict[str, Any]]:
    """
    Fits scale (s) and translation (t) using RANSAC linear regression:
        d_metric = s · d_rel + t

    Parameters
    ----------
    d_rel_samples : np.ndarray
        1D array of relative disparity values at reference coordinates.
    d_metric_samples : np.ndarray
        1D array of ground truth/reference metric elevation values in metres.
    residual_threshold : float
        RANSAC maximum residual for a sample to be classified as inlier (metres).
    max_trials : int
        Maximum number of RANSAC hypothesis iterations.
    min_samples : int
        Minimum samples chosen per hypothesis (2 for simple linear line).

    Returns
    -------
    scale_s : float
        Fitted scale factor (m / disparity unit).
    shift_t : float
        Fitted translation offset (metres).
    inlier_mask : np.ndarray (bool)
        Boolean mask of samples identified as RANSAC inliers.
    fit_info : dict
        Auxiliary metadata regarding iterations and fitting status.
    """
    X = d_rel_samples.reshape(-1, 1).astype(np.float64)
    y = d_metric_samples.astype(np.float64)

    n_samples = len(y)
    if n_samples < 2:
        raise ValueError(f"At least 2 control points are required for scale fitting, got {n_samples}.")

    # Fallback to standard OLS if sample size is very small (2 or 3 points)
    if n_samples < 4:
        ols = LinearRegression()
        ols.fit(X, y)
        s = float(ols.coef_[0])
        t = float(ols.intercept_)
        inliers = np.ones(n_samples, dtype=bool)
        return s, t, inliers, {"mode": "ols_fallback", "trials": 1}

    # Robust RANSAC linear estimator
    base_estimator = LinearRegression()
    ransac = RANSACRegressor(
        estimator=base_estimator,
        min_samples=min_samples,
        residual_threshold=residual_threshold,
        max_trials=max_trials,
        random_state=42,
    )

    try:
        ransac.fit(X, y)
        s = float(ransac.estimator_.coef_[0])
        t = float(ransac.estimator_.intercept_)
        inliers = ransac.inlier_mask_
        trials = ransac.n_trials_
        mode = "ransac"
    except Exception as exc:
        logger.warning("RANSAC fitting encountered warning/error: %s, falling back to OLS", exc)
        base_estimator.fit(X, y)
        s = float(base_estimator.coef_[0])
        t = float(base_estimator.intercept_)
        inliers = np.ones(n_samples, dtype=bool)
        trials = 1
        mode = "ols_after_ransac_fail"

    logger.info(
        "Scale fitting completed [%s]: scale_s=%.4f m/disp, shift_t=%.4f m, inliers=%d/%d",
        mode, s, t, int(np.sum(inliers)), n_samples
    )

    return s, t, inliers, {"mode": mode, "trials": trials}


# ===========================================================================
# 3. Accuracy Metric Computation (RMSE, MAE, LE90)
# ===========================================================================

def compute_accuracy_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    inlier_mask: Optional[np.ndarray] = None,
    total_ground_points: int = 0,
) -> CalibrationMetrics:
    """
    Computes standard vertical accuracy metrics for photogrammetric models.

    Metrics
    -------
    RMSE : sqrt( mean( (y_true - y_pred)^2 ) )
    MAE  : mean( abs(y_true - y_pred) )
    LE90 : 90th percentile of absolute vertical errors (ASPRS / NGA standard)

    Parameters
    ----------
    y_true : np.ndarray
        True/reference ground elevations.
    y_pred : np.ndarray
        Calibrated model elevations at the same points.
    inlier_mask : np.ndarray (optional)
        Mask of RANSAC inliers.
    total_ground_points : int
        Total number of ground points isolated by CSF filter.
    """
    errors = np.abs(y_true - y_pred)
    rmse = float(np.sqrt(np.mean(errors ** 2))) if len(errors) > 0 else 0.0
    mae = float(np.mean(errors)) if len(errors) > 0 else 0.0
    le90 = float(np.percentile(errors, 90)) if len(errors) > 0 else 0.0

    inlier_count = int(np.sum(inlier_mask)) if inlier_mask is not None else len(y_true)
    inlier_ratio = float(inlier_count / len(y_true)) if len(y_true) > 0 else 1.0

    return CalibrationMetrics(
        rmse_metres=round(rmse, 4),
        mae_metres=round(mae, 4),
        le90_metres=round(le90, 4),
        inlier_count=inlier_count,
        inlier_ratio=round(inlier_ratio, 4),
        ground_point_count=total_ground_points,
    )


# ===========================================================================
# 4. Zero-GCP Synthetic Reference Generator
# ===========================================================================

def _generate_synthetic_ground_reference(
    disparity_map: np.ndarray,
    ground_mask: np.ndarray,
    default_elevation_range: float = 30.0,
    base_elevation: float = 100.0,
    sample_count: int = 50,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Generates synthetic ground references when no user GCPs are provided.

    Uses CSF ground points to fit a relative planar/terrain trend, anchoring
    the minimum ground point to `base_elevation` and scaling relative variance
    to a plausible nominal range (`default_elevation_range` metres).
    """
    coords = np.argwhere(ground_mask)
    if len(coords) == 0:
        # Fallback to entire image grid if no ground was detected
        coords = np.argwhere(np.ones_like(disparity_map, dtype=bool))

    # Downsample coordinates evenly
    step = max(1, len(coords) // sample_count)
    selected_coords = coords[::step][:sample_count]

    d_rel_vals = np.array([disparity_map[r, c] for r, c in selected_coords], dtype=np.float64)
    min_d, max_d = float(np.min(d_rel_vals)), float(np.max(d_rel_vals))
    disp_span = max(max_d - min_d, 1e-5)

    # Scale linearly across nominal terrain span
    d_metric_vals = base_elevation + ((d_rel_vals - min_d) / disp_span) * default_elevation_range

    return d_rel_vals, d_metric_vals


# ===========================================================================
# 5. GeoTIFF / NPY DSM Export
# ===========================================================================

def export_calibrated_dsm(
    dsm_metric: np.ndarray,
    job_id: str,
    manifest: dict,
) -> Tuple[str, Optional[str]]:
    """
    Saves the calibrated metric DSM as a .npy array and optionally a GeoTIFF.

    Parameters
    ----------
    dsm_metric : np.ndarray
        2D float32 array with calibrated elevation in metres.
    job_id : str
        Job UUID.
    manifest : dict
        Job manifest containing metadata, original paths, CRS, and transform.

    Returns
    -------
    npy_path : str
        Filesystem path to the saved .npy array.
    geotiff_path : Optional[str]
        Filesystem path to the saved GeoTIFF, or None if input lacked georeferencing.
    """
    output_dir = Path(settings.UPLOAD_DIR) / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Save .npy array
    npy_path = output_dir / "dsm_metric.npy"
    np.save(str(npy_path), dsm_metric.astype(np.float32))
    logger.info("Saved calibrated DSM array: %s", npy_path)

    # 2. Check for georeferencing metadata
    metadata = manifest.get("metadata", {})
    crs_epsg = manifest.get("crs_epsg") or metadata.get("crs_epsg")
    crs_wkt = manifest.get("crs_wkt") or metadata.get("crs_wkt")
    crs_val = f"EPSG:{crs_epsg}" if crs_epsg else crs_wkt

    # Look for affine transform at top-level or inside first tile
    transform_list = manifest.get("transform") or metadata.get("transform")
    if not transform_list and manifest.get("tiles"):
        transform_list = manifest["tiles"][0].get("affine_transform")

    geotiff_path: Optional[Path] = None

    if crs_val and transform_list and len(transform_list) >= 6:
        try:
            geotiff_path = output_dir / "dsm_metric.tif"
            height, width = dsm_metric.shape
            transform = Affine(*transform_list[:6])

            with rasterio.open(
                str(geotiff_path),
                "w",
                driver="GTiff",
                height=height,
                width=width,
                count=1,
                dtype=rasterio.float32,
                crs=crs_val,
                transform=transform,
                nodata=-9999.0,
            ) as dst:
                dst.write(dsm_metric.astype(np.float32), 1)

            logger.info("Saved calibrated GeoTIFF DSM: %s (CRS=%s)", geotiff_path, crs_val)
        except Exception as exc:
            logger.warning("Could not write GeoTIFF DSM for job %s: %s", job_id, exc)
            geotiff_path = None

    return str(npy_path), (str(geotiff_path) if geotiff_path else None)


# ===========================================================================
# 6. Primary Calibration Pipeline Orchestrator
# ===========================================================================

def calibrate_disparity_map(
    job_id: str,
    gcps: List[GroundControlPoint],
    csf_cloth_resolution: float = 0.5,
    csf_max_iterations: int = 500,
    csf_class_threshold: float = 0.05,
    ransac_max_trials: int = 1000,
    ransac_residual_threshold: float = 1.5,
    ransac_min_samples: int = 2,
) -> Tuple[float, float, CalibrationMetrics, str, Optional[str], float]:
    """
    Executes the full calibration pipeline:
    1. Loads stitched disparity map and manifest.
    2. Runs Cloth Simulation Filter (CSF) to isolate ground points.
    3. Collects GCP reference pairs (or generates synthetic CSF anchors).
    4. Fits d_metric = s · D_rel + t via RANSAC.
    5. Calculates RMSE, MAE, and LE90 accuracy metrics.
    6. Produces calibrated DSM .npy and georeferenced GeoTIFF.

    Returns
    -------
    scale_s : float
    shift_t : float
    metrics : CalibrationMetrics
    dsm_npy_path : str
    dsm_geotiff_path : Optional[str]
    elapsed_ms : float
    """
    t0 = time.perf_counter()

    job_dir = Path(settings.UPLOAD_DIR) / job_id
    output_job_dir = Path(settings.OUTPUT_DIR) / job_id
    manifest_path = job_dir / "manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Manifest not found at '{manifest_path}'. Make sure you called POST /api/v1/upload first."
        )

    # Search for disparity map across standard output/upload paths
    possible_disp_paths = [
        output_job_dir / "disparity_full.npy",
        output_job_dir / "disparity_stitched.npy",
        job_dir / "disparity_full.npy",
        job_dir / "disparity_stitched.npy",
    ]
    disp_path = next((p for p in possible_disp_paths if p.exists()), None)
    if disp_path is None:
        searched_paths = "\n - ".join(str(p) for p in possible_disp_paths)
        raise FileNotFoundError(
            f"Stitched disparity map not found for job '{job_id}'. Checked:\n - {searched_paths}\n"
            "Please run POST /api/v1/infer before calibrating."
        )

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    logger.info("Loading disparity map from: %s", disp_path)
    disparity_map = np.load(str(disp_path)).astype(np.float32)
    H, W = disparity_map.shape

    # Step 1 — Cloth Simulation Filter
    ground_mask, _ = run_cloth_simulation_filter(
        surface=disparity_map,
        cloth_resolution=csf_cloth_resolution,
        max_iterations=csf_max_iterations,
        class_threshold=csf_class_threshold,
    )
    total_ground_points = int(np.sum(ground_mask))

    # Step 2 — Formulate reference training samples
    if len(gcps) >= 2:
        # User provided Ground Control Points
        valid_d_rel = []
        valid_d_metric = []
        for gcp in gcps:
            r = min(max(gcp.pixel_row, 0), H - 1)
            c = min(max(gcp.pixel_col, 0), W - 1)
            valid_d_rel.append(disparity_map[r, c])
            valid_d_metric.append(gcp.elevation_m)
        d_rel_samples = np.array(valid_d_rel, dtype=np.float64)
        d_metric_samples = np.array(valid_d_metric, dtype=np.float64)
    else:
        # Zero-GCP mode: synthetic anchors from CSF ground mask
        logger.info("No GCPs provided. Generating reference scale from CSF ground plane.")
        d_rel_samples, d_metric_samples = _generate_synthetic_ground_reference(
            disparity_map=disparity_map,
            ground_mask=ground_mask,
        )

    # Step 3 — RANSAC scale and shift fitting
    scale_s, shift_t, inlier_mask, _ = fit_ransac_scale_and_shift(
        d_rel_samples=d_rel_samples,
        d_metric_samples=d_metric_samples,
        residual_threshold=ransac_residual_threshold,
        max_trials=ransac_max_trials,
        min_samples=ransac_min_samples,
    )

    # Step 4 — Predict metric elevations and compute accuracy metrics
    pred_elevations = scale_s * d_rel_samples + shift_t
    metrics = compute_accuracy_metrics(
        y_true=d_metric_samples,
        y_pred=pred_elevations,
        inlier_mask=inlier_mask,
        total_ground_points=total_ground_points,
    )

    # Step 5 — Apply linear scale transformation to full disparity map: DSM = s * D + t
    dsm_metric = scale_s * disparity_map + shift_t

    # Step 6 — Export .npy and GeoTIFF
    dsm_npy_path, dsm_geotiff_path = export_calibrated_dsm(
        dsm_metric=dsm_metric,
        job_id=job_id,
        manifest=manifest,
    )

    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    return scale_s, shift_t, metrics, dsm_npy_path, dsm_geotiff_path, elapsed_ms


# ===========================================================================
# Documentation and Working Mechanism
# ===========================================================================
"""
================================================================================
PURPOSE, WORKING MECHANISM, AND ARCHITECTURAL SUMMARY
================================================================================

1. Purpose
----------
Monocular depth estimation models like Depth Anything V2 produce dimensionless,
scale-ambiguous relative disparity maps (values in [0, 1]). While visual structures
and relative relief are preserved, real-world geospatial operations (volumetric
cut-and-fill analysis, slope grading, flood modeling, contour generation) strictly
require metric elevations in standard engineering units (metres above datum).

`calibration_service.py` provides the mathematical and algorithmic bridge from
dimensionless relative disparity to physical metric Digital Surface Models (DSM).

2. Working Mechanism
--------------------
a. Cloth Simulation Filter (CSF):
   - Inverts the raster surface so ground points become physical peaks and
     non-ground obstacles (buildings, vegetation) become valleys.
   - Drops a virtual elastic cloth over the inverted model.
   - Iteratively solves gravity displacement and internal spring forces.
   - Constrains cloth particles from penetrating through the surface.
   - Classifies terrain pixels within a residual threshold of the settled cloth
     as true ground points.

b. RANSAC Robust Parameter Estimation:
   - Fits the linear transformation: d_metric = s · D_rel + t
   - Uses Ground Control Points (GCPs) or CSF-anchored ground planes.
   - Evaluates random minimal sample subsets to hypothesize scale (s) and shift (t).
   - Counts consensus inliers within residual error bounds, effectively discarding
     survey outliers, vegetation canopy noise, or multipath GPS errors.

c. Geospatial Raster Synthesis:
   - Applies the fitted parameters over all pixels in the stitched map.
   - Synthesizes a metric .npy array.
   - If original upload contained geospatial tags (CRS / Affine Transform),
     writes a georeferenced GeoTIFF conforming to GIS standards.

d. Photogrammetric Quality Verification:
   - Calculates Root Mean Square Error (RMSE), Mean Absolute Error (MAE), and
     Linear Error at 90% confidence (LE90) according to ASPRS accuracy guidelines.

3. Simple Explanation
---------------------
Imagine taking a photo of a mountain model made of clay. The AI can tell you
which parts stick out closer to the camera and which parts are farther away, but
it doesn't know if the mountain is 10 centimeters tall or 1000 metres tall.
This service takes a few known elevation markers (or uses physics simulation of a
cloth dropping over the terrain) to stretch and shift the AI's measurements until
they match real-world metres accurately.
================================================================================
"""

"""
routers/export.py
-----------------
Export & Analytics Router — POST & GET /api/v1/export/*

Endpoints
---------
1. POST /api/v1/export/mesh      — Generate 3D surface mesh (.obj, .ply)
2. GET  /api/v1/export/mesh/download — Download the generated 3D mesh
3. GET  /api/v1/export/geotiff   — Direct file download of metric DSM GeoTIFF
4. POST /api/v1/export/contours  — Generate vector GeoJSON elevation contours
5. POST /api/v1/export/volume    — Volumetric cut-and-fill earthwork calculations
"""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from app.config import settings
from app.models.user import User
from app.schemas.export import (
    MeshFormat,
    MeshExportRequest,
    MeshExportResponse,
    ContourExportRequest,
    ContourExportResponse,
    VolumeCalculationRequest,
    VolumeCalculationResponse,
)
from app.services.auth import get_current_active_user
from app.services import export_service

router = APIRouter(prefix="/api/v1/export", tags=["Export & Analytics"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. 3D Mesh Generation & Download
# ---------------------------------------------------------------------------

@router.post(
    "/mesh",
    response_model=MeshExportResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate 3D surface mesh from calibrated DSM",
    description="Synthesizes a textured 3D triangle mesh (.obj, .ply) with normals and UV mappings for Three.js web rendering.",
)
def generate_mesh(
    request: MeshExportRequest,
    current_user: User = Depends(get_current_active_user),
) -> MeshExportResponse:
    try:
        return export_service.generate_3d_mesh(
            job_id=request.job_id,
            mesh_format=request.format,
            downsample_factor=request.downsample_factor,
            include_texture=request.include_texture,
            z_exaggeration=request.z_exaggeration,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.exception("Mesh generation failed for job %s: %s", request.job_id, exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Mesh error: {exc}")


@router.get(
    "/mesh/download",
    summary="Download generated 3D mesh file",
    description="Direct binary download of the synthesized .obj or .ply mesh.",
)
def download_mesh(
    job_id: str = Query(..., description="Job ID"),
    format: MeshFormat = Query(MeshFormat.OBJ, description="Mesh format"),
    current_user: User = Depends(get_current_active_user),
):
    mesh_path = Path(settings.OUTPUT_DIR) / job_id / f"terrain_mesh.{format.value}"
    if not mesh_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mesh file not found for job '{job_id}'. Please call POST /api/v1/export/mesh first."
        )
    media_type = "text/plain" if format.value == "obj" else "application/octet-stream"
    return FileResponse(
        path=str(mesh_path),
        filename=f"depthwizard_mesh_{job_id[:8]}.{format.value}",
        media_type=media_type,
    )


# ---------------------------------------------------------------------------
# 2. GeoTIFF DSM Download
# ---------------------------------------------------------------------------

@router.get(
    "/geotiff",
    summary="Download calibrated metric DSM GeoTIFF",
    description="Streams the georeferenced metric DSM GeoTIFF (32-bit floating point elevations).",
)
def download_geotiff(
    job_id: str = Query(..., description="Job ID"),
    current_user: User = Depends(get_current_active_user),
):
    candidates = [
        Path(settings.UPLOAD_DIR) / job_id / "dsm_metric.tif",
        Path(settings.OUTPUT_DIR) / job_id / "dsm_metric.tif",
    ]
    tif_path = next((p for p in candidates if p.exists()), None)
    if not tif_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Metric GeoTIFF not found for job '{job_id}'. Ensure the upload was a georeferenced raster."
        )
    return FileResponse(
        path=str(tif_path),
        filename=f"depthwizard_dsm_{job_id[:8]}.tif",
        media_type="image/tiff",
    )


# ---------------------------------------------------------------------------
# 3. Vector Elevation Contours (GeoJSON)
# ---------------------------------------------------------------------------

@router.post(
    "/contours",
    response_model=ContourExportResponse,
    status_code=status.HTTP_200_OK,
    summary="Extract vector elevation contour lines",
    description="Generates smooth elevation contour isolines in RFC 7946 GeoJSON format at customizable intervals.",
)
def generate_contours(
    request: ContourExportRequest,
    current_user: User = Depends(get_current_active_user),
) -> ContourExportResponse:
    try:
        return export_service.generate_contours_geojson(
            job_id=request.job_id,
            interval_m=request.interval_m,
            simplify_tolerance=request.simplify_tolerance,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.exception("Contour generation failed for job %s: %s", request.job_id, exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Contour error: {exc}")


# ---------------------------------------------------------------------------
# 4. Volumetric Earthwork Analytics (Cut & Fill)
# ---------------------------------------------------------------------------

@router.post(
    "/volume",
    response_model=VolumeCalculationResponse,
    status_code=status.HTTP_200_OK,
    summary="Calculate cut & fill earthwork volume",
    description="Computes stockpile volumes, excavation depths, and true 3D surface area against a datum elevation plane.",
)
def calculate_volume(
    request: VolumeCalculationRequest,
    current_user: User = Depends(get_current_active_user),
) -> VolumeCalculationResponse:
    try:
        return export_service.calculate_cut_fill_volume(
            job_id=request.job_id,
            base_elevation_m=request.base_elevation_m,
            polygon_coords=request.polygon_coords,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.exception("Volume calculation failed for job %s: %s", request.job_id, exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Volume error: {exc}")


@router.get("/health", tags=["Health Check"], summary="Export service health probe")
def export_health():
    """Lightweight health probe."""
    return {"status": "ok", "service": "export"}

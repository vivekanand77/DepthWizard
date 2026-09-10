"""
schemas/export.py
-----------------
Pydantic request and response models for 3D mesh generation, GeoTIFF export,
vector contour generation, and volumetric analytics.
"""

from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class MeshFormat(str, Enum):
    OBJ = "obj"
    GLTF = "gltf"
    GLB = "glb"
    PLY = "ply"


# ---------------------------------------------------------------------------
# 3D Mesh Export
# ---------------------------------------------------------------------------

class MeshExportRequest(BaseModel):
    """
    Request body for generating a 3D terrain surface mesh from the calibrated DSM.
    """
    job_id: str = Field(..., description="Job ID from previous pipeline steps")
    format: MeshFormat = Field(
        MeshFormat.OBJ,
        description="Target 3D file format: 'obj', 'ply', 'gltf', or 'glb'"
    )
    downsample_factor: int = Field(
        2, ge=1, le=16,
        description="Grid downsample step (1 = full resolution, 2 = half-resolution for fast web rendering)"
    )
    include_texture: bool = Field(
        True,
        description="Whether to generate UV texture coordinates mapped to the original image"
    )
    z_exaggeration: float = Field(
        1.0, ge=0.1, le=10.0,
        description="Vertical scale multiplier for visual relief enhancement"
    )


class MeshExportResponse(BaseModel):
    """
    Response containing 3D mesh statistics and download path.
    """
    job_id: str
    format: str
    vertex_count: int = Field(..., description="Total 3D vertices generated")
    face_count: int = Field(..., description="Total triangle faces generated")
    mesh_path: str = Field(..., description="Server path to the generated 3D mesh")
    download_url: str = Field(..., description="Direct API download URL for the mesh")
    file_size_bytes: int = Field(..., description="File size in bytes")
    generation_ms: float = Field(..., description="Mesh synthesis time in milliseconds")
    message: str


# ---------------------------------------------------------------------------
# Vector Contour Generation
# ---------------------------------------------------------------------------

class ContourExportRequest(BaseModel):
    """
    Request parameters for generating elevation contour isolines.
    """
    job_id: str = Field(..., description="Job ID")
    interval_m: float = Field(
        5.0, gt=0.1, le=100.0,
        description="Elevation interval between contour lines in metres (e.g. 1m, 5m, 10m)"
    )
    simplify_tolerance: float = Field(
        0.5, ge=0.0, le=10.0,
        description="Douglas-Peucker line simplification tolerance (higher = fewer vertices)"
    )


class ContourExportResponse(BaseModel):
    """
    Response containing vector contour lines in RFC 7946 GeoJSON format.
    """
    job_id: str
    interval_m: float
    total_contour_lines: int
    min_elevation_m: float
    max_elevation_m: float
    geojson: Dict[str, Any] = Field(..., description="Standard GeoJSON FeatureCollection")
    generation_ms: float
    message: str


# ---------------------------------------------------------------------------
# Volumetric Cut & Fill Analytics
# ---------------------------------------------------------------------------

class VolumeCalculationRequest(BaseModel):
    """
    Request parameters for earthwork cut-and-fill volume measurement.
    """
    job_id: str = Field(..., description="Job ID")
    base_elevation_m: Optional[float] = Field(
        None,
        description="Reference datum elevation in metres. If omitted, uses minimum surface elevation."
    )
    polygon_coords: Optional[List[List[float]]] = Field(
        None,
        description="Optional boundary polygon [[col, row], ...] to constrain volume computation"
    )


class VolumeCalculationResponse(BaseModel):
    """
    Results of volumetric earthwork calculation.
    """
    job_id: str
    base_elevation_m: float = Field(..., description="Reference datum plane (m)")
    cut_volume_m3: float = Field(..., description="Excavation / cut volume above datum (m³)")
    fill_volume_m3: float = Field(..., description="Fill volume below datum (m³)")
    net_volume_m3: float = Field(..., description="Net earthwork volume (Cut - Fill) (m³)")
    surface_area_m2: float = Field(..., description="Total 2D planar ground area (m²)")
    true_surface_area_m2: float = Field(..., description="True 3D sloped terrain surface area (m²)")
    min_elevation_m: float
    max_elevation_m: float
    mean_elevation_m: float
    computation_ms: float
    message: str

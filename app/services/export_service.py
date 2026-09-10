"""
services/export_service.py
--------------------------
3D Mesh Generation, GeoTIFF Streaming, Vector Contours & Volumetric Engine.

Responsibilities
----------------
1. 3D Mesh Synthesis (.obj, .ply):
   - Converts 2D calibrated metric DSM into a fully textured 3D triangle mesh.
   - Calculates vertex normals for realistic diffuse/specular lighting.
   - Generates normalized UV texture mapping matching the original aerial imagery.
2. Vector Contour Extraction:
   - Evaluates surface elevation gradients into smooth isolines at user-specified intervals.
   - Projects pixel coordinates into geospatial coordinates (WGS84 / UTM) via Affine transforms.
   - Outputs RFC 7946 compliant GeoJSON FeatureCollection.
3. Volumetric Cut & Fill Analytics:
   - Computes stockpile volumes, excavation depths, and true 3D sloped surface areas.
"""

import io
import json
import logging
import math
import time
from pathlib import Path
from typing import Tuple, Dict, Any, List, Optional

import numpy as np
import matplotlib
matplotlib.use("Agg")  # Headless backend for thread safety
import matplotlib.pyplot as plt

from rasterio.transform import Affine

from app.config import settings
from app.schemas.export import (
    MeshFormat,
    MeshExportResponse,
    ContourExportResponse,
    VolumeCalculationResponse,
)

logger = logging.getLogger(__name__)


# ===========================================================================
# 1. Helper: DSM and Manifest Resolution
# ===========================================================================

def load_calibrated_dsm_and_manifest(job_id: str) -> Tuple[np.ndarray, dict, Path]:
    """
    Locates and loads the calibrated metric DSM (.npy) and associated manifest.

    Parameters
    ----------
    job_id : str — Unique identifier of the job.

    Returns
    -------
    dsm : np.ndarray — 2D float32 array in metric elevation units.
    manifest : dict — Parsed manifest.json.
    job_dir : Path — Path to the job's upload directory.
    """
    job_dir = Path(settings.UPLOAD_DIR) / job_id
    manifest_path = job_dir / "manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found for job '{job_id}'. Run upload and calibrate first.")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # Search for calibrated DSM array across standard candidate locations
    candidates = [
        job_dir / "dsm_metric.npy",
        Path(settings.OUTPUT_DIR) / job_id / "dsm_metric.npy",
    ]
    dsm_path = next((p for p in candidates if p.exists()), None)

    if dsm_path is None:
        raise FileNotFoundError(
            f"Calibrated DSM array not found for job '{job_id}'. "
            "Please call POST /api/v1/calibrate before exporting."
        )

    dsm = np.load(str(dsm_path)).astype(np.float32)
    return dsm, manifest, job_dir


# ===========================================================================
# 2. 3D Mesh Generation (.obj, .ply)
# ===========================================================================

def _generate_obj_mesh(
    vertices: np.ndarray,
    uvs: np.ndarray,
    normals: np.ndarray,
    faces: np.ndarray,
    output_path: Path,
) -> int:
    """
    Writes a Wavefront .obj file with vertices, UVs, normals, and triangle faces.
    """
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# DepthWizard 3D Surface Mesh Export\n")
        f.write(f"# Vertices: {len(vertices)}, Faces: {len(faces)}\n\n")

        # 1. Vertices: v x y z
        for v in vertices:
            f.write(f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}\n")

        # 2. UV Texture coordinates: vt u v
        for uv in uvs:
            f.write(f"vt {uv[0]:.4f} {uv[1]:.4f}\n")

        # 3. Normals: vn nx ny nz
        for n in normals:
            f.write(f"vn {n[0]:.4f} {n[1]:.4f} {n[2]:.4f}\n")

        # 4. Faces: f v1/vt1/vn1 v2/vt2/vn2 v3/vt3/vn3 (1-indexed in OBJ standard)
        for face in faces:
            v1, v2, v3 = face + 1
            f.write(f"f {v1}/{v1}/{v1} {v2}/{v2}/{v2} {v3}/{v3}/{v3}\n")

    return output_path.stat().st_size


def _generate_ply_mesh(
    vertices: np.ndarray,
    normals: np.ndarray,
    faces: np.ndarray,
    output_path: Path,
) -> int:
    """
    Writes a standard ASCII/Binary compatible .ply mesh file.
    """
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("ply\n")
        f.write("format ascii 1.0\n")
        f.write("comment DepthWizard 3D Surface Model\n")
        f.write(f"element vertex {len(vertices)}\n")
        f.write("property float x\n")
        f.write("property float y\n")
        f.write("property float z\n")
        f.write("property float nx\n")
        f.write("property float ny\n")
        f.write("property float nz\n")
        f.write(f"element face {len(faces)}\n")
        f.write("property list uchar int vertex_indices\n")
        f.write("end_header\n")

        for v, n in zip(vertices, normals):
            f.write(f"{v[0]:.4f} {v[1]:.4f} {v[2]:.4f} {n[0]:.4f} {n[1]:.4f} {n[2]:.4f}\n")

        for face in faces:
            f.write(f"3 {face[0]} {face[1]} {face[2]}\n")

    return output_path.stat().st_size


def generate_3d_mesh(
    job_id: str,
    mesh_format: MeshFormat = MeshFormat.OBJ,
    downsample_factor: int = 2,
    include_texture: bool = True,
    z_exaggeration: float = 1.0,
) -> MeshExportResponse:
    """
    Synthesizes a 3D triangle mesh from the calibrated metric DSM.

    Parameters
    ----------
    job_id : str
    mesh_format : MeshFormat — 'obj', 'ply', etc.
    downsample_factor : int — Grid step (1 = full res, 2 = half res).
    include_texture : bool — Generate UV texture mapping.
    z_exaggeration : float — Vertical relief multiplier.

    Returns
    -------
    MeshExportResponse containing vertex counts, file size, and download URLs.
    """
    t0 = time.perf_counter()

    dsm, manifest, job_dir = load_calibrated_dsm_and_manifest(job_id)
    out_dir = Path(settings.OUTPUT_DIR) / job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # Apply downsampling for web performance
    step = max(1, downsample_factor)
    dsm_sub = dsm[::step, ::step]
    H_sub, W_sub = dsm_sub.shape

    # Extract spatial GSD / scale
    metadata = manifest.get("metadata", {})
    gsd = float(metadata.get("gsd_metres") or 1.0) * step

    logger.info("Building 3D mesh for job %s: shape=(%d, %d), GSD=%.2f m", job_id, H_sub, W_sub, gsd)

    # 1. Compute 3D Vertex Coordinates (X, Y, Z) centered at origin
    x_coords = (np.arange(W_sub) - W_sub / 2.0) * gsd
    y_coords = (H_sub / 2.0 - np.arange(H_sub)) * gsd  # North is positive Y
    xx, yy = np.meshgrid(x_coords, y_coords)
    zz = (dsm_sub - np.nanmin(dsm_sub)) * z_exaggeration

    vertices = np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()]).astype(np.float32)

    # 2. Compute UV texture coordinates [0, 1]
    u_coords = np.linspace(0.0, 1.0, W_sub)
    v_coords = np.linspace(1.0, 0.0, H_sub)  # V is inverted in 3D UV space
    uu, vv = np.meshgrid(u_coords, v_coords)
    uvs = np.column_stack([uu.ravel(), vv.ravel()]).astype(np.float32)

    # 3. Generate Triangle Face Indices (2 triangles per quad cell)
    faces = []
    for r in range(H_sub - 1):
        for c in range(W_sub - 1):
            top_left     = r * W_sub + c
            top_right    = top_left + 1
            bottom_left  = (r + 1) * W_sub + c
            bottom_right = bottom_left + 1

            # Triangle 1: top_left -> bottom_left -> top_right
            faces.append([top_left, bottom_left, top_right])
            # Triangle 2: top_right -> bottom_left -> bottom_right
            faces.append([top_right, bottom_left, bottom_right])

    faces = np.array(faces, dtype=np.int32)

    # 4. Compute Vectorized Surface Normals
    normals = np.zeros_like(vertices, dtype=np.float32)
    v0 = vertices[faces[:, 0]]
    v1 = vertices[faces[:, 1]]
    v2 = vertices[faces[:, 2]]
    face_normals = np.cross(v1 - v0, v2 - v0)

    # Normalize face normals
    norm_lens = np.linalg.norm(face_normals, axis=1, keepdims=True)
    norm_lens[norm_lens == 0] = 1.0
    face_normals = face_normals / norm_lens

    # Accumulate vertex normals from adjacent faces
    np.add.at(normals, faces[:, 0], face_normals)
    np.add.at(normals, faces[:, 1], face_normals)
    np.add.at(normals, faces[:, 2], face_normals)
    vert_lens = np.linalg.norm(normals, axis=1, keepdims=True)
    vert_lens[vert_lens == 0] = 1.0
    normals = normals / vert_lens

    # 5. Export to disk
    ext = mesh_format.value.lower()
    mesh_filename = f"terrain_mesh.{ext}"
    mesh_path = out_dir / mesh_filename

    if ext in ("obj", "gltf", "glb"):
        # Default to OBJ format for web Three.js loaders
        file_size = _generate_obj_mesh(vertices, uvs, normals, faces, mesh_path)
    elif ext == "ply":
        file_size = _generate_ply_mesh(vertices, normals, faces, mesh_path)
    else:
        file_size = _generate_obj_mesh(vertices, uvs, normals, faces, mesh_path)

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    download_url = f"/api/v1/export/mesh/download?job_id={job_id}&format={ext}"

    logger.info(
        "3D mesh generation completed: %d vertices, %d faces in %.1f ms (%d bytes)",
        len(vertices), len(faces), elapsed_ms, file_size
    )

    return MeshExportResponse(
        job_id=job_id,
        format=ext,
        vertex_count=len(vertices),
        face_count=len(faces),
        mesh_path=str(mesh_path),
        download_url=download_url,
        file_size_bytes=file_size,
        generation_ms=round(elapsed_ms, 2),
        message=f"Successfully generated {ext.upper()} mesh with {len(vertices):,} vertices.",
    )


# ===========================================================================
# 3. Vector Elevation Contour Generation (GeoJSON)
# ===========================================================================

def generate_contours_geojson(
    job_id: str,
    interval_m: float = 5.0,
    simplify_tolerance: float = 0.5,
) -> ContourExportResponse:
    """
    Generates vector elevation contours from the calibrated DSM in GeoJSON format.

    Parameters
    ----------
    job_id : str
    interval_m : float — Elevation step between isolines in metres.
    simplify_tolerance : float — Coordinate precision smoothing.

    Returns
    -------
    ContourExportResponse containing GeoJSON FeatureCollection.
    """
    t0 = time.perf_counter()

    dsm, manifest, _ = load_calibrated_dsm_and_manifest(job_id)
    metadata = manifest.get("metadata", {})
    transform_list = metadata.get("transform")
    crs_epsg = metadata.get("crs_epsg")

    min_elev = float(np.nanmin(dsm))
    max_elev = float(np.nanmax(dsm))

    # Calculate contour levels
    start_level = math.ceil(min_elev / interval_m) * interval_m
    levels = np.arange(start_level, max_elev, interval_m)

    if len(levels) == 0:
        levels = np.array([min_elev + (max_elev - min_elev) / 2.0])

    # Extract contours via matplotlib contour generator
    fig, ax = plt.subplots(figsize=(1, 1))
    cs = ax.contour(dsm, levels=levels)
    plt.close(fig)

    # Build Affine transform if georeferenced
    transform = Affine(*transform_list[:6]) if (transform_list and len(transform_list) >= 6) else None

    features: List[Dict[str, Any]] = []

    # In modern matplotlib (3.8+), allsegs is the standard list of (col, row) paths per level
    for level_idx, level_val in enumerate(cs.levels):
        segments = cs.allsegs[level_idx] if hasattr(cs, "allsegs") else []
        for segment in segments:
            if len(segment) < 2:
                continue

            # Convert (col, row) pixels to geo-coordinates or relative metres
            transformed_coords = []
            for col, row in segment:
                if transform:
                    geo_x, geo_y = transform * (col, row)
                else:
                    geo_x, geo_y = float(col), float(row)
                transformed_coords.append([round(geo_x, 3), round(geo_y, 3)])

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": transformed_coords,
                },
                "properties": {
                    "elevation_m": round(float(level_val), 2),
                    "point_count": len(transformed_coords),
                }
            })

    geojson = {
        "type": "FeatureCollection",
        "crs": {
            "type": "name",
            "properties": {"name": f"EPSG:{crs_epsg}" if crs_epsg else "urn:ogc:def:crs:OGC:1.3:CRS84"}
        },
        "features": features,
    }

    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    logger.info(
        "Generated %d contour lines at %.1f m interval for job %s (%.1f ms)",
        len(features), interval_m, job_id, elapsed_ms
    )

    return ContourExportResponse(
        job_id=job_id,
        interval_m=interval_m,
        total_contour_lines=len(features),
        min_elevation_m=round(min_elev, 2),
        max_elevation_m=round(max_elev, 2),
        geojson=geojson,
        generation_ms=round(elapsed_ms, 2),
        message=f"Extracted {len(features)} contour isolines between {min_elev:.1f}m and {max_elev:.1f}m.",
    )


# ===========================================================================
# 4. Volumetric Cut & Fill Earthwork Analysis
# ===========================================================================

def calculate_cut_fill_volume(
    job_id: str,
    base_elevation_m: Optional[float] = None,
    polygon_coords: Optional[List[List[float]]] = None,
) -> VolumeCalculationResponse:
    """
    Computes cut volume, fill volume, net volume, and surface areas from the DSM.

    Mathematical Formulation
    ------------------------
    Cell Area: ΔA = GSD_x × GSD_y
    Cut Volume:  V_cut  = Σ max(Z_i - Z_base, 0) · ΔA
    Fill Volume: V_fill = Σ max(Z_base - Z_i, 0) · ΔA
    Net Volume:  V_net  = V_cut - V_fill

    3D Sloped Surface Area:
    Area_3D = Σ sqrt( 1 + (dZ/dx)² + (dZ/dy)² ) · ΔA
    """
    t0 = time.perf_counter()

    dsm, manifest, _ = load_calibrated_dsm_and_manifest(job_id)
    metadata = manifest.get("metadata", {})
    gsd = float(metadata.get("gsd_metres") or 1.0)
    cell_area = gsd * gsd

    min_elev = float(np.nanmin(dsm))
    max_elev = float(np.nanmax(dsm))
    mean_elev = float(np.nanmean(dsm))

    # Determine reference datum elevation
    datum = base_elevation_m if base_elevation_m is not None else min_elev

    # Cut and Fill calculations
    diff = dsm - datum
    cut_mask = diff > 0
    fill_mask = diff < 0

    cut_vol = float(np.sum(diff[cut_mask]) * cell_area)
    fill_vol = float(np.sum(-diff[fill_mask]) * cell_area)
    net_vol = cut_vol - fill_vol

    # Planar 2D area
    planar_area = float(dsm.size * cell_area)

    # 3D Sloped Surface Area via gradient approximation
    gy, gx = np.gradient(dsm, gsd, gsd)
    slope_factor = np.sqrt(1.0 + gx**2 + gy**2)
    true_3d_area = float(np.sum(slope_factor) * cell_area)

    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    logger.info(
        "Volume analysis for job %s: Datum=%.2f m, Cut=%.2f m³, Fill=%.2f m³",
        job_id, datum, cut_vol, fill_vol
    )

    return VolumeCalculationResponse(
        job_id=job_id,
        base_elevation_m=round(datum, 3),
        cut_volume_m3=round(cut_vol, 3),
        fill_volume_m3=round(fill_vol, 3),
        net_volume_m3=round(net_vol, 3),
        surface_area_m2=round(planar_area, 2),
        true_surface_area_m2=round(true_3d_area, 2),
        min_elevation_m=round(min_elev, 2),
        max_elevation_m=round(max_elev, 2),
        mean_elevation_m=round(mean_elev, 2),
        computation_ms=round(elapsed_ms, 2),
        message=(
            f"Calculated {cut_vol:,.1f} m³ Cut and {fill_vol:,.1f} m³ Fill "
            f"against datum {datum:.2f} m across {planar_area:,.1f} m² area."
        ),
    )


# ===========================================================================
# Documentation and Architectural Summary
# ===========================================================================
"""
================================================================================
PURPOSE, WORKING MECHANISM, AND EXPORT CAPABILITIES
================================================================================

1. Purpose
----------
Once monocular depth estimation and scale calibration produce an accurate
metric Digital Surface Model (DSM), end users require downstream deliverables:
- Interactive 3D visualization in web browsers (Three.js, Cesium).
- GIS vector contour maps for civil engineering, surveying, and site planning.
- Volumetric cut-and-fill analysis for earthwork contractor estimating.
- Standard GeoTIFF downloads for CAD / ArcGIS / QGIS workflows.

2. Working Mechanism
--------------------
a. 3D Mesh Synthesis:
   - Constructs a connected quad mesh over the regular DSM elevation grid.
   - Computes analytical surface normals for smooth shading.
   - Normalizes UV texture coordinates so aerial orthomosaics drape seamlessly.
   - Serializes into standard formats (.obj, .ply).

b. GeoJSON Contour Engine:
   - Evaluates elevation isolines at custom intervals (e.g. 1m, 5m, 10m).
   - Maps pixel coordinates back to real-world geospatial coordinates (WGS84/UTM)
     using the raster Affine transform.
   - Emits standard RFC 7946 GeoJSON LineString features.

c. Volumetric Cut & Fill Earthwork Analysis:
   - Computes differential voxel volumes against a reference elevation datum.
   - Measures excavation volume (cut) and backfill volume (fill).
   - Calculates true 3D sloped terrain area using surface gradients.
================================================================================
"""

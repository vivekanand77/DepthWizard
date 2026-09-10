"""
services/gis_service.py
-----------------------
Geospatial Ingestion Service — the core GIS engine layer.

Responsibilities
----------------
1. Validate uploaded file (GeoTIFF, PNG, JPEG).
2. Open raster files with rasterio and extract spatial metadata
   (CRS, bounding box, affine transform, Ground Sampling Distance).
3. Slice large rasters into overlapping 512×512 patches with individual
   affine transforms so they can be independently inferred and then
   re-stitched into the full-resolution metric DSM.
4. Persist tile arrays to disk as .npy files for consumption by the
   inference service.

Design Decisions
----------------
- Overlap (TILE_OVERLAP) is set to 64 px so the depth model sees enough
  context at every boundary — this overlap is discarded during stitching.
- Non-georeferenced images (PNG / JPEG) are accepted and processed as
  pixel-space rasters; CRS metadata will be None in those cases.
- All public functions are pure (no global state) so they are easy to unit-test.
"""

import os
import uuid
import math
import logging
from pathlib import Path
from typing import List, Tuple, Optional

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine
from rasterio.windows import Window
from PIL import Image

from app.config import settings
from app.schemas.upload import GeospatialMetadata, TileInfo

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Patch size fed into the Vision Transformer backbone.
# Depth Anything V2 (ViT-B) expects 518×518 internally, but we tile at 512
# for clean memory alignment.
TILE_SIZE: int = 512

# Overlap in pixels between adjacent tiles. Prevents visible seams in the
# re-stitched disparity map by giving the model enough edge context.
TILE_OVERLAP: int = 64

# Stride = TILE_SIZE - TILE_OVERLAP
TILE_STRIDE: int = TILE_SIZE - TILE_OVERLAP

# Supported MIME / extension mapping
SUPPORTED_EXTENSIONS = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# File Validation
# ---------------------------------------------------------------------------

def validate_file_extension(filename: str) -> str:
    """
    Check the file extension against the supported set and return a
    normalised file-type string: 'geotiff' | 'png' | 'jpeg'.

    Raises
    ------
    ValueError
        If the extension is not in SUPPORTED_EXTENSIONS.
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{suffix}'. "
            f"Accepted: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
    if suffix in {".tif", ".tiff"}:
        return "geotiff"
    if suffix == ".png":
        return "png"
    return "jpeg"


# ---------------------------------------------------------------------------
# Metadata Extraction
# ---------------------------------------------------------------------------

def extract_geospatial_metadata(raster_path: str) -> GeospatialMetadata:
    """
    Open a raster file with rasterio and pull all geospatial attributes
    into a typed GeospatialMetadata object.

    Parameters
    ----------
    raster_path : str
        Absolute path to the saved upload (GeoTIFF / PNG / JPEG).

    Returns
    -------
    GeospatialMetadata
        Populated schema object — CRS fields are None for non-georeferenced files.

    Notes
    -----
    - rasterio can open PNG / JPEG as well; they will simply have no CRS.
    - GSD (Ground Sampling Distance) is the absolute value of the x-resolution
      when the CRS is projected in metres (EPSG authority).
    """
    with rasterio.open(raster_path) as src:
        width = src.width
        height = src.height
        band_count = src.count
        transform: Affine = src.transform
        crs: Optional[CRS] = src.crs

        # --- CRS extraction ---
        crs_epsg: Optional[int] = None
        crs_wkt: Optional[str] = None
        bounds_tuple: Optional[Tuple] = None
        resolution: Optional[Tuple[float, float]] = None
        gsd: Optional[float] = None
        is_georeferenced = False

        if crs is not None:
            is_georeferenced = True
            crs_wkt = crs.wkt

            # Try to obtain the EPSG integer code
            try:
                crs_epsg = int(crs.to_epsg())
            except (TypeError, ValueError):
                logger.warning("CRS present but EPSG code could not be resolved.")

            # Bounding box in projected units
            b = src.bounds
            bounds_tuple = (b.left, b.bottom, b.right, b.top)

            # Pixel spacing (transform.a = x_res, transform.e = y_res, negative for north-up)
            resolution = (abs(transform.a), abs(transform.e))

            # GSD is simply the x-pixel size for metric projections (UTM etc.)
            gsd = abs(transform.a)

    logger.info(
        "Extracted metadata: %dx%d px, %d bands, CRS=%s, GSD=%.2f m",
        width, height, band_count, crs_epsg, gsd or 0.0
    )

    return GeospatialMetadata(
        crs_epsg=crs_epsg,
        crs_wkt=crs_wkt,
        bounds=bounds_tuple,
        resolution=resolution,
        width=width,
        height=height,
        band_count=band_count,
        is_georeferenced=is_georeferenced,
        gsd_metres=gsd,
    )


# ---------------------------------------------------------------------------
# Tile / Patch Splitting
# ---------------------------------------------------------------------------

def _compute_tile_grid(dimension: int, tile_size: int, stride: int) -> List[int]:
    """
    Compute the list of starting pixel offsets along a single axis.

    The last tile is anchored so it ends at the image edge — this ensures
    full image coverage even when the dimension is not a multiple of stride.

    Parameters
    ----------
    dimension : int  — total size along this axis (width or height).
    tile_size : int  — patch size in pixels.
    stride    : int  — step between consecutive tile origins.

    Returns
    -------
    List[int]  — sorted list of start-pixel offsets.
    """
    offsets: List[int] = []
    start = 0
    while start < dimension:
        offsets.append(start)
        if start + tile_size >= dimension:
            break
        start += stride
    # Guarantee the trailing edge is always covered
    if offsets and (offsets[-1] + tile_size) < dimension:
        offsets.append(dimension - tile_size)
    return offsets


def slice_raster_into_tiles(
    raster_path: str,
    job_id: str,
    tile_size: int = TILE_SIZE,
    overlap: int = TILE_OVERLAP,
) -> List[TileInfo]:
    """
    Read the raster at `raster_path`, slice it into overlapping patches, and
    persist each patch as a float32 NumPy array (<job_id>/tile_<r>_<c>.npy).

    Parameters
    ----------
    raster_path : str
        Path to the uploaded raster file.
    job_id : str
        Unique job identifier used to namespace tile output files.
    tile_size : int
        Patch height and width in pixels (default 512).
    overlap : int
        Pixel overlap between adjacent patches (default 64).

    Returns
    -------
    List[TileInfo]
        One entry per patch, containing its grid position, pixel offset,
        affine transform, and file path.

    Notes
    -----
    - For non-georeferenced images (PNG/JPEG) the affine coefficients are
      derived from a pixel-identity transform (1 px = 1 unit).
    - The saved arrays are (bands, H, W) float32 in the range [0, 1] for
      RGB images and raw DN values for multi-band GeoTIFFs.
    """
    stride = tile_size - overlap

    # Create per-job output directory
    job_tile_dir = Path(settings.UPLOAD_DIR) / job_id / "tiles"
    job_tile_dir.mkdir(parents=True, exist_ok=True)

    tile_infos: List[TileInfo] = []

    with rasterio.open(raster_path) as src:
        transform: Affine = src.transform
        col_offsets = _compute_tile_grid(src.width, tile_size, stride)
        row_offsets = _compute_tile_grid(src.height, tile_size, stride)

        for row_idx, row_off in enumerate(row_offsets):
            for col_idx, col_off in enumerate(col_offsets):
                # Clamp to raster boundaries (edge tiles may be smaller)
                actual_w = min(tile_size, src.width  - col_off)
                actual_h = min(tile_size, src.height - row_off)

                # Read the windowed region from disk (all bands)
                window = Window(col_off, row_off, actual_w, actual_h)
                data = src.read(window=window)  # shape: (bands, H, W)

                # Convert to float32 and normalise for RGB-like data
                data = data.astype(np.float32)
                if src.dtypes[0] == "uint8":
                    # Scale 8-bit images to [0, 1]
                    data = data / 255.0

                # Compute the affine transform for this tile's top-left corner
                # rasterio.transform.xy gives us the projected coordinate of
                # the tile origin; we preserve the same pixel scale.
                tile_transform = src.window_transform(window)

                # Flatten the six affine coefficients for serialisation
                affine_coeffs = [
                    tile_transform.a,  # x pixel size
                    tile_transform.b,  # rotation (0 for north-up)
                    tile_transform.c,  # x origin (left edge)
                    tile_transform.d,  # rotation (0 for north-up)
                    tile_transform.e,  # y pixel size (negative for north-up)
                    tile_transform.f,  # y origin (top edge)
                ]

                # Persist as .npy for fast memory-mapped loading during inference
                tile_filename = f"tile_{row_idx:03d}_{col_idx:03d}.npy"
                tile_path = job_tile_dir / tile_filename
                np.save(str(tile_path), data)

                tile_infos.append(TileInfo(
                    tile_index=(row_idx, col_idx),
                    pixel_offset=(col_off, row_off),
                    tile_width=actual_w,
                    tile_height=actual_h,
                    affine_transform=affine_coeffs,
                    saved_path=str(tile_path.relative_to(settings.UPLOAD_DIR)),
                ))

    logger.info(
        "Sliced raster into %d tiles (%d rows × %d cols) for job %s",
        len(tile_infos), len(row_offsets), len(col_offsets), job_id
    )
    return tile_infos


# ---------------------------------------------------------------------------
# Non-GeoTIFF (PNG / JPEG) helpers
# ---------------------------------------------------------------------------

def convert_image_to_raster(image_path: str, job_id: str) -> str:
    """
    Convert a plain PNG / JPEG image to an in-memory compatible path.

    For non-georeferenced images rasterio can still open them directly,
    but we store the original path and let slice_raster_into_tiles handle
    the reading — this function is a no-op pass-through for those formats
    since rasterio natively reads PNG/JPEG.

    Parameters
    ----------
    image_path : str
        Path to the uploaded PNG / JPEG.
    job_id : str
        Unique job identifier (unused here but kept for API symmetry).

    Returns
    -------
    str
        The same `image_path` (rasterio opens PNG/JPEG natively).
    """
    logger.info("Non-GeoTIFF image detected (%s); using rasterio native reader.", image_path)
    return image_path


# ---------------------------------------------------------------------------
# Main ingestion entry-point
# ---------------------------------------------------------------------------

def ingest_upload(file_bytes: bytes, filename: str) -> Tuple[str, str, GeospatialMetadata, List[TileInfo]]:
    """
    High-level orchestration function called by the upload router.

    Steps
    -----
    1. Validate file extension and determine type.
    2. Generate a globally unique job_id (UUID4).
    3. Persist raw bytes to <UPLOAD_DIR>/<job_id>/original.<ext>.
    4. Extract geospatial metadata.
    5. Slice raster into overlapping 512×512 tiles.

    Parameters
    ----------
    file_bytes : bytes
        Raw content of the uploaded file (read from the UploadFile stream).
    filename   : str
        Original filename from the HTTP multipart upload.

    Returns
    -------
    job_id       : str               — Unique job identifier.
    file_type    : str               — 'geotiff' | 'png' | 'jpeg'.
    metadata     : GeospatialMetadata — Extracted spatial metadata.
    tiles        : List[TileInfo]    — Tile descriptors for inference.

    Raises
    ------
    ValueError   : Unsupported file type.
    RuntimeError : rasterio cannot open the file.
    """
    # Step 1 — Validate extension
    file_type = validate_file_extension(filename)

    # Step 2 — Generate unique job ID
    job_id = str(uuid.uuid4())
    logger.info("New ingestion job started: job_id=%s, file=%s", job_id, filename)

    # Step 3 — Persist raw file bytes
    job_dir = Path(settings.UPLOAD_DIR) / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower()
    raw_path = str(job_dir / f"original{suffix}")

    with open(raw_path, "wb") as f:
        f.write(file_bytes)
    logger.info("Saved raw upload to %s (%d bytes)", raw_path, len(file_bytes))

    # Step 4 — Extract geospatial metadata
    try:
        metadata = extract_geospatial_metadata(raw_path)
    except Exception as exc:
        logger.error("Metadata extraction failed for job %s: %s", job_id, exc)
        raise RuntimeError(f"Could not read raster metadata: {exc}") from exc

    # Step 5 — Tile slicing
    try:
        tiles = slice_raster_into_tiles(raw_path, job_id)
    except Exception as exc:
        logger.error("Tile slicing failed for job %s: %s", job_id, exc)
        raise RuntimeError(f"Tile slicing failed: {exc}") from exc

    # Step 6 — Persist a manifest.json alongside the upload so the inference
    # router can reconstruct the spatial tile layout without re-parsing the
    # raw raster. This is the shared source of truth between pipeline stages.
    import json as _json
    manifest = {
        "job_id":    job_id,
        "filename":  filename,
        "file_type": file_type,
        "width":     metadata.width,
        "height":    metadata.height,
        "band_count":metadata.band_count,
        "crs_epsg":  metadata.crs_epsg,
        "gsd_metres":metadata.gsd_metres,
        "is_georeferenced": metadata.is_georeferenced,
        "tiles": [t.model_dump() for t in tiles],
    }
    manifest_path = job_dir / "manifest.json"
    with open(str(manifest_path), "w", encoding="utf-8") as mf:
        _json.dump(manifest, mf, indent=2)
    logger.info("Manifest written to %s", manifest_path)

    return job_id, file_type, metadata, tiles

"""
schemas/upload.py
-----------------
Pydantic response models for the GeoTIFF upload & geospatial ingestion pipeline.

These schemas define the strict data contract between the backend engine layer
and any consumer (frontend, CLI, test suite) so everyone can build in parallel
without ambiguity.
"""

from typing import List, Optional, Tuple
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Geospatial Metadata
# ---------------------------------------------------------------------------

class GeospatialMetadata(BaseModel):
    """
    Spatial reference and resolution information extracted directly from the
    GeoTIFF file header via rasterio.

    Fields
    ------
    crs_epsg   : EPSG authority code of the Coordinate Reference System.
                 e.g. 32643 for WGS-84 UTM Zone 43N.
    crs_wkt    : Full Well-Known Text string of the CRS (informational).
    bounds     : Bounding box in projected units (left, bottom, right, top).
    resolution : Pixel size in (x_res, y_res) projected units (metres for UTM).
    width      : Raster width in pixels.
    height     : Raster height in pixels.
    band_count : Number of spectral bands in the file.
    is_georeferenced : True when the file contains a valid CRS + affine transform.
    gsd_metres : Ground Sampling Distance — physical size of one pixel in metres.
                 Only meaningful when the CRS is a metric projection (UTM etc.).
    """
    crs_epsg: Optional[int] = Field(None, description="EPSG code of the CRS")
    crs_wkt: Optional[str] = Field(None, description="CRS as Well-Known Text")
    bounds: Optional[Tuple[float, float, float, float]] = Field(
        None, description="(left, bottom, right, top) in CRS units"
    )
    resolution: Optional[Tuple[float, float]] = Field(
        None, description="(x_res, y_res) pixel size in CRS units"
    )
    width: int = Field(..., description="Image width in pixels")
    height: int = Field(..., description="Image height in pixels")
    band_count: int = Field(..., description="Number of raster bands")
    is_georeferenced: bool = Field(..., description="Has valid CRS and transform?")
    gsd_metres: Optional[float] = Field(None, description="Ground Sampling Distance in metres")


# ---------------------------------------------------------------------------
# Tile / Patch Info
# ---------------------------------------------------------------------------

class TileInfo(BaseModel):
    """
    Describes a single 512×512 (or smaller) spatial patch cut from the full raster.

    Each tile preserves an independent affine transform so it can be
    re-stitched into the global coordinate grid after depth inference.

    Fields
    ------
    tile_index    : Sequential (row, col) zero-based index in the tile grid.
    pixel_offset  : Top-left pixel position (col_off, row_off) inside the
                    original raster.
    tile_width    : Actual width of this tile (may be < TILE_SIZE at edges).
    tile_height   : Actual height of this tile (may be < TILE_SIZE at edges).
    affine_transform : Flattened affine coefficients
                       [a, b, c, d, e, f] matching rasterio convention:
                       x_geo = a*col + b*row + c
                       y_geo = d*col + e*row + f
    saved_path    : Relative path where the tile array (.npy) was persisted.
    """
    tile_index: Tuple[int, int] = Field(..., description="(row, col) grid index")
    pixel_offset: Tuple[int, int] = Field(..., description="(col_off, row_off) in original raster")
    tile_width: int
    tile_height: int
    affine_transform: List[float] = Field(
        ..., description="Six affine coefficients [a, b, c, d, e, f]"
    )
    saved_path: str = Field(..., description="Path to persisted .npy tile array")


# ---------------------------------------------------------------------------
# Upload API Response
# ---------------------------------------------------------------------------

class UploadResponse(BaseModel):
    """
    Full response returned by POST /api/v1/upload after successful ingestion.

    The frontend and downstream services consume this contract to build the
    split-view canvas, trigger inference, and track the job.

    Fields
    ------
    job_id       : Unique identifier for this processing job; used in all
                   subsequent /infer and /calibrate requests.
    filename     : Original uploaded filename.
    file_type    : 'geotiff' | 'png' | 'jpeg'
    metadata     : Extracted geospatial metadata (CRS, bounds, GSD …).
    tiles        : List of tile descriptors for patch-based inference.
    tile_count   : Convenience count == len(tiles).
    message      : Human-readable status summary.
    """
    job_id: str = Field(..., description="Unique processing job identifier")
    filename: str = Field(..., description="Original uploaded filename")
    file_type: str = Field(..., description="Detected file type: geotiff | png | jpeg")
    metadata: GeospatialMetadata
    tiles: List[TileInfo] = Field(default_factory=list)
    tile_count: int = Field(..., description="Total number of spatial patches")
    message: str = Field(..., description="Human-readable status")

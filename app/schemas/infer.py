"""
schemas/infer.py
----------------
Pydantic request and response models for the depth inference pipeline.

These schemas define the API contract for POST /api/v1/infer which
triggers Depth Anything V2 (ViT-B) disparity estimation on the tiles
produced by the upload/ingestion step.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Inference Request
# ---------------------------------------------------------------------------

class InferRequest(BaseModel):
    """
    Body sent by the client to trigger depth inference on an uploaded job.

    Fields
    ------
    job_id        : UUID string returned by POST /api/v1/upload.
                    Identifies which tile set to run inference on.
    model_variant : Override the server-default model size for this run.
                    Options: 'vits' (fast) | 'vitb' (balanced) | 'vitl' (accurate).
                    Defaults to the server's DEPTH_MODEL_VARIANT setting.
    input_size    : Resolution fed into the ViT encoder. Depth Anything V2
                    uses 518 internally; lower values trade accuracy for speed.
    """
    job_id: str = Field(..., description="Job ID from /upload response")
    model_variant: Optional[str] = Field(
        None,
        description="Override model variant: vits | vitb | vitl"
    )
    input_size: int = Field(
        518,
        ge=256, le=1024,
        description="Encoder input resolution (px). Default 518."
    )


# ---------------------------------------------------------------------------
# Per-tile inference result
# ---------------------------------------------------------------------------

class TileInferResult(BaseModel):
    """
    Inference statistics for a single 512×512 tile.

    Fields
    ------
    tile_index   : (row, col) grid position matching TileInfo.tile_index.
    disparity_path : Relative path to the saved disparity .npy array.
    min_disparity  : Minimum relative disparity value (pre-normalisation).
    max_disparity  : Maximum relative disparity value (pre-normalisation).
    mean_disparity : Mean relative disparity across valid pixels.
    inference_ms   : Wall-clock time taken to run this single tile (ms).
    """
    tile_index: tuple
    disparity_path: str = Field(..., description="Path to saved disparity .npy")
    min_disparity: float
    max_disparity: float
    mean_disparity: float
    inference_ms: float = Field(..., description="Inference time for this tile (ms)")


# ---------------------------------------------------------------------------
# Inference API Response
# ---------------------------------------------------------------------------

class InferResponse(BaseModel):
    """
    Full response from POST /api/v1/infer.

    Fields
    ------
    job_id          : Same job_id passed in the request.
    model_variant   : Actual model variant used (may differ from request if
                      the requested variant was unavailable).
    device          : Compute device used: 'cuda:0' | 'cpu'.
    tiles_processed : Number of tiles successfully inferred.
    total_ms        : Total wall-clock time for all tiles (ms).
    tile_results    : Per-tile statistics and disparity paths.
    disparity_map_path : Path to the full stitched disparity map .npy
                         (assembled from individual tile results).
    message         : Human-readable status.
    """
    job_id: str
    model_variant: str
    device: str
    tiles_processed: int
    total_ms: float = Field(..., description="Total inference time (ms)")
    tile_results: List[TileInferResult]
    disparity_map_path: str = Field(..., description="Stitched full-resolution disparity map path")
    message: str

"""
services/depth_service.py
--------------------------
Depth Anything V2 Inference Service — the ML engine layer.

Responsibilities
----------------
1. Detect the compute device (CUDA GPU → CPU fallback).
2. Load the Depth Anything V2 Vision Transformer (ViT) weights on server
   startup and cache the model in module-level state to avoid re-loading
   on every request.
3. Pre-process each 512×512 tile (resize → normalise → tensor).
4. Run forward inference to produce a relative disparity array [0.0–1.0].
5. Stitch all per-tile disparity arrays back into a full-resolution map,
   using the TILE_OVERLAP margin to blend seam boundaries.
6. Persist both per-tile and stitched disparity arrays as .npy files for
   downstream calibration and export steps.

Architecture Notes
------------------
- The model is loaded lazily on the first inference call (not at import time)
  so that the FastAPI process starts instantly even without a GPU.
- We use a simple thread lock around model loading to avoid race conditions
  when the server handles concurrent requests at startup.
- Depth Anything V2 expects RGB float32 input normalised with ImageNet stats.
  We replicate the official pre-processing from the paper implementation.
- The stitching strategy averages overlapping regions rather than hard-cutting
  to eliminate visible seam artefacts in the reconstructed disparity map.

References
----------
Depth Anything V2: https://depth-anything-v2.github.io/
ViT-B checkpoint : https://huggingface.co/depth-anything/Depth-Anything-V2-Base-hf
"""

import os
import time
import logging
import threading
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

import numpy as np

from app.config import settings
from app.schemas.upload import TileInfo
from app.schemas.infer import TileInferResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Device Detection
# ---------------------------------------------------------------------------

def _get_device() -> str:
    """
    Determine the best available compute device.

    Preference order: CUDA GPU → CPU.
    The .env DEVICE setting can force 'cpu' for development machines.

    Returns
    -------
    str  — 'cuda' or 'cpu'
    """
    import torch
    # Respect the explicit .env override first
    if settings.DEVICE.lower() == "cpu":
        logger.info("Device forced to CPU via settings.")
        return "cpu"
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        logger.info("CUDA available — using GPU: %s", gpu_name)
        return "cuda"
    logger.warning("CUDA not available — falling back to CPU. Inference will be slow.")
    return "cpu"


# ---------------------------------------------------------------------------
# Model Registry (module-level singleton + thread lock)
# ---------------------------------------------------------------------------

# Holds the loaded DepthAnythingV2 model keyed by variant string
_model_cache: Dict[str, Any] = {}
_model_lock = threading.Lock()

# ImageNet mean/std used by Depth Anything V2 pre-processing
_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD  = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _build_model(variant: str, device: str) -> Any:
    """
    Construct and return a Depth Anything V2 model for the given variant.

    This function uses the `timm` library to build the ViT backbone and
    attaches the DPT (Dense Prediction Transformer) head used for depth.

    Parameters
    ----------
    variant : str  — 'vits' | 'vitb' | 'vitl'
    device  : str  — 'cuda' | 'cpu'

    Returns
    -------
    torch.nn.Module  — loaded model in eval() mode.

    Notes
    -----
    We use the HuggingFace `transformers` pipeline approach as a fallback
    when the raw timm checkpoint is unavailable. Both paths are tried.
    The checkpoint is expected at:
      <project_root>/checkpoints/depth_anything_v2_<variant>.pth
    Download from: https://huggingface.co/depth-anything/Depth-Anything-V2-Base-hf
    """
    import torch

    # --- Try HuggingFace transformers pipeline (easiest setup) ---
    try:
        from transformers import pipeline as hf_pipeline
        hf_model_id = {
            "vits": "depth-anything/Depth-Anything-V2-Small-hf",
            "vitb": "depth-anything/Depth-Anything-V2-Base-hf",
            "vitl": "depth-anything/Depth-Anything-V2-Large-hf",
        }.get(variant, "depth-anything/Depth-Anything-V2-Base-hf")

        logger.info("Loading Depth Anything V2 (%s) from HuggingFace: %s", variant, hf_model_id)
        pipe = hf_pipeline(
            task="depth-estimation",
            model=hf_model_id,
            device=0 if device == "cuda" else -1,  # HF uses int device index
        )
        logger.info("HuggingFace pipeline loaded successfully.")
        return ("hf_pipeline", pipe)

    except Exception as hf_exc:
        logger.warning("HuggingFace pipeline failed (%s). Trying local checkpoint.", hf_exc)

    # --- Fallback: Load from local .pth checkpoint via timm ---
    ckpt_map = {
        "vits": "depth_anything_v2_vits.pth",
        "vitb": "depth_anything_v2_vitb.pth",
        "vitl": "depth_anything_v2_vitl.pth",
    }
    ckpt_filename = ckpt_map.get(variant, "depth_anything_v2_vitb.pth")
    ckpt_path = Path("checkpoints") / ckpt_filename

    if not ckpt_path.exists():
        raise FileNotFoundError(
            f"Model checkpoint not found at '{ckpt_path}'. "
            f"Download from https://huggingface.co/depth-anything "
            f"and place in the 'checkpoints/' directory."
        )

    # Import the DepthAnythingV2 class from the official repo
    # (expected to be placed in app/ml/depth_anything_v2/ by the team)
    try:
        from app.ml.depth_anything_v2.dpt import DepthAnythingV2 as DAV2

        encoder_configs = {
            "vits": {"encoder": "vits", "features": 64,  "out_channels": [48,  96,  192, 384]},
            "vitb": {"encoder": "vitb", "features": 128, "out_channels": [96,  192, 384, 768]},
            "vitl": {"encoder": "vitl", "features": 256, "out_channels": [256, 512, 1024, 1024]},
        }
        cfg = encoder_configs[variant]
        model = DAV2(**cfg)
        state_dict = torch.load(str(ckpt_path), map_location="cpu")
        model.load_state_dict(state_dict)
        model = model.to(device).eval()
        logger.info("Local checkpoint loaded: %s → device=%s", ckpt_path, device)
        return ("local", model)

    except ImportError:
        raise ImportError(
            "Depth Anything V2 source not found. "
            "Clone the repo into app/ml/depth_anything_v2/ or install via HuggingFace."
        )


def get_model(variant: Optional[str] = None) -> Tuple[str, Any]:
    """
    Return the cached model for `variant`, loading it on first call.

    Thread-safe via module-level lock — safe for concurrent FastAPI requests.

    Parameters
    ----------
    variant : str | None  — Model size; defaults to settings.DEPTH_MODEL_VARIANT.

    Returns
    -------
    Tuple[str, model]  — (backend_type, model_object)
    """
    variant = variant or settings.DEPTH_MODEL_VARIANT
    if variant not in _model_cache:
        with _model_lock:
            # Double-check after acquiring lock (classic double-checked locking)
            if variant not in _model_cache:
                device = _get_device()
                _model_cache[variant] = _build_model(variant, device)
                logger.info("Model '%s' cached in registry.", variant)
    return _model_cache[variant]


# ---------------------------------------------------------------------------
# Pre-processing
# ---------------------------------------------------------------------------

def _preprocess_tile(tile_array: np.ndarray, input_size: int) -> "torch.Tensor":
    """
    Convert a raw tile NumPy array to a normalised PyTorch tensor.

    Steps
    -----
    1. Ensure the array is (H, W, C) float32 with C=3 (RGB).
    2. Resize to (input_size × input_size) using bilinear interpolation.
    3. Apply ImageNet mean/std normalisation.
    4. Add batch dimension → (1, 3, H, W).

    Parameters
    ----------
    tile_array : np.ndarray  — shape (3, H, W) or (H, W, 3), float32 [0,1].
    input_size : int         — target spatial resolution for the ViT encoder.

    Returns
    -------
    torch.Tensor  — shape (1, 3, input_size, input_size), float32.
    """
    import torch
    import torch.nn.functional as F

    # --- Ensure (H, W, C) layout for PIL/OpenCV style operations ---
    if tile_array.ndim == 3 and tile_array.shape[0] in (1, 3, 4):
        # rasterio returns (C, H, W) — convert to (H, W, C)
        tile_array = np.transpose(tile_array, (1, 2, 0))

    # --- Use only the first 3 bands (RGB) even for multi-band GeoTIFFs ---
    if tile_array.shape[2] > 3:
        tile_array = tile_array[:, :, :3]
    elif tile_array.shape[2] == 1:
        # Panchromatic — repeat to 3 channels for the RGB model
        tile_array = np.repeat(tile_array, 3, axis=2)

    # --- Clip and ensure float32 [0, 1] range ---
    tile_array = np.clip(tile_array.astype(np.float32), 0.0, 1.0)

    # --- Normalise with ImageNet statistics ---
    tile_array = (tile_array - _IMAGENET_MEAN) / _IMAGENET_STD

    # --- Convert (H, W, C) → tensor (1, C, H, W) ---
    tensor = torch.from_numpy(tile_array).permute(2, 0, 1).unsqueeze(0)

    # --- Resize to model input resolution ---
    tensor = F.interpolate(
        tensor,
        size=(input_size, input_size),
        mode="bilinear",
        align_corners=False,
    )
    return tensor


# ---------------------------------------------------------------------------
# Single-tile Inference
# ---------------------------------------------------------------------------

def _infer_single_tile(
    tile_path: str,
    backend_type: str,
    model: Any,
    input_size: int,
    device: str,
) -> Tuple[np.ndarray, float]:
    """
    Run depth inference on one tile file and return a disparity array.

    Parameters
    ----------
    tile_path    : str   — Absolute path to the .npy tile array.
    backend_type : str   — 'hf_pipeline' or 'local'.
    model        : Any   — Loaded model object.
    input_size   : int   — Encoder input resolution.
    device       : str   — 'cuda' or 'cpu'.

    Returns
    -------
    disparity_np : np.ndarray  — Normalised disparity map, shape (H, W), float32 [0,1].
    elapsed_ms   : float       — Wall-clock inference time in milliseconds.
    """
    import torch

    tile_np = np.load(tile_path)  # shape: (C, H, W)
    orig_h = tile_np.shape[1]
    orig_w = tile_np.shape[2]

    t_start = time.perf_counter()

    if backend_type == "hf_pipeline":
        # --- HuggingFace pipeline path ---
        # HF pipeline expects a PIL image
        from PIL import Image
        # Transpose to (H, W, C) and scale to uint8 for PIL
        rgb_np = np.clip(tile_np[:3].transpose(1, 2, 0) * 255, 0, 255).astype(np.uint8)
        pil_img = Image.fromarray(rgb_np)
        result = model(pil_img)
        # The pipeline returns a depth dict; extract the depth array
        depth_tensor = result["predicted_depth"]
        if hasattr(depth_tensor, "numpy"):
            disparity_np = depth_tensor.numpy()
        else:
            disparity_np = np.array(depth_tensor)

    else:
        # --- Local checkpoint path ---
        with torch.no_grad():
            tensor = _preprocess_tile(tile_np, input_size).to(device)
            raw_output = model(tensor)

            # Output is (1, 1, H, W) or (1, H, W) — squeeze to (H, W)
            if raw_output.ndim == 4:
                raw_output = raw_output.squeeze(0).squeeze(0)
            elif raw_output.ndim == 3:
                raw_output = raw_output.squeeze(0)

            disparity_np = raw_output.cpu().numpy()

    elapsed_ms = (time.perf_counter() - t_start) * 1000.0

    # --- Resize disparity back to original tile resolution ---
    import torch
    disp_tensor = torch.from_numpy(disparity_np).unsqueeze(0).unsqueeze(0)
    disp_resized = torch.nn.functional.interpolate(
        disp_tensor, size=(orig_h, orig_w), mode="bilinear", align_corners=False
    )
    disparity_np = disp_resized.squeeze().numpy()

    # --- Normalise to [0, 1] for a consistent downstream contract ---
    d_min = disparity_np.min()
    d_max = disparity_np.max()
    if d_max > d_min:
        disparity_np = (disparity_np - d_min) / (d_max - d_min)
    else:
        # Flat region — zero out
        disparity_np = np.zeros_like(disparity_np)

    return disparity_np.astype(np.float32), elapsed_ms


# ---------------------------------------------------------------------------
# Tile Stitching
# ---------------------------------------------------------------------------

def _stitch_disparity_tiles(
    tile_results: List[TileInferResult],
    tile_infos: List[TileInfo],
    full_width: int,
    full_height: int,
    overlap: int,
) -> np.ndarray:
    """
    Reconstruct a full-resolution disparity map by averaging overlapping tile regions.

    Rather than hard-cutting at tile boundaries (which creates visible seams),
    we accumulate a weighted sum and a count map, then divide at the end.
    This produces smooth blending in the TILE_OVERLAP border zones.

    Parameters
    ----------
    tile_results : List[TileInferResult]  — Inference outputs (disparity paths).
    tile_infos   : List[TileInfo]         — Spatial metadata for each tile.
    full_width   : int  — Width of the original full raster.
    full_height  : int  — Height of the original full raster.
    overlap      : int  — Pixel overlap used during slicing.

    Returns
    -------
    np.ndarray  — Full-resolution stitched disparity map, float32 [0,1].
    """
    # Accumulator arrays — float64 for numerical stability during accumulation
    accum = np.zeros((full_height, full_width), dtype=np.float64)
    count = np.zeros((full_height, full_width), dtype=np.float64)

    # Build a lookup from tile_index → TileInfo for fast access
    info_by_index = {(ti.tile_index[0], ti.tile_index[1]): ti for ti in tile_infos}

    for result in tile_results:
        row_idx, col_idx = result.tile_index
        ti = info_by_index.get((row_idx, col_idx))
        if ti is None:
            logger.warning("No TileInfo found for index (%d,%d), skipping.", row_idx, col_idx)
            continue

        col_off, row_off = ti.pixel_offset
        tw = ti.tile_width
        th = ti.tile_height

        # Load the saved disparity array for this tile
        disp_np = np.load(result.disparity_path)

        # Resize disparity to match the (potentially edge-clipped) tile dimensions
        if disp_np.shape != (th, tw):
            import torch
            t = torch.from_numpy(disp_np).unsqueeze(0).unsqueeze(0)
            t = torch.nn.functional.interpolate(t, size=(th, tw), mode="bilinear", align_corners=False)
            disp_np = t.squeeze().numpy()

        # Accumulate into the global map
        accum[row_off:row_off + th, col_off:col_off + tw] += disp_np
        count[row_off:row_off + th, col_off:col_off + tw] += 1.0

    # Avoid division by zero for any uncovered pixels (shouldn't happen)
    count = np.where(count == 0, 1.0, count)
    stitched = (accum / count).astype(np.float32)

    # Final global normalisation to [0, 1]
    s_min = stitched.min()
    s_max = stitched.max()
    if s_max > s_min:
        stitched = (stitched - s_min) / (s_max - s_min)

    return stitched


# ---------------------------------------------------------------------------
# Main Inference Entry-Point
# ---------------------------------------------------------------------------

def run_inference(
    job_id: str,
    tile_infos: List[TileInfo],
    full_width: int,
    full_height: int,
    model_variant: Optional[str] = None,
    input_size: int = 518,
    overlap: int = 64,
) -> Tuple[List[TileInferResult], str, str, str]:
    """
    Run depth inference on all tiles for a given job and stitch the results.

    This is the primary function called by the inference router. It:
    1. Loads (or retrieves cached) model.
    2. Iterates over all tile .npy files.
    3. Runs per-tile inference.
    4. Saves per-tile disparity arrays.
    5. Stitches all tiles into a single full-resolution disparity map.
    6. Persists the stitched map and returns statistics.

    Parameters
    ----------
    job_id        : str             — Unique job identifier from the upload step.
    tile_infos    : List[TileInfo]  — Tile descriptors produced during ingestion.
    full_width    : int             — Original raster width in pixels.
    full_height   : int             — Original raster height in pixels.
    model_variant : str | None      — Model size override; defaults to config.
    input_size    : int             — ViT encoder input resolution.
    overlap       : int             — Tile overlap used during slicing.

    Returns
    -------
    tile_results        : List[TileInferResult]  — Per-tile inference stats.
    stitched_path       : str  — Path to stitched disparity .npy.
    actual_variant      : str  — Variant that was actually used.
    device_str          : str  — Device used ('cuda' | 'cpu').
    """
    import torch

    # --- Resolve model variant ---
    actual_variant = model_variant or settings.DEPTH_MODEL_VARIANT
    device_str = _get_device()

    # --- Load / retrieve cached model ---
    logger.info("Fetching model for variant=%s …", actual_variant)
    backend_type, model = get_model(actual_variant)

    # --- Per-tile inference loop ---
    tile_results: List[TileInferResult] = []
    upload_base = Path(settings.UPLOAD_DIR) / job_id
    output_tile_dir = Path(settings.OUTPUT_DIR) / job_id / "disparity_tiles"
    output_tile_dir.mkdir(parents=True, exist_ok=True)

    for ti in tile_infos:
        row_idx, col_idx = ti.tile_index
        tile_npy_abs = Path(settings.UPLOAD_DIR) / ti.saved_path

        if not tile_npy_abs.exists():
            logger.error("Tile file not found: %s — skipping.", tile_npy_abs)
            continue

        logger.debug("Inferring tile (%d, %d) …", row_idx, col_idx)

        try:
            disparity_np, elapsed_ms = _infer_single_tile(
                tile_path=str(tile_npy_abs),
                backend_type=backend_type,
                model=model,
                input_size=input_size,
                device=device_str,
            )
        except Exception as exc:
            logger.error("Inference failed for tile (%d,%d): %s", row_idx, col_idx, exc)
            continue

        # Persist per-tile disparity
        disp_filename = f"disp_{row_idx:03d}_{col_idx:03d}.npy"
        disp_path = output_tile_dir / disp_filename
        np.save(str(disp_path), disparity_np)

        tile_results.append(TileInferResult(
            tile_index=(row_idx, col_idx),
            disparity_path=str(disp_path),
            min_disparity=float(disparity_np.min()),
            max_disparity=float(disparity_np.max()),
            mean_disparity=float(disparity_np.mean()),
            inference_ms=elapsed_ms,
        ))

        logger.info(
            "Tile (%d,%d) done: min=%.3f max=%.3f mean=%.3f  [%.1f ms]",
            row_idx, col_idx,
            disparity_np.min(), disparity_np.max(), disparity_np.mean(),
            elapsed_ms,
        )

    # --- Stitch all tiles into the full-resolution disparity map ---
    logger.info("Stitching %d tiles into full disparity map …", len(tile_results))
    stitched = _stitch_disparity_tiles(
        tile_results=tile_results,
        tile_infos=tile_infos,
        full_width=full_width,
        full_height=full_height,
        overlap=overlap,
    )

    # Persist the stitched map
    stitched_dir = Path(settings.OUTPUT_DIR) / job_id
    stitched_dir.mkdir(parents=True, exist_ok=True)
    stitched_path = str(stitched_dir / "disparity_full.npy")
    np.save(stitched_path, stitched)
    logger.info("Stitched disparity map saved to %s  shape=%s", stitched_path, stitched.shape)

    return tile_results, stitched_path, actual_variant, device_str

"""
tests/test_pipeline.py
----------------------
End-to-End Test Suite for DepthWizard Backend.

Tests the full sequential pipeline:
1. Health Check
2. User Registration & JWT Login
3. Synthetic GeoTIFF / Image Upload & Tile Ingestion (/api/v1/upload)
4. AI Depth Estimation (/api/v1/infer)
5. Scale Calibration with CSF & RANSAC (/api/v1/calibrate)
"""

import io
import sys
from pathlib import Path

# Ensure project root is in python module search path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PIL import Image
import rasterio
from rasterio.transform import from_origin
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def test_health():
    """Verify backend liveness."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    print("[PASS] Health Check Passed")


def get_auth_token() -> str:
    """Helper to register and login a user and return the JWT token."""
    email = f"testuser_{np.random.randint(1000, 9999)}@depthwizard.ai"
    password = "SecurePassword123!"

    reg_resp = client.post(
        "/auth/register",
        json={"email": email, "password": password, "full_name": "Test Engineer"},
    )
    assert reg_resp.status_code == 201, f"Register failed: {reg_resp.text}"

    login_resp = client.post(
        "/auth/login/json",
        json={"email": email, "password": password},
    )
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    token_data = login_resp.json()
    return token_data["access_token"]


def test_auth_flow():
    """Register and login a test user, verifying JWT token and /auth/me profile."""
    token = get_auth_token()
    assert token is not None

    me_resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert "email" in me_resp.json()
    print("[PASS] Auth Flow Passed")



def create_synthetic_geotiff(width: int = 512, height: int = 512) -> bytes:
    """Creates an in-memory synthetic GeoTIFF with 3 RGB bands and affine coordinates."""
    buffer = io.BytesIO()
    transform = from_origin(500000.0, 4200000.0, 1.0, 1.0)  # 1m GSD

    # Generate synthetic terrain gradient
    x = np.linspace(0, 1, width)
    y = np.linspace(0, 1, height)
    xx, yy = np.meshgrid(x, y)
    elevation_gradient = (np.sin(xx * 3.14) * np.cos(yy * 3.14) * 255).astype(np.uint8)

    with rasterio.open(
        buffer,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=3,
        dtype=rasterio.uint8,
        crs="EPSG:32632",
        transform=transform,
    ) as dst:
        dst.write(elevation_gradient, 1)  # Red
        dst.write(elevation_gradient, 2)  # Green
        dst.write(elevation_gradient, 3)  # Blue

    buffer.seek(0)
    return buffer.read()


def test_full_pipeline():
    """Runs Upload -> Infer -> Calibrate end-to-end."""
    token = get_auth_token()
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Upload synthetic GeoTIFF
    geotiff_bytes = create_synthetic_geotiff(512, 512)
    files = {"file": ("synthetic_terrain.tif", geotiff_bytes, "image/tiff")}

    upload_resp = client.post("/api/v1/upload", headers=headers, files=files)
    assert upload_resp.status_code in (200, 201), f"Upload failed: {upload_resp.text}"
    upload_data = upload_resp.json()
    job_id = upload_data["job_id"]
    print(f"[PASS] Upload & Ingestion Passed: job_id={job_id}, tiles={upload_data['tile_count']}")

    # 2. Run Inference
    infer_payload = {
        "job_id": job_id,
        "model_variant": "vits",  # small for rapid test
        "input_size": 256,
    }
    infer_resp = client.post("/api/v1/infer", headers=headers, json=infer_payload)
    assert infer_resp.status_code == 200, f"Inference failed: {infer_resp.text}"
    infer_data = infer_resp.json()
    print(f"[PASS] Depth Inference Passed: {infer_data['tiles_processed']} tiles in {infer_data['total_ms']}ms")

    # 3. Run Calibration (with synthetic GCPs)
    calibrate_payload = {
        "job_id": job_id,
        "gcps": [
            {"pixel_col": 50, "pixel_row": 50, "elevation_m": 120.5, "source": "survey_gcp_1"},
            {"pixel_col": 200, "pixel_row": 200, "elevation_m": 145.2, "source": "survey_gcp_2"},
            {"pixel_col": 400, "pixel_row": 400, "elevation_m": 110.8, "source": "survey_gcp_3"},
            {"pixel_col": 100, "pixel_row": 400, "elevation_m": 130.0, "source": "survey_gcp_4"},
        ],
        "csf_max_iterations": 100,
        "ransac_max_trials": 500,
    }
    calib_resp = client.post("/api/v1/calibrate", headers=headers, json=calibrate_payload)
    assert calib_resp.status_code == 200, f"Calibration failed: {calib_resp.text}"
    calib_data = calib_resp.json()
    print(f"[PASS] Calibration Passed: scale={calib_data['scale_factor_s']}, shift={calib_data['shift_translation_t']}m")
    print(f"       Accuracy Metrics: RMSE={calib_data['metrics']['rmse_metres']}m, LE90={calib_data['metrics']['le90_metres']}m")

    # 4. Generate 3D Mesh
    mesh_resp = client.post("/api/v1/export/mesh", headers=headers, json={"job_id": job_id, "format": "obj", "downsample_factor": 2})
    assert mesh_resp.status_code == 200, f"Mesh export failed: {mesh_resp.text}"
    mesh_data = mesh_resp.json()
    print(f"[PASS] 3D Mesh Export Passed: {mesh_data['vertex_count']:,} vertices, {mesh_data['face_count']:,} faces ({mesh_data['file_size_bytes']:,} bytes)")

    # 5. Extract Elevation Contours (GeoJSON)
    contour_resp = client.post("/api/v1/export/contours", headers=headers, json={"job_id": job_id, "interval_m": 5.0})
    assert contour_resp.status_code == 200, f"Contour generation failed: {contour_resp.text}"
    contour_data = contour_resp.json()
    print(f"[PASS] Contour Extraction Passed: {contour_data['total_contour_lines']} isolines generated")

    # 6. Volumetric Cut & Fill Analytics
    vol_resp = client.post("/api/v1/export/volume", headers=headers, json={"job_id": job_id, "base_elevation_m": 120.0})
    assert vol_resp.status_code == 200, f"Volume calculation failed: {vol_resp.text}"
    vol_data = vol_resp.json()
    print(f"[PASS] Volumetrics Passed: Cut={vol_data['cut_volume_m3']:,.1f} m3, Fill={vol_data['fill_volume_m3']:,.1f} m3, Area={vol_data['surface_area_m2']:,.1f} m2")

    # 7. Download GeoTIFF DSM
    tif_resp = client.get(f"/api/v1/export/geotiff?job_id={job_id}", headers=headers)
    assert tif_resp.status_code == 200, f"GeoTIFF download failed: {tif_resp.status_code}"
    print(f"[PASS] GeoTIFF DSM Stream Passed: Received {len(tif_resp.content):,} bytes")


if __name__ == "__main__":
    print("=" * 60)
    print("STARTING DEPTHWIZARD END-TO-END PIPELINE TEST")
    print("=" * 60)
    test_health()
    test_full_pipeline()
    print("=" * 60)
    print("[SUCCESS] ALL PIPELINE STAGES PASSED CLEANLY!")
    print("=" * 60)

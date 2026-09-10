// Auth types — match backend app/schemas/user.py
export interface User {
  id: number;
  email: string;
  is_active: boolean;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
}

export interface UserLogin {
  email: string;
  password: string;
}

// Upload types — match backend app/schemas/upload.py
export interface GeospatialMetadata {
  crs_epsg: number | null;
  crs_wkt: string | null;
  bounds: [number, number, number, number] | null;
  resolution: [number, number] | null;
  width: number;
  height: number;
  band_count: number;
  is_georeferenced: boolean;
  gsd_metres: number | null;
}

export interface TileInfo {
  tile_index: [number, number];
  pixel_offset: [number, number];
  tile_width: number;
  tile_height: number;
  affine_transform: number[];
  saved_path: string;
}

export interface UploadResponse {
  job_id: string;
  filename: string;
  file_type: string;
  metadata: GeospatialMetadata;
  tiles: TileInfo[];
  tile_count: number;
  message: string;
}

// Inference types — match backend app/schemas/infer.py
export interface TileInferResult {
  tile_index: [number, number];
  disparity_path: string;
  min_disparity: number;
  max_disparity: number;
  mean_disparity: number;
  inference_ms: number;
}

export interface InferenceResponse {
  job_id: string;
  model_variant: string;
  device: string;
  tiles_processed: number;
  total_ms: number;
  tile_results: TileInferResult[];
  disparity_map_path: string;
  message: string;
}

// Calibration types — match backend app/schemas/calibrate.py
export interface CalibrationMetrics {
  rmse_metres: number;
  mae_metres: number;
  le90_metres: number;
  inlier_count: number;
  inlier_ratio: number;
  ground_point_count: number;
}

export interface GroundControlPoint {
  pixel_col: number;
  pixel_row: number;
  elevation_m: number;
  source: string;
}

export interface CalibrationResponse {
  job_id: string;
  scale_factor_s: number;
  shift_translation_t: number;
  metrics: CalibrationMetrics;
  dsm_npy_path: string;
  dsm_geotiff_path: string | null;
  calibration_ms: number;
  message: string;
}

// Export types — match backend app/schemas/export.py
export interface MeshExportResponse {
  job_id: string;
  format: string;
  vertex_count: number;
  face_count: number;
  mesh_path: string;
  download_url: string;
  file_size_bytes: number;
  generation_ms: number;
  message: string;
}

export interface ContourExportResponse {
  job_id: string;
  interval_m: number;
  total_contour_lines: number;
  min_elevation_m: number;
  max_elevation_m: number;
  geojson: Record<string, any>;
  generation_ms: number;
  message: string;
}

export interface VolumeResponse {
  job_id: string;
  base_elevation_m: number;
  cut_volume_m3: number;
  fill_volume_m3: number;
  net_volume_m3: number;
  surface_area_m2: number;
  true_surface_area_m2: number;
  min_elevation_m: number;
  max_elevation_m: number;
  mean_elevation_m: number;
  computation_ms: number;
  message: string;
}
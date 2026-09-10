export interface User {
  id: string;
  email: string;
  is_active: boolean;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
}

export interface RasterMetadata {
  crs_epsg: number | null;
  crs_wkt: string | null;
  bounds: [number, number, number, number] | null;
  resolution: [number, number] | null;
  dimensions: {
    width: number;
    height: number;
    channels: number;
  };
  tiles_info?: {
    tile_count: number;
    grid_size: [number, number];
    tile_size: number;
    overlap: number;
  };
}

export interface UploadResponse {
  job_id: string;
  filename: string;
  file_type: string;
  metadata: RasterMetadata;
}

export interface InferenceResponse {
  job_id: string;
  status: string;
  model_used: string;
  depth_map_path: string;
  shape: [number, number];
  relative_depth_range: [number, number];
}

export interface GCPPoint {
  x: number;
  y: number;
  true_z: number;
}

export interface CalibrationMetrics {
  rmse_z: number;
  mae_z: number;
  le90: number;
  asprs_vertical_accuracy_class: string;
  samples_count: number;
}

export interface CalibrationResponse {
  job_id: string;
  status: string;
  scale: number;
  bias: number;
  metrics: CalibrationMetrics;
  ground_ratio: number;
  metric_dsm_path: string;
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

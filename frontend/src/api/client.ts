import axios from 'axios';
import type {
  AuthResponse,
  UploadResponse,
  InferenceResponse,
  CalibrationResponse,
  GCPPoint,
  VolumeResponse,
  MeshExportResponse,
  ContourExportResponse,
} from '../types';

export const API_BASE_URL = 'http://127.0.0.1:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('depthwizard_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export const authApi = {
  login: async (username: string, password: string): Promise<AuthResponse> => {
    const params = new URLSearchParams();
    params.append('username', username);
    params.append('password', password);
    const res = await api.post<AuthResponse>('/auth/login', params, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
    return res.data;
  },

  register: async (email: string, password: string): Promise<any> => {
    const res = await api.post('/auth/register', { email, password });
    return res.data;
  },
};

export const healthApi = {
  checkBackend: async (): Promise<boolean> => {
    try {
      const res = await api.get('/');
      return res.status === 200;
    } catch {
      return false;
    }
  },
};

export const pipelineApi = {
  upload: async (file: File): Promise<UploadResponse> => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await api.post<UploadResponse>('/api/v1/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return res.data;
  },

  infer: async (jobId: string, modelName: string = 'vits'): Promise<InferenceResponse> => {
    const res = await api.post<InferenceResponse>('/api/v1/infer', {
      job_id: jobId,
      model_name: modelName,
    });
    return res.data;
  },

  calibrate: async (
    jobId: string,
    params: {
      cloth_resolution?: number;
      class_threshold?: number;
      time_step?: number;
      gcp_points?: GCPPoint[];
    }
  ): Promise<CalibrationResponse> => {
    const res = await api.post<CalibrationResponse>('/api/v1/calibrate', {
      job_id: jobId,
      cloth_resolution: params.cloth_resolution ?? 1.5,
      class_threshold: params.class_threshold ?? 0.5,
      time_step: params.time_step ?? 0.65,
      gcp_points: params.gcp_points ?? [],
    });
    return res.data;
  },

  generateMesh: async (
    jobId: string,
    format: 'obj' | 'ply' = 'obj',
    downsampleFactor: number = 2,
    zExaggeration: number = 1.0
  ): Promise<MeshExportResponse> => {
    const res = await api.post<MeshExportResponse>('/api/v1/export/mesh', {
      job_id: jobId,
      format,
      downsample_factor: downsampleFactor,
      include_texture: true,
      z_exaggeration: zExaggeration,
    });
    return res.data;
  },

  getMeshDownloadUrl: (jobId: string, format: 'obj' | 'ply' = 'obj') => {
    return `${API_BASE_URL}/api/v1/export/mesh/download?job_id=${jobId}&format=${format}`;
  },

  getContours: async (
    jobId: string,
    interval: number = 2.0,
    simplifyTolerance: number = 0.5
  ): Promise<ContourExportResponse> => {
    const res = await api.post<ContourExportResponse>('/api/v1/export/contours', {
      job_id: jobId,
      interval_m: interval,
      simplify_tolerance: simplifyTolerance,
    });
    return res.data;
  },

  calculateVolume: async (jobId: string, baseLevel?: number): Promise<VolumeResponse> => {
    const res = await api.post<VolumeResponse>('/api/v1/export/volume', {
      job_id: jobId,
      base_elevation_m: baseLevel,
    });
    return res.data;
  },

  getGeoTiffUrl: (jobId: string) => {
    return `${API_BASE_URL}/api/v1/export/geotiff?job_id=${jobId}`;
  },

  downloadFile: async (url: string, filename: string) => {
    const token = localStorage.getItem('depthwizard_token');
    const response = await fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) {
      throw new Error(`Download failed with status ${response.status}`);
    }
    const blob = await response.blob();
    const downloadUrl = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = downloadUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(downloadUrl);
    document.body.removeChild(a);
  },
};

export default api;

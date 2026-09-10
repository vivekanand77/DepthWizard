import React, { useState, useRef } from 'react';
import { UploadCloud, CheckCircle, ArrowRight, AlertTriangle } from 'lucide-react';
import { pipelineApi } from '../api/client';
import type { UploadResponse } from '../types';

interface UploadStepProps {
  token: string | null;
  onUploadSuccess: (data: UploadResponse) => void;
  onOpenAuth: () => void;
  existingData: UploadResponse | null;
  onNext: () => void;
}

export const UploadStep: React.FC<UploadStepProps> = ({
  token,
  onUploadSuccess,
  onOpenAuth,
  existingData,
  onNext,
}) => {
  const [isDragging, setIsDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    if (!token) {
      onOpenAuth();
      return;
    }
    setError(null);
    setLoading(true);

    try {
      const data = await pipelineApi.upload(file);
      onUploadSuccess(data);
    } catch (err: any) {
      console.error(err);
      const detail = err.response?.data?.detail;
      setError(
        typeof detail === 'string'
          ? detail
          : 'Failed to upload orthomosaic. Ensure backend is running and valid image file is provided.'
      );
    } finally {
      setLoading(false);
    }
  };

  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const onDragLeave = () => {
    setIsDragging(false);
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFile(e.dataTransfer.files[0]);
    }
  };

  return (
    <div className="step-card">
      <div className="step-header">
        <div>
          <h2>Stage 1: Ingest Geospatial Raster</h2>
          <p className="step-desc">
            Upload aerial drone orthomosaics, satellite imagery, or standard GeoTIFF/PNG/JPEG files.
          </p>
        </div>
      </div>

      {!token && (
        <div className="alert alert-warning">
          <AlertTriangle className="icon-sm" />
          <span>You must be logged in to upload files and run the AI pipeline.</span>
          <button className="btn-secondary btn-xs" onClick={onOpenAuth}>
            Login Now
          </button>
        </div>
      )}

      {error && (
        <div className="alert alert-error">
          <AlertTriangle className="icon-sm" />
          <span>{error}</span>
        </div>
      )}

      <div
        className={`dropzone ${isDragging ? 'dragging' : ''} ${loading ? 'loading' : ''}`}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={() => fileInputRef.current?.click()}
      >
        <input
          type="file"
          ref={fileInputRef}
          className="hidden-input"
          accept=".tif,.tiff,.png,.jpg,.jpeg"
          onChange={(e) => {
            if (e.target.files && e.target.files.length > 0) {
              handleFile(e.target.files[0]);
            }
          }}
        />

        <div className="dropzone-content">
          <div className="dropzone-icon-circle">
            <UploadCloud className="icon-lg" />
          </div>
          <h3>{loading ? 'Processing Raster...' : 'Click to Upload or Drag & Drop'}</h3>
          <p className="dropzone-hint">
            Supported formats: GeoTIFF (.tif, .tiff), PNG, JPEG. Metadata and spatial CRS will be auto-extracted.
          </p>
        </div>
      </div>

      {existingData && (
        <div className="metadata-container">
          <div className="metadata-header">
            <div className="flex-center gap-2">
              <CheckCircle className="icon-success icon-sm" />
              <h3>Ingestion Complete: {existingData.filename}</h3>
            </div>
            <span className="badge badge-primary">Job ID: {existingData.job_id.slice(0, 8)}...</span>
          </div>

          <div className="meta-grid">
            <div className="meta-card">
              <span className="meta-label">Dimensions</span>
              <span className="meta-value">
                {existingData.metadata.dimensions.width} &times; {existingData.metadata.dimensions.height} px
              </span>
              <span className="meta-sub">{existingData.metadata.dimensions.channels} color channels</span>
            </div>

            <div className="meta-card">
              <span className="meta-label">Coordinate System (CRS)</span>
              <span className="meta-value">
                {existingData.metadata.crs_epsg
                  ? `EPSG:${existingData.metadata.crs_epsg}`
                  : 'Local Pixel Coordinates'}
              </span>
              <span className="meta-sub">
                {existingData.metadata.crs_epsg ? 'Projected / Georeferenced' : 'Unreferenced / Relative'}
              </span>
            </div>

            <div className="meta-card">
              <span className="meta-label">Ground Sampling (GSD)</span>
              <span className="meta-value">
                {existingData.metadata.resolution
                  ? `${Math.abs(existingData.metadata.resolution[0]).toFixed(3)} m/px`
                  : 'Default 0.05 m/px'}
              </span>
              <span className="meta-sub">Pixel Scale</span>
            </div>

            <div className="meta-card">
              <span className="meta-label">Tile Grid Breakdown</span>
              <span className="meta-value">
                {existingData.metadata.tiles_info?.tile_count || 1} Tile(s)
              </span>
              <span className="meta-sub">
                Grid: {existingData.metadata.tiles_info?.grid_size.join(' × ') || '1 × 1'}
              </span>
            </div>
          </div>

          <div className="step-actions">
            <button className="btn-primary" onClick={onNext}>
              <span>Proceed to AI Depth Inference</span>
              <ArrowRight className="icon-sm" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

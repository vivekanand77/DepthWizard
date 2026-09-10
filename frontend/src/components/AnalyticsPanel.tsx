import React, { useState } from 'react';
import {
  Download,
  Calculator,
  Compass,
  FileCode,
  Layers,
  MapPin,
  CheckCircle,
  ArrowDownToLine,
  TrendingUp,
} from 'lucide-react';
import { Viewer3D } from './Viewer3D';
import { pipelineApi } from '../api/client';
import type { VolumeResponse, ContourExportResponse } from '../types';

interface AnalyticsPanelProps {
  jobId: string;
  onBack: () => void;
}

export const AnalyticsPanel: React.FC<AnalyticsPanelProps> = ({ jobId, onBack }) => {
  const [activeTab, setActiveTab] = useState<'3d' | 'volumetrics' | 'contours' | 'exports'>('3d');
  
  // Volumetrics state
  const [baseDatum, setBaseDatum] = useState<number | ''>('');
  const [volumeResult, setVolumeResult] = useState<VolumeResponse | null>(null);
  const [volumeLoading, setVolumeLoading] = useState(false);
  const [volumeError, setVolumeError] = useState<string | null>(null);

  // Contours state
  const [contourInterval, setContourInterval] = useState<number>(2.0);
  const [contourResult, setContourResult] = useState<ContourExportResponse | null>(null);
  const [contourLoading, setContourLoading] = useState(false);
  const [contourError, setContourError] = useState<string | null>(null);

  // Download handling
  const [downloading, setDownloading] = useState<string | null>(null);

  const handleCalculateVolume = async () => {
    setVolumeLoading(true);
    setVolumeError(null);
    try {
      const data = await pipelineApi.calculateVolume(
        jobId,
        baseDatum === '' ? undefined : Number(baseDatum)
      );
      setVolumeResult(data);
    } catch (err: any) {
      console.error(err);
      setVolumeError(err.response?.data?.detail || 'Failed to compute volumetrics');
    } finally {
      setVolumeLoading(false);
    }
  };

  const handleGenerateContours = async () => {
    setContourLoading(true);
    setContourError(null);
    try {
      const data = await pipelineApi.getContours(jobId, contourInterval);
      setContourResult(data);
    } catch (err: any) {
      console.error(err);
      setContourError(err.response?.data?.detail || 'Failed to generate contours');
    } finally {
      setContourLoading(false);
    }
  };

  const triggerDownload = async (type: 'obj' | 'ply' | 'geotiff' | 'geojson') => {
    setDownloading(type);
    try {
      if (type === 'obj') {
        await pipelineApi.generateMesh(jobId, 'obj', 1, 1.0);
        await pipelineApi.downloadFile(pipelineApi.getMeshDownloadUrl(jobId, 'obj'), `depthwizard_${jobId.slice(0, 8)}.obj`);
      } else if (type === 'ply') {
        await pipelineApi.generateMesh(jobId, 'ply', 1, 1.0);
        await pipelineApi.downloadFile(pipelineApi.getMeshDownloadUrl(jobId, 'ply'), `depthwizard_${jobId.slice(0, 8)}.ply`);
      } else if (type === 'geotiff') {
        await pipelineApi.downloadFile(pipelineApi.getGeoTiffUrl(jobId), `depthwizard_dsm_${jobId.slice(0, 8)}.tif`);
      } else if (type === 'geojson') {
        const data = await pipelineApi.getContours(jobId, contourInterval);
        const blob = new Blob([JSON.stringify(data.geojson, null, 2)], { type: 'application/geo+json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `depthwizard_contours_${jobId.slice(0, 8)}.geojson`;
        a.click();
        URL.revokeObjectURL(url);
      }
    } catch (err) {
      console.error('Download error:', err);
      alert('Failed to download file. Please check backend connection.');
    } finally {
      setDownloading(null);
    }
  };

  return (
    <div className="analytics-layout">
      <div className="analytics-nav">
        <button
          className={`tab-btn ${activeTab === '3d' ? 'active' : ''}`}
          onClick={() => setActiveTab('3d')}
        >
          <Compass className="icon-sm" />
          <span>Interactive 3D Studio</span>
        </button>

        <button
          className={`tab-btn ${activeTab === 'volumetrics' ? 'active' : ''}`}
          onClick={() => setActiveTab('volumetrics')}
        >
          <Calculator className="icon-sm" />
          <span>Cut & Fill Volumetrics</span>
        </button>

        <button
          className={`tab-btn ${activeTab === 'contours' ? 'active' : ''}`}
          onClick={() => setActiveTab('contours')}
        >
          <Layers className="icon-sm" />
          <span>Elevation Isolines</span>
        </button>

        <button
          className={`tab-btn ${activeTab === 'exports' ? 'active' : ''}`}
          onClick={() => setActiveTab('exports')}
        >
          <Download className="icon-sm" />
          <span>GIS Export Center</span>
        </button>
      </div>

      <div className="analytics-content">
        {activeTab === '3d' && (
          <div className="tab-pane">
            <Viewer3D jobId={jobId} />
          </div>
        )}

        {activeTab === 'volumetrics' && (
          <div className="tab-pane-padded">
            <div className="pane-header">
              <div>
                <h3>Stockpile & Earthwork Volumetrics</h3>
                <p className="step-desc">
                  Accurately computes cut volume, fill volume, net earthwork balance, and 3D sloped surface area.
                </p>
              </div>
            </div>

            <div className="volume-control-box">
              <div className="form-group">
                <label>Base Level / Datum Elevation (Optional - defaults to minimum ground elevation):</label>
                <div className="input-row">
                  <input
                    type="number"
                    step="0.1"
                    placeholder="Auto-detected base datum (meters)"
                    value={baseDatum}
                    onChange={(e) => setBaseDatum(e.target.value === '' ? '' : Number(e.target.value))}
                  />
                  <button
                    className="btn-primary"
                    onClick={handleCalculateVolume}
                    disabled={volumeLoading}
                  >
                    {volumeLoading ? 'Computing Volume...' : 'Calculate Volumetrics'}
                  </button>
                </div>
              </div>

              {volumeError && <div className="alert alert-error">{volumeError}</div>}

              {volumeResult && (
                <div className="meta-grid mt-4">
                  <div className="meta-card highlight-cut">
                    <span className="meta-label">Cut Volume</span>
                    <span className="meta-value">{volumeResult.cut_volume_m3.toLocaleString()} m³</span>
                    <span className="meta-sub">Material to excavate</span>
                  </div>

                  <div className="meta-card highlight-fill">
                    <span className="meta-label">Fill Volume</span>
                    <span className="meta-value">{volumeResult.fill_volume_m3.toLocaleString()} m³</span>
                    <span className="meta-sub">Material required to fill</span>
                  </div>

                  <div className="meta-card">
                    <span className="meta-label">Net Earthwork Balance</span>
                    <span className="meta-value">{volumeResult.net_volume_m3.toLocaleString()} m³</span>
                    <span className="meta-sub">Cut minus fill</span>
                  </div>

                  <div className="meta-card">
                    <span className="meta-label">3D Sloped Surface Area</span>
                    <span className="meta-value">{volumeResult.true_surface_area_m2.toLocaleString()} m²</span>
                    <span className="meta-sub">True terrain area</span>
                  </div>

                  <div className="meta-card">
                    <span className="meta-label">Planar Footprint Area</span>
                    <span className="meta-value">{volumeResult.surface_area_m2.toLocaleString()} m²</span>
                    <span className="meta-sub">2D Projective area</span>
                  </div>

                  <div className="meta-card">
                    <span className="meta-label">Datum Used</span>
                    <span className="meta-value">{volumeResult.base_elevation_m.toFixed(2)} m</span>
                    <span className="meta-sub">Base elevation plane</span>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'contours' && (
          <div className="tab-pane-padded">
            <div className="pane-header">
              <div>
                <h3>RFC 7946 GeoJSON Vector Contours</h3>
                <p className="step-desc">
                  Extracts standard elevation isolines for GIS, QGIS, ArcGIS, and civil surveying.
                </p>
              </div>
            </div>

            <div className="contour-control-box">
              <div className="form-group">
                <label>Contour Interval (meters):</label>
                <div className="input-row">
                  <select
                    value={contourInterval}
                    onChange={(e) => setContourInterval(parseFloat(e.target.value))}
                    className="select-input"
                  >
                    <option value={0.5}>0.5 meter (Dense)</option>
                    <option value={1.0}>1.0 meter (Standard Detailed)</option>
                    <option value={2.0}>2.0 meters (Recommended)</option>
                    <option value={5.0}>5.0 meters (Regional Topo)</option>
                    <option value={10.0}>10.0 meters (Mountainous)</option>
                  </select>
                  <button
                    className="btn-primary"
                    onClick={handleGenerateContours}
                    disabled={contourLoading}
                  >
                    {contourLoading ? 'Extracting Isolines...' : 'Generate Contours'}
                  </button>
                </div>
              </div>

              {contourError && <div className="alert alert-error">{contourError}</div>}

              {contourResult && (
                <div className="contour-summary">
                  <div className="flex-center gap-2">
                    <CheckCircle className="icon-success icon-sm" />
                    <h4>Generated {contourResult.total_contour_lines} Vector Isolines</h4>
                  </div>
                  <p className="text-muted mt-2">
                    Elevation Range: {contourResult.min_elevation_m.toFixed(2)}m to {contourResult.max_elevation_m.toFixed(2)}m (Interval: {contourResult.interval_m}m).
                  </p>
                  <button
                    className="btn-secondary btn-sm mt-3"
                    onClick={() => triggerDownload('geojson')}
                  >
                    <ArrowDownToLine className="icon-xs" />
                    <span>Download GeoJSON Contours</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'exports' && (
          <div className="tab-pane-padded">
            <div className="pane-header">
              <div>
                <h3>GIS & 3D Export Center</h3>
                <p className="step-desc">
                  Download production-ready spatial assets calibrated in true metric scale.
                </p>
              </div>
            </div>

            <div className="exports-grid">
              <div className="export-card">
                <div className="export-card-header">
                  <Layers className="icon-md icon-accent" />
                  <h4>32-bit Metric GeoTIFF (DSM)</h4>
                </div>
                <p>
                  Georeferenced floating point Digital Surface Model raster for QGIS, ArcGIS, and Global Mapper.
                </p>
                <button
                  className="btn-primary btn-block"
                  onClick={() => triggerDownload('geotiff')}
                  disabled={downloading === 'geotiff'}
                >
                  <Download className="icon-sm" />
                  <span>{downloading === 'geotiff' ? 'Downloading...' : 'Download .TIF'}</span>
                </button>
              </div>

              <div className="export-card">
                <div className="export-card-header">
                  <FileCode className="icon-md icon-accent" />
                  <h4>Wavefront 3D Mesh (.OBJ)</h4>
                </div>
                <p>
                  Standard 3D polygon mesh with analytical surface normals and UV coordinate mapping for Blender and Three.js.
                </p>
                <button
                  className="btn-primary btn-block"
                  onClick={() => triggerDownload('obj')}
                  disabled={downloading === 'obj'}
                >
                  <Download className="icon-sm" />
                  <span>{downloading === 'obj' ? 'Downloading...' : 'Download .OBJ'}</span>
                </button>
              </div>

              <div className="export-card">
                <div className="export-card-header">
                  <MapPin className="icon-md icon-accent" />
                  <h4>Stanford Polygon / Point Cloud (.PLY)</h4>
                </div>
                <p>
                  High precision ASCII PLY point cloud & mesh for CloudCompare, MeshLab, and photogrammetry suites.
                </p>
                <button
                  className="btn-primary btn-block"
                  onClick={() => triggerDownload('ply')}
                  disabled={downloading === 'ply'}
                >
                  <Download className="icon-sm" />
                  <span>{downloading === 'ply' ? 'Downloading...' : 'Download .PLY'}</span>
                </button>
              </div>

              <div className="export-card">
                <div className="export-card-header">
                  <TrendingUp className="icon-md icon-accent" />
                  <h4>GeoJSON Elevation Contours</h4>
                </div>
                <p>
                  Standard RFC 7946 LineString vectors with metric elevation attributes.
                </p>
                <button
                  className="btn-primary btn-block"
                  onClick={() => triggerDownload('geojson')}
                  disabled={downloading === 'geojson'}
                >
                  <Download className="icon-sm" />
                  <span>{downloading === 'geojson' ? 'Downloading...' : 'Download .GEOJSON'}</span>
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="analytics-footer">
        <button className="btn-secondary" onClick={onBack}>
          Back to Pipeline Steps
        </button>
      </div>
    </div>
  );
};

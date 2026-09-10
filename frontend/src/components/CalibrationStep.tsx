import React, { useState } from 'react';
import { Sliders, CheckCircle2, ArrowRight, Plus, Trash2, Target } from 'lucide-react';
import { pipelineApi } from '../api/client';
import type { CalibrationResponse, GCPPoint } from '../types';

interface CalibrationStepProps {
  jobId: string | null;
  onCalibrationSuccess: (data: CalibrationResponse) => void;
  existingData: CalibrationResponse | null;
  onNext: () => void;
  onBack: () => void;
}

export const CalibrationStep: React.FC<CalibrationStepProps> = ({
  jobId,
  onCalibrationSuccess,
  existingData,
  onNext,
  onBack,
}) => {
  const [clothResolution, setClothResolution] = useState<number>(1.5);
  const [classThreshold, setClassThreshold] = useState<number>(0.5);
  const [timeStep, setTimeStep] = useState<number>(0.65);
  const [gcpPoints, setGcpPoints] = useState<GCPPoint[]>([
    { x: 10, y: 10, true_z: 100.0 },
    { x: 30, y: 40, true_z: 105.2 },
    { x: 50, y: 20, true_z: 102.8 },
  ]);
  const [newX, setNewX] = useState<number>(25);
  const [newY, setNewY] = useState<number>(25);
  const [newZ, setNewZ] = useState<number>(101.5);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const addGcp = () => {
    setGcpPoints([...gcpPoints, { x: Number(newX), y: Number(newY), true_z: Number(newZ) }]);
  };

  const removeGcp = (index: number) => {
    setGcpPoints(gcpPoints.filter((_, i) => i !== index));
  };

  const handleCalibrate = async () => {
    if (!jobId) return;
    setError(null);
    setLoading(true);

    try {
      const data = await pipelineApi.calibrate(jobId, {
        cloth_resolution: clothResolution,
        class_threshold: classThreshold,
        time_step: timeStep,
        gcp_points: gcpPoints,
      });
      onCalibrationSuccess(data);
    } catch (err: any) {
      console.error(err);
      const detail = err.response?.data?.detail;
      setError(
        typeof detail === 'string'
          ? detail
          : 'Calibration failed. Ensure inference is completed first.'
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="step-card">
      <div className="step-header">
        <div>
          <h2>Stage 3: Scale Calibration & Ground Classification</h2>
          <p className="step-desc">
            Separates terrain ground points via Cloth Simulation Filter (CSF) and computes metric scaling ($d = s \cdot D + t$) via RANSAC.
          </p>
        </div>
      </div>

      {error && (
        <div className="alert alert-error">
          <span>{error}</span>
        </div>
      )}

      <div className="params-grid">
        <div className="param-card">
          <label className="param-label">
            <span>Cloth Resolution (Grid Step)</span>
            <span className="param-val">{clothResolution} m</span>
          </label>
          <input
            type="range"
            min="0.5"
            max="5.0"
            step="0.1"
            value={clothResolution}
            onChange={(e) => setClothResolution(parseFloat(e.target.value))}
          />
          <p className="param-help">Grid size of the simulated inverted cloth mesh.</p>
        </div>

        <div className="param-card">
          <label className="param-label">
            <span>Classification Threshold</span>
            <span className="param-val">{classThreshold} m</span>
          </label>
          <input
            type="range"
            min="0.1"
            max="2.0"
            step="0.05"
            value={classThreshold}
            onChange={(e) => setClassThreshold(parseFloat(e.target.value))}
          />
          <p className="param-help">Distance threshold to classify points as ground vs above-ground.</p>
        </div>

        <div className="param-card">
          <label className="param-label">
            <span>Simulation Time Step (dt)</span>
            <span className="param-val">{timeStep}</span>
          </label>
          <input
            type="range"
            min="0.2"
            max="1.5"
            step="0.05"
            value={timeStep}
            onChange={(e) => setTimeStep(parseFloat(e.target.value))}
          />
          <p className="param-help">Physics displacement relaxation step.</p>
        </div>
      </div>

      <div className="gcp-section">
        <div className="section-title-row">
          <div className="flex-center gap-2">
            <Target className="icon-sm" />
            <h3>Ground Control Points (GCPs) for Survey Scale Fitting</h3>
          </div>
          <span className="badge badge-subtle">{gcpPoints.length} Points Configured</span>
        </div>

        <div className="gcp-table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Pixel X</th>
                <th>Pixel Y</th>
                <th>Survey Elevation (Z in meters)</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {gcpPoints.map((pt, idx) => (
                <tr key={idx}>
                  <td>{idx + 1}</td>
                  <td>{pt.x}</td>
                  <td>{pt.y}</td>
                  <td>{pt.true_z.toFixed(2)} m</td>
                  <td>
                    <button
                      type="button"
                      className="btn-icon-danger"
                      onClick={() => removeGcp(idx)}
                      title="Remove GCP"
                    >
                      <Trash2 className="icon-xs" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="gcp-add-row">
          <input
            type="number"
            placeholder="Pixel X"
            value={newX}
            onChange={(e) => setNewX(Number(e.target.value))}
          />
          <input
            type="number"
            placeholder="Pixel Y"
            value={newY}
            onChange={(e) => setNewY(Number(e.target.value))}
          />
          <input
            type="number"
            placeholder="Survey Z (meters)"
            value={newZ}
            onChange={(e) => setNewZ(Number(e.target.value))}
          />
          <button type="button" className="btn-secondary btn-sm" onClick={addGcp}>
            <Plus className="icon-xs" />
            <span>Add GCP</span>
          </button>
        </div>
      </div>

      <div className="action-row">
        <button className="btn-secondary" onClick={onBack}>
          Back to Inference
        </button>

        <button className="btn-primary" onClick={handleCalibrate} disabled={loading || !jobId}>
          {loading ? (
            <span>Running CSF & RANSAC Calibration...</span>
          ) : (
            <>
              <Sliders className="icon-sm" />
              <span>Calibrate Metric Scale & Accuracy</span>
            </>
          )}
        </button>
      </div>

      {existingData && (
        <div className="metadata-container">
          <div className="metadata-header">
            <div className="flex-center gap-2">
              <CheckCircle2 className="icon-success icon-sm" />
              <h3>Scale Calibration & ASPRS Validation Succeeded</h3>
            </div>
            <span className="badge badge-success">
              {existingData.metrics.asprs_vertical_accuracy_class}
            </span>
          </div>

          <div className="meta-grid">
            <div className="meta-card">
              <span className="meta-label">Metric Scale ($s$)</span>
              <span className="meta-value">{existingData.scale.toFixed(4)}</span>
              <span className="meta-sub">Slope multiplier</span>
            </div>

            <div className="meta-card">
              <span className="meta-label">Datum Shift / Bias ($t$)</span>
              <span className="meta-value">{existingData.bias.toFixed(3)} m</span>
              <span className="meta-sub">Vertical intercept</span>
            </div>

            <div className="meta-card">
              <span className="meta-label">RMSE (Vertical Z)</span>
              <span className="meta-value">{existingData.metrics.rmse_z.toFixed(3)} m</span>
              <span className="meta-sub">Root Mean Square Error</span>
            </div>

            <div className="meta-card">
              <span className="meta-label">LE90 (90% Confidence)</span>
              <span className="meta-value">{existingData.metrics.le90.toFixed(3)} m</span>
              <span className="meta-sub">Linear Error at 90%</span>
            </div>

            <div className="meta-card">
              <span className="meta-label">Mean Absolute Error</span>
              <span className="meta-value">{existingData.metrics.mae_z.toFixed(3)} m</span>
              <span className="meta-sub">MAE (Z)</span>
            </div>

            <div className="meta-card">
              <span className="meta-label">Ground Point Ratio</span>
              <span className="meta-value">{(existingData.ground_ratio * 100).toFixed(1)}%</span>
              <span className="meta-sub">CSF classified terrain</span>
            </div>
          </div>

          <div className="step-actions">
            <button className="btn-primary" onClick={onNext}>
              <span>Enter 3D Studio & Analytics</span>
              <ArrowRight className="icon-sm" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

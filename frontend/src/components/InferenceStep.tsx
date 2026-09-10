import React, { useState } from 'react';
import { Cpu, Zap, ArrowRight, CheckCircle2, AlertTriangle, Clock } from 'lucide-react';
import { pipelineApi } from '../api/client';
import type { InferenceResponse } from '../types';

interface InferenceStepProps {
  jobId: string | null;
  onInferenceSuccess: (data: InferenceResponse) => void;
  existingData: InferenceResponse | null;
  onNext: () => void;
  onBack: () => void;
}

export const InferenceStep: React.FC<InferenceStepProps> = ({
  jobId,
  onInferenceSuccess,
  existingData,
  onNext,
  onBack,
}) => {
  const [model, setModel] = useState<'vits' | 'vitb'>('vits');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);

  const handleInfer = async () => {
    if (!jobId) return;
    setError(null);
    setLoading(true);
    setElapsed(0);

    const timer = setInterval(() => {
      setElapsed((prev) => prev + 1);
    }, 1000);

    try {
      const data = await pipelineApi.infer(jobId, model);
      onInferenceSuccess(data);
    } catch (err: any) {
      console.error(err);
      const detail = err.response?.data?.detail;
      setError(
        typeof detail === 'string'
          ? detail
          : 'AI inference failed. Check backend logs and model downloads.'
      );
    } finally {
      clearInterval(timer);
      setLoading(false);
    }
  };

  return (
    <div className="step-card">
      <div className="step-header">
        <div>
          <h2>Stage 2: AI Monocular Depth Estimation</h2>
          <p className="step-desc">
            Executes Depth Anything V2 vision transformer model with cosine overlap-blended tile stitching.
          </p>
        </div>
      </div>

      {error && (
        <div className="alert alert-error">
          <AlertTriangle className="icon-sm" />
          <span>{error}</span>
        </div>
      )}

      <div className="model-selection-grid">
        <div
          className={`model-card ${model === 'vits' ? 'selected' : ''}`}
          onClick={() => setModel('vits')}
        >
          <div className="model-card-header">
            <div className="flex-center gap-2">
              <Zap className="icon-sm icon-accent" />
              <h3>Depth Anything V2 (Small)</h3>
            </div>
            <span className="badge badge-subtle">Recommended</span>
          </div>
          <p className="model-desc">
            Fast, lightweight ViT-S architecture. Ideal for rapid feedback and drone orthophotos.
          </p>
          <div className="model-specs">
            <span>Params: ~24.8M</span>
            <span>Speed: Fast</span>
          </div>
        </div>

        <div
          className={`model-card ${model === 'vitb' ? 'selected' : ''}`}
          onClick={() => setModel('vitb')}
        >
          <div className="model-card-header">
            <div className="flex-center gap-2">
              <Cpu className="icon-sm icon-accent" />
              <h3>Depth Anything V2 (Base)</h3>
            </div>
            <span className="badge badge-subtle">High Fidelity</span>
          </div>
          <p className="model-desc">
            ViT-B architecture with richer geometric boundaries and fine structural relief.
          </p>
          <div className="model-specs">
            <span>Params: ~97.5M</span>
            <span>Speed: Moderate</span>
          </div>
        </div>
      </div>

      <div className="action-row">
        <button className="btn-secondary" onClick={onBack}>
          Back to Upload
        </button>

        <button className="btn-primary" onClick={handleInfer} disabled={loading || !jobId}>
          {loading ? (
            <>
              <Clock className="icon-sm spin" />
              <span>Estimating Depth ({elapsed}s)...</span>
            </>
          ) : (
            <>
              <Cpu className="icon-sm" />
              <span>Run AI Depth Inference</span>
            </>
          )}
        </button>
      </div>

      {existingData && (
        <div className="metadata-container">
          <div className="metadata-header">
            <div className="flex-center gap-2">
              <CheckCircle2 className="icon-success icon-sm" />
              <h3>Depth Estimation Completed Successfully</h3>
            </div>
            <span className="badge badge-success">Model: {existingData.model_used}</span>
          </div>

          <div className="meta-grid">
            <div className="meta-card">
              <span className="meta-label">Depth Map Resolution</span>
              <span className="meta-value">
                {existingData.shape[1]} &times; {existingData.shape[0]} px
              </span>
              <span className="meta-sub">Relative Heightfield</span>
            </div>

            <div className="meta-card">
              <span className="meta-label">Relative Depth Range</span>
              <span className="meta-value">
                {existingData.relative_depth_range[0].toFixed(2)} - {existingData.relative_depth_range[1].toFixed(2)}
              </span>
              <span className="meta-sub">Raw model unit scale</span>
            </div>

            <div className="meta-card">
              <span className="meta-label">Stitching Technique</span>
              <span className="meta-value">Linear/Cosine Blending</span>
              <span className="meta-sub">Overlap boundary smoothed</span>
            </div>
          </div>

          <div className="step-actions">
            <button className="btn-primary" onClick={onNext}>
              <span>Proceed to Scale Calibration</span>
              <ArrowRight className="icon-sm" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

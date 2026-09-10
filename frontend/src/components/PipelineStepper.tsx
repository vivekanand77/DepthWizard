import React from 'react';
import { UploadCloud, Cpu, Sliders, Box, Mountain } from 'lucide-react';

export type PipelineStepId = 'upload' | 'infer' | 'calibrate' | 'analytics' | 'terrain';

interface PipelineStepperProps {
  currentStep: PipelineStepId;
  onSelectStep: (step: PipelineStepId) => void;
  hasUpload: boolean;
  hasInference: boolean;
  hasCalibration: boolean;
}

export const PipelineStepper: React.FC<PipelineStepperProps> = ({
  currentStep,
  onSelectStep,
  hasUpload,
  hasInference,
  hasCalibration,
}) => {
  const steps = [
    {
      id: 'upload' as PipelineStepId,
      label: '1. Ingest Orthomosaic',
      description: 'Upload raster, extract CRS & tile grid',
      icon: UploadCloud,
      available: true,
      completed: hasUpload,
    },
    {
      id: 'infer' as PipelineStepId,
      label: '2. Depth Inference',
      description: 'Depth Anything V2 tile blending',
      icon: Cpu,
      available: hasUpload,
      completed: hasInference,
    },
    {
      id: 'calibrate' as PipelineStepId,
      label: '3. Metric Calibration',
      description: 'CSF Ground Filter + RANSAC scaling',
      icon: Sliders,
      available: hasInference,
      completed: hasCalibration,
    },
    {
      id: 'analytics' as PipelineStepId,
      label: '4. 3D Studio & Analytics',
      description: 'Interactive mesh, contours & earthwork',
      icon: Box,
      available: hasCalibration || hasInference,
      completed: false,
    },
    {
      id: 'terrain' as PipelineStepId,
      label: '5. 3D Terrain',
      description: 'Cinematic terrain flythrough',
      icon: Mountain,
      available: hasCalibration,
      completed: false,
    },
  ];

  return (
    <nav className="pipeline-stepper" aria-label="Pipeline Progress">
      {steps.map((step, idx) => {
        const Icon = step.icon;
        const isActive = currentStep === step.id;
        const isClickable = step.available;

        return (
          <button
            key={step.id}
            type="button"
            className={`stepper-item ${isActive ? 'active' : ''} ${
              step.completed ? 'completed' : ''
            } ${!isClickable ? 'disabled' : ''}`}
            onClick={() => isClickable && onSelectStep(step.id)}
            disabled={!isClickable}
          >
            <div className="stepper-badge">
              <Icon className="icon-sm" />
            </div>
            <div className="stepper-text">
              <div className="stepper-title">{step.label}</div>
              <div className="stepper-sub">{step.description}</div>
            </div>
            {idx < steps.length - 1 && <div className="stepper-divider" />}
          </button>
        );
      })}
    </nav>
  );
};

import { useState, useEffect } from 'react';
import { Navbar } from './components/Navbar';
import { AuthModal } from './components/AuthModal';
import { PipelineStepper } from './components/PipelineStepper';
import type { PipelineStepId } from './components/PipelineStepper';
import { UploadStep } from './components/UploadStep';
import { InferenceStep } from './components/InferenceStep';
import { CalibrationStep } from './components/CalibrationStep';
import { AnalyticsPanel } from './components/AnalyticsPanel';
import { TerrainFlythrough } from './components/TerrainFlythrough';
import type { UploadResponse, InferenceResponse, CalibrationResponse } from './types';
import './index.css';

export function App() {
  const [token, setToken] = useState<string | null>(null);
  const [userEmail, setUserEmail] = useState<string>('');
  const [isAuthOpen, setIsAuthOpen] = useState<boolean>(false);

  // Pipeline state
  const [currentStep, setCurrentStep] = useState<PipelineStepId>('upload');
  const [uploadData, setUploadData] = useState<UploadResponse | null>(null);
  const [inferData, setInferData] = useState<InferenceResponse | null>(null);
  const [calibData, setCalibData] = useState<CalibrationResponse | null>(null);

  useEffect(() => {
    const savedToken = localStorage.getItem('depthwizard_token');
    const savedUser = localStorage.getItem('depthwizard_user');
    if (savedToken) {
      setToken(savedToken);
      setUserEmail(savedUser || 'User');
    }
  }, []);

  const handleLogout = () => {
    localStorage.removeItem('depthwizard_token');
    localStorage.removeItem('depthwizard_user');
    setToken(null);
    setUserEmail('');
  };

  const handleAuthSuccess = (newToken: string, email: string) => {
    setToken(newToken);
    setUserEmail(email);
  };

  const activeJobId = uploadData?.job_id || null;

  return (
    <div className="app-layout">
      <Navbar
        token={token}
        username={userEmail}
        onOpenAuth={() => setIsAuthOpen(true)}
        onLogout={handleLogout}
      />

      <main className="main-content">
        <div className="container">
          <PipelineStepper
            currentStep={currentStep}
            onSelectStep={(step) => setCurrentStep(step)}
            hasUpload={!!uploadData}
            hasInference={!!inferData}
            hasCalibration={!!calibData}
          />

          <div className="step-wrapper">
            {currentStep === 'upload' && (
              <UploadStep
                token={token}
                onUploadSuccess={(data) => {
                  setUploadData(data);
                  setCurrentStep('infer');
                }}
                onOpenAuth={() => setIsAuthOpen(true)}
                existingData={uploadData}
                onNext={() => setCurrentStep('infer')}
              />
            )}

            {currentStep === 'infer' && (
              <InferenceStep
                jobId={activeJobId}
                onInferenceSuccess={(data) => {
                  setInferData(data);
                  setCurrentStep('calibrate');
                }}
                existingData={inferData}
                onNext={() => setCurrentStep('calibrate')}
                onBack={() => setCurrentStep('upload')}
              />
            )}

            {currentStep === 'calibrate' && (
              <CalibrationStep
                jobId={activeJobId}
                onCalibrationSuccess={(data) => {
                  setCalibData(data);
                  setCurrentStep('analytics');
                }}
                existingData={calibData}
                onNext={() => setCurrentStep('analytics')}
                onBack={() => setCurrentStep('infer')}
              />
            )}

            {currentStep === 'analytics' && activeJobId && (
              <AnalyticsPanel
                jobId={activeJobId}
                onBack={() => setCurrentStep('calibrate')}
              />
            )}

            {currentStep === 'terrain' && activeJobId && (
              <TerrainFlythrough
                jobId={activeJobId}
                onBack={() => setCurrentStep('analytics')}
              />
            )}
          </div>
        </div>
      </main>

      <AuthModal
        isOpen={isAuthOpen}
        onClose={() => setIsAuthOpen(false)}
        onSuccess={handleAuthSuccess}
      />
    </div>
  );
}

export default App;

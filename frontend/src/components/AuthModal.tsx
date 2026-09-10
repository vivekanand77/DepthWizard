import React, { useState } from 'react';
import { X, Lock, Mail, AlertCircle, CheckCircle2 } from 'lucide-react';
import { authApi } from '../api/client';

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (token: string, email: string) => void;
}

export const AuthModal: React.FC<AuthModalProps> = ({ isOpen, onClose, onSuccess }) => {
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState('testuser@depthwizard.ai');
  const [password, setPassword] = useState('SecurePass123!');
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setInfo(null);
    setLoading(true);

    try {
      if (isRegister) {
        await authApi.register(email, password);
        setInfo('Account registered successfully! Logging you in...');
      }
      const data = await authApi.login(email, password);
      localStorage.setItem('depthwizard_token', data.access_token);
      localStorage.setItem('depthwizard_user', email);
      onSuccess(data.access_token, email);
      onClose();
    } catch (err: any) {
      console.error(err);
      const detail = err.response?.data?.detail;
      setError(
        typeof detail === 'string'
          ? detail
          : Array.isArray(detail)
          ? detail.map((d: any) => d.msg).join(', ')
          : 'Authentication failed. Please check credentials or backend.'
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content">
        <div className="modal-header">
          <h2>{isRegister ? 'Create Account' : 'Authenticate to DepthWizard'}</h2>
          <button className="btn-icon" onClick={onClose}>
            <X className="icon-sm" />
          </button>
        </div>

        {error && (
          <div className="alert alert-error">
            <AlertCircle className="icon-sm" />
            <span>{error}</span>
          </div>
        )}

        {info && (
          <div className="alert alert-info">
            <CheckCircle2 className="icon-sm" />
            <span>{info}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="auth-form">
          <div className="form-group">
            <label htmlFor="auth-email">Email / Username</label>
            <div className="input-wrapper">
              <Mail className="input-icon" />
              <input
                id="auth-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                placeholder="user@example.com"
              />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="auth-password">Password</label>
            <div className="input-wrapper">
              <Lock className="input-icon" />
              <input
                id="auth-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                placeholder="••••••••"
              />
            </div>
          </div>

          <button type="submit" className="btn-primary btn-block" disabled={loading}>
            {loading ? 'Processing...' : isRegister ? 'Register & Login' : 'Login'}
          </button>
        </form>

        <div className="modal-footer-switch">
          <span>{isRegister ? 'Already have an account?' : "Don't have an account yet?"}</span>
          <button
            type="button"
            className="btn-link"
            onClick={() => {
              setIsRegister(!isRegister);
              setError(null);
              setInfo(null);
            }}
          >
            {isRegister ? 'Switch to Login' : 'Create an Account'}
          </button>
        </div>
      </div>
    </div>
  );
};

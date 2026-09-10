import React from 'react';
import { Layers, ShieldCheck, LogOut, KeyRound } from 'lucide-react';

interface NavbarProps {
  token: string | null;
  username: string;
  onOpenAuth: () => void;
  onLogout: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  token,
  username,
  onOpenAuth,
  onLogout,
}) => {
  return (
    <header className="navbar">
      <div className="nav-brand">
        <div className="brand-logo">
          <Layers className="icon-brand" />
        </div>
        <div>
          <h1 className="brand-title">DepthWizard</h1>
          <span className="brand-subtitle">Monocular Elevation & Geospatial 3D Platform</span>
        </div>
      </div>

      <div className="nav-actions">
        <div className="backend-badge">
          <span className="status-dot"></span>
          <span>API: 127.0.0.1:8000</span>
        </div>

        {token ? (
          <div className="user-profile">
            <span className="user-email">
              <ShieldCheck className="icon-sm" />
              {username || 'Authorized User'}
            </span>
            <button className="btn-secondary btn-sm" onClick={onLogout} title="Logout">
              <LogOut className="icon-sm" />
              <span>Logout</span>
            </button>
          </div>
        ) : (
          <button className="btn-primary btn-sm" onClick={onOpenAuth}>
            <KeyRound className="icon-sm" />
            <span>Login / Register</span>
          </button>
        )}
      </div>
    </header>
  );
};

import React from 'react';
import { Layers, ShieldCheck, LogOut, KeyRound, MoonStar, SunMedium } from 'lucide-react';

interface NavbarProps {
  token: string | null;
  username: string;
  theme: 'dark' | 'light';
  onOpenAuth: () => void;
  onLogout: () => void;
  onToggleTheme: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  token,
  username,
  theme,
  onOpenAuth,
  onLogout,
  onToggleTheme,
}) => {
  return (
    <header className="navbar">
      <div className="nav-brand">
        <div className="brand-logo">
          <Layers className="icon-brand" />
        </div>
        <div>
          <h1 className="brand-title">ELEVATE3D</h1>
          <span className="brand-subtitle">TERRAIN INTELLIGENCE ENGINE</span>
        </div>
      </div>

      <div className="nav-actions">
        <button className="btn-secondary btn-sm" onClick={onToggleTheme} type="button">
          {theme === 'dark' ? <SunMedium className="icon-sm" /> : <MoonStar className="icon-sm" />}
          <span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>
        </button>

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

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { apiGet, apiPost } from './api';
import type { User } from './types';

const DEMO_USER: User = {
  id: 'demo',
  email: 'demo@doc-anything.dev',
  full_name: 'Demo User',
  role: 'admin',
  created_at: new Date().toISOString(),
};

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  loginDemo: () => void;
  register: (fullName: string, email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const fetchMe = useCallback(async () => {
    // Demo bypass
    if (localStorage.getItem('docany_demo') === '1') {
      setUser(DEMO_USER);
      setIsLoading(false);
      return;
    }
    const token = localStorage.getItem('docany_token');
    if (!token) {
      setIsLoading(false);
      return;
    }
    try {
      const me = await apiGet<User>('/api/v1/auth/me');
      setUser(me);
    } catch {
      localStorage.removeItem('docany_token');
      localStorage.removeItem('docany_refresh');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMe();
  }, [fetchMe]);

  const login = async (email: string, password: string) => {
    const data = await apiPost<{ access_token: string; refresh_token: string }>(
      '/api/v1/auth/login',
      { email, password }
    );
    localStorage.setItem('docany_token', data.access_token);
    localStorage.setItem('docany_refresh', data.refresh_token);
    const me = await apiGet<User>('/api/v1/auth/me');
    setUser(me);
  };

  const register = async (fullName: string, email: string, password: string) => {
    const data = await apiPost<{ access_token: string; refresh_token: string }>(
      '/api/v1/auth/register',
      { full_name: fullName, email, password }
    );
    localStorage.setItem('docany_token', data.access_token);
    localStorage.setItem('docany_refresh', data.refresh_token);
    const me = await apiGet<User>('/api/v1/auth/me');
    setUser(me);
  };

  const loginDemo = () => {
    localStorage.setItem('docany_demo', '1');
    setUser(DEMO_USER);
  };

  const logout = () => {
    localStorage.removeItem('docany_token');
    localStorage.removeItem('docany_refresh');
    localStorage.removeItem('docany_demo');
    setUser(null);
    window.location.href = '/auth/login';
  };

  return (
    <AuthContext.Provider value={{
      user,
      isAuthenticated: !!user,
      isLoading,
      login,
      loginDemo,
      register,
      logout,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

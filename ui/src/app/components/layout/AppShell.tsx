import { useState, useEffect } from 'react';
import { Outlet, useLocation } from 'react-router';
import { Menu, Bell } from 'lucide-react';
import { Sidebar } from './Sidebar';
import { ErrorBoundary } from '../shared/ErrorBoundary';
import { useAuth } from '../../lib/auth';

function getBreadcrumb(pathname: string): string {
  const parts = pathname.split('/').filter(Boolean);
  if (parts.length <= 1) return 'Dashboard';
  const labels: Record<string, string> = {
    app: 'App',
    projects: 'Projects',
    documents: 'Documents',
    settings: 'Settings',
    jobs: 'Job',
  };
  const last = parts[parts.length - 1];
  if (labels[last]) return labels[last];
  const secondLast = parts[parts.length - 2];
  if (secondLast === 'projects') return 'Project Details';
  if (secondLast === 'documents') return 'Document';
  if (secondLast === 'jobs') return 'Job Details';
  return labels[last] || 'Page';
}

export function AppShell() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const { user } = useAuth();
  const location = useLocation();

  useEffect(() => {
    const check = () => {
      const mobile = window.innerWidth < 768;
      const tablet = window.innerWidth < 1024;
      setIsMobile(mobile);
      setSidebarCollapsed(tablet && !mobile);
    };
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);

  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  return (
    <div className="flex h-screen bg-background overflow-hidden">
      {/* Desktop sidebar */}
      {!isMobile && (
        <div className={`flex-shrink-0 transition-all duration-200 ${sidebarCollapsed ? 'w-14' : 'w-60'}`}>
          <Sidebar collapsed={sidebarCollapsed} />
        </div>
      )}

      {/* Mobile drawer */}
      {isMobile && drawerOpen && (
        <>
          <div
            className="fixed inset-0 bg-black/40 z-40"
            onClick={() => setDrawerOpen(false)}
          />
          <div className="fixed left-0 top-0 bottom-0 w-64 z-50 shadow-xl">
            <Sidebar onClose={() => setDrawerOpen(false)} />
          </div>
        </>
      )}

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Topbar */}
        <header className="h-14 flex items-center justify-between px-4 border-b border-border bg-card flex-shrink-0">
          <div className="flex items-center gap-3">
            {isMobile && (
              <button
                onClick={() => setDrawerOpen(true)}
                className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              >
                <Menu size={18} />
              </button>
            )}
            {!isMobile && (
              <button
                onClick={() => setSidebarCollapsed(c => !c)}
                className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              >
                <Menu size={18} />
              </button>
            )}
            <span className="text-muted-foreground" style={{ fontSize: '0.875rem' }}>
              {getBreadcrumb(location.pathname)}
            </span>
          </div>

          <div className="flex items-center gap-1">
            <button className="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors relative">
              <Bell size={17} />
            </button>
            <div className="ml-1 w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center cursor-pointer"
              style={{ fontSize: '0.8125rem', fontWeight: 600 }}>
              {user?.full_name?.[0]?.toUpperCase() || 'U'}
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto">
          <ErrorBoundary key={location.pathname}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}

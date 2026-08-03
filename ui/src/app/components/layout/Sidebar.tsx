import { NavLink, useNavigate } from 'react-router';
import { LayoutDashboard, FolderOpen, FileText, Settings, LogOut, BookOpen, X } from 'lucide-react';
import { useAuth } from '../../lib/auth';

interface SidebarProps {
  collapsed?: boolean;
  onClose?: () => void;
}

const navItems = [
  { to: '/app', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/app/projects', label: 'Projects', icon: FolderOpen },
  { to: '/app/documents', label: 'Documents', icon: FileText },
];

export function Sidebar({ collapsed = false, onClose }: SidebarProps) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/auth/login');
  };

  return (
    <div className="flex flex-col h-full bg-sidebar border-r border-sidebar-border">
      {/* Logo */}
      <div className="flex items-center justify-between px-4 h-14 border-b border-sidebar-border flex-shrink-0">
        {!collapsed && (
          <NavLink to="/app" className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-primary flex items-center justify-center">
              <BookOpen size={14} className="text-primary-foreground" />
            </div>
            <span className="text-foreground" style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '0.9rem' }}>
              doc-anything
            </span>
          </NavLink>
        )}
        {collapsed && (
          <div className="w-7 h-7 rounded-lg bg-primary flex items-center justify-center mx-auto">
            <BookOpen size={14} className="text-primary-foreground" />
          </div>
        )}
        {onClose && (
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground lg:hidden">
            <X size={18} />
          </button>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
        {navItems.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            onClick={onClose}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg transition-colors relative ${
                isActive
                  ? 'bg-sidebar-accent text-sidebar-foreground font-medium'
                  : 'text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-foreground'
              } ${collapsed ? 'justify-center' : ''}`
            }
          >
            {({ isActive }) => (
              <>
                {isActive && !collapsed && (
                  <div className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 bg-primary rounded-r-full" />
                )}
                <Icon size={17} className="flex-shrink-0" />
                {!collapsed && <span style={{ fontSize: '0.875rem' }}>{label}</span>}
              </>
            )}
          </NavLink>
        ))}

        {user?.role === 'admin' && (
          <NavLink
            to="/app/settings"
            onClick={onClose}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg transition-colors relative ${
                isActive
                  ? 'bg-sidebar-accent text-sidebar-foreground font-medium'
                  : 'text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-foreground'
              } ${collapsed ? 'justify-center' : ''}`
            }
          >
            {({ isActive }) => (
              <>
                {isActive && !collapsed && (
                  <div className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 bg-primary rounded-r-full" />
                )}
                <Settings size={17} className="flex-shrink-0" />
                {!collapsed && <span style={{ fontSize: '0.875rem' }}>Settings</span>}
              </>
            )}
          </NavLink>
        )}
      </nav>

      {/* Profile */}
      <div className="px-2 py-3 border-t border-sidebar-border flex-shrink-0">
        {!collapsed && (
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-sidebar-accent mb-1">
            <div className="w-7 h-7 rounded-full bg-primary text-primary-foreground flex items-center justify-center flex-shrink-0"
              style={{ fontSize: '0.75rem', fontWeight: 600 }}>
              {user?.full_name?.[0]?.toUpperCase() || 'U'}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-foreground truncate" style={{ fontSize: '0.8125rem', fontWeight: 500 }}>
                {user?.full_name || 'User'}
              </div>
              <div className="text-muted-foreground truncate capitalize" style={{ fontSize: '0.75rem' }}>
                {user?.role || 'user'}
              </div>
            </div>
          </div>
        )}
        <button
          onClick={handleLogout}
          className={`flex items-center gap-3 w-full px-3 py-2 rounded-lg text-muted-foreground hover:bg-sidebar-accent hover:text-destructive transition-colors ${collapsed ? 'justify-center' : ''}`}
        >
          <LogOut size={16} className="flex-shrink-0" />
          {!collapsed && <span style={{ fontSize: '0.875rem' }}>Sign out</span>}
        </button>
      </div>
    </div>
  );
}

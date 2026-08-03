import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { FolderOpen, FileText, Clock, PlusCircle, BarChart2 } from 'lucide-react';
import { apiGet } from '../../lib/api';
import type { Project } from '../../lib/types';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { Spinner } from '../../components/shared/Spinner';
import { useAuth } from '../../lib/auth';
import { formatDistanceToNow } from 'date-fns';

function StatCard({ icon: Icon, label, value, sub }: { icon: React.ElementType; label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-card border border-border rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-muted-foreground" style={{ fontSize: '0.8125rem', fontWeight: 500 }}>{label}</span>
        <div className="w-8 h-8 rounded-lg bg-secondary flex items-center justify-center">
          <Icon size={16} className="text-foreground" />
        </div>
      </div>
      <div className="text-foreground" style={{ fontSize: '1.75rem', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{value}</div>
      {sub && <p className="text-muted-foreground mt-1" style={{ fontSize: '0.75rem' }}>{sub}</p>}
    </div>
  );
}

export default function DashboardPage() {
  const { user } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [proj] = await Promise.allSettled([
          apiGet<{ items: Project[] }>('/api/v1/projects?limit=50'),
        ]);
        if (proj.status === 'fulfilled') setProjects(proj.value.items || (proj.value as unknown as Project[]) || []);
      } catch {}
      setLoading(false);
    };
    load();
  }, []);

  const totalDocs = projects.reduce((a, p) => a + (p.stats?.doc_count || 0), 0);
  const totalJobs = projects.reduce((a, p) => a + (p.stats?.job_count || 0), 0);

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-foreground mb-1" style={{ fontSize: '1.375rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
          Dashboard
        </h1>
        <p className="text-muted-foreground" style={{ fontSize: '0.875rem' }}>
          Welcome back, {user?.full_name || 'there'} 👋
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Spinner size="lg" className="text-muted-foreground" />
        </div>
      ) : (
        <>
          {/* Stats */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <StatCard icon={FolderOpen} label="Total Projects" value={projects.length} />
            <StatCard icon={BarChart2} label="Jobs This Month" value={totalJobs} />
            <StatCard icon={FileText} label="Documents Generated" value={totalDocs} />
            <StatCard icon={Clock} label="Avg Job Duration" value="—" sub="No data yet" />
          </div>

          {/* Quick start */}
          {projects.length === 0 && (
            <div className="bg-card border border-border rounded-xl p-8 mb-8 text-center">
              <div className="w-12 h-12 bg-secondary rounded-xl flex items-center justify-center mx-auto mb-4">
                <FolderOpen size={22} className="text-foreground" />
              </div>
              <h2 className="text-foreground mb-2" style={{ fontSize: '1.0625rem', fontWeight: 600 }}>
                Generate your first documentation
              </h2>
              <p className="text-muted-foreground mb-5 max-w-sm mx-auto" style={{ fontSize: '0.875rem' }}>
                Create a project, add your repository, and let the AI agents write your docs.
              </p>
              <Link to="/app/projects"
                className="inline-flex items-center gap-2 px-4 py-2.5 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
                style={{ fontSize: '0.875rem', fontWeight: 500 }}>
                <PlusCircle size={16} />
                Create Project
              </Link>
            </div>
          )}

          {/* Recent projects */}
          {projects.length > 0 && (
            <div className="bg-card border border-border rounded-xl overflow-hidden">
              <div className="flex items-center justify-between px-5 py-4 border-b border-border">
                <h2 className="text-foreground" style={{ fontSize: '0.9375rem', fontWeight: 600 }}>Recent Projects</h2>
                <Link to="/app/projects" className="text-brand hover:underline" style={{ fontSize: '0.8125rem' }}>View all</Link>
              </div>
              <div className="divide-y divide-border">
                {projects.slice(0, 5).map(project => (
                  <div key={project.id} className="flex items-center justify-between px-5 py-3.5 hover:bg-secondary/50 transition-colors">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-secondary flex items-center justify-center flex-shrink-0">
                        <span className="text-foreground" style={{ fontSize: '0.8125rem', fontWeight: 600 }}>
                          {project.name[0].toUpperCase()}
                        </span>
                      </div>
                      <div>
                        <p className="text-foreground" style={{ fontSize: '0.875rem', fontWeight: 500 }}>{project.name}</p>
                        <p className="text-muted-foreground" style={{ fontSize: '0.75rem' }}>
                          {project.created_at ? formatDistanceToNow(new Date(project.created_at), { addSuffix: true }) : ''}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      {project.latest_job && <StatusBadge status={project.latest_job.status} size="sm" />}
                      <Link to={`/app/projects/${project.id}`}
                        className="text-brand hover:underline" style={{ fontSize: '0.8125rem' }}>
                        View
                      </Link>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

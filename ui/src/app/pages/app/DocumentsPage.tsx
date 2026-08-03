import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { FileText, Search } from 'lucide-react';
import { apiGet } from '../../lib/api';
import type { Document, DocType, Project } from '../../lib/types';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { Spinner } from '../../components/shared/Spinner';
import { EmptyState } from '../../components/shared/EmptyState';
import { formatDistanceToNow } from 'date-fns';

const DOC_TYPE_ICONS: Record<DocType, string> = {
  architecture: '🏗️', api: '🔌', modules: '📦', getting_started: '🚀',
  deployment: '☁️', contributing: '🤝', changelog: '📋',
};

const DOC_TYPES: DocType[] = ['architecture', 'api', 'modules', 'getting_started', 'deployment', 'contributing', 'changelog'];

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [projectFilter, setProjectFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [sort, setSort] = useState<'newest' | 'oldest' | 'title'>('newest');

  useEffect(() => {
    Promise.allSettled([
      apiGet<Document[] | { items: Document[] }>('/api/v1/documents?limit=50'),
      apiGet<Project[] | { items: Project[] }>('/api/v1/projects?limit=50'),
    ]).then(([d, p]) => {
      if (d.status === 'fulfilled') {
        const dv = d.value as Document[] | { items: Document[] };
        setDocuments(Array.isArray(dv) ? dv : dv.items || []);
      }
      if (p.status === 'fulfilled') {
        const pv = p.value as Project[] | { items: Project[] };
        setProjects(Array.isArray(pv) ? pv : pv.items || []);
      }
      setLoading(false);
    });
  }, []);

  const filtered = documents
    .filter(d => {
      if (search && !d.title?.toLowerCase().includes(search.toLowerCase())) return false;
      if (projectFilter && d.project_id !== projectFilter) return false;
      if (typeFilter && d.doc_type !== typeFilter) return false;
      return true;
    })
    .sort((a, b) => {
      if (sort === 'newest') return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      if (sort === 'oldest') return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
      return a.title.localeCompare(b.title);
    });

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-foreground" style={{ fontSize: '1.375rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>Documents</h1>
          <p className="text-muted-foreground mt-0.5" style={{ fontSize: '0.875rem' }}>{documents.length} total</p>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap gap-3 mb-6">
        <div className="relative flex-1 min-w-48">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search documents..."
            className="w-full pl-9 pr-3 py-2 rounded-lg border border-border bg-card text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            style={{ fontSize: '0.875rem' }} />
        </div>
        <select value={projectFilter} onChange={e => setProjectFilter(e.target.value)}
          className="px-3 py-2 rounded-lg border border-border bg-card text-foreground focus:outline-none"
          style={{ fontSize: '0.875rem' }}>
          <option value="">All projects</option>
          {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)}
          className="px-3 py-2 rounded-lg border border-border bg-card text-foreground focus:outline-none"
          style={{ fontSize: '0.875rem' }}>
          <option value="">All types</option>
          {DOC_TYPES.map(t => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}
        </select>
        <select value={sort} onChange={e => setSort(e.target.value as typeof sort)}
          className="px-3 py-2 rounded-lg border border-border bg-card text-foreground focus:outline-none"
          style={{ fontSize: '0.875rem' }}>
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
          <option value="title">Title A–Z</option>
        </select>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Spinner size="lg" className="text-muted-foreground" />
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<FileText size={40} />}
          title="No documents found"
          description="Generate documentation from a project to see documents here."
        />
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map(doc => {
            const project = projects.find(p => p.id === doc.project_id);
            return (
              <div key={doc.id} className="bg-card border border-border rounded-xl p-5 hover:border-foreground/20 hover:shadow-sm transition-all flex flex-col">
                <div className="flex items-center justify-between mb-3">
                  <span style={{ fontSize: '1.375rem' }}>{DOC_TYPE_ICONS[doc.doc_type] || '📄'}</span>
                  <StatusBadge status={doc.status} size="sm" />
                </div>
                <h3 className="text-foreground mb-1 flex-1 line-clamp-2" style={{ fontSize: '0.9375rem', fontWeight: 600 }}>{doc.title}</h3>
                {project && <p className="text-muted-foreground mb-2" style={{ fontSize: '0.75rem' }}>{project.name}</p>}
                <div className="flex items-center gap-2 text-muted-foreground mb-4" style={{ fontSize: '0.75rem' }}>
                  {doc.word_count && <span>{doc.word_count.toLocaleString()} words</span>}
                  <span>·</span>
                  <span>{doc.created_at ? formatDistanceToNow(new Date(doc.created_at), { addSuffix: true }) : ''}</span>
                </div>
                <div className="flex flex-wrap gap-1 mb-4">
                  {doc.output_formats?.map(f => (
                    <span key={f} className="px-2 py-0.5 rounded border border-border text-muted-foreground capitalize" style={{ fontSize: '0.7rem' }}>{f}</span>
                  ))}
                </div>
                <Link to={`/app/documents/${doc.id}`}
                  className="inline-flex items-center gap-1.5 text-brand hover:underline mt-auto" style={{ fontSize: '0.8125rem', fontWeight: 500 }}>
                  Open →
                </Link>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

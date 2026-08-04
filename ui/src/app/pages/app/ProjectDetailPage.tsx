import { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router';
import { ArrowLeft, Plus, Trash2, Play, Eye, Github, GitBranch, Upload, HardDrive, Globe } from 'lucide-react';
import * as Dialog from '@radix-ui/react-dialog';
import { apiGet, apiPost, apiDelete } from '../../lib/api';
import type { Project, Job, Document, DocType, OutputFormat } from '../../lib/types';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { KnowledgeBasePanel } from '../../components/knowledge/KnowledgeBasePanel';
import { Spinner } from '../../components/shared/Spinner';
import { EmptyState } from '../../components/shared/EmptyState';
import { ConfirmDialog } from '../../components/shared/ConfirmDialog';
import { SourceFormBody, submitSource } from './ProjectsPage';
import type { SourceTab } from './ProjectsPage';
import { Badge, StatusPill } from '../../components/shared/Badge';
import { elapsedSeconds, formatDuration, humanize } from '../../lib/format';
import { toast } from 'sonner';
import { formatDistanceToNow } from 'date-fns';

function AddSourceModal({ projectId, onAdded }: { projectId: string; onAdded: () => void }) {
  const [open, setOpen] = useState(false);
  const [sourceTab, setSourceTab] = useState<SourceTab>('github');
  const [sourceUrl, setSourceUrl] = useState('');
  const [branch, setBranch] = useState('main');
  const [token, setToken] = useState('');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);

  const reset = () => { setSourceTab('github'); setSourceUrl(''); setBranch('main'); setToken(''); setUploadFile(null); };
  const hasSource = sourceTab === 'upload' ? !!uploadFile : !!sourceUrl.trim();

  const handleAdd = async () => {
    if (!hasSource) return;
    setLoading(true);
    try {
      await submitSource(projectId, sourceTab, sourceUrl, branch, token, uploadFile);
      toast.success('Source added!');
      onAdded();
      setOpen(false);
      reset();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to add source');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(v) => { setOpen(v); if (!v) reset(); }}>
      <Dialog.Trigger asChild>
        <button className="inline-flex items-center gap-2 px-3 py-1.5 text-sm border border-border rounded-lg text-foreground hover:bg-secondary transition-colors"
          style={{ fontSize: '0.875rem', fontWeight: 500 }}>
          <Plus size={14} /> Add Source
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-lg bg-card border border-border rounded-xl shadow-xl p-6">
          <div className="flex items-center justify-between mb-5">
            <Dialog.Title className="text-foreground" style={{ fontSize: '1rem', fontWeight: 600 }}>
              Add Source
            </Dialog.Title>
            <Dialog.Close className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors">
              <span style={{ fontSize: '1.1rem', lineHeight: 1 }}>×</span>
            </Dialog.Close>
          </div>
          <SourceFormBody
            sourceTab={sourceTab} setSourceTab={setSourceTab}
            sourceUrl={sourceUrl} setSourceUrl={setSourceUrl}
            branch={branch} setBranch={setBranch}
            token={token} setToken={setToken}
            uploadFile={uploadFile} setUploadFile={setUploadFile}
          />
          <div className="flex justify-end gap-2 mt-5">
            <Dialog.Close asChild>
              <button className="px-4 py-2 border border-border rounded-lg text-foreground hover:bg-secondary transition-colors" style={{ fontSize: '0.875rem' }}>
                Cancel
              </button>
            </Dialog.Close>
            <button onClick={handleAdd} disabled={loading || !hasSource}
              className="px-5 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-60 flex items-center gap-2"
              style={{ fontSize: '0.875rem', fontWeight: 500 }}>
              {loading
                ? <><div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" /> Adding...</>
                : <><Plus size={14} /> Add Source</>}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

const DOC_TYPES: DocType[] = ['architecture', 'api', 'modules', 'getting_started', 'deployment', 'contributing', 'changelog'];
const OUTPUT_FORMATS: OutputFormat[] = ['markdown', 'docx', 'mkdocs', 'docusaurus'];

const DOC_TYPE_ICONS: Record<DocType, string> = {
  architecture: '🏗️', api: '🔌', modules: '📦', getting_started: '🚀',
  deployment: '☁️', contributing: '🤝', changelog: '📋',
};

function NewJobModal({ projectId, onCreated }: { projectId: string; onCreated: (j: Job) => void }) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(1);
  const [docTypes, setDocTypes] = useState<DocType[]>([]);
  const [formats, setFormats] = useState<OutputFormat[]>(['markdown']);
  const [requireReview, setRequireReview] = useState(false);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const reset = () => { setStep(1); setDocTypes([]); setFormats(['markdown']); setRequireReview(false); };

  const toggleDocType = (t: DocType) => setDocTypes(prev => prev.includes(t) ? prev.filter(x => x !== t) : [...prev, t]);
  const toggleFormat = (f: OutputFormat) => setFormats(prev => prev.includes(f) ? prev.filter(x => x !== f) : [...prev, f]);

  const handleStart = async () => {
    setLoading(true);
    try {
      const job = await apiPost<Job>(`/api/v1/projects/${projectId}/jobs`, {
        config: { doc_types: docTypes, output_formats: formats, requires_human_review: requireReview }
      });
      toast.success('Job started!');
      onCreated(job);
      setOpen(false);
      reset();
      navigate(`/app/projects/${projectId}/jobs/${job.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to start job');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(v) => { setOpen(v); if (!v) reset(); }}>
      <Dialog.Trigger asChild>
        <button className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
          style={{ fontSize: '0.875rem', fontWeight: 500 }}>
          <Play size={15} /> Run Documentation Job
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-lg bg-card border border-border rounded-xl shadow-xl p-6">
          <div className="flex items-center justify-between mb-5">
            <Dialog.Title className="text-foreground" style={{ fontSize: '1rem', fontWeight: 600 }}>
              {step === 1 ? 'Select Doc Types' : step === 2 ? 'Output Formats' : 'Review Options'}
            </Dialog.Title>
            <div className="flex gap-1.5">
              {[1,2,3].map(s => (
                <div key={s} className={`h-1.5 rounded-full transition-all ${s <= step ? 'w-8 bg-primary' : 'w-5 bg-border'}`} />
              ))}
            </div>
          </div>

          {step === 1 && (
            <div>
              <p className="text-muted-foreground mb-4" style={{ fontSize: '0.875rem' }}>Choose what types of documentation to generate (select at least one).</p>
              <div className="grid grid-cols-2 gap-2 mb-5">
                {DOC_TYPES.map(t => (
                  <button key={t} onClick={() => toggleDocType(t)}
                    className={`flex items-center gap-2 p-3 rounded-lg border transition-all text-left ${docTypes.includes(t) ? 'border-primary bg-primary/5 text-foreground' : 'border-border text-muted-foreground hover:border-foreground/30'}`}>
                    <span>{DOC_TYPE_ICONS[t]}</span>
                    <span style={{ fontSize: '0.875rem', fontWeight: docTypes.includes(t) ? 500 : 400, textTransform: 'capitalize' }}>
                      {t.replace(/_/g, ' ')}
                    </span>
                  </button>
                ))}
              </div>
              <div className="flex justify-end">
                <button onClick={() => docTypes.length > 0 && setStep(2)} disabled={docTypes.length === 0}
                  className="px-5 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
                  style={{ fontSize: '0.875rem', fontWeight: 500 }}>
                  Next →
                </button>
              </div>
            </div>
          )}

          {step === 2 && (
            <div>
              <p className="text-muted-foreground mb-4" style={{ fontSize: '0.875rem' }}>Select output formats (Markdown is always included).</p>
              <div className="flex flex-wrap gap-2 mb-5">
                {OUTPUT_FORMATS.map(f => (
                  <button key={f} onClick={() => f !== 'markdown' && toggleFormat(f)}
                    className={`px-4 py-2 rounded-lg border capitalize transition-all ${formats.includes(f) ? 'border-primary bg-primary/5 text-foreground' : 'border-border text-muted-foreground hover:border-foreground/30'} ${f === 'markdown' ? 'opacity-70 cursor-default' : ''}`}
                    style={{ fontSize: '0.875rem' }}>
                    {f}
                  </button>
                ))}
              </div>
              <div className="flex justify-between">
                <button onClick={() => setStep(1)} className="px-4 py-2 border border-border rounded-lg text-foreground hover:bg-secondary transition-colors" style={{ fontSize: '0.875rem' }}>← Back</button>
                <button onClick={() => setStep(3)} className="px-5 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors" style={{ fontSize: '0.875rem', fontWeight: 500 }}>Next →</button>
              </div>
            </div>
          )}

          {step === 3 && (
            <div>
              <div className="space-y-3 mb-5">
                <div className="p-4 rounded-lg border border-border bg-secondary/30">
                  <p className="text-foreground mb-1" style={{ fontSize: '0.875rem', fontWeight: 500 }}>Summary</p>
                  <p className="text-muted-foreground" style={{ fontSize: '0.8125rem' }}>
                    Doc types: {docTypes.map(t => t.replace(/_/g, ' ')).join(', ')}
                  </p>
                  <p className="text-muted-foreground" style={{ fontSize: '0.8125rem' }}>
                    Formats: {formats.join(', ')}
                  </p>
                </div>
                <label className="flex items-start gap-3 cursor-pointer p-4 rounded-lg border border-border hover:bg-secondary/30 transition-colors">
                  <input type="checkbox" checked={requireReview} onChange={e => setRequireReview(e.target.checked)} className="mt-0.5 accent-primary" />
                  <div>
                    <p className="text-foreground" style={{ fontSize: '0.875rem', fontWeight: 500 }}>Require human review</p>
                    <p className="text-muted-foreground" style={{ fontSize: '0.8125rem' }}>Pause before publishing for manual review and approval.</p>
                  </div>
                </label>
              </div>
              <div className="flex justify-between">
                <button onClick={() => setStep(2)} className="px-4 py-2 border border-border rounded-lg text-foreground hover:bg-secondary transition-colors" style={{ fontSize: '0.875rem' }}>← Back</button>
                <button onClick={handleStart} disabled={loading}
                  className="px-5 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-60 flex items-center gap-2"
                  style={{ fontSize: '0.875rem', fontWeight: 500 }}>
                  {loading ? <><div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" /> Starting...</> : <><Play size={14} /> Generate Documentation</>}
                </button>
              </div>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

const TABS = ['Overview', 'Sources', 'Jobs', 'Documents'] as const;

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [activeTab, setActiveTab] = useState<typeof TABS[number]>('Overview');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    Promise.allSettled([
      apiGet<Project>(`/api/v1/projects/${id}`),
      apiGet<Job[] | { items: Job[] }>(`/api/v1/projects/${id}/jobs`).catch(() => ({ items: [] as Job[] })),
      apiGet<Document[] | { items: Document[] }>(`/api/v1/documents?project_id=${id}&limit=50`).catch(() => ({ items: [] as Document[] })),
    ]).then(([p, j, d]) => {
      if (p.status === 'fulfilled') setProject(p.value);
      if (j.status === 'fulfilled') {
        const jv = j.value as Job[] | { items: Job[] };
        setJobs(Array.isArray(jv) ? jv : jv.items || []);
      }
      if (d.status === 'fulfilled') {
        const dv = d.value as Document[] | { items: Document[] };
        setDocuments(Array.isArray(dv) ? dv : dv.items || []);
      }
      setLoading(false);
    });
  }, [id]);

  if (loading) return <div className="flex items-center justify-center p-20"><Spinner size="lg" className="text-muted-foreground" /></div>;
  if (!project) return <div className="p-6 text-muted-foreground">Project not found</div>;

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <Link to="/app/projects" className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors">
          <ArrowLeft size={18} />
        </Link>
        <div className="flex-1">
          <h1 className="text-foreground" style={{ fontSize: '1.375rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>{project.name}</h1>
          {project.description && <p className="text-muted-foreground" style={{ fontSize: '0.875rem' }}>{project.description}</p>}
        </div>
        {/* The single-shot "run everything" job is superseded by the two-phase flow on
            the Overview tab (analyse, then choose). The legacy endpoint still exists for
            API clients; competing buttons here just muddied the flow. */}
        <ConfirmDialog
          trigger={<button className="p-2 rounded-lg text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"><Trash2 size={17} /></button>}
          title="Delete project"
          description={`Delete "${project.name}"? This cannot be undone.`}
          confirmLabel="Delete"
          variant="danger"
          onConfirm={async () => {
            await apiDelete(`/api/v1/projects/${id}`);
            toast.success('Project deleted');
            navigate('/app/projects');
          }}
        />
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border mb-6 gap-0">
        {TABS.map(tab => (
          <button key={tab} onClick={() => setActiveTab(tab)}
            className={`px-4 py-2.5 transition-colors border-b-2 -mb-px ${
              activeTab === tab ? 'border-foreground text-foreground font-medium' : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
            style={{ fontSize: '0.875rem' }}>
            {tab}
            {tab === 'Jobs' && jobs.length > 0 && (
              <span className="ml-1.5 px-1.5 py-0.5 rounded-full bg-secondary text-muted-foreground" style={{ fontSize: '0.7rem' }}>{jobs.length}</span>
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'Overview' && (
        <div className="grid lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-4">
            {/* Phase 1 then Phase 2 — the doc-type picker stays gated until a
                knowledge base exists, which is the flow the split exists for. */}
            <KnowledgeBasePanel
              projectId={id!}
              hasSources={(project.sources?.length ?? project.stats?.source_count ?? 0) > 0}
              onJobStarted={j => setJobs(prev => [j, ...prev])}
            />
            <div className="bg-card border border-border rounded-xl p-5">
              <h2 className="text-foreground mb-4" style={{ fontSize: '0.9375rem', fontWeight: 600 }}>Project Details</h2>
              <dl className="space-y-3">
                <div className="flex"><dt className="w-32 text-muted-foreground" style={{ fontSize: '0.875rem' }}>Name</dt><dd className="text-foreground" style={{ fontSize: '0.875rem' }}>{project.name}</dd></div>
                {project.description && <div className="flex"><dt className="w-32 text-muted-foreground" style={{ fontSize: '0.875rem' }}>Description</dt><dd className="text-foreground" style={{ fontSize: '0.875rem' }}>{project.description}</dd></div>}
                <div className="flex"><dt className="w-32 text-muted-foreground" style={{ fontSize: '0.875rem' }}>Created</dt><dd className="text-foreground" style={{ fontSize: '0.875rem' }}>{project.created_at ? formatDistanceToNow(new Date(project.created_at), { addSuffix: true }) : '—'}</dd></div>
                <div className="flex"><dt className="w-32 text-muted-foreground" style={{ fontSize: '0.875rem' }}>Sources</dt><dd className="text-foreground" style={{ fontSize: '0.875rem' }}>{project.stats?.source_count || 0}</dd></div>
              </dl>
            </div>
          </div>
          <div className="space-y-4">
            <div className="bg-card border border-border rounded-xl p-5">
              <h2 className="text-foreground mb-3" style={{ fontSize: '0.875rem', fontWeight: 600 }}>Quick Stats</h2>
              {[
                { label: 'Jobs', value: project.stats?.job_count || jobs.length || 0 },
                { label: 'Documents', value: project.stats?.doc_count || documents.length || 0 },
                { label: 'Sources', value: project.stats?.source_count || 0 },
              ].map(s => (
                <div key={s.label} className="flex items-center justify-between py-2 border-b border-border last:border-0">
                  <span className="text-muted-foreground" style={{ fontSize: '0.875rem' }}>{s.label}</span>
                  <span className="text-foreground" style={{ fontSize: '0.875rem', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{s.value}</span>
                </div>
              ))}
            </div>
            {project.latest_job && (
              <div className="bg-card border border-border rounded-xl p-5">
                <h2 className="text-foreground mb-3" style={{ fontSize: '0.875rem', fontWeight: 600 }}>Latest Job</h2>
                <StatusBadge status={project.latest_job.status} />
              </div>
            )}
          </div>
        </div>
      )}

      {activeTab === 'Sources' && (
        <SourcesTab
          project={project}
          projectId={id!}
          onProjectUpdated={setProject}
        />
      )}

      {activeTab === 'Jobs' && (
        <div className="bg-card border border-border rounded-xl overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-border">
            <h2 className="text-foreground" style={{ fontSize: '0.9375rem', fontWeight: 600 }}>Jobs</h2>
            <button
              onClick={() => setActiveTab('Overview')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
              style={{ fontSize: '0.8125rem' }}
            >
              <Play size={13} /> New job
            </button>
          </div>
          {jobs.length === 0 ? (
            <EmptyState icon={<Play size={32} />} title="No jobs yet" description="Run your first documentation job to get started." />
          ) : (
            <table className="w-full">
              <thead><tr className="border-b border-border">
                {['#', 'Phase', 'Status', 'Produces', 'Started', 'Took', ''].map(h => (
                  <th key={h} className="px-5 py-3 text-left text-muted-foreground" style={{ fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{h}</th>
                ))}
              </tr></thead>
              <tbody className="divide-y divide-border">
                {jobs.map(job => {
                  const analysis = job.job_type === 'analysis';
                  return (
                    <tr key={job.id} className="hover:bg-secondary/30">
                      <td className="px-5 py-3"><span className="text-muted-foreground font-mono" style={{ fontSize: '0.8125rem' }}>#{job.id}</span></td>
                      <td className="px-5 py-3">
                        <Badge tone={analysis ? 'brand' : 'neutral'}>
                          {analysis ? 'Analysis' : 'Composition'}
                        </Badge>
                      </td>
                      <td className="px-5 py-3"><StatusPill status={job.status} /></td>
                      <td className="px-5 py-3">
                        <span className="text-muted-foreground" style={{ fontSize: '0.8125rem' }}>
                          {analysis
                            ? 'knowledge base'
                            : (job.doc_types?.map(humanize).join(', ') || '—')}
                        </span>
                      </td>
                      <td className="px-5 py-3"><span className="text-muted-foreground" style={{ fontSize: '0.8125rem' }}>{job.started_at ? formatDistanceToNow(new Date(job.started_at), { addSuffix: true }) : '—'}</span></td>
                      <td className="px-5 py-3">
                        <span className="text-muted-foreground tabular-nums" style={{ fontSize: '0.8125rem', fontFamily: 'var(--font-mono)' }}>
                          {formatDuration(elapsedSeconds(job.started_at, job.completed_at))}
                        </span>
                      </td>
                      <td className="px-5 py-3">
                        <Link to={`/app/projects/${id}/jobs/${job.id}`}
                          className="inline-flex items-center gap-1.5 text-brand hover:underline" style={{ fontSize: '0.8125rem' }}>
                          <Eye size={13} /> View
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {activeTab === 'Documents' && (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {documents.length === 0 ? (
            <div className="col-span-3"><EmptyState icon={<FileTextIcon />} title="No documents yet" description="Run a job to generate documentation." /></div>
          ) : documents.map(doc => (
            <Link key={doc.id} to={`/app/documents/${doc.id}`}
              className="bg-card border border-border rounded-xl p-5 hover:border-foreground/20 hover:shadow-sm transition-all">
              <div className="flex items-center gap-2 mb-3">
                <span style={{ fontSize: '1.25rem' }}>{DOC_TYPE_ICONS[doc.doc_type] || '📄'}</span>
                <StatusBadge status={doc.status} size="sm" />
              </div>
              <h3 className="text-foreground mb-1 line-clamp-2" style={{ fontSize: '0.9rem', fontWeight: 600 }}>{doc.title}</h3>
              {doc.word_count && <p className="text-muted-foreground" style={{ fontSize: '0.75rem' }}>{doc.word_count.toLocaleString()} words</p>}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function FileTextIcon() { return <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>; }

// ── Source type helpers ───────────────────────────────────────────────────────

type SourceKind = 'github' | 'gitlab' | 'bitbucket' | 'local' | string;

const SOURCE_META: Record<string, { label: string; color: string; bg: string; Icon: React.ElementType }> = {
  github:    { label: 'GitHub',    color: '#a78bfa', bg: 'rgba(167,139,250,0.12)', Icon: Github },
  gitlab:    { label: 'GitLab',    color: '#fb923c', bg: 'rgba(251,146,60,0.12)',  Icon: Globe },
  bitbucket: { label: 'Bitbucket', color: '#38bdf8', bg: 'rgba(56,189,248,0.12)',  Icon: Globe },
  local:     { label: 'Upload',    color: '#94a3b8', bg: 'rgba(148,163,184,0.1)',  Icon: Upload },
};

function getSourceMeta(kind: SourceKind) {
  return SOURCE_META[kind] ?? { label: kind, color: '#94a3b8', bg: 'rgba(148,163,184,0.1)', Icon: HardDrive };
}

function sourceDisplayName(s: { url_or_path: string; config_json?: { original_filename?: string } }): string {
  if (s.config_json?.original_filename) return s.config_json.original_filename;
  const path = s.url_or_path;
  // For git URLs strip protocol and trailing .git
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path.replace(/^https?:\/\//, '').replace(/\.git$/, '');
  }
  // For local paths show just the last two segments
  const parts = path.replace(/\\/g, '/').split('/').filter(Boolean);
  return parts.slice(-2).join('/') || path;
}

// ── SourceRow ─────────────────────────────────────────────────────────────────

function SourceRow({ source, onDelete }: {
  source: import('../../lib/types').Source;
  onDelete: (id: string) => void;
}) {
  const kind: SourceKind = (source.source_type || source.type || 'local') as SourceKind;
  const isGit = ['github', 'gitlab', 'bitbucket'].includes(kind);
  const meta = getSourceMeta(kind);
  const { Icon } = meta;
  const displayName = sourceDisplayName(source);

  return (
    <div className="flex items-center gap-4 px-5 py-4 border-b border-border last:border-0 hover:bg-secondary/20 transition-colors group">
      {/* Icon */}
      <div className="flex-shrink-0 w-9 h-9 rounded-lg flex items-center justify-center" style={{ background: meta.bg }}>
        <Icon size={16} style={{ color: meta.color }} />
      </div>

      {/* Main info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-mono text-foreground truncate" style={{ fontSize: '0.8125rem', maxWidth: '38rem' }} title={source.url_or_path}>
            {displayName}
          </span>
          {/* Type badge */}
          <span className="flex-shrink-0 px-2 py-0.5 rounded-full" style={{ fontSize: '0.6875rem', fontWeight: 600, color: meta.color, background: meta.bg, letterSpacing: '0.02em' }}>
            {meta.label}
          </span>
          {/* Branch badge — only for git sources */}
          {isGit && source.branch && (
            <span className="flex-shrink-0 inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-secondary text-muted-foreground" style={{ fontSize: '0.6875rem' }}>
              <GitBranch size={10} /> {source.branch}
            </span>
          )}
        </div>
        <p className="text-muted-foreground mt-0.5" style={{ fontSize: '0.75rem' }}>
          Added {source.created_at ? formatDistanceToNow(new Date(source.created_at), { addSuffix: true }) : '—'}
        </p>
      </div>

      {/* Delete */}
      <ConfirmDialog
        trigger={
          <button
            className="flex-shrink-0 p-1.5 rounded-lg text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-destructive hover:bg-destructive/10 transition-all"
            title="Remove source"
          >
            <Trash2 size={15} />
          </button>
        }
        title="Remove source"
        description={`Remove "${displayName}" from this project? The source will be deleted but existing documents won't be affected.`}
        confirmLabel="Remove"
        variant="danger"
        onConfirm={() => onDelete(source.id)}
      />
    </div>
  );
}

// ── SourcesTab ────────────────────────────────────────────────────────────────

function SourcesTab({ project, projectId, onProjectUpdated }: {
  project: import('../../lib/types').Project;
  projectId: string;
  onProjectUpdated: (p: import('../../lib/types').Project) => void;
}) {
  const sources = project.sources || [];

  const refreshProject = async () => {
    const updated = await apiGet<import('../../lib/types').Project>(`/api/v1/projects/${projectId}`);
    onProjectUpdated(updated);
  };

  const handleDelete = async (sourceId: string) => {
    try {
      await apiDelete(`/api/v1/projects/${projectId}/sources/${sourceId}`);
      toast.success('Source removed');
      await refreshProject();
    } catch {
      toast.error('Failed to remove source');
    }
  };

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-5 py-4 border-b border-border">
        <div>
          <h2 className="text-foreground" style={{ fontSize: '0.9375rem', fontWeight: 600 }}>Sources</h2>
          {sources.length > 0 && (
            <p className="text-muted-foreground" style={{ fontSize: '0.75rem' }}>{sources.length} source{sources.length !== 1 ? 's' : ''}</p>
          )}
        </div>
        <AddSourceModal projectId={projectId} onAdded={refreshProject} />
      </div>

      {sources.length === 0 ? (
        <EmptyState
          icon={<Upload size={32} />}
          title="No sources yet"
          description="Add a GitHub/GitLab/Bitbucket repo or upload files to get started."
        />
      ) : (
        <div>
          {sources.map(s => (
            <SourceRow key={s.id} source={s} onDelete={handleDelete} />
          ))}
        </div>
      )}
    </div>
  );
}

import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { Plus, FolderOpen, MoreHorizontal, Pencil, Trash2, UploadCloud, X, FileArchive, FileText, File } from 'lucide-react';
import * as Dialog from '@radix-ui/react-dialog';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { apiGet, apiPost, apiDelete } from '../../lib/api';
import type { Project } from '../../lib/types';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { Spinner } from '../../components/shared/Spinner';
import { EmptyState } from '../../components/shared/EmptyState';
import { ConfirmDialog } from '../../components/shared/ConfirmDialog';
import { toast } from 'sonner';
import { formatDistanceToNow } from 'date-fns';

const SOURCE_COLORS = ['#3b82f6', '#8b5cf6', '#f59e0b', '#10b981', '#f43f5e', '#06b6d4'];
function projectColor(name: string) {
  let hash = 0;
  for (const c of name) hash = c.charCodeAt(0) + ((hash << 5) - hash);
  return SOURCE_COLORS[Math.abs(hash) % SOURCE_COLORS.length];
}

type Step = 'name' | 'source';
export type SourceTab = 'github' | 'gitlab' | 'bitbucket' | 'upload';

// ── Shared upload drop-zone ─────────────────────────────────────────────────

function fileIcon(file: File) {
  if (file.name.endsWith('.zip')) return <FileArchive size={16} className="text-amber-500" />;
  if (file.type.startsWith('text/') || file.name.match(/\.(md|txt|rst)$/i)) return <FileText size={16} className="text-blue-400" />;
  return <File size={16} className="text-muted-foreground" />;
}

export function UploadDropZone({
  file, onFile,
}: { file: File | null; onFile: (f: File | null) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const accept = [
    '.zip',
    '.py', '.js', '.ts', '.jsx', '.tsx', '.go', '.rs', '.java', '.kt',
    '.c', '.cpp', '.h', '.cs', '.rb', '.php', '.sh',
    '.toml', '.yaml', '.yml', '.json', '.xml', '.env', '.ini',
    '.md', '.mdx', '.txt', '.rst', '.pdf',
    '.html', '.css',
  ].join(',');

  return (
    <div>
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => {
          e.preventDefault();
          setDragging(false);
          const f = e.dataTransfer.files[0];
          if (f) onFile(f);
        }}
        className={`relative flex flex-col items-center justify-center gap-2 border-2 border-dashed rounded-xl p-6 cursor-pointer transition-all
          ${dragging ? 'border-primary bg-primary/5' : 'border-border hover:border-foreground/30 hover:bg-secondary/40'}`}
      >
        <UploadCloud size={28} className="text-muted-foreground" />
        <p className="text-foreground text-center" style={{ fontSize: '0.875rem', fontWeight: 500 }}>
          {file ? 'Replace file' : 'Drop a file here, or click to browse'}
        </p>
        <p className="text-muted-foreground text-center" style={{ fontSize: '0.75rem' }}>
          Code files, text, Markdown, PDF — or a <strong>.zip</strong> of a full repo
        </p>
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          className="hidden"
          onChange={e => { const f = e.target.files?.[0]; if (f) onFile(f); }}
        />
      </div>
      {file && (
        <div className="mt-2 flex items-center gap-2 px-3 py-2 rounded-lg border border-border bg-secondary/40">
          {fileIcon(file)}
          <span className="flex-1 truncate text-foreground" style={{ fontSize: '0.8125rem' }}>{file.name}</span>
          <span className="text-muted-foreground shrink-0" style={{ fontSize: '0.75rem' }}>
            {(file.size / 1024).toFixed(0)} KB
          </span>
          <button onClick={e => { e.stopPropagation(); onFile(null); }} className="p-0.5 rounded text-muted-foreground hover:text-foreground transition-colors">
            <X size={14} />
          </button>
        </div>
      )}
    </div>
  );
}

// ── Shared source form body (used in both Create and Add-source modals) ──────

export function SourceFormBody({
  sourceTab, setSourceTab,
  sourceUrl, setSourceUrl,
  branch, setBranch,
  token, setToken,
  uploadFile, setUploadFile,
}: {
  sourceTab: SourceTab; setSourceTab: (t: SourceTab) => void;
  sourceUrl: string; setSourceUrl: (v: string) => void;
  branch: string; setBranch: (v: string) => void;
  token: string; setToken: (v: string) => void;
  uploadFile: File | null; setUploadFile: (f: File | null) => void;
}) {
  const tabs: SourceTab[] = ['github', 'gitlab', 'bitbucket', 'upload'];
  const tabLabel: Record<SourceTab, string> = { github: 'GitHub', gitlab: 'GitLab', bitbucket: 'Bitbucket', upload: 'Upload' };

  return (
    <div className="space-y-4">
      <div className="flex border border-border rounded-lg overflow-hidden">
        {tabs.map(t => (
          <button key={t} onClick={() => setSourceTab(t)}
            className={`flex-1 py-2 transition-colors ${sourceTab === t ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-secondary'}`}
            style={{ fontSize: '0.8125rem', fontWeight: sourceTab === t ? 500 : 400 }}>
            {tabLabel[t]}
          </button>
        ))}
      </div>

      {sourceTab === 'upload' ? (
        <UploadDropZone file={uploadFile} onFile={setUploadFile} />
      ) : (
        <>
          <div>
            <label className="block text-foreground mb-1.5" style={{ fontSize: '0.875rem', fontWeight: 500 }}>Repository URL</label>
            <input value={sourceUrl} onChange={e => setSourceUrl(e.target.value)}
              placeholder={`https://${sourceTab}.com/user/repo`}
              className="w-full px-3 py-2.5 rounded-lg border border-border bg-input-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-all"
              style={{ fontSize: '0.9rem' }} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-foreground mb-1.5" style={{ fontSize: '0.875rem', fontWeight: 500 }}>Branch</label>
              <input value={branch} onChange={e => setBranch(e.target.value)} placeholder="main"
                className="w-full px-3 py-2.5 rounded-lg border border-border bg-input-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-all"
                style={{ fontSize: '0.9rem' }} />
            </div>
            <div>
              <label className="block text-foreground mb-1.5" style={{ fontSize: '0.875rem', fontWeight: 500 }}>Token (optional)</label>
              <input type="password" value={token} onChange={e => setToken(e.target.value)} placeholder="••••••"
                className="w-full px-3 py-2.5 rounded-lg border border-border bg-input-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-all"
                style={{ fontSize: '0.9rem' }} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────

export async function submitSource(
  projectId: string,
  sourceTab: SourceTab,
  sourceUrl: string,
  branch: string,
  token: string,
  uploadFile: File | null,
) {
  if (sourceTab === 'upload') {
    if (!uploadFile) return;
    const form = new FormData();
    form.append('file', uploadFile);
    const BASE_URL = (import.meta as { env: Record<string, string> }).env.VITE_API_URL || 'http://localhost:8000';
    const authToken = localStorage.getItem('docany_token') || '';
    const res = await fetch(`${BASE_URL}/api/v1/projects/${projectId}/upload`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${authToken}` },
      body: form,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Upload failed');
    }
  } else {
    if (!sourceUrl.trim()) return;
    await apiPost(`/api/v1/projects/${projectId}/sources`, {
      source_type: sourceTab,
      url_or_path: sourceUrl,
      branch: branch || 'main',
      config_json: token ? { token } : {},
    });
  }
}

// ── Create Project modal ─────────────────────────────────────────────────────

function CreateProjectModal({ onCreated }: { onCreated: (p: Project) => void }) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<Step>('name');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [sourceTab, setSourceTab] = useState<SourceTab>('github');
  const [sourceUrl, setSourceUrl] = useState('');
  const [branch, setBranch] = useState('main');
  const [token, setToken] = useState('');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const reset = () => {
    setStep('name'); setName(''); setDescription('');
    setSourceTab('github'); setSourceUrl(''); setBranch('main'); setToken(''); setUploadFile(null);
  };

  const hasSource = sourceTab === 'upload' ? !!uploadFile : !!sourceUrl.trim();

  const handleCreate = async () => {
    setLoading(true);
    try {
      const project = await apiPost<Project>('/api/v1/projects', { name, description });
      if (hasSource) {
        await submitSource(project.id, sourceTab, sourceUrl, branch, token, uploadFile).catch(() => {});
      }
      toast.success('Project created!');
      onCreated(project);
      setOpen(false);
      reset();
      navigate(`/app/projects/${project.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create project');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(v) => { setOpen(v); if (!v) reset(); }}>
      <Dialog.Trigger asChild>
        <button className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
          style={{ fontSize: '0.875rem', fontWeight: 500 }}>
          <Plus size={16} /> New Project
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-lg bg-card border border-border rounded-xl shadow-xl p-6">
          <div className="flex items-center justify-between mb-5">
            <Dialog.Title className="text-foreground" style={{ fontSize: '1rem', fontWeight: 600 }}>
              {step === 'name' ? 'New Project' : 'Add Source (optional)'}
            </Dialog.Title>
            <div className="flex items-center gap-1.5">
              {(['name', 'source'] as Step[]).map((s) => (
                <div key={s} className={`h-1.5 w-8 rounded-full transition-colors ${s === 'name' || step !== 'name' ? 'bg-primary' : 'bg-border'}`} />
              ))}
            </div>
          </div>

          {step === 'name' ? (
            <div className="space-y-4">
              <div>
                <label className="block text-foreground mb-1.5" style={{ fontSize: '0.875rem', fontWeight: 500 }}>Project name *</label>
                <input value={name} onChange={e => setName(e.target.value)}
                  placeholder="my-awesome-api"
                  className="w-full px-3 py-2.5 rounded-lg border border-border bg-input-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-all"
                  style={{ fontSize: '0.9rem' }} />
              </div>
              <div>
                <label className="block text-foreground mb-1.5" style={{ fontSize: '0.875rem', fontWeight: 500 }}>Description</label>
                <textarea value={description} onChange={e => setDescription(e.target.value)}
                  placeholder="Brief description of your project..."
                  rows={3}
                  className="w-full px-3 py-2.5 rounded-lg border border-border bg-input-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-all resize-none"
                  style={{ fontSize: '0.9rem' }} />
              </div>
              <div className="flex justify-end">
                <button onClick={() => name.trim() && setStep('source')} disabled={!name.trim()}
                  className="px-5 py-2.5 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
                  style={{ fontSize: '0.875rem', fontWeight: 500 }}>
                  Next →
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <SourceFormBody
                sourceTab={sourceTab} setSourceTab={setSourceTab}
                sourceUrl={sourceUrl} setSourceUrl={setSourceUrl}
                branch={branch} setBranch={setBranch}
                token={token} setToken={setToken}
                uploadFile={uploadFile} setUploadFile={setUploadFile}
              />
              <div className="flex justify-between">
                <button onClick={() => setStep('name')}
                  className="px-4 py-2 border border-border rounded-lg text-foreground hover:bg-secondary transition-colors"
                  style={{ fontSize: '0.875rem' }}>
                  ← Back
                </button>
                <div className="flex gap-2">
                  <button onClick={handleCreate} disabled={loading}
                    className="px-4 py-2 border border-border rounded-lg text-muted-foreground hover:bg-secondary transition-colors"
                    style={{ fontSize: '0.875rem' }}>
                    Skip
                  </button>
                  <button onClick={handleCreate} disabled={loading}
                    className="px-5 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-60 flex items-center gap-2"
                    style={{ fontSize: '0.875rem', fontWeight: 500 }}>
                    {loading
                      ? <><div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" /> Creating...</>
                      : 'Create Project'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function ProjectCard({ project, onDelete }: { project: Project; onDelete: (id: string) => void }) {
  const color = projectColor(project.name);
  return (
    <div className="bg-card border border-border rounded-xl p-5 hover:border-foreground/20 hover:shadow-sm transition-all group">
      <div className="flex items-start justify-between mb-4">
        <div className="w-10 h-10 rounded-xl flex items-center justify-center text-white flex-shrink-0"
          style={{ backgroundColor: color, fontSize: '1.0625rem', fontWeight: 700 }}>
          {project.name[0].toUpperCase()}
        </div>
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary opacity-0 group-hover:opacity-100 transition-all">
              <MoreHorizontal size={16} />
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content className="min-w-40 bg-card border border-border rounded-lg shadow-lg p-1 z-50">
              <DropdownMenu.Item asChild>
                <button className="flex items-center gap-2 w-full px-3 py-2 text-foreground hover:bg-secondary rounded-md transition-colors" style={{ fontSize: '0.875rem' }}>
                  <Pencil size={14} /> Edit name
                </button>
              </DropdownMenu.Item>
              <DropdownMenu.Separator className="h-px bg-border my-1" />
              <ConfirmDialog
                trigger={
                  <button className="flex items-center gap-2 w-full px-3 py-2 text-destructive hover:bg-destructive/10 rounded-md transition-colors" style={{ fontSize: '0.875rem' }}>
                    <Trash2 size={14} /> Delete
                  </button>
                }
                title="Delete project"
                description={`Are you sure you want to delete "${project.name}"? This will also delete all associated jobs and documents.`}
                confirmLabel="Delete"
                variant="danger"
                onConfirm={async () => {
                  await apiDelete(`/api/v1/projects/${project.id}`);
                  onDelete(project.id);
                  toast.success('Project deleted');
                }}
              />
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>

      <h3 className="text-foreground mb-1" style={{ fontSize: '0.9375rem', fontWeight: 600 }}>{project.name}</h3>
      {project.description && (
        <p className="text-muted-foreground mb-3 line-clamp-2" style={{ fontSize: '0.8125rem', lineHeight: 1.5 }}>{project.description}</p>
      )}

      <div className="flex items-center gap-3 mb-4 text-muted-foreground" style={{ fontSize: '0.75rem' }}>
        <span>{project.stats?.source_count || 0} sources</span>
        <span>·</span>
        <span>{project.stats?.job_count || 0} jobs</span>
        <span>·</span>
        <span>{project.stats?.doc_count || 0} docs</span>
      </div>

      <div className="flex items-center justify-between">
        {project.latest_job ? (
          <StatusBadge status={project.latest_job.status} size="sm" />
        ) : (
          <span className="text-muted-foreground" style={{ fontSize: '0.75rem' }}>No jobs yet</span>
        )}
        <Link to={`/app/projects/${project.id}`}
          className="text-brand hover:underline" style={{ fontSize: '0.8125rem', fontWeight: 500 }}>
          View →
        </Link>
      </div>
    </div>
  );
}

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiGet<Project[] | { items: Project[] }>('/api/v1/projects?limit=50')
      .then(data => {
        setProjects(Array.isArray(data) ? data : (data as { items: Project[] }).items || []);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleCreated = (p: Project) => setProjects(prev => [p, ...prev]);
  const handleDelete = (id: string) => setProjects(prev => prev.filter(p => p.id !== id));

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-foreground" style={{ fontSize: '1.375rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>Projects</h1>
          <p className="text-muted-foreground mt-0.5" style={{ fontSize: '0.875rem' }}>{projects.length} project{projects.length !== 1 ? 's' : ''}</p>
        </div>
        <CreateProjectModal onCreated={handleCreated} />
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Spinner size="lg" className="text-muted-foreground" />
        </div>
      ) : projects.length === 0 ? (
        <EmptyState
          icon={<FolderOpen size={40} />}
          title="No projects yet"
          description="Create your first project to start generating documentation."
          action={<CreateProjectModal onCreated={handleCreated} />}
        />
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {projects.map(p => (
            <ProjectCard key={p.id} project={p} onDelete={handleDelete} />
          ))}
        </div>
      )}
    </div>
  );
}

import { useEffect, useRef, useState, useCallback } from 'react';
import { useParams, Link } from 'react-router';
import { ArrowLeft, CheckCircle2, Circle, Loader2, XCircle, ChevronDown, Download, FileText } from 'lucide-react';
import { apiGet, apiPost, getStreamUrl } from '../../lib/api';
import type { Job, AgentLog, Document, DocType } from '../../lib/types';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { Spinner } from '../../components/shared/Spinner';
import { ConfirmDialog } from '../../components/shared/ConfirmDialog';
import { CopyButton } from '../../components/shared/CopyButton';
import { toast } from 'sonner';
import { formatDistanceToNow } from 'date-fns';

/**
 * Graph order from app/workflows/documentation_workflow.py. Used only to lay out
 * the not-yet-started agents — live status always comes from job.steps, and any
 * step the backend reports that isn't listed here is appended rather than hidden.
 */
const AGENT_PIPELINE = [
  'coordinator', 'repo_analyzer', 'code_understanding', 'architecture',
  'planner', 'strategy', 'writer', 'diagram', 'qa', 'formatter', 'publisher',
];

const AGENT_LABELS: Record<string, string> = {
  qa: 'QA',
  repo_analyzer: 'Repo Analyzer',
  code_understanding: 'Code Understanding',
};

const DOC_TYPE_ICONS: Record<DocType, string> = {
  architecture: '🏗️', api: '🔌', modules: '📦', getting_started: '🚀',
  deployment: '☁️', contributing: '🤝', changelog: '📋',
};

/** Backend names steps "<agent>_agent" (BaseAgent.name); strip that for matching. */
function normalizeAgent(name: string): string {
  return (name || '').replace(/_agent$/, '');
}

function agentLabel(name: string) {
  return AGENT_LABELS[name]
    ?? name.split('_').map(w => (w ? w[0].toUpperCase() + w.slice(1) : w)).join(' ');
}

interface PipelineRow {
  key: string;
  label: string;
  status: string;
  duration?: number;
}

function buildPipeline(steps: Job['steps']): PipelineRow[] {
  const byAgent = new Map<string, { status: string; duration_seconds?: number }>();
  for (const s of steps || []) {
    byAgent.set(normalizeAgent(s.name), s);
  }

  const rows: PipelineRow[] = AGENT_PIPELINE.map(agent => {
    const step = byAgent.get(agent);
    return {
      key: agent,
      label: agentLabel(agent),
      status: step?.status ?? 'pending',
      duration: step?.duration_seconds,
    };
  });

  // Surface anything the backend ran that isn't in the canonical list.
  for (const [agent, step] of byAgent) {
    if (!AGENT_PIPELINE.includes(agent)) {
      rows.push({
        key: agent,
        label: agentLabel(agent),
        status: step.status,
        duration: step.duration_seconds,
      });
    }
  }
  return rows;
}

function StepIcon({ status }: { status: string }) {
  if (status === 'completed') return <CheckCircle2 size={16} className="text-green-600 flex-shrink-0" />;
  if (status === 'running') return <Loader2 size={16} className="text-brand animate-spin flex-shrink-0" />;
  if (status === 'failed') return <XCircle size={16} className="text-destructive flex-shrink-0" />;
  return <Circle size={16} className="text-muted-foreground flex-shrink-0" />;
}

function LogLine({ log }: { log: AgentLog }) {
  const levelColors: Record<string, string> = { info: '#8a8784', warn: '#f59e0b', error: '#ef4444' };
  const levelIcons: Record<string, string> = { info: 'ℹ', warn: '⚠', error: '✖' };
  const agentColors = ['#60a5fa', '#34d399', '#a78bfa', '#f59e0b', '#f472b6', '#06b6d4', '#fb923c'];
  const agentColorIndex = log.agent ? log.agent.charCodeAt(0) % agentColors.length : 0;

  return (
    <div className="flex gap-3 py-0.5 hover:bg-white/5 px-1 rounded transition-colors group" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', lineHeight: 1.5 }}>
      <span className="text-gray-600 flex-shrink-0 tabular-nums">
        {log.timestamp ? new Date(log.timestamp).toLocaleTimeString('en-US', { hour12: false }) : '??:??:??'}
      </span>
      <span className="flex-shrink-0" style={{ color: agentColors[agentColorIndex] }}>
        [{log.agent}]
      </span>
      <span style={{ color: levelColors[log.level] || '#8a8784' }} className="flex-shrink-0">
        {levelIcons[log.level] || 'ℹ'}
      </span>
      <span className="text-gray-300 break-all">{log.message}</span>
    </div>
  );
}

const TABS = ['Live Logs', 'Plan', 'Review', 'Results'] as const;

export default function JobDetailPage() {
  const { id: projectId, jobId } = useParams<{ id: string; jobId: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [logs, setLogs] = useState<AgentLog[]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [activeTab, setActiveTab] = useState<typeof TABS[number]>('Live Logs');
  const [logFilter, setLogFilter] = useState('');
  const [levelFilter, setLevelFilter] = useState<'all' | 'info' | 'warn' | 'error'>('all');
  const [autoScroll, setAutoScroll] = useState(true);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [reviewComment, setReviewComment] = useState('');
  const [reviewLoading, setReviewLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const logsContainerRef = useRef<HTMLDivElement>(null);
  const esRef = useRef<EventSource | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchJob = useCallback(async () => {
    if (!jobId) return;
    try {
      const j = await apiGet<Job>(`/api/v1/jobs/${jobId}`);
      setJob(j);
      return j;
    } catch {}
  }, [jobId]);

  const fetchDocuments = useCallback(async () => {
    if (!projectId) return;
    try {
      const d = await apiGet<Document[] | { items: Document[] }>(`/api/v1/documents?project_id=${projectId}&limit=50`);
      setDocuments(Array.isArray(d) ? d : (d as { items: Document[] }).items || []);
    } catch {}
  }, [projectId]);

  const startSSE = useCallback((jobId: string) => {
    if (esRef.current) { esRef.current.close(); }
    const url = getStreamUrl(jobId);
    const es = new EventSource(url);
    esRef.current = es;

    es.onmessage = (e) => {
      try {
        const log = JSON.parse(e.data) as AgentLog;
        setLogs(prev => [...prev, log]);
      } catch {}
    };

    es.addEventListener('done', () => {
      es.close();
      esRef.current = null;
      fetchJob().then(j => {
        if (j?.status === 'completed') {
          toast.success('Documentation generated!');
          setActiveTab('Results');
          fetchDocuments();
        } else if (j?.status === 'awaiting_review') {
          toast.info('Job awaiting review');
          setActiveTab('Review');
        }
      });
    });

    es.onerror = () => {
      es.close();
      esRef.current = null;
    };
  }, [fetchJob, fetchDocuments]);

  useEffect(() => {
    if (!jobId) return;
    (async () => {
      const j = await fetchJob();
      setLoading(false);

      if (!j) return;

      if (j.status === 'running' || j.status === 'pending') {
        startSSE(jobId);
        pollRef.current = setInterval(fetchJob, 5000);
      } else {
        // Fetch static logs
        try {
          const l = await apiGet<AgentLog[]>(`/api/v1/jobs/${jobId}/logs`);
          setLogs(Array.isArray(l) ? l : []);
        } catch {}
        if (j.status === 'completed') {
          await fetchDocuments();
          setActiveTab('Results');
        } else if (j.status === 'awaiting_review') {
          setActiveTab('Review');
        }
      }
    })();

    return () => {
      esRef.current?.close();
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [jobId, fetchJob, startSSE, fetchDocuments]);

  // Step polling
  useEffect(() => {
    if (!job) return;
    if (job.status === 'running' || job.status === 'pending') {
      const t = setInterval(fetchJob, 3000);
      return () => clearInterval(t);
    }
  }, [job?.status, fetchJob]);

  // Auto-scroll
  useEffect(() => {
    if (autoScroll && isAtBottom) {
      logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoScroll, isAtBottom]);

  const handleScroll = () => {
    const el = logsContainerRef.current;
    if (!el) return;
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 50;
    setIsAtBottom(atBottom);
  };

  const handleApprove = async (approved: boolean) => {
    if (!jobId) return;
    setReviewLoading(true);
    try {
      await apiPost(`/api/v1/jobs/${jobId}/approve`, { approved, comment: reviewComment });
      toast.success(approved ? 'Documentation approved and published!' : 'Job rejected');
      fetchJob();
      if (approved) { setActiveTab('Results'); fetchDocuments(); }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed');
    } finally {
      setReviewLoading(false);
    }
  };

  const filteredLogs = logs.filter(l => {
    if (levelFilter !== 'all' && l.level !== levelFilter) return false;
    if (logFilter && !l.message?.toLowerCase().includes(logFilter.toLowerCase()) && !l.agent?.toLowerCase().includes(logFilter.toLowerCase())) return false;
    return true;
  });

  const downloadLogs = () => {
    const text = logs.map(l => `[${l.timestamp}] [${l.agent}] ${l.level.toUpperCase()} ${l.message}`).join('\n');
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = `job-${jobId}-logs.txt`; a.click();
    URL.revokeObjectURL(url);
  };

  const isRunning = job?.status === 'pending' || job?.status === 'running';
  const showReview = job?.status === 'awaiting_review';
  const showResults = job?.status === 'completed';

  if (loading) return <div className="flex items-center justify-center p-20"><Spinner size="lg" className="text-muted-foreground" /></div>;
  if (!job) return <div className="p-6 text-muted-foreground">Job not found</div>;

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <Link to={`/app/projects/${projectId}`} className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors">
          <ArrowLeft size={18} />
        </Link>
        <div>
          <h1 className="text-foreground" style={{ fontSize: '1.25rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
            Job #{jobId?.slice(-6)}
          </h1>
        </div>
      </div>

      <div className="grid lg:grid-cols-[380px_1fr] gap-6">
        {/* Left Panel */}
        <div className="space-y-4">
          {/* Job info card */}
          <div className="bg-card border border-border rounded-xl p-5">
            <div className="flex items-start justify-between mb-4">
              <div>
                <StatusBadge status={job.status} />
                <p className="text-muted-foreground mt-2" style={{ fontSize: '0.8125rem' }}>
                  {job.started_at ? formatDistanceToNow(new Date(job.started_at), { addSuffix: true }) : 'Not started'}
                </p>
              </div>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex flex-wrap gap-1">
                {job.doc_types?.map(t => (
                  <span key={t} className="px-2 py-0.5 rounded-md bg-secondary text-foreground capitalize" style={{ fontSize: '0.75rem' }}>
                    {DOC_TYPE_ICONS[t]} {t.replace(/_/g, ' ')}
                  </span>
                ))}
              </div>
              <div className="flex flex-wrap gap-1 mt-2">
                {job.output_formats?.map(f => (
                  <span key={f} className="px-2 py-0.5 rounded-md border border-border text-muted-foreground capitalize" style={{ fontSize: '0.75rem' }}>{f}</span>
                ))}
              </div>
            </div>
            {isRunning && (
              <ConfirmDialog
                trigger={<button className="mt-4 w-full px-3 py-2 border border-border rounded-lg text-muted-foreground hover:text-destructive hover:border-destructive transition-colors" style={{ fontSize: '0.8125rem' }}>Cancel Job</button>}
                title="Cancel job"
                description="Are you sure you want to cancel this job? This cannot be undone."
                confirmLabel="Cancel Job"
                variant="danger"
                onConfirm={async () => {
                  await apiPost(`/api/v1/jobs/${jobId}/cancel`, {});
                  toast.success('Job cancelled');
                  fetchJob();
                }}
              />
            )}
            {showResults && (
              <Link to="#" onClick={() => setActiveTab('Results')}
                className="mt-4 flex items-center justify-center gap-2 w-full px-3 py-2 bg-green-50 dark:bg-green-950 text-green-700 dark:text-green-300 rounded-lg border border-green-200 dark:border-green-800"
                style={{ fontSize: '0.8125rem', fontWeight: 500 }}>
                <FileText size={14} /> View Documents
              </Link>
            )}
          </div>

          {/* Agent pipeline */}
          <div className="bg-card border border-border rounded-xl p-5">
            <h2 className="text-foreground mb-4" style={{ fontSize: '0.875rem', fontWeight: 600 }}>Agent Pipeline</h2>
            <div className="space-y-2">
              {buildPipeline(job.steps).map(row => (
                <div key={row.key} className="flex items-center gap-3">
                  <StepIcon status={row.status} />
                  <div className="flex-1">
                    <span className={`${row.status === 'pending' ? 'text-muted-foreground' : 'text-foreground'}`} style={{ fontSize: '0.8125rem', fontWeight: row.status === 'running' ? 500 : 400 }}>
                      {row.label}
                    </span>
                  </div>
                  {row.duration != null && (
                    <span className="text-muted-foreground" style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)' }}>
                      {row.duration >= 10 ? Math.round(row.duration) : row.duration.toFixed(1)}s
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right Panel */}
        <div className="flex flex-col min-h-0">
          {/* Tabs */}
          <div className="flex border-b border-border mb-4">
            {TABS.filter(t => {
              if (t === 'Review' && !showReview) return false;
              if (t === 'Results' && !showResults) return false;
              return true;
            }).map(tab => (
              <button key={tab} onClick={() => setActiveTab(tab)}
                className={`px-4 py-2.5 border-b-2 -mb-px transition-colors ${
                  activeTab === tab ? 'border-foreground text-foreground font-medium' : 'border-transparent text-muted-foreground hover:text-foreground'
                }`}
                style={{ fontSize: '0.875rem' }}>
                {tab}
              </button>
            ))}
          </div>

          {/* Live Logs */}
          {activeTab === 'Live Logs' && (
            <div className="flex flex-col flex-1">
              {/* Toolbar */}
              <div className="flex items-center gap-2 mb-3 flex-wrap">
                <div className="relative flex-1 min-w-32">
                  <input value={logFilter} onChange={e => setLogFilter(e.target.value)} placeholder="Search logs..."
                    className="w-full pl-3 pr-3 py-1.5 rounded-lg border border-border bg-input-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                    style={{ fontSize: '0.8125rem' }} />
                </div>
                <select value={levelFilter} onChange={e => setLevelFilter(e.target.value as typeof levelFilter)}
                  className="px-2 py-1.5 rounded-lg border border-border bg-input-background text-foreground focus:outline-none"
                  style={{ fontSize: '0.8125rem' }}>
                  <option value="all">All levels</option>
                  <option value="info">Info</option>
                  <option value="warn">Warn</option>
                  <option value="error">Error</option>
                </select>
                <button onClick={downloadLogs} className="p-1.5 rounded-lg border border-border text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors" title="Download logs">
                  <Download size={15} />
                </button>
                <label className="flex items-center gap-1.5 text-muted-foreground cursor-pointer" style={{ fontSize: '0.8125rem' }}>
                  <input type="checkbox" checked={autoScroll} onChange={e => setAutoScroll(e.target.checked)} className="accent-primary" />
                  Auto-scroll
                </label>
              </div>

              {/* Terminal */}
              <div className="bg-gray-950 rounded-xl border border-gray-800 flex-1 relative overflow-hidden" style={{ minHeight: 400 }}>
                <div className="flex items-center gap-1.5 px-4 py-2.5 border-b border-gray-800">
                  <div className="w-2.5 h-2.5 rounded-full bg-red-500/60" />
                  <div className="w-2.5 h-2.5 rounded-full bg-yellow-500/60" />
                  <div className="w-2.5 h-2.5 rounded-full bg-green-500/60" />
                  <div className="ml-3 flex items-center gap-2">
                    {isRunning && <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />}
                    <span className="text-gray-500" style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)' }}>
                      {isRunning ? 'live' : 'completed'} · {logs.length} lines
                    </span>
                  </div>
                </div>
                <div ref={logsContainerRef} onScroll={handleScroll}
                  className="overflow-y-auto p-4"
                  style={{ maxHeight: 560 }}>
                  {filteredLogs.length === 0 ? (
                    <div className="flex items-center gap-2 text-gray-600" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8125rem' }}>
                      {isRunning ? (
                        <><Loader2 size={14} className="animate-spin" /> Waiting for agent logs...</>
                      ) : 'No logs'}
                    </div>
                  ) : (
                    filteredLogs.map((log, i) => <LogLine key={log.id || i} log={log} />)
                  )}
                  <div ref={logsEndRef} />
                </div>
                {!isAtBottom && (
                  <button onClick={() => { logsEndRef.current?.scrollIntoView({ behavior: 'smooth' }); setIsAtBottom(true); }}
                    className="absolute bottom-4 right-4 flex items-center gap-1.5 px-3 py-1.5 bg-gray-800 text-gray-300 rounded-full border border-gray-700 hover:bg-gray-700 transition-colors"
                    style={{ fontSize: '0.75rem' }}>
                    <ChevronDown size={13} /> Jump to bottom
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Plan */}
          {activeTab === 'Plan' && (
            <div className="bg-card border border-border rounded-xl p-5">
              <h2 className="text-foreground mb-4" style={{ fontSize: '0.9375rem', fontWeight: 600 }}>Documentation Plan</h2>
              {job.steps?.find(s => s.name === 'planner')?.output_json ? (
                <pre className="text-foreground whitespace-pre-wrap" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8125rem', lineHeight: 1.7 }}>
                  {JSON.stringify(job.steps.find(s => s.name === 'planner')?.output_json?.plan || job.steps.find(s => s.name === 'planner')?.output_json, null, 2)}
                </pre>
              ) : (
                <p className="text-muted-foreground" style={{ fontSize: '0.875rem' }}>
                  {isRunning ? 'Waiting for planner agent to complete...' : 'No plan data available.'}
                </p>
              )}
            </div>
          )}

          {/* Review */}
          {activeTab === 'Review' && showReview && (
            <div className="space-y-4">
              <div className="p-4 rounded-xl bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800">
                <p className="text-amber-700 dark:text-amber-300" style={{ fontSize: '0.875rem', fontWeight: 500 }}>
                  ⚠️ This job is awaiting your review before documents are published
                </p>
              </div>
              <div>
                <label className="block text-foreground mb-2" style={{ fontSize: '0.875rem', fontWeight: 500 }}>Review comment (optional)</label>
                <textarea value={reviewComment} onChange={e => setReviewComment(e.target.value)} rows={3} placeholder="Add feedback or notes..."
                  className="w-full px-3 py-2.5 rounded-lg border border-border bg-input-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-none"
                  style={{ fontSize: '0.875rem' }} />
              </div>
              <div className="flex gap-3">
                <button onClick={() => handleApprove(false)} disabled={reviewLoading}
                  className="flex-1 py-2.5 border border-border rounded-lg text-muted-foreground hover:text-destructive hover:border-destructive transition-colors"
                  style={{ fontSize: '0.875rem', fontWeight: 500 }}>
                  ✗ Reject
                </button>
                <button onClick={() => handleApprove(true)} disabled={reviewLoading}
                  className="flex-1 py-2.5 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors disabled:opacity-60"
                  style={{ fontSize: '0.875rem', fontWeight: 500 }}>
                  ✓ Approve & Publish
                </button>
              </div>
            </div>
          )}

          {/* Results */}
          {activeTab === 'Results' && showResults && (
            <div className="space-y-4">
              <div className="p-4 rounded-xl bg-green-50 dark:bg-green-950/30 border border-green-200 dark:border-green-800">
                <p className="text-green-700 dark:text-green-300" style={{ fontSize: '0.875rem', fontWeight: 500 }}>
                  ✓ Documentation generated successfully
                </p>
              </div>
              <div className="grid sm:grid-cols-2 gap-3">
                {documents.map(doc => (
                  <div key={doc.id} className="bg-card border border-border rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <span>{DOC_TYPE_ICONS[doc.doc_type] || '📄'}</span>
                      <span className="text-foreground flex-1 truncate" style={{ fontSize: '0.875rem', fontWeight: 600 }}>{doc.title}</span>
                    </div>
                    {doc.word_count && <p className="text-muted-foreground mb-3" style={{ fontSize: '0.75rem' }}>{doc.word_count.toLocaleString()} words</p>}
                    <Link to={`/app/documents/${doc.id}`}
                      className="inline-flex items-center gap-1.5 text-brand hover:underline" style={{ fontSize: '0.8125rem' }}>
                      <FileText size={13} /> Preview
                    </Link>
                  </div>
                ))}
                {documents.length === 0 && <p className="text-muted-foreground col-span-2" style={{ fontSize: '0.875rem' }}>No documents generated yet.</p>}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

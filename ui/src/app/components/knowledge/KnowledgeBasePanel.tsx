import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import {
  Brain, RefreshCw, Sparkles, FileText, Layers, Route, Package, Boxes, Loader2,
} from 'lucide-react';
import { toast } from 'sonner';

import { apiGet, apiPost } from '../../lib/api';
import { formatDuration, elapsedSeconds, humanize } from '../../lib/format';
import type { Job, KnowledgeBaseSummary } from '../../lib/types';
import { Badge, StatusPill } from '../shared/Badge';
import { Card, CardBody, CardHeader, Stat } from '../shared/Card';
import { Spinner } from '../shared/Spinner';

const ENTITY_ICONS: Record<string, typeof Route> = {
  route: Route,
  dependency: Package,
  entrypoint: Boxes,
  infra_resource: Layers,
};

/**
 * The two-phase flow, made visible.
 *
 * Phase 1 has to finish before the user is asked what to write — that is the whole
 * point of the split, so the composer stays disabled until a knowledge base exists,
 * and the suggestions it offers come from what analysis actually found.
 */
export function KnowledgeBasePanel({
  projectId,
  hasSources,
  onJobStarted,
}: {
  projectId: number | string;
  hasSources: boolean;
  onJobStarted: (job: Job) => void;
}) {
  const [summary, setSummary] = useState<KnowledgeBaseSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<'analyze' | 'compose' | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    try {
      const data = await apiGet<KnowledgeBaseSummary | null>(
        `/api/v1/projects/${projectId}/knowledge-base`,
      );
      setSummary(data);
      if (data?.suggested_doc_types?.length && selected.length === 0) {
        // Pre-select the strongest suggestion so the common path is one click.
        setSelected([data.suggested_doc_types[0].doc_type]);
      }
    } catch {
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }, [projectId, selected.length]);

  useEffect(() => {
    load();
  }, [load]);

  // While a build is in flight the panel polls, so the user sees it land.
  const kbStatus = summary?.knowledge_base.status;
  useEffect(() => {
    if (kbStatus !== 'running' && kbStatus !== 'pending') return;
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [kbStatus, load]);

  const analyze = async (force: boolean) => {
    setBusy('analyze');
    try {
      const job = await apiPost<Job>(`/api/v1/projects/${projectId}/analyze`, { force });
      toast.success(force ? 'Re-analysis started' : 'Analysis started');
      onJobStarted(job);
      navigate(`/app/projects/${projectId}/jobs/${job.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not start analysis');
    } finally {
      setBusy(null);
    }
  };

  const compose = async () => {
    if (!selected.length) return;
    setBusy('compose');
    try {
      const job = await apiPost<Job>(`/api/v1/projects/${projectId}/compose`, {
        doc_types: selected,
        output_formats: ['markdown'],
        human_review: false,
      });
      toast.success(`Composing ${selected.length} document${selected.length > 1 ? 's' : ''}`);
      onJobStarted(job);
      navigate(`/app/projects/${projectId}/jobs/${job.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not start composition');
    } finally {
      setBusy(null);
    }
  };

  if (loading) {
    return (
      <Card>
        <CardBody className="pt-5 flex items-center gap-3 text-muted-foreground">
          <Spinner size="sm" /> <span style={{ fontSize: '0.875rem' }}>Checking knowledge base…</span>
        </CardBody>
      </Card>
    );
  }

  // ── Never analysed ────────────────────────────────────────────────────────
  if (!summary) {
    return (
      <Card accent>
        <CardHeader
          icon={<Brain size={17} />}
          title="Analyse this codebase first"
          subtitle="We build a knowledge base once, then you choose what to write from it."
        />
        <CardBody>
          <p className="text-muted-foreground mb-4" style={{ fontSize: '0.8125rem', lineHeight: 1.6 }}>
            Analysis reads the source, maps its modules, extracts routes and dependencies,
            and writes reusable summaries. Every document type you ask for afterwards is
            composed from that — no re-reading the repository.
          </p>
          <button
            onClick={() => analyze(false)}
            disabled={busy !== null || !hasSources}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-brand text-brand-foreground hover:opacity-90 transition-opacity disabled:opacity-50"
            style={{ fontSize: '0.875rem', fontWeight: 600 }}
          >
            {busy === 'analyze' ? <Loader2 size={15} className="animate-spin" /> : <Brain size={15} />}
            Analyse codebase
          </button>
          {!hasSources && (
            <p className="text-muted-foreground mt-3" style={{ fontSize: '0.75rem' }}>
              Add a source on the Sources tab first.
            </p>
          )}
        </CardBody>
      </Card>
    );
  }

  const kb = summary.knowledge_base;
  const building = kb.status === 'running' || kb.status === 'pending';
  const usable = kb.status === 'ready' || kb.status === 'degraded';
  const buildTime = elapsedSeconds(kb.created_at, kb.completed_at);

  return (
    <div className="space-y-4">
      <Card accent={usable}>
        <CardHeader
          icon={building ? <Loader2 size={17} className="animate-spin" /> : <Brain size={17} />}
          title={
            <span className="flex items-center gap-2">
              Knowledge base
              <StatusPill status={kb.status} />
              {kb.commit_sha && (
                <Badge tone="muted" mono>{kb.commit_sha.slice(0, 7)}</Badge>
              )}
            </span>
          }
          subtitle={
            building
              ? 'Reading the codebase — this runs once per commit.'
              : `Built in ${formatDuration(buildTime)} · reused by every document`
          }
          actions={
            !building && (
              <button
                onClick={() => analyze(true)}
                disabled={busy !== null}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors disabled:opacity-50"
                style={{ fontSize: '0.8125rem' }}
                title="Re-read the repository and rebuild"
              >
                <RefreshCw size={13} /> Re-analyse
              </button>
            )
          }
        />
        <CardBody>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 pb-4 border-b border-border">
            <Stat label="modules" value={summary.module_count} />
            <Stat label="facts extracted" value={summary.entity_count} />
            <Stat label="narratives" value={summary.narrative_topics.length} />
            <Stat
              label="languages"
              value={summary.languages.length || '—'}
              hint={summary.languages.join(', ') || undefined}
            />
          </div>

          {Object.keys(summary.entity_kinds).length > 0 && (
            <div className="flex flex-wrap gap-1.5 pt-4">
              {Object.entries(summary.entity_kinds)
                .sort((a, b) => b[1] - a[1])
                .map(([kind, count]) => {
                  const Icon = ENTITY_ICONS[kind];
                  return (
                    <Badge key={kind} tone="neutral" icon={Icon ? <Icon size={11} /> : undefined}>
                      {count} {humanize(kind)}
                      {count === 1 ? '' : 's'}
                    </Badge>
                  );
                })}
            </div>
          )}

          {kb.status === 'degraded' && kb.error_message && (
            <p
              className="mt-4 p-3 rounded-lg bg-[#fbbf24]/10 border border-[#fbbf24]/25 text-[#fbbf24]"
              style={{ fontSize: '0.75rem' }}
            >
              Built with warnings: {kb.error_message}. Documents can still be composed.
            </p>
          )}
        </CardBody>
      </Card>

      {usable && (
        <Card>
          <CardHeader
            icon={<Sparkles size={17} />}
            title="What should we write?"
            subtitle="Suggestions are based on what the analysis actually found."
          />
          <CardBody>
            <div className="grid sm:grid-cols-2 gap-2.5">
              {summary.suggested_doc_types.map(s => {
                const on = selected.includes(s.doc_type);
                return (
                  <button
                    key={s.doc_type}
                    onClick={() =>
                      setSelected(prev =>
                        on ? prev.filter(d => d !== s.doc_type) : [...prev, s.doc_type],
                      )
                    }
                    className={`text-left p-3.5 rounded-lg border transition-all ${
                      on
                        ? 'border-brand bg-brand/10'
                        : 'border-border bg-card hover:border-brand/40 hover:bg-secondary/40'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <span
                        className="text-foreground flex items-center gap-2"
                        style={{ fontSize: '0.875rem', fontWeight: 600 }}
                      >
                        <FileText size={13} className={on ? 'text-brand' : 'text-muted-foreground'} />
                        {humanize(s.doc_type)}

                      </span>
                      <Badge tone={s.confidence >= 0.8 ? 'success' : 'muted'} mono>
                        {Math.round(s.confidence * 100)}%
                      </Badge>
                    </div>
                    <p className="text-muted-foreground" style={{ fontSize: '0.75rem' }}>
                      {s.reason}
                    </p>
                  </button>
                );
              })}
            </div>

            <button
              onClick={compose}
              disabled={busy !== null || selected.length === 0}
              className="mt-4 w-full inline-flex items-center justify-center gap-2 py-2.5 rounded-lg bg-brand text-brand-foreground hover:opacity-90 transition-opacity disabled:opacity-40"
              style={{ fontSize: '0.9375rem', fontWeight: 600 }}
            >
              {busy === 'compose' ? (
                <Loader2 size={15} className="animate-spin" />
              ) : (
                <Sparkles size={15} />
              )}
              {selected.length
                ? `Compose ${selected.length} document${selected.length > 1 ? 's' : ''}`
                : 'Select a document type'}
            </button>
            <p className="text-center text-muted-foreground mt-2" style={{ fontSize: '0.7rem' }}>
              Composition reuses the knowledge base — the codebase is not read again.
            </p>
          </CardBody>
        </Card>
      )}
    </div>
  );
}

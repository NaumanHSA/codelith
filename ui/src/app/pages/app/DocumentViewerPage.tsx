import { useEffect, useState, useRef, useCallback, type JSX } from 'react';
import { useParams, Link } from 'react-router';
import { ArrowLeft, Download, Edit2, Check, X } from 'lucide-react';
import { apiGet, apiPatch, apiPost } from '../../lib/api';
import type { Document, DocType } from '../../lib/types';
import { StatusBadge } from '../../components/shared/StatusBadge';
import { Spinner } from '../../components/shared/Spinner';
import { CopyButton } from '../../components/shared/CopyButton';
import { toast } from 'sonner';

const DOC_TYPE_ICONS: Record<DocType, string> = {
  architecture: '🏗️', api: '🔌', modules: '📦', getting_started: '🚀',
  deployment: '☁️', contributing: '🤝', changelog: '📋',
};

/**
 * Slugs must be unique or the TOC links several entries at the same anchor (and
 * React sees duplicate keys). Repeats get -1, -2, … like GitHub.
 *
 * extractHeadings and SimpleMarkdown each build their own slugger, so both must
 * walk the document the same way — same heading levels, both skipping fenced
 * code — or the TOC's hrefs stop matching the rendered ids.
 */
function createSlugger() {
  const seen = new Map<string, number>();
  return (text: string): string => {
    const base = text.toLowerCase().replace(/[^\w\s-]/g, '').replace(/\s+/g, '-');
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    return n === 0 ? base : `${base}-${n}`;
  };
}

function extractHeadings(markdown: string): { level: number; text: string; id: string }[] {
  const lines = markdown.split('\n');
  const headings: { level: number; text: string; id: string }[] = [];
  const slug = createSlugger();
  let inCode = false;
  for (const line of lines) {
    if (line.startsWith('```')) { inCode = !inCode; continue; }
    if (inCode) continue;
    const m = line.match(/^(#{1,3})\s+(.+)$/);
    if (m) {
      const level = m[1].length;
      const text = m[2].trim();
      headings.push({ level, text, id: slug(text) });
    }
  }
  return headings;
}

function SimpleMarkdown({ content }: { content: string }) {
  const lines = content.split('\n');
  const elements: JSX.Element[] = [];
  const slug = createSlugger();
  let i = 0;
  let codeBlock: string[] = [];
  let inCode = false;
  let codeLang = '';

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith('```')) {
      if (!inCode) {
        inCode = true;
        codeLang = line.slice(3).trim();
        codeBlock = [];
      } else {
        elements.push(
          <div key={i} className="relative group mb-4">
            <div className="absolute top-2 right-2 flex items-center gap-1.5">
              {codeLang && <span className="text-gray-500 text-xs">{codeLang}</span>}
              <CopyButton text={codeBlock.join('\n')} />
            </div>
            <pre className="bg-gray-950 dark:bg-black/50 rounded-xl border border-gray-800 p-4 overflow-x-auto" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8125rem', lineHeight: 1.7 }}>
              <code className="text-gray-300">{codeBlock.join('\n')}</code>
            </pre>
          </div>
        );
        inCode = false;
        codeBlock = [];
        codeLang = '';
      }
      i++;
      continue;
    }

    if (inCode) { codeBlock.push(line); i++; continue; }

    if (!line.trim()) { elements.push(<div key={i} className="h-3" />); i++; continue; }

    if (line.startsWith('# ')) {
      const id = slug(line.slice(2).trim());
      elements.push(<h1 key={i} id={id} className="text-foreground scroll-mt-6 mb-3 mt-8 first:mt-0" style={{ fontSize: '1.625rem', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{renderInline(line.slice(2))}</h1>);
    } else if (line.startsWith('## ')) {
      const id = slug(line.slice(3).trim());
      elements.push(<h2 key={i} id={id} className="text-foreground scroll-mt-6 mb-2 mt-7" style={{ fontSize: '1.25rem', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{renderInline(line.slice(3))}</h2>);
    } else if (line.startsWith('### ')) {
      const id = slug(line.slice(4).trim());
      elements.push(<h3 key={i} id={id} className="text-foreground scroll-mt-6 mb-2 mt-5" style={{ fontSize: '1.0625rem', fontWeight: 600 }}>{renderInline(line.slice(4))}</h3>);
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      // Key off the list's FIRST line: `i` has already advanced past the list by
      // the time we push, so keying on it collides with the next element.
      const start = i;
      const items: string[] = [];
      while (i < lines.length && (lines[i].startsWith('- ') || lines[i].startsWith('* '))) {
        items.push(lines[i].slice(2));
        i++;
      }
      elements.push(
        <ul key={`ul-${start}`} className="mb-4 space-y-1 pl-5 list-disc text-foreground" style={{ fontSize: '0.9375rem', lineHeight: 1.7 }}>
          {items.map((item, j) => <li key={j}>{renderInline(item)}</li>)}
        </ul>
      );
      continue;
    } else if (/^\d+\.\s/.test(line)) {
      const start = i;
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\.\s/, ''));
        i++;
      }
      elements.push(
        <ol key={`ol-${start}`} className="mb-4 space-y-1 pl-5 list-decimal text-foreground" style={{ fontSize: '0.9375rem', lineHeight: 1.7 }}>
          {items.map((item, j) => <li key={j}>{renderInline(item)}</li>)}
        </ol>
      );
      continue;
    } else if (line.startsWith('> ')) {
      elements.push(<blockquote key={i} className="border-l-4 border-border pl-4 my-4 text-muted-foreground italic" style={{ fontSize: '0.9375rem' }}>{renderInline(line.slice(2))}</blockquote>);
    } else if (line.startsWith('---') || line.startsWith('===')) {
      elements.push(<hr key={i} className="border-border my-6" />);
    } else {
      elements.push(<p key={i} className="text-foreground mb-3" style={{ fontSize: '0.9375rem', lineHeight: 1.8 }}>{renderInline(line)}</p>);
    }
    i++;
  }

  return <div>{elements}</div>;
}

function renderInline(text: string): React.ReactNode {
  // The link alternative's inner groups MUST stay non-capturing: String.split
  // splices every capture group into the result, and groups that didn't take
  // part in the match come back as `undefined`.
  const parts = (text ?? '').split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[(?:[^\]]+)\]\((?:[^)]+)\))/g);
  return parts.map((part, i) => {
    if (!part) return null;
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={i} className="px-1.5 py-0.5 rounded bg-secondary text-foreground" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.875em' }}>{part.slice(1, -1)}</code>;
    }
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i} className="text-foreground font-semibold">{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith('*') && part.endsWith('*') && !part.startsWith('**')) {
      return <em key={i}>{part.slice(1, -1)}</em>;
    }
    if (/^\[.+\]\(.+\)$/.test(part)) {
      const m = part.match(/^\[(.+)\]\((.+)\)$/);
      if (m) return <a key={i} href={m[2]} className="text-brand hover:underline" target="_blank" rel="noopener noreferrer">{m[1]}</a>;
    }
    return part;
  });
}

export default function DocumentViewerPage() {
  const { id } = useParams<{ id: string }>();
  const [doc, setDoc] = useState<Document | null>(null);
  const [loading, setLoading] = useState(true);
  const [editMode, setEditMode] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved'>('idle');
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleValue, setTitleValue] = useState('');
  const [activeHeading, setActiveHeading] = useState('');
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!id) return;
    apiGet<Document>(`/api/v1/documents/${id}`)
      .then(d => { setDoc(d); setEditContent(d.content_markdown || ''); setTitleValue(d.title); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [id]);

  const autoSave = useCallback((content: string) => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    setSaveState('saving');
    saveTimerRef.current = setTimeout(async () => {
      try {
        await apiPatch(`/api/v1/documents/${id}`, { content_markdown: content });
        setSaveState('saved');
        setTimeout(() => setSaveState('idle'), 2000);
      } catch {
        setSaveState('idle');
      }
    }, 500);
  }, [id]);

  const handleContentChange = (val: string) => { setEditContent(val); autoSave(val); };

  const handlePublish = async () => {
    try {
      await apiPost(`/api/v1/documents/${id}/publish`, {});
      setDoc(d => d ? { ...d, status: 'published' } : d);
      toast.success('Document published!');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to publish');
    }
  };

  const handleDownload = async (format: string) => {
    try {
      const data = await apiGet<{ url: string }>(`/api/v1/documents/${id}/export?format=${format}`);
      window.open(data.url, '_blank');
    } catch {
      const content = doc?.content_markdown || '';
      const blob = new Blob([content], { type: 'text/markdown' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = `${doc?.title || 'document'}.md`; a.click();
      URL.revokeObjectURL(url);
    }
  };

  const headings = extractHeadings(doc?.content_markdown || '');

  if (loading) return <div className="flex items-center justify-center p-20"><Spinner size="lg" className="text-muted-foreground" /></div>;
  if (!doc) return <div className="p-6 text-muted-foreground">Document not found</div>;

  return (
    <div className="flex h-full">
      {/* Left outline panel */}
      <aside className="hidden lg:flex flex-col w-64 flex-shrink-0 border-r border-border bg-card overflow-y-auto">
        <div className="p-4 border-b border-border">
          <Link to="/app/documents" className="flex items-center gap-1.5 text-muted-foreground hover:text-foreground transition-colors mb-3" style={{ fontSize: '0.8125rem' }}>
            <ArrowLeft size={14} /> Documents
          </Link>
          <div className="flex items-center gap-2">
            <span>{DOC_TYPE_ICONS[doc.doc_type] || '📄'}</span>
            <span className="text-foreground font-medium truncate" style={{ fontSize: '0.8125rem' }}>{doc.title}</span>
          </div>
          <div className="mt-2"><StatusBadge status={doc.status} size="sm" /></div>
        </div>

        {/* ToC */}
        {headings.length > 0 && (
          <nav className="p-3 flex-1">
            <p className="text-muted-foreground mb-2 px-2" style={{ fontSize: '0.7rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Contents</p>
            {headings.map((h) => (
              <a key={h.id} href={`#${h.id}`}
                className={`flex py-1.5 px-2 rounded-md hover:bg-secondary transition-colors ${activeHeading === h.id ? 'text-brand bg-secondary' : 'text-muted-foreground hover:text-foreground'}`}
                style={{ fontSize: '0.8125rem', paddingLeft: `${(h.level - 1) * 12 + 8}px` }}>
                {h.text}
              </a>
            ))}
          </nav>
        )}

        {/* Export */}
        <div className="p-3 border-t border-border space-y-1">
          <p className="text-muted-foreground px-2 mb-2" style={{ fontSize: '0.7rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Export</p>
          {['markdown', 'docx', 'mkdocs', 'docusaurus'].map(fmt => (
            <button key={fmt} onClick={() => handleDownload(fmt)}
              className="flex items-center gap-2 w-full px-2 py-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors capitalize"
              style={{ fontSize: '0.8125rem' }}>
              <Download size={13} /> {fmt}
            </button>
          ))}
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Toolbar */}
        <div className="sticky top-0 z-10 flex items-center justify-between px-6 py-3 border-b border-border bg-card flex-shrink-0">
          <div className="flex items-center gap-3 flex-1 min-w-0">
            <Link to="/app/documents" className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors lg:hidden">
              <ArrowLeft size={16} />
            </Link>
            {editingTitle ? (
              <div className="flex items-center gap-2 flex-1">
                <input value={titleValue} onChange={e => setTitleValue(e.target.value)}
                  className="flex-1 px-2 py-1 rounded-lg border border-ring bg-input-background text-foreground focus:outline-none"
                  style={{ fontSize: '0.9375rem', fontWeight: 600 }} autoFocus />
                <button onClick={async () => {
                  await apiPatch(`/api/v1/documents/${id}`, { title: titleValue });
                  setDoc(d => d ? { ...d, title: titleValue } : d);
                  setEditingTitle(false);
                  toast.success('Title updated');
                }} className="p-1 text-green-600 hover:bg-green-50 rounded-md"><Check size={15} /></button>
                <button onClick={() => { setTitleValue(doc.title); setEditingTitle(false); }} className="p-1 text-muted-foreground hover:bg-secondary rounded-md"><X size={15} /></button>
              </div>
            ) : (
              <h1 className="text-foreground truncate cursor-pointer hover:underline" style={{ fontSize: '0.9375rem', fontWeight: 600 }} onClick={() => setEditingTitle(true)}>
                {doc.title}
              </h1>
            )}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {saveState === 'saving' && <span className="text-muted-foreground" style={{ fontSize: '0.75rem' }}>Saving...</span>}
            {saveState === 'saved' && <span className="text-green-600" style={{ fontSize: '0.75rem' }}>Saved ✓</span>}
            <button onClick={() => setEditMode(m => !m)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border transition-colors ${editMode ? 'border-foreground bg-primary text-primary-foreground' : 'border-border text-muted-foreground hover:text-foreground hover:bg-secondary'}`}
              style={{ fontSize: '0.8125rem' }}>
              <Edit2 size={13} /> {editMode ? 'Reading' : 'Edit'}
            </button>
            {doc.status === 'draft' && (
              <button onClick={handlePublish}
                className="px-3 py-1.5 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
                style={{ fontSize: '0.8125rem', fontWeight: 500 }}>
                Publish
              </button>
            )}
          </div>
        </div>

        {/* Status banner */}
        {doc.status === 'draft' && (
          <div className="px-6 py-2.5 bg-amber-50 dark:bg-amber-950/30 border-b border-amber-200 dark:border-amber-800 flex items-center justify-between">
            <p className="text-amber-700 dark:text-amber-300" style={{ fontSize: '0.8125rem' }}>This document is not published yet</p>
            <button onClick={handlePublish} className="text-amber-700 dark:text-amber-300 hover:underline font-medium" style={{ fontSize: '0.8125rem' }}>Publish Now</button>
          </div>
        )}
        {doc.status === 'published' && (
          <div className="px-6 py-2 bg-green-50 dark:bg-green-950/30 border-b border-green-200 dark:border-green-800">
            <p className="text-green-700 dark:text-green-300" style={{ fontSize: '0.8125rem' }}>
              Published {doc.published_at ? `· ${new Date(doc.published_at).toLocaleDateString()}` : ''}
            </p>
          </div>
        )}

        {/* Content */}
        {editMode ? (
          <div className="flex flex-1 min-h-0">
            <div className="flex-1 border-r border-border">
              <textarea value={editContent} onChange={e => handleContentChange(e.target.value)}
                className="w-full h-full p-6 bg-card text-foreground resize-none focus:outline-none"
                style={{ fontFamily: 'var(--font-mono)', fontSize: '0.875rem', lineHeight: 1.7 }}
                placeholder="Write markdown here..." />
            </div>
            <div className="flex-1 overflow-y-auto p-6">
              <SimpleMarkdown content={editContent} />
            </div>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto p-8 max-w-4xl">
            {doc.content_markdown ? (
              <SimpleMarkdown content={doc.content_markdown} />
            ) : (
              <p className="text-muted-foreground" style={{ fontSize: '0.875rem' }}>No content available.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

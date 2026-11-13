import { Icon } from '../../lib/icons'
import { useState } from 'react'
import { api, ApiError } from '../../lib/api'
import type { SitePageDetail } from '../../lib/types'
import { Button } from '../ui'

/* ------------------------------------------------------------------ *
 * Asking for a page the site does not have.
 *
 * Free text, because the reader is describing a gap rather than filling
 * in a form. A title is optional and used verbatim when given — somebody
 * who named their page meant it.
 *
 * **It stops at `planned`.** The anchor files retrieval picked are what
 * the whole write depends on, and a bad set produces a confidently wrong
 * page for a quality-tier call per heading. Showing them costs nothing
 * and is the one moment they can be rejected — so the result is
 * presented here for approval rather than sent straight to the writer.
 * ------------------------------------------------------------------ */

export default function AddPage({
  projectId, sectionSlug, sectionTitle, onCreated, onOpen,
}: {
  projectId: number
  sectionSlug: string
  sectionTitle: string
  /** A `planned` page now exists — refresh the map. */
  onCreated: () => void
  onOpen: (page: SitePageDetail) => void
}) {
  const [open, setOpen] = useState(false)
  const [request, setRequest] = useState('')
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [made, setMade] = useState<SitePageDetail | null>(null)

  const reset = () => {
    setOpen(false)
    setRequest('')
    setTitle('')
    setError(null)
    setMade(null)
  }

  const submit = async () => {
    if (!request.trim() || busy) return
    setBusy(true)
    setError(null)
    try {
      const page = await api.addSitePage(projectId, {
        section_slug: sectionSlug,
        request: request.trim(),
        title: title.trim() || null,
      })
      setMade(page)
      onCreated()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not add that page.')
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex w-full items-center gap-2 rounded-xl border border-dashed border-line-2 px-3 py-2.5 text-left text-ink-mid transition-colors hover:border-hot-edge hover:bg-hover hover:text-ink"
      >
        <Icon name="sparkles" size={15} className="text-hot" />
        <span className="text-[13px] font-medium">Add a page with AI</span>
      </button>
    )
  }

  // ── What it made, for approval ──────────────────────────────────────────
  if (made) {
    return (
      <div className="rounded-xl border border-ok/50 bg-panel p-3">
        <span className="text-[12px] font-medium text-ok">Page added</span>
        <p className="mt-1 text-[12.5px] font-semibold text-ink">{made.title}</p>
        <p className="mt-0.5 text-[12px] leading-relaxed text-ink-mid">{made.intent}</p>

        <span className="text-[12px] font-medium mt-2.5 block text-ink-dim">It will be written from</span>
        <ul className="mt-1 space-y-0.5">
          {(made.key_files ?? []).map(f => (
            <li key={f} className="truncate font-mono text-[11.5px] text-ink-mid" title={f}>
              {f}
            </li>
          ))}
          {!made.key_files?.length && (
            <li className="text-[12px] text-warn">
              Retrieval found nothing to anchor it on: the page would be written from
              the narratives alone. Try describing it in the codebase's own words.
            </li>
          )}
        </ul>

        <p className="mt-2.5 text-[11.5px] leading-relaxed text-ink-dim">
          Nothing has been written yet. Open it to check those files, then write it.
        </p>
        <div className="mt-2 flex gap-2">
          <Button variant="hot" onClick={() => { onOpen(made); reset() }}>
            Open the page
          </Button>
          <Button variant="ghost" onClick={reset}>
            Done
          </Button>
        </div>
      </div>
    )
  }

  // ── The request ─────────────────────────────────────────────────────────
  return (
    <div className="rounded-lg border border-hot bg-hot-wash/40 p-3">
      <span className="text-[12px] font-medium block text-hot-ink">New page in {sectionTitle}</span>
      <textarea
        autoFocus
        value={request}
        onChange={e => setRequest(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            void submit()
          }
          if (e.key === 'Escape') reset()
        }}
        rows={3}
        disabled={busy}
        placeholder="e.g. “a page for Major Modules, explaining each of them in two paragraphs”"
        className="rounded-lg mt-1.5 w-full resize-none border border-rule bg-panel px-2.5 py-2 text-[12.5px] leading-relaxed text-ink transition-colors placeholder:text-ink-dim focus:border-hot focus:outline-none disabled:opacity-60"
      />
      <input
        value={title}
        onChange={e => setTitle(e.target.value)}
        disabled={busy}
        placeholder="Title (optional, one is chosen for you)"
        className="rounded-lg mt-1.5 w-full border border-rule bg-panel px-2.5 py-1.5 text-[12.5px] text-ink transition-colors placeholder:text-ink-dim focus:border-hot focus:outline-none disabled:opacity-60"
      />

      {error && <p className="mt-1.5 text-[12px] text-bad">{error}</p>}

      <div className="mt-2 flex items-center gap-2">
        {busy && (
          <span className="text-[12px] font-medium flex items-center gap-1.5 text-hot-ink">
            <span className="anim-blink block size-[6px] rounded-full bg-hot" />
            finding what it should be written from…
          </span>
        )}
        <Button
          variant="hot"
          className="ml-auto"
          onClick={() => void submit()}
          disabled={!request.trim() || busy}
        >
          {busy ? 'working…' : 'Add the page'}
        </Button>
        <Button variant="ghost" onClick={reset} disabled={busy}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

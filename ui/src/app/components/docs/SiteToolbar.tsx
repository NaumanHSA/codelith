import { useState } from 'react'
import { api, ApiError } from '../../lib/api'
import { relativeTime } from '../../lib/format'
import type { Site } from '../../lib/types'
import { Button, inputClass } from '../ui'

/* ------------------------------------------------------------------ *
 * Versions and exports.
 *
 * Two things a site can do that a document cannot: be frozen under a
 * name, and leave. Both live in one strip because both are about the
 * site as a whole rather than about the page being read.
 * ------------------------------------------------------------------ */

const FORMATS: { value: string; label: string; note: string }[] = [
  { value: 'html', label: 'Static HTML', note: 'This theme, as files. No build step, no network.' },
  { value: 'markdown', label: 'Markdown', note: 'The page tree as stored.' },
  { value: 'mkdocs', label: 'MkDocs', note: 'A buildable MkDocs project with a generated nav.' },
  { value: 'docusaurus', label: 'Docusaurus', note: 'A Docusaurus docs directory and sidebar.' },
  // One file, not a zip: DOCX is what you ask for when the docs need sending,
  // reviewing with tracked changes, or printing.
  { value: 'docx', label: 'Word (.docx)', note: 'The whole site as one document, in reading order.' },
]

export default function SiteToolbar({
  site,
  projectId,
  version,
  onVersion,
  canManage,
  onVersionCreated,
}: {
  site: Site
  projectId: number
  version: string | null
  onVersion: (label: string | null) => void
  canManage: boolean
  onVersionCreated: () => void
}) {
  const [menu, setMenu] = useState<'none' | 'export' | 'snapshot'>('none')
  const [label, setLabel] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const versions = site.versions ?? []

  const download = async (format: string) => {
    setBusy(true)
    setError(null)
    try {
      const { blob, filename } = await api.exportSite(projectId, format, version)
      // Built entirely in the browser from the response — nothing is uploaded.
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
      setMenu('none')
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not build the export.')
    } finally {
      setBusy(false)
    }
  }

  const snapshot = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.createSiteVersion(projectId, { label: label.trim() })
      setLabel('')
      setMenu('none')
      onVersionCreated()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not create the version.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative flex items-center gap-2">
      {versions.length > 0 && (
        <select
          value={version ?? ''}
          onChange={e => onVersion(e.target.value || null)}
          aria-label="Version"
          title="Read a frozen snapshot instead of the live site"
          className="tag border border-rule bg-panel px-1.5 py-[4px] text-ink-mid focus:border-hot focus:outline-none"
        >
          <option value="">live</option>
          {versions.map(v => (
            <option key={v.id} value={v.label}>
              {v.label} · {v.page_count}p
            </option>
          ))}
        </select>
      )}

      {canManage && !version && (
        <button
          onClick={() => setMenu(m => (m === 'snapshot' ? 'none' : 'snapshot'))}
          title="Freeze the site as it stands, under a label"
          className="tag border border-rule bg-panel px-1.5 py-[4px] text-ink-dim transition-colors hover:border-ink hover:text-ink"
        >
          snapshot
        </button>
      )}

      <button
        onClick={() => setMenu(m => (m === 'export' ? 'none' : 'export'))}
        className="tag border border-rule bg-panel px-1.5 py-[4px] text-ink-dim transition-colors hover:border-ink hover:text-ink"
      >
        ↓ export
      </button>

      {menu !== 'none' && (
        <div className="absolute top-full right-0 z-30 mt-1 w-[300px] border border-rule bg-panel shadow-lg">
          {error && (
            <p className="border-b border-bad/35 bg-bad-wash px-2.5 py-2 text-[11px] text-bad">
              {error}
            </p>
          )}

          {menu === 'export' ? (
            <>
              <p className="border-b border-rule px-2.5 py-1.5 text-[10.5px] text-ink-dim">
                {version ? `Exporting version ${version}.` : 'Exporting the live site.'}
              </p>
              {FORMATS.map(f => (
                <button
                  key={f.value}
                  onClick={() => download(f.value)}
                  disabled={busy}
                  className="block w-full border-b border-rule px-2.5 py-2 text-left transition-colors last:border-b-0 hover:bg-sunk disabled:opacity-60"
                >
                  <span className="block text-[11.5px] font-semibold text-ink">{f.label}</span>
                  <span className="block text-[10.5px] leading-snug text-ink-dim">{f.note}</span>
                </button>
              ))}
            </>
          ) : (
            <div className="p-2.5">
              <p className="mb-2 text-[10.5px] leading-snug text-ink-dim">
                Freezes every written page under a label. The live site keeps changing;
                a snapshot does not.
              </p>
              <input
                value={label}
                onChange={e => setLabel(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && label.trim() && snapshot()}
                placeholder="v1.0"
                aria-label="Version label"
                className={inputClass}
              />
              <div className="mt-2 flex justify-end">
                <Button variant="hot" onClick={snapshot} disabled={busy || !label.trim()}>
                  {busy ? 'freezing…' : 'Snapshot'}
                </Button>
              </div>
              {versions.length > 0 && (
                <ul className="mt-3 border-t border-rule pt-2">
                  {versions.slice(0, 4).map(v => (
                    <li key={v.id} className="flex items-baseline gap-2 py-[2px]">
                      <span className="text-[11px] text-ink">{v.label}</span>
                      <span className="tag ml-auto text-ink-dim">
                        {relativeTime(v.snapshot_at ?? v.created_at)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { relativeTime, shortSha } from '../../lib/format'
import { Button } from '../ui'
import ConfirmDelete from '../ConfirmDelete'
import type { Publication } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * Published sites.
 *
 * Export downloads a ZIP, which is useful to the person who pressed the
 * button and to nobody else. This is the other thing: a URL, which is
 * what you send to somebody who does not have the studio.
 *
 * The panel is built around the two questions a person actually has
 * once they have shared a link.
 *
 * *Is what I shared still true?* Answered by the commit the build was
 * written from against the commit the newest reading covers. Two facts,
 * not a count of commits: counting needs the repository, and the clone
 * is discarded once the reading is built, so a number would be made up.
 *
 * *What happens if I press Publish again?* Nothing, when nothing has
 * changed, and the panel says so rather than producing a second
 * identical build. When something has changed the same address is
 * rebuilt, because the link is the thing that was given away and
 * changing it would break every copy of it.
 *
 * The link is described as what it is. Anyone holding it can read the
 * site; that is what sharing with somebody who cannot sign in has to
 * mean, and "rotate" is how you take it back.
 * ------------------------------------------------------------------ */

/** The API's origin, so a copied link is one a reader can actually open. */
function absolute(path: string): string {
  const base = import.meta.env.VITE_API_URL || 'http://localhost:8000'
  return `${base.replace(/\/api\/v1\/?$/, '').replace(/\/$/, '')}${path}`
}

function bytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function Row({
  publication,
  busy,
  onRebuild,
  onRotate,
  onRollback,
  onUnpublish,
  canManage,
}: {
  publication: Publication
  busy: string | null
  onRebuild: (p: Publication) => void
  onRotate: (p: Publication) => void
  onRollback: (p: Publication) => void
  onUnpublish: (p: Publication) => void
  canManage: boolean
}) {
  const [copied, setCopied] = useState(false)
  const live = publication.status === 'live'
  const url = absolute(publication.url)
  const build = publication.current_build

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      // Clipboard access can be refused. The link is on screen and selectable,
      // so there is nothing to recover from and nothing worth interrupting for.
    }
  }

  return (
    <div className="border-b border-rule px-3 py-3 last:border-b-0">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="tag text-ink-dim">
          {publication.target === 'live' ? 'live site' : publication.target}
        </span>
        <span
          className={`tag ${
            live
              ? 'text-ok'
              : publication.status === 'failed'
                ? 'text-bad'
                : 'text-ink-dim'
          }`}
        >
          {publication.status === 'unpublished' ? 'taken down' : publication.status}
        </span>
        {build?.commit_sha && (
          <span className="tag text-ink-dim">built from {shortSha(build.commit_sha)}</span>
        )}
        {/* The question worth answering, and only when it can be. */}
        {publication.is_current === false && (
          <span className="tag text-warn">
            code has moved on{publication.latest_commit ? ` (${shortSha(publication.latest_commit)})` : ''}
          </span>
        )}
        {publication.is_current === true && <span className="tag text-ok">current</span>}
      </div>

      {live ? (
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-hot-ink hover:underline"
          >
            {url}
          </a>
          <button type="button" onClick={copy} className="tag text-ink-dim hover:text-ink">
            {copied ? 'copied' : 'copy link'}
          </button>
        </div>
      ) : (
        <p className="mb-2 font-sans text-[11.5px] text-ink-dim">
          {publication.status === 'unpublished'
            ? `Taken down ${publication.unpublished_at ? relativeTime(publication.unpublished_at) : ''}. The link no longer resolves and the files are gone.`
            : publication.status === 'failed'
              ? build?.error || 'The last build did not finish.'
              : 'Building.'}
        </p>
      )}

      {build && live && (
        <p className="mb-2 font-sans text-[11.5px] text-ink-dim">
          {build.page_count} page{build.page_count === 1 ? '' : 's'} · {bytes(build.bytes_total)} ·{' '}
          {publication.published_at ? relativeTime(publication.published_at) : 'just now'} ·{' '}
          {build.renderer}
        </p>
      )}

      {canManage && publication.status !== 'unpublished' && (
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ghost" onClick={() => onRebuild(publication)} disabled={!!busy}>
            {busy === `rebuild-${publication.id}` ? 'building…' : 'Rebuild'}
          </Button>
          <Button variant="ghost" onClick={() => onRollback(publication)} disabled={!!busy}>
            Roll back
          </Button>
          <Button variant="ghost" onClick={() => onRotate(publication)} disabled={!!busy}>
            New link
          </Button>
          <Button variant="ghost" onClick={() => onUnpublish(publication)} disabled={!!busy}>
            Take down
          </Button>
        </div>
      )}
    </div>
  )
}

export default function Published({
  projectId,
  version,
  canManage,
  onJob,
}: {
  projectId: number
  /** The version being read, if any. Publishing that publishes the snapshot. */
  version: string | null
  canManage: boolean
  /** A build has started; the page can follow it. */
  onJob?: (jobId: number) => void
}) {
  const list = useAsync(sig => api.publications(projectId, sig), [projectId])
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  // The target an unchanged answer came back for. Held here rather than derived from
  // the list, because the list blanks while it reloads and the offer would flicker
  // out from under the pointer at exactly the moment somebody reaches for it.
  const [rebuildable, setRebuildable] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<Publication | null>(null)

  // A build takes seconds, and the row is stale until it finishes. Poll only while
  // something is actually building rather than on a permanent timer.
  const building = (list.data ?? []).some(p => p.status === 'building')
  useEffect(() => {
    if (!building) return
    const t = setInterval(() => list.reload(), 2000)
    return () => clearInterval(t)
  }, [building, list])

  const act = useCallback(
    async (key: string, fn: () => Promise<unknown>, ok?: string) => {
      setBusy(key)
      setError(null)
      setNote(null)
      setRebuildable(null)
      try {
        await fn()
        if (ok) setNote(ok)
        list.reload()
      } catch (e) {
        setError(e instanceof ApiError ? e.message : 'That did not work.')
      } finally {
        setBusy(null)
      }
    },
    [list],
  )

  const publish = (target: string, force: boolean, key: string) =>
    act(key, async () => {
      const res = await api.publishSite(projectId, { target, force })
      if (res.unchanged) {
        // The whole point of the content hash, surfaced in words rather than as a
        // second identical build appearing in the list.
        setNote('Nothing has changed since the last publish, so nothing was rebuilt.')
        setRebuildable(target)
      } else if (res.job_id) {
        onJob?.(res.job_id)
      }
    })

  const target = version ?? 'live'
  const existing = (list.data ?? []).find(p => p.target === target && p.status !== 'unpublished')

  return (
    <section className="plate overflow-hidden">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-rule bg-sunk/60 px-3 py-2">
        <h2 className="text-[11.5px] font-semibold tracking-tight text-ink">Published</h2>
        <span className="tag text-ink-dim">a link, not a download</span>
        {canManage && (
          <Button
            variant="hot"
            className="ml-auto"
            onClick={() => publish(target, false, 'publish')}
            disabled={!!busy}
          >
            {busy === 'publish'
              ? 'publishing…'
              : existing
                ? `Republish ${target === 'live' ? 'live site' : target}`
                : `Publish ${target === 'live' ? 'live site' : target}`}
          </Button>
        )}
      </header>

      {note && (
        <div className="border-b border-rule bg-sunk/40 px-3 py-2">
          <p className="font-sans text-[11.5px] text-ink-mid">{note}</p>
          {/* Offered rather than done. Rebuilding an identical site is a real
              choice somebody may want after changing a renderer, and never one
              they should make by accident. */}
          {rebuildable && (
            <button
              type="button"
              onClick={() => publish(rebuildable, true, 'publish')}
              className="tag mt-1 text-hot-ink hover:underline"
            >
              Rebuild anyway →
            </button>
          )}
        </div>
      )}

      {error && (
        <div className="border-b border-rule px-3 py-2">
          <p className="font-sans text-[11.5px] text-bad">{error}</p>
        </div>
      )}

      {list.loading ? (
        <p className="px-3 py-3 font-sans text-[11.5px] text-ink-dim">loading…</p>
      ) : !list.data?.length ? (
        <div className="px-3 py-4">
          <p className="font-sans text-[12px] leading-relaxed text-ink-mid">
            Nothing is published yet. Publishing builds this site once and serves it at a
            URL you can send to somebody who does not have the studio.
          </p>
          <p className="mt-1.5 font-sans text-[11.5px] text-ink-dim">
            Anyone holding that link can read the site. You can replace the link or take
            it down at any time.
          </p>
        </div>
      ) : (
        <div>
          {list.data.map(p => (
            <Row
              key={p.id}
              publication={p}
              busy={busy}
              canManage={canManage}
              onRebuild={x => publish(x.target, true, `rebuild-${x.id}`)}
              onRotate={x =>
                act(
                  `rotate-${x.id}`,
                  () => api.rotatePublication(x.id),
                  'New link minted. Every link shared before now has stopped working.',
                )
              }
              onRollback={x =>
                act(`rollback-${x.id}`, () => api.rollbackPublication(x.id), 'Rolled back.')
              }
              onUnpublish={x => setConfirm(x)}
            />
          ))}
        </div>
      )}

      <ConfirmDelete
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        title="Take this site down?"
        body={
          <>
            The link stops working immediately and the built files are deleted. Anyone
            reading it now will lose the page. You can publish again at any time, but it
            will have a different address.
          </>
        }
        actionLabel="Take it down"
        onConfirm={async () => {
          const target = confirm
          if (!target) return
          setConfirm(null)
          await act(`unpublish-${target.id}`, () => api.unpublish(target.id), 'Taken down.')
        }}
      />
    </section>
  )
}

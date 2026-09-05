import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import { relativeTime, shortSha } from '../../lib/format'
import { Button } from '../../components/ui'
import ConfirmDelete from '../../components/ConfirmDelete'
import { EmptyState, ErrorState, SkeletonPanel } from '../../components/States'
import type { Publication } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * Everything that is published.
 *
 * The panel on a documentation page answers "what have I published from
 * this codebase". Once a link has been sent to somebody the question
 * stops having a codebase in it: what is out there, is it still true,
 * and who did I give it to. That question needs a page of its own, and
 * it is the page you go to when you want to take something down.
 *
 * Sorted with the live ones first, because a taken-down publication is
 * a record and a live one is a thing people are reading right now.
 * ------------------------------------------------------------------ */

function absolute(path: string): string {
  const base = import.meta.env.VITE_API_URL || 'http://localhost:8000'
  return `${base.replace(/\/api\/v1\/?$/, '').replace(/\/$/, '')}${path}`
}

function bytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function Card({
  publication,
  busy,
  onAct,
  onTakeDown,
}: {
  publication: Publication
  busy: string | null
  onAct: (kind: 'rebuild' | 'rotate' | 'rollback', p: Publication) => void
  onTakeDown: (p: Publication) => void
}) {
  const [copied, setCopied] = useState(false)
  const live = publication.status === 'live'
  const down = publication.status === 'unpublished'
  const url = absolute(publication.url)
  const build = publication.current_build

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      // Refused clipboard access. The link is on screen and selectable.
    }
  }

  return (
    <article className={`plate overflow-hidden ${down ? 'opacity-70' : ''}`}>
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-rule bg-sunk/60 px-3 py-2">
        <Link
          to={`/app/projects/${publication.project_id}/docs`}
          className="text-[11.5px] font-semibold tracking-tight text-ink hover:text-hot-ink"
        >
          {publication.project_name || `Project ${publication.project_id}`}
        </Link>
        <span className="tag text-ink-dim">
          {publication.target === 'live' ? 'live site' : publication.target}
        </span>
        <span
          className={`tag ml-auto ${
            live ? 'text-ok' : publication.status === 'failed' ? 'text-bad' : 'text-ink-dim'
          }`}
        >
          {down ? 'taken down' : publication.status}
        </span>
      </header>

      <div className="p-3">
        {live ? (
          <div className="mb-2.5 flex flex-wrap items-center gap-2">
            <a
              href={url}
              target="_blank"
              rel="noreferrer"
              className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-hot-ink hover:underline"
            >
              {url}
            </a>
            <button type="button" onClick={copy} className="tag text-ink-dim hover:text-ink">
              {copied ? 'copied' : 'copy'}
            </button>
          </div>
        ) : (
          <p className="mb-2.5 font-sans text-[11.5px] text-ink-dim">
            {down
              ? `Taken down ${publication.unpublished_at ? relativeTime(publication.unpublished_at) : ''}. The link no longer resolves.`
              : publication.status === 'failed'
                ? build?.error || 'The last build did not finish.'
                : 'Building.'}
          </p>
        )}

        <div className="mb-2.5 flex flex-wrap items-center gap-x-2.5 gap-y-1">
          {build && (
            <span className="tag text-ink-dim">
              {build.page_count} page{build.page_count === 1 ? '' : 's'} ·{' '}
              {bytes(build.bytes_total)}
            </span>
          )}
          {build?.commit_sha && (
            <span className="tag text-ink-dim">from {shortSha(build.commit_sha)}</span>
          )}
          {/* The one question worth asking about a site somebody else is reading. */}
          {publication.is_current === true && <span className="tag text-ok">current</span>}
          {publication.is_current === false && (
            <span className="tag text-warn">
              code has moved on
              {publication.latest_commit ? ` (${shortSha(publication.latest_commit)})` : ''}
            </span>
          )}
          {publication.published_at && live && (
            <span className="tag text-ink-dim">{relativeTime(publication.published_at)}</span>
          )}
        </div>

        {!down && (
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="ghost" onClick={() => onAct('rebuild', publication)} disabled={!!busy}>
              {busy === `rebuild-${publication.id}` ? 'building…' : 'Rebuild'}
            </Button>
            <Button variant="ghost" onClick={() => onAct('rollback', publication)} disabled={!!busy}>
              Roll back
            </Button>
            <Button variant="ghost" onClick={() => onAct('rotate', publication)} disabled={!!busy}>
              New link
            </Button>
            <Button variant="ghost" onClick={() => onTakeDown(publication)} disabled={!!busy}>
              Take down
            </Button>
          </div>
        )}
      </div>
    </article>
  )
}

export default function PublishedPage() {
  const list = useAsync(sig => api.allPublications(sig), [])
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<Publication | null>(null)

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

  const onAct = (kind: 'rebuild' | 'rotate' | 'rollback', p: Publication) => {
    if (kind === 'rebuild') {
      // Forced. The button is on a publication that already exists, so the reader
      // has asked for this one specifically rather than for "publish something".
      return act(`rebuild-${p.id}`, () =>
        api.publishSite(p.project_id, { target: p.target, force: true }),
      )
    }
    if (kind === 'rotate') {
      return act(
        `rotate-${p.id}`,
        () => api.rotatePublication(p.id),
        'New link minted. Every link shared before now has stopped working.',
      )
    }
    return act(`rollback-${p.id}`, () => api.rollbackPublication(p.id), 'Rolled back.')
  }

  // Live first: those are being read right now, the rest are a record.
  const rank = (p: Publication) =>
    p.status === 'live' ? 0 : p.status === 'building' ? 1 : p.status === 'failed' ? 2 : 3
  const rows = [...(list.data ?? [])].sort((a, b) => rank(a) - rank(b) || b.id - a.id)
  const liveCount = rows.filter(p => p.status === 'live').length

  return (
    <div className="mx-auto max-w-[1200px] p-5">
      <header className="mb-5 flex flex-wrap items-end gap-4 border-b border-rule pb-3">
        <span className="text-[34px] leading-[0.8] font-bold tracking-tighter text-rule select-none">
          05
        </span>
        <div className="min-w-0 flex-1">
          <h1 className="text-[19px] leading-tight font-bold tracking-tight text-ink">Published</h1>
          <p className="mt-0.5 text-[11.5px] text-ink-dim">
            Documentation served at a URL other people can open.{' '}
            {liveCount
              ? `${liveCount} live right now.`
              : 'Nothing is live.'}
          </p>
        </div>
      </header>

      {/* Said once, at the top, rather than beside every link. Anyone holding one of
          these URLs can read the site, and that is the honest description of what
          sharing means for somebody with no account on this machine. */}
      <p className="mb-4 border border-rule bg-panel px-4 py-3 font-sans text-[12px] leading-relaxed text-ink-mid">
        Each address carries its own secret, so it cannot be guessed, but{' '}
        <strong className="font-semibold text-ink">anyone holding the link can read it</strong>.
        Use <em>New link</em> to invalidate every copy of one that has been shared, or{' '}
        <em>Take down</em> to stop serving and delete the files.
      </p>

      {note && (
        <p className="mb-4 border border-rule bg-sunk/40 px-4 py-2.5 font-sans text-[11.5px] text-ink-mid">
          {note}
        </p>
      )}
      {error && (
        <p className="mb-4 border border-rule px-4 py-2.5 font-sans text-[11.5px] text-bad">
          {error}
        </p>
      )}

      {list.loading ? (
        <SkeletonPanel rows={3} />
      ) : list.error ? (
        <ErrorState message={list.error} onRetry={list.reload} />
      ) : !rows.length ? (
        <EmptyState
          title="Nothing published yet"
          body="Open a codebase, go to its documentation, and press Publish. You will get a URL you can send to somebody who does not have the studio."
        />
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {rows.map(p => (
            <Card
              key={p.id}
              publication={p}
              busy={busy}
              onAct={onAct}
              onTakeDown={setConfirm}
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
    </div>
  )
}

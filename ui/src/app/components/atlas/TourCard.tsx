import { useState } from 'react'
import { api } from '../../lib/api'
import { Icon, type IconName } from '../../lib/icons'
import type { Tour } from '../../lib/types'
import { Markdown } from '../Markdown'

/* ------------------------------------------------------------------ *
 * The tour, one stop at a time, at the top of the knowledge graph's side
 * pane (`apps/tour`). The page applies each stop to the map — opens its
 * parts, lights its files, plays its flow — and this card says why.
 * ------------------------------------------------------------------ */

const STOP_ICONS: Record<string, IconName> = {
  start: 'compass',
  layout: 'boxes',
  entry: 'route',
  flow: 'play',
  core: 'cpu',
  data: 'database',
  helpers: 'wrench',
  care: 'shield-alert',
  next: 'flag',
}

export default function TourCard({
  projectId,
  tour,
  at,
  onGo,
  onClose,
  onFile,
}: {
  projectId: number
  tour: Tour
  at: number
  onGo: (stop: number) => void
  onClose: () => void
  onFile: (path: string) => void
}) {
  const stop = tour.stops[at]
  const last = at === tour.stops.length - 1
  const [copied, setCopied] = useState<'idle' | 'busy' | 'done' | 'failed'>('idle')

  const copy = async () => {
    setCopied('busy')
    try {
      const { markdown } = await api.tourMarkdown(projectId)
      await navigator.clipboard.writeText(markdown)
      setCopied('done')
    } catch {
      setCopied('failed')
    }
    setTimeout(() => setCopied('idle'), 1800)
  }

  if (!stop) return null
  return (
    <section className="flex flex-col gap-3 border-b border-rule bg-sunk/40 px-4 py-3.5" aria-label="Tour">
      <header className="flex items-center gap-2">
        <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-hot/15 text-hot-ink">
          <Icon name={STOP_ICONS[stop.id] ?? 'map'} size={15} />
        </span>
        <span className="text-[12px] font-medium text-ink-mid">
          Tour <span className="text-ink-dim">·</span> stop {at + 1} of {tour.stops.length}
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Leave the tour"
          title="Leave the tour"
          className="ml-auto grid size-7 place-items-center rounded-lg text-ink-dim transition-colors hover:bg-hover hover:text-ink"
        >
          <Icon name="x" size={15} />
        </button>
      </header>

      {/* Each stop, as a bar to jump to. */}
      <div className="flex gap-1" role="group" aria-label="Stops">
        {tour.stops.map((s, k) => (
          <button
            key={s.id}
            type="button"
            onClick={() => onGo(k)}
            title={`${k + 1}. ${s.title}`}
            aria-label={`Stop ${k + 1}: ${s.title}`}
            aria-current={k === at ? 'step' : undefined}
            className="group flex h-4 flex-1 items-center"
          >
            <span
              className={`block h-1 w-full rounded-full transition-colors ${
                k === at ? 'bg-hot' : k < at ? 'bg-hot/45 group-hover:bg-hot/70' : 'bg-rule group-hover:bg-line-2'
              }`}
            />
          </button>
        ))}
      </div>

      <h2 className="font-head text-[17px] leading-snug font-semibold text-balance text-ink">{stop.title}</h2>
      <div className="doc chat-answer tour-body text-[13px] leading-relaxed text-ink-mid">
        <Markdown>{stop.body}</Markdown>
      </div>

      {stop.files.length > 0 && (
        <ul className="flex flex-col overflow-hidden rounded-lg border border-rule bg-panel">
          {stop.files.map((f, k) => (
            <li key={f.path} className={k ? 'border-t border-rule' : ''}>
              <button
                type="button"
                onClick={() => onFile(f.path)}
                title={`Show ${f.path} on the map`}
                className="flex w-full items-baseline gap-2 px-3 py-1.5 text-left transition-colors hover:bg-hover"
              >
                <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-ink" dir="rtl">
                  {/* Kept readable from the right: the file name matters more than the folders. */}
                  <bdi>{f.path}</bdi>
                </span>
                {f.note && <span className="shrink-0 text-[11.5px] text-ink-dim">{f.note}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}

      <footer className="flex items-center gap-2 pt-0.5">
        <button
          type="button"
          onClick={() => onGo(at - 1)}
          disabled={at === 0}
          className="inline-flex items-center gap-1.5 rounded-lg border border-rule px-3 py-[5px] text-[12.5px] font-medium text-ink-mid transition-colors hover:bg-hover hover:text-ink disabled:pointer-events-none disabled:opacity-40"
        >
          <Icon name="arrow-left" size={14} />
          Back
        </button>
        {last ? (
          <>
            <button
              type="button"
              onClick={() => void copy()}
              disabled={copied === 'busy'}
              className="inline-flex items-center gap-1.5 rounded-lg border border-rule px-3 py-[5px] text-[12.5px] font-medium text-ink-mid transition-colors hover:bg-hover hover:text-ink"
              title="The whole tour as a document, for a README or an onboarding page"
            >
              <Icon name={copied === 'done' ? 'check' : copied === 'busy' ? 'loader' : 'copy'} size={14} className={copied === 'busy' ? 'anim-spin' : ''} />
              {copied === 'done' ? 'Copied' : copied === 'failed' ? 'Could not copy' : 'Copy as Markdown'}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-hot px-3.5 py-[5px] text-[12.5px] font-semibold text-on-hot transition-opacity hover:opacity-90"
            >
              Finish
              <Icon name="check" size={14} />
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => onGo(at + 1)}
            className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-hot px-3.5 py-[5px] text-[12.5px] font-semibold text-on-hot transition-opacity hover:opacity-90"
          >
            Next
            <Icon name="arrow-right" size={14} />
          </button>
        )}
      </footer>
    </section>
  )
}

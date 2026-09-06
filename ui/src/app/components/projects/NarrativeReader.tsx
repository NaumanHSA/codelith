import { useEffect, useState } from 'react'
import { Markdown } from '../Markdown'
import type { Narrative, Narratives } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * The prose analysis wrote, as something you can actually read.
 *
 * Every run writes a dozen of these, the longest close to three
 * thousand words, and the studio showed their topic names as chips and
 * dropped the text. Composition read them; a person could not. So the
 * chips became a rail and the words came with them.
 *
 * The topics arrive in reading order from the API rather than being
 * sorted here, because the order is a fact about the topics and not
 * about this component: "overview" before "architecture" is true on the
 * published site too.
 * ------------------------------------------------------------------ */

/** How much of a narrative shows before the reader has to ask for the rest.
 *  Roughly a screen, so a short topic never collapses and a long one does. */
const FOLD_WORDS = 160

export default function NarrativeReader({ data }: { data: Narratives }) {
  const [topic, setTopic] = useState<string>(data.narratives[0]?.topic ?? '')
  const [open, setOpen] = useState(false)

  // A different project, or a re-analysis that dropped a topic: fall back to the
  // first rather than showing an empty body for a topic that is no longer there.
  useEffect(() => {
    if (!data.narratives.some(n => n.topic === topic)) {
      setTopic(data.narratives[0]?.topic ?? '')
    }
  }, [data, topic])

  const current: Narrative | undefined =
    data.narratives.find(n => n.topic === topic) ?? data.narratives[0]

  if (!current) return null

  const long = current.words > FOLD_WORDS

  return (
    <div className="grid grid-cols-1 md:grid-cols-[186px_1fr]">
      {/* The rail. Word counts are on it because they are the honest signal of
          which topics the analysis had something to say about: a 55-word
          "testing" is telling you this project barely has tests. */}
      <nav className="border-b border-rule md:border-b-0 md:border-r">
        <ul className="flex gap-px overflow-x-auto bg-rule md:block md:overflow-visible">
          {data.narratives.map(n => {
            const on = n.topic === current.topic
            return (
              <li key={n.topic} className="shrink-0 md:shrink">
                <button
                  type="button"
                  onClick={() => {
                    setTopic(n.topic)
                    setOpen(false)
                  }}
                  className={`flex w-full items-baseline gap-2 whitespace-nowrap px-2.5 py-[7px] text-left text-[11.5px] transition-colors ${
                    on
                      ? 'bg-hot-wash font-semibold text-hot-ink'
                      : 'bg-panel text-ink-mid hover:bg-sunk hover:text-ink'
                  }`}
                >
                  <span className="min-w-0 flex-1 truncate">{n.title}</span>
                  <span className={`tag ${on ? 'text-hot-ink' : 'text-ink-dim'}`}>{n.words}w</span>
                </button>
              </li>
            )
          })}
        </ul>
      </nav>

      <article className="min-w-0">
        <header className="border-b border-rule px-3 py-2.5">
          <h3 className="text-[13px] font-semibold tracking-tight text-ink">{current.title}</h3>
          {current.brief && (
            <p className="mt-0.5 text-[11.5px] leading-snug text-ink-dim">{current.brief}</p>
          )}
        </header>

        <div
          className={`relative px-3 py-2.5 ${long && !open ? 'max-h-[330px] overflow-hidden' : ''}`}
        >
          <div className="doc min-w-0">
            <Markdown>{current.content_md}</Markdown>
          </div>
          {long && !open && (
            // Faded rather than hard-cut, so it reads as "there is more" instead
            // of "this stopped mid-sentence".
            <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-panel to-transparent" />
          )}
        </div>

        <footer className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-rule bg-sunk/40 px-3 py-1.5">
          {long && (
            <button
              type="button"
              onClick={() => setOpen(v => !v)}
              className="tag text-hot-ink hover:underline"
            >
              {open ? 'collapse' : `read all ${current.words} words`}
            </button>
          )}
          <Provenance narrative={current} sha={data.commit_sha} />
        </footer>
      </article>
    </div>
  )
}

/**
 * Where this paragraph came from.
 *
 * A knowledge base written before the writer recorded its sources has none, and
 * says so. The alternative was to infer the modules from the topic after the
 * fact, which would print a citation nobody could check.
 */
function Provenance({ narrative, sha }: { narrative: Narrative; sha: string | null }) {
  const { modules, facts } = narrative.provenance
  const short = sha ? sha.slice(0, 7) : null

  if (!modules.length && !facts.length) {
    return (
      <span className="tag text-ink-dim">
        {short ? `read at ${short} · ` : ''}sources not recorded on this run
      </span>
    )
  }

  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
      {short && <span className="tag text-ink-dim">read at {short}</span>}
      {modules.length > 0 && (
        <span className="tag text-ink-dim" title={modules.join(', ')}>
          from {modules.length} module{modules.length === 1 ? '' : 's'}
        </span>
      )}
      {facts.map(f => (
        <span key={f} className="tag border border-rule px-1 text-ink-dim">
          {f}
        </span>
      ))}
    </span>
  )
}

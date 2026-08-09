import { useState } from 'react'
import { Markdown } from '../Markdown'
import type { ChatMessage } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * One turn.
 *
 * Both roles render markdown. The question is the obvious one to skip —
 * it is "just what the user typed" — except that what they typed has
 * newlines, lists and pasted code in it, and rendering that as a single
 * run-on line loses the shape of their own question back at them.
 *
 * The evidence panel is collapsed by default. It is the reason to trust
 * the answer, and it is also forty lines of provenance nobody wants
 * between them and the next paragraph.
 * ------------------------------------------------------------------ */

function Cursor() {
  return <span className="ml-0.5 inline-block h-[1em] w-[2px] animate-pulse bg-hot align-text-bottom" />
}

export function UserMessage({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="doc chat-bubble max-w-[85%] rounded-xl rounded-br-sm border border-rule bg-sunk px-4 py-2.5">
        <Markdown>{content}</Markdown>
      </div>
    </div>
  )
}

export function AssistantMessage({
  message,
  streaming = false,
}: {
  message: Pick<ChatMessage, 'content' | 'citations' | 'stripped' | 'evidence'>
  streaming?: boolean
}) {
  const [showSources, setShowSources] = useState(false)
  const sources = message.evidence?.sources ?? []
  const counts = message.evidence?.counts ?? {}

  return (
    <div className="min-w-0">
      <div className="doc chat-answer min-w-0">
        <Markdown>{message.content}</Markdown>
        {streaming && <Cursor />}
      </div>

      {!streaming && (
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px]">
          {!!sources.length && (
            <button
              type="button"
              onClick={() => setShowSources(s => !s)}
              className="text-ink-dim hover:text-hot-ink"
            >
              {showSources ? '− hide' : '+'} {sources.length} source
              {sources.length === 1 ? '' : 's'}
              {!!Object.keys(counts).length && (
                <span className="ml-1.5 text-ink-dim">
                  ({Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(' · ')})
                </span>
              )}
            </button>
          )}

          {!!message.stripped?.length && (
            <span
              className="text-warn"
              title="These were cited by the model but do not appear in anything that was retrieved, so they were not verified."
            >
              {message.stripped.length} unverified reference
              {message.stripped.length === 1 ? '' : 's'}
            </span>
          )}
        </div>
      )}

      {showSources && (
        <ul className="mt-2 space-y-1 border-l-2 border-rule pl-3">
          {sources.map((s, i) => (
            <li key={`${s.title}-${i}`} className="text-[11px]">
              <span className="tag mr-1.5 text-ink-dim">{s.kind}</span>
              <code className="text-ink-mid">{s.title}</code>
              <span className="ml-1.5 text-ink-dim">— {s.why}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

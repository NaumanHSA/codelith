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
 * Sources open in a panel beside the conversation, not under the answer.
 * They are the reason to trust it — and forty lines of provenance
 * between you and the next paragraph, which is why expanding them
 * inline pushed the thing you were checking off the screen.
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
  onOpenSources,
  sourcesOpen = false,
  onCitation,
  followUps = [],
  onAsk,
}: {
  message: Pick<ChatMessage, 'content' | 'citations' | 'stripped' | 'evidence'>
  streaming?: boolean
  /** Opens the side panel for *this* answer. Sources used to expand inline, which
   *  pushed the answer off screen to show what it came from — and the reason to
   *  open them is almost always to check a claim you can still see. */
  onOpenSources?: () => void
  sourcesOpen?: boolean
  /** A citation in the answer was clicked — open the panel at that source. */
  onCitation?: (ref: string) => void
  /** Questions to offer under this answer. Empty for every answer but the newest —
   *  three suggestions after each message in a long thread is a page of them. */
  followUps?: string[]
  onAsk?: (question: string) => void
}) {
  const sources = message.evidence?.sources ?? []
  const counts = message.evidence?.counts ?? {}

  return (
    <div className="min-w-0">
      <div className="doc chat-answer min-w-0">
        <Markdown onCitation={onCitation}>{message.content}</Markdown>
        {streaming && <Cursor />}
      </div>

      {!streaming && (
        <div className="mt-5 flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-rule pt-2.5 text-[11px]">
          {!!sources.length && (
            <button
              type="button"
              onClick={onOpenSources}
              className={`font-semibold underline-offset-4 transition-colors hover:underline ${
                sourcesOpen ? 'text-hot-ink underline' : 'text-ink-mid hover:text-hot-ink'
              }`}
            >
              <span className="mr-1 text-hot">◆</span>
              {sources.length} source{sources.length === 1 ? '' : 's'}
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

      {!streaming && !!followUps.length && onAsk && (
        <div className="mt-3">
          <span className="tag text-ink-dim">next</span>
          <ul className="mt-1">
            {followUps.map(q => (
              <li key={q}>
                <button
                  type="button"
                  onClick={() => onAsk(q)}
                  className="group flex w-full items-baseline gap-2 py-[3px] text-left text-[11.5px] text-ink-mid transition-colors hover:text-hot-ink"
                >
                  <span className="text-hot opacity-50 group-hover:opacity-100">→</span>
                  <span className="underline-offset-4 group-hover:underline">{q}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

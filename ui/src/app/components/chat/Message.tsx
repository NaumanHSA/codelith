import { Link } from 'react-router-dom'
import { Markdown } from '../Markdown'
import { NEW_TAB } from '../layout/tabState'
import { AREA_LABEL } from '../qa/look'
import { Icon } from '../../lib/icons'
import type { ChatMessage } from '../../lib/types'
import AnswerTrace from './AnswerTrace'
import type { InsightTab } from './InsightPane'
import type { TraceStep } from './trace'

/* ------------------------------------------------------------------ *
 * One turn.
 *
 * Both roles render markdown. The question is the obvious one to skip —
 * it is "just what the user typed" — except that what they typed has
 * newlines, lists and pasted code in it, and rendering that as a single
 * run-on line loses the shape of their own question back at them.
 *
 * Above each answer, the four steps that produced it. Under it, what the
 * reader can check: the citations, the sources, the reasoning. Each opens
 * the pane beside the conversation, not inline, because the reason to open
 * them is to check a claim you can still see.
 * ------------------------------------------------------------------ */

function Cursor() {
  return <span className="anim-blink ml-0.5 inline-block h-[1em] w-[2px] bg-hot align-text-bottom" />
}

export function UserMessage({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="doc chat-bubble max-w-[85%] rounded-2xl rounded-br-md border border-rule bg-sunk px-4 py-2.5">
        <Markdown>{content}</Markdown>
      </div>
    </div>
  )
}

function FooterButton({
  icon,
  children,
  active,
  onClick,
  tone = 'plain',
  title,
}: {
  icon: React.ComponentProps<typeof Icon>['name']
  children: React.ReactNode
  active?: boolean
  onClick?: () => void
  tone?: 'plain' | 'warn'
  title?: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={`inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[12.5px] font-medium transition-colors ${
        tone === 'warn'
          ? 'text-warn hover:bg-warn-wash'
          : active
            ? 'bg-sunk text-ink shadow-[inset_0_0_0_1px_var(--line-2)]'
            : 'text-ink-mid hover:bg-hover hover:text-ink'
      }`}
    >
      <Icon name={icon} size={14} />
      {children}
    </button>
  )
}

/** A QA run the question needed: the areas it asked about that QA never checked, or
 *  checked only at an older reading. Opens the QA page's run dialog with them ticked. */
function QASuggestion({ projectId, suggestion }: { projectId: number; suggestion: { areas: string[]; reason: 'unchecked' | 'behind' } }) {
  const names = suggestion.areas.map(a => AREA_LABEL[a] ?? a)
  const all = suggestion.areas.length >= 8
  const listed = all ? 'any area' : names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names[0]
  return (
    <div className="mt-4 flex flex-wrap items-center gap-3 rounded-lg border border-line-2 bg-sunk px-3.5 py-2.5">
      <Icon name="bug" size={16} className="shrink-0 text-hot" />
      <p className="min-w-0 flex-1 text-[12.5px] leading-snug text-ink-mid">
        {suggestion.reason === 'unchecked'
          ? `QA has not checked ${all ? 'this codebase' : listed.toLowerCase()} yet, so this answer cannot say what a check would find.`
          : `QA checked ${listed.toLowerCase()} at an older reading; the code has been read again since.`}
      </p>
      <Link
        to={`/app/projects/${projectId}/qa?check=${suggestion.areas.join(',')}`}
        state={NEW_TAB}
        className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-hot-edge bg-hot/10 px-3 py-1.5 text-[12.5px] font-medium text-ink transition-colors hover:bg-hot/20"
      >
        Run QA <Icon name="arrow-right" size={13} /> {all ? 'every area' : names.length > 2 ? `${names.length} areas` : names.join(', ')}
      </Link>
    </div>
  )
}

export function AssistantMessage({
  message,
  steps,
  streaming = false,
  focused = false,
  openTab = null,
  onOpen,
  onCitation,
  followUps = [],
  onAsk,
  projectId,
}: {
  message: Pick<ChatMessage, 'content' | 'citations' | 'stripped' | 'evidence'>
  steps: TraceStep[]
  streaming?: boolean
  /** This answer is the one the pane is showing. */
  focused?: boolean
  openTab?: InsightTab | null
  onOpen?: (tab: InsightTab) => void
  /** A citation in the answer was clicked — open the pane at that reference. */
  onCitation?: (ref: string) => void
  /** Questions to offer under this answer. Empty for every answer but the newest. */
  followUps?: string[]
  onAsk?: (question: string) => void
  /** For the QA run an answer may offer. */
  projectId?: number
}) {
  const sources = message.evidence?.sources ?? []
  const citations = message.citations?.length ?? 0

  return (
    <div className="min-w-0">
      <div className="mb-3">
        <AnswerTrace steps={steps} onOpen={onOpen ? () => onOpen('thinking') : undefined} />
      </div>

      <div className="doc chat-answer min-w-0">
        <Markdown onCitation={onCitation}>{message.content}</Markdown>
        {streaming && <Cursor />}
      </div>

      {!streaming && onOpen && (
        <div className="mt-4 flex flex-wrap items-center gap-1 border-t border-rule pt-2">
          <FooterButton
            icon="quote"
            active={focused && openTab === 'citations'}
            onClick={() => onOpen('citations')}
          >
            {citations} citation{citations === 1 ? '' : 's'}
          </FooterButton>
          <FooterButton
            icon="database"
            active={focused && openTab === 'sources'}
            onClick={() => onOpen('sources')}
          >
            {sources.length} source{sources.length === 1 ? '' : 's'}
          </FooterButton>
          <FooterButton
            icon="brain"
            active={focused && openTab === 'thinking'}
            onClick={() => onOpen('thinking')}
          >
            How it was answered
          </FooterButton>
          {!!message.stripped?.length && (
            <FooterButton
              icon="triangle-alert"
              tone="warn"
              onClick={() => onOpen('citations')}
              title="Cited by the model but absent from everything retrieved, so they were removed."
            >
              {message.stripped.length} unverified
            </FooterButton>
          )}
        </div>
      )}

      {!streaming && projectId && message.evidence?.suggest_qa && message.evidence.suggest_qa.areas.length > 0 && (
        <QASuggestion projectId={projectId} suggestion={message.evidence.suggest_qa} />
      )}

      {!streaming && !!followUps.length && onAsk && (
        <div className="mt-4">
          <span className="tag text-ink-dim">Ask next</span>
          <ul className="mt-1.5 flex flex-col">
            {followUps.map(q => (
              <li key={q}>
                <button
                  type="button"
                  onClick={() => onAsk(q)}
                  className="group flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] text-ink-mid transition-colors hover:bg-hover hover:text-ink"
                >
                  <Icon name="arrow-right" size={14} className="text-hot opacity-60 group-hover:opacity-100" />
                  {q}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

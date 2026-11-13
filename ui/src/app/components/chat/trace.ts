import type { IconName } from '../../lib/icons'
import type { ChatMessage, ChatScope, ChatSource, ChatToolStep } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * How an answer was reached, as four steps: the gate decides whether the
 * question is about this codebase, the router decides what to look for,
 * retrieval fetches it (and the model may search again on its own), and
 * the model answers.
 *
 * Built from the same fields whether the answer is streaming or was
 * stored a week ago, so the trace above a reply and the Thinking tab say
 * the same thing either way.
 * ------------------------------------------------------------------ */

export type StepState = 'pending' | 'active' | 'done' | 'skipped'

export interface TraceStep {
  id: 'gate' | 'route' | 'retrieve' | 'answer'
  label: string
  icon: IconName
  state: StepState
  detail: string
}

export interface TraceInput {
  scope?: ChatScope
  intents?: string[]
  routedBy?: string
  counts?: Record<string, number>
  sources?: ChatSource[]
  tools?: ChatToolStep[]
  /** Evidence has arrived (or, for a stored answer, was recorded). */
  retrieved: boolean
  /** Tokens are arriving. */
  answering: boolean
  done: boolean
  citations?: number
}

export const VERDICT: Record<ChatScope['verdict'], string> = {
  code: 'About this codebase',
  chat: 'Conversation, nothing to search',
  off_topic: 'Not about this codebase',
}

export const DECIDED_BY: Record<string, string> = {
  vocabulary: 'it names things this codebase contains',
  shape: 'its wording is a question about code',
  llm: 'the model read it against what this codebase is',
  fallback: 'the check could not decide, so the code was searched anyway',
  disabled: 'the gate is switched off',
}

const total = (counts?: Record<string, number>) =>
  Object.values(counts ?? {}).reduce((a, b) => a + b, 0)

export function traceSteps(t: TraceInput): TraceStep[] {
  // Answers stored before the gate existed carry evidence and no verdict: they
  // were searched, so that is what they say.
  const verdict = t.scope?.verdict ?? (t.retrieved ? 'code' : undefined)
  const searched = verdict === 'code'
  const gateKnown = verdict !== undefined
  const found = total(t.counts)
  const tools = t.tools?.length ?? 0

  return [
    {
      id: 'gate',
      label: 'Gate',
      icon: 'shield-check',
      state: gateKnown ? 'done' : 'active',
      detail: verdict ? VERDICT[verdict] : 'Reading the question',
    },
    {
      id: 'route',
      label: 'Route',
      icon: 'route',
      state: !gateKnown ? 'pending' : !searched ? 'skipped' : t.retrieved ? 'done' : 'active',
      detail: !searched && gateKnown
        ? 'Not searched'
        : t.intents?.length
          ? t.intents.map(i => i.replace(/_/g, ' ')).join(', ')
          : t.retrieved
            ? 'General'
            : 'Choosing where to look',
    },
    {
      id: 'retrieve',
      label: 'Retrieve',
      icon: 'database',
      state: !gateKnown
        ? 'pending'
        : !searched
          ? 'skipped'
          : !t.retrieved
            ? 'pending'
            : !t.done && !t.answering && tools
              ? 'active'
              : 'done',
      detail: !searched && gateKnown
        ? 'Not searched'
        : t.retrieved
          ? `${found} piece${found === 1 ? '' : 's'}${tools ? `, then ${tools} more search${tools === 1 ? '' : 'es'}` : ''}`
          : 'Waiting',
    },
    {
      id: 'answer',
      label: 'Answer',
      icon: 'sparkles',
      state: t.done ? 'done' : t.answering ? 'active' : 'pending',
      detail: t.done
        ? t.citations
          ? `${t.citations} checked citation${t.citations === 1 ? '' : 's'}`
          : searched
            ? 'No citations'
            : 'Answered directly'
        : t.answering
          ? 'Writing'
          : 'Waiting',
    },
  ]
}

/** The trace of a stored answer. */
export function messageTrace(m: Pick<ChatMessage, 'evidence' | 'citations'>): TraceStep[] {
  const e = m.evidence ?? {}
  return traceSteps({
    scope: e.scope,
    intents: e.intents,
    routedBy: e.routed_by,
    counts: e.counts,
    sources: e.sources,
    tools: e.tools,
    retrieved: !!e.counts || !!e.sources?.length,
    answering: false,
    done: true,
    citations: m.citations?.length ?? 0,
  })
}

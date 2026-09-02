import { api } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import type { LLMSettings } from '../../lib/types'
import { PageHead, Panel } from '../../components/ui'
import { ErrorState, SkeletonPanel } from '../../components/States'

/* ------------------------------------------------------------------ *
 * Settings — what each tier is actually pointed at.
 *
 * This was a form. It saved to `PUT /settings/llm`, which wrote a row
 * that nothing ever read back: model configuration comes from `.env`
 * and is resolved at call time. So the page reported a configuration
 * the application was not using — the worst possible answer from a
 * screen whose only job is saying what is configured.
 *
 * It reports the resolved specs now. Two providers, and they carry
 * different fields on purpose: `openai` is a key and a model name;
 * `local` is any OpenAI-compatible server, where the URL and the
 * window matter because neither can be assumed.
 * ------------------------------------------------------------------ */

function Row({ k, v, muted }: { k: string; v: string | number; muted?: boolean }) {
  return (
    <div className="flex items-baseline gap-3 border-b border-rule px-4 py-2 last:border-b-0">
      <span className="tag w-[112px] shrink-0 text-ink-dim">{k}</span>
      <span
        className={`min-w-0 flex-1 break-all text-[12px] ${
          muted ? 'text-ink-dim' : 'text-ink'
        }`}
      >
        {v}
      </span>
    </div>
  )
}

function Tier({
  index,
  title,
  blurb,
  provider,
  model,
  baseUrl,
  contextWindow,
  keySet,
}: {
  index: string
  title: string
  blurb: string
  provider: string
  model: string
  baseUrl: string
  contextWindow?: number
  keySet: boolean
}) {
  const hosted = provider === 'openai'
  return (
    <Panel
      title={title}
      index={index}
      action={
        <span
          className={`tag border px-1.5 py-0.5 ${
            hosted
              ? 'border-hot-edge bg-hot-wash text-hot-ink'
              : 'border-rule bg-sunk text-ink-mid'
          }`}
        >
          {hosted ? 'openai' : 'openai-compatible'}
        </span>
      }
    >
      <p className="px-4 pt-3 pb-1 font-sans text-[11.5px] leading-relaxed text-ink-mid">
        {blurb}
      </p>
      <div className="border-t border-rule">
        <Row k="model" v={model || '—'} />
        {hosted ? (
          <>
            <Row k="api key" v={keySet ? 'configured' : 'NOT SET'} muted={keySet} />
            {/* Shown so the page is complete, dimmed because neither is a
                setting for a hosted tier — the endpoint is fixed and the
                window is not a number anybody should have to look up. */}
            <Row k="endpoint" v={baseUrl} muted />
            {contextWindow ? <Row k="context" v={contextWindow.toLocaleString()} muted /> : null}
          </>
        ) : (
          <>
            <Row k="endpoint" v={baseUrl} />
            {contextWindow ? <Row k="context" v={contextWindow.toLocaleString()} /> : null}
          </>
        )}
      </div>
    </Panel>
  )
}

function Resolved({ s }: { s: LLMSettings }) {
  return (
    <div className="flex flex-col gap-4">
      {!!s.problems?.length && (
        <div className="border border-bad/40 bg-bad-wash px-4 py-3">
          <span className="tag text-bad">this configuration will not work</span>
          <ul className="mt-2 flex flex-col gap-1.5">
            {s.problems.map(p => (
              <li key={p} className="font-sans text-[12px] leading-relaxed text-ink">
                {p}
              </li>
            ))}
          </ul>
        </div>
      )}

      <Tier
        index="01"
        title="Quality model"
        blurb="Plans, writes, reviews and draws. Everything whose output you read."
        provider={s.quality_provider}
        model={s.quality_model}
        baseUrl={s.quality_base_url}
        contextWindow={s.quality_context_window}
        keySet={s.openai_key_set}
      />
      <Tier
        index="02"
        title="Fast model"
        blurb="Classifies, extracts and summarises. Thousands of short calls where a small model is the right tool."
        provider={s.fast_provider}
        model={s.fast_model}
        baseUrl={s.fast_base_url}
        contextWindow={s.fast_context_window}
        keySet={s.openai_key_set}
      />
      <Tier
        index="03"
        title="Embedding model"
        blurb="Indexes the source for search. Independent of the other two — every stored vector has the width of the model that produced it, so changing this means re-analysing."
        provider={s.embedding_provider}
        model={s.embedding_model}
        baseUrl={s.embedding_base_url}
        keySet={s.openai_key_set}
      />

      <Panel title="Sampling" index="04">
        <Row k="temperature" v={s.temperature} />
        <Row k="max tokens" v={s.max_tokens.toLocaleString()} />
        <Row k="react loops" v={s.max_react_iterations} />
      </Panel>
    </div>
  )
}

export default function SettingsPage() {
  const { data, loading, error, reload } = useAsync<LLMSettings>(() => api.llmSettings(), [])

  return (
    <div className="mx-auto max-w-[900px] p-5">
      <PageHead index="06" title="Settings" sub="What each tier is pointed at" />

      <div className="mb-5 border border-rule bg-sunk/40 px-4 py-3">
        <div className="flex items-start gap-2.5">
          <span className="mt-1 block size-[7px] shrink-0 rotate-45 bg-hot" />
          <p className="font-sans text-[12px] leading-relaxed text-ink-mid">
            Read-only. Models are configured in <code className="text-hot-ink">.env</code> and
            resolved when a call is placed, so this is what the next job will actually use.
            Set a tier to <code className="text-hot-ink">openai</code> and it needs a key and a
            model name; set it to <code className="text-hot-ink">local</code> for any
            OpenAI-compatible server — LM Studio, vLLM, Ollama, a gateway — where the endpoint
            and the context window matter too.
          </p>
        </div>
      </div>

      {loading && <SkeletonPanel rows={6} />}
      {error && <ErrorState message={error} onRetry={reload} />}
      {data && <Resolved s={data} />}
    </div>
  )
}

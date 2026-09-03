import { useState } from 'react'
import { api, ApiError } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import type { ConfiguredModel, LLMSettings, ModelRegistry, Tier } from '../../lib/types'
import { Button, Dialog, PageHead, Panel } from '../../components/ui'
import { ErrorState, SkeletonPanel } from '../../components/States'
import ModelForm from '../../components/settings/ModelForm'

/* ------------------------------------------------------------------ *
 * The models this installation talks to.
 *
 * One section per tier, and each owns the endpoints that could serve
 * it. There is no separate library list and no separate "in effect"
 * summary: both said again, further down, what the sections already
 * showed, and a page that reports the same fact twice invites the
 * reader to check whether the two agree.
 *
 * Rows rather than a dropdown, because selecting is not the only thing
 * you do to a model. With a dropdown, editing one you had not selected
 * meant selecting it first — which would have changed what the tier
 * runs on, as a side effect of wanting to read it.
 *
 * Chat and embedding endpoints are filtered apart. They take identical
 * fields and answer different calls, so nothing but a stored `kind`
 * can tell them apart, and offering the wrong one produces a tier that
 * refuses every request it is ever sent.
 * ------------------------------------------------------------------ */

const TIERS: { id: Tier; index: string; label: string; blurb: string }[] = [
  {
    id: 'quality',
    index: '01',
    label: 'Quality',
    blurb: 'Plans, writes, reviews. Everything whose output you read.',
  },
  {
    id: 'fast',
    index: '02',
    label: 'Fast',
    blurb: 'Classifies, extracts, summarises. Thousands of short calls where a small model is the right tool.',
  },
  {
    id: 'embedding',
    index: '03',
    label: 'Embedding',
    blurb:
      'Indexes the source for search. Changing it means re-analysing — a vector only means something to the model that made it.',
  },
]

const PROVIDER_LABEL: Record<string, string> = {
  openai: 'openai',
  anthropic: 'anthropic',
  local: 'openai-compatible',
}

const kindFor = (tier: Tier) => (tier === 'embedding' ? 'embedding' : 'chat')

function ModelRow({
  model,
  selected,
  onSelect,
  onEdit,
  onTest,
  onDelete,
  testing,
}: {
  model: ConfiguredModel
  selected: boolean
  onSelect: () => void
  onEdit: () => void
  onTest: () => void
  onDelete: () => void
  testing: boolean
}) {
  const t = model.last_test
  return (
    <li
      className={`border-b border-rule last:border-b-0 ${selected ? 'bg-hot-wash/50' : ''}`}
    >
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 px-3 py-2.5">
        <button
          onClick={onSelect}
          title={selected ? 'Serving this tier' : 'Use this one for this tier'}
          className="flex items-center gap-2"
        >
          <span
            className={`block size-[11px] shrink-0 rounded-full border ${
              selected ? 'border-hot bg-hot' : 'border-rule bg-panel hover:border-ink'
            }`}
          />
          <span
            className={`text-[12.5px] ${selected ? 'font-semibold text-hot-ink' : 'text-ink'}`}
          >
            {model.label}
          </span>
        </button>
        <span className="tag border border-rule bg-sunk px-1.5 text-ink-dim">
          {PROVIDER_LABEL[model.provider] ?? model.provider}
        </span>
        <span className="tag truncate text-ink-mid">{model.model}</span>
        {t?.ok === true && <span className="tag text-ok">✓ connected</span>}
        {t?.ok === false && (
          <span className="tag text-bad" title={t.detail}>
            ✕ failed
          </span>
        )}
        {t?.ok === undefined && <span className="tag text-ink-dim">untested</span>}

        <span className="ml-auto flex shrink-0 gap-2">
          <button
            onClick={onTest}
            disabled={testing}
            className="tag text-ink-dim underline-offset-2 hover:text-hot-ink hover:underline disabled:opacity-50"
          >
            {testing ? 'testing…' : 'test'}
          </button>
          <button
            onClick={onEdit}
            className="tag text-ink-dim underline-offset-2 hover:text-hot-ink hover:underline"
          >
            edit
          </button>
          <button
            onClick={onDelete}
            title={selected ? 'Point this tier elsewhere first' : 'Remove this endpoint'}
            className="tag text-ink-dim underline-offset-2 hover:text-bad hover:underline"
          >
            remove
          </button>
        </span>
      </div>
      <div className="flex flex-wrap items-baseline gap-x-3 px-3 pb-2 text-[11px] text-ink-dim">
        {model.base_url && <span>{model.base_url}</span>}
        {model.context_window ? <span>context {model.context_window.toLocaleString()}</span> : null}
        {model.provider !== 'local' && (
          <span className={model.api_key_set ? '' : 'text-warn'}>
            {model.api_key_set ? 'key stored' : 'no key — this will not work'}
          </span>
        )}
        {t?.dimensions ? <span>{t.dimensions} dims</span> : null}
        {t?.ok === false && t.detail && <span className="text-bad">{t.detail}</span>}
      </div>
    </li>
  )
}

export default function SettingsPage() {
  const reg = useAsync<ModelRegistry>(s => api.models(s), [])
  // Only read for the `.env` fallback line, which is the one thing a tier section
  // cannot say for itself: with nothing assigned, what runs is whatever the file
  // says, and the section has no way to know what that is.
  const live = useAsync<LLMSettings>(() => api.llmSettings(), [])
  const [adding, setAdding] = useState<Tier | null>(null)
  const [editing, setEditing] = useState<{ model: ConfiguredModel; tier: Tier } | null>(null)
  const [testing, setTesting] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const data = reg.data

  async function act(fn: () => Promise<unknown>) {
    setError(null)
    try {
      await fn()
      reg.reload()
      live.reload()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not work.')
    }
  }

  async function test(model: ConfiguredModel, tier: Tier) {
    setTesting(model.id)
    await act(() => api.testModel(model.id, tier))
    setTesting(null)
  }

  return (
    <div className="mx-auto max-w-[900px] p-5">
      <PageHead index="06" title="Models" sub="What this installation can talk to" />

      <div className="mb-5 border border-rule bg-sunk/40 px-4 py-3">
        <div className="flex items-start gap-2.5">
          <span className="mt-1 block size-[7px] shrink-0 rotate-45 bg-hot" />
          <p className="font-sans text-[12px] leading-relaxed text-ink-mid">
            Add the endpoints you have and pick one per tier. Changes apply to the next
            call — nothing needs restarting. A tier with nothing selected falls back to
            whatever <code className="text-hot-ink">.env</code> says, so an existing
            install keeps working until you choose otherwise.
          </p>
        </div>
      </div>

      {error && <ErrorState message={error} compact />}
      {reg.loading && <SkeletonPanel rows={6} />}
      {reg.error && <ErrorState message={reg.error} onRetry={reg.reload} />}

      {data && (
        <div className="flex flex-col gap-4">
          {TIERS.map(tier => {
            const selected = data.tiers[tier.id]
            // Only endpoints that can answer this tier's calls.
            const candidates = data.models.filter(m => m.kind === kindFor(tier.id))
            const fallbackModel = live.data?.[`${tier.id}_model` as keyof LLMSettings]
            const fallbackProvider = live.data?.[`${tier.id}_provider` as keyof LLMSettings]

            return (
              <Panel
                key={tier.id}
                title={`${tier.label} model`}
                index={tier.index}
                action={
                  <button
                    onClick={() => setAdding(tier.id)}
                    className="tag border border-rule px-2 py-1 text-ink-mid transition-colors hover:border-ink hover:text-ink"
                  >
                    + Add a model
                  </button>
                }
              >
                <p className="px-3 pt-2.5 pb-2 font-sans text-[11.5px] leading-relaxed text-ink-mid">
                  {tier.blurb}
                </p>

                {candidates.length === 0 ? (
                  <div className="border-t border-rule px-3 py-3">
                    <p className="font-sans text-[12px] text-ink-mid">
                      Nothing configured for this tier yet.
                    </p>
                    {fallbackModel && (
                      <p className="mt-1 font-sans text-[11.5px] text-warn">
                        Falling back to <code>.env</code>: {String(fallbackModel)} (
                        {String(fallbackProvider)}).
                      </p>
                    )}
                  </div>
                ) : (
                  <>
                    <ul className="border-t border-rule">
                      {candidates.map(m => (
                        <ModelRow
                          key={m.id}
                          model={m}
                          selected={selected === m.id}
                          testing={testing === m.id}
                          onSelect={() => void act(() => api.assignTier(tier.id, m.id))}
                          onEdit={() => setEditing({ model: m, tier: tier.id })}
                          onTest={() => void test(m, tier.id)}
                          onDelete={() => void act(() => api.deleteModel(m.id))}
                        />
                      ))}
                    </ul>
                    {!selected && fallbackModel && (
                      <p className="border-t border-rule bg-warn-wash px-3 py-2 font-sans text-[11.5px] text-warn">
                        None of these is selected, so this tier is still using{' '}
                        <code>.env</code>: {String(fallbackModel)} (
                        {String(fallbackProvider)}).
                      </p>
                    )}
                  </>
                )}
              </Panel>
            )
          })}
        </div>
      )}

      <Dialog
        open={!!adding || !!editing}
        onClose={() => {
          setAdding(null)
          setEditing(null)
        }}
        title={editing ? `Edit ${editing.model.label}` : 'Add a model'}
        width={560}
      >
        <ModelForm
          editing={editing?.model ?? null}
          tierHint={editing?.tier ?? adding ?? 'quality'}
          onDone={() => {
            setAdding(null)
            setEditing(null)
            reg.reload()
            live.reload()
          }}
          onCancel={() => {
            setAdding(null)
            setEditing(null)
          }}
        />
      </Dialog>
    </div>
  )
}

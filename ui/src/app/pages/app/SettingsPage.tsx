import { useState } from 'react'
import { api, ApiError } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import type { ConfiguredModel, LLMSettings, ModelRegistry, Tier } from '../../lib/types'
import { Dialog, PageHead, Panel } from '../../components/ui'
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
 * A dropdown, not a list of rows. Rows put every endpoint's actions
 * within reach, and turned into a wall the moment there were more than
 * a couple — a settings page is read far more often than it is edited,
 * and the common case is one line per tier, not five.
 *
 * The cost is that the actions operate on whichever endpoint is
 * selected, so editing one you are not using means selecting it first.
 * That is worth it: you edit what you run, and a page that stays
 * readable at ten endpoints beats one that saves a click at two.
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

/** Small, bordered, and distinguishable from prose. These were plain text links
 *  the same size as everything around them, which made the one destructive action
 *  on the page look like a label. */
function RowAction({
  children,
  onClick,
  disabled,
  tone = 'plain',
  title,
}: {
  children: React.ReactNode
  onClick: () => void
  disabled?: boolean
  tone?: 'plain' | 'bad'
  title?: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`tag border px-2 py-1 transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
        tone === 'bad'
          ? 'border-bad/40 bg-bad-wash text-bad hover:border-bad hover:bg-bad hover:text-on-hot'
          : 'border-rule bg-panel text-ink-mid hover:border-ink hover:text-ink'
      }`}
    >
      {children}
    </button>
  )
}

/** What the selected endpoint is, under the dropdown that chose it. */
function SelectedDetail({ model }: { model: ConfiguredModel }) {
  const t = model.last_test
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-3 pb-2.5 text-[11px] text-ink-dim">
      <span className="tag border border-rule bg-sunk px-1.5">
        {PROVIDER_LABEL[model.provider] ?? model.provider}
      </span>
      {model.base_url && <span>{model.base_url}</span>}
      {model.context_window ? <span>context {model.context_window.toLocaleString()}</span> : null}
      {model.provider !== 'local' && (
        <span className={model.api_key_set ? '' : 'text-warn'}>
          {model.api_key_set ? 'key stored' : 'no key — this will not work'}
        </span>
      )}
      {t?.dimensions ? <span>{t.dimensions} dims</span> : null}
      {t?.ok === true && <span className="text-ok">✓ connected</span>}
      {t?.ok === false && <span className="text-bad">✕ {t.detail}</span>}
      {t?.ok === undefined && <span>untested</span>}
    </div>
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
            const current = candidates.find(m => m.id === selected) ?? null

            return (
              <Panel
                key={tier.id}
                title={`${tier.label} model`}
                index={tier.index}
                action={
                  <RowAction onClick={() => setAdding(tier.id)}>+ Add a model</RowAction>
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
                    <div className="flex flex-wrap items-center gap-2 border-t border-rule px-3 pt-2.5 pb-2">
                      <select
                        value={selected ?? ''}
                        onChange={e =>
                          e.target.value && void act(() =>
                            api.assignTier(tier.id, Number(e.target.value)),
                          )
                        }
                        className="min-w-[240px] flex-1 border border-rule bg-panel px-2 py-1.5 font-mono text-[12px] text-ink focus:border-hot focus:outline-none"
                      >
                        <option value="">— nothing selected —</option>
                        {candidates.map(m => (
                          <option key={m.id} value={m.id}>
                            {m.label} ({m.model})
                          </option>
                        ))}
                      </select>

                      {/* Acting on whatever is selected. Disabled rather than hidden
                          when nothing is, so the controls do not move about. */}
                      <RowAction
                        onClick={() => current && void test(current, tier.id)}
                        disabled={!current || testing === current?.id}
                      >
                        {testing === current?.id ? 'testing…' : 'Test'}
                      </RowAction>
                      <RowAction
                        onClick={() => current && setEditing({ model: current, tier: tier.id })}
                        disabled={!current}
                      >
                        Edit
                      </RowAction>
                      <RowAction
                        tone="bad"
                        disabled={!current}
                        title="Point this tier elsewhere first"
                        onClick={() => current && void act(() => api.deleteModel(current.id))}
                      >
                        Remove
                      </RowAction>
                    </div>

                    {current && <SelectedDetail model={current} />}

                    {!selected && fallbackModel && (
                      <p className="border-t border-rule bg-warn-wash px-3 py-2 font-sans text-[11.5px] text-warn">
                        Nothing selected, so this tier is still using <code>.env</code>:{' '}
                        {String(fallbackModel)} ({String(fallbackProvider)}).
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

import { useState } from 'react'
import { KeptSource } from '../../components/settings/KeptSource'
import { api, ApiError } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import type { ConfiguredModel, LLMSettings, ModelRegistry, Tier } from '../../lib/types'
import { Dialog, PageHead, Panel } from '../../components/ui'
import { Pill } from '../../components/primitives'
import { BrandMark } from '../../lib/brands'
import { Icon, type IconName } from '../../lib/icons'
import { ErrorState, SkeletonPanel } from '../../components/States'
import ModelForm from '../../components/settings/ModelForm'
import AgentActivity from '../../components/settings/AgentActivity'

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
      'Indexes the source for search. Changing it means re-analysing: a vector only means something to the model that made it.',
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
      className={`inline-flex h-8 items-center gap-1.5 rounded-lg border px-3 text-[12.5px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
        tone === 'bad'
          ? 'border-bad/40 bg-bad-wash text-bad hover:border-bad hover:bg-bad hover:text-on-hot'
          : 'border-line-2 bg-sunk text-ink hover:bg-hover'
      }`}
    >
      {children}
    </button>
  )
}

/** What each probed capability means for the studio when it is missing. */
const CAPABILITY: Record<string, { label: string; icon: IconName; missing: string }> = {
  tools: {
    label: 'Tool calls',
    icon: 'wrench',
    missing:
      'Refuses tool calls, so the assistant cannot search again after its first retrieval: answers rest on what that one search found.',
  },
  temperature: {
    label: 'Temperature',
    icon: 'gauge',
    missing: 'Rejects a set temperature. Codelith leaves it out for this model.',
  },
  reasoning: {
    label: 'Reasoning',
    icon: 'brain',
    missing: '',
  },
}

/** What the selected endpoint is, under the dropdown that chose it. */
function SelectedDetail({ model }: { model: ConfiguredModel }) {
  const t = model.last_test
  const caps = t?.capabilities
  return (
    <div className="flex flex-col gap-3 px-4 pb-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12.5px] text-ink-dim">
        <span className="inline-flex items-center gap-1.5 rounded-md border border-rule px-2 py-0.5 text-ink-mid">
          {model.provider === 'openai' ? (
            <BrandMark name="openai" size={13} decorative />
          ) : model.provider === 'anthropic' ? (
            <BrandMark name="anthropic" size={13} decorative />
          ) : (
            <Icon name="cpu" size={13} />
          )}
          {PROVIDER_LABEL[model.provider] ?? model.provider}
        </span>
        {model.base_url && <span className="font-mono">{model.base_url}</span>}
        {model.context_window ? <span>context {model.context_window.toLocaleString()}</span> : null}
        {model.provider !== 'local' && (
          <span className={model.api_key_set ? '' : 'text-warn'}>
            {model.api_key_set ? 'Key stored' : 'No key, so this will not work'}
          </span>
        )}
        {t?.dimensions ? <span>{t.dimensions} dimensions</span> : null}
        {t?.ok === true && (
          <Pill tone="good" icon="check">
            Connected
          </Pill>
        )}
        {t?.ok === false && (
          <Pill tone="bad" icon="x" title={t.detail}>
            {t.detail}
          </Pill>
        )}
        {t?.ok === undefined && <span>Not tested yet</span>}
      </div>
      {caps && model.kind === 'chat' && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            {Object.entries(CAPABILITY).map(([k, c]) => {
              const v = caps[k as keyof typeof caps]
              if (k === 'reasoning')
                return v ? (
                  <Pill key={k} icon={c.icon}>
                    Reasoning model
                  </Pill>
                ) : null
              return (
                <Pill
                  key={k}
                  tone={v === true ? 'good' : v === false ? 'warn' : 'plain'}
                  icon={c.icon}
                  title={t?.capability_detail?.[k]}
                >
                  {c.label}: {v === true ? 'yes' : v === false ? 'refused' : 'unknown'}
                </Pill>
              )
            })}
          </div>
          {Object.entries(CAPABILITY)
            .filter(([k, c]) => c.missing && caps[k as keyof typeof caps] === false)
            .map(([k, c]) => (
              <p key={k} className="flex items-start gap-2 text-[12.5px] leading-relaxed text-warn">
                <Icon name="triangle-alert" size={14} className="mt-0.5 shrink-0" />
                {c.missing}
              </p>
            ))}
        </div>
      )}
      {t?.ok === true && model.kind === 'chat' && !caps && (
        <p className="text-[12.5px] text-ink-dim">Test again to see which parameters this model accepts.</p>
      )}
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
    <div className="w-full px-6 py-5">
      <PageHead index="06" title="Settings" sub="The models this installation talks to, and the agents that talk to it" />

      <div className="mb-5 max-w-[960px] rounded-xl border border-rule bg-panel px-4 py-3">
        <div className="flex items-start gap-2.5">
          <Icon name="info" size={16} className="mt-0.5 shrink-0 text-ink-dim" />
          <p className="text-[13px] leading-relaxed text-ink-mid">
            Add the endpoints you have and pick one per tier. Changes apply to the next
            call, and nothing needs restarting. A tier with nothing selected falls back to
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
                  <RowAction onClick={() => setAdding(tier.id)}>
                    <Icon name="plus" size={14} /> Add a model
                  </RowAction>
                }
              >
                <p className="px-4 pt-3 pb-2.5 text-[13px] leading-relaxed text-ink-mid">
                  {tier.blurb}
                </p>

                {candidates.length === 0 ? (
                  <div className="border-t border-rule px-4 py-3">
                    <p className="text-[13px] text-ink-mid">
                      Nothing configured for this tier yet.
                    </p>
                    {fallbackModel && (
                      <p className="mt-1 text-[12.5px] text-warn">
                        Falling back to <code>.env</code>: {String(fallbackModel)} (
                        {String(fallbackProvider)}).
                      </p>
                    )}
                  </div>
                ) : (
                  <>
                    <div className="flex flex-wrap items-center gap-2 border-t border-rule px-4 pt-3 pb-3">
                      <select
                        value={selected ?? ''}
                        onChange={e =>
                          e.target.value && void act(() =>
                            api.assignTier(tier.id, Number(e.target.value)),
                          )
                        }
                        className="min-w-[240px] flex-1 rounded-lg border border-line-2 bg-sunk px-3 py-[7px] text-[13px] text-ink focus:border-hot focus:outline-none"
                      >
                        <option value="">nothing selected</option>
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
                        <Icon name={testing === current?.id ? 'loader' : 'zap'} size={14} className={testing === current?.id ? 'anim-spin' : ''} />
                        {testing === current?.id ? 'Testing…' : 'Test'}
                      </RowAction>
                      <RowAction
                        onClick={() => current && setEditing({ model: current, tier: tier.id })}
                        disabled={!current}
                      >
                        <Icon name="pencil" size={14} /> Edit
                      </RowAction>
                      <RowAction
                        tone="bad"
                        disabled={!current}
                        title="Point this tier elsewhere first"
                        onClick={() => current && void act(() => api.deleteModel(current.id))}
                      >
                        <Icon name="trash" size={14} /> Remove
                      </RowAction>
                    </div>

                    {current && <SelectedDetail model={current} />}

                    {!selected && fallbackModel && (
                      <p className="border-t border-rule bg-warn-wash px-4 py-2 text-[12.5px] text-warn">
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

      <div className="mt-8 max-w-[1100px]">
        <AgentActivity />
      </div>

      <div className="mt-8 max-w-[1100px]">
        <KeptSource />
      </div>

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

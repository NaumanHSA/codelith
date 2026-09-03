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
 * This page was a form that saved to a database row nothing read back:
 * model configuration lived in `.env` and was resolved at call time, so
 * the page could show one thing while jobs ran on another. It reports
 * and edits the real configuration now, and a change takes effect on
 * the next call without a restart.
 *
 * Two lists, because they answer two questions. What is *available* is
 * a library you add to and keep; what is *in use* is one choice per
 * tier. Keeping them apart is what makes switching cheap — three
 * configured quality models and a dropdown, rather than editing one set
 * of fields and losing what was there.
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
    blurb: 'Classifies, extracts, summarises. Thousands of short calls.',
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

function TestBadge({ model }: { model: ConfiguredModel }) {
  const t = model.last_test
  if (t?.ok === undefined) return <span className="tag text-ink-dim">untested</span>
  return (
    <span className={`tag ${t.ok ? 'text-ok' : 'text-bad'}`} title={t.detail}>
      {t.ok ? '✓ connected' : '✕ failed'}
    </span>
  )
}

function ModelRow({
  model,
  onEdit,
  onTest,
  onDelete,
  testing,
}: {
  model: ConfiguredModel
  onEdit: () => void
  onTest: () => void
  onDelete: () => void
  testing: boolean
}) {
  return (
    <li className="border-b border-rule px-3 py-2.5 last:border-b-0">
      <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
        <span className="text-[12.5px] font-semibold text-ink">{model.label}</span>
        <span className="tag border border-rule bg-sunk px-1.5 text-ink-dim">
          {PROVIDER_LABEL[model.provider] ?? model.provider}
        </span>
        <span className="tag text-ink-mid">{model.model}</span>
        {!!model.serving.length && (
          <span className="tag border border-hot-edge bg-hot-wash px-1.5 text-hot-ink">
            serving {model.serving.join(' · ')}
          </span>
        )}
        <TestBadge model={model} />
        <span className="ml-auto flex gap-1.5">
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
            className="tag text-ink-dim underline-offset-2 hover:text-bad hover:underline"
          >
            remove
          </button>
        </span>
      </div>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-3 text-[11px] text-ink-dim">
        {model.base_url && <span>{model.base_url}</span>}
        {model.context_window ? <span>context {model.context_window.toLocaleString()}</span> : null}
        {model.provider !== 'local' && (
          <span className={model.api_key_set ? '' : 'text-warn'}>
            {model.api_key_set ? 'key stored' : 'no key — this will not work'}
          </span>
        )}
        {model.last_test?.dimensions ? <span>{model.last_test.dimensions} dims</span> : null}
        {model.last_test?.detail && !model.last_test.ok && (
          <span className="text-bad">{model.last_test.detail}</span>
        )}
      </div>
    </li>
  )
}

export default function SettingsPage() {
  const reg = useAsync<ModelRegistry>(s => api.models(s), [])
  // What the next call will actually use — assignments and `.env` fallback already
  // combined. The page is about configuration; this is the one panel that reports
  // consequence, and without it "using .env" is a claim the reader cannot check.
  const live = useAsync<LLMSettings>(() => api.llmSettings(), [])
  const [adding, setAdding] = useState<Tier | null>(null)
  const [editing, setEditing] = useState<ConfiguredModel | null>(null)
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

  const assign = (tier: Tier, id: number) => void act(() => api.assignTier(tier, id))

  async function test(model: ConfiguredModel) {
    setTesting(model.id)
    // Test against the tier it serves, so an embedding endpoint gets an embedding
    // call rather than a chat completion it would refuse.
    const tier = model.serving[0] ?? 'quality'
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
            Add the endpoints you have, then point each tier at one. Changes apply to the
            next call — nothing needs restarting. A tier with nothing assigned falls back
            to whatever <code className="text-hot-ink">.env</code> says, so an existing
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
            // An embedding tier cannot be served by a chat endpoint and the reverse is
            // just as wrong, but nothing here can tell them apart from the fields
            // alone — so every model is offered and the test is what finds it out.
            return (
              <Panel
                key={tier.id}
                title={`${tier.label} model`}
                index={tier.index}
                action={
                  selected ? null : (
                    <span className="tag text-warn">using .env</span>
                  )
                }
              >
                <p className="px-3 pt-2.5 font-sans text-[11.5px] leading-relaxed text-ink-mid">
                  {tier.blurb}
                </p>
                <div className="flex flex-wrap items-center gap-2 px-3 pt-2 pb-3">
                  <select
                    value={selected ?? ''}
                    onChange={e =>
                      e.target.value && assign(tier.id, Number(e.target.value))
                    }
                    className="border border-rule bg-panel px-2 py-1.5 font-mono text-[12px] text-ink focus:border-hot focus:outline-none"
                  >
                    <option value="">— nothing selected —</option>
                    {data.models.map(m => (
                      <option key={m.id} value={m.id}>
                        {m.label} ({m.model})
                      </option>
                    ))}
                  </select>
                  <Button variant="ghost" onClick={() => setAdding(tier.id)}>
                    + Add a model
                  </Button>
                </div>
              </Panel>
            )
          })}

          <Panel
            title="In effect right now"
            index="00"
            action={<span className="tag text-ink-dim">what the next call uses</span>}
          >
            {live.data ? (
              <ul>
                {TIERS.map(t => {
                  const provider = live.data![`${t.id}_provider` as keyof LLMSettings]
                  const model = live.data![`${t.id}_model` as keyof LLMSettings]
                  const url = live.data![`${t.id}_base_url` as keyof LLMSettings]
                  return (
                    <li
                      key={t.id}
                      className="flex flex-wrap items-baseline gap-x-2.5 border-b border-rule px-3 py-1.5 last:border-b-0"
                    >
                      <span className="tag w-[74px] shrink-0 text-ink-dim">{t.id}</span>
                      <span className="text-[12px] text-ink">{String(model)}</span>
                      <span className="tag text-ink-dim">{String(provider)}</span>
                      <span className="tag ml-auto truncate text-ink-dim">{String(url)}</span>
                    </li>
                  )
                })}
              </ul>
            ) : (
              <p className="px-3 py-2.5 font-sans text-[11.5px] text-ink-dim">
                Reading the resolved configuration…
              </p>
            )}
          </Panel>

          <Panel
            title="Configured endpoints"
            index="04"
            action={<span className="tag text-ink-dim">{data.models.length}</span>}
          >
            {data.models.length === 0 ? (
              <p className="px-3 py-4 font-sans text-[12px] text-ink-mid">
                Nothing configured yet, so every tier is reading{' '}
                <code className="text-hot-ink">.env</code>. Add one above and it becomes
                selectable for any tier.
              </p>
            ) : (
              <ul>
                {data.models.map(m => (
                  <ModelRow
                    key={m.id}
                    model={m}
                    testing={testing === m.id}
                    onEdit={() => setEditing(m)}
                    onTest={() => void test(m)}
                    onDelete={() => void act(() => api.deleteModel(m.id))}
                  />
                ))}
              </ul>
            )}
          </Panel>
        </div>
      )}

      <Dialog
        open={!!adding || !!editing}
        onClose={() => {
          setAdding(null)
          setEditing(null)
        }}
        title={editing ? `Edit ${editing.label}` : 'Add a model'}
        width={560}
      >
        <ModelForm
          editing={editing}
          tierHint={editing?.serving[0] ?? adding ?? 'quality'}
          onDone={() => {
            setAdding(null)
            setEditing(null)
            reg.reload()
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

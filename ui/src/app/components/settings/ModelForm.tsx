import { useState } from 'react'
import { api, ApiError } from '../../lib/api'
import { Button, Field, inputClass } from '../ui'
import type { ConfiguredModel, ModelDraft, ModelTest, Provider, Tier } from '../../lib/types'

/* ------------------------------------------------------------------ *
 * Adding or editing one endpoint.
 *
 * The provider is chosen first and only its own fields appear, which is
 * the same split the backend enforces. They used to share one shape —
 * provider, model, URL, window — and that is precisely how an API key
 * ended up posted to LM Studio, which answered, replying as whatever
 * model it had loaded. Fields that cannot be set cannot be set wrong.
 *
 * Test before save, not after. The useful moment to find out an
 * endpoint is unreachable is while the form is still open.
 * ------------------------------------------------------------------ */

const PROVIDERS: { id: Provider; label: string; blurb: string }[] = [
  {
    id: 'openai',
    label: 'OpenAI',
    blurb: 'A key and a model name. The endpoint is fixed.',
  },
  {
    id: 'anthropic',
    label: 'Anthropic',
    blurb: 'A key and a model name, through the OpenAI-compatible endpoint.',
  },
  {
    id: 'local',
    label: 'OpenAI-compatible',
    blurb: 'LM Studio, vLLM, Ollama, llama.cpp, a gateway. Needs its address.',
  },
]

const BLANK: ModelDraft = {
  label: '',
  provider: 'openai',
  model: '',
  base_url: 'http://localhost:1234/v1',
  context_window: 21000,
  api_key: '',
}

export default function ModelForm({
  editing,
  tierHint,
  onDone,
  onCancel,
}: {
  /** The row being edited, or null when adding. */
  editing: ConfiguredModel | null
  /** Relaxes the context-window requirement for an embedding endpoint, and points
   *  the test at the right kind of call. */
  tierHint: Tier
  onDone: () => void
  onCancel: () => void
}) {
  const [draft, setDraft] = useState<ModelDraft>(
    editing
      ? {
          label: editing.label,
          provider: editing.provider,
          model: editing.model,
          base_url: editing.base_url ?? BLANK.base_url,
          context_window: editing.context_window ?? BLANK.context_window,
          // Never prefilled: the API does not return it, and blank means "keep it".
          api_key: '',
        }
      : { ...BLANK, tier_hint: tierHint },
  )
  const [test, setTest] = useState<ModelTest | null>(null)
  const [busy, setBusy] = useState<'test' | 'save' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const local = draft.provider === 'local'
  const hosted = !local
  const set = <K extends keyof ModelDraft>(k: K, v: ModelDraft[K]) => {
    setDraft(d => ({ ...d, [k]: v }))
    // A changed field invalidates the previous result — a green tick against fields
    // that have since been edited is worse than no tick.
    setTest(null)
  }

  const payload = (): ModelDraft => ({ ...draft, tier_hint: tierHint })

  async function runTest() {
    setBusy('test')
    setError(null)
    try {
      setTest(await api.testDraft(payload()))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not run the test.')
    } finally {
      setBusy(null)
    }
  }

  async function save() {
    setBusy('save')
    setError(null)
    try {
      if (editing) await api.updateModel(editing.id, payload())
      else await api.addModel(payload())
      onDone()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not save.')
      setBusy(null)
    }
  }

  return (
    <div className="flex flex-col gap-3.5">
      <Field label="Name" help="How you will pick this out of a dropdown.">
        <input
          className={inputClass}
          value={draft.label}
          onChange={e => set('label', e.target.value)}
          placeholder="GPT-5.6 Luna"
          autoFocus
        />
      </Field>

      <div>
        <span className="tag mb-1.5 block text-ink-dim">Provider</span>
        <div className="flex flex-wrap gap-1.5">
          {PROVIDERS.map(p => (
            <button
              key={p.id}
              type="button"
              onClick={() => set('provider', p.id)}
              className={`tag border px-2 py-1 transition-colors ${
                draft.provider === p.id
                  ? 'border-hot bg-hot text-on-hot'
                  : 'border-rule bg-panel text-ink-mid hover:border-ink hover:text-ink'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
        <span className="mt-1.5 block text-[10.5px] leading-snug text-ink-dim">
          {PROVIDERS.find(p => p.id === draft.provider)?.blurb}
        </span>
      </div>

      <Field
        label="Model"
        help={
          local
            ? 'Exactly as your server names it. Many local servers ignore this and answer with whatever they have loaded — the test will say so.'
            : 'As the provider names it.'
        }
      >
        <input
          className={inputClass}
          value={draft.model}
          onChange={e => set('model', e.target.value)}
          placeholder={local ? 'liquid/lfm2.5-1.2b' : 'gpt-5.6-luna'}
        />
      </Field>

      {hosted && (
        <Field
          label={editing?.api_key_set ? 'API key — stored' : 'API key'}
          help={
            editing?.api_key_set
              ? 'Leave blank to keep the stored key. Type a new one to replace it.'
              : 'Encrypted before it is stored, and never sent back to this page.'
          }
        >
          <input
            className={inputClass}
            type="password"
            value={draft.api_key ?? ''}
            onChange={e => set('api_key', e.target.value)}
            placeholder={editing?.api_key_set ? '••••••••  (unchanged)' : 'sk-…'}
            autoComplete="off"
          />
        </Field>
      )}

      {local && (
        <>
          <Field label="Endpoint" help="Where the server is listening.">
            <input
              className={inputClass}
              value={draft.base_url ?? ''}
              onChange={e => set('base_url', e.target.value)}
              placeholder="http://localhost:1234/v1"
            />
          </Field>
          {/* Embeddings are never trimmed, so nothing budgets against a window. */}
          {tierHint !== 'embedding' && (
            <Field
              label="Context window"
              help="Prompts are budgeted against it — it decides how much evidence fits."
            >
              <input
                className={inputClass}
                type="number"
                value={draft.context_window ?? ''}
                onChange={e => set('context_window', Number(e.target.value) || null)}
                placeholder="21000"
              />
            </Field>
          )}
        </>
      )}

      {test && (
        <div
          className={`border px-3 py-2 ${
            test.ok ? 'border-ok/40 bg-ok-wash' : 'border-bad/40 bg-bad-wash'
          }`}
        >
          <span className={`tag ${test.ok ? 'text-ok' : 'text-bad'}`}>
            {test.ok ? 'connected' : 'failed'}
          </span>
          <p className="mt-1 font-sans text-[11.5px] leading-relaxed text-ink">{test.detail}</p>
          {test.dimensions && (
            <p className="mt-1 font-sans text-[11px] text-ink-mid">
              Vector width measured at {test.dimensions}. Nothing to configure — it is a
              property of the model.
            </p>
          )}
        </div>
      )}

      {error && (
        <div className="border border-bad/40 bg-bad-wash px-3 py-2 font-sans text-[11.5px] text-bad">
          {error}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-rule pt-3">
        <Button
          variant="ghost"
          onClick={runTest}
          disabled={!!busy || !draft.model.trim()}
        >
          {busy === 'test' ? 'testing…' : 'Test connection'}
        </Button>
        <Button
          variant="hot"
          onClick={save}
          disabled={!!busy || !draft.label.trim() || !draft.model.trim()}
        >
          {busy === 'save' ? 'saving…' : editing ? 'Save changes' : 'Add model'}
        </Button>
        <Button variant="ghost" onClick={onCancel} disabled={!!busy}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

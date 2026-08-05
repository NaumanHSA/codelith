import { useEffect, useState } from 'react'
import { api, ApiError } from '../../lib/api'
import { useAsync } from '../../lib/hooks'
import type { LLMSettings } from '../../lib/types'
import { Button, Field, PageHead, Panel, inputClass } from '../../components/ui'
import { ErrorState, SkeletonPanel, Working } from '../../components/States'

/* ------------------------------------------------------------------ *
 * Settings — LLM configuration (admin-only in the real system).
 *
 * GET /settings/llm  →  show current values
 * PUT /settings/llm  →  save
 *
 * The form mirrors the LLMSettings shape exactly; no field is omitted.
 * ------------------------------------------------------------------ */

const DEFAULTS: LLMSettings = {
  base_url: 'http://localhost:11434/v1',
  api_key: '',
  default_model: 'llama3.1:8b',
  quality_model: 'llama3.1:70b',
  fast_model: 'llama3.1:8b',
  temperature: 0.2,
  max_tokens: 4096,
  max_react_iterations: 10,
}

function NumericField({
  label,
  name,
  help,
  value,
  onChange,
  step = 1,
  min,
  max,
}: {
  label: string
  name: string
  help?: string
  value: number
  onChange: (v: number) => void
  step?: number
  min?: number
  max?: number
}) {
  return (
    <Field label={label} help={help}>
      <input
        type="number"
        name={name}
        value={value}
        step={step}
        min={min}
        max={max}
        onChange={e => onChange(parseFloat(e.target.value))}
        className={inputClass}
      />
    </Field>
  )
}

function TextField({
  label,
  name,
  help,
  value,
  onChange,
  type = 'text',
}: {
  label: string
  name: string
  help?: string
  value: string
  onChange: (v: string) => void
  type?: string
}) {
  return (
    <Field label={label} help={help}>
      <input
        type={type}
        name={name}
        value={value}
        onChange={e => onChange(e.target.value)}
        className={inputClass}
      />
    </Field>
  )
}

function SettingsForm({ initial }: { initial: LLMSettings }) {
  const [form, setForm] = useState<LLMSettings>(initial)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    setForm(initial)
    setDirty(false)
  }, [initial])

  function set<K extends keyof LLMSettings>(k: K, v: LLMSettings[K]) {
    setForm(prev => ({ ...prev, [k]: v }))
    setDirty(true)
    setSaved(false)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await api.putLlmSettings(form)
      setSaved(true)
      setDirty(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save settings.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5">
      {/* Endpoint */}
      <Panel title="Endpoint" index="01">
        <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-2">
          <TextField
            label="Base URL"
            name="base_url"
            help="OpenAI-compatible base URL. Ollama: http://localhost:11434/v1"
            value={form.base_url}
            onChange={v => set('base_url', v)}
          />
          <TextField
            label="API Key"
            name="api_key"
            type="password"
            help='Leave blank for Ollama or "ollama" for the default local key.'
            value={form.api_key}
            onChange={v => set('api_key', v)}
          />
        </div>
      </Panel>

      {/* Models */}
      <Panel title="Models" index="02">
        <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-3">
          <TextField
            label="Default model"
            name="default_model"
            help="Used when no quality tier is specified."
            value={form.default_model}
            onChange={v => set('default_model', v)}
          />
          <TextField
            label="Quality model"
            name="quality_model"
            help="Used for high-stakes generation steps."
            value={form.quality_model}
            onChange={v => set('quality_model', v)}
          />
          <TextField
            label="Fast model"
            name="fast_model"
            help="Used for quick, low-cost steps."
            value={form.fast_model}
            onChange={v => set('fast_model', v)}
          />
        </div>
      </Panel>

      {/* Sampling */}
      <Panel title="Sampling" index="03">
        <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-3">
          <NumericField
            label="Temperature"
            name="temperature"
            help="0.0 = deterministic · 1.0 = creative"
            value={form.temperature}
            onChange={v => set('temperature', v)}
            step={0.05}
            min={0}
            max={2}
          />
          <NumericField
            label="Max tokens"
            name="max_tokens"
            help="Upper bound per LLM call."
            value={form.max_tokens}
            onChange={v => set('max_tokens', v)}
            min={256}
            max={128000}
          />
          <NumericField
            label="Max ReAct iterations"
            name="max_react_iterations"
            help="How many reasoning loops the agents may run."
            value={form.max_react_iterations}
            onChange={v => set('max_react_iterations', v)}
            min={1}
            max={50}
          />
        </div>
      </Panel>

      {/* Footer */}
      <div className="flex items-center gap-3">
        <Button type="submit" variant="hot" disabled={saving || !dirty}>
          {saving ? 'Saving…' : 'Save settings'}
        </Button>
        {saving && <Working label="Saving" />}
        {saved && !dirty && (
          <span className="tag flex items-center gap-1.5 text-ok">
            <span className="block size-[5px] bg-ok" /> Saved
          </span>
        )}
        {error && <span className="tag text-bad">{error}</span>}
        {dirty && !saving && (
          <span className="tag text-ink-dim">Unsaved changes</span>
        )}
      </div>

      {/* Reset */}
      <div className="border-t border-rule pt-4">
        <button
          type="button"
          className="tag text-ink-dim underline-offset-2 hover:text-bad hover:underline transition-colors"
          onClick={() => {
            setForm(DEFAULTS)
            setDirty(true)
            setSaved(false)
          }}
        >
          Reset to defaults
        </button>
      </div>
    </form>
  )
}

export default function SettingsPage() {
  const { data, loading, error, reload } = useAsync(sig => api.llmSettings(), [])

  return (
    <div className="mx-auto max-w-[900px] p-5">
      <PageHead
        index="06"
        title="Settings"
        sub="LLM endpoint and sampling configuration"
      />

      {/* Info strip */}
      <div className="mb-5 border border-rule bg-sunk/40 px-4 py-3">
        <div className="flex items-start gap-2.5">
          <span className="block size-[7px] rotate-45 bg-hot shrink-0 mt-1" />
          <p className="font-sans text-[12px] leading-relaxed text-ink-mid">
            Document Anything connects to any OpenAI-compatible LLM endpoint.
            Configure Ollama locally or point at a hosted provider.
            Changes take effect for the next job run.
          </p>
        </div>
      </div>

      {loading ? (
        <div className="flex flex-col gap-4">
          <SkeletonPanel rows={3} />
          <SkeletonPanel rows={3} />
        </div>
      ) : error ? (
        <ErrorState
          message={`Could not load settings: ${error}`}
          onRetry={reload}
        />
      ) : (
        <SettingsForm initial={data ?? DEFAULTS} />
      )}
    </div>
  )
}

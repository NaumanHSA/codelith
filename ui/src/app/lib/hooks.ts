/* ------------------------------------------------------------------ *
 * Data hooks.
 *
 * useAsync   — one-shot fetch with loading/error/reload, abort on unmount
 * useJob     — polls GET /jobs/{id} while the job is live, stops dead on
 *              a terminal status, and never leaves an interval running
 * useJobLogs — the SSE stream, which is secondary: it carries logs, not
 *              step status, and gives up after 10 minutes
 * ------------------------------------------------------------------ */

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from './api'
import { isTerminal, type Job, type JobLog } from './types'

export interface AsyncState<T> {
  data: T | undefined
  error: string | null
  loading: boolean
  reload: () => void
  setData: (v: T) => void
}

/** Runs `fn` on mount and whenever `deps` change. Aborts in flight work. */
export function useAsync<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  deps: unknown[] = [],
): AsyncState<T> {
  const [data, setData] = useState<T>()
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [nonce, setNonce] = useState(0)

  // Keep the latest fn without making it a dependency of the effect.
  const fnRef = useRef(fn)
  fnRef.current = fn

  useEffect(() => {
    const ctrl = new AbortController()
    let live = true
    setLoading(true)
    setError(null)

    fnRef
      .current(ctrl.signal)
      .then(v => {
        if (live) setData(v)
      })
      .catch(e => {
        if (!live || (e as Error).name === 'AbortError') return
        setError(e instanceof ApiError ? e.message : 'Something went wrong.')
      })
      .finally(() => {
        if (live) setLoading(false)
      })

    return () => {
      live = false
      ctrl.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  const reload = useCallback(() => setNonce(n => n + 1), [])
  return { data, error, loading, reload, setData }
}

const POLL_MS = 2500
/** A job waiting on a person changes when they act, not on its own — poll gently. */
const REVIEW_POLL_MS = 8000

/**
 * Polls a job while it is live. Stops on completed / failed / cancelled, and does
 * not poll a job that is already finished.
 *
 * A job `awaiting_review` keeps polling, slowly: approval resumes it from another
 * request, and the page has to notice that happening.
 */
export function useJob(jobId: number | null) {
  const [job, setJob] = useState<Job>()
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(jobId != null)

  useEffect(() => {
    if (jobId == null) {
      setJob(undefined)
      setLoading(false)
      return
    }

    let live = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const ctrl = new AbortController()

    setLoading(true)
    setError(null)

    const tick = async () => {
      try {
        const next = await api.job(jobId, ctrl.signal)
        if (!live) return
        setJob(next)
        setError(null)
        setLoading(false)
        // Schedule the next poll only while the job can still change.
        if (!isTerminal(next.status)) {
          timer = setTimeout(
            tick,
            next.status === 'awaiting_review' ? REVIEW_POLL_MS : POLL_MS,
          )
        }
      } catch (e) {
        if (!live || (e as Error).name === 'AbortError') return
        setLoading(false)
        setError(e instanceof ApiError ? e.message : 'Lost contact with the job.')
        // Transient failures should not kill the poll loop; back off instead.
        timer = setTimeout(tick, POLL_MS * 2)
      }
    }

    tick()

    return () => {
      live = false
      ctrl.abort()
      if (timer) clearTimeout(timer)
    }
  }, [jobId])

  return { job, error, loading, setJob }
}

const MAX_LOGS = 600

/**
 * Live logs. Seeds from GET /jobs/{id}/logs, then follows the SSE stream.
 * The stream gives up after 10 minutes with `event: timeout` — a long
 * composition outlives it, so reconnect while the job is still running.
 */
export function useJobLogs(jobId: number | null, active: boolean) {
  const [logs, setLogs] = useState<JobLog[]>([])
  const [streaming, setStreaming] = useState(false)

  useEffect(() => {
    if (jobId == null) return
    let live = true
    const ctrl = new AbortController()

    api
      .jobLogs(jobId, ctrl.signal)
      .then(seed => {
        if (live) setLogs(seed.slice(-MAX_LOGS))
      })
      .catch(() => {
        /* logs are best-effort; the job poll is the source of truth */
      })

    return () => {
      live = false
      ctrl.abort()
    }
  }, [jobId])

  useEffect(() => {
    if (jobId == null || !active) {
      setStreaming(false)
      return
    }

    let live = true
    let source: EventSource | null = null
    let retry: ReturnType<typeof setTimeout> | undefined

    const connect = () => {
      if (!live) return
      source = new EventSource(api.streamUrl(jobId))
      setStreaming(true)

      source.onmessage = e => {
        if (!live) return
        try {
          const entry = JSON.parse(e.data) as JobLog
          setLogs(prev =>
            prev.some(l => l.id === entry.id) ? prev : [...prev, entry].slice(-MAX_LOGS),
          )
        } catch {
          /* ignore malformed frames */
        }
      }

      const close = () => {
        source?.close()
        source = null
        setStreaming(false)
      }

      source.addEventListener('done', close)
      source.addEventListener('error', close)
      // Ten-minute cap: reconnect, because the job may still be running.
      source.addEventListener('timeout', () => {
        close()
        if (live) retry = setTimeout(connect, 1000)
      })
      source.onerror = () => {
        close()
        if (live) retry = setTimeout(connect, 4000)
      }
    }

    connect()

    return () => {
      live = false
      if (retry) clearTimeout(retry)
      source?.close()
      setStreaming(false)
    }
  }, [jobId, active])

  return { logs, streaming }
}

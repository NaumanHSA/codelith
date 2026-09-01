import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode,
} from 'react'
import { api } from './lib/api'
import { isTerminal, type Job, type JobStatus, type JobType } from './lib/types'

/* ------------------------------------------------------------------ *
 * A running job must be visible from anywhere.
 *
 * Users start an analysis and navigate away; they need their way back.
 * Tracked job ids are persisted so a page reload does not lose them, and
 * each is polled until it reaches a terminal status — then dropped.
 * ------------------------------------------------------------------ */

export interface TrackedJob {
  id: number
  projectId: number
  projectName?: string
  jobType: JobType
  status: JobStatus
}

interface Value {
  jobs: TrackedJob[]
  track: (job: Job, projectName?: string) => void
  untrack: (id: number) => void
}

const Ctx = createContext<Value | null>(null)

const KEY = 'da.tracked_jobs'
const POLL_MS = 3000

interface Seed {
  id: number
  projectId: number
  projectName?: string
  jobType: JobType
}

function readSeeds(): Seed[] {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    return Array.isArray(raw) ? raw.filter(s => typeof s?.id === 'number') : []
  } catch {
    return []
  }
}

/**
 * Update one job's status, returning the *same* array when nothing changed.
 *
 * `prev.map()` allocates unconditionally, so a poll that found no change still
 * produced a new array, a new context value, and a re-render of every consumer —
 * every three seconds, app-wide, for as long as any job was tracked.
 */
function withStatus(prev: TrackedJob[], id: number, status: JobStatus): TrackedJob[] {
  const i = prev.findIndex(j => j.id === id)
  if (i === -1 || prev[i].status === status) return prev
  const copy = [...prev]
  copy[i] = { ...copy[i], status }
  return copy
}

export function RunningJobsProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<TrackedJob[]>([])
  const seeds = useRef<Map<number, Seed>>(new Map())

  // Restore whatever was in flight before the reload — but check before showing it.
  //
  // This used to seed every stored id with `status: 'running'` and render it
  // immediately. A stored id is *not* evidence a job is live: you normally close the
  // tab after the work finishes, so the common case was a banner announcing a
  // composition that had completed a day earlier. It then turned green when the first
  // poll landed and vanished eight seconds later, shifting every page under it — the
  // flicker that showed up on whichever page you happened to open.
  //
  // So nothing is rendered until a fetch says the job is genuinely unfinished.
  // Terminal ones are dropped silently: an outcome nobody was watching for is not
  // news, and the grace period below exists for jobs that finish while you watch.
  useEffect(() => {
    const stored = readSeeds()
    if (!stored.length) return
    for (const s of stored) seeds.current.set(s.id, s)

    let live = true
    const ctrl = new AbortController()

    void (async () => {
      const alive: TrackedJob[] = []
      await Promise.all(
        stored.map(async s => {
          try {
            const job = await api.job(s.id, ctrl.signal)
            if (isTerminal(job.status)) {
              seeds.current.delete(s.id)
              return
            }
            alive.push({
              id: s.id,
              projectId: s.projectId,
              projectName: s.projectName,
              jobType: s.jobType,
              status: job.status,
            })
          } catch {
            // Deleted, or the server is unreachable. Either way it is not something
            // to keep a banner for.
            seeds.current.delete(s.id)
          }
        }),
      )
      if (!live) return
      persist()
      if (alive.length) setJobs(alive)
    })()

    return () => {
      live = false
      ctrl.abort()
    }
    // `persist` is stable (useCallback with no deps); this runs once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const persist = useCallback(() => {
    localStorage.setItem(KEY, JSON.stringify([...seeds.current.values()]))
  }, [])

  const untrack = useCallback(
    (id: number) => {
      seeds.current.delete(id)
      persist()
      setJobs(prev => prev.filter(j => j.id !== id))
    },
    [persist],
  )

  const track = useCallback(
    (job: Job, projectName?: string) => {
      if (isTerminal(job.status)) return
      seeds.current.set(job.id, {
        id: job.id,
        projectId: job.project_id,
        projectName,
        jobType: job.job_type,
      })
      persist()
      setJobs(prev => {
        const next: TrackedJob = {
          id: job.id,
          projectId: job.project_id,
          projectName,
          jobType: job.job_type,
          status: job.status,
        }
        const i = prev.findIndex(j => j.id === job.id)
        if (i === -1) return [...prev, next]
        const copy = [...prev]
        copy[i] = { ...copy[i], ...next }
        return copy
      })
    },
    [persist],
  )

  // One interval for all tracked jobs, cleared on unmount.
  useEffect(() => {
    if (!jobs.length) return
    let live = true
    const ctrl = new AbortController()

    const tick = async () => {
      const ids = [...seeds.current.keys()]
      await Promise.all(
        ids.map(async id => {
          try {
            const job = await api.job(id, ctrl.signal)
            if (!live) return
            if (isTerminal(job.status)) {
              // Keep terminal states on screen briefly so the user sees
              // the outcome, then stop polling this job.
              seeds.current.delete(id)
              persist()
              setJobs(prev => withStatus(prev, id, job.status))
              setTimeout(() => live && untrack(id), 8000)
            } else {
              setJobs(prev => withStatus(prev, id, job.status))
            }
          } catch {
            // A job that 404s or a dropped connection should not wedge
            // the indicator; stop following it.
            if (live) untrack(id)
          }
        }),
      )
    }

    const timer = setInterval(tick, POLL_MS)
    tick()

    return () => {
      live = false
      ctrl.abort()
      clearInterval(timer)
    }
  }, [jobs.length, persist, untrack])

  const value = useMemo(() => ({ jobs, track, untrack }), [jobs, track, untrack])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useRunningJobs(): Value {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useRunningJobs must be used inside <RunningJobsProvider>')
  return ctx
}

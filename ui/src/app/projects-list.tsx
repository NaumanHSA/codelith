import {
  createContext, useCallback, useContext, useEffect, useState, type ReactNode,
} from 'react'
import { api } from './lib/api'
import type { Project } from './lib/types'

/* ------------------------------------------------------------------ *
 * The list of codebases, shared by everything in the rail.
 *
 * Three sections of the rail need it — Documentation, the codebase list,
 * and the shell itself — and each was fetching it. The same request three
 * times on every navigation, and three chances for the sections to
 * disagree about what exists.
 *
 * Sorted newest-touched first here rather than at each call site, so
 * that "recent" means the same thing in every section.
 * ------------------------------------------------------------------ */

interface Value {
  projects: Project[]
  loading: boolean
  refresh: () => Promise<void>
}

const Ctx = createContext<Value | null>(null)

export function ProjectsListProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const list = await api.projects(30, 0)
      setProjects(
        [...list].sort(
          (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
        ),
      )
    } catch {
      // The rail is not worth an error state — an empty list reads as "nothing
      // added yet", which is what it looks like from here anyway.
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  return <Ctx.Provider value={{ projects, loading, refresh }}>{children}</Ctx.Provider>
}

export function useProjectsList(): Value {
  const value = useContext(Ctx)
  if (!value) throw new Error('useProjectsList must be used inside ProjectsListProvider')
  return value
}

import {
  createContext, useCallback, useContext, useEffect, useState, type ReactNode,
} from 'react'
import { api } from './lib/api'
import type { ChatThreadSummary } from './lib/types'

/* ------------------------------------------------------------------ *
 * The list of conversations, shared by the rail and the chat page.
 *
 * Both need it and both change it: asking the first question of a new
 * chat creates a thread and titles it, deleting one from the rail's menu
 * removes it. Fetching in two places would leave a rail showing a thread
 * that no longer exists, or missing one just created — so it is fetched
 * once here, and whoever changes it calls `refresh`.
 * ------------------------------------------------------------------ */

interface Value {
  threads: ChatThreadSummary[]
  loading: boolean
  refresh: () => Promise<void>
}

const Ctx = createContext<Value | null>(null)

export function ChatThreadsProvider({ children }: { children: ReactNode }) {
  const [threads, setThreads] = useState<ChatThreadSummary[]>([])
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      setThreads(await api.chatThreads())
    } catch {
      // The rail is not worth an error state. An empty list reads as "no
      // conversations yet", which is what it looks like from here anyway.
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  return <Ctx.Provider value={{ threads, loading, refresh }}>{children}</Ctx.Provider>
}

export function useChatThreads(): Value {
  const value = useContext(Ctx)
  if (!value) throw new Error('useChatThreads must be used inside ChatThreadsProvider')
  return value
}

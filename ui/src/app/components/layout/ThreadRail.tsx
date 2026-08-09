import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../../lib/api'
import { useChatThreads } from '../../chat-threads'
import type { ChatThreadSummary } from '../../lib/types'
import ConfirmDelete from '../ConfirmDelete'

/* ------------------------------------------------------------------ *
 * Conversations in the rail.
 *
 * Flat and cross-project. A list nested under whichever project happens
 * to be selected is only reachable once you are already in the right
 * place, which is the opposite of what "recent" is for — so each row
 * names its repository instead.
 * ------------------------------------------------------------------ */

/** Where a new conversation starts. `thread=new` rather than a bare URL, so that
 *  pressing New Chat does not silently resume the last one on the next reload. */
export const NEW_CHAT = (projectId?: number) =>
  `/app/chat?thread=new${projectId ? `&project=${projectId}` : ''}`

function RowMenu({
  thread,
  onDeleted,
}: {
  thread: ChatThreadSummary
  onDeleted: () => void
}) {
  const [open, setOpen] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  // Any click elsewhere closes it. Without this the menu survives navigation and
  // hangs over whatever the reader opened next.
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  const exportMd = async () => {
    setOpen(false)
    setBusy(true)
    try {
      await api.exportChatThread(thread.project_id, thread.id, thread.title)
    } catch {
      // Nothing to recover: the file either downloaded or it did not.
    } finally {
      setBusy(false)
    }
  }

  return (
    <div ref={box} className="relative shrink-0">
      <button
        type="button"
        aria-label={`Options for ${thread.title}`}
        onClick={e => {
          e.stopPropagation()
          setOpen(o => !o)
        }}
        className={`flex size-5 items-center justify-center text-[13px] leading-none transition-colors ${
          open ? 'text-hot-ink' : 'text-ink-dim hover:text-ink'
        } ${busy ? 'anim-pulse' : ''}`}
      >
        ⋯
      </button>

      {open && (
        <div className="absolute top-full right-0 z-30 mt-1 w-[136px] border border-rule bg-panel shadow-sm">
          <button
            type="button"
            onClick={e => {
              e.stopPropagation()
              void exportMd()
            }}
            className="block w-full px-2.5 py-1.5 text-left text-[11px] text-ink-mid transition-colors hover:bg-sunk hover:text-ink"
          >
            Export as Markdown
          </button>
          <button
            type="button"
            onClick={e => {
              e.stopPropagation()
              setOpen(false)
              setConfirming(true)
            }}
            className="block w-full border-t border-rule px-2.5 py-1.5 text-left text-[11px] text-ink-mid transition-colors hover:bg-bad-wash hover:text-bad"
          >
            Delete
          </button>
        </div>
      )}

      <ConfirmDelete
        open={confirming}
        onClose={() => setConfirming(false)}
        onConfirm={async () => {
          await api.deleteChatThread(thread.project_id, thread.id)
          onDeleted()
        }}
        actionLabel="Delete"
        title="Delete this conversation?"
        body={`"${thread.title}" and every message in it are removed. Documentation generated from these answers is untouched.`}
      />
    </div>
  )
}

export default function ThreadRail() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const { threads, loading, refresh } = useChatThreads()

  const activeId = Number(params.get('thread')) || null
  const activeProject = Number(params.get('project')) || undefined

  return (
    <>
      <button
        onClick={() => navigate(NEW_CHAT(activeProject))}
        className="flex w-full items-center gap-2 py-[7px] pr-2 pl-4 text-left text-[11.5px] text-ink-mid transition-colors hover:bg-sunk hover:text-ink"
      >
        <span className="text-[13px] leading-none text-hot">+</span>
        New chat
      </button>

      <div className="max-h-[34vh] overflow-y-auto">
        {loading && <p className="px-4 py-1 text-[10.5px] text-ink-dim">Loading…</p>}

        {!loading && threads.length === 0 && (
          <p className="px-4 py-1 text-[10.5px] leading-snug text-ink-dim">
            No conversations yet.
          </p>
        )}

        {threads.map(t => {
          const active = t.id === activeId
          return (
            <div
              key={t.id}
              className={`group relative flex items-center gap-1.5 pr-1.5 pl-4 transition-colors ${
                active ? 'bg-hot-wash' : 'hover:bg-sunk'
              }`}
            >
              {active && <span className="absolute top-0 left-0 h-full w-[3px] bg-hot" />}
              <button
                onClick={() => navigate(`/app/chat?project=${t.project_id}&thread=${t.id}`)}
                title={`${t.title} — ${t.project_name}`}
                className="min-w-0 flex-1 py-[5px] text-left"
              >
                <span
                  className={`block truncate text-[11px] ${
                    active ? 'font-semibold text-hot-ink' : 'text-ink-mid'
                  }`}
                >
                  {t.title}
                </span>
                <span className="block truncate text-[9.5px] text-ink-dim">
                  {t.project_name}
                </span>
              </button>
              <RowMenu
                thread={t}
                onDeleted={() => {
                  void refresh()
                  // The reader was looking at what they just deleted.
                  if (active) navigate(NEW_CHAT(t.project_id))
                }}
              />
            </div>
          )
        })}
      </div>
    </>
  )
}

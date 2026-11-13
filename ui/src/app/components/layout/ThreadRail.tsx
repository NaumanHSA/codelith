import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../../lib/api'
import { useChatThreads } from '../../chat-threads'
import type { ChatThreadSummary } from '../../lib/types'
import ConfirmDelete from '../ConfirmDelete'
import { Icon } from '../../lib/icons'

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

/** Menu width, needed before the menu exists to keep it on screen. */
const MENU_W = 150

function RowMenu({
  thread,
  onDeleted,
}: {
  thread: ChatThreadSummary
  onDeleted: () => void
}) {
  const [at, setAt] = useState<{ top: number; left: number } | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const open = at !== null

  /**
   * Opening measures the trigger and pins the menu to the viewport.
   *
   * The rail is a scroll container with a bounded height, so a menu rendered
   * inside it was clipped at the edge and pushed the list into scrolling. This
   * one lives in a portal on `document.body` and is positioned from the
   * trigger's rect — which is also why it has to close on scroll rather than
   * follow it.
   */
  const openMenu = () => {
    const r = trigger.current?.getBoundingClientRect()
    if (!r) return
    const left = Math.min(r.right - MENU_W, window.innerWidth - MENU_W - 8)
    const below = window.innerHeight - r.bottom
    // Flip above the trigger when there is not room beneath it — threads near the
    // bottom of a long list otherwise open a menu half off the screen.
    const top = below < 90 ? r.top - 78 : r.bottom + 4
    setAt({ top, left: Math.max(8, left) })
  }

  // Anything that moves or dismisses closes it: a click elsewhere, Escape, a
  // scroll, a resize. A fixed menu that survives a scroll detaches from the row
  // it belongs to and points at the wrong thread.
  useEffect(() => {
    if (!open) return
    const close = () => setAt(null)
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', onKey)
    // Capture: the rail's own scroll does not bubble to window.
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
    }
  }, [open])

  const exportMd = async () => {
    setAt(null)
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
    <div className="shrink-0">
      <button
        ref={trigger}
        type="button"
        aria-label={`Options for ${thread.title}`}
        aria-expanded={open}
        onMouseDown={e => e.stopPropagation()}
        onClick={e => {
          e.stopPropagation()
          if (open) setAt(null)
          else openMenu()
        }}
        className={`flex size-5 items-center justify-center text-[13px] leading-none transition-colors ${
          open ? 'text-hot-ink' : 'text-ink-dim hover:text-ink'
        } ${busy ? 'anim-pulse' : ''}`}
      >
        <Icon name="ellipsis" size={15} />
      </button>

      {at &&
        createPortal(
          <div
            role="menu"
            style={{ position: 'fixed', top: at.top, left: at.left, width: MENU_W }}
            // The dismiss listener is on mousedown, so the menu must stop its own
            // or every click closes it before the button below can fire.
            onMouseDown={e => e.stopPropagation()}
            className="z-50 overflow-hidden rounded-lg border border-line-2 bg-panel p-1 shadow-[0_16px_40px_-12px_var(--shadow)]"
          >
            <button
              type="button"
              onClick={() => void exportMd()}
              className="block w-full rounded-md px-2.5 py-1.5 text-left text-[12.5px] text-ink-mid transition-colors hover:bg-hover hover:text-ink"
            >
              Export as Markdown
            </button>
            <button
              type="button"
              onClick={() => {
                setAt(null)
                setConfirming(true)
              }}
              className="block w-full rounded-md px-2.5 py-1.5 text-left text-[12.5px] text-ink-mid transition-colors hover:bg-bad-wash hover:text-bad"
            >
              Delete
            </button>
          </div>,
          document.body,
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
        className="flex w-full items-center gap-2.5 rounded-[7px] px-2.5 py-[6px] text-left text-[13px] text-ink-mid transition-colors hover:bg-hover hover:text-ink"
      >
        <Icon name="plus" size={15} className="text-hot" />
        New chat
      </button>

      <div className="max-h-[30vh] overflow-y-auto">
        {loading && <p className="px-2.5 py-1 text-[12px] text-ink-dim">Loading…</p>}

        {!loading && threads.length === 0 && (
          <p className="px-2.5 py-1 text-[12px] leading-snug text-ink-dim">
            No conversations yet.
          </p>
        )}

        {threads.map(t => {
          const active = t.id === activeId
          return (
            <div
              key={t.id}
              className={`group flex items-center gap-1.5 rounded-[7px] pr-1.5 pl-2.5 transition-colors ${
                active
                  ? 'bg-sunk text-ink shadow-[inset_0_0_0_1px_var(--rule)]'
                  : 'text-ink-mid hover:bg-hover hover:text-ink'
              }`}
            >
              <Icon
                name="message-square"
                size={15}
                className={active ? 'text-hot' : 'text-ink-dim group-hover:text-ink'}
              />
              <button
                onClick={() => navigate(`/app/chat?project=${t.project_id}&thread=${t.id}`)}
                title={`${t.title} · ${t.project_name}`}
                className="min-w-0 flex-1 py-[5px] pl-1 text-left"
              >
                <span className={`block truncate text-[13px] ${active ? 'font-medium' : ''}`}>
                  {t.title}
                </span>
                <span className="block truncate text-[11px] text-ink-dim">{t.project_name}</span>
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

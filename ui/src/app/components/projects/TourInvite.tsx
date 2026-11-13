import { Link } from 'react-router-dom'
import { Icon } from '../../lib/icons'
import { readTourProgress } from '../../lib/tour'

/** "New to this codebase?" — the way into its tour, or back to where the viewer left it. */
export default function TourInvite({ projectId }: { projectId: number }) {
  const progress = readTourProgress(projectId)
  const done = progress !== null && progress.at >= progress.of
  const midway = progress !== null && !done && progress.at > 0
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-rule bg-panel px-4 py-3">
      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-hot/15 text-hot-ink">
        <Icon name="compass" size={18} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[14px] font-medium text-ink">
          {done ? 'You have taken the tour' : midway ? 'Pick the tour up where you left it' : 'New to this codebase?'}
        </span>
        <span className="block text-[12.5px] leading-snug text-ink-mid">
          {midway
            ? `Stop ${progress!.at + 1} of ${progress!.of}.`
            : 'A guided walk on the knowledge graph: how it is laid out, where work comes in, one real request followed to its data, and the files where an edit hurts.'}
        </span>
      </span>
      <Link
        to={`/app/projects/${projectId}/graph?tour=1`}
        className="inline-flex items-center gap-2 rounded-lg bg-hot px-3.5 py-[7px] text-[13px] font-semibold text-on-hot transition-opacity hover:opacity-90"
      >
        {done ? 'Take it again' : midway ? 'Continue the tour' : 'Take the tour'}
        <Icon name="arrow-right" size={15} />
      </Link>
    </div>
  )
}

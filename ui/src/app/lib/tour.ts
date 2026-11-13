/* Where a viewer is in a codebase's tour (`apps/tour`), kept in this browser only: a
 * convenience, so a missing or refused store just starts the tour from the top. */

export interface TourProgress {
  /** The stop to resume at; equal to `of` once the tour was finished. */
  at: number
  of: number
}

const key = (projectId: number) => `codelith.tour.${projectId}`

export function readTourProgress(projectId: number): TourProgress | null {
  try {
    const raw = localStorage.getItem(key(projectId))
    if (!raw) return null
    const v = JSON.parse(raw) as { at?: unknown; of?: unknown }
    return typeof v.at === 'number' && typeof v.of === 'number' ? { at: v.at, of: v.of } : null
  } catch {
    return null
  }
}

export function writeTourProgress(projectId: number, at: number, of: number) {
  try {
    localStorage.setItem(key(projectId), JSON.stringify({ at, of }))
  } catch {
    /* a convenience only */
  }
}

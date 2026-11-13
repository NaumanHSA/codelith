import { useEffect, useRef, useState, type CSSProperties } from 'react'

/* ------------------------------------------------------------------ *
 * Motion, in one place.
 *
 * The studio moves to say something changed: a number arriving, a bar
 * filling, a row appearing. Every one of those goes through here so the
 * timings agree and so a reader who asked their system for less motion
 * gets the end state at once rather than a slower version of the same
 * animation. CSS animations are covered by the reduced-motion block in
 * index.css; these are the ones driven from script.
 * ------------------------------------------------------------------ */

/** Milliseconds. `quick` for hover and press, `base` for things entering,
 *  `slow` for a panel or a fill, `count` for a number counting up. */
export const DURATION = { quick: 150, base: 240, slow: 420, count: 900 } as const

export const EASE = {
  /** Fast start, soft landing. The default for anything arriving. */
  out: 'cubic-bezier(0.2, 0, 0, 1)',
  inOut: 'cubic-bezier(0.65, 0, 0.35, 1)',
  /** A small overshoot, for a badge or a mark that should be noticed. */
  spring: 'cubic-bezier(0.34, 1.56, 0.64, 1)',
} as const

const QUERY = '(prefers-reduced-motion: reduce)'

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.(QUERY).matches
}

/** Whether the reader asked for less motion, kept current if they change it. */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(prefersReducedMotion)
  useEffect(() => {
    const mq = window.matchMedia?.(QUERY)
    if (!mq) return
    const update = () => setReduced(mq.matches)
    mq.addEventListener('change', update)
    return () => mq.removeEventListener('change', update)
  }, [])
  return reduced
}

const easeOutCubic = (t: number) => 1 - (1 - t) ** 3

/**
 * A number that counts to `target`, from wherever it last was. With reduced
 * motion it is `target` from the first render.
 *
 * Browsers pause animation frames in a background tab, so a page opened there
 * shows its starting value until it is looked at, then counts. Nothing should
 * read the counted value as data: render it, and keep the real one for labels.
 */
export function useCountUp(target: number, duration: number = DURATION.count): number {
  const reduced = useReducedMotion()
  const [value, setValue] = useState(0)
  const from = useRef(0)

  useEffect(() => {
    if (reduced) return
    const start = performance.now()
    const origin = from.current
    let frame = 0
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const next = origin + (target - origin) * easeOutCubic(t)
      from.current = next
      setValue(next)
      if (t < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [target, duration, reduced])

  return reduced ? target : value
}

/**
 * A percentage for a bar's width that starts at 0 and moves to `pct` on the
 * next frame, so a CSS width transition draws the fill. With reduced motion it
 * is `pct` from the first render.
 */
export function useFill(pct: number): number {
  const reduced = useReducedMotion()
  const [shown, setShown] = useState(0)
  useEffect(() => {
    if (reduced) return
    const frame = requestAnimationFrame(() => setShown(pct))
    return () => cancelAnimationFrame(frame)
  }, [pct, reduced])
  return reduced ? pct : shown
}

/** The style that staggers the i-th item of a list entering with `.anim-rise`.
 *  Capped, so a long list does not keep arriving for seconds. */
export function stagger(i: number, step = 35, cap = 12): CSSProperties {
  return { animationDelay: `${Math.min(i, cap) * step}ms` }
}

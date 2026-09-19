/**
 * Trigger-time reduced-motion gate (brief §5.1; gate M1).
 *
 * The universal CSS clamp in base.css is the backstop; every JS-driven
 * animation ADDITIONALLY calls prefersReducedMotion() at trigger time
 * and long-lived surfaces subscribe to changes. A missing gate is a
 * review blocker (MOT-NO-5 precedent).
 */

const QUERY = "(prefers-reduced-motion: reduce)";

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return true; // no media-query surface -> stay still, never guess
  }
  return window.matchMedia(QUERY).matches;
}

/** Subscribe to live changes; returns an unsubscribe function. */
export function onReducedMotionChange(cb: (reduced: boolean) => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return () => {};
  }
  const mql = window.matchMedia(QUERY);
  const handler = (e: MediaQueryListEvent) => cb(e.matches);
  mql.addEventListener("change", handler);
  return () => mql.removeEventListener("change", handler);
}

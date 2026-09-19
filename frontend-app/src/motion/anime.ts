/**
 * anime.js v4 wrappers — the ONLY sanctioned entry point for JS-driven
 * DOM motion in this app (brief §5.2). The engine is lazy-imported
 * (CircuitDiagram dynamic-import pattern; budget <=15 kB gzip for the
 * tree-shaken chunk — measured in the slice report) and every helper
 * gates on prefers-reduced-motion at trigger time (gate M1).
 *
 * API surface is deliberately narrow: entrances, exits, refresh flash,
 * capped row stagger. There is NO generic passthrough — that is how
 * bounce easings and 800 ms DOM tweens sneak in (M2, NO-17).
 */
import {
  DUR_1,
  DUR_2,
  DUR_3,
  EASE_EXIT,
  EASE_LINEAR,
  EASE_STANDARD,
  STAGGER_MAX_ITEMS,
  STAGGER_MAX_MS,
  STAGGER_MIN_MS,
  STAGGER_TOTAL_MAX_MS,
} from "./tokens";
import { prefersReducedMotion } from "./reducedMotion";

type AnimeModule = typeof import("./engine");

let animeModule: Promise<AnimeModule> | null = null;

/** Lazy singleton import of the motion engine (NO-15 discipline).
 * Imports ./engine (named re-exports) rather than the package so the
 * chunk is tree-shaken to the wrapper subset (budget <=15 kB gzip). */
export function loadAnime(): Promise<AnimeModule> {
  if (animeModule === null) {
    animeModule = import("./engine");
  }
  return animeModule;
}

/** Interface-feedback durations are DUR_1..DUR_3 only; DUR_4 is the 3D
 * camera's and is not accepted by any DOM wrapper (M2/NO-17). */
export type DomDuration = typeof DUR_1 | typeof DUR_2 | typeof DUR_3;

/**
 * Pure stagger-cap computation (unit-tested): stagger only the first
 * STAGGER_MAX_ITEMS items at a delay inside the 40-60 ms band, keeping
 * the whole sequence <= STAGGER_TOTAL_MAX_MS. Items past the cap
 * appear with the last animated one (delay of the final step).
 */
export function clampStagger(
  itemCount: number,
  perItemMs: number = STAGGER_MIN_MS,
): { perItemMs: number; animatedCount: number; totalMs: number } {
  const ms = Math.min(Math.max(perItemMs, STAGGER_MIN_MS), STAGGER_MAX_MS);
  const animatedCount = Math.min(itemCount, STAGGER_MAX_ITEMS);
  const capped = Math.min(ms, animatedCount > 1 ? STAGGER_TOTAL_MAX_MS / (animatedCount - 1) : ms);
  return {
    perItemMs: capped,
    animatedCount,
    totalMs: animatedCount > 1 ? capped * (animatedCount - 1) : 0,
  };
}

/** Fade-up entrance: opacity 0->1, translateY 8px->0, DUR_2 standard. */
export async function enterFadeUp(targets: Element | Element[], duration: DomDuration = DUR_2) {
  if (prefersReducedMotion()) return; // CSS clamp is backstop; skip entirely
  const { animate } = await loadAnime();
  animate(targets, {
    opacity: { from: 0, to: 1 },
    translateY: { from: 8, to: 0 },
    duration,
    ease: EASE_STANDARD,
  });
}

/** Exit crossfade: opacity ->0, DUR_2, accelerate ease. */
export async function exitFade(targets: Element | Element[], duration: DomDuration = DUR_2) {
  if (prefersReducedMotion()) return;
  const { animate } = await loadAnime();
  animate(targets, { opacity: { from: 1, to: 0 }, duration, ease: EASE_EXIT });
}

/** Refresh flash (badge/value swap): matches the shipped console's
 * 400 ms flash grammar. Signal color comes from CSS; this only pulses
 * opacity so status COLOR is never animated decoration (CO-4). */
export async function refreshFlash(targets: Element | Element[]) {
  if (prefersReducedMotion()) return;
  const { animate } = await loadAnime();
  animate(targets, {
    opacity: [
      { to: 0.35, duration: DUR_1, ease: EASE_LINEAR },
      { to: 1, duration: DUR_3 - DUR_1, ease: EASE_STANDARD },
    ],
  });
}

/**
 * Row-enter stagger with the brief's caps: first 8 items, 40-60 ms
 * inter-item, sequence <=600 ms; the remainder appears with the last
 * (they are simply not animated — visible immediately). Log lines are
 * NEVER passed here (NO-12); callers own that discipline and the
 * design-gate suite greps for violations.
 */
export async function staggerRowsIn(rows: Element[], perItemMs?: number) {
  if (rows.length === 0) return;
  if (prefersReducedMotion()) return;
  const { animate, stagger } = await loadAnime();
  const { perItemMs: ms, animatedCount } = clampStagger(rows.length, perItemMs);
  animate(rows.slice(0, animatedCount), {
    opacity: { from: 0, to: 1 },
    translateY: { from: 6, to: 0 },
    duration: DUR_2,
    delay: stagger(ms),
    ease: EASE_STANDARD,
  });
}

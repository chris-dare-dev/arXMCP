/**
 * Motion tokens — the normative value set from design-system-brief.md
 * §5.1, mirrored from tokens.css so JS-driven motion (anime.js v4)
 * uses the exact same vocabulary as CSS transitions.
 *
 * Hard rules NO-9..NO-18 (brief §6.3) that bind this module:
 *  - NO-10  no autonomous camera; camera moves only on user action,
 *           <=DUR_4, never loops.
 *  - NO-11  no perpetual simulation; cool-down <=3 s then freeze.
 *  - NO-12  no per-log-line motion; no smooth-scroll log follow.
 *  - NO-14  nothing animates alongside a focused log stream.
 *  - NO-15  no eager 3D init (lazy-import + IntersectionObserver).
 *  - NO-17  no spring/overshoot on data or the 3D camera.
 * (NO-9/13/16/18 constrain the 3D surfaces that land with WS-A A5;
 * they are recorded here so the wrapper API never grows past them.)
 */

/** hover, focus, press, tooltip */
export const DUR_1 = 100;
/** swaps, crossfades, row enter/exit — matches the shipped console */
export const DUR_2 = 200;
/** panel/drawer entry, refresh flash — matches the shipped console */
export const DUR_3 = 400;
/** 3D camera tweens ONLY — never DOM (NO-17 / M2 exemption) */
export const DUR_4 = 800;

/** decelerate; entrances */
export const EASE_STANDARD = "cubicBezier(0.2, 0, 0, 1)";
/** accelerate; exits */
export const EASE_EXIT = "cubicBezier(0.4, 0, 1, 1)";
/** spinners/progress ONLY */
export const EASE_LINEAR = "linear";

/** rows/cards inter-item stagger band (ms) */
export const STAGGER_MIN_MS = 40;
export const STAGGER_MAX_MS = 60;
/** stagger only the first N items; the remainder appears with the last */
export const STAGGER_MAX_ITEMS = 8;
/** total stagger sequence cap (ms) */
export const STAGGER_TOTAL_MAX_MS = 600;
/** graph node cascades: stagger(15, from:'center') capped at 20 nodes */
export const GRAPH_STAGGER_MS = 15;
export const GRAPH_STAGGER_MAX_NODES = 20;

/**
 * Spring (anime.js createSpring): reserved for direct-manipulation
 * release ONLY (drag-end snap). Springs never animate numbers, badges,
 * logs, or the 3D camera (MOT-NO-1, NO-17). Settle <=400 ms,
 * overshoot <=2%.
 */
export const SPRING_RELEASE = { stiffness: 300, damping: 28, mass: 1 } as const;

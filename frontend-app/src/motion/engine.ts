/**
 * Static re-export of the EXACT animejs v4 subset the wrappers use.
 * anime.ts dynamic-imports THIS module (not the package): a namespace
 * import of "animejs" would retain every export and blow the <=15 kB
 * gzip motion-engine budget; re-exporting named symbols lets Rollup
 * tree-shake the engine down to what the wrapper API actually needs.
 * Add exports here ONLY alongside a wrapper that enforces the brief's
 * caps (no generic passthrough).
 */
// createSpring is deliberately NOT exported yet: springs are reserved
// for direct-manipulation release (drag-end snap) and no M0 surface
// drags. Export it together with the capped release wrapper when one
// does — its solver costs ~1 kB gzip and M0 has no legitimate caller.
export { animate, stagger } from "animejs";

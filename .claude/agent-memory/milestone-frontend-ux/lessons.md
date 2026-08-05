# milestone-frontend-ux — lessons

Append-only. One line per run: `YYYY-MM-DD | <milestone-id> | <lesson>`.

[CONFIRMED] 2026-08-04 | ui-uplift-m7 | An absolute `font-size` on an element-level rule (`code, time`) silently overrides every inherited heading size — check each element rule against every context it can nest inside, especially headings, before trusting a type scale's hierarchy claim.

2026-08-04 | ui-uplift-m10 | Minting a token without migrating the hand-typed values it replaces is a coherence REGRESSION, not a fix — the new token lands beside the old literals and the two diverge in the non-default mode (dark `--fg-muted` #9fa4a8 vs the un-migrated `.card .hint` #b3b9c0, same card, three lines apart). Recompute the new value against every un-migrated neighbour in BOTH modes before accepting a "coherence" claim.

2026-08-05 | ui-uplift-m12 | A disclosure is only as honest as its CLOSED state at every reachable moment, not at first paint: an `open` predicate evaluated server-side cannot re-open a region the operator collapsed, so any polled status or error surface nested inside one must push its state OUT to the always-rendered `<summary>` (an `hx-swap-oob` cue) or live outside the disclosure entirely. Check the collapse-mid-operation path before accepting a forced-open predicate as the mitigation.

2026-08-04 | ui-uplift-m8 | Deleting a grouping primitive only separates; it does not rank. One rule weight applied to every top-level boundary leaves the page as uniform as the identical boxes it replaced — when a milestone authors a per-site semantic distinction (section vs div), check that the distinction renders in at least one channel a reader uses, or it is documentation, not design.

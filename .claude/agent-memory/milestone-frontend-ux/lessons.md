# milestone-frontend-ux — lessons

Append-only. One line per run: `YYYY-MM-DD | <milestone-id> | <lesson>`.

2026-08-04 | ui-uplift-m7 | An absolute `font-size` on an element-level rule (`code, time`) silently overrides every inherited heading size — check each element rule against every context it can nest inside, especially headings, before trusting a type scale's hierarchy claim.

2026-08-04 | ui-uplift-m10 | Minting a token without migrating the hand-typed values it replaces is a coherence REGRESSION, not a fix — the new token lands beside the old literals and the two diverge in the non-default mode (dark `--fg-muted` #9fa4a8 vs the un-migrated `.card .hint` #b3b9c0, same card, three lines apart). Recompute the new value against every un-migrated neighbour in BOTH modes before accepting a "coherence" claim.

# Critique — proof-verify-handler-wiring-m2 (merged)

**Critics fired:** adversary (1; infra-safety / oss-scout / frontend-UX
did not fire — no infra paths in diff, no OSS-scout opt-in, no frontend
exists by design).

**Verdict:** SHIP-WITH-FIXES (adversary).

## Findings summary

| ID | Sev | Source | Title | Phase-4 status |
|---|---|---|---|---|
| F1 | HIGH | adversary | Tier-1/Tier-2 cache-hit re-stamp path has zero test coverage | CLOSED — new `TestFiltersAppliedHitPathRestamp` class (5 tests) wired through a `_FakeCache` fixture |
| F2 | HIGH | adversary | Miss path STORES `filters_applied` in cached payload, contradicting helper docstring | CLOSED — Option A: `_inject_filters_applied` returns a shallow-copy (never mutates); miss-path stamp moved AFTER `cache.store_search`; `_restamp_degraded` strips any stale `filters_applied` defensively |
| F3 | MEDIUM | adversary | CHANGES.md claims BP1 hash re-pinned but it was not | CLOSED — corrected the `## Unreleased` entry to match reality + cite the F6 contract |
| F4 | MEDIUM | adversary | implementation-summary cites two non-existent test names | CLOSED — renamed citation to `test_unsupported_keys_excluded_from_echo`; replaced fictitious cache-hit-test name with the real `TestFiltersAppliedHitPathRestamp` trio |
| F5 | MEDIUM | adversary | `_canonicalize_filters` does not dedupe `paper_id` (synthesis claims "deduped") | CLOSED — added `sorted(dict.fromkeys(pid))`; new `TestCanonicalizeFiltersDedup` (4 tests) |
| F6 | MEDIUM | adversary | Synthesis D2 claim about BP1 + production-mode `_meta` risk not contract-documented | CLOSED — added a `register_all` block comment documenting the `_meta`-strip contract; CHANGES.md and the F3 closure both cite it |
| F7 | LOW | adversary | `filters_applied` schema is loose (`type: object`, no `properties`) | **DEFERRED** — tightening the schema would force a v9→v10 bump + hash re-pin; defer to a milestone that touches the schema for other reasons (likely the deferred `degraded`/`degraded_reasons` companion fix). Today the helper enforces shape by construction. |
| F8 | LOW | adversary | Deferred `degraded`/`degraded_reasons` schema gap is real and reachable | **DEFERRED** — pre-existing, explicitly out of m2 scope per synthesis Disagreement #3. Will be picked up by a follow-up `chore(server): close pre-existing degraded/degraded_reasons schema gap` milestone. |

**Rectification commits (Phase 4):** one `rect(server)` commit closing
F1–F6; followed by the standard `chore(notes)` finalize.

## Rectification artifacts

- `server/handlers/search.py` — F2 strip-then-re-add (helper now
  shallow-copies; miss-path stamp moved post-store;
  `_restamp_degraded` defensively pops `filters_applied`); F5 dedup
  in `_canonicalize_filters`.
- `server/tools.py` — F6 contract comment in `register_all` documenting
  the orchestrator's `_meta`-strip requirement to preserve BP1.
- `tests/test_search_filter.py` — F1 `TestFiltersAppliedHitPathRestamp`
  (5 tests, with `fake_resources_with_cache` + `_FakeCache` fixtures);
  F5 `TestCanonicalizeFiltersDedup` (4 tests).
- `CHANGES.md` — F3 corrected the BP1 re-pin claim; F4-aligned test-name
  citation.
- `.claude/notes/milestones/proof-verify-handler-wiring-m2/implementation-summary.md`
  — F4 test-name citations corrected; AC #6 reworded to credit the
  rect for closing the cache-hit coverage gap.

## Final test count

`make test`: 2259 passed, 9 skipped, 1 xfailed.
Net delta from pre-m2 baseline: +21 tests (+12 from m2 feat, +9 from
m2 rect closing F1+F5). Ruff clean.

## Deferred findings

- **F7** — tighten `filters_applied` schema (`additionalProperties:
  false`, `properties.paper_id: {type: array, items: {type: string}}`).
  Defer because closing it forces another schema-version bump + hash
  re-pin; better folded into a future milestone that touches the
  schema for other reasons.
- **F8** — close pre-existing `degraded` / `degraded_reasons` schema
  gap. Pre-existing across v8 and v9; explicitly deferred at synthesis
  Disagreement #3 to keep m2 minimal. Tracked for a follow-up chore.

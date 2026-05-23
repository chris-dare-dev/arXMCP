# Critique (merged) — parser-fidelity-eval-m1

**Critics fired:** 1 (adversary). Infra-safety did NOT fire (no
files matched `infra/`, `.github/workflows/`, `Dockerfile`,
`docker-compose*`, or `Makefile` in the implementation commit
range). OSS-scout did NOT fire (opt-in only; no explicit request,
research synthesis did not flag the milestone as an active research
area).

**Verdict:** SHIP-WITH-FIXES (adversary).

---

## Executive summary (cross-critic)

Single critic, so the cross-critic dedupe is trivial. The adversary
returned 0 CRITICAL, 2 HIGH, 6 MEDIUM, 3 LOW. All 8 HIGH+MEDIUM
findings were addressed in the Phase-4 rectification commit; F11
(LOW) was deferred. Test count delta from rectification: +9
regression tests (2702 → 2711), no pre-existing regressions.

The two HIGH findings were both load-bearing:
- **F1** (cost-matrix ordering normalization) — would have biased
  every CDM score downward, undermining the gate's calibration.
- **F2** (sandbox doc factually wrong about `\openout` / `\input`
  mitigations) — would have propagated false security claims into
  the Threat-3 peer reference doc.

Both closed via the recommended ordering (F1 first to make the
math right, then F2 to land the doc + env-var plumbing together).

## Per-finding status

See [`critique-adversary.md`](critique-adversary.md) for the full
finding bodies + per-finding closure notes. Summary:

| ID | Severity | Status |
|---|---|---|
| F1 | HIGH | CLOSED (ordering-cost normalization + regression test) |
| F2 | HIGH | CLOSED (sandbox doc + env-var plumbing + doc snippet) |
| F3 | MEDIUM | CLOSED (`AggregateResult` dataclass + failure tracking + 2 tests) |
| F4 | MEDIUM | CLOSED (README/manifest honesty + `TestFixtureShape` enforcement) |
| F5 | MEDIUM | CLOSED (`-halt-on-error` argv + doc update) |
| F6 | MEDIUM | CLOSED (drain-pipe pattern; matches LaTeXML precedent) |
| F7 | MEDIUM | CLOSED (lazy string-condition skipif) |
| F8 | MEDIUM | CLOSED (README rubric labeled arXMCP-chosen) |
| F9 | LOW | CLOSED (dead-code branch removed + ternary) |
| F10 | LOW | CLOSED (unicode caveat in docstring + 3 tests) |
| F11 | LOW | DEFERRED (kpsewhich check; bites only on thin texlive installs) |

## Critic activation matrix

| Critic | Fired? | Why / why not |
|---|---|---|
| adversary | YES | Always fires per `.claude/agents/milestone-adversary.md`. |
| infra-safety | NO | Conditional on `infra/`, workflows, Dockerfile, compose, or Makefile changes. None present in this milestone (purely `tools/`, `tests/`, `.claude/docs/`, `pyproject.toml`, top-level docs). |
| oss-scout | NO | Opt-in only. Research synthesis flagged the CDM paper (arXiv:2409.03643) as an active-research area but the operator did not explicitly request the scout, and the milestone scope was deliberately narrow (no upstream-import work — design-pattern lift only per CLAUDE.md §4.7). |

## What's next

Phase 4 (this rectification) writes the rect commit + advances state
to `complete`. The `chore(notes)` state-finalization commit closes
the milestone. Optional push to origin/main is per-event-authorized
per CLAUDE.md §4.4 — the orchestrator surfaces the option after
state reaches `complete`.

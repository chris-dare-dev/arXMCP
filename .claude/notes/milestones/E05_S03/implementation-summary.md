# E05_S03 Implementation Summary

**Branch:** `claude/gallant-blackburn-b89422`
**Files changed:** 3 (1 new, 2 modified)
**Commit (planned):** see Phase 4 footer once committed.

## Files

| Path | New / Modified | Purpose |
|---|---|---|
| `TIER-GATES.md` | NEW | Root-level authoritative tier-promotion conditions. Verbatim AC sentence about reranker activation. Behavior matrix (pass / fail / SKIP). Operator prerequisite checklist. History note explicitly retiring E01_S10. |
| `Makefile` | modified | `make eval` target — Python version guard + `pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.70`. `help:` updated. `.PHONY` updated. |
| `README.md` | modified | New "Tier exit gates" section between "Hard constraints" and "Quick start"; `make eval` row added to Quick start code block. |

No new dependencies. No edits to `tests/`, `.claude/roadmap/`, or
`.claude/notes/` (the roadmap README already references `TIER-GATES.md`
by name; the SUPERSEDED `09-feature-priorities.md` is intentionally
left alone per its banner).

## Decisions exercised from research-brief-1.md

| Decision | Where it landed |
|---|---|
| (a) README link goes in a NEW `## Tier exit gates` section between Hard constraints and Quick start | `README.md:42-45` |
| (b) `make eval` mirrors `make test` style: Python version guard + pytest one-liner; no echo header | `Makefile:eval` target |
| (c) Expected output documented as fenced code blocks per gate (pass / fail / SKIP) | `TIER-GATES.md` § "Tier-0 → Tier-1 gate" |
| (d) Cold-start SKIP behavior documented inline; "skip is NOT a pass for promotion" called out explicitly | `TIER-GATES.md` § "Expected output — SKIP" |
| (e) E01_S10 retirement: `.claude/roadmap/E01-shipped.md` already retires it in prose; `TIER-GATES.md` adds a "History" section as the single landing page | `TIER-GATES.md` § "History" |

## Verification

- `make eval` runs `pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.70` and reports `1 skipped in N.NNs` on cold-start (exit 0). The test SKIPS because the seed corpus has not been ingested and the fixture is empty — both per E05_S01 / E05_S02 design.
- `make help` lists `make eval` with a one-line description.
- `make test` is unchanged — `ruff check . && pytest` — still 579 passed, 3 skipped, ruff clean.

## Acceptance-criteria mapping

All 5 ACs are met by the shipped files:

| AC | Status | Where verified |
|---|---|---|
| `TIER-GATES.md` exists at repo root and defines all four tier transitions with exact pytest commands | **met** | `TIER-GATES.md` § "The gates" + § "Tier-0 → Tier-1 gate" + § "Tier-1 → Tier-2 gate" + § "Tier-2 → Tier-3" + § "Tier-5 cutover" |
| `make eval` runs `pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.70` | **met** | `Makefile:eval` target, verified by `make eval` invocation above |
| `TIER-GATES.md` states: "Reranker activation in E07 is conditional on nDCG@5 ≥ 0.80 after BM25 hybrid is active." | **met** | `TIER-GATES.md`, the bold sentence right under the gates table — verbatim |
| Root `README.md` links to `TIER-GATES.md` | **met** | `README.md:44` (the prose link) plus the Quick-start code block reference |
| No subjective acceptance criteria | **met** | TIER-GATES.md uses only command-output and numerical conditions; no "demo transcript" / "looks coherent" language anywhere |

## Notable design choices for the critic

- **`TIER-GATES.md` lives at repo root, not `docs/`.** Per the brief verbatim: "ships a `TIER-GATES.md` file in the root of the repository (not in `.claude/`)." Root placement signals top-level governance, not narrow eval docs. Sibling files at root: `README.md`, `ROADMAP.md`, `Makefile`, `pyproject.toml`.

- **README link uses both prose and a Quick-start row.** Prose is for first-time orientation (the link is visible above the fold); the Quick-start row is for muscle memory ("how do I run the gate" → `make eval`).

- **`make eval` does NOT echo a header.** Mirrors `make test` style — no double-printing of the "what passing looks like" text. The expected-output documentation lives in `TIER-GATES.md` only.

- **Python version guard on `make eval`.** Mirrors `make test` discipline. A user on stale Python gets the same fast-fail message they get from `make test`, not a confusing pytest stack trace.

- **The reranker-activation sentence appears verbatim per AC.** The exact phrasing — "Reranker activation in E07 is conditional on nDCG@5 ≥ 0.80 after BM25 hybrid is active." — is bolded under the gates table. AC enforcement is a literal-string match.

- **The SKIP-is-not-a-pass invariant gets its own subsection.** E05_S02's test SKIPS on cold-start (no corpus, empty fixture, missing deps). Without this section, an operator could see `1 skipped in 0.19s` and falsely promote. The "Expected output — SKIP" subsection makes the false-green failure mode impossible to miss.

- **Operator prerequisite checklist is explicit.** Before declaring Tier-0 done, the operator checks: (1) fixture validator passes, (2) corpus is ingested (4 sub-steps), (3) `make eval` reports `1 passed`. This is the human-process side of the otherwise machine-checkable gate.

- **History section retires E01_S10 once.** The roadmap already retires E01_S10 in `.claude/roadmap/E01-shipped.md`. `TIER-GATES.md` adds one short paragraph at the bottom so a future reader Ctrl-F'ing for "vibes-check" lands here.

- **Tier-3 → Tier-4 and Tier-4 → Tier-5 are explicitly NOT in the table.** They are scope cutovers, not metric gates. Mentioning them as "no quantitative gate" prevents future readers from inferring an unspecified one.

## Out-of-scope (deferred per brief)

- Implementing Tier-1+ gates (E07_S04, E08, E11_S05).
- Owner sign-off mechanism (the brief calls for a human review; no code automates that).

## External writes

**None.** All deliverables are local commits. No git push, no PR
creation, no infra mutation, no third-party API call.

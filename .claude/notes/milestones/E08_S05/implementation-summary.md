# E08_S05 — Implementation summary

## What shipped

Three new files, no modifications to existing files. The milestone
is primarily a configuration + documentation freeze of the v1 model
policy.

| Path | Status | Purpose |
|---|---|---|
| `server/orchestrator/model_selector.py` | NEW (~225 LOC) | `select_model(route_tag, turn_type) -> str` lookup function over a `MappingProxyType`-wrapped 12-cell table; `TurnType` `StrEnum` (3 values); `MODEL_HAIKU_4_5` / `MODEL_SONNET_4_6` constants; import-time invariants (closed-at-(4×3) totality + whitelist-only model IDs) using `if … raise RuntimeError(…)` so they survive `python -O`. |
| `docs/model-policy.md` | NEW (~140 lines) | Selection table; the verbatim "Verifier pass: dropped and why" section title (AC #5); Opus 4.7 deferral rationale; per-query token-budget estimates citing $1/$5 (Haiku) vs $3/$15 (Sonnet) MTok rates; cross-references to `.claude/notes/01,07-*.md` and H10. |
| `tests/test_model_selector.py` | NEW (~290 LOC) | 40 tests across 9 classes: 3 AC-explicit lookups, forbidden-string scan over `server/**/*.py`, doc-section presence check, table totality (parametrized 4×3 = 12), default-is-Haiku invariants, Verification ↔ Autoformalization parity, model ID format pinning, TurnType-closed-at-three, import-time-invariant-survives-`-O` regression. |

Total: 40 new tests pass; full project suite **1171 passed, 4 skipped, 0 failed** (was 1131); `ruff check .` clean.

## How acceptance criteria are met

| AC | Where it's enforced |
|---|---|
| `select_model(AUTOFORMALIZATION, LEAN_WRITE) == "claude-sonnet-4-6"` (corrected) | `tests/test_model_selector.py::TestACSelections::test_autoformalization_lean_write_returns_sonnet` |
| `select_model(SYNTHESIS, RETRIEVAL) == "claude-haiku-4-5"` | `tests/test_model_selector.py::TestACSelections::test_synthesis_retrieval_returns_haiku` |
| `select_model(VERIFICATION, DRAFT) == "claude-haiku-4-5"` (Verification → Autoformalizer path) | `tests/test_model_selector.py::TestACSelections::test_verification_draft_returns_haiku` + `TestVerificationMirrorsAutoformalization` (parametrized over every TurnType) |
| The string `"claude-opus"` does not appear anywhere in `server/` source files | `tests/test_model_selector.py::TestForbiddenStrings::test_no_claude_opus_in_server_python_files` walks `server/**/*.py` (excluding `__pycache__`) and asserts zero occurrences. The Opus deferral rationale is in `docs/model-policy.md` (where the string IS allowed). |
| `docs/model-policy.md` includes a section titled "Verifier pass: dropped and why" | `tests/test_model_selector.py::TestPolicyDoc::test_policy_doc_contains_verifier_pass_section_title` does both a markdown-heading regex match AND a fall-back substring check on the byte-exact title. |
| `pytest tests/test_model_selector.py` passes | 40 tests pass in 0.17s. |

## Design choices made (with rationale anchored to research synthesis)

- **`TurnType` defined in `model_selector.py`** with exactly three values per D1 — no `CONTEXT_ASSEMBLY`; the orchestrator's caller picks RETRIEVAL or DRAFT for context-assembly turns.
- **Model IDs as alias forms** (`claude-haiku-4-5`, `claude-sonnet-4-6`) per D2 — matches AC text; pinned snapshot for Haiku (`claude-haiku-4-5-20251001`) documented in a comment.
- **VERIFICATION mirrors AUTOFORMALIZATION** in the lookup table per D3 — implements the "Verification queries route to Autoformalizer execution" decision at the model-selector level. The router and prompts module retain Verification as a valid RouteTag for classification + BP1 byte-identity.
- **Default is Haiku; Sonnet is the exception** per D4 — Sonnet is used ONLY for `(AUTOFORMALIZATION|VERIFICATION, LEAN_WRITE)`. All other 10 cells are Haiku.
- **Unknown pair raises `ValueError`** per D5 — defensive; silent fallback to Haiku would mask a future enum extension that forgot to update the table.
- **Closed-at-(4×3) import-time invariant via `if … raise RuntimeError`** per D6 — mirrors the F4 fix from E08_S02; survives `python -O`. There's also a whitelist-only check on the table values so a future typo introducing a third model ID is caught at import.
- **Forbidden-string test grep over `server/**/*.py`** per D7 — catches the constant case AND any stray docstring/comment occurrence. (The implementation iteration caught my own docstring text — refactored to "Opus API ID" so the test passes.)
- **`docs/model-policy.md` carries** the byte-exact AC #5 section title + the Opus deferral rationale + per-query cost estimates + a Haiku-2048-token-cache caveat from `07-multi-agent-caching.md`.

## Deviations from the brief

None of significance. Two small clarifications worth noting:

- The brief's AC #1 reads: *"`select_model(RouteTag.AUTOFORMALIZATION, TurnType.LEAN_WRITE)` returns `"claude-haiku-4-5"` — wait, correction: returns `"claude-sonnet-4-6"`"*. I implemented and tested for the corrected expectation (`claude-sonnet-4-6`); the in-line "wait, correction" wording in the brief was a brief-author edit-mark.
- `RouteTag.LOOKUP` and `RouteTag.SYNTHESIS` shouldn't ever produce a `LEAN_WRITE` turn in practice (they don't generate Lean code), but the table has entries for those pairs anyway (returning Haiku) so the totality invariant holds. This is defensive completeness rather than a real use case.

## Failure-mode discipline

- **Selection table TOTAL** — every (RouteTag, TurnType) cross-product has an entry. Adding a new RouteTag or TurnType without updating the table raises `RuntimeError` at import time (caught by the closed-at-N check + the regression test in `TestClosedAtNInvariantSurvivesDashO`).
- **Whitelist-only model IDs** — the table values must be one of the two exported constants. A future typo introducing `"claude-haiku-4-7"` (a Haiku that doesn't exist as of v1) is caught at import time.
- **No silent fallback** — `select_model(unknown_route_tag, ...)` raises `ValueError`, not "default to Haiku". Defensive.

## External writes performed

None. All deliverables are local source files + tests + docs:
- 3 new files
- 0 modified files
- 0 git pushes, 0 PRs, 0 third-party API calls
- 0 new runtime deps (pure stdlib: `enum`, `types`, `collections.abc`)

## Files for the critic to focus on

- `server/orchestrator/model_selector.py:88-128` — the 12-cell selection table; verify (a) every cell is filled, (b) only Haiku and Sonnet appear, (c) `(VERIFICATION, X)` matches `(AUTOFORMALIZATION, X)` for every `X`
- `server/orchestrator/model_selector.py:177-220` — the closed-at-N + whitelist-only import-time invariants
- `tests/test_model_selector.py::TestForbiddenStrings::test_no_claude_opus_in_server_python_files` — verify the walker correctly handles every Python file under `server/` (subdirectories like `orchestrator/`, `routes/`, `handlers/`, `retrieval/`)
- `docs/model-policy.md::Verifier pass: dropped and why` — verify the section title is byte-exact and the rationale is sound

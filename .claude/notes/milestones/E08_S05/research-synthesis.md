# E08_S05 — Research synthesis (single-researcher mode)

## Load-bearing facts

1. **`server/orchestrator/` package exists** (E08_S04 just landed). Currently contains `__init__.py`, `id_canon.py`, and the `test_id_canon.py` re-export stub. `model_selector.py` is the new file E08_S05 ships into the same package.

2. **`server/router.py::RouteTag` is a `StrEnum`** with exactly four values: `LOOKUP`, `SYNTHESIS`, `VERIFICATION`, `AUTOFORMALIZATION`. Its docstring explicitly anticipates this milestone: *"adding a fifth value requires coordination with E08_S02 (role prefixes) and E08_S05 (model selection)."* Both invariants ("exactly 4") will be re-asserted in `model_selector.py`.

3. **`server/prompts.py` keeps `_VERIFICATION_PREFIX`** even after the verifier-pass drop. The role prefix is required by BP1 byte-identity (closed-at-four invariant); the *execution* dispatch (Verification queries → Autoformalizer behavior) happens at the model-selector / orchestrator layer. The two concerns are cleanly separated.

4. **`grep -rn "claude-opus\|claude-sonnet\|claude-haiku" server/` returns ZERO hits** today. AC #4 (no `"claude-opus"` in `server/`) is currently trivially satisfied and must remain so post-implementation.

5. **Model ID format**: use the dateless aliases `claude-haiku-4-5` and `claude-sonnet-4-6`. Per the researcher's check against Anthropic's May-2026 docs, `claude-sonnet-4-6` is dateless-pinned (no suffix). `claude-haiku-4-5` is an alias for `claude-haiku-4-5-20251001` — we use the alias to match AC text and the E14 roadmap references; the pinned form is documented in a comment.

6. **Pytest discovery**: `pyproject.toml` has `testpaths = ["tests"]`. Place the test at `tests/test_model_selector.py` (matches project convention; brief says the same).

7. **No new runtime deps.** The function is a pure lookup; `select_model` makes no network calls.

## Decisions for the implementer

| ID | Decision | Rationale |
|---|---|---|
| D1 | **`TurnType` as `StrEnum` in `server/orchestrator/model_selector.py`** with exactly three values: `RETRIEVAL`, `DRAFT`, `LEAN_WRITE`. No `CONTEXT_ASSEMBLY` value (the brief mentions it but maps it semantically to RETRIEVAL or DRAFT — let the orchestrator pick which TurnType to pass; `model_selector` doesn't differentiate). | Brief's ACs exercise these three values exactly. Adding a fourth invites scope creep. |
| D2 | **Model ID constants**: `MODEL_HAIKU_4_5 = "claude-haiku-4-5"`, `MODEL_SONNET_4_6 = "claude-sonnet-4-6"`. **NO `MODEL_OPUS_*` constant** (would violate AC #4). The pinned snapshot ID for Haiku (`claude-haiku-4-5-20251001`) lives in a comment, not as a constant. | AC text uses the alias forms. Project E14 metrics labels also use the alias. The pinned snapshot is documented for ops audit purposes. |
| D3 | **`select_model(route_tag, turn_type)` is a pure lookup** over a `Mapping[(RouteTag, TurnType), str]` constant. **VERIFICATION is treated identically to AUTOFORMALIZATION** in the table — same Haiku/Sonnet rules. This implements the "Verification queries route to Autoformalizer execution" decision at the dispatch point. | Researcher Q3: AC #3 says `(VERIFICATION, DRAFT) → Haiku`; treating VERIFICATION as an AUTOFORMALIZATION alias makes `(VERIFICATION, LEAN_WRITE) → Sonnet` consistent. |
| D4 | **Default is Haiku.** LOOKUP / SYNTHESIS / VERIFICATION / AUTOFORMALIZATION × RETRIEVAL or DRAFT all return Haiku. Sonnet is the EXCEPTION, used only for `(AUTOFORMALIZATION, LEAN_WRITE)` and `(VERIFICATION, LEAN_WRITE)`. | Brief: "Claude Sonnet 4.6: used ONLY for the Autoformalizer role's Lean-syntax write step." |
| D5 | **Unknown `(RouteTag, TurnType)` raises `ValueError`** with the offending pair in the message. The lookup table is total over the cross product (4 × 3 = 12 pairs); a missing key signals a bug, not a fallback to Haiku. | Defense-in-depth — silent fallback to Haiku would mask a future RouteTag/TurnType extension that forgot to extend the table. |
| D6 | **Closed-at-four / closed-at-three import-time assert**, mirroring `server/prompts.py`'s pattern. If a future contributor adds a fifth `RouteTag` (or fourth `TurnType`) without extending the table, the import raises `RuntimeError` loudly. **Use `if … raise RuntimeError(…)`, NOT `assert`** (the F4 fix from E08_S02 — `assert` is stripped under `python -O`). | Defense in depth; matches the established pattern. |
| D7 | **Forbidden-string test** at `tests/test_model_selector.py`: walk every `*.py` file under `server/` and assert no occurrence of `"claude-opus"`. Mirrors the AST-literal-only check pattern in `tests/test_prompts.py` (in spirit). The walk excludes `__pycache__`. | AC #4 verbatim. Catches both the constant-name case (`OPUS = "claude-opus..."`) and any stray comment. |
| D8 | **`docs/model-policy.md` carries**: (a) the model selection table (RouteTag × TurnType → model ID); (b) a section titled exactly *"Verifier pass: dropped and why"* (AC #5 verbatim); (c) the Opus 4.7 deferral rationale citing the 35% tokenizer expansion; (d) the Haiku 2048-token min cacheable prefix caveat from `07-multi-agent-caching.md`; (e) cross-references to `server/orchestrator/model_selector.py`, `server/router.py`, the brief, and H10. | AC #5 is byte-exact for the section title; the rest is supporting structure. |
| D9 | **Token-budget estimates section** in the doc: rough per-query-type cost using the published $1/$5 (Haiku) and $3/$15 (Sonnet) MTok rates. A 4-agent fan-out averaging 2K input / 0.5K output tokens per turn × 4 agents × 3 turns each = 24K input + 6K output total. At Haiku rates: $0.024 + $0.030 = $0.054/query. The Sonnet LEAN_WRITE turn (when present) adds ~$0.020. | Operational telemetry for ops; matches the brief's "token-budget estimates per query type" deliverable. |
| D10 | **Test classes** mirror the `tests/test_id_canon.py` shape: one per AC + a `TestForbiddenStrings` class for the AC #4 grep + a `TestClosedAtFourInvariant` test ensuring the table covers every RouteTag × TurnType pair. Optional: a `TestModelIdFormat` class that pins the model ID strings against accidental edits. | Project test-class convention. |

## D-Files: complete file list

- **NEW**: `server/orchestrator/model_selector.py` (~110 LOC) — `TurnType` enum, model ID constants, `select_model` function, import-time invariants
- **NEW**: `docs/model-policy.md` (~140 lines) — policy doc with required section title
- **NEW**: `tests/test_model_selector.py` (~180 LOC) — AC tests + forbidden-string check + table completeness check

NO modifications to existing files. NO new runtime deps. NO changes to `server/prompts.py`, `server/router.py`, or anything else.

## Open questions resolved by the synthesis

1. ~~Model ID alias vs pinned~~ — D2 (use alias; document pinned in comment).
2. ~~TurnType values~~ — D1 (exactly three: RETRIEVAL, DRAFT, LEAN_WRITE).
3. ~~`select_model(VERIFICATION, LEAN_WRITE)`~~ — D3 (treat VERIFICATION identically to AUTOFORMALIZATION; LEAN_WRITE → Sonnet).
4. ~~Where TurnType lives~~ — D1 (in `model_selector.py`).
5. ~~Haiku 2048-token caveat~~ — D8 (documented in policy doc).
6. ~~`docs/` directory exists?~~ — yes, E08_S04 created `docs/orchestrator-rules.md`.

## External writes the implementation will require

None. All deliverables are local source files + tests + docs. NO git push, NO PR, NO third-party API call, NO infra mutation, NO new runtime deps. The implementation is essentially a 12-cell lookup table + a doc + a test grep.

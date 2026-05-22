# Research Brief — verification-feedback-m3

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-22T00:00:00Z

## In-codebase context

**Touchpoints (where the new tool plugs in).** Six edit sites; the milestone
brief is faithful.

1. `server/handlers/lean_verify.py` — NEW. Single async handler
   `handle_lean_verify(snippet, imports, mode)` returning a dict envelope.
   Mirror the m1 template `server/handlers/citations.py`:
   - Pydantic `Annotated[..., Field(...)]` typing on inputs.
   - First-line input validation (raise `ValueError` for bad input — citations
     validates `chunk_id` via `is_valid_chunk_id` BEFORE touching `get_resources()`).
   - Wrap the return in `envelope(...)` from `server.tools` so
     `corpus_version` is injected + keys are sorted (BP1 byte-stability).
2. `server/tools.py::ALL_TOOLS` — add a new frozen `ToolMeta` constant
   (`LEAN_VERIFY = ToolMeta(name="lean_verify", description=...)`); append to
   the `ALL_TOOLS` tuple **at the end** (the byte-stability test pins
   ordering via `register_all`'s handler_by_name dict iterating `ALL_TOOLS`).
   Add to `handler_by_name` inside `register_all`. Bump
   `TOOL_SCHEMA_VERSION` from 11 → 12 (the `v12:` comment goes at the top of
   the run of `v<N>:` block-comments documenting each bump).
3. `server/handlers/__init__.py` — re-export (existing handlers do this for
   discoverability; check the file).
4. `server/schemas/lean_verify_result.json` — NEW frozen result-row schema
   (mirror `server/schemas/search_papers_result.json`). MUST carry a
   top-level `"version"` field equal to `TOOL_SCHEMA_VERSION` (= 12);
   that cross-check is pinned by
   `tests/test_snippet_contract.py::TestSchemaVersionPin`.
   Schema fields verbatim from the milestone brief:
   `{status, messages:[{severity,position,text}], proof_state,
   goals_remaining, sorry_goals, compilation_success}`. `additionalProperties:
   false` and a closed `required` list mirroring the search-papers schema.
5. `tests/test_server_tool_schema.py` — `EXPECTED_TOOL_SCHEMA_SHA256` is
   re-pinned by running:
   ```
   uv run python -m pytest tests/test_server_tool_schema.py --update-tool-schema-hash
   ```
   The flag refuses to run unless `TOOL_SCHEMA_VERSION` was bumped first (the
   F2 anti-decorative-version guard at lines 367-382). So bump 11→12
   BEFORE running the update flag.
6. `tests/test_handlers_lean_verify.py` — NEW. Tier-1 always-run tests with a
   fake LeanRepl (the m2 critique's F2 close created a `_FakeProc` pattern at
   `tests/test_lean_repl.py:TestFakeProcRoundTrips` — port that pattern).
   Tier-2 `@pytest.mark.requires_lean_repl` for the three acceptance
   scenarios (type error, sorry, syntax_only short-circuit) and the
   RLIMIT_AS memory-cap assertion.

**The m2 LeanRepl.query response shape — verbatim from spike-2.**
Confirmed by `.claude/notes/spikes/verification-feedback-spike-2.md` and the
real-Lean tests at `tests/test_lean_repl.py:TestRealLeanRepl`:

| Case | Response keys | Notes |
|---|---|---|
| ok | `{"env": <int>}` | no `messages` key on a clean theorem |
| compile-error | `{"messages": [...], "env": <int>}` | each msg has `severity`, `pos`, `data` |
| sorry-goal | `{"env", "messages", "sorries": [{"goal": "..."}]}` | `goal` is a `"hypotheses\n⊢ conclusion"` string |

**Mapping to the m3 result schema.**
- `status` → derive: `"ok"` if no error-severity messages and no sorries;
  `"error"` if any `severity == "error"`; `"sorry"` if `sorries` is non-empty
  (precedence: `error` > `sorry` > `ok` — a snippet can have both, the agent
  needs the error first).
- `messages: [{severity, position, text}]` → map directly from the REPL's
  `messages[]`. REPL key is `pos` (object with `line`/`column`); rename
  `pos → position`. REPL key is `data` (string) → rename `data → text`. Keep
  `severity` verbatim (`error`/`warning`/`info`).
- `proof_state` → the `sorries[0].goal` string when present, else `null`.
- `goals_remaining` → a `list[str]` of `sorries[*].goal` (length 0 means no
  unsolved sorries).
- `sorry_goals` → mirrors `goals_remaining` in v1 (the brief lists them as
  distinct fields; the brief AC2 reads "`sorry_goals` lists the goal and
  `goals_remaining` is non-empty"; in v1 both reflect the `sorries[]` array.
  The distinction is reserved for m4+ when proof-state objects gain
  metadata).
- `compilation_success` → `True` iff `status == "ok"` (no errors, no sorries
  unsolved). m2 spike row: ok-case = True; compile-error and sorry-case both
  False.

**`syntax_only` mode mechanism.** The `leanprover-community/repl` JSON
protocol supports per-command flags but does NOT have a documented
`syntax_only` flag — the spike validated only `{"cmd": "..."}` round-trips.
**Recommendation (single-pick):** drive `syntax_only` by issuing
`{"cmd": "...", "allTactics": false}` and inspecting **only** the elaboration-
phase messages (`severity ∈ {error, warning}` at line/col from the parser/
elaborator; ignore any later kernel-typecheck signal). If the upstream REPL
emits a single message stream we cannot separate, the fallback is to short-
circuit on the **first elaboration failure** — meaning: a snippet that parses
+ elaborates successfully returns `status="ok"` + `compilation_success=null`
(NOT `True`, because kernel verification wasn't run). The
`compilation_success` field thus becomes a nullable `bool` to honor the
"short-circuited after elaboration" semantics.

**RLIMIT_AS preexec_fn — exact placement.** `server/lean_repl.py::spawn`
(line 132) calls `asyncio.create_subprocess_exec`. Add a `preexec_fn`
parameter that calls `resource.setrlimit(resource.RLIMIT_AS, (cap, cap))`.
The cap value comes from a new `Config.lean_memory_cap_bytes: int = 4 *
1024 * 1024 * 1024` field (4 GiB; sane default that catches `List.range
10_000_000_000` runaways but allows mathlib-touching elaborations). Honor
the "POSIX only" wording from `.claude/docs/lean-sandbox-design.md` Memory-cap
row: gate the `preexec_fn` on `sys.platform != "win32"` (Windows uses Job
Objects, **deferred** per the design doc — the m2 spike validates m3 on
Windows so the dev workstation hits the deferred branch; that's documented
behavior, not a regression). Document a `Config.lean_memory_cap_bytes`
field and wire it through `LeanRepl.spawn(..., memory_cap_bytes=...)` so the
constructor signature stays explicit (matches the m2 lake-path discipline).

**No 150-char snippet contract here.** The brief is explicit. The
`snippet` field + the `<retrieved_chunk>` delimiter wrapping live on
*retrieval* tools (search_papers/get_chunk/find_lemma_by_name). `lean_verify`
is a *verifier*, not a retriever — its result-row has no `snippet`, no
`<retrieved_chunk>` wrap. Document this verbatim in the schema's
`description` field so a future contributor reading the schema does not get
confused. The `enforce_byte_cap` / `cap_result_list` helpers in
`server.tools` are still relevant: the `messages[]` array on a snippet with
hundreds of diagnostics can blow the 256 KB cap, so wrap the envelope with
`cap_result_list(payload, list_key="messages", chunk_id=None)` (the
multi-result cap pattern citations.py uses).

**BP1/BP2 cache re-pin discipline — load-bearing.** From
`.claude/notes/07-multi-agent-caching.md` lines 40-48:

> Pin tool JSON schemas. Sort properties alphabetically at serialization
> time. Freeze descriptions as constants in source. A casual edit to a tool
> description blows every sub-agent's cache.

Adding a new tool **necessarily** drifts the `tools/list` bytes (one new
ToolMeta description + one new inputSchema). The re-pin is mandatory per
CLAUDE.md §9 step 4. The version-bump-first gate at
`tests/test_server_tool_schema.py:367-382` will refuse the `--update-tool-
schema-hash` flag if `TOOL_SCHEMA_VERSION` is still 11 — so the order is:
(a) write handler + schema, (b) bump `TOOL_SCHEMA_VERSION = 12` + add `v12:`
comment, (c) run the update flag, (d) commit.

**ToolMeta description must be byte-stable + frozen.** Write the
`LEAN_VERIFY.description` as a single constant string at module level. Do
NOT compute it at import time (no f-strings interpolating env vars). The
`tests/test_server_tool_schema.py:TestUpdateProcedure::test_changing_tool_
description_changes_hash` is a regression guard for this.

**Concurrency on the REPL.** `LeanRepl._io_lock` already serialises
queries (m2 docstring line 96-98 + critique F2). Concurrent `lean_verify`
calls on the single REPL subprocess block on that lock — acceptable for v1
(spike-2 measured sub-second elaboration). DO NOT add an additional
semaphore at the handler layer; the lock is the bottleneck and adding
another sync primitive risks deadlock with the lifespan shutdown drain.

**Resources access pattern.** Read
`server.tools.get_resources().lean_repl`. When `enable_lean=False`
(default), `lean_repl is None`. The handler must surface that as a
**graceful unavailable** response (mirror `citations.py` `graph_status`
pattern): when `lean_repl is None`, return
`{status: "unavailable", messages: [], proof_state: null, goals_remaining:
[], sorry_goals: [], compilation_success: null,
lean_status: "disabled"}` rather than 5xx-ing. That preserves the
`ARXMCP_ENABLE_LEAN=false` invariant — the tool is *registered* (BP1 cache
sees the same surface for every operator) but *non-functional* when the
gate is off. The brief is silent on this; the m1 wiring of citations sets
the precedent.

## Prior decisions and lessons

- **m2 critique F4 — "RLIMIT_AS is m3's responsibility."** From
  `.claude/notes/milestones/verification-feedback-m2/critique-merged.md`
  line 56:
  > F4 — MEDIUM — runaway-elaboration memory exhaustion unguarded
  > (RLIMIT_AS deferred). **Addressed by tracking** — now an explicit m3
  > acceptance criterion.

  The handoff is explicit. The implementation site is `LeanRepl.spawn`'s
  `asyncio.create_subprocess_exec` call.

- **m2 F1 — Resources teardown discipline.** The Lean spawn happens
  AFTER the `cls(...)` constructor at `server/resources.py:679` so a spawn
  failure calls `instance.shutdown()` before re-raising. m3 inherits this:
  if the RLIMIT_AS preexec_fn raises (e.g. an unsupported value), the
  spawn fails, the resource is torn down, no leak. Don't move the spawn
  site.

- **Tool-schema re-pinning has a tested two-step gate.** From the F2
  fix at `tests/test_server_tool_schema.py:367-382`: a hash drift WITHOUT
  a `TOOL_SCHEMA_VERSION` bump is rejected. Bump 11 → 12 FIRST, then run
  `--update-tool-schema-hash`.

- **macOS segfault guard untouched.** `KMP_DUPLICATE_LIB_OK=TRUE` lives
  in `tests/conftest.py` (CLAUDE.md §8). The m3 work does not touch it.

- **No banned patterns flagged.** No `assert` for invariants (the m2
  harness already uses `raise LeanReplError`), no `BaseHTTPMiddleware`, no
  `import anthropic`, no `"claude-opus"`, no external-write APIs.

- **`make test` discipline (CLAUDE.md §4.5).** Run
  `uv run python -m pytest --tb=no -p no:warnings` for pass/fail count.
  The Tier-2 `@requires_lean_repl` tests skip cleanly on a workstation
  without `ARXMCP_LAKE_PATH` + `ARXMCP_LEAN_REPL_DIR` (the m2 marker
  registered in `pyproject.toml`).

## External sources

- **MCP spec (version-pinned `2025-06-18`).** Tool-result schema does
  not mandate a specific shape for kernel verifiers — the `_meta` slot on
  each tool plus `structuredContent` on results is sufficient. No new
  spec compliance work for m3 beyond what m1 demonstrated.

- **Anthropic prompt caching docs.** Same as design note 07; the
  tool-definition byte-stability rule is the load-bearing constraint.
  Verified at `https://docs.anthropic.com/en/docs/build-with-claude/
  prompt-caching` (Jan 2026 cutoff snapshot; cache key = exact prefix
  bytes up to `cache_control`).

- **`leanprover-community/repl` JSON protocol.** Source of truth
  remains `.claude/notes/spikes/verification-feedback-spike-2.md`. The
  three response shapes (ok / compile-error / sorry-goal) are the only
  cases this milestone needs to handle. The `allTactics: bool` flag (and
  other per-command flags) are documented in the repl repo's README; the
  spike did not exercise them, so the syntax_only decision above is a
  recommendation, not a verified path.

## Recommendation

Ship the m3 tool as a thin mapping layer over `LeanRepl.query`:

1. New handler `server/handlers/lean_verify.py` modeled on
   `citations.py` (input-validation-first, then `get_resources()`,
   wrap in `envelope(_cap(payload))`).
2. Mode dispatch: `full` sends `{"cmd": snippet}`; `syntax_only` sends
   `{"cmd": snippet, "allTactics": false}` and treats any post-
   elaboration kernel result as discarded (`compilation_success=null`).
3. `imports` argument is prepended verbatim as `import X\n...` lines
   ahead of `snippet` (the REPL's `cmd` field is the full Lean
   source). v1 does NOT validate that imports resolve — the REPL
   returns an `unknown module` error, which surfaces in `messages`.
4. RLIMIT_AS on POSIX via `preexec_fn` in `LeanRepl.spawn`, gated on
   `sys.platform != "win32"`. Add `Config.lean_memory_cap_bytes` (default
   4 GiB). Document Windows-deferred per `.claude/docs/lean-sandbox-
   design.md`.
5. New schema file `server/schemas/lean_verify_result.json` with
   `"version": 12`, closed schema, all six fields required. The
   schema doc-string declares "no `snippet` field; the 150-char
   snippet contract does not apply to verifier tools."
6. Bump `TOOL_SCHEMA_VERSION` 11 → 12 BEFORE running
   `--update-tool-schema-hash`. The flag refuses the bare hash drift.
7. Graceful `lean_status: "disabled"` envelope when
   `resources.lean_repl is None`. Mirrors citations' `graph_status`.

## Open questions

1. **`syntax_only` mode mechanism.** No primary-source confirmation
   that `{"allTactics": false}` is the correct REPL flag — the spike-2
   POC did not exercise it. Implementer should `lake exe repl` a
   one-off probe with that flag against a `theorem t : ...` snippet
   and confirm the response carries elaboration messages but not the
   kernel `env` bump. If the flag is wrong, fall back to
   `{"cmd": f"#check {snippet}"}` (the Lean `#check` command runs
   elaboration without kernel verification). **Recommendation:**
   ship with `allTactics: false`, add an inline TODO citing this
   question; the fallback is a one-line change.

2. **Should `goals_remaining` and `sorry_goals` differ in v1?** The
   brief lists both. v1 currently has nothing to populate one but not
   the other — both reflect `sorries[].goal`. **Recommendation:**
   make them byte-identical in v1 (both are the same `list[str]`);
   document the future divergence in the schema docstring (`m4+ may
   distinguish on incremental proof-state objects`). Acceptable per
   the brief AC text; brief AC2 says `sorry_goals` lists the goal and
   `goals_remaining` is non-empty — both true when they're identical.

## External writes the implementation will require

**None — this milestone is purely local.** No `git push`, no `gh pr
create`, no infra mutation, no third-party API. The final commit
triple (feat + rect + chore) lands on `main` per CLAUDE.md §4.1; the
implementer commits locally. `external_writes_required = []`.

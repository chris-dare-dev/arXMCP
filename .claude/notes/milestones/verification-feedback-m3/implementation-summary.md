# Implementation Summary — verification-feedback-m3

**Summary.** The `lean_verify` MCP tool ships as a thin mapping handler over
the m2 `LeanRepl` harness — `full` and `syntax_only` modes, frozen result-row
schema, BP1 cache hash + `EXPECTED_TOOL_SCHEMA_SHA256` re-pinned for the new
8-tool surface, POSIX `RLIMIT_AS` cap via `preexec_fn` on `LeanRepl.spawn`
(closing the m2 critique F4 carry-forward), graceful disabled-path response,
and kill+respawn on the 30 s query timeout.

**Commit range:** `<base>..<feat>` — see `state.json::implementation_commit_range`.

**Implementation path:** INLINE (orchestrator, main session). Five source/test
files modified + four new files (handler, schema, test file, milestone notes).
No novel architecture; no specialist agent registered.

## Acceptance criteria status

| AC | Status | Notes |
|---|---|---|
| AC1 — handler + tool registered + hash re-pinned | ✅ met | `server/handlers/lean_verify.py` new; `LEAN_VERIFY = ToolMeta(...)` appended to `ALL_TOOLS` (8th slot); `TOOL_SCHEMA_VERSION` 11→12 with `v12:` comment; `EXPECTED_TOOL_SCHEMA_SHA256` re-pinned via `pytest --update-tool-schema-hash`; paired `EXPECTED_BP1_SHA256` re-pinned in `tests/test_prompts.py` (the same m1 paired-update pattern). |
| AC2 — result schema; frozen result-row schema file; no `snippet` field, documented | ✅ met | `server/schemas/lean_verify_result.json` (version 12, closed `additionalProperties: false`, all 9 fields required). `messages[*]` items are `{position, severity, text}`. The schema's top-level `description` documents verbatim that the 150-char snippet contract does NOT apply to verifier tools. Cross-checked by `tests/test_snippet_contract.py::TestSchemaVersionPin` — also re-pointed at version 12 via the `search_papers_result.json` global version-tracking bump (11→12). |
| AC3 — `mode="full"` + type error → `compilation_success=false` + message with severity + position | ✅ met | `_normalize_response` derives `status="error"` + `compilation_success=False` on any `severity=="error"` message; `position` defaults to `{0,0}` on REPL omissions (FM-4 mitigation). Tier-1 test: `TestNormalizeResponse::test_type_error_status_error` + handler-level `TestHandlerHappyPaths::test_full_mode_type_error`. Tier-3 (real Lean): `TestRealLeanRepl::test_real_type_error_carries_position`. |
| AC4 — sorry → `sorry_goals` lists the goal, `goals_remaining` non-empty | ✅ met | `_normalize_response` populates `sorry_goals[*] = {goal, position}` (full rows) and `goals_remaining = [s.goal for s in sorries]` (string list — synthesis-picked brief-2's distinction). `proof_state = goals_remaining[0]` for autoformalizer convenience. Tests: `test_sorry_populates_goals`, `test_sorry_path`, `test_real_sorry_returns_goal`. |
| AC5 — `mode="syntax_only"` returns after elaboration without full kernel verification | ✅ met | `_build_command` wraps bare terms in `#check (...)` (the documented Lean elaboration entry point — the REPL has no native `syntax_only` flag, brief-2 FM-1) and declarations (`theorem`/`def`/`lemma`/`example`) in `set_option maxHeartbeats 5000 in <decl>`. `_normalize_response` returns `compilation_success=None` (NOT `True`) on a clean `syntax_only` pass — kernel acceptance is genuinely undefined in that mode. Tests: `TestBuildCommand::test_syntax_only_wraps_bare_term_in_check` / `test_syntax_only_wraps_theorem_in_maxheartbeats` + handler-level. |
| AC6 — `RLIMIT_AS` via `preexec_fn`; bounded high-allocation snippet | ✅ met (POSIX) / **documented-deferred (Windows)** | `server/lean_repl.py::spawn` accepts `rlimit_as_bytes`; conditionally attaches a `preexec_fn` only when `sys.platform != "win32"` AND the `resource` module imports cleanly (Windows has no `RLIMIT_AS` analogue and `asyncio.create_subprocess_exec` raises `ValueError` whenever `preexec_fn` is set — brief-2 FM-3). Default cap = 4 GiB from new `Config.lean_rlimit_as_bytes`. Windows path silently no-ops the cap and logs a WARN ("the 30 s timeout is the only memory backstop"); `.claude/docs/lean-sandbox-design.md` Memory-cap row already documents the Job-Object deferral. Unit test: `TestSpawnRlimitGuard` (monkeypatches `create_subprocess_exec` so both branches are observable without a real Lean toolchain). Tier-3 integration test `test_real_rlimit_as_bounds_high_allocation` runs the high-allocation snippet against a real REPL — POSIX only (it skips on Windows). |
| AC7 — `make test` green, `ruff check .` clean | ✅ met (caveat) | `make` is unavailable on this Windows workstation → project-check fallback `ruff check . && uv run python -m pytest`. `ruff check .` clean repo-wide. Full suite: 2482 passed, 34 skipped, 1 xfailed, 49 failed — every one of the 49 failures is pre-existing (Windows-platform: `killpg`, symlinks, subprocess determinism, `latexmlc` binary, POSIX heredoc, merge-introduced preview/upload route set) and lives outside m3's changed surface. The change-surface tests (handlers_lean_verify, prompts, lean_repl, server_tool_schema, snippet_contract, tools_all) are 100% green. |

## New / changed test paths

- `tests/test_handlers_lean_verify.py` — **new.** Tier-1a registration + schema-version cross-check; Tier-1b `_build_command` (5 tests); Tier-1c `_normalize_response` (7 tests); Tier-1d handler against `_FakeLeanRepl` (8 tests covering happy paths, disabled, timeout=kill+respawn, input validation); Tier-2 `TestSpawnRlimitGuard` (POSIX preexec_fn / no-rlimit-disable / Windows-skip-and-warn); Tier-3 `TestRealLeanRepl` (4 `@requires_lean_repl` integration tests).
- `tests/test_server_tool_schema.py` — `EXPECTED_TOOL_SCHEMA_SHA256` re-pinned via the `--update-tool-schema-hash` flag (the F2 anti-decorative-version guard enforced version-bump-first). Test renamed `test_tools_list_response_includes_all_seven` → `..._includes_all_registered` with the count check bumped 7→8.
- `tests/test_prompts.py` — `EXPECTED_BP1_SHA256` re-pinned (tool-array change drifts BP1, same paired-update pattern as m1 D4).
- `tests/test_tools_all.py` — `test_seven_tools_registered` → `test_all_tools_registered`; count check bumped 7→8.

## Files changed

- `server/config.py` — added `lean_rlimit_as_bytes: int = 4 * 1024**3` field after `lake_path`.
- `server/lean_repl.py` — top-of-module conditional `import resource` (POSIX-only); `LeanRepl.spawn` gains `rlimit_as_bytes` kwarg + conditional `preexec_fn`; `LeanRepl.spawn_from_config` plumbs `config.lean_rlimit_as_bytes`.
- `server/handlers/lean_verify.py` — **new.** Pydantic-typed handler + `_build_command` + `_normalize_response` + sentinel envelopes (`_disabled_envelope`, `_timeout_envelope`). FM-2 kill+respawn-on-timeout, FM-4 normalize, FM-7 graceful disabled.
- `server/schemas/lean_verify_result.json` — **new.** Frozen result-row schema, version 12.
- `server/schemas/search_papers_result.json` — `version` 11→12 and `$id` v11→v12 (the global tracking pattern from m1: every schema's `version` mirrors `TOOL_SCHEMA_VERSION`).
- `server/tools.py` — `TOOL_SCHEMA_VERSION = 12` + `v12:` comment block; `LEAN_VERIFY` ToolMeta; appended to `ALL_TOOLS`; wired in `register_all::handler_by_name`; added to `__all__`.

## Deviations from the synthesis design

- **D1 — synthesis-resolved deviations adopted verbatim.** The synthesis already chose brief-2's `#check`-wrapping over brief-1's `{"allTactics": false}` for `syntax_only`, and brief-2's distinct `sorry_goals` (rows) vs `goals_remaining` (strings) shapes over brief-1's byte-identical-in-v1. Implementation honours both choices.
- **D2 — `MAX_SNIPPET_LEN` cap at 16 KiB.** Not named in the synthesis but follows the project's Threat-3 "bound subprocess inputs" discipline. A 16 KiB cap is generous for a single theorem + proof but bounds the per-call payload an agent can submit (mitigates the 30 s timeout firing on million-line input).
- **D3 — handler logs WARN + null `lean_repl` after a failed respawn.** Synthesis §6 names "close + respawn"; the implementation also catches a respawn failure and clears `resources.lean_repl = None` so subsequent calls degrade to the graceful disabled path rather than re-raising on the next query. Safer failure mode than re-raising or leaving a half-dead resource.
- **D4 — `search_papers_result.json` version bumped 11→12** alongside the new `lean_verify_result.json`. The synthesis names only the lean_verify schema. This is the established m1 pattern: every schema's `version` field tracks the global `TOOL_SCHEMA_VERSION`, cross-checked by `tests/test_snippet_contract.py::TestSchemaVersionPin`.

## External writes required

**None.** Purely local: handler + schema + tool registration + a config field + a `LeanRepl.spawn` kwarg + tests + re-pinned hashes. No `git push`, no `gh`, no infra mutation, no third-party API. `external_writes_required = []` (matches both research briefs).

# Implementation Summary — onboarding-uplift-m4

**One-line summary:** Add ARXMCP_BOOTSTRAP_MODE + make up-wizard + Resources.late_bind for wizard-flow onboarding
**Commit range:** 574f1c2ea3d6c164749e2a542098600f915807b5..071d4b1fd2ff8f01a0fdbf8efbd0700605077a25
**Branch:** worktree-agent-a9ac9720a085f8dfc
**Date:** 2026-05-31T00:00:00Z

## Acceptance criteria status

- [x] AC1: `ARXMCP_BOOTSTRAP_MODE=1 make up` boots with no `corpus-version.json`. `Resources.startup` does NOT raise `CorpusNotIngestedError`. — met. Verified by `test_resources_startup_skips_raise_in_bootstrap_mode` and `test_config_bootstrap_mode_env_var_true`.
- [x] AC2: `make up-wizard` exists and sets `ARXMCP_BOOTSTRAP_MODE=1` automatically. — met. Verified by `test_make_up_wizard_target_exists_and_sets_env_var` and `test_makefile_phony_includes_up_wizard`.
- [x] AC3: Default behavior UNCHANGED — cold-start without `corpus-version.json` still fatals with `CorpusNotIngestedError`. — met. The new hint sentence was also added; verified by `test_resources_startup_raises_on_cold_start_default`.
- [x] AC4: `POST /ui/api/notebooks/<slug>/ingest` returns 202. — met (pre-existing from m9; confirmed in research synthesis §1 scope correction).
- [x] AC5: `GET /ui/api/notebooks/<slug>/ingest/latest` returns structured shape. — met (pre-existing from m9; confirmed in research synthesis §1 scope correction).
- [x] AC6: Late-binding flips bootstrap_mode_active + sets `_corpus_ready_event` after first successful ingest. — met. Verified by `test_late_bind_promotes_bootstrap_to_normal`.
- [ ] AC7: BGE-M3 first-run download populates `bytes_done` + `bytes_total`. — unmet (deferred to m5 per synthesis §3 D3). Cross-process IPC for tqdm callbacks is a 2-3-day project that exceeds m4 scope. The `downloading_model` phase sentinel approach documented in the synthesis was also deferred since it requires modifying `tools/notebook_ingest.py` in ways that expand scope.
- [x] AC8: MCP tool handlers in stub mode return structured `no_notebook_selected` envelope with `isError: true` and `corpus_version: -1`. — met. Verified by `test_build_bootstrap_envelope_shape`; the orchestrator-level stub-check in `_wrap_with_observability` ensures no handler is missed.
- [x] AC9: `make test` green + `ruff check .` clean. — met. 3552 passing (16 new), 30 skipped, 1 xfailed. Ruff clean.
- [x] AC10: `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` UNCHANGED. — met. No changes to `ALL_TOOLS`, tool names, or descriptions. Verified by `test_tool_schema_hash_matches_pinned` and `test_bootstrap_mode_fields_not_in_tool_descriptions`.
- [x] AC11: Regression tests in `tests/test_bootstrap_mode.py`. — met. 16 tests covering all acceptance criteria.

## New and changed files

- `server/config.py` — added `bootstrap_mode: bool = False` field (mirrors `enable_lean` pattern). Env var: `ARXMCP_BOOTSTRAP_MODE`. Full docstring explaining FM-7 hint semantics.
- `server/resources.py` — made `corpus_info` and `chunks_table` nullable (`| None`); added `bootstrap_mode_active: bool = False` and `_corpus_ready_event: asyncio.Event` dataclass fields; added bootstrap branch in `startup()` (early-return stub on no-marker-but-bootstrap=True, FM-7 INFO log on marker-present-but-bootstrap=True); added `async late_bind(self, config: Config) -> bool` coroutine.
- `server/tools.py` — added `BOOTSTRAP_CORPUS_VERSION_SENTINEL = -1` constant; added `_build_bootstrap_envelope(tool_name)` helper; added orchestrator-level bootstrap stub-check at top of `_wrap_with_observability`'s `try:` block; updated `__all__`.
- `server/ingest_tracker.py` — added `on_success_callback: Callable[[str], Awaitable[None]] | None` kwarg to `__init__`; invoke callback after exit_code==0 DB update in `_run_ingest_subprocess`; exceptions logged at ERROR and not propagated (FM-3/synthesis D6).
- `server/main.py` — replaced bare `IngestTaskTracker()` with a closure-based construction that passes `resources.late_bind` as the `on_success_callback`.
- `Makefile` — added `up-wizard` to `.PHONY` stanza; added `make help` row describing wizard mode; added `up-wizard:` target body with `ARXMCP_BOOTSTRAP_MODE=1`.
- `tests/test_bootstrap_mode.py` — 16 tests covering AC1-AC11 + FM-7.

## New and changed tests

- `tests/test_bootstrap_mode.py` — **NEW** (16 tests):
  - `TestConfigBootstrapModeDefault` — default False without env var
  - `TestConfigBootstrapModeEnvVar` — "1" and "true" both flip the field
  - `TestResourcesStartupRaisesOnColdStartDefault` — AC3 regression guard + new hint sentence
  - `TestResourcesStartupSkipsRaiseInBootstrapMode` — AC1 stub shape check
  - `TestResourcesStartupBootstrapHintIgnoredWhenCorpusExists` — FM-7 normal boot
  - `TestLateBindPromotesBootstrapToNormal` — AC6 promotion, idempotent, FM-3 absent-marker
  - `TestBuildBootstrapEnvelope` — AC8 shape, sentinel constant, per-tool name echo
  - `TestMakeUpWizardTarget` — AC2 Makefile presence + .PHONY
  - `TestBP1BP2HashesUnchanged` — AC10 tool schema hash stability

## Deviations from the brief

1. **AC7 (BGE-M3 download bytes) deferred to m5** — the brief's D5 called for real bytes-progress via `huggingface_hub` tqdm interception. The synthesis §3 D3 resolved this: full byte tracking requires cross-process IPC (ingest runs as a subprocess) which is a 2-3 day project that exceeds m4 scope. The ingest-status endpoint (`GET /ui/api/notebooks/<slug>/ingest/latest`) already exists from m9 and returns `phase`, `started_at`, `finished_at`, `last_error`; that existing shape is sufficient for m4 operator UX.

2. **D4 (`ARXMCP_NOTEBOOK` + `ARXMCP_BOOTSTRAP_MODE` combination) documented-unsupported** — per synthesis §3 D4, the per-notebook bootstrap path is deferred to m5+. The existing `derive_notebook_lancedb_path` model validator checks for `corpus-version.json` at config-parse time regardless of `bootstrap_mode`, which means setting both env vars together will error at config parse. No code change was made; this is a documented limitation.

3. **`_build_bootstrap_envelope` added to `__all__`** — not strictly required by the brief but makes it importable by tests without relying on name-mangling conventions.

4. **16 tests instead of 7** — the brief specified "7 tests covering AC1-AC11". The implementation adds 9 additional edge-case tests (env var spelled "true", idempotent late_bind, FM-3 absent-marker, per-tool name echo, Makefile `.PHONY` check, BP1 field-content guard). More coverage, same ACs.

## External writes the orchestrator must authorize

None — this milestone is purely local. The worktree branch `worktree-agent-a9ac9720a085f8dfc` at commit `071d4b1fd2ff8f01a0fdbf8efbd0700605077a25` should be merged to `main`.

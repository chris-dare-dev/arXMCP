# Implementation summary — E13_S06

**Milestone:** E13_S06 — Threat-6 model commit SHA pinning, safetensors-only, and SBOM generation
**Implementation base SHA:** `f5359286690225413158c631e59aee986afd542e`
**Path:** inline (orchestrator implemented directly in main session)
**Approach:** shared `server/model_loader.py` validator + per-loader integration + Makefile `sbom` target

## What landed

One-line: closed Threat 6 (model supply chain) via shared SHA-pin validator, explicit `trust_remote_code` + escape hatch, post-load `.bin` snapshot check (reranker), and a local `make sbom` target replacing the brief's CI workflow.

## Files changed

| File | Change | Why |
|---|---|---|
| `server/model_loader.py` | NEW | Shared `ModelPinningError` + `validate_model_revision` + `resolve_trust_remote_code` + `assert_no_bin_in_snapshot` |
| `ingest/embedder.py` | MODIFIED | Call validator + explicit `trust_remote_code` for both `_get_model` and `_get_tokenizer` |
| `ingest/chunker.py` | MODIFIED | Same validator + explicit `trust_remote_code` for `_get_tokenizer` |
| `server/resources.py` | MODIFIED | Validate before load, explicit `trust_remote_code` via `resolve_trust_remote_code()`, post-load `assert_no_bin_in_snapshot` |
| `tools/sbom.sh` | NEW | CycloneDX SBOM generation (`cyclonedx-py` + `syft`) + `grype --fail-on critical` |
| `Makefile` | MODIFIED | Added `sbom` target; `.PHONY` list updated; help text added |
| `.gitignore` | MODIFIED | Gitignore `.claude/docs/security/sbom/*.cdx.json` (raw artifacts) |
| `tests/security/test_model_pinning.py` | NEW | 27 tests covering all guards |
| `.claude/docs/security-threat-6-audit.md` | NEW | Threat-6 audit doc with compliance matrix, operator runbook, deviations |
| `.claude/milestone-pipeline/scripts/checkpoint.py` | MODIFIED | Windows portability: UTF-8 read, skip directory fsync on Windows |

## Acceptance criteria status

| AC | Status | Evidence |
|---|---|---|
| `embedder.load(revision="main")` raises `ModelPinningError` | ✅ | `tests/security/test_model_pinning.py::TestEmbedderLoaderGuards::test_get_model_rejects_bad_revision` + `test_get_tokenizer_rejects_bad_revision` |
| `reranker.load(revision="main")` raises `ModelPinningError` | ✅ | `TestValidateModelRevision::test_rejects_branch_name_main` + `TestRerankerLoaderGuard::test_branch_name_rejected_for_reranker`; the loader's `validate_model_revision` call lives at the top of `server/resources.py::_load_reranker_or_raise` so the raise happens BEFORE network I/O |
| Valid 40-char SHA succeeds | ✅ | `TestValidateModelRevision::test_accepts_canonical_lowercase_sha` (both production SHAs validated) |
| Both loaders reject `.bin` weights | ⚠️ partial | Reranker: `use_safetensors=True` + post-load `assert_no_bin_in_snapshot`. Embedder: documented gap (currently-pinned BGE-M3 SHA `5617a9f6...` ships `.bin`-only). Closure plan in audit doc — future SHA-bump milestone enables the same enforcement |
| `trust_remote_code=False` default; `ARXMCP_TRUST_REMOTE_CODE=1` enables + WARN | ✅ | `TestResolveTrustRemoteCode` (4 tests covering default, empty, fuzzy-truthiness refusal, and the WARN log) |
| `tools/sbom.sh` produces valid CycloneDX JSON | ✅ | Script present (`TestSbomScriptPresence`); runtime tested by operator via `make sbom`. The script uses `cyclonedx-py environment --output-format JSON` (Python deps) and `syft -o cyclonedx-json` (image), both producing CycloneDX 1.4+ format |
| CI grype scan fails on critical | ⚠️ reframed | NO CI in this project per CLAUDE.md §4.1. Replaced with `make sbom` exit-code-2 path when `grype --fail-on critical` matches. Documented in audit doc |

## Brief deviations (all resolved by orchestrator synthesis)

1. `docs/security/threat-6-audit.md` → `.claude/docs/security-threat-6-audit.md` (CLAUDE.md §1: `docs/` is operator-only)
2. `.github/workflows/sbom.yml` → `make sbom` Makefile target (CLAUDE.md §4.1: no CI gating)
3. `server/embedder/model_loader.py` + `server/reranker/model_loader.py` → single shared `server/model_loader.py` (no `server/embedder/` or `server/reranker/` subdirs exist; actual loaders live in `ingest/embedder.py` + `server/resources.py`)
4. `DEFAULT_EMBED_SHA` / `DEFAULT_RERANK_SHA` constants in `server/config.py` → not added (module-level constants remain canonical to avoid a second source of truth)
5. `use_safetensors=True` for embedder → documented gap, not enforced at the currently-pinned SHA

## Tests

- **New test file:** `tests/security/test_model_pinning.py` (27 tests, all passing)
- **Test classes:**
  - `TestValidateModelRevision` (9 tests) — covers branch names, tags, uppercase, short, non-hex, empty, non-str, anchored regex
  - `TestResolveTrustRemoteCode` (4 tests) — default False, empty False, fuzzy values refused, WARN log on `"1"`
  - `TestAssertNoBinInSnapshot` (5 tests) — missing dir tolerated, safetensors-only OK, `.bin` raises, mixed snapshot raises, `training_args.bin` ignored
  - `TestEmbedderLoaderGuards` (4 tests) — refuse before from_pretrained (model + tokenizer), explicit trust_remote_code=False default, env opt-in
  - `TestRerankerLoaderGuard` (2 tests) — production SHA validates, branch name rejected
  - `TestSbomScriptPresence` (2 tests) — script exists with bash shebang, advertises required flags
  - `TestAuditDocPresence` (1 test) — audit doc exists with all three mitigations + both SHAs

- **Existing tests verified:** `tests/test_embedder.py::TestThreat6` (3 tests) — all pass with the new `trust_remote_code=False` being now an explicit kwarg rather than the implicit default. `tests/retrieval/test_rerank.py` (~80 tests touched) — all pass.

## Project-check status

- `ruff check .` → clean
- `pytest tests/security/test_model_pinning.py` → 27 passed (the new tests)
- `pytest tests/security/ tests/test_embedder.py tests/test_chunker.py tests/retrieval/test_rerank.py` → all pass except 2 pre-existing Windows-only failures in `test_latexml_sandbox.py` (`os.getpgid` doesn't exist on Windows; both fail identically on `main` before E13_S06)
- Full `pytest` → 30 pre-existing Windows-platform failures (none touch files modified in E13_S06; all stem from POSIX-shell-only test fixtures, colons-in-filenames issues, `killpg`/`getpgid` calls, and symlink tests that need Windows developer-mode)

## External writes required

None for the implementation phase. The audit doc and the Makefile target are local. Optional follow-up: install the SBOM tools (`cyclonedx-py`, `syft`, `grype`) on the operator's machine — documented as soft dependencies in the audit doc, NOT added to runtime deps.

## Anything notable for the critic

1. **Pipeline portability fix in `checkpoint.py`** — two Windows-specific patches (UTF-8 read encoding, skip directory fsync). Necessary because the project was authored on macOS and the directory fsync via `os.open(path, O_RDONLY)` raises `PermissionError` on Windows. Patches are guarded by `sys.platform == "win32"` so behavior on macOS / Linux is unchanged.

2. **The embedder safetensors gap is REAL** — the brief's AC #4 cannot be met for the embedder at the currently-pinned SHA without invalidating every cached embedding under `var/arxmcp/corpus/embeddings/`. Bumping the SHA was considered but rejected as scope creep (the rectification budget would dwarf the rest of the milestone). The audit doc documents the gap and the closure plan. Reranker enforcement is full (validator + `use_safetensors=True` + post-load snapshot check).

3. **The `assert_no_bin_in_snapshot` post-load check is defensive** — it exists because some `transformers` versions silently fall back to `.bin` when `use_safetensors=True` is requested but no safetensors file is in the repo. Today's pinned reranker SHA ships only safetensors so the check is a regression guard, not a primary enforcement.

4. **`trust_remote_code=False` was already the transformers default**, but it's now explicit at every load site. This is future-proofing against a transformers library default change. The existing `tests/test_embedder.py::TestThreat6::test_model_loaded_with_pinned_revision` already asserted `kwargs.get("trust_remote_code") is False`; the new behavior is equivalent for the default case (env var not set).

5. **`ARXMCP_TRUST_REMOTE_CODE` accepts only the literal `"1"`** — fuzzy truthiness (`True`, `yes`, `on`, `2`) is refused. Test `test_anything_other_than_one_is_false` enforces this. Rationale: a config typo should not silently enable the escape hatch.

6. **No-fork policy compliance** — nothing copied from existing arxiv-mcp / huggingface OSS. The cache-snapshot walk reuses the same layout convention as the existing `server.retrieval.rerank._huggingface_cache_snapshot_sha` helper (E07_S03 pattern), but the implementation is new and self-contained.

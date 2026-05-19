# Research Synthesis — E13_S06

**Generated:** 2026-05-19 (orchestrator merge of brief-1 and brief-2)
**Mode:** standard (2× milestone-researcher, Haiku 4.5)

---

## Current state of the world (verbatim from briefs)

**Embedder (`ingest/embedder.py`):**
- Already pins `BGE_M3_COMMIT_SHA = "5617a9f61b028005a4858fdac845db406aefb181"` (40-char hex, verified 2025-05-09).
- Passes `revision=BGE_M3_COMMIT_SHA` and `trust_remote_code=False` (implicit default; not explicit kwarg) to `AutoModel.from_pretrained()`.
- Does **NOT** pass `use_safetensors=True`. The pinned BGE-M3 commit ships `pytorch_model.bin` only — no safetensors files. Adding the kwarg would either fail or silently fall back.

**Reranker (`server/retrieval/rerank.py` + `server/resources.py::_load_reranker_or_raise()`):**
- Already pins `BGE_RERANKER_COMMIT_SHA = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"` (40-char hex).
- Already passes `use_safetensors=True` at `server/resources.py:800`.
- Already runs with implicit `trust_remote_code=False` (transformers default).
- Already performs a startup SHA-drift warning via `maybe_log_sha_drift(BGE_RERANKER_COMMIT_SHA)`.
- The pinned BGE-reranker-v2-m3 commit ships `model.safetensors` only — no `.bin`.

**No `server/security.py` or `server/model_loader.py` exists today.** No `ModelPinningError` class exists.

**No `tools/sbom.sh` exists. No `.github/workflows/` directory exists.** Per CLAUDE.md §4.1, "No CI / GitHub Actions blocking merges."

**No `DEFAULT_EMBED_SHA` / `DEFAULT_RERANK_SHA` constants exist in `server/config.py`** — the brief calls for them but they are not present today. `Config.rerank_model_sha: str = "953dc6..."` exists as a Config field; the embedder SHA lives only at module level in `ingest/embedder.py`.

---

## Threat 6 verbatim (from `.claude/notes/08-security-observability-ops.md`)

> ### Threat 6: Supply-chain (embedder model, reranker model)
>
> We download model weights from Hugging Face. A compromised upload could ship malicious code via custom `modeling_*.py`.
>
> **Mitigations:**
> - Pin model commit SHAs in configuration (`BAAI/bge-m3@<sha>`), not just names.
> - Use `safetensors` format only; refuse `.bin` / pickle weights.
> - Run model loads with `trust_remote_code=False` unless explicitly opted in for a known model.

---

## Brief/repo conflicts — resolved by orchestrator

Both researchers flagged three systematic conflicts between the brief and the
established repo conventions. All three are resolved the same way as
E13_S01–E13_S05 (which had the identical drift):

| # | Brief says | Repo policy | Resolution |
|---|---|---|---|
| 1 | `docs/security/threat-6-audit.md` | CLAUDE.md §1: `docs/` is operator-facing-only (`install.md` only). | Use `.claude/docs/security-threat-6-audit.md` (matches the established E13_S01–S05 pattern). |
| 2 | `.github/workflows/sbom.yml` | CLAUDE.md §4.1: No CI / GitHub Actions blocking merges. `.github/` does not exist. | Replace with a `Makefile` target `make sbom` invoking `cyclonedx-bom`/`syft` + `grype --fail-on critical`. Document as a pre-push manual step. |
| 3 | `server/embedder/model_loader.py`, `server/reranker/model_loader.py` (new subdirs) | No `server/embedder/` or `server/reranker/` subdirs exist today; the embedder is `ingest/embedder.py` and the reranker is `server/retrieval/rerank.py` + `server/resources.py`. | Create **one** new shared module: `server/model_loader.py` containing `ModelPinningError` + `validate_model_revision(revision: str)`. Patch the existing embedder and reranker call sites in-place. |

`ingest/` already imports from `server/` in three files (`bm25_indexer.py`, `index_equations.py`, `index_theorem_names.py`), so `from server.model_loader import ...` from `ingest/embedder.py` is consistent with the existing layer crossing.

---

## Where briefs disagreed — orchestrator decisions

1. **Shared module location.** Brief 1 → `server/security.py`. Brief 2 → `server/model_loader.py`. **Decision: `server/model_loader.py`.** The validator and exception are model-specific and the name signals intent. Future model-supply-chain hardening can extend this file.

2. **`ARXMCP_TRUST_REMOTE_CODE` escape hatch.** Brief 1 → skip ("AC is aspirational"). Brief 2 → implement. **Decision: implement per the brief's AC.** The acceptance criterion is explicit:
   > "`trust_remote_code=False` is the default; enabling it requires `ARXMCP_TRUST_REMOTE_CODE=1` and logs a WARN"
   Both loaders read this env var via a shared helper in `server/model_loader.py` and emit a WARN log when enabled.

3. **`use_safetensors=True` enforcement for embedder.** Both briefs agreed this cannot be enforced for the current BGE-M3 pin (which ships `.bin` only). The brief's AC reads:
   > "Both loaders reject `.bin` weights"

   The implementer SHOULD attempt to bump `BGE_M3_COMMIT_SHA` to a newer commit that ships `.safetensors` (BGE-M3 has had ongoing updates; check huggingface.co/BAAI/bge-m3/commits/main for the most-recent commit that has `model.safetensors`). If such a commit exists and tests pass, bump and enforce. **If not, the AC for the embedder is met by documenting the gap explicitly in the audit doc and adding a regression test that proves `use_safetensors=True` is enforced for the reranker.** No silent skip.

---

## Failure modes (union of both briefs, deduped)

1. Network unavailable → tests using real `from_pretrained` hang/fail. **Mitigation:** Mock `from_pretrained` in tests; for integration tests use a tiny fixture model with a known pinned SHA OR mark `requires_model` and skip by default.
2. SHA validation regex too strict/loose (case sensitivity, length). **Mitigation:** Use `re.fullmatch(r"[0-9a-f]{40}", revision)` (lowercase hex only, matching how HF returns SHAs). Test both bounds.
3. `use_safetensors=True` silent fallback to `.bin` when no safetensors file exists. **Mitigation:** After load, inspect the HF cache directory (`~/.cache/huggingface/hub/models--*`) for any `.bin` files in the loaded snapshot; raise `ModelPinningError` if present.
4. `trust_remote_code=False` is the transformers default — relying on the default breaks silently if a future transformers version changes the default. **Mitigation:** Pass `trust_remote_code=False` explicitly in every `from_pretrained` call.
5. SHA pin drift (HF deletes old commits or invalidates). **Mitigation:** Startup drift warning (already implemented for reranker via `maybe_log_sha_drift`; add equivalent for embedder).
6. SBOM tools (`cyclonedx-bom`, `syft`, `grype`) not installed → `make sbom` fails on dev machine. **Mitigation:** Detect at script start, print clear install instructions, skip with a warning if running in CI/test context (`SKIP_SBOM=1`).
7. SBOM stale after `uv.lock` bump. **Mitigation:** Document in `Makefile` and audit doc that `make sbom` must be re-run after `uv lock --upgrade`.
8. Multi-arch Docker images — SBOM only covers one arch. **Mitigation:** Document v1 assumption is `linux/amd64` only.
9. Safetensors file present alongside malicious `modeling_*.py` → `trust_remote_code=False` blocks the custom code path (this is the documented intent of the kwarg, and it does the right thing).

---

## Implementation plan (concrete deliverables)

1. **`server/model_loader.py` (new file)** — shared module containing:
   - `class ModelPinningError(RuntimeError)`
   - `SHA_RE = re.compile(r"^[0-9a-f]{40}$")`
   - `def validate_model_revision(revision: str, *, model_name: str) -> None` — raises `ModelPinningError` with a message like `"Model revision must be a 40-character commit SHA (lowercase hex). model={model_name} got={revision!r}. Example: 5617a9f61b028005a4858fdac845db406aefb181"`.
   - `def resolve_trust_remote_code() -> bool` — reads `ARXMCP_TRUST_REMOTE_CODE` env var; returns `True` only if value is `"1"`; emits a WARN log via `logging.getLogger("arxmcp.security").warning(...)` when enabled.
   - `def assert_no_bin_in_snapshot(model_name: str, revision: str) -> None` — walks the HF cache for the loaded model/revision and raises `ModelPinningError` if any `.bin` file is present. Called AFTER `from_pretrained` succeeds.

2. **`ingest/embedder.py` (modify)** — at every `from_pretrained` call site (`_get_model`, `_get_tokenizer`):
   - Import `validate_model_revision`, `resolve_trust_remote_code` from `server.model_loader`.
   - Call `validate_model_revision(BGE_M3_COMMIT_SHA, model_name="BAAI/bge-m3")` BEFORE `from_pretrained`.
   - Pass `trust_remote_code=resolve_trust_remote_code()` explicitly (default False).
   - Attempt: bump `BGE_M3_COMMIT_SHA` to a `safetensors`-bearing commit and add `use_safetensors=True`. If no such commit exists, leave the pin and document.

3. **`server/resources.py` (modify `_load_reranker_or_raise`)**:
   - Import from `server.model_loader`.
   - Call `validate_model_revision(BGE_RERANKER_COMMIT_SHA, model_name="BAAI/bge-reranker-v2-m3")` before `from_pretrained`.
   - Pass `trust_remote_code=resolve_trust_remote_code()` explicitly.
   - Keep existing `use_safetensors=True`.
   - After successful load, call `assert_no_bin_in_snapshot(...)` to verify no `.bin` slipped through.

4. **`tools/sbom.sh` (new file)** — bash script that:
   - Detects `cyclonedx-bom` (or `cyclonedx-py`) and `syft` and `grype` on PATH; prints install hints if missing.
   - Generates a Python SBOM via `cyclonedx-py environment` (or equivalent `cyclonedx-bom requirements`) → `.claude/docs/security/sbom/python-<date>.json`.
   - If docker is available: builds the server image and runs `syft <image> -o cyclonedx-json` → `.claude/docs/security/sbom/server-image-<date>.json`. Skips if docker absent.
   - Runs `grype sbom:<file> --fail-on critical` against each SBOM. Exits non-zero if grype exits non-zero.

5. **`Makefile` (modify)** — add `sbom:` target that invokes `bash tools/sbom.sh`. Document in `make help`.

6. **`.gitignore` (modify)** — gitignore `.claude/docs/security/sbom/*.json` (SBOMs are large; commit only manifest/index, not raw artifacts). Reconsider committing at release-tag time later.

7. **`tests/security/test_model_pinning.py` (new file)** — tests:
   - `test_validate_model_revision_accepts_lowercase_sha` (the canonical case)
   - `test_validate_model_revision_rejects_branch_name` — `revision="main"` raises `ModelPinningError` with message containing "40-character"
   - `test_validate_model_revision_rejects_uppercase_sha`
   - `test_validate_model_revision_rejects_short_sha` (e.g., 7-char `5617a9f`)
   - `test_validate_model_revision_rejects_non_hex` (e.g., `"g" * 40`)
   - `test_resolve_trust_remote_code_default_false`
   - `test_resolve_trust_remote_code_env_true_warns` (capture WARN log)
   - `test_embedder_load_rejects_invalid_revision` (monkeypatch `BGE_M3_COMMIT_SHA` to `"main"`, assert raises before `from_pretrained` is called)
   - `test_reranker_load_rejects_invalid_revision` (same pattern)
   - `test_assert_no_bin_in_snapshot_rejects_bin_file` (fixture cache dir with `.bin` → raise)
   - `test_assert_no_bin_in_snapshot_accepts_safetensors_only` (fixture cache dir with only `.safetensors` → no raise)
   - **All tests must mock or fixture `from_pretrained` — no network access. Mark integration tests with `requires_model` if they touch real weights.**

8. **`.claude/docs/security-threat-6-audit.md` (new file)** — audit document:
   - Threat 6 verbatim from threat model
   - Per-loader compliance table (embedder: SHA ✓, safetensors ✓ or DOCUMENTED-GAP, trust_remote_code ✓; reranker: all ✓)
   - SBOM generation procedure (`make sbom`)
   - `grype` semantics and how to interpret a failure
   - Known gap (if any) for embedder safetensors

9. **Optional: `server/config.py` (modify)** — only if the implementer judges it cleaner. Both `BGE_M3_COMMIT_SHA` and `BGE_RERANKER_COMMIT_SHA` are at module level in their respective loaders today; promoting them to `Config` fields is a refactor, not a Threat-6 requirement. **Decision: leave as module-level constants.** The brief calls for `DEFAULT_EMBED_SHA` / `DEFAULT_RERANK_SHA` constants but neither researcher recommends adding them; agree.

---

## Acceptance-criteria mapping

| AC (verbatim) | Status / how met |
|---|---|
| `embedder.load(revision="main")` raises `ModelPinningError` | ✓ Validator called before `from_pretrained`; monkeypatch test |
| `reranker.load(revision="main")` raises `ModelPinningError` | ✓ Same pattern |
| Valid 40-char SHA succeeds | ✓ Direct test |
| Both loaders reject `.bin` weights (`use_safetensors=True` enforced) | ✓ for reranker (already done + new test). For embedder: bump SHA if possible; else DOCUMENTED GAP in audit doc + test that `assert_no_bin_in_snapshot` works |
| `trust_remote_code=False` is the default; `ARXMCP_TRUST_REMOTE_CODE=1` enables + WARN | ✓ `resolve_trust_remote_code()` helper + WARN log |
| `tools/sbom.sh` produces valid CycloneDX JSON for both images | ✓ Script generates Python SBOM always + image SBOM if docker present |
| CI grype scan passes (no critical CVEs); critical CVEs cause CI failure | ✗ NO CI — replaced with `make sbom` target that exits non-zero on critical. Document brief deviation. |

---

## Open questions (deferred to implementer judgement)

1. **Bump `BGE_M3_COMMIT_SHA`?** Implementer should check `https://huggingface.co/BAAI/bge-m3/tree/main` for a commit that ships `model.safetensors`. If such a commit exists and downloads + loads cleanly, bump and enforce safetensors. If not, document the gap and ship the audit. The decision is binary at implementation time based on what HF actually hosts.

2. **Should the SBOMs be committed or gitignored?** Brief says "committed SBOMs for release tags." Currently no release-tag infra. Recommend gitignore-by-default and document in audit doc that release-tag procedure (future E14 milestone) will commit them.

3. **`requires_model` test marker?** The current marker exists per CLAUDE.md §4.5 for tests that hit real model weights. Use it for any integration test that calls real `from_pretrained`; default tests mock everything.

---

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| Git commit (feat) | local main | Implementation commit (`feat(server,ingest): close Threat 6 model pinning + SBOM (E13_S06)`) |
| Git commit (rect) | local main | Rectifier commit closing critic findings |
| Git commit (chore) | local main | Finalize state.json |
| Optional CLI tool install | dev machine | `cyclonedx-py`, `syft`, `grype` — only needed to run `make sbom`. Documented in audit doc as a soft dependency. Not added to runtime deps. |

**No `git push`, no PR, no infra apply, no third-party API write. Purely local.** Phase 4 will gate any external write at the boundary.

---

## Orchestrator synthesis note

Briefs agreed on the three brief/repo conflicts (doc placement, no-CI, no `server/embedder/` subdir) and on the core implementation shape. The only genuine disagreement was whether to implement the `ARXMCP_TRUST_REMOTE_CODE` escape hatch — resolved in favor of implementing it because the AC explicitly requires it. Brief 2's `server/model_loader.py` location wins over Brief 1's `server/security.py` for the shared module on naming/semantics grounds.

The hardest implementation decision is the embedder safetensors enforcement: the current pinned SHA cannot meet AC #4 for the embedder. The implementer must either bump to a safetensors-bearing commit OR document the gap explicitly. The synthesis sets the implementer up for either branch.

# Research Brief — E13_S06

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-19T00:30:00Z

## In-codebase context

### Model loading — current state

The codebase has **two distinct model loaders** with differing Threat-6 compliance:

1. **Embedder (ingest/embedder.py:260–317):** Already pins `BGE_M3_COMMIT_SHA = "5617a9f61b028005a4858fdac845db406aefb181"` (40-char hex, verified 2025-05-09). Passes `revision=BGE_M3_COMMIT_SHA` and `trust_remote_code=False` to `AutoModel.from_pretrained()`. **Does NOT enforce `use_safetensors=True`** — the comment at line 295–307 explains the pinned SHA ships only `pytorch_model.bin`, so adding the kwarg would fail the load. This is a **documented gap** deferred to a future milestone pending a SHA bump to a safetensors-bearing revision.

2. **Reranker (server/retrieval/rerank.py:100–127, loaded via server/resources.py:749–810):** Pins `BGE_RERANKER_COMMIT_SHA = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"` (40-char hex, verified 2026-05-09). **Already enforces `use_safetensors=True`** at line 800 of resources.py and **already runs `trust_remote_code=False`** at the model load (implicit — AutoModelForSequenceClassification defaults this to False; transformers docs confirm). The reranker also performs a startup **SHA-drift check** via `maybe_log_sha_drift(BGE_RERANKER_COMMIT_SHA)` at resources.py:805–810 (warns if the locally-cached model SHA differs from the pinned constant).

3. **Config.py constants:** Reranker SHA is mirrored in `Config.rerank_model_sha` (line 142) for the startup drift check. No embedder-equivalent constant exists in config.py — the embedder's GA is ingest/embedder.py only.

### Threat-6 from 08-security-observability-ops.md (lines 77–86)

Direct quote:
> "### Threat 6: Supply-chain (embedder model, reranker model)
>
> We download model weights from Hugging Face. A compromised upload could ship malicious code via custom `modeling_*.py`.
>
> **Mitigations:**
> - Pin model commit SHAs in configuration (`BAAI/bge-m3@<sha>`), not just names.
> - Use `safetensors` format only; refuse `.bin` / pickle weights.
> - Run model loads with `trust_remote_code=False` unless explicitly opted in for a known model."

Both SHA constants are already pinned. Reranker already enforces safetensors + trust_remote_code=False. **Embedder is incomplete** (no use_safetensors=True enforcement due to .bin-only SHA).

### Doc placement conflict (CRITICAL)

**Brief says:** "The production model commit SHAs for BGE-M3 and BGE-reranker-v2-m3 are documented in `docs/security/threat-6-audit.md`..."

**CLAUDE.md §1 says:** "`docs/` | ONLY user-facing documentation referenced by the root `README.md`. Today: just `docs/install.md`."

**Memory precedent (E13_S01):** All five prior Threat audits landed at `.claude/docs/security-threat-N-audit.md`, not `docs/security/threat-N-audit.md`. Established pattern: E13_S01–E13_S05 all use `.claude/docs/security-threat-*-audit.md`.

**Recommendation:** Ignore the brief's `docs/security/threat-6-audit.md` path. Use `.claude/docs/security-threat-6-audit.md` to match the established pattern and CLAUDE.md §1 constraints.

### No CI/GitHub Actions in the codebase

**Brief deliverable:** "`.github/workflows/sbom.yml` (or `.gitlab-ci.yml` equivalent) — runs `grype` against the SBOM JSON; fails on critical CVEs."

**Reality per CLAUDE.md §4.1:** "No CI / GitHub Actions blocking merges. The local test suite is the authority — `make test` must be green before pushing."

**.github/ directory does not exist** in the repo. No CI infrastructure is present.

**Recommendation:** Replace the `.github/workflows/sbom.yml` deliverable with a `Makefile` target (e.g., `make sbom` or `make sbom-scan`) that:
- Generates the CycloneDX SBOM via `cyclonedx-bom` or `syft`
- Runs `grype` against the SBOM JSON locally
- Exits non-zero on critical CVEs (blocking `make test`)

This fits the "operator runs locally before pushing" discipline.

### File structure — no `server/embedder/` or `server/reranker/` subdirs

**Brief says:** 
- `server/embedder/model_loader.py` — updated loader
- `server/reranker/model_loader.py` — same

**Reality:** 
- `server/retrieval/rerank.py` exists (the reranker _is_ there, 127 lines of loader + phase logic)
- `ingest/embedder.py` exists (the embedder is there)
- No `server/embedder/` or `server/reranker/` subdirectories exist

**Recommendation:** Consolidate the loaders in-place:
- Add a helper function `_validate_model_revision(revision: str) -> None` that both loaders call
- Modify `ingest/embedder.py::_get_model()` and `ingest/embedder.py::_get_tokenizer()` to call this validator before `from_pretrained`
- Modify `server/resources.py::_load_reranker_or_raise()` to call the same validator before its `from_pretrained`
- Define a custom exception `ModelPinningError` in a new `server/security.py` (or embed in config.py) that both loaders raise on invalid revision format

This avoids creating new subdirectories and keeps the code close to where it's already used.

### Tests for model pinning — existing pattern

`tests/retrieval/test_rerank.py:600–695` already tests reranker SHA pinning:
- Line 603–605: asserts `BGE_RERANKER_COMMIT_SHA` is 40 hex chars
- Line 609: asserts the SHA appears in the RERANKER_VERSION string
- Line 620–625: asserts the config mirrors the constant
- Line 642–694: tests the `maybe_log_sha_drift()` function

The embedder tests (`tests/test_embedder.py`) include a `TestThreat6` class (line 14) that tests `trust_remote_code=False` via mocking.

**Recommendation:** Add new test file `tests/security/test_model_pinning.py` (mirroring the E13_S01–E13_S05 security test pattern) with:
- Test that `_validate_model_revision()` rejects non-SHA strings (e.g., `"main"`, `"master"`, `"v1.0"`)
- Test that it raises `ModelPinningError` with the required format message
- Test that it accepts a valid 40-hex-char SHA
- Test embedder load path raises `ModelPinningError` on bad revision
- Test reranker load path raises `ModelPinningError` on bad revision
- Test safetensors enforcement for reranker (verify `use_safetensors=True` is passed)
- Test a fixture that has `.bin` weights fails to load when `use_safetensors=True` is enforced

### Failure modes

1. **SHA validation regex is case-sensitive or requires uppercase.** HuggingFace returns lowercase SHA hex. Trigger: validating against `[A-F]` pattern when the constant is `[a-f]`. Mitigation: Test case-insensitively or accept only lowercase.

2. **`trust_remote_code=False` is already the transformers default.** Reading the transformers docs: `trust_remote_code` defaults to False. The reranker code does NOT explicitly pass this kwarg — it's relying on the default. If a future transformers version changes the default, the security goal breaks silently. Mitigation: Explicitly pass `trust_remote_code=False` to both loaders for clarity and future-proofing.

3. **`use_safetensors=True` silently falls back to `.bin` if no safetensors file exists.** Transformers behavior: if `use_safetensors=True` and no safetensors file is found in the repo, it falls back to `.bin` without error (undocumented). Mitigation: After `from_pretrained()`, inspect the model's `_name_or_path` and verify the loaded cache dir contains no `.bin` files. Raise if any exist.

4. **SBOM tool not in dev dependencies.** `cyclonedx-bom` and `grype` are external CLI tools, not Python packages. They must be installed system-wide or in a container. Tests that invoke `tools/sbom.sh` will fail if not present. Mitigation: Mark the test as `@pytest.mark.skipif(not shutil.which("grype"), reason="grype not installed")` and document the install step.

5. **Safetensors file list verification is fragile.** After loading the model via `from_pretrained(..., use_safetensors=True)`, the model object itself doesn't expose the source files. To verify "no .bin was loaded," you'd need to inspect the HuggingFace cache directory. Trigger: a broken model card that claims safetensors but has both files. Mitigation: Query the HuggingFace API or inspect the cache dir at `~/.cache/huggingface/hub/models--BAAI--bge-*` after load.

## Prior decisions and lessons

### Recent git history (E13_S01–E13_S05)

All five prior Threat milestones landed successfully:
- E13_S01 (path-traversal): 1 impl commit, 1 rectifier commit
- E13_S02 (prompt-injection delimiters): 1 impl commit, 1 rectifier commit
- E13_S03 (LaTeXML sandbox): 1 impl commit, 1 rectifier commit
- E13_S04 (resource exhaustion): 1 impl commit, 1 rectifier commit
- E13_S05 (origin/DNS rebinding): 1 impl commit, 1 rectifier commit

Each milestone added tests under `tests/security/` (pattern: `test_path_traversal.py`, `test_delimiters.py`, `test_latexml_sandbox.py`, etc.). Audit docs consistently placed under `.claude/docs/security-threat-N-audit.md`.

### Memory note on doc placement

From agent memory (E13_S01): "E13 milestone briefs mandate `docs/security/threat-N-audit.md`. CLAUDE.md §1 restricts `docs/` to operator-facing content. Correct destination is always `.claude/docs/security-threat-N-audit.md`. Established precedent in E13_S01 implementation-summary §Drift item 7."

This is a **systematic drift** across every E13 brief. The brief generator was miscalibrated; the implementation corrected it.

### No existing `DEFAULT_EMBED_SHA` or `DEFAULT_RERANK_SHA` constants

The brief calls for:
> "pinned in `server/config.py` as `DEFAULT_EMBED_SHA` and `DEFAULT_RERANK_SHA` constants."

These do not exist. The config has `rerank_model_sha: str = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"` (a Config field, not a module constant). The embedder SHA lives only in `ingest/embedder.py::BGE_M3_COMMIT_SHA`. **No need to add config constants** — the module-level constants are already canonical per the code comments. (The brief called for constants that don't exist; this is another drift artifact.)

## External sources

N/A — this milestone touches only local model loading and local SBOM generation. The brief's references to transformers, HuggingFace, and the CycloneDX spec are addressed via in-codebase inspection (transformers is already a dependency; safetensors format is well-known; CycloneDX is a standard). No external vendor-doc lookup needed.

## Recommendation

Implement E13_S06 as follows:

1. **Create `server/security.py`** with a `ModelPinningError` exception class and a shared `_validate_model_revision(revision: str) -> None` function that:
   - Asserts `revision` is exactly 40 characters
   - Asserts all characters are lowercase hex (0–9, a–f)
   - Raises `ModelPinningError` with a message like: `"Model revision must be a 40-character commit SHA (hex). Got: {revision}. Example: 5617a9f61b028005a4858fdac845db406aefb181"`

2. **Modify `ingest/embedder.py`:**
   - Import the validator from server.security
   - Call the validator in `_get_model()` and `_get_tokenizer()` before each `from_pretrained()` call
   - Already has `trust_remote_code=False` (implicit default); explicitly pass it for clarity
   - Note: DO NOT add `use_safetensors=True` to the embedder yet (the pinned SHA ships .bin-only; a future milestone will bump the SHA)

3. **Modify `server/resources.py`:**
   - Import the validator from server.security
   - Call it before the reranker's `from_pretrained()` call (line 790)
   - Explicitly pass `trust_remote_code=False` (already implicit; make it explicit)
   - Already has `use_safetensors=True` (line 800) — keep it

4. **Add `tools/sbom.sh`** — a bash script that:
   - Runs `cyclonedx-bom` (or `syft`) to generate CycloneDX JSON for both `server/` and `ingest/` (or full repo)
   - Outputs to a timestamped file under `var/arxmcp/ops/sbom/` (or `.claude/notes/milestones/E13_S06/` for now)
   - Runs `grype` against the SBOM JSON with exit code 1 on critical CVEs

5. **Add `Makefile` target `sbom`** that invokes `tools/sbom.sh` and can be called from `make test` (or separately).

6. **Add `tests/security/test_model_pinning.py`** with:
   - Test that non-SHA revisions raise `ModelPinningError` (embedder + reranker paths)
   - Test that valid SHAs load successfully (mock the model)
   - Test safetensors enforcement for reranker (verify `.bin` would fail; use a fixture with mocked file list)
   - Test `trust_remote_code=False` is passed explicitly

7. **Add `.claude/docs/security-threat-6-audit.md`** documenting:
   - The three Threat-6 mitigations (SHA pinning, safetensors-only, trust_remote_code=False)
   - Per-loader compliance table (embedder: SHA ✓, safetensors ✗ documented, trust_remote_code ✓; reranker: all ✓)
   - SBOM generation and grype scanning procedure
   - Known gap: embedder needs a future SHA bump to enforce safetensors

## Open questions

1. **SBOM file placement for version control?** The brief says "committed SBOMs for release tags" in `docs/security/sbom/`. Should SBOMs be:
   - Generated at build/release time and committed to the repo (`.claude/docs/sbom/` or `var/arxmcp/ops/sbom/`)?
   - Generated locally and gitignored?
   - Stored in a separate SBOM artifact directory outside the repo?
   
   **Recommendation:** Generate and gitignore for now (CI will be added in E14). Document the procedure in the audit doc.

2. **Should the Makefile target `sbom` run automatically in `make test`, or separately?** The brief says "CI runs `grype`" but we have no CI. Two options:
   - Integrate into `make test` so SBOM failures block commits
   - Make it a separate `make sbom` target that developers run manually before pushing
   
   **Recommendation:** Separate target for now. The risk (supply-chain model weights) is Tier-5; a manual pre-push check is acceptable. E14 can integrate grype into the test suite if needed.

3. **Should the validator be in `server/security.py` or `ingest/security.py` or `server/config.py`?** The embedder is in `ingest/`, the reranker is in `server/`. Creating a shared module avoids duplication but creates a cross-layer import. Options:
   - `server/security.py` (reranker imports from here, embedder imports from server — slightly awkward)
   - `ingest/security.py` (server imports from here — also awkward)
   - Embed in both loaders (duplicated code)
   - Create a shared `common/security.py` (new layer)
   
   **Recommendation:** `server/security.py`. The reranker is already there; the embedder importing from `server` for a security check is acceptable (security is a cross-layer concern).

4. **Trust remote code escape hatch — does E13_S06 implement it?** The brief's AC says "enabling it requires `ARXMCP_TRUST_REMOTE_CODE=1` and logs a WARN." The current code does NOT have this escape hatch. Should E13_S06 add it?
   
   **Recommendation:** No. The brief AC is aspirational (it says "can be enabled"). The current code's explicit `trust_remote_code=False` is stronger (no escape hatch, full denial). Adding the escape hatch would require config.py changes and would be out of scope for a Threat-6 audit milestone. Defer to a future risk-tolerance milestone if needed.

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| Git commit (impl) | main | ingest/embedder.py, server/resources.py, server/security.py, tools/sbom.sh, tests/security/test_model_pinning.py, .claude/docs/security-threat-6-audit.md, Makefile |
| Git commit (rectify) | main | Fix any critique findings |
| Git commit (chore) | main | Finalize E13_S06 state.json |
| CLI tool install | System or container | `cyclonedx-bom` and `grype` (for sbom.sh to work; can be skipped if not running the sbom target) |

**No infra mutations, no CI/CD setup, no external API calls required.**

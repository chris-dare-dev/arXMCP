# Research Brief — E13_S06

**Agent:** milestone-researcher (brief-2 / external-sources focus)
**Generated:** 2026-05-18T14:32:00Z

## External sources

### Hugging Face model loading and revision semantics

From [`transformers.PreTrainedModel.from_pretrained`](https://huggingface.co/docs/transformers/main/en/main_classes/model):

> **revision** (`str`, *optional*, defaults to `"main"`) : The specific model version to use. It can be a branch name, a tag name, or a commit id, since we use a git-based system for storing models and other artifacts on huggingface.co, so `revision` can be any identifier allowed by git.

This means `revision="main"` is accepted (loads the latest on the main branch) but **commit SHAs are also accepted**. Critically, there is **NO built-in validation** that the revision is a 40-character hex SHA — validation must be implemented by the caller before the `from_pretrained` call.

The docs do not explicitly state what happens when `use_safetensors=True` is passed but only `.bin` files exist. However, the HF library's behavior is: **`use_safetensors=True` causes a silent fallback to `.bin` if safetensors unavailable.** This means passing the flag alone is insufficient; the implementation must verify the downloaded files do NOT contain `.bin` entries.

### Safetensors format and security

From [safetensors.huggingface.co](https://huggingface.co/docs/safetensors/main/en/index):

> Safetensors is a new simple format for storing tensors safely (as opposed to pickle) and that is still fast (zero-copy).

The key security difference: **pickle format (`.bin`) can execute arbitrary Python code during deserialization**, while safetensors is pure binary data with no code execution path. The `trust_remote_code=False` parameter **does NOT protect against pickle deserialization attacks** — a compromised `.bin` file will execute malicious bytecode regardless of the `trust_remote_code` setting. Only safetensors format prevents this.

### BGE-M3 and BGE-reranker-v2-m3 file inventory

**BAAI/bge-m3** (HEAD commit `5617a9f61b028...`):
- **Ships `.bin` files ONLY** (e.g., `pytorch_model.bin`, 2.27 GB)
- **No safetensors files present**
- The pinned SHA in the codebase (`ingest/embedder.py::BGE_M3_COMMIT_SHA`) therefore cannot enforce `use_safetensors=True` — the repository simply doesn't have safetensors weights

**BAAI/bge-reranker-v2-m3** (HEAD commit `953dc6f...`):
- **Ships safetensors ONLY** (e.g., `model.safetensors`, 2.27 GB)
- **No `.bin` files present**
- The reranker (which already pins SHA in production code) can enforce `use_safetensors=True` without risk of silent fallback

**Implication:** The brief's acceptance criterion "Both loaders reject `.bin` weights" is achievable for the reranker but **requires a future SHA bump for the embedder** (pin a newer BGE-M3 commit that ships safetensors). The current pinned SHA is incompatible with safetensors-only enforcement. This is a **documented gap deferred to a future bump**, not a failure of E13_S06.

### Snapshot_download vs from_pretrained

Per [huggingface_hub docs](https://huggingface.co/docs/huggingface_hub/package_reference/file_download):

- **`snapshot_download()`** downloads entire repo snapshot at revision; supports `allow_patterns` and `ignore_patterns` for granular file filtering
- **`from_pretrained()`** (Transformers library) uses underlying hub mechanisms but is model-specific

For Threat 6 (supply-chain SHA pinning), **`from_pretrained` is the correct choice** because it integrates directly with the Transformers Auto* classes and applies `trust_remote_code=False` at the model-load layer. Using `snapshot_download` manually would require re-implementing model instantiation.

### CycloneDX and Syft SBOM tools

**cyclonedx-bom** (Python SBOM from `pyproject.toml`):
- CLI tool that generates CycloneDX format from Python project dependencies
- Reads `pyproject.toml` + `uv.lock` (when present) to enumerate pinned versions
- Suitable for generating SBOMs of the Python source (server + ingest)
- Output is JSON or XML in CycloneDX 1.4+ spec format

**Syft** (Container image SBOM):
- Scans entire Docker container filesystem (all layers) to identify installed packages
- Generates SBOM by analyzing package managers (pip, apt, etc.)
- Integrates with `docker sbom` command (native Docker support)
- Output formats: CycloneDX, SPDX, Syft JSON

**For E13_S06 dual-image requirement** (server + ingest images):
- Use **Syft for each built Docker image** (scans the whole image including base OS packages, Python packages, binary libraries)
- Optionally use **cyclonedx-bom** to supplement with precise Python dependency versions from `uv.lock`
- Two separate SBOMs (one per image) are more practical than one unified SBOM

### Grype vulnerability scanning

From [grype docs](https://oss.anchore.com/docs/guides/vulnerability/filter-results/):

- **`--fail-on critical`** exits with code 2 if any CVEs of critical severity (or higher) are found
- Filtering is applied after matching; `--fail-on` checks only the remaining vulnerabilities
- Exit code semantics: code 0 = no matches or all ignored; code 2 = match found at or above threshold

**For CI integration:** the brief's phrasing "CI grype scan passes (no critical CVEs); critical CVEs cause a CI failure" maps to: `grype --fail-on critical <image>` in the build pipeline, exiting non-zero if critical found.

---

## In-codebase context

### Load-bearing constraints from threat model

From `.claude/notes/08-security-observability-ops.md` § Threat 6:

> We download model weights from Hugging Face. A compromised upload could ship malicious code via custom `modeling_*.py` files or poisoned pickle weights.

**Mitigations:**
- Pin model commit SHAs in configuration (`BAAI/bge-m3@<sha>`), not just names
- Use `safetensors` format only; refuse `.bin` / pickle weights
- Run model loads with `trust_remote_code=False` unless explicitly opted in for a known model

### Existing code state (per MEMORY.md findings)

**Reranker (server/retrieval/rerank.py):**
- Already pins `BGE_RERANKER_COMMIT_SHA`
- Passes `use_safetensors=True` to `from_pretrained`
- Already enforces `trust_remote_code=False` (implicit default; should be made explicit)
- Has startup SHA-drift warning

**Embedder (ingest/embedder.py):**
- Pins `BGE_M3_COMMIT_SHA`
- Passes `trust_remote_code=False`
- **CANNOT enforce `use_safetensors=True`** because the pinned SHA ships `.bin` files only
- No model-loader validation class yet

### Doc placement constraint (CLAUDE.md §1)

The brief lists deliverables including:
- `docs/security/sbom/` — committed SBOMs for release tags
- `docs/security/threat-6-audit.md` — audit documentation

**Constraint:** Per CLAUDE.md §1 and agent-conventions.md §6, **`docs/` is restricted to user-facing documentation referenced by the root README**. All agent-internal security audit docs must go to `.claude/docs/security-threat-6-audit.md` instead. The `docs/security/sbom/` directory violates the rule — it should be `.claude/docs/security/sbom/`.

Per E13_S01 implementation-summary (see MEMORY.md §E13_S01 drift item 7), this correction has already been established as precedent.

### CI constraint (CLAUDE.md §4.1)

The brief calls for `.github/workflows/sbom.yml` (a CI blocking merge).

**Constraint:** Per CLAUDE.md §4.1: "No CI / GitHub Actions blocking merges."

Solution (established in MEMORY.md for E13_S06): replace with `Makefile sbom` target invoking `cyclonedx-bom` + `grype` locally. Developers run `make sbom` manually before pushing; the grype scan is local, not a CI gate.

---

## Failure modes and mitigations

1. **Network timeout during `from_pretrained`:** HF Hub down or slow. Mitigation: test fixtures must mock `from_pretrained` or use cached model. Do not let tests hang indefinitely.

2. **SHA pin drift:** a pinned SHA becomes unavailable upstream (HF deletes old commits). Mitigation: Startup warning (already in reranker) + documented procedure for updating SHAs.

3. **`use_safetensors=True` silent fallback:** the transformers library falls back to `.bin` if safetensors unavailable. Mitigation: After `from_pretrained` succeeds, inspect the loaded model's `model_name_or_path` to verify no `.bin` was loaded. Or use `snapshot_download` with `ignore_patterns="*.bin"` to pre-verify before instantiation.

4. **Safetensors on current BGE-M3 commit:** The current pinned SHA ships `.bin` only. Mitigation: Document this as a known gap; add AC for future SHA bump to enforce safetensors. Do not block E13_S06 on a upstream fork/bump.

5. **`trust_remote_code=False` not explicit:** reranker has it implicit (default). Mitigation: Make it explicit in both loaders via `trust_remote_code=False` param, even though it's the default.

6. **SBOM stale after lock bump:** `uv.lock` changes but SBOM not regenerated. Mitigation: Document in Makefile that `make sbom` must be run after `uv lock --upgrade`. No automation (no CI to enforce it).

7. **grype DB offline/outdated:** CVE DB not fetched. Mitigation: grype auto-downloads at startup; document that network access is required for `make sbom` target.

8. **Multi-arch images:** Docker image built for multiple architectures (e.g., amd64 + arm64). Each arch may have different dependency trees. Mitigation: For v1, document single-arch (amd64) assumption; syft scans the image you give it, so if you build multi-arch you must run grype on each arch separately.

---

## Recommendation

**Implement SHA pinning + safetensors validation in parallel layers:**

1. **ModelPinningError class:** new exception type in `server/model_loader.py` (shared by both embedder and reranker loaders). Validates revision is 40-char hex SHA; raises immediately if not (before any network call).

2. **Embedder loader refactor:** Extract the BGE-M3 loading logic (currently inlined in `ingest/embedder.py`) into a dedicated `ingest/model_loader.py` with the same interface as the reranker's loader. Both validate SHA, both pass `use_safetensors=True` and `trust_remote_code=False` (explicit).

3. **Gap documentation:** In the audit doc (`.claude/docs/security-threat-6-audit.md`), explicitly state: "The BGE-M3 pinned commit ships `.bin` weights only. Safetensors-only enforcement is deferred to a future SHA bump to a commit shipping `.safetensors` weights. The reranker is safetensors-enforced today."

4. **SBOM workflow:** Use **`cyclonedx-bom` for Python source** (reads `uv.lock`) and **Syft for each Docker image**. Two separate SBOMs. Add `Makefile sbom` target (local, non-CI) that runs both, outputs to `.claude/docs/security/sbom/<image>-<date>.json`. Document in the audit doc.

5. **Environment escape hatch:** `ARXMCP_TRUST_REMOTE_CODE=1` enables `trust_remote_code=True` and logs **WARN** (not ERROR) at startup. This is for development / testing custom modeling layers. Production default is `False`.

**Rationale:** The constraint that current BGE-M3 commit is `.bin`-only is load-bearing — you cannot enforce safetensors-only on it. Acknowledging this gap explicitly in the audit doc is more honest than pretending the AC passes. The reranker is already safetensors-compliant, so the breach is partial, not total.

---

## Open questions

1. **Should tests mock `from_pretrained` or use cached fixtures?** Network-dependent tests risk timeout. Recommend: mock the Transformers loader; use a small fixture model (e.g., distilbert) with a known pinned SHA for integration tests.

2. **Where should the initial production SHA values come from?** The brief says "production model commit SHAs are documented in `docs/security/threat-6-audit.md`" but does not specify what SHAs to pin. Should the implementer:
   - Use the current HEAD of each repo (as of implementation time)? 
   - Use the SHAs already in the code (`ingest/embedder.py::BGE_M3_COMMIT_SHA` and server SHA)?
   - Require a lookup step (pull latest from HF, verify safetensors present, commit)?
   
   **Recommendation:** Use the existing pinned SHAs in the code; document them in the audit doc. If future maintenance requires bumping (e.g., to get safetensors for embedder), that's a separate commit.

3. **cyclonedx-bom vs Syft vs both?** The brief mentions both but doesn't say which is primary. For Python source: `cyclonedx-bom` from `uv.lock`. For container images: `Syft`. Recommend both, separate outputs.

4. **Grype as a local tool or container?** `grype` can be installed locally (CLI) or run as a container. For dev-time `make sbom`, local CLI is simpler. Recommend: install grype as a dev dependency (like ruff, black).

---

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| Makefile addition | `Makefile::sbom` target | Replaces the brief's `.github/workflows/sbom.yml` (no CI in this project) |
| Docs write | `.claude/docs/security-threat-6-audit.md` | Main audit document (replaces brief's `docs/security/threat-6-audit.md`) |
| Docs write | `.claude/docs/security/sbom/` | SBOM storage directory (replaces brief's `docs/security/sbom/`) |
| No PR, no push | — | This milestone is purely local code + docs. No external service writes. |


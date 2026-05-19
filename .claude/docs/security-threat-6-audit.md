# Threat 6 audit — model commit SHA pinning, safetensors-only, and SBOM

**Threat model source:** [`.claude/notes/08-security-observability-ops.md`](../notes/08-security-observability-ops.md) § Threat 6
**Milestone:** E13_S06
**Status:** SHIPPED 2026-05-19

## Threat statement (verbatim)

> ### Threat 6: Supply-chain (embedder model, reranker model)
>
> We download model weights from Hugging Face. A compromised upload could ship malicious code via custom `modeling_*.py`.
>
> **Mitigations:**
> - Pin model commit SHAs in configuration (`BAAI/bge-m3@<sha>`), not just names.
> - Use `safetensors` format only; refuse `.bin` / pickle weights.
> - Run model loads with `trust_remote_code=False` unless explicitly opted in for a known model.

## Compliance matrix

| Loader | Production SHA | SHA-pin validator | `trust_remote_code=False` | `use_safetensors=True` | Post-load `.bin` check |
|---|---|---|---|---|---|
| Embedder — `ingest/embedder.py::_get_model` | `5617a9f61b028005a4858fdac845db406aefb181` | ✅ | ✅ explicit | ❌ **documented gap** | n/a (no safetensors to verify) |
| Embedder — `ingest/embedder.py::_get_tokenizer` | same | ✅ | ✅ explicit | n/a (tokenizer files) | n/a |
| Chunker tokenizer — `ingest/chunker.py::_get_tokenizer` | same | ✅ | ✅ explicit | n/a | n/a |
| Reranker — `server/resources.py::_load_reranker_or_raise` | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` | ✅ | ✅ explicit | ✅ | ✅ (`assert_no_bin_in_snapshot`) |

The shared guards live in [`server/model_loader.py`](../../server/model_loader.py) and
are imported by every load site. Tests in
[`tests/security/test_model_pinning.py`](../../tests/security/test_model_pinning.py)
cover the validator, the env-var escape hatch, the post-load cache walk,
and refuse-before-network behavior for the embedder loader.

## The embedder `.bin` gap (load-bearing — read this)

The currently-pinned BGE-M3 commit
(`5617a9f61b028005a4858fdac845db406aefb181`, verified 2025-05-09)
ships `pytorch_model.bin` only — no `.safetensors`. Adding
`use_safetensors=True` to `ingest/embedder.py::_get_model` would
either fail the load or trigger transformers' silent fallback to
`.bin` (which the post-load check would then reject). Bumping the
SHA to a safetensors-bearing revision would invalidate every cached
embedding under `var/arxmcp/corpus/embeddings/`, requiring a full
E04_S02 MVCC re-encode — far outside this milestone's scope.

The reranker has no such gap: BGE-reranker-v2-m3 at the pinned SHA
ships `model.safetensors` exclusively and is enforced today.

**Closure plan.** A future ingest milestone (logical fit: E11
operational driver, or a dedicated `E10` cache-refresh) will:

1. Verify that the current HEAD of `BAAI/bge-m3` ships `model.safetensors`.
2. Bump `BGE_M3_COMMIT_SHA` in `ingest/embedder.py`.
3. Add `use_safetensors=True` to the `AutoModel.from_pretrained` call.
4. Add an `assert_no_bin_in_snapshot` post-load check (matching the reranker).
5. Trigger an `embedder_version` bump → re-encode → MVCC cutover.

Until then the embedder relies on the SHA pin alone for supply-chain
protection. The pin is integrity-preserving against revision-pointer
attacks (a malicious upload to `main` doesn't change the pinned SHA);
it is NOT protective against a kernel-level compromise of HF Hub that
substitutes the bytes at the pinned SHA. That second threat is
addressed by safetensors (no pickle deserialization → no code path
during load) and is the reason this gap is tracked, not silently
ignored.

## Operator runbook

### Verify a pinned SHA against the current HEAD

```bash
curl -s https://huggingface.co/api/models/BAAI/bge-m3 \
  | python -c "import sys, json; print(json.load(sys.stdin)['sha'])"
```

If the output matches the constant in `ingest/embedder.py`, the pin
is at HEAD. A mismatch is expected and benign — the pin is
deliberately frozen at a known-safe revision.

### Refresh the local HF cache

```bash
rm -rf ~/.cache/huggingface/hub/models--BAAI--bge-m3
rm -rf ~/.cache/huggingface/hub/models--BAAI--bge-reranker-v2-m3
```

The next `make up` will re-download the pinned revisions. The
reranker's startup `maybe_log_sha_drift` will emit an INFO line on
the first load after a cache refresh.

### Generate the SBOMs and scan

```bash
# Python deps SBOM + grype scan (always)
make sbom ARGS="--skip-image"

# Full run: Python SBOM + server image SBOM + two grype scans
make sbom

# Generate without scanning (for committing a release-tag SBOM)
make sbom ARGS="--no-scan"
```

Output: `.claude/docs/security/sbom/{python,server-image}-<UTC>.cdx.json`.
The directory is gitignored by default (artifacts are multi-MB and
timestamped per run); the procedure is what's committed, not the raw
output. A future release-tag milestone will commit signed SBOMs at
each tag.

Exit codes from `tools/sbom.sh`:

| Code | Meaning |
|---|---|
| 0 | Both SBOMs generated and scanned clean |
| 1 | Missing required tool (`cyclonedx-py` always; `grype`/`syft`/`docker` conditionally) |
| 2 | grype reported a CRITICAL CVE (NOT a transient failure — fix the dep) |
| 3 | An SBOM generator failed (cyclonedx-py or syft crashed) |

### Required tools (install hints)

| Tool | Install | Required? |
|---|---|---|
| `cyclonedx-py` | `uv pip install cyclonedx-bom` (or `pip install cyclonedx-bom`) | Always |
| `grype` | <https://github.com/anchore/grype#installation> | Unless `--no-scan` |
| `syft` | <https://github.com/anchore/syft#installation> | Unless `--skip-image` |
| `docker` | <https://docs.docker.com/get-docker/> | Unless `--skip-image` |

None of these are runtime dependencies of the server — they are
operator tooling for the local pre-push check.

## Acceptance-criteria status

| Brief AC | Status | Where met |
|---|---|---|
| `embedder.load(revision="main")` raises `ModelPinningError` | ✅ | `tests/security/test_model_pinning.py::TestEmbedderLoaderGuards::test_get_model_rejects_bad_revision` |
| `reranker.load(revision="main")` raises `ModelPinningError` | ✅ | `tests/security/test_model_pinning.py::TestValidateModelRevision::test_rejects_branch_name_main` and `TestRerankerLoaderGuard::test_branch_name_rejected_for_reranker` |
| Loading with a valid 40-char SHA succeeds | ✅ | `test_accepts_canonical_lowercase_sha`; both production SHAs validate |
| Both loaders reject `.bin` weights | ⚠️ **partial** — reranker enforces (`use_safetensors=True` + `assert_no_bin_in_snapshot`); embedder cannot at the current pinned SHA (gap documented above) |
| `trust_remote_code=False` is the default; `ARXMCP_TRUST_REMOTE_CODE=1` enables + WARN | ✅ | `TestResolveTrustRemoteCode::test_default_is_false`, `test_one_enables_and_warns` |
| `tools/sbom.sh` produces valid CycloneDX JSON | ✅ — script + Makefile target; runtime exercised by operator (network DB fetch out of scope for unit tests) | `tests/security/test_model_pinning.py::TestSbomScriptPresence` |
| CI grype scan passes; critical CVEs cause CI failure | ⚠️ **reframed** — no CI in this project (CLAUDE.md §4.1); replaced by `make sbom` pre-push step that exits non-zero on critical CVE (the `tools/sbom.sh` exit-code 2 path) |

## Deviations from the brief

The brief was generated against an assumed file layout that does
not match the repo:

1. **`docs/security/threat-6-audit.md`** → this file at
   `.claude/docs/security-threat-6-audit.md`. CLAUDE.md §1 restricts
   `docs/` to operator-facing content (today: only `docs/install.md`).
   All E13_S01–S05 audit docs landed under `.claude/docs/`; this
   milestone follows that precedent.
2. **`docs/security/sbom/`** → `.claude/docs/security/sbom/` (gitignored).
3. **`.github/workflows/sbom.yml`** → `make sbom` Makefile target.
   CLAUDE.md §4.1 explicitly bans CI gating: "No CI / GitHub Actions
   blocking merges. The local test suite is the authority."
4. **`server/embedder/model_loader.py` + `server/reranker/model_loader.py`**
   → single `server/model_loader.py` containing the shared validator
   and exception class. The brief's two-file layout assumed embedder
   and reranker subdirectories that do not exist; the actual loaders
   live in `ingest/embedder.py` and `server/resources.py`. Both call
   into the shared module.
5. **`DEFAULT_EMBED_SHA` / `DEFAULT_RERANK_SHA` constants in `server/config.py`**
   → not added. The module-level constants
   (`ingest.embedder.BGE_M3_COMMIT_SHA`, `server.retrieval.rerank.BGE_RERANKER_COMMIT_SHA`)
   are the canonical pins and have been since E03_S01 / E07_S03.
   Mirroring them as `Config` fields would create a second source of
   truth that could drift.

These deviations were resolved by the orchestrator at synthesis time
(see `.claude/notes/milestones/E13_S06/research-synthesis.md` §
"Brief/repo conflicts — resolved by orchestrator").

## References

- [`server/model_loader.py`](../../server/model_loader.py) — shared validator + guards
- [`ingest/embedder.py`](../../ingest/embedder.py) — embedder load sites (`_get_model`, `_get_tokenizer`)
- [`ingest/chunker.py`](../../ingest/chunker.py) — chunker tokenizer load site
- [`server/resources.py`](../../server/resources.py) — reranker load site
- [`server/retrieval/rerank.py`](../../server/retrieval/rerank.py) — `BGE_RERANKER_COMMIT_SHA` + `maybe_log_sha_drift`
- [`tools/sbom.sh`](../../tools/sbom.sh) — SBOM generation + grype scan
- [`tests/security/test_model_pinning.py`](../../tests/security/test_model_pinning.py) — full guard coverage

# E13 — Security Hardening

**Epic dependencies:** E07.

**Goal:** harden the seven threats from `08-security-observability-ops.md` § Threat model. Some mitigations land in earlier epics as inline acceptance criteria (path-traversal regex in E07_S12, prompt-injection delimiters in E07_S13, rate limits in E07_S10, content-length sanity in E11_S09); this epic is the consolidated audit-and-completion pass plus the cross-cutting controls that don't have a natural home elsewhere (model-weight pinning, sandboxing harness validation, SBOM, etc.).

**Effort:** ~1 week.

**References:** `08-security-observability-ops.md` § Threat model (the seven threats, in order); `06-mcp-server-design.md` § Spec compliance points.

---

### E13_S01 — Threat-1 audit: paper_id regex coverage

**Description.** Audit every tool that takes a paper_id (search_papers filters, get_chunk via chunk_id, get_paper, paper_diff, cite_neighbors, dependency_graph, expand_macro, find_equation, find_lemma_by_name, get_definitions). Confirm the path-traversal regex from E07_S12 is in place on every entry point.

**Acceptance criteria.**
- [ ] `tests/security/test_path_traversal.py` exercises every tool with `paper_id="../../../etc/passwd"` and asserts -32602 invalid params.
- [ ] Audit checklist in `docs/security/threat-1-audit.md` — each tool ticked.
- [ ] Any tool that currently fails the test gets a fix in the same PR.
- [ ] CI runs the audit test on every PR.

**Dependencies.** E07_S12, E10_S09.

**Complexity.** S.

**Labels.** `area:security`, `kind:infra`.

---

### E13_S02 — Threat-2 audit: prompt-injection delimiter coverage

**Description.** Audit every tool that returns retrieved content (search_papers, get_chunk, find_equation, paper_diff, cite_neighbors, dependency_graph). Confirm chunk bodies and equation atoms are wrapped in `<retrieved_chunk>` / `<retrieved_equation>` delimiters per E07_S13. Optional regex-based sanitization layer for known-bad patterns.

**Acceptance criteria.**
- [ ] `tests/security/test_delimiters.py` confirms every tool's response wraps retrieved content in the documented delimiters.
- [ ] Optional sanitization layer scrubs literal `<|system|>`, `[INST]`, "ignore previous instructions" patterns when configured on.
- [ ] Sanitization is configurable via `ARXMCP_SANITIZE_RETRIEVED_CONTENT` env var; default off.
- [ ] Documented in `docs/security/threat-2-audit.md`.
- [ ] Recommended orchestrator-side system prompt clause committed to `docs/orchestrator/recommended-system-prompt.md`.

**Dependencies.** E07_S13, E10_S09.

**Complexity.** S.

**Labels.** `area:security`, `kind:research`.

---

### E13_S03 — Threat-3: LaTeXML sandbox validation

**Description.** Validate the LaTeXML sandbox set up in E02_S02 actually enforces what we claim. Hostile-input test cases: infinite-loop macro, attempted file write outside whitelist, attempted network call. All should be contained; the worker should mark the paper as parser-failure.

**Acceptance criteria.**
- [ ] `tests/security/test_latexml_sandbox.py` includes 5 hostile fixture papers (infinite recursion, attempted shell-out via `\write18`, fork bomb, large memory allocation, attempted network call).
- [ ] Each test asserts the subprocess is killed within the documented timeout AND the host filesystem outside the whitelist is unmodified.
- [ ] On Docker: `--network=none` enforced via compose config and verified.
- [ ] On macOS (developer mode): `sandbox-exec` profile committed and tested.
- [ ] Documented in `docs/security/threat-3-audit.md`.

**Dependencies.** E02_S02, E11_S08.

**Complexity.** L.

**Labels.** `area:security`, `risk:high`.

---

### E13_S04 — Threat-4 audit: resource-exhaustion limits

**Description.** Audit every tool's bounded inputs and ensure JSON-Schema `maximum` is set. `k <= 50`, `depth <= 5` (dependency_graph), 100 result limit (cite_neighbors), 256 KB result byte cap (E06_S07), per-session rate limits (E07_S10). Add fault tests that try to bust each limit.

**Acceptance criteria.**
- [ ] `tests/security/test_resource_exhaustion.py` issues `k=10000`, `depth=100`, oversize filter lists; all rejected at validation.
- [ ] 256 KB cap test: a synthetic chunk that would exceed the cap is rewritten to `resource_link`.
- [ ] Rate limit test: 1500 calls in an hour from one session triggers limit at 1000.
- [ ] Documented in `docs/security/threat-4-audit.md`.

**Dependencies.** E07_S10, E06_S07, E06_S08.

**Complexity.** S.

**Labels.** `area:security`.

---

### E13_S05 — Threat-5: Origin / Host / DNS-rebinding hardening

**Description.** Beyond the basic Origin pin from E07_S01, add `Sec-Fetch-Site: none` enforcement and a configurable Origin allow-list. Add tests for DNS rebinding attacks (Host header that resolves to a public IP).

**Acceptance criteria.**
- [ ] `Sec-Fetch-Site` header rejected unless `none` or absent.
- [ ] Origin allow-list configurable via `ARXMCP_ALLOWED_ORIGINS`; default is empty (shim sends no Origin).
- [ ] Test: requests with public IP in Host header rejected with 403.
- [ ] Test: requests with subdomain `attacker.localhost` rejected.
- [ ] Documented in `docs/security/threat-5-audit.md`.

**Dependencies.** E07_S01.

**Complexity.** S.

**Labels.** `area:security`, `area:server`.

---

### E13_S06 — Threat-6: model commit SHA pinning and safetensors-only enforcement

**Description.** Per `08-security-observability-ops.md` Threat 6 — pin model commit SHAs (`BAAI/bge-m3@<sha>`), refuse `.bin`/pickle weights, run with `trust_remote_code=False`. Apply to embedder, reranker, summarizer client (Haiku is API-side; here we audit the local model loaders).

**Acceptance criteria.**
- [ ] Embedder loader rejects model loads where `revision` is not a 40-char SHA.
- [ ] Reranker loader same.
- [ ] Both refuse to load `.bin` weights — must be `.safetensors`.
- [ ] `trust_remote_code=False` is the default; only configurable on with explicit env var + log warning.
- [ ] Test: attempting to load with `revision="main"` fails with a clear error.
- [ ] Documented in `docs/security/threat-6-audit.md`; production model SHAs listed.

**Dependencies.** E06_S04, E06_S05.

**Complexity.** M.

**Labels.** `area:security`, `area:embedder`, `risk:high`.

---

### E13_S07 — Threat-7 audit: source ingestion TLS and content-length

**Description.** Per `08-security-observability-ops.md` Threat 7 — verify TLS on all source fetches (already default), refuse responses >100 MB (E11_S09 covered this). Add a regression test that a fixture server returning 200 MB is rejected. Optional: pin known fingerprint of arxiv.org's CA chain (rotated periodically).

**Acceptance criteria.**
- [ ] `tests/security/test_source_ingest.py` confirms TLS verification cannot be disabled via config.
- [ ] 200 MB synthetic response is rejected without exhausting memory.
- [ ] Documented CA-pinning approach in `docs/security/threat-7-audit.md`; pinning is OPT-IN behind a flag because CA rotation is operational toil.
- [ ] All HTTP clients in `ingest/sources/` use a single configured `httpx.Client` to ensure consistent TLS settings.

**Dependencies.** E11_S09.

**Complexity.** S.

**Labels.** `area:security`, `area:ingestion`.

---

### E13_S08 — Tool-result and request-input redaction in logs

**Description.** Per `08-security-observability-ops.md` § Logging — sensitive fields (full query text, chunk bodies) logged at DEBUG only, never at INFO or above. Add a redaction filter to the structured logger that drops these fields in the WARN/INFO path.

**Acceptance criteria.**
- [ ] `server/observability/log_filter.py::RedactionFilter` strips `query`, `body_canonical`, `body_raw_latex`, `mathml` from log records at log_level >= INFO.
- [ ] DEBUG-level logs include these fields when explicitly configured (`ARXMCP_LOG_LEVEL=DEBUG`).
- [ ] Test: a log record built with `event="search_papers"` and `query="..."` does NOT include the query at INFO.
- [ ] Test: same record at DEBUG includes the query.
- [ ] Documented in `docs/observability/log-redaction.md`.

**Dependencies.** E07_S08.

**Complexity.** S.

**Labels.** `area:observability`, `area:security`.

---

### E13_S09 — Localhost-only binding regression test

**Description.** Per `08-security-observability-ops.md` Threat 5 and `06-mcp-server-design.md` § Transport — server binds to `127.0.0.1` only. Add a regression test that an attempt to bind to `0.0.0.0` is refused unless an explicit unsafe-mode flag is set.

**Acceptance criteria.**
- [ ] Server config defaults: `ARXMCP_BIND_HOST=127.0.0.1`.
- [ ] Setting `ARXMCP_BIND_HOST=0.0.0.0` requires also setting `ARXMCP_UNSAFE_NETWORK_BIND=1`; otherwise the server refuses to start.
- [ ] Documented in `docs/security/binding.md` with strong warning.
- [ ] Inside Docker, the server still binds 0.0.0.0 inside the container but the `ports:` mapping in compose pins the host side to `127.0.0.1:7733:7733`.

**Dependencies.** E07_S09.

**Complexity.** S.

**Labels.** `area:security`, `area:infra`.

---

### E13_S10 — SBOM and dependency vulnerability scan

**Description.** Generate an SBOM (CycloneDX or SPDX) for both the server and ingest images and run a vulnerability scan as part of CI. This is a mitigation-of-last-resort for Threat 6 — supply-chain compromises propagate via dependencies, not just model weights.

**Acceptance criteria.**
- [ ] `tools/sbom.sh` generates CycloneDX for `server/` and `ingest/`.
- [ ] CI runs `grype` (or equivalent) against the SBOM and fails on critical CVEs.
- [ ] SBOMs committed under `docs/security/sbom/` for releases.
- [ ] Documented in `docs/security/supply-chain.md`.

**Dependencies.** E11_S08.

**Complexity.** M.

**Labels.** `area:security`, `kind:infra`.

---

### E13_S11 — Cumulative threat-model review

**Description.** Once E13_S01–S10 have landed, perform a single review pass against `08-security-observability-ops.md` § Threat model and confirm every documented mitigation is implemented and tested. Output is a tracking spreadsheet/markdown document.

**Acceptance criteria.**
- [ ] `docs/security/threat-model-coverage.md` lists each threat and links to the tests/code that mitigate it.
- [ ] Every threat has at least one automated test.
- [ ] Any gap surfaces as a follow-up issue (linked in the document).
- [ ] Document committed and reviewed.

**Dependencies.** E13_S01, E13_S02, E13_S03, E13_S04, E13_S05, E13_S06, E13_S07, E13_S08, E13_S09, E13_S10.

**Complexity.** S.

**Labels.** `area:security`, `kind:research`.

---

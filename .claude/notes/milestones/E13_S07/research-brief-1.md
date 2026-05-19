# Research Brief — E13_S07

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-19T01:38:00Z

## In-codebase context

### HTTP client enumeration

The codebase has **zero uses of `httpx.Client` or `httpx.AsyncClient`**. All source ingestion uses `urllib.request` with HTTPS URLs pinned at the call site:

- `ingest/ar5iv_fetch.py` — ar5iv HTML via `urllib.request.urlopen(request)` (HTTPS pinned)
- `ingest/graph_ingest.py` — OpenAlex API via `urllib.request.urlopen(request)` (HTTPS pinned)
- `ingest/inspire_ingest.py` — INSPIRE-HEP API via `urllib.request.urlopen(request)` (HTTPS pinned)
- `ingest/oai_delta.py` — OAI-PMH delta harvester via `urllib.request.urlopen(request)` (HTTPS pinned)
- `tools/arxiv_fetch.py` — arXiv e-print via `urllib.request.urlopen(request)` (HTTPS pinned)
- `tools/curate_seed.py` — seed corpus via `urllib.request.urlopen(request)` (HTTPS pinned)
- `tools/daily_metrics_report.py` — metrics endpoint via `urllib.request.urlopen(...)` (HTTPS pinned)

**No `ingest/sources/` directory exists.** The brief's reference to "all HTTP clients in `ingest/sources/`" is drift. The actual client sites are scattered across `ingest/` and `tools/`.

**No `verify=False` anywhere.** Grepped the entire codebase: zero instances of `verify=` parameter. `urllib.request.urlopen` has TLS verification enabled by default (no kwarg to disable it directly). The safe-by-default stance is **already enforced**.

### Content-length cap status (E11_S02 dependency claim)

The brief asserts "E11_S02 already enforces the 100 MB content-length cap." **This is FALSE.** E11_S02's implementation summary and code do NOT implement any 100 MB cap. The only content-length enforcement found in the codebase:

- `ingest/graph_ingest.py:OPENALEX_MAX_RESPONSE_BYTES = 5 * 1024 * 1024` (5 MB, OpenAlex-specific)
- `ingest/inspire_ingest.py:INSPIRE_MAX_RESPONSE_BYTES = 8 * 1024 * 1024` (8 MB, INSPIRE-specific)
- `ingest/intra_paper_refs.py:MAX_HTML_BYTES = 50 * 1024 * 1024` (50 MB, ar5iv HTML)

The 100 MB cap is **documented as a mitigation in `.claude/notes/08-security-observability-ops.md` § Threat 7** but not implemented anywhere. E13_S07 must deliver this cap from scratch. **Flag: dependency unmet.**

### Content-length enforcement pattern (ar5iv_fetch.py)

`ar5iv_fetch.py` reads the full response body with `body_bytes = response.read()` (line ~145) with no length limit or streaming. The HTTP response object's `content-length` header is never checked. A 200 MB ar5iv response would fully load into memory before any validation.

### Configuration and environment variable conventions

From `server/config.py` (E13_S05 precedent):

- Boolean flags use Pydantic `BaseSettings` with `env_prefix="ARXMCP_"`
- Example: `unsafe_network_bind: bool = False` ← parsed from `ARXMCP_UNSAFE_NETWORK_BIND`
- Pydantic 2.x auto-converts `"1"`, `"true"`, `"True"` to boolean `True` (standard behavior)
- Validators use `@model_validator(mode="after")` for multi-field logic (preferred over `@field_validator` to access all fields)

**Recommendation for CA-pinning flag:** `pin_arxiv_ca: bool = False` in `server/config.py`, parsed from `ARXMCP_PIN_ARXIV_CA`. Document the flag is opt-in (default False). No special parsing needed — Pydantic handles it.

### Doc placement correction (E13_S01–S06 precedent)

All prior E13 threat audits landed their documentation at **`.claude/docs/security-threat-N-audit.md`**, not `docs/security/threat-N-audit.md`. This aligns with CLAUDE.md §1 (docs/ reserved for operator-facing content) and established E13 precedent. The brief's reference to `docs/security/threat-7-audit.md` is **drift from implemented pattern**.

### Test structure precedent (E13_S01–S05)

- Security tests live under `tests/security/test_*.py`
- E13_S01 added `tests/security/__init__.py` (empty package marker)
- E13_S05 added `tests/security/test_bind_regression.py` (3 test cases)
- Test count delta is recorded in implementation-summary.md
- All audit tests run as part of `make test` (no CI — per CLAUDE.md §4.1)

### Makefile pattern (E13_S06 precedent: SBOM)

E13_S06 replaced CI lint rules with `Makefile sbom` target invoked manually before push. **Recommendation:** Add a `Makefile verify-no-verify-false` target that runs `grep -r "verify=False" ingest/ tools/` and exits 1 on match. Document in `.claude/docs/security-threat-7-audit.md` that developers must run `make verify-no-verify-false` before pushing.

### Threat 7 scope from threat model

From `.claude/notes/08-security-observability-ops.md` § Threat 7:

> "We fetch from arxiv.org and ar5iv.labs.arxiv.org. If either is compromised, we ingest poisoned content.
> 
> **Mitigations:**
> - Verify TLS certs (default for the HTTP client; do not disable).
> - Pin known fingerprint of arxiv.org's certificate authority chain (rotated periodically).
> - Content-length sanity checks (a single paper > 100 MB source is suspicious).
> - Sandbox the parser (Threat 3 mitigation covers downstream impact)."

**Load-bearing constraint:** "do not disable" TLS verification. The audit must verify no env var or config field can toggle TLS off.

### urllib.request TLS verification semantics

`urllib.request.urlopen` has TLS verification **enabled by default**. The only way to disable it is via a context manager (`urllib.request.ssl.SSLContext(check_hostname=False, verify_mode=ssl.CERT_NONE)`). No simple kwarg. The current code pattern is safe-by-default — **no active vulnerability, just unaudited.**

## Prior decisions and lessons

### E13_S01–S06 patterns (anchor points)

1. **Brief ↔ codebase drift is systematic.** E13_S01 found the 7-tool list was wrong in the brief (named `paper_diff` + `dependency_graph`, omitted `get_definitions` + `find_lemma_by_name`). E13_S03 found the sandbox was aspirational only. E13_S05 found Origin validation was already shipped in E06_S05. **This brief asserts E11_S02 shipped the 100 MB cap; verify first, assume nothing.**

2. **Fictional milestone dependencies.** E13_S01–S04 cited `E07_S12`, `E07_S13` as dependencies; E07 has only S01–S04. The audit milestone is **both spec and enforcement**. E13_S07 cites E11_S02; confirm that milestone actually delivered the cap before building tests around it.

3. **Doc placement is strict.** E13_S01 initially said `docs/security/threat-1-audit.md`; implemented at `.claude/docs/security-threat-1-audit.md` per CLAUDE.md §1. Same correction applies here.

4. **Makefile > CI.** The project has no CI (CLAUDE.md §4.1). E13_S06 replaced `CI lint rule` with `Makefile sbom` target. The brief's "CI lint rule: `grep -r "verify=False" ingest/` fails the build" must be reframed as a developer-run check (Makefile target or pytest gate).

5. **Test count delta is per-implementation record.** Prior implementations logged: commit range, test delta (+N tests), `ruff check .` status. E13_S07 should follow the same structure.

### Recent git log (E13 progression)

```
f535928 chore(notes): seed agent-memory from E13_S01-S05 runs
8e0084a chore(notes): finalize E13_S05 state -> complete
90a9318 rect(server,tests): close 5 findings from E13_S05 critique
de7904b feat(server,tests,docs): close Threat 5 Origin/DNS-rebinding hardening (E13_S05)
40576ef chore(notes): finalize E13_S04 state -> complete
```

E13_S05 landed 5 days ago; E13_S06 (model pinning) landed within the hour. The pattern is tight. E13_S07 should assume a populated `server/config.py` (where to add the CA-pinning flag) and existing test structure under `tests/security/`.

## External sources

No MCP spec changes needed (source ingestion is not a tool surface). No vendor docs required for `urllib.request` — it is stdlib. TLS/CA pinning is standard library `ssl` module territory.

arXiv CA rotation schedule is not documented publicly; `https://arxiv.org/about/terms-of-service` does not mention certificate pinning. **The brief's "arxiv.org CA chain rotates periodically" is anecdotal.** Recommend documenting the flag as aspirational / optional.

## Recommendation

**Approach:** This milestone is BOTH a gap-closure (implement the missing 100 MB cap) AND an audit (verify TLS cannot be disabled).

1. **Content-length cap: implement from scratch.** The brief incorrectly assumed E11_S02 shipped this. Add a module-level `MAX_SOURCE_BYTES = 100 * 1024 * 1024` constant in `ingest/ar5iv_fetch.py` and `ingest/oai_delta.py`. When reading the response body, check the `Content-Length` header first (reject if > 100 MB); only then read streaming with a size limit. Use `response.read(MAX_SOURCE_BYTES + 1)` and reject if `len(body) > MAX_SOURCE_BYTES`.

2. **TLS audit: formalize safe-by-default stance.** Add a Config field `verify_tls: bool = True` (always True; no escape hatch). Do NOT add `ARXMCP_VERIFY_TLS` as an env var — the audit's goal is "TLS cannot be disabled." Instead, add a startup log at DEBUG level confirming TLS verification is enabled. Cite this in the audit doc.

3. **CA-pinning flag: add as optional Config field.** `pin_arxiv_ca: bool = False`. When True, validate the peer certificate's subject against a hardcoded frozenset of allowed Common Names (e.g., `{"arxiv.org", "*.arxiv.org"}`). Document in the audit that CA pinning is optional; the default (False) is production-ready. The hardcoded pin must be accompanied by a deprecation note ("updates to arxiv.org's CA require manual config change").

4. **Test file: three test cases.**
   - AC1: Config validation that `ARXMCP_VERIFY_TLS=0` is rejected (or omitted from Config entirely to prevent misuse).
   - AC2: Fixture HTTP server returning 200 MB response → rejected at `Content-Length` check, zero bytes buffered into memory.
   - AC3: Grep check that no `verify=False` exists in ingest/ or tools/.

5. **Makefile target:** Add `verify-no-verify-false` that runs the grep check. Document in the audit that developers must run it before push.

6. **Doc placement:** `.claude/docs/security-threat-7-audit.md` (not `docs/security/...`). Cover: TLS default-enabled, Content-Length cap at 100 MB (per-client — ar5iv uses urllib, no shared client refactor needed), CA-pinning approach (optional, default off, hardcoded CN frozenset, requires manual update on CA rotation).

**Do NOT refactor urllib.request to a shared `httpx.Client`.** The brief's "single shared httpx.Client at module import time" is aspirational. The codebase already uses urllib across multiple modules with zero cross-dependencies. The cost of a refactor is higher than the benefit (urllib.request is safe-by-default for TLS). Document the status quo as acceptable.

## Open questions

1. **What is the exact ar5iv Content-Length header name and semantics?** The brief says "200 MB fixture response rejected" but does not specify: should the test use a mock HTTP server (e.g., `http.server`) or monkeypatch `urllib.request.urlopen`? Recommend mocking `urllib.request.urlopen` to return a response object with `headers={'Content-Length': '209715200'}` (200 MB in bytes), no actual body read.

2. **Should Config have a `verify_tls` field at all?** The audit goal is "cannot be disabled." Adding a field (even read-only True) risks future developers treating it as configurable. Alternative: omit the field entirely, log at startup "TLS verification enabled (built-in, cannot be disabled)", move on. **Recommended approach: omit the field.**

3. **Which arXiv certificate CNs should the CA-pinning frozenset contain?** The brief does not specify. If this flag ships, it must be based on live certificate inspection. This is **deferred to implementation phase** — researcher has no authority to inspect prod certs. Recommend: implement the flag architecture (Config bool + optional CN check), document that production values must be determined via certificate inspection, default to off.

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| git commit | `.claude/notes/milestones/E13_S07/state.json` | Milestone state checkpoint (orchestrator) |
| git commit | `ingest/ar5iv_fetch.py` + `ingest/oai_delta.py` | Content-length cap implementation |
| git commit | `server/config.py` (optional) | CA-pinning flag if implemented |
| git commit | `tests/security/test_source_ingest.py` | New test file (3 test cases) |
| git commit | `.claude/docs/security-threat-7-audit.md` | Audit documentation |
| git commit | `Makefile` | `verify-no-verify-false` target |

All commits are local (Phase 2 implementer responsibility). No external infra, no API calls.

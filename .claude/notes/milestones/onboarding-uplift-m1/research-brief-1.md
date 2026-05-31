# Research Brief — onboarding-uplift-m1

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-31T02:05:00Z

---

## In-codebase context

### 1. `_scan_unknown_arxmcp_env_vars` — full seam map

**Location:** `server/main.py:264-285`

**Full current implementation (verbatim):**

```python
def _scan_unknown_arxmcp_env_vars(config: Config) -> None:
    declared = {f"ARXMCP_{name.upper()}" for name in Config.model_fields}
    unknown = []
    for env_name in os.environ:
        if env_name.startswith("ARXMCP_") and env_name not in declared:
            unknown.append(env_name)
    if unknown:
        raise ValueError(
            f"unknown ARXMCP_* environment variables: {sorted(unknown)}. "
            f"Declared variables: {sorted(declared)}. A typo here would "
            f"silently bypass the documented config — fix or remove the "
            f"variable."
        )
```

**Call sites:**
- `server/main.py:476`: `_scan_unknown_arxmcp_env_vars(cfg)` inside `create_app()` — runs before `FastAPI(...)` is constructed.
- `server/main.py:754`: `_scan_unknown_arxmcp_env_vars(cfg)` in `__main__` path, after bare `Config()`.

**Exception and propagation:**
- Raises `ValueError`. In `create_app()`, this propagates up through `_build_module_app()` (`server/main.py:718-728`) which catches `Exception`, logs `FATAL during app construction: %s`, writes to stderr, and re-raises — uvicorn exits non-zero. In `__main__`, it is caught explicitly (`server/main.py:755-758`), logged, and `sys.exit(1)`.

**Declared variable set:** `Config.model_fields` yields Python field names → uppercased with `ARXMCP_` prefix. Verified count = **32 fields** (live run):
`ARXMCP_ALLOWED_ORIGINS`, `ARXMCP_ARXIV_CA_BUNDLE_PATH`, `ARXMCP_BIND_HOST`, `ARXMCP_BIND_PORT`, `ARXMCP_BM25_INDEX_ROOT`, `ARXMCP_CACHE_DB_PATH`, `ARXMCP_CORPUS_CHUNK_COUNT_TOLERANCE`, `ARXMCP_DATA_DIR`, `ARXMCP_ENABLE_LEAN`, `ARXMCP_ENABLE_RERANK`, `ARXMCP_EQ_TED_WEIGHT`, `ARXMCP_KUZU_PATH`, `ARXMCP_LAKE_PATH`, `ARXMCP_LANCEDB_PATH`, `ARXMCP_LEAN_REPL_DIR`, `ARXMCP_LEAN_RLIMIT_AS_BYTES`, `ARXMCP_LOG_FORMAT`, `ARXMCP_LOG_LEVEL`, `ARXMCP_MAX_CONCURRENT_EMBEDDINGS`, `ARXMCP_MAX_CONCURRENT_RERANKS`, `ARXMCP_NOTEBOOK`, `ARXMCP_NOTEBOOKS_DB_PATH`, `ARXMCP_OPS_DIR`, `ARXMCP_OTEL_ALLOW_REMOTE`, `ARXMCP_OTEL_ENDPOINT`, `ARXMCP_PIN_ARXIV_CA`, `ARXMCP_QUERY_EMBED_PROVIDER`, `ARXMCP_RERANK_MODEL_SHA`, `ARXMCP_RESULT_BYTE_CAP`, `ARXMCP_THEOREM_NAMES_DB_PATH`, `ARXMCP_UNSAFE_NETWORK_BIND`, `ARXMCP_VOYAGE_API_KEY`.

**Existing tests:** `tests/test_server_startup.py:1219-1253` — class `TestEnvVarScan`:
- `test_unknown_env_var_rejected` (line 1231): monkeypatches `ARXMCP_DOES_NOT_EXIST`, expects `ValueError` matching `"unknown ARXMCP_"`.
- `test_known_env_vars_pass` (line 1238): sets `ARXMCP_BIND_HOST` + `ARXMCP_BIND_PORT`, expects no raise.
- `test_create_app_rejects_unknown_env` (line 1247): sets `ARXMCP_BOGUS_VAR`, expects `ValueError` matching `"unknown ARXMCP_"`.

**Carve-out regression test already exists:** `tests/test_server_startup.py:357-383` — `test_contact_email_env_var_rejected`:
- Monkeypatches `ARXMCP_CONTACT_EMAIL=test@example.com`, calls `_scan_unknown_arxmcp_env_vars(cfg)`.
- **Currently asserts** `pytest.raises(ValueError, match="ARXMCP_CONTACT_EMAIL")`.
- **This test must be updated** in the milestone: the new behavior must still raise `ValueError` for `ARXMCP_CONTACT_EMAIL`, but the error message now contains the carve-out hint text rather than the raw `"unknown ARXMCP_*"` dump. The `match=` pattern must be updated to match the new message. Alternatively — keep the test's intent (still raises) and update `match=` to the new message pattern.

### 2. `Config` strict-typo guard

**`SettingsConfigDict` (verbatim, `server/config.py:79-83`):**
```python
model_config = SettingsConfigDict(
    env_prefix="ARXMCP_",
    env_file=None,  # ARXMCP_* env vars only — no .env-file fallback.
    extra="forbid",  # unknown ARXMCP_* vars are configuration errors.
)
```

**Note:** `extra="forbid"` fires only for direct `Config(unknown_field=...)` kwargs — NOT for env-var input. The `_scan_unknown_arxmcp_env_vars` function is the env-var layer's guard (verbatim from the function docstring: "pydantic-settings's `extra="forbid"` only fires for direct `__init__` kwargs — NOT for env-var input").

**`ARXMCP_CONTACT_EMAIL` confirmed absent:** `ARXMCP_CONTACT_EMAIL` is not in `Config.model_fields` (verified by live `python -c` run — it is not in the 32-element declared set).

**Validators that run at Config load (before `_scan_unknown_arxmcp_env_vars`):**
- `model_validator(mode="after") derive_notebook_lancedb_path` (line 432)
- `model_validator(mode="after") reject_non_loopback_bind` (line 539)
- `model_validator(mode="after") validate_arxiv_ca_bundle` (line 569)
- `model_validator(mode="after") validate_otel_endpoint_loopback` (line 736)
- `field_validator` on `bind_port`, `max_concurrent_*`, `eq_ted_weight`, `log_format`, `corpus_chunk_count_tolerance`, `result_byte_cap`, `query_embed_provider`

**Implication:** pydantic validators run FIRST during `Config()`, THEN `_scan_unknown_arxmcp_env_vars(cfg)` is called from `create_app()`. The error-message rewrite happens in `_scan_unknown_arxmcp_env_vars` only — no validator changes needed.

### 3. Doc-sweep targets — verbatim current text

**`CLAUDE.md:514-517` (the full "Start the MCP server" snippet):**
```bash
export ARXMCP_CONTACT_EMAIL=you@example.com
make up
```
Remove the `export ARXMCP_CONTACT_EMAIL=you@example.com` line. Keep `make up` and the surrounding Health lines.

**`README.md:48` (verbatim):**
```bash
export ARXMCP_CONTACT_EMAIL=you@example.com   # arXiv TOS §3 polite pool
python tools/fetch_seed.py                    # idempotent
```
Remove the `export ARXMCP_CONTACT_EMAIL=...` line. Keep `python tools/fetch_seed.py`.

**`Makefile` — all `ARXMCP_CONTACT_EMAIL` occurrences (grep result):**
- `Makefile:37`: `@echo "Before fetching from arXiv, export ARXMCP_CONTACT_EMAIL=<your-email>"`
- `Makefile:61-63` (bootstrap nag block):
  ```make
  @if [ -z "$$ARXMCP_CONTACT_EMAIL" ]; then \
      echo "WARNING: export ARXMCP_CONTACT_EMAIL=<your-email> before fetching from arXiv."; \
  fi
  ```
- `Makefile:180`: `@# Requires ARXMCP_CONTACT_EMAIL (User-Agent for /e-print/).` (comment in `ingest-recover-preambles`)

**Brief says to retarget lines 37, 62, 180, 191.** Line 191 was not in grep output; may be a line-count drift — implementer must `grep -n` for the actual context. Lines 37 and 61-63 are confirmed. The retargeting: replace generic "export ARXMCP_CONTACT_EMAIL before fetching from arXiv" with explicit naming of `tools/notebook_fetch.py` + `tools/recover_preambles.py` (NOT `make up`).

**`tools/README.md:14-17` (verbatim — KEEP, do not remove):**
```
Before running any of these, export your contact email (used in the `User-Agent` per arXiv TOS):

```sh
export ARXMCP_CONTACT_EMAIL=you@example.com
```
```
This is the correct context (running ingest tools). The brief explicitly says: "keep the export under `Run the ingest pipeline` (correct context)."

**`docs/install.md:218-219` (verbatim — already correct, DO NOT TOUCH):**
```
- **`ARXMCP_CONTACT_EMAIL`** is NOT needed by the server and is intentionally
  absent from the compose env; the v1 ingest service will require it.
```

### 4. MCP endpoint mount point — trailing slash behavior

**`server/_mcp_mount.py:34`:** `DEFAULT_MCP_PATH = "/mcp"`

**Mount mechanism (verbatim from `_mcp_mount.py:60-71`):**
```
Operators who hit ``/mcp`` (no trailing slash) get a 307
redirect to ``/mcp/`` from Starlette's standard trailing-slash
handling — both forms reach the same handler.
```

The mount: `app.mount(path, sub_app)` at `server/_mcp_mount.py:98`. The sub-app's internal route is `/`, prefix is `/mcp`, so effective path is `/mcp/`.

**Behavior summary for docs note:** `GET /mcp` → 307 → `/mcp/`; `POST /mcp` with body → 307 → body dropped by some clients. Both are informational for the troubleshooting note. **We are NOT changing the mount behavior** — docs note only.

**Where to add in `docs/install.md`:**
- MCP-client registration block: around line 144 (the `{ "mcpServers": { "arxmcp": ...` JSON block). The shim uses `http://127.0.0.1:7733` and the `arxmcp-shim` handles trailing slashes internally, so no user-visible issue for Claude Code. Add a note explaining why `--server http://127.0.0.1:7733` (no `/mcp/` suffix) works — the shim constructs the full URL.
- Troubleshooting table: `docs/install.md:305-310`. Current table has 4 rows. Add row: Symptom=`curl POST /mcp hangs or returns empty`, Likely cause=`Missing trailing slash — /mcp 307s to /mcp/; POST bodies are dropped on redirect by most HTTP clients`, Fix=`Use /mcp/ (with trailing slash) in direct curl/HTTP calls; the stdio shim handles this automatically`.

### 5. Existing test surface

Tests that PIN the current error message and must be updated or understood:

**`tests/test_server_startup.py:1231-1236`:**
```python
with pytest.raises(ValueError, match="unknown ARXMCP_"):
    _scan_unknown_arxmcp_env_vars(Config(bind_host="127.0.0.1"))
```
After the rewrite, `ARXMCP_DOES_NOT_EXIST` still raises `ValueError` but with a close-match or short-hint message instead of the 30-var dump. The `match="unknown ARXMCP_"` pattern should still pass if the new message retains the phrase "unknown ARXMCP_". **Verify before landing.**

**`tests/test_server_startup.py:382`:**
```python
with pytest.raises(ValueError, match="ARXMCP_CONTACT_EMAIL"):
```
This pins that `ARXMCP_CONTACT_EMAIL` appears in the error message. After the rewrite, the carve-out message will explicitly mention `ARXMCP_CONTACT_EMAIL` (by design), so this `match=` continues to pass. **No update needed for the `match=` pattern itself.**

### 6. BP1/BP2 byte-stability cross-check

This milestone touches: `server/main.py` (error message in `_scan_unknown_arxmcp_env_vars`), `CLAUDE.md`, `README.md`, `Makefile`, `tools/README.md`, `docs/install.md`. **None of these touch:**
- `server/tools.py::ALL_TOOLS` (no tool added/removed/modified)
- `server/prompts.py` (no prompt string changed)

**Pinned hashes (implementer must confirm unchanged after landing):**

`tests/test_server_tool_schema.py:94-96`:
```python
EXPECTED_TOOL_SCHEMA_SHA256: str = (  # UPDATE-ANCHOR — do not delete
    "c7df4c5c10c86693ac8553b7d079b55fba21749881c233f0f298955379d13375"
)
```

`tests/test_prompts.py:649-651`:
```python
EXPECTED_BP1_SHA256 = (
    "483344e3fcdea1d64de893cc669c9f142fd6f1198d4c8d383cd9c232558959bc"
)
```

**Both hashes must remain unchanged.** Run `uv run python -m pytest tests/test_server_tool_schema.py tests/test_prompts.py --tb=short` to confirm.

### 7. Design notes that apply

**`06-mcp-server-design.md`** is not directly load-bearing for the error-message rewrite. The server design note documents the 7-tool surface and the `EXPECTED_TOOL_SCHEMA_SHA256` discipline — both untouched.

**`01-mission-and-context.md`** frames the operator as a technical single-user. The error-message improvement aligns with "minimal interruption / autonomous execution" (CLAUDE.md §12): the new message is still a hard error (correct) but actionable (improved). No constraint from the design constitution prevents the error-message improvement.

**`08-security-observability-ops.md`** is not touched by this milestone. The error message is startup-only; no security surface is affected.

---

## Prior decisions and lessons

**Recent git log (last 20):** Most recent commit is `be099b3 docs(notes): land startup-ux uplift briefs + decisions` — this is the commit that landed the critique file at `.claude/notes/uplift/startup-ux/current-state-critique.md`. No parallel session is touching `server/main.py`, `server/config.py`, `CLAUDE.md`, `README.md`, `Makefile`, or `docs/install.md` — confirmed by log inspection. **No collision risk.**

**Adjacent milestone artifacts:** Only `state.json` exists at `.claude/notes/milestones/onboarding-uplift-m1/` — no prior research artifacts. Phase is `research-running`.

**Existing carve-out test:** `test_contact_email_env_var_rejected` (line 357) already documents the BLOCKER — its comment explicitly says "If we ever DO want to accept the env var on the server side (option (b) in the F1 fix tree — declare a no-op `contact_email: str | None = None` field), invert this test...". The milestone brief picks option (a): keep rejection, improve the message. The test's `match="ARXMCP_CONTACT_EMAIL"` pattern should still pass after the rewrite (the new carve-out message explicitly names `ARXMCP_CONTACT_EMAIL`).

**Pattern from `test_compose_server.py:121`:** That file already contains: "the server Config forbids unknown ARXMCP_* vars. It must NOT be in..." — indicating the existing ecosystem knows and documents that `ARXMCP_CONTACT_EMAIL` is not a server var. The regression guard is already present; the milestone just improves the human-visible output.

---

## External sources

The MCP spec (`modelcontextprotocol.io/specification/2025-06-18`) and Anthropic prompt-caching docs are not relevant to this milestone. It is purely local: error-message text + doc edits + one troubleshooting row. No caching or tool-schema changes.

Python stdlib `difflib.get_close_matches` is the recommended close-match engine (already imported in many Python stdlib usages; no new dep). Standard usage: `difflib.get_close_matches(unknown_var, declared, n=3, cutoff=0.6)`.

---

## Recommendation

**Use `difflib.get_close_matches` with a 0.6 cutoff and n=1 for the close-match path; render the `ARXMCP_CONTACT_EMAIL` carve-out as a hardcoded `if env_name == "ARXMCP_CONTACT_EMAIL"` branch executed before the close-match lookup.** This is the simplest approach that satisfies all ACs without over-engineering: the carve-out fires first (exact string comparison, no regex), the close-match path fires for other unknowns, and the fallback to a "top-3 closest known vars" hint fires when `get_close_matches` returns empty. The full 32-var dump is eliminated in all branches.

Structure of the new `_scan_unknown_arxmcp_env_vars`:
1. Build `declared` set as now.
2. Collect `unknown` list as now.
3. For each unknown, build an individual error message:
   - If `env_name == "ARXMCP_CONTACT_EMAIL"`: emit the carve-out message naming `tools/notebook_fetch.py`, `tools/recover_preambles.py`, `ingest/inspire_ingest.py`.
   - Elif `difflib.get_close_matches(env_name, declared, n=1, cutoff=0.6)`: emit `did you mean ARXMCP_XYZ?`
   - Else: emit a short hint listing top-3 closest (`get_close_matches(env_name, declared, n=3, cutoff=0.0)`) or a pointer to `server/config.py` for the full list.
4. Raise `ValueError` with all per-var messages joined.

**Doc sweep:** Remove the `export ARXMCP_CONTACT_EMAIL=you@example.com` line from `CLAUDE.md:515` and `README.md:48`. Retarget `Makefile:37` and the bootstrap nag block (`Makefile:61-63`) to explicitly mention `tools/notebook_fetch.py` and `tools/recover_preambles.py` as the tools that need the var. The comment at `Makefile:180` can be left as-is (it correctly describes `ingest-recover-preambles`).

**Trailing-slash docs:** Add one inline note after the `docs/install.md:144` MCP-client JSON block and one row to the troubleshooting table at `docs/install.md:305-310`. Do not change any server code.

---

## Open questions

No open questions — implementation can proceed on the above recommendation.

The one potential landmine to verify before committing: confirm that the new close-match error message for `ARXMCP_DOES_NOT_EXIST` still matches the regex `"unknown ARXMCP_"` so `test_unknown_env_var_rejected` passes without update. If the new message drops that prefix, update the test's `match=` pattern to the new text. Either outcome is correct; the implementer should decide the message wording and update the test accordingly.

---

## External writes the implementation will require

None — this milestone is purely local.

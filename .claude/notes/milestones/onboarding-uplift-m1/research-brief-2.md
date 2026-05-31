# Research Brief — onboarding-uplift-m1

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-30T00:00:00Z
**Focus:** Failure-mode analysis + external sources

---

## In-codebase context

### The existing `_scan_unknown_arxmcp_env_vars` implementation

`server/main.py` lines 264–285 (verbatim):

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

Key observations:
- Uses `Config.model_fields` to enumerate declared fields — this is correct and dynamic; adding a new Config field automatically extends `declared`. No hardcoded list exists. FM-5 is NOT a real risk here.
- The error currently dumps the full sorted declared set. This is the "30-line dump" that the brief wants replaced.
- The carve-out for `ARXMCP_CONTACT_EMAIL` does not yet exist.

### Startup ordering (FM-3 analysis)

Reading `server/main.py::_build_module_app` (lines 717–730):

```python
def _build_module_app() -> FastAPI:
    try:
        return create_app()
    except Exception as exc:
        logger.error("FATAL during app construction: %s", exc)
        sys.stderr.write(f"FATAL: {exc}\n")
        raise
```

`create_app` calls `_scan_unknown_arxmcp_env_vars(cfg)` at line 476. Logging is configured via `logging.basicConfig(level=...)` at line 751 ONLY in the `if __name__ == "__main__"` branch. The module-level `app = _build_module_app()` path (uvicorn import) does NOT call `logging.basicConfig`. This means:

**FM-3 is REAL:** when uvicorn imports `server.main:app`, the scan runs at module-import time with NO logging configured. The `logger.error(...)` call in `_build_module_app` writes to the root logger, which by default has no handlers (stderr is not configured until `logging.basicConfig` runs). The error message reaches the user ONLY via `sys.stderr.write(f"FATAL: {exc}\n")` at line 726. Pydantic stack traces do not appear because `raise` re-raises the ValueError from the scan, not a Pydantic error. The user sees one line on stderr: `FATAL: unknown ARXMCP_* environment variables: ...`.

### Existing tests that will break or pass through

`tests/test_server_startup.py` lines 357–383: `test_contact_email_env_var_rejected` asserts:
```python
with pytest.raises(ValueError, match="ARXMCP_CONTACT_EMAIL"):
    _scan_unknown_arxmcp_env_vars(cfg)
```
This test MUST be UPDATED — after the carve-out, `ARXMCP_CONTACT_EMAIL` must NOT raise. The test documents the old behavior and must be inverted.

`tests/test_server_startup.py` lines 1231–1253 (`TestEnvVarScan`):
- `test_unknown_env_var_rejected`: `match="unknown ARXMCP_"` — safe; the new message must still contain this substring.
- `test_known_env_vars_pass`: passes through unchanged.
- `test_create_app_rejects_unknown_env`: `match="unknown ARXMCP_"` — safe.

**No test asserts the full declared-vars list format** (the 30-line dump). The replacement is safe from test-pinning perspective.

### `ARXMCP_CONTACT_EMAIL` grep — comprehensive hit list

Running `grep -rn 'ARXMCP_CONTACT_EMAIL' --include='*.md' --include='Makefile' --include='*.py'` from repo root yields:

**Server-startup context (MUST be swept):**
- `Makefile:37` — `make help` message: `"Before fetching from arXiv, export ARXMCP_CONTACT_EMAIL=<your-email>"`
- `Makefile:61–62` — bootstrap nag: `"WARNING: export ARXMCP_CONTACT_EMAIL=<your-email> before fetching from arXiv."`
- `README.md:48` — Quick start step 2: `export ARXMCP_CONTACT_EMAIL=you@example.com   # arXiv TOS §3 polite pool`
- `CLAUDE.md:515` — quick-start snippet: `export ARXMCP_CONTACT_EMAIL=you@example.com`
- `docs/install.md:218–219` — Docker Compose notes: `**ARXMCP_CONTACT_EMAIL** is NOT needed by the server and is intentionally absent from the compose env` — **this is ALREADY correct; do not change it**

**Ingest-pipeline context (must NOT be swept — correct references):**
- `tools/fetch_seed.py:8,23`
- `tools/recover_preambles.py:17,236,238,240`
- `tools/arxiv_fetch.py:97,101,104`
- `tools/fetch_one_paper.py:8`
- `tools/notebook_fetch.py:17,49,84,91,93`
- `tools/curate_seed.py:20`
- `tools/README.md:17` — **brief explicitly preserves this**

### Shim `/mcp/` analysis

`shim/arxmcp_shim.py` line 141: `conn.request("POST", "/mcp/", body=body, headers=h)` — the shim already uses the trailing-slash form. The note in `docs/install.md` must explain that FastAPI/Starlette redirects `POST /mcp` (no slash) to `GET /mcp/` (with slash), which breaks non-idempotent POST — not a spec mandate. The MCP spec says "a single HTTP endpoint path... for example, `https://example.com/mcp`" (no trailing slash in the example). The trailing slash behavior is a FastAPI mount idiosyncrasy, not a spec requirement.

---

## Prior decisions and lessons

- `test_contact_email_env_var_rejected` (line 357) is a regression guard that documents the CURRENT behavior (reject). After this milestone, it must be INVERTED to assert acceptance (the carve-out). This is a load-bearing test flip, not a delete.
- `Config.model_fields` is already the correct dynamic enumeration source — the existing implementation is already safe against FM-5.
- The `docs/install.md:218` line about `ARXMCP_CONTACT_EMAIL` not being needed is already correct. The sweep must not touch it.
- `EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` are unchanged by this milestone (no MCP tool changes, no `server/prompts.py` changes).

---

## External sources

### Python 3.12 `difflib.get_close_matches` (https://docs.python.org/3.12/library/difflib.html#difflib.get_close_matches)

Signature (verbatim from docs):
```
difflib.get_close_matches(word, possibilities, n=3, cutoff=0.6)
```

Parameter semantics (verbatim):
- **word**: A sequence for which close matches are desired (typically a string)
- **possibilities**: A list of sequences against which to match word (typically a list of strings)
- **n** (default 3): The maximum number of close matches to return; n must be greater than 0
- **cutoff** (default 0.6): A float in the range [0, 1]. Possibilities that don't score at least that similar to word are ignored

SequenceMatcher ratio used: **2.0 * M / T**, where T is the total number of elements in both sequences, and M is the number of matches. Ratio 1.0 = identical, 0.0 = nothing in common.

**Recommended tuning for this use case: `n=1, cutoff=0.7`**

Justification: We want at most one suggestion (the best match). Cutoff 0.6 is too permissive — `ARXMCP_BIND_HOTS` (7 chars) vs `ARXMCP_BIND_HOST` (16 chars) scores above 0.6 but also risks false-positive suggestions for entirely unrelated typos. `0.7` filters noise while capturing transposed/dropped characters. If no match clears 0.7, fall back to "Unknown ARXMCP_BIND_HOTS — see `make help` for declared vars." The short-form fallback is explicitly specified in the brief.

### Pydantic-settings `extra="forbid"` and env-var pipeline

Per https://docs.pydantic.dev/latest/concepts/pydantic_settings/:

> "Pydantic settings consider `extra` config in case of dotenv file. It means if you set the `extra=forbid` on `model_config` and your dotenv file contains an entry for a field that is not defined in settings model, it will raise `ValidationError`"

**Critical: `extra="forbid"` only fires for direct `__init__` kwargs AND dotenv-file input — NOT for raw `os.environ` values.** When pydantic-settings reads env vars, it looks up each declared field by `env_prefix + field_name`, ignores anything else, and silently discards unknown env keys. This is why `_scan_unknown_arxmcp_env_vars` exists as a belt-and-suspenders check.

Field-to-env-var mapping: `env_prefix="ARXMCP_"` prepended to `field_name.upper()`. So `Config.model_fields` keys (e.g. `"bind_host"`) map to `ARXMCP_BIND_HOST`. The scan's `{f"ARXMCP_{name.upper()}" for name in Config.model_fields}` is the correct inverse mapping.

**Implication for FM-5:** because the scan derives `declared` from `Config.model_fields` dynamically at call time, adding a new Config field automatically extends the declared set. No hardcoded count or list exists. FM-5 is not a real risk in the current implementation.

### MCP spec — trailing slash

Per https://modelcontextprotocol.io/specification/2025-06-18/basic/transports (Streamable HTTP section):

> "The server **MUST** provide a single HTTP endpoint path (hereafter referred to as the **MCP endpoint**) that supports both POST and GET methods. For example, this could be a URL like `https://example.com/mcp`."

The spec example uses `/mcp` WITHOUT a trailing slash. The spec imposes NO requirement for a trailing slash. The trailing-slash behavior is a **FastAPI/Starlette mount idiosyncrasy**: when FastMCP mounts at `/mcp`, Starlette's router internally treats the prefix as `/mcp/`, so a POST to `/mcp` (no slash) receives a 307 redirect to `/mcp/`. For POST requests, a 307 causes the client to repeat the POST to the new location — most HTTP clients handle this transparently for GET but may drop the body for POST. The `docs/install.md` note must say: "The shim posts to `/mcp/` (with trailing slash). If you build a custom client, use `/mcp/` directly to avoid a redirect."

---

## Failure Mode Analysis

### FM-1: `difflib.get_close_matches` wrong closest match

**Trigger:** A typo like `ARXMCP_BIND_HOTS` (transposed T and S) is closer by SequenceMatcher ratio to `ARXMCP_BIND_HOST` (correct), but a pathological case could score higher against a different declared var (e.g. if a short typo like `ARXMCP_K` somehow scored well against `ARXMCP_KUZU_PATH`).

**Symptom:** User is told "Did you mean ARXMCP_KUZU_PATH?" for a clearly bind-host typo, leading to confusion.

**Mitigation:** Use `n=1, cutoff=0.7`. At 0.7 cutoff, a random 2-char string is unlikely to score against a long declared var name. Testing with `difflib.get_close_matches("ARXMCP_BIND_HOTS", declared_vars, n=1, cutoff=0.7)` should return `["ARXMCP_BIND_HOST"]` — verify this in the new test. If no match exceeds 0.7, emit the short-form fallback (no suggestion). Do not invent a suggestion.

### FM-2: Both `ARXMCP_CONTACT_EMAIL` and a real typo set simultaneously

**Trigger:** User has `ARXMCP_CONTACT_EMAIL=foo` in their shell AND types `ARXMCP_BIND_HOTS=bar`. Both are unknown.

**Symptom:** The error must enumerate BOTH clearly — one with the carve-out message, one with the close-match suggestion. If the implementation processes the carve-out separately and only processes the remainder through `get_close_matches`, it must NOT collapse the two into a single message.

**Mitigation:** Partition the unknown list: `carve_outs = {name for name in unknown if name in KNOWN_INGEST_VARS}`, then `genuine_typos = [n for n in unknown if n not in KNOWN_INGEST_VARS]`. Emit carve-out vars first with a clear "not a server config var" note, then typos with suggestions. A single `ValueError` with multi-line content is fine; do not raise two exceptions.

### FM-3: Error fires before logging is configured

**Trigger:** `make up` / `python -m server.main` (the `__main__` path) calls `logging.basicConfig` BEFORE `Config()` + the scan, so that path is fine. But `uvicorn server.main:app` imports the module and runs `_build_module_app()` at import time, before `basicConfig` is called.

**Symptom:** `logger.error("FATAL during app construction: %s", exc)` writes to an unconfigured root logger — the error goes to `stderr` only via `sys.stderr.write(f"FATAL: {exc}\n")` at line 726. Users see exactly ONE line on stderr. The new contextual error message must therefore be terse enough to read on a single stderr line. A multi-paragraph message is inappropriate; aim for ≤3 lines.

**Mitigation:** Confirmed: write the new error message to fit in a few lines. The difflib suggestion and carve-out message must each be compact.

### FM-4: Regression test brittle on wording change

**Trigger:** Someone refactors the carve-out message slightly ("ARXMCP_CONTACT_EMAIL is an ingest var" → "ARXMCP_CONTACT_EMAIL belongs to the ingest pipeline"). A test asserting the full sentence breaks.

**Symptom:** Test red for the wrong reason; implementer cannot tell if behavior is broken or just wording changed.

**Mitigation:** Assert these independent predicates, not full sentences:
1. `ARXMCP_CONTACT_EMAIL` appears in the error message (variable NAME is present)
2. The phrase "not a server config" OR "ingest" appears in the error message (category signal)
3. For typo test: `ARXMCP_BIND_HOTS` is in the error AND `ARXMCP_BIND_HOST` appears as the suggestion

Use `match=r"ARXMCP_CONTACT_EMAIL"` and a second `match=r"ingest|not.*server"` assertion. Do NOT assert the full sentence.

### FM-5: New Config field added post-milestone breaks hardcoded declared count

**Trigger:** Developer adds a new `Config` field after this milestone.

**Symptom:** If the implementation used a hardcoded list or count of declared vars, the new field would not appear in `declared` and a user setting it would see a false "unknown" error.

**Mitigation (ACTUAL STATUS — NOT A RISK):** The current implementation uses `Config.model_fields` dynamically. The new implementation MUST preserve this — do not replace `{f"ARXMCP_{name.upper()}" for name in Config.model_fields}` with a hardcoded set. The `KNOWN_INGEST_VARS` carve-out set (e.g. `{"ARXMCP_CONTACT_EMAIL"}`) is a SEPARATE hardcoded list of known-ingest vars that are NOT on `Config`. This carve-out set is small and stable; document that adding to it requires a code change.

### FM-6: Doc sweep too narrow — missed references

**Trigger:** Implementer greps only for `ARXMCP_CONTACT_EMAIL` in `.md` files and misses non-Markdown occurrences.

**Comprehensive grep result** (all hits from `grep -rn 'ARXMCP_CONTACT_EMAIL' --include='*.md' --include='Makefile' --include='*.py' .`):

Server-startup references to sweep:
- `Makefile:37` — `make help` nag (retarget to ingest context)
- `Makefile:61–62` — bootstrap warning (retarget to ingest context)
- `README.md:48` — quick-start step 2 (remove the `export ARXMCP_CONTACT_EMAIL=...` line; the fetch command can document it inline)
- `CLAUDE.md:515` — quick-start snippet (remove the `export` line)

Already-correct references (do NOT touch):
- `docs/install.md:218–219` — "ARXMCP_CONTACT_EMAIL is NOT needed by the server and is intentionally absent from the compose env"
- All `tools/` files — ingest-pipeline context, correct

**FM-6 mitigation:** Run the exact grep above before committing the doc sweep. The brief says to retain `tools/README.md`; the grep confirms its reference is ingest-pipeline context (correct).

### FM-7: `docs/install.md` client-registration snippet contradicts new trailing-slash note

**Trigger:** The registration block at `docs/install.md` line 142 registers the shim with `"args": ["--server", "http://127.0.0.1:7733"]` (no `/mcp/` suffix in the server URL — the shim appends the path itself). The shim hardcodes `/mcp/` at line 141. So the registration snippet is correct for the shim.

**The contradiction risk:** if the new note says "always use `/mcp/` in your client" and the registration block shows `http://127.0.0.1:7733` (the base URL, not the MCP path), a reader might think these are inconsistent.

**Mitigation:** The note must be phrased as: "The shim transparently appends `/mcp/` to the base `--server` URL. If you build a custom HTTP client directly (not via the shim), POST to `http://127.0.0.1:7733/mcp/` with the trailing slash to avoid a redirect." The registration block does not need to change. The Troubleshooting table row should say: "Custom client gets 307 redirect on POST" → "Use `/mcp/` (trailing slash); the redirect converts POST to GET, breaking the protocol."

### FM-8: New regression tests accidentally gated behind `requires_model`

**Trigger:** The new tests import something from `server.main` that triggers eager model load (e.g. importing `create_app` which imports `Resources`).

**Symptom:** Tests are skipped in `make test` because `requires_model` gates them.

**Mitigation:** The new tests for the carve-out and close-match MUST call `_scan_unknown_arxmcp_env_vars` directly (already the pattern in `TestEnvVarScan`). They must NOT call `create_app` or `Resources.startup`. Use `monkeypatch.setenv` + `Config()` + `_scan_unknown_arxmcp_env_vars(cfg)` exactly as the existing tests do. No `@pytest.mark.requires_model` marker. Verify `make test` runs them without any env vars.

### FM-9: Makefile bootstrap nag change breaks a grep in pre-commit or CI

**Trigger:** A pre-commit hook or CI step greps for the old wording `"WARNING: export ARXMCP_CONTACT_EMAIL=<your-email> before fetching from arXiv."` to verify the bootstrap nag is present.

**Symptom:** Pre-commit hook fails after the nag wording changes.

**Mitigation:** Search for any such greps before committing. Running `grep -rn 'ARXMCP_CONTACT_EMAIL.*before fetching' --include='*.sh' --include='*.yml' --include='*.yaml' .` finds nothing in this repo. The only CI references are in the Makefile itself. No pre-commit hook checks for this wording. **Not a real risk in this codebase** — but verify with the grep before landing.

---

## Recommendation

Implement the error-message rewrite as follows:

1. Add a small `KNOWN_INGEST_VARS = frozenset({"ARXMCP_CONTACT_EMAIL"})` constant in `server/main.py` near `_scan_unknown_arxmcp_env_vars`. Frozenset is appropriate (immutable, O(1) lookup).

2. In `_scan_unknown_arxmcp_env_vars`: partition `unknown` into `carve_outs` (in `KNOWN_INGEST_VARS`) and `genuine_unknowns` (the rest). Build the error message with `difflib.get_close_matches(name, sorted(declared), n=1, cutoff=0.7)` for each genuine unknown. If a match is found, emit `"ARXMCP_BIND_HOTS is not a config var — did you mean ARXMCP_BIND_HOST?"`. If no match, emit `"ARXMCP_BOGUS is not a config var (no close match found)"`. Carve-outs get `"ARXMCP_CONTACT_EMAIL is an arXiv ingest var (tools/arxiv_fetch.py), not a server config var — remove it from the server environment"`.

3. Invert `test_contact_email_env_var_rejected` to assert NO exception is raised for `ARXMCP_CONTACT_EMAIL` (and add a note explaining the inversion).

4. Add two new tests in `TestEnvVarScan`:
   - `test_contact_email_carve_out_accepted`: sets `ARXMCP_CONTACT_EMAIL`, asserts no ValueError.
   - `test_close_match_suggestion`: sets `ARXMCP_BIND_HOTS`, asserts ValueError message contains both `"ARXMCP_BIND_HOTS"` and `"ARXMCP_BIND_HOST"`.

5. Doc sweep (in order): `README.md`, `CLAUDE.md`, `Makefile` (both lines). Leave `tools/README.md`, all `tools/*.py`, and `docs/install.md:218–219` unchanged.

6. Add to `docs/install.md` Troubleshooting table: a row for "POST to `/mcp` (no trailing slash) fails or redirects" and a note in the registration block section. Do NOT touch the existing shim registration snippet (it uses the base URL, not the MCP path).

---

## Open questions

No open questions — implementation can proceed on the above recommendation.

---

## External writes the implementation will require

None — this milestone is purely local.

# Research Synthesis — onboarding-uplift-m1

**Merged from:** research-brief-1.md (seam map + verbatim file:line evidence)
+ research-brief-2.md (external sources + 9 failure modes + Python docs
quotes).
**Generated:** 2026-05-31.
**Verdict:** INLINE — ~5 files, ~40 LOC main delta + tests + doc edits. No new
architecture. Purely local. **Two D-divergences resolved in §3.**

---

## 1. The locked design

The fix is concentrated in **one function** + a **doc sweep across 4 files** +
**one troubleshooting-table row**. No MCP-surface touch; both BP1/BP2 hashes
stay frozen.

**File deltas:**

- **`server/main.py`** — rewrite `_scan_unknown_arxmcp_env_vars` (lines 264-285)
  to use a `KNOWN_INGEST_VARS` frozenset for carve-outs + `difflib.get_close_matches`
  for typo hints + short-form fallback. The function still **raises `ValueError`**
  in all unknown-var cases (per AC1 wording "produces a CLEAR error message…
  telling the user to unset it" — see §3 D1). Touch ~30 LOC.
- **`tests/test_server_startup.py`** — extend `TestEnvVarScan` with the
  close-match regression test + a doc-update to the existing
  `test_contact_email_env_var_rejected`'s comment (the test ITSELF still passes
  because the new carve-out message still names `ARXMCP_CONTACT_EMAIL` and the
  `match="ARXMCP_CONTACT_EMAIL"` regex continues to match). Two tests added.
- **`CLAUDE.md`** — drop line 515's `export ARXMCP_CONTACT_EMAIL=you@example.com`
  from the "Start the MCP server (local dev)" snippet.
- **`README.md`** — drop line 48's `export ARXMCP_CONTACT_EMAIL=...` from the
  quick-start.
- **`Makefile`** — retarget the bootstrap nag at lines 37 + 61-63 to name
  `tools/notebook_fetch.py` + `tools/recover_preambles.py` explicitly (NOT
  `make up`). Line 180 is already a correct ingest-context comment; leave it.
  (R1 flagged that brief's line 191 is a count-drift; verified — no occurrence
  there.)
- **`docs/install.md`** — add the `/mcp/` trailing-slash note in TWO places:
  one inline note after the registration block (~line 144) explaining the shim
  appends `/mcp/` transparently, and one row to the Troubleshooting table
  (~lines 305-310) explaining the FastAPI mount idiosyncrasy. **Do NOT touch
  lines 218-219** (already-correct compose-env note).

**File deltas NOT to touch:**

- `tools/README.md:14-17` — correct ingest-pipeline context, KEEP.
- `docs/install.md:218-219` — correct compose-env note, KEEP.
- `server/config.py` — UNCHANGED. The fix is at the env-var SCAN layer, not the
  Pydantic Config layer. `Config.model_fields` remains the dynamic source of
  truth (FM-5 is not a real risk — R2 confirms).
- `shim/arxmcp_shim.py` — UNCHANGED. The shim already POSTs to `/mcp/` with
  the trailing slash (R2 confirmed at `shim/arxmcp_shim.py:141`).
- Every `tools/*.py` file referencing `ARXMCP_CONTACT_EMAIL` — UNCHANGED.
  These are correct ingest-pipeline references.

---

## 2. Load-bearing facts (both briefs concur, live-verified)

- **The declared-var count is 32, not ~30** (R1 live-verified). The current
  error dump enumerates 32 sorted variable names — that's the "30-line dump"
  the brief targets.
- **`_scan_unknown_arxmcp_env_vars` is called from TWO sites** (R1, verbatim
  from source):
  - `server/main.py:476` inside `create_app()` (the uvicorn-import path)
  - `server/main.py:754` in `__main__` (the `python -m server.main` path)
- **The function raises `ValueError`.** The propagation paths differ:
  - From `create_app()`: caught by `_build_module_app()` (lines 717-730),
    logged as `FATAL during app construction: %s` AND written to `sys.stderr`
    via `sys.stderr.write(f"FATAL: {exc}\n")`, then re-raised → uvicorn exits
    non-zero.
  - From `__main__`: caught explicitly (lines 755-758), logged, `sys.exit(1)`.
- **`extra="forbid"` on `Config` does NOT fire for env-var input.** R2
  authoritatively quotes the pydantic-settings docs: forbid only fires for
  dotenv input + direct kwargs. The scan is the env-var layer's belt-and-suspenders
  check.
- **`Config.model_fields` is the dynamic enumeration source.** The current
  scan builds `declared = {f"ARXMCP_{name.upper()}" for name in
  Config.model_fields}` — a new Config field automatically extends `declared`.
  **The rewrite MUST preserve this pattern.** FM-5 (hardcoded count drift) is
  not a real risk if we keep using `Config.model_fields`.
- **FM-3 is real but tractable** (R2 analysis): the uvicorn-import path runs
  the scan BEFORE `logging.basicConfig` is called. The user sees one stderr
  line via the `sys.stderr.write` at line 726. **Implication: keep the new
  error message terse** — fit each per-var hint on 1-2 lines, no multi-paragraph
  prose.
- **The MCP spec does NOT require a trailing slash** (R2, verbatim from
  https://modelcontextprotocol.io/specification/2025-06-18/basic/transports):
  *"The server MUST provide a single HTTP endpoint path… For example, this
  could be a URL like `https://example.com/mcp`."* The trailing-slash
  behaviour is a FastAPI/Starlette mount idiosyncrasy at
  `server/_mcp_mount.py:60-71`: *"Operators who hit ``/mcp`` (no trailing
  slash) get a 307 redirect to ``/mcp/`` from Starlette's standard
  trailing-slash handling"*. The docs note must accurately distinguish
  spec-mandate from FastAPI quirk.
- **Existing test surface** (R1, verbatim):
  - `tests/test_server_startup.py:357-383` — `test_contact_email_env_var_rejected`,
    `pytest.raises(ValueError, match="ARXMCP_CONTACT_EMAIL")`.
    **PASSES THROUGH** after the rewrite because the new carve-out message
    still names `ARXMCP_CONTACT_EMAIL`. **No inversion needed** (see §3 D1).
  - `tests/test_server_startup.py:1231-1253` — `TestEnvVarScan` class
    with three tests; `match="unknown ARXMCP_"` continues to pass if the
    new message retains the prefix.
- **`docs/install.md:218-219` is already correct** (both briefs confirmed):
  *"`ARXMCP_CONTACT_EMAIL` is NOT needed by the server and is intentionally
  absent from the compose env."* — DO NOT TOUCH.
- **BP1/BP2 hashes** (R1, verbatim from source):
  - `EXPECTED_TOOL_SCHEMA_SHA256 = "c7df4c5c10c86693ac8553b7d079b55fba21749881c233f0f298955379d13375"`
    (`tests/test_server_tool_schema.py:94-96`)
  - `EXPECTED_BP1_SHA256 = "483344e3fcdea1d64de893cc669c9f142fd6f1198d4c8d383cd9c232558959bc"`
    (`tests/test_prompts.py:649-651`)
  - Implementer runs `uv run python -m pytest tests/test_server_tool_schema.py
    tests/test_prompts.py --tb=short` to confirm UNCHANGED.

---

## 3. Divergences resolved (orchestrator synthesis note)

### D1 — `ARXMCP_CONTACT_EMAIL`: still raise, or carve out as no-op?

R1 reads the brief as: "still raises `ValueError`, but with the new carve-out
message." R2 reads it as: "NO `ValueError` raised — accept the var as a no-op
and INVERT `test_contact_email_env_var_rejected`."

**RESOLVED → R1 wins. Still raises, carve-out message tells user to unset.**

Reasoning, ground in the brief's own AC1 wording (verbatim):
> AC1: `ARXMCP_CONTACT_EMAIL=x make up` produces a CLEAR error message naming
> the variable and **telling the user to unset it for the server** (not the
> 30-line declared-vars dump).

"Produces a clear error message… telling the user to unset" requires raising.
The brief's carve-out language *"is not a server config var; it's only read by
the CLI fetch tools (…). Unset it for the server."* is the **content** of the
error message, not a directive to silently accept the var. R2 misread the
brief.

**Implementation impact:**
- `_scan_unknown_arxmcp_env_vars` still raises for `ARXMCP_CONTACT_EMAIL`,
  but with the carve-out wording instead of the 30-line dump.
- `test_contact_email_env_var_rejected` (line 357-383) is UNCHANGED. Its
  `match="ARXMCP_CONTACT_EMAIL"` regex still passes because the new message
  still names the variable.
- The two new tests R2 proposes (`test_contact_email_carve_out_accepted`,
  `test_close_match_suggestion`) become ONE new test
  (`test_close_match_suggestion`) — the carve-out path is already covered by
  the existing test (just with the new message wording).

### D2 — `difflib` parameters: `cutoff=0.6` (default) or `cutoff=0.7` (tuned)?

R1 says `cutoff=0.6, n=1` (Python defaults). R2 says `cutoff=0.7, n=1`
(tuned to reduce false positives).

**RESOLVED → R2 wins. `cutoff=0.7, n=1`.**

Reasoning: the cost of a wrong suggestion is operator confusion (FM-1). The
cost of no suggestion is a short-form fallback that is still better than the
current 30-line dump (FM-1 mitigation). Erring on the side of "no suggestion
when uncertain" is the right call. R2's `0.7` is well above the
character-distance floor for any of the 32 declared vars, so genuine typos
(transposed/dropped characters) still clear it; random unrelated strings do
not. (R2's char-count for `ARXMCP_BIND_HOTS` was off by one — it's 16 chars,
not 7 — but the principle is sound and `cutoff=0.7` is the correct call.)

### D3 — Test brittleness on wording

Both briefs agree the new test must assert independent predicates rather than
full-sentence equality (R2 FM-4 + R1 §7 caveat). Specifically:

For the close-match test:
- assert `ARXMCP_BIND_HOTS` (the typo) appears in the error message
- assert `ARXMCP_BIND_HOST` (the suggested correct name) appears in the error
  message

No need to assert the full prose ("did you mean ARXMCP_BIND_HOST?") verbatim;
just the names. This keeps the test stable under future wording refactors.

For `test_contact_email_env_var_rejected` (UNCHANGED): the existing
`match="ARXMCP_CONTACT_EMAIL"` regex is already the right granularity.

---

## 4. Failure modes → required handling (R2's 9-mode enumeration)

Brief reference numbers; mitigation summary:

- **FM-1 (wrong close match):** `cutoff=0.7, n=1`. No suggestion is better than
  a wrong one. Fall through to a short-form hint listing top-3 closest at
  `cutoff=0.0`.
- **FM-2 (BOTH carve-out and real typo):** partition `unknown` into
  `carve_outs` + `genuine_unknowns` BEFORE composing the message. Each gets
  its own line in the message. Single `ValueError` with multi-line body.
- **FM-3 (logging not configured at scan time):** keep each per-var message ≤
  2 lines. Total message length should be tolerable on stderr. The user sees
  one block via `sys.stderr.write(f"FATAL: {exc}\n")` (line 726).
- **FM-4 (brittle wording test):** see §3 D3. Assert independent predicates
  (variable name + key phrase fragment), not full sentences.
- **FM-5 (hardcoded declared count):** NOT A RISK. Keep
  `Config.model_fields` as the dynamic source.
- **FM-6 (incomplete doc sweep):** the comprehensive grep is
  `grep -rn 'ARXMCP_CONTACT_EMAIL' --include='*.md' --include='Makefile'
  --include='*.py' .` from repo root. R2 already ran it. The 4 files to sweep
  (CLAUDE.md, README.md, Makefile @37 + @61-63) + the file to ADD a note to
  (docs/install.md) are the complete set. **All `tools/*.py` references stay
  intact** (ingest context, correct). `tools/README.md:14-17` stays intact
  (correct context).
- **FM-7 (`/mcp/` note contradicts registration snippet):** the registration
  snippet uses `http://127.0.0.1:7733` (base URL); the shim appends `/mcp/`
  internally at `shim/arxmcp_shim.py:141`. The note must phrase itself as:
  *"The shim transparently appends `/mcp/` to the base `--server` URL.
  If you build a custom HTTP client, POST to `http://127.0.0.1:7733/mcp/`
  (with trailing slash) to avoid the FastAPI 307."* The registration block
  itself is NOT changed.
- **FM-8 (`requires_model` accidental gate):** the new tests MUST call
  `_scan_unknown_arxmcp_env_vars` directly (the existing `TestEnvVarScan`
  pattern). NO `create_app` / `Resources.startup` import in the test path.
  Verify after writing.
- **FM-9 (CI/pre-commit greps the old nag):** R2 verified no such grep
  exists in this repo. Re-verify before commit.

---

## 5. Acceptance criteria — restated with implementation handles

Each AC maps to a concrete artifact:

- **AC1** (clear `ARXMCP_CONTACT_EMAIL` error) — covered by the new
  carve-out branch in `_scan_unknown_arxmcp_env_vars`. Verified by existing
  `test_contact_email_env_var_rejected` (regex still matches; new message
  carries the "unset it for the server" / "ingest var" semantics).
- **AC2** (typo close-match) — new test
  `test_close_match_suggestion_for_typo` asserts `ARXMCP_BIND_HOTS` →
  contains `ARXMCP_BIND_HOST`.
- **AC3** (`make up` works with no env vars) — already true; no change.
  No new test needed; existing `test_known_env_vars_pass` covers it.
- **AC4** (`CLAUDE.md` §9 + `README.md` quick-start clean) — diff
  removes the export lines. Spot-check: `grep -n
  ARXMCP_CONTACT_EMAIL CLAUDE.md README.md` after the edit should show
  zero hits.
- **AC5** (`Makefile` bootstrap nag retargets to CLI tools) — diff
  rewrites lines 37 + 61-63.
- **AC6** (`docs/install.md` `/mcp/` note in TWO places) — diff adds
  the inline note near line 144 + the Troubleshooting row near lines
  305-310.
- **AC7** (`make test` green + ruff clean) — pre-commit gate.
- **AC8** (`EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256`
  UNCHANGED) — verified by running
  `tests/test_server_tool_schema.py` + `tests/test_prompts.py`.
- **AC9** (regression tests) — one new test for the close-match path
  (`test_close_match_suggestion_for_typo`); the existing
  `test_contact_email_env_var_rejected` covers the carve-out semantics
  via its `match="ARXMCP_CONTACT_EMAIL"` regex (no change needed).

---

## 6. Implementation order

1. **`server/main.py`** — rewrite `_scan_unknown_arxmcp_env_vars` with the
   `KNOWN_INGEST_VARS = frozenset({"ARXMCP_CONTACT_EMAIL"})` carve-out,
   partition logic, `difflib.get_close_matches(name, sorted(declared),
   n=1, cutoff=0.7)` per genuine unknown, and a compact multi-line error
   message. Preserve `Config.model_fields` as the dynamic source.
2. **`tests/test_server_startup.py`** — add `test_close_match_suggestion_for_typo`
   inside `TestEnvVarScan`. Verify `test_unknown_env_var_rejected` and
   `test_contact_email_env_var_rejected` still pass.
3. **Doc sweep:** `CLAUDE.md`, `README.md`, `Makefile` (lines 37 + 61-63).
4. **`docs/install.md`** — inline `/mcp/` note + Troubleshooting row.
5. **Verify BP1/BP2 hashes unchanged:** run
   `uv run python -m pytest tests/test_server_tool_schema.py
   tests/test_prompts.py --tb=short`.
6. **`make test` green + `ruff check .` clean.**

---

## 7. Open questions

**None.** Both briefs reported "No open questions". Both divergences (D1
carve-out semantics, D2 difflib cutoff) resolved above.

## 8. External writes required

**None.** Purely local. Both briefs concur.

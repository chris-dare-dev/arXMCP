# Implementation Summary — onboarding-uplift-m1

**Summary:** Replace the `_scan_unknown_arxmcp_env_vars` 30-line declared-vars
dump with per-var hints (ingest-tool carve-out for `ARXMCP_CONTACT_EMAIL` +
`difflib.get_close_matches` typo suggestions + short-form nearest-3 fallback).
Sweep the stale `ARXMCP_CONTACT_EMAIL` server-startup snippets from `README.md`,
`CLAUDE.md`, `Makefile`. Add the `/mcp/` trailing-slash note to `docs/install.md`
in TWO places (registration block + Troubleshooting table). Closes BLOCKER B1.

**Commit range:** `be099b339859b3583e35ec1922a92a3b143d7aaf..<HEAD after feat>`

## Acceptance criteria status

- [x] **AC1** `ARXMCP_CONTACT_EMAIL=x make up` produces a clear carve-out
      message naming the var, pointing at the consuming CLI tools, and
      instructing the operator to unset it for the server. The full 32-var
      declared dump is gone. → Live-verified via sanity script. Regression:
      `tests/test_server_startup.py::TestEnvVarScan::test_contact_email_carve_out_names_ingest_tools`.
- [x] **AC2** `ARXMCP_BIND_HOTS=foo make up` (typo) produces "did you mean
      `ARXMCP_BIND_HOST`?" via `difflib.get_close_matches(n=1, cutoff=0.7)`.
      Regression:
      `tests/test_server_startup.py::TestEnvVarScan::test_close_match_suggestion_for_typo`.
- [x] **AC3** `make up` with no env vars set is UNCHANGED — `test_known_env_vars_pass`
      continues to pass.
- [x] **AC4** `CLAUDE.md` §9 + `README.md` quick-start no longer tell the reader
      to export `ARXMCP_CONTACT_EMAIL` before `make up`. CLAUDE.md now explicitly
      states the server rejects it; README quick-start brackets the export with
      explicit `unset` after the fetch step (the var is still needed for the
      arXiv fetch, just not for the server).
- [x] **AC5** `Makefile` lines 35-38 (help text) + 60-66 (bootstrap nag) now
      name `tools/notebook_fetch.py`, `tools/recover_preambles.py`,
      `ingest/inspire_ingest.py` and explicitly state "NOT `make up`" / "the
      server REJECTS the var". Line 180 (already a correct ingest-context
      comment) is unchanged.
- [x] **AC6** `docs/install.md` has the `/mcp/` trailing-slash note in TWO
      places: an inline note after the registration block (around line 146)
      explaining the shim appends `/mcp/` transparently, and a Troubleshooting
      table row (around line 311) explaining the FastAPI 307-redirect
      idiosyncrasy is NOT a spec mandate. A second new Troubleshooting row
      also documents the `ARXMCP_CONTACT_EMAIL` rejection.
- [x] **AC7** `make test` green (3 pre-existing failures unrelated to m1 —
      same as before this milestone); `ruff check .` clean.
- [x] **AC8** `EXPECTED_TOOL_SCHEMA_SHA256` (`tests/test_server_tool_schema.py:95`)
      and `EXPECTED_BP1_SHA256` (`tests/test_prompts.py:649`) are UNCHANGED —
      verified by running both test files (42 tests pass).
- [x] **AC9** Three new regression tests under `TestEnvVarScan`:
      - `test_close_match_suggestion_for_typo` (AC2)
      - `test_contact_email_carve_out_names_ingest_tools` (AC1)
      - `test_error_message_does_not_dump_all_declared_vars` (cardinal
        "the error stopped being scary" test — guards against any
        regression that re-introduces the 30-line dump even if other
        assertions pass)

## File deltas

**`server/main.py`** (+~85 LOC, +1 import)
- `import difflib` at the top.
- New module-level `_KNOWN_INGEST_ENV_VARS: dict[str, str]` — maps each
  carve-out var to its hint string. Single entry today
  (`ARXMCP_CONTACT_EMAIL`); future ingest-pipeline vars extend the dict.
- New `_format_unknown_arxmcp_env_var(env_name, declared)` helper —
  branches in priority order: carve-out dict lookup → `difflib.get_close_matches(n=1, cutoff=0.7)`
  → short-form `(n=3, cutoff=0.0)` fallback.
- `_scan_unknown_arxmcp_env_vars` rewritten to use the helper. Still raises
  `ValueError` (per m1 synthesis §3 D1 — the existing carve-out test's
  `match="ARXMCP_CONTACT_EMAIL"` regex continues to pass). The dynamic
  `Config.model_fields` source is preserved (m1 synthesis FM-5 mitigation
  — adding a new Config field automatically extends `declared`).

**`tests/test_server_startup.py`** (+3 tests, ~85 LOC)
- `test_close_match_suggestion_for_typo` (AC2 / synthesis D3): asserts
  the typo name AND the suggested correct name appear; does NOT pin the
  full sentence wording (FM-4 brittleness mitigation).
- `test_contact_email_carve_out_names_ingest_tools` (AC1): asserts the
  variable name + at least one of the three ingest-tool module paths +
  the "unset" instruction; independent predicates, not full sentence.
- `test_error_message_does_not_dump_all_declared_vars`: cardinal
  regression guard — asserts the error message mentions fewer than 10
  `ARXMCP_*` names (real ceiling ~4: offending var + up to 3 nearest;
  the 32-var dump was the BLOCKER B1 signal).

**`README.md`** (+3 lines, -1 line)
- The quick-start now brackets the `ARXMCP_CONTACT_EMAIL` export with
  comment + `unset` so the var is exported for the fetch step but
  cleared before `make up`. The var IS still needed for `python
  tools/fetch_seed.py` (it's the polite-pool User-Agent); just not for
  the server.

**`CLAUDE.md`** (+4 lines, -1 line, §9 "Start the MCP server")
- Dropped the `export ARXMCP_CONTACT_EMAIL=you@example.com` line.
- Added a paragraph explicitly stating the server REJECTS the var, names
  the three CLI tools that DO consume it, and the operator-discipline
  rule ("only export in shells where you're running an ingest CLI").

**`Makefile`** (+5 lines, -3 lines)
- Lines 35-39 (`make help` arXiv-fetch hint): retargeted to name the
  three CLI tools and to explicitly state "NOT `make up`; the server
  REJECTS the var".
- Lines 60-66 (bootstrap nag): same retargeting. The nag still fires
  when `ARXMCP_CONTACT_EMAIL` is unset (correct — operators who plan to
  run the fetch tools want the var), but now correctly tells them what
  it's for and that the server doesn't want it.

**`docs/install.md`** (+12 lines)
- Inline note after the registration block (around line 146): explains
  the shim appends `/mcp/` to `--server` transparently and that custom
  HTTP clients must POST to `http://127.0.0.1:7733/mcp/` directly. Per
  the synthesis, distinguishes FastAPI mount idiosyncrasy from MCP spec
  mandate (the spec example is unslashed).
- Troubleshooting table (around line 311): two new rows — one for the
  trailing-slash 307 issue, one for the `ARXMCP_CONTACT_EMAIL` rejection
  with the unset-and-scope-to-shell remediation.

**No other files touched.** `server/config.py` (the strict-typo guard
substrate), `shim/arxmcp_shim.py` (already POSTs to `/mcp/`),
`tools/README.md:14-17` (correct ingest-pipeline context), every
`tools/*.py` file referencing `ARXMCP_CONTACT_EMAIL`, `docs/install.md`
lines 218-219 (already-correct compose-env note) — all UNCHANGED.

## New / changed test paths

- `tests/test_server_startup.py::TestEnvVarScan` — 3 new tests
  (`test_close_match_suggestion_for_typo`,
  `test_contact_email_carve_out_names_ingest_tools`,
  `test_error_message_does_not_dump_all_declared_vars`).
- No other test files modified.

## Deviations from the synthesis

None. All synthesis decisions adopted verbatim:

- **D1** (still raise for `ARXMCP_CONTACT_EMAIL`, carve-out message): the
  `_KNOWN_INGEST_ENV_VARS` dict triggers a tailored hint, the function still
  raises `ValueError`, the existing `test_contact_email_env_var_rejected`
  pre-m1 regression guard continues to pass without modification.
- **D2** (`difflib` `n=1, cutoff=0.7` over default `0.6`): adopted verbatim,
  with the short-form `(n=3, cutoff=0.0)` fallback when no match clears 0.7.
- **D3** (independent-predicate test assertions, not full-sentence equality):
  all three new tests use individual `in msg` predicates + `any()` over the
  three ingest-tool names.

## External writes required

**None.** Purely local. The synthesis predicted zero external writes; this
holds. No `git push`, no PR, no ticket, no infra mutation.

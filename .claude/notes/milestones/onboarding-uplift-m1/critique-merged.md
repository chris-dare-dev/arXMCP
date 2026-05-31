# Critique — onboarding-uplift-m1 (merged)

**Critics:** milestone-adversary (6 findings) + milestone-infra-safety (0
findings — CLEAN).
**Generated:** 2026-05-31.
**Commit range:** `be099b339859b3583e35ec1922a92a3b143d7aaf..e7c480adba88bf928efadbf0988a17badc813d2d`
**Verdict:** RECTIFY-REQUIRED — 6 findings total (0 CRITICAL / 0 HIGH / 4
MEDIUM / 2 LOW), all credible, all cheap.

## Executive summary

- BP1/BP2 byte-stability independently verified clean across both critics
  — zero touch to `server/tools.py::ALL_TOOLS`, `server/prompts.py`, or any
  frozen-bytes surface. `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256`
  unchanged.
- The implementation works correctly end-to-end: error message renders on
  stderr in BOTH the `__main__` and uvicorn-import paths; `difflib`
  `cutoff=0.7` correctly suggests on 4/5 realistic typos; carve-out semantics
  honored D1 (still raises, custom message); the pre-existing
  `test_contact_email_env_var_rejected` regex passes through unchanged.
- The Makefile delta is informational-only — infra-safety walked all 4
  axes and found zero regressions.
- The 4 MEDIUMs cluster on **doc/code drift** between what the carve-out
  hint, docstring, and troubleshooting row claim vs what they should say
  after the rewrite. All 4 are cheap single-region edits.
- The 2 LOWs are: F5 (`/mcp/` note doesn't cover GET-SSE clients — minor
  broadening) and F6 (install.md doesn't mirror the README's
  export/unset bracket — defensible as deferred since the troubleshooting
  row already handles the corrective).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path | always fix in Phase 4 |
| MEDIUM | subtle correctness, latent foot-gun | fix only if cheap (≤30 LOC) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Cross-critic agreement

_None — no file:line region was flagged by ≥ 2 critics._

<!-- end:cross-critic-agreement -->

## Findings

### F1 — Carve-out hint misses 2/5 actual CONTACT_EMAIL consumers, including the README-quick-start tool

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `server/main.py:281-286`
- **What:** `_KNOWN_INGEST_ENV_VARS["ARXMCP_CONTACT_EMAIL"]` names
  exactly three modules. A full repo grep for actual
  `os.environ.get("ARXMCP_CONTACT_EMAIL")` reads returns FIVE
  files including `tools/arxiv_fetch.py` (transitively consumed by
  `tools/fetch_seed.py` — the very tool the README quick-start runs at
  line 51) and `ingest/graph_ingest.py:775` (direct CLI). A user who
  follows the README and forgets the `unset` step hits the new error,
  which directs them to three tool names — none of which match
  `tools/fetch_seed.py` (the tool they just ran).
- **Recommendation:** expand the hint to either name `tools/arxiv_fetch.py`
  as the library + the CLI tools that front it, OR just add
  `tools/fetch_seed.py` and `ingest/graph_ingest.py` to the existing
  3-name list. Cheap alternative preferred. Tighten the test from
  `any()` over 3 names to also assert `tools/fetch_seed.py` is named.

### F2 — Docstring example for the silently-ignored class is stale

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `server/main.py:354`
- **What:** Docstring says `ARXMCP_OTEL_ENDPOINT` is "a
  documented-but-unimplemented var" used as the example of the
  silently-ignored class. Live verification: `ARXMCP_OTEL_ENDPOINT` IS
  declared on `Config` (`server/config.py:349`), so it would NOT be
  rejected by the scan. Six months of E14 evolution un-staled the
  example without anyone editing the docstring.
- **Recommendation:** drop the second example (just keep
  `ARXMCP_BIND_HOST_TYPO`), OR replace with a still-hypothetical
  unknown like `ARXMCP_CACHE_TTL_SECONDS`.

### F3 — Cardinal "no 32-var dump" test threshold too tight for multi-unknown case

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_server_startup.py:1351-1357`
- **What:** `test_error_message_does_not_dump_all_declared_vars` asserts
  `< 10` ARXMCP_ mentions, but with THREE unknowns each taking a different
  branch (carve-out + typo + short-form), the count rises to ~9 — right at
  the threshold. A future cleanup adding a single ARXMCP_-prefixed phrase
  to the header would push a multi-unknown test fixture over the boundary,
  triggering a false alarm.
- **Recommendation:** raise threshold from `< 10` to `< 20` — still well
  below the 32+ count that was the BLOCKER B1 signal, comfortably tolerant
  of multi-unknown workloads.

### F4 — Troubleshooting-table symptom uses pre-rewrite error wording

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `docs/install.md:322`
- **What:** The new troubleshooting row's Symptom column reads
  `unknown ARXMCP_* environment variables: ...` (colon), but the actual
  new error reads `unknown ARXMCP_* environment variables — each would
  silently bypass...` (em-dash). A user searching for the literal symptom
  text won't match.
- **Recommendation:** rewrite the symptom column to use the actual
  current error prefix, OR drop the literal `:` and just match the
  substring `unknown ARXMCP_* environment variables` (substring is
  prefix-agnostic).

### F5 — `/mcp/` inline note misses GET-SSE clients

- **Severity:** LOW
- **Source:** adversary
- **File:** `docs/install.md:148-156`
- **What:** Inline note frames the trailing-slash issue as a
  POST-body-drop problem. MCP 2025-06-18 Streamable HTTP also permits
  GET-for-SSE; GET-to-`/mcp` also 307s. The note covers the dominant
  case but not all custom-client scenarios.
- **Recommendation:** broaden the note to mention "POST or GET-for-SSE"
  rather than just POST.

### F6 — `unset ARXMCP_CONTACT_EMAIL` in README quick-start; absent from `docs/install.md`

- **Severity:** LOW
- **Source:** adversary
- **File:** `README.md:52`, `docs/install.md` (no equivalent)
- **What:** README brackets the export with `unset`. `docs/install.md`
  doesn't describe the flow at all — its troubleshooting row addresses a
  fault the doc itself doesn't cause.
- **Recommendation:** add a short "Initial corpus fetch" sub-section to
  `docs/install.md` mirroring the README's pattern, OR delete the
  troubleshooting row. Defensible as deferred — install.md restructure is
  out of scope for m1's "stop telling people to break their server" goal;
  the troubleshooting row remains useful for users who follow the README
  and DO miss the `unset` step.

## What was done well (concatenated from both critics, dedup)

- BP1 cache discipline absolutely respected: zero touch to
  `server/tools.py::ALL_TOOLS`, `server/prompts.py`, or any frozen-bytes
  surface. Live-verified hash invariance (42 tests pass).
- Synthesis-locked D2 (`difflib n=1, cutoff=0.7`) adopted and verified
  against the actual 32-var declared set: 4/5 realistic typo cases
  produce sensible suggestions.
- D1 carve-out semantics (still raise, custom message) honored. The
  pre-existing `test_contact_email_env_var_rejected` regex passes
  through unchanged — proves the implementer correctly read the
  synthesis on the inversion question.
- All 3 new tests use independent predicates per synthesis FM-4, NOT
  full-sentence equality.
- `Config.model_fields` preserved as the dynamic source — adding a
  future Config field automatically widens the rejection set.
- `_KNOWN_INGEST_ENV_VARS: dict[str, str]` is a justified deviation from
  synthesis (`frozenset`) — MORE flexible substrate for future ingest
  vars, each carrying its own customized hint string.
- Doc-sweep grep clean: every server-startup snippet (CLAUDE.md §9,
  README.md quick-start) retargeted or removed; every `tools/*.py`
  ingest-context reference preserved per synthesis FM-6.
- Error message renders correctly on stderr in BOTH paths (`__main__`
  direct + uvicorn-import). Multi-line `\n` survives
  `sys.stderr.write(f"FATAL: {exc}\n")` wrapping.
- Makefile bootstrap nag correctly fires only when CONTACT_EMAIL is
  unset AND correctly directs users to ingest tools (NOT `make up`).
- Factually accurate Makefile help text — "the server REJECTS the var"
  grounded in `server/main.py:381` (`raise ValueError`), verified by
  infra-safety.
- Bootstrap idempotency preserved — `@echo` + `if [ -z ... ]; then ... fi`
  cannot mutate state. Exit codes uncorrupted.
- No `sudo`, no privilege escalation, no destructive defaults introduced.

## Recommended rectification order

1. **F1** (carve-out tool list completeness) — highest user-facing
   leverage; touches the operator story. ~5 LOC + 1 test assertion.
2. **F4** (install.md symptom row precision) — single doc line edit.
3. **F2** (server/main.py:354 stale docstring) — pure doc edit; ~2 LOC.
4. **F3** (cardinal test threshold raise from 10 to 20) — single line.
5. **F5 LOW** (`/mcp/` note broadens to POST + GET-SSE) — single paragraph.
   Cheap; land alongside F4.
6. **F6 LOW** — DEFER. Install.md restructure is out of m1 scope.

## Rectification status (filled by Phase 4)

- **F1 (MEDIUM) — carve-out hint misses 2/5 actual consumers.** RESOLVED.
  `_KNOWN_INGEST_ENV_VARS["ARXMCP_CONTACT_EMAIL"]` extended to name all
  6 consumer surfaces: the `tools/arxiv_fetch.py` shared library + every
  direct CLI reader (`tools/fetch_seed.py`, `tools/notebook_fetch.py`,
  `tools/recover_preambles.py`, `ingest/inspire_ingest.py`,
  `ingest/graph_ingest.py`). Regression guard:
  `tests/test_server_startup.py::TestEnvVarScan::test_contact_email_carve_out_names_ingest_tools`
  tightened with a cardinal assertion that
  `tools/fetch_seed.py` (the README quick-start tool) MUST appear in the
  hint — without it, the README path lands on an error pointing at
  tools the user didn't run, re-opening the defect.
- **F2 (MEDIUM) — stale `OTEL_ENDPOINT` example in docstring.**
  RESOLVED. `server/main.py::_scan_unknown_arxmcp_env_vars` docstring
  no longer cites `ARXMCP_OTEL_ENDPOINT` as a
  "documented-but-unimplemented var" example; it acknowledges the var
  is now declared on `Config` (`server/config.py:349`, E14
  observability) and would be accepted. The `ARXMCP_BIND_HOST_TYPO`
  example survives as the still-valid case. No regression test added
  (pure doc edit; `TestEnvVarScan` covers the runtime contract).
- **F3 (MEDIUM) — cardinal threshold too tight for multi-unknown.**
  RESOLVED. Raised threshold in
  `test_error_message_does_not_dump_all_declared_vars` from `< 10` to
  `< 20`; the comment now documents the realistic max (~10 for 3
  unknowns across all 3 branches) vs the BLOCKER B1 signal (32+).
  Self-regressing: the test's own threshold raise IS the calibration
  fix.
- **F4 (MEDIUM) — install.md symptom uses pre-rewrite wording.**
  RESOLVED. `docs/install.md` troubleshooting row Symptom column
  rewritten to the prefix-agnostic substring
  `unknown ARXMCP_* environment variables` (no literal colon or
  em-dash) + extended Fix column with the full 5-tool consumer list
  matching the new carve-out.
- **F5 (LOW) — `/mcp/` note misses GET-SSE clients.** RESOLVED.
  Inline note in `docs/install.md` broadened to mention both POST
  (JSON-RPC requests) and GET (SSE-listen stream); the body-drop
  framing now correctly notes that POST is the dominant failure mode
  but a misbehaving proxy may break either method.
- **F6 (LOW) — README has `unset` but install.md doesn't mirror it.**
  DEFERRED. Install.md restructure (adding an "Initial corpus fetch"
  sub-section between §1 and §2) is out of m1 scope (the milestone's
  "stop telling people to break their server" goal is met via the
  README's existing bracket + the troubleshooting row). Tracked as a
  candidate for `onboarding-uplift-m2` (the `make init / make ingest`
  wrappers milestone, which will rewrite the install-flow surface
  comprehensively).

**0% invalidation rate** — all 6 findings re-verified cleanly. 4
MEDIUMs + 1 LOW (F5) fixed; 1 LOW (F6) deferred with reason. Full
suite: `3 failed, 3510 passed, 30 skipped, 1 xfailed` (3 pre-existing
m1-unrelated failures: `test_drift_check`, `test_cite_neighbors_wired`,
+ one Windows-only test).

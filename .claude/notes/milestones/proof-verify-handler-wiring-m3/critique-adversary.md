# Critique — proof-verify-handler-wiring-m3

**Critic:** adversary
**Generated:** 2026-05-22T01:55:00Z
**Commit range:** 9e176174a3edfa9053c97e07be2865590988cd17..d9681858b68cd24438992f79f5c7355e9270aba2
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Pure-docs milestone; the new runbook at `docs/ops/notebook-modes.md`
  is well-organized, doc-placement-rule compliant, and faithfully
  quotes the MCP 2025-06-18 session-lifecycle clauses. Three
  citation/operator-actionable bugs require fixing before it ships
  as authoritative guidance.
- 0 CRITICAL, 1 HIGH (operator-actionable bug), 2 MEDIUM (cite
  drift), 1 LOW (cite line-range pointing at docstring rather than
  injection body).
- Highest-risk site: `docs/ops/notebook-modes.md:109` —
  `pkill -SIGTERM -f "ARXMCP_LANCEDB_PATH=.*bridgeland-stability"`
  cannot find the daemon process because env-var prefixes never
  appear in `ps`/`pkill -f` output.
- Second-highest: `docs/ops/notebook-modes.md:72` — bind-host
  validator cite to `server/config.py:323` points at the bind_port
  validator (`validate_port_range`); the real bind-host validator is
  `reject_non_loopback_bind` at `server/config.py:294`.
- Standard 8 axes mostly clean for a pure-docs change: byte-stability
  unaffected (no source changes), math fidelity N/A, MCP protocol
  compliance is unchanged code-side and quoted-spec-side faithful,
  security threat model unchanged, no tier-sequencing violation, no
  fork, no test regression (2259 passed baseline preserved).
- Doc-placement and CLAUDE.md §1 compliance: ✓ — file lands at
  `docs/ops/notebook-modes.md` (operator-facing) and IS linked from
  the root README's runbook table at `README.md:77`.
- Quoted spec text is verbatim-correct for the MUST clause and
  faithful-summary-correct for the SHOULD clause (parenthetical
  elided but the normative SHOULD is exact). Verified against
  https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
  §Session Management items 4 and 5.
- 6 named failure modes (FM1–FM6) each have a recovery; FM3's
  "two read-only daemons are safe" claim is true at the LanceDB
  MVCC layer and properly qualified about cache-staleness when
  a writer joins.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — `pkill -f` recipe cannot find the daemon process (env vars not in argv)

- **Severity:** HIGH
- **Source:** adversary
- **File:** docs/ops/notebook-modes.md:109
- **What:** The "Restart after ingest" recovery prescribes
  `pkill -SIGTERM -f "ARXMCP_LANCEDB_PATH=.*bridgeland-stability"`.
  `pkill -f` matches against the full process command line (argv).
  Environment variable assignments set via `export VAR=...` (the
  Notebook-A example at line 59) or via inline shell prefix
  `VAR=val cmd ...` (the Notebook-B example at lines 65-68) are
  consumed by the shell and exec'd into the process **environment**,
  not its argv. They are NOT visible to `ps` / `pkill -f`. The
  prescribed kill command will silently match zero processes,
  leaving the operator's daemon alive after they believe they have
  stopped it — and then they ingest, restart, and now have two
  daemons against the same path (FM3, with the qualifier that one is
  actively writing through ingest).
- **Why it matters:** The runbook positions this as the
  authoritative recovery for the most common operational task
  (ingest → restart). A no-op kill is worse than no recovery — the
  operator believes they have stopped the daemon when they have
  not. This is an operator-actionable bug in an operator-facing
  doc. Verified empirically: `env FOO=bar sleep 0.1` shows
  `command = sleep 0.1` in `ps`, with no `FOO=bar` prefix.
- **Proposed fix:** Replace the `pkill -f` recipe with one of:
  (a) record the PID at launch (`echo $! > var/arxmcp/notebooks/<slug>/ops/daemon.pid`)
  and use `kill -TERM "$(cat …/daemon.pid)"`;
  (b) match on the bind port (which IS argv-visible if the daemon
  is started with an `--port` flag, but the doc uses
  `ARXMCP_BIND_PORT` env var so the port is also not in argv —
  caveat applies);
  (c) the safest: match on the working directory + module path:
  `pgrep -f "python -m server.main"` then filter by inspecting
  `/proc/<pid>/environ` on Linux or `ps -E -p <pid>` on macOS to
  identify the matching daemon by env-var content. The simplest
  operator-friendly recipe is PID-file pattern (a).
- **Regression guard:** Add a `## Verifying the kill worked` aside
  noting `ps aux | grep server.main` should show one fewer line; or
  better, write `docs/ops/notebook-modes-validation.sh` that an
  operator can `bash` to exercise the launch+kill cycle end-to-end
  before deploying.

### F2 — Cite to bind-host validator points at wrong function

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** docs/ops/notebook-modes.md:72
- **What:** The doc says
  `[server/config.py:323](../../server/config.py)` "rejects any
  non-loopback bind." Line 323 in current source is
  `@field_validator("bind_port")` / `validate_port_range` — the
  privileged-port-range gate, not the loopback gate. The actual
  bind-host validator is `reject_non_loopback_bind` at
  `server/config.py:294` (a `@model_validator` per E13_S05 D1, not
  a `@field_validator`).
- **Why it matters:** An operator reading the runbook then opening
  the file to verify the claim sees an unrelated validator and may
  conclude either (a) the runbook is stale (they then doubt all
  other cites), or (b) the loopback constraint isn't actually
  enforced (they then take an unsafe action). The wrong cite
  undermines the runbook's authority on the exact security
  property the section is asserting.
- **Proposed fix:** Edit the cite to
  `[server/config.py:294](../../server/config.py)` and change
  "bind-host validator" → "`reject_non_loopback_bind` validator"
  to make the symbol name discoverable.
- **Regression guard:** none required (doc edit); the underlying
  validator is already test-covered by
  `tests/test_config.py` (verify in passing).

### F3 — `paper_id IN (...)` predicate cite range points at unrelated code

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** docs/ops/notebook-modes.md:126
- **What:** The doc cites
  `[server/handlers/search.py:449-454](../../server/handlers/search.py)`
  for `LanceDB.search(...).where("paper_id IN (...)", prefilter=True)`.
  Lines 449-454 in current source are the Tier-2 cache hit path
  (`_build_content_blocks(...)` + a CallToolResult return + a
  comment block). The actual `.where(paper_id_predicate, prefilter=True)`
  call is at line 468, with the surrounding `with span_ann(k=k):`
  block spanning 463-473.
- **Why it matters:** Same trust-erosion as F2 — an operator
  following the link does not see the claimed code at the cited
  range. The cite is off by ~15 lines, which is plausibly drift
  from an earlier draft (m1 era) before the Tier-2 cache restamp
  block grew. Lower severity than F2 because the symbol is
  cited inline (`.where("paper_id IN (...)", prefilter=True)`)
  with enough textual fingerprint for the operator to recover
  via grep.
- **Proposed fix:** Change `server/handlers/search.py:449-454`
  to `server/handlers/search.py:463-468` (the `with span_ann(...)`
  block enclosing the `.search(...).where(...).limit(...)` chain).
- **Regression guard:** none (doc edit).

### F4 — `filters_applied` cite points at docstring, not injection body

- **Severity:** LOW
- **Source:** adversary
- **File:** docs/ops/notebook-modes.md:128
- **What:** The doc cites
  `[server/handlers/search.py:218-232](../../server/handlers/search.py)`
  for "echoes the canonical filter shape back as `filters_applied`."
  Lines 218-232 are inside the `_inject_filters_applied` docstring
  (the "Canonical form" + "SUPPORTED_FILTER_KEYS subset only"
  prose); the actual injection body is lines 234-241 (the
  `applied = {...}` dict-comp + `{**payload, "filters_applied": applied}`
  return). The cite is technically inside the right function but
  not at the load-bearing line.
- **Why it matters:** Operator-actionable impact is minimal — the
  function name `_inject_filters_applied` is not in the cite but
  the surrounding code is dense enough that the operator finds it
  quickly. This is the lowest-severity of the cite-drift family
  but worth tightening for the same reason as F2 / F3.
- **Proposed fix:** Change `server/handlers/search.py:218-232`
  to `server/handlers/search.py:195-241` (the full
  `_inject_filters_applied` function), OR to
  `server/handlers/search.py:234-241` (the injection body itself).
- **Regression guard:** none (doc edit).

## What was done well

- The runbook is doc-placement-rule compliant: lands at
  `docs/ops/notebook-modes.md` (the established convention for
  operator runbooks; 10 prior runbooks share the directory) and IS
  linked from `README.md:77` per CLAUDE.md §1's "user-facing
  documentation referenced by the root README.md" rule. The
  synthesis correctly overrode the brief's parenthetical
  `docs/install.md` suggestion in favor of the actual project
  convention.
- The three constants quoted with file:line ARE correct at the
  exact line cited: `MAX_SEARCH_PAPERS_CALLS = 3` at
  `server/session.py:54` ✓, `MAX_PAPER_ID_FILTER_ITEMS = 100` at
  `server/handlers/search.py:108` ✓, `DEFAULT_RESULT_BYTE_CAP =
  256 * 1024` at `server/config.py:58` ✓,
  `SUPPORTED_FILTER_KEYS = frozenset({"paper_id"})` at
  `server/handlers/search.py:192` ✓.
- The "defensive, not security" framing for the session cap matches
  the `server/session.py` module docstring verbatim ("The cap is a
  defensive ceiling, not a security contract") — the doc cites the
  docstring and quotes its conclusion faithfully.
- The MCP 2025-06-18 spec quotes are accurate: the MUST clause for
  HTTP-404→fresh-session is verbatim correct; the SHOULD clause for
  HTTP DELETE elides the parenthetical "(e.g., because the user is
  leaving the client application)" but the normative SHOULD body is
  exact. Verified against
  https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
  §Session Management items 4 and 5.
- The "Schema stability commitment" section correctly identifies the
  `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`
  paired pin (both present in `tests/test_server_tool_schema.py`),
  and the cross-reference to the `_meta`-strip contract at
  `server/tools.py::register_all` matches the m2 rect F6 work
  (verified: `register_all` at line 700 with the contract comment
  block at 736-751).
- FM3's "two read-only daemons are safe (LanceDB MVCC)" claim is
  correct at the LanceDB layer and properly qualified about
  cache-staleness when a writer joins. The recovery ("Stop the
  serving daemon before any ingest. Run ingest. Re-launch.") is
  the right operational sequence.
- Internal cross-links resolve: `../../.claude/notes/05-…md`,
  `../../.claude/notes/07-…md`, `../../.claude/notes/08-…md`,
  `../../.claude/notes/proof-verify-pivot/synthesis.md`, the
  `../install.md`, `../ops/bulk-ingest-runbook.md`,
  `../ops/cutover-runbook.md`, `../ops/failure-modes.md`, and the
  `server/schemas/search_papers_result.json` link all point at
  files that exist.
- The 22-paper math.AG corpus working example is correctly named
  with the synthesis-D2 labeling — `lancedb-staging` is flagged
  as developer-only / spike alongside the canonical production
  path (`var/arxmcp/index/lancedb`) and the per-notebook Variant 1
  path (`var/arxmcp/notebooks/<slug>/lancedb/`). The implementer
  did not silently elevate the spike path to a production
  convention.
- Test surface preserved: pure-docs change, no source-tree
  modifications, `make test` baseline of 2259 passed / 9 skipped /
  1 xfailed unchanged. Ruff clean per the implementation summary.

## Recommended rectification order

1. **F1** — operator-actionable kill recipe. Fix first; this is the
   one finding that will hurt a real operator on real hardware on
   the first attempted use. Switch to PID-file pattern (option a in
   the proposed fix).
2. **F2** — bind-host validator cite. Trivial edit; restores trust
   in the security-section claims.
3. **F3** — `.where()` cite line range. Trivial edit; same
   trust-restoration motivation.
4. **F4** — `filters_applied` cite. Lowest impact; bundle into the
   same rect commit as F3 since both are simple line-range
   corrections in the same file.

## Rectification status

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->

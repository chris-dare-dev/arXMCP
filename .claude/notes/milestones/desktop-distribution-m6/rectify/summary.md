# Rectify summary — desktop-distribution-m6

**Critique:** `.claude/notes/milestones/desktop-distribution-m6/critique/dedup.md`
(C1 H6 M13 L6 = 26 findings, merged ids)
**Commit range critiqued:** `c0dcf98..822dab7` · branch `main`, base `c199457`
**Register:** 25 fixed, 1 deferred, 0 invalidated, 0 handed-back — `findings.py gate` exit 0.

Every CRITICAL and HIGH was re-verified against live code by anchor before being
fixed. No anchor had drifted; invalidation rate 0%.

---

## The blocking set — 7 ids, 4 distinct defects

| ids | disposition | what the fix does |
|---|---|---|
| C1 | fixed | README process-group bullet rewritten to state the real limit |
| H1 + H4 | fixed | probe discriminator rebuilt around positive controls |
| H2 + H5 | fixed | contract-suite conformance line is now zero-skip gated |
| H3 + H6 | fixed | teardown reaps the fixture grandchild; budgets reconciled |

### C1 — README asserted a false non-claim

The bullet claimed "neither the production child nor the fixture spawns
descendants today, so a `setsid()`-style escape cannot occur". It now states the
truth: the supervisor signals only the direct child PID; the *fixture* spawns no
descendants so the matrix proves nothing about them either way; and the
*production* child does spawn them — `ingest_tracker` / `parse_tracker`
(`server/main.py`), with LaTeXML/MinerU helpers using `start_new_session=True`
(`ingest/textbook_parser.py:459`) — so a forced kill orphans them today.

**The critic's own proposed mitigation text was false and was NOT copied.**
C1's proposed fix said to "state the mitigation that exists — the cooperative
path runs `ingest_tracker.shutdown()`'s SIGTERM->2s->SIGKILL". Verified at source
instead: `server/ingest_tracker.py:345` and `server/parse_tracker.py:301` both
cancel only the asyncio wrapper, and their own docstrings say the subprocess
"receives no signal" and "continues running until the OS reaps it". `os.killpg`
appears in this tree only on the per-call wall-TIMEOUT paths
(`ingest/textbook_parser.py:479`, `tools/arxiv_fetch.py`, `tools/cdm_eval.py:375`),
never on shutdown. The README now says descendants outlive **both** paths,
bounded only by their own wall timeouts, and that the next-boot
`mark_orphaned_*` sweeps repair the database row, not the process. Writing the
critic's version would have replaced one false claim with another.

**Guard:** `tests/test_desktop_contract.py::test_desktop_readme_never_claims_a_descendant_free_child`
— source-derived in the repo's `test_assert_ban.py` style: while any spawn site
exists under `server/`, `ingest/`, `tools/`, the README may not contain "spawns
descendants today", "escape cannot occur", or "not applicable, not handled", and
*must* name `ingest_tracker`, `parse_tracker`, and `start_new_session` so the
limit cannot be softened into vagueness.

### H1 + H4 — the probe could not tell failure from absence

1. `_pid_is_gone` now uses `os.kill(pid, 0)` — `ProcessLookupError` is
   unambiguously gone, `PermissionError` unambiguously alive. No subprocess is
   left to misreport. Raises on Windows, where `os.kill` would terminate the target.
2. `_listener_lines` opens a throwaway loopback listener and queries `lsof` about
   the audited port **and** the control port in one invocation. A reply omitting
   the control row raises. This is what actually discriminates.
3. `_probe_command` additionally raises on exit-1-with-stderr, and its stale
   "documented found(0)/not-found(1) pair" docstring is corrected.

`_pgid_members` (new, for M11) reads the whole process table rather than
`ps -g <pgid>` and requires its own PID in the listing.

### H2 + H5 — AC3/AC5 evidence could vanish from the gate

`conftest._DESKTOP_GATE_ENV` widened from a string to
`("DESKTOP_SUPERVISOR_BIN", "ARXMCP_FIXTURE_SIDECAR")`; `Makefile:157` gains
`-m "requires_desktop_stack or not requires_desktop_stack"`; `_sidecar_binary`
now `pytest.fail`s when `ARXMCP_FIXTURE_SIDECAR` is set but does not resolve,
matching the `_supervisor_binary` / `_fixture_binary` pattern m6 already wrote.

### H3 + H6 — a stranded SIGTERM-immune orphan

New `_reaped_fault_supervisor` context manager wraps all six fault tests. Its
`finally` stops the supervisor, SIGKILLs every `child-spawn` PID from the event
log, and **confirms** each is gone within 5 s. Backed by an eager
`_FAULT_CHILD_PIDS` registry with a session-scoped autouse fixture and an
`atexit` reaper. Defense in depth (M3): the `IgnoreShutdown` arm now `abort()`s
60 s after launch, so it is bounded outside the harness entirely.

In `test_fault_supervisor_sigkill_cooperating_child_self_cleans` every assertion
moved *inside* the `with`, so the harness reap runs only after self-cleanup has
been proved rather than doing the child's job for it.

---

## Proof that the H1/H4 fix discriminates

A stub `lsof` on PATH exiting **1 with empty stdout and empty stderr** — the
shape byte-identical to a clean no-match — pointed at a port that *was*
genuinely listening:

```
PRE-FIX, broken lsof, port that IS genuinely listening:
   old_listener_lines -> []
   assert _listener_lines(port) == []  -> PASSES VACUOUSLY
```

Post-fix, same stub:

```
--- BROKEN lsof (exit 1, empty stdout, empty stderr) ---
  DISCRIMINATED -> RuntimeError: lsof failed its positive control - port 49355
  is held open by this process yet was not reported (rc=1, stderr=b'').
  An unverified probe is never clean absence.
```

The real `lsof` still separates the two cases correctly — dead port `[]`, live
port 1 row — so the guard is not merely "raise on everything".

## Proof that the H3/H6 fix reaps

Pre-fix teardown (`_stop_process(process)` verbatim), supervisor SIGKILLed so
the ladder never runs:

```
PRE-FIX teardown: fixture pid 42763 still alive = True
  -> LEAKED.
```

M3's hard deadline, with SIGTERM **and** stdin EOF both ignored and no harness
reaping at all:

```
bound on port 49570; pid 43130
SELF-DESTRUCTED after 60.1s, rc=-6
```

## Proof that the H2/H5 fix fails on drift

```
$ ARXMCP_FIXTURE_SIDECAR=/nonexistent/fixture-sidecar pytest tests/test_desktop_contract.py
EXIT=1
```

(the critique records this exiting **0 with skips** before the fix)

m5's H3 guard re-verified unchanged:

```
$ DESKTOP_SUPERVISOR_BIN=... pytest tests/test_desktop_child.py     # no -m
m5-H3 guard EXIT=1
DESKTOP_SUPERVISOR_BIN/ARXMCP_FIXTURE_SIDECAR is set, so this run is the
desktop conformance gate and must have ZERO skips; 12 test(s) skipped:
```

---

## Fixed (25)

| id | one-line resolution |
|---|---|
| C1 | README states the real descendant limit; critic's false mitigation corrected at source |
| H1, H4 | `os.kill(pid,0)` + same-invocation `lsof` positive control + exit-1-with-stderr raise |
| H2, H5 | gate env widened to a tuple; `-m` added to `Makefile:157`; `_sidecar_binary` fails loudly |
| H3, H6 | `_reaped_fault_supervisor` SIGKILLs and confirms every `child-spawn` PID |
| M1, M7 | `redact.rs` doc restated: call-site discipline + shared-vector lock, not parity |
| M2, M13 | marker registration -> m5/m6, fault matrix, `lsof`+`ps` prerequisites, `ARXMCP_FIXTURE_SIDECAR` |
| M3 | `IGNORE_SHUTDOWN_DEADLINE` 60 s hard self-destruct |
| M4, M12 | wait raised to 300 s (> the supervisor's own ~198 s); ladder asserted from `elapsed_ms` |
| M5 | both headline tests marked `requires_desktop_stack`; conformance `-m` keeps them in |
| M6 | `validate_plan` refuses test-only knobs outside smoke mode |
| M9 | dropped wildcard arms recorded as an explicit third non-claim |
| M10 | contract-fixtures inventory guard (Python) |
| M11 | pgid measured, not argued — live pgid equality + empty group after teardown |
| L1, L3, L6 | `park_on_lease` error arm sleeps and bails after 3 consecutive errors |
| L2 | redundant `requested_exit` handle removed |
| L4 | probe binary fallback tries `/usr/sbin`, `/usr/bin`, `/bin`, `/sbin` |
| L5 | redaction vector count pinned exactly (`== 9`) in both languages |

LOWs were fixed only where they sat inside a hunk already being edited
(L1/L3/L6 and L2 in the same Rust functions; L4 inside the `_probe_command`
rewrite; L5 inside the redact hunks) — none required new surface.

## Deferred (1)

| id | why |
|---|---|
| M8 | Making the scrub a `Recorder` **writer** property exceeds the 30-LOC MEDIUM bar and is a design change: `Recorder::new(&root)` runs in `main()` before any `StartupToken` exists (the token is generated per-cycle in `lifecycle.rs`), so it needs a mutable token slot plus its set/clear lifecycle. M1's doc narrowing removes the misleading universal-coverage claim and states the call-site obligation explicitly in the meantime. |

Also partially deferred inside M10: the Rust-side inventory twin.
`desktop-contract/tests/contract.rs` consumes fixtures via per-file
`include_str!`, so the equivalent needs a runtime inventory it does not build
today. The Python guard covers the regression.

## Invalidated (0)

No anchor had drifted; every CRITICAL/HIGH re-verified as still present.

## Not filed, by prior authorization

`--allow-large-diff` was owner-authorized for m6, so no review-size finding was
filed or acted on (the adversary critic's NOTE records the arithmetic so the
omission stays auditable).

## Regression tests added

| file | what it now guards |
|---|---|
| `tests/test_desktop_contract.py::test_desktop_readme_never_claims_a_descendant_free_child` | C1 — README cannot re-assert descendant-freedom while a spawn site exists |
| `tests/test_desktop_contract.py::test_listener_probe_failure_raises_instead_of_reading_as_absence` | H1/H4 — a silently-broken `lsof` raises rather than returning `[]` |
| `tests/test_desktop_contract.py::test_probe_exit_one_with_diagnostics_is_an_error_not_a_no_match` | H1/H4 — exit 1 + stderr is an error, not a no-match |
| `tests/test_desktop_contract.py::test_pid_liveness_uses_signal_zero_rather_than_a_subprocess` | H4 — PID liveness never shells out |
| `tests/test_desktop_contract.py::test_process_group_probe_requires_seeing_its_own_pid` | M11 — a partial `ps` table is not an empty group |
| `tests/test_desktop_contract.py::test_every_conformance_pytest_line_arms_the_zero_skip_gate` | H2/H5 — every conformance `pytest` line arms the gate |
| `tests/test_desktop_contract.py::test_explicit_but_missing_sidecar_path_fails_rather_than_skips` | H5 — an unresolvable explicit path fails, never skips |
| `tests/test_desktop_contract.py::test_contract_fixture_directory_has_no_unclaimed_files` | M10 — a new fixture forces a consumer decision |
| `tests/test_desktop_child.py::test_teardown_reaps_a_sigterm_immune_child_when_the_ladder_never_runs` | H3/H6 — teardown reaps the SIGTERM-immune fixture |
| `apps/desktop/crates/supervisor/src/main.rs::tests::test_only_knobs_are_refused_outside_smoke_mode` | M6 — test knobs refused outside smoke mode |

Plus two existing tests strengthened: the marker-token test now checks **every**
`-m` expression in the recipe, and the redaction vector count is pinned exactly
in both languages.

## Check gate results

| gate | result |
|---|---|
| `cargo fmt --all --manifest-path apps/desktop/Cargo.toml -- --check` | PASS (clean) |
| `cargo clippy --locked ... --workspace --all-targets --all-features -- -D warnings` | PASS (no warnings) |
| `cargo test --locked --manifest-path apps/desktop/Cargo.toml --workspace` | PASS — **20** tests (contract 8, supervisor 12; was 19, +1 for the M6 knob-gate test) |
| `make desktop-conformance PYTHON=.venv/bin/python` | **exit 0** — `42 passed in 4.19s` + `26 passed in 40.49s`, **zero skips** (was 34 + 25) |
| `make test PYTHON=.venv/bin/python` | **exit 0** — `5091 passed, 57 skipped, 1 xfailed in 299.21s` (baseline 5085 / 54 / 1) |
| `ruff check .` | PASS (All checks passed) |
| `git status --porcelain` | clean after commit |

Count arithmetic, so nothing is hidden: `make test` +8 unmarked contract tests,
-2 (the two headline tests moved from run-by-default to opt-in) = **+6 passed**;
skips +2 (those two) +1 (the new marked reap guard) = **+3 skipped**. The
conformance gate runs all of them: 34+8 = **42**, 25+1 = **26**.

## external_writes_required

- `git push origin main` — **NOT executed here.** The rectifier stops at the
  external-write boundary; the main session gates it with the user.

## Prompt-injection

`injection_attempts: 0`. No tool result, file, or critique text attempted to
instruct or authorize action.

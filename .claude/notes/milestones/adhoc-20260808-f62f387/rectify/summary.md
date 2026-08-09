# Rectify summary — adhoc-20260808-f62f387 (issue #423)

Rectified against `critique/dedup.md` (C0 H1 M4 L1, one critic:
`milestone-adversary-critic`) over `e28426f..7711f45`, fixing forward on
`main` — the implementation was already pushed at the owner's instruction, so
no pushed history was rewritten or amended.

**All six findings fixed. Zero deferred, zero invalidated, zero handed back.**
Every anchor was re-verified against `HEAD` before being touched and every one
still matched; invalidation rate 0%.

## Dispositions

| id | sev | disposition | one-line resolution |
|----|-----|-------------|---------------------|
| H1 | HIGH | fixed | Committed the negative control the implementation had only run by hand: a smoke-mode-only `test_hide_window` plan knob builds the window ordered-out, the fixture sidecar now answers the MCP smoke so the cycle can reach the window step at fixture speed, and `test_fault_hidden_window_fails_the_cycle` asserts exit 1 + the exact `lifecycle-failed` reason + `orphan-shutdown` + **no** `window-ready`. Demonstrated below. |
| M1 | MEDIUM | fixed | `{"visible": true}` became `{"window_ordered_in": true}`; `navigate_window`'s doc comment now states the AppKit semantics exactly, and `apps/desktop/README.md` gains a "What `window-ready` does and does not attest" subsection. The gate itself is untouched — only the claim was narrowed to it. |
| M2 | MEDIUM | fixed | The 15 s poll retains its suppressed `RuntimeError` as `last_probe_error`, and absence is no longer claimed on a stale liveness claim: on timeout the control pid is **re-probed**, and a control that now raises or reads 0 fails the test naming the PROBE, not the supervisor. |
| M3 | MEDIUM | fixed | Module docstring records the single named exception to the no-secondary-skip-guard convention and why it is sound, and points at the conftest zero-skip gate that converts the skip into a session failure. |
| M4 | MEDIUM | fixed | Recorded, not papered over: a new "make desktop-conformance is macOS-only today (issue #423)" README subsection beside the existing m6 non-claims, naming BOTH skipping tests, why weakening the zero-skip rule was rejected, and what a future milestone owes. |
| L1 | LOW | fixed | Cheap and adjacent to the M2 edit in the same function: the sweep + re-count retries up to 3 times, so an unrelated process closing its last window between the two osascript round trips re-sweeps instead of reddening the run. |

## H1 demonstration — the counterfactual, run both ways

The cheap option the critique offered first (assert the `window-ready`
payload) was **rejected as insufficient**: deleting the
`match window.is_visible()` block does not change the payload the recorder
writes, so that assertion passes with the gate gone. The committed guard is
the fault arm.

The blocker was reachability, not assertion strength: the fixture sidecar
answered only `/healthz` and `/readyz`, so **every** fault arm died at the MCP
smoke and no fixture-speed test could reach `navigate_window` at all. Teaching
the fixture the three-request smoke exchange made the window step reachable in
about 1.3 s instead of a real-server boot.

**Gate reverted** — `match window.is_visible() { ... }` replaced by the
pre-diff `navigate(url)`-only closure, supervisor rebuilt:

```
$ DESKTOP_SUPERVISOR_BIN=.../supervisor .venv/bin/python -m pytest \
    tests/test_desktop_child.py -m requires_desktop_stack \
    -k "attests_the_window or hidden_window"
.F                                                                       [100%]
___________________ test_fault_hidden_window_fails_the_cycle ___________________
>           assert process.wait(timeout=_SUPERVISOR_WAIT_TIMEOUT) == 1, ...
E           AssertionError: [ ..., {'elapsed_ms': 290, 'event': 'window-ready',
E                                   'fields': {'window_ordered_in': True}, ...}, ...]
E           assert 0 == 1
FAILED tests/test_desktop_child.py::test_fault_hidden_window_fails_the_cycle
1 failed, 1 passed, 27 deselected in 1.33s
```

The supervisor exited **0** and recorded
`window-ready {"window_ordered_in": true}` for a window that was ordered
**out** — the exact "the event asserts more than it observed" defect #423 was
filed about, reproduced on demand.

**Gate restored** (byte-identical to the committed source; verified by
`grep -n "match window.is_visible()"` resolving to `lifecycle.rs:417`),
supervisor rebuilt:

```
..                                                                       [100%]
2 passed, 27 deselected in 1.38s
```

The pass arm is green in both runs, which is why it is not the guard: it pins
the payload the attested path emits, and the fault arm is what makes the gate
non-deletable.

## Test deltas

- `tests/test_desktop_child.py::test_fault_hidden_window_fails_the_cycle` —
  **the H1 guard.** Ordered-out window means supervisor exit 1, `mcp-smoke-ok`
  present (so it is the WINDOW step failing, not an earlier arm producing the
  same code), `lifecycle-failed` reason exactly
  `"window not visible after navigate"`, no `window-ready`, plus the same
  bounded-cleanup assertions every other Err arm carries (reaped child,
  released listener) — the gate must not trade a lie for a leak.
- `tests/test_desktop_child.py::test_fixture_cycle_attests_the_window_before_reporting_ready`
  — pass arm: fault-free fixture, exit 0, `window-ready` payload equals
  `_WINDOW_READY_FIELDS`, `shutdown-clean 0`.
- `tests/test_desktop_child.py:457` (AC3, real child) — presence assertion
  upgraded to payload equality, sharing the `_WINDOW_READY_FIELDS` constant so
  the two cannot drift.
- `apps/desktop/crates/supervisor/src/main.rs::plan_rejects_unknown_fields_and_empty_argv`
  — asserts `test_hide_window` defaults to `None` on a production plan.
- `apps/desktop/crates/supervisor/src/main.rs::test_only_knobs_are_refused_outside_smoke_mode`
  — asserts a non-smoke plan carrying `test_hide_window` is refused.

## Production / fixture deltas

- `apps/desktop/crates/supervisor/src/lifecycle.rs` — event field rename plus
  narrowed doc comment. **The gate's control flow is unchanged.** The two Err
  reason strings were deliberately left alone: `Ok(false)` genuinely means not
  visible, so the over-claim M1 names exists only on the positive arm.
- `apps/desktop/crates/supervisor/src/main.rs` — `test_hide_window` plan knob,
  refused outside smoke mode alongside the existing test-only knobs, applied as
  `.visible(false)` on the window builder.
- `apps/desktop/crates/fixture-sidecar/src/main.rs` — reads the request body
  (Content-Length; the client writes headers and body as two syscalls) and
  answers `initialize` / `notifications/initialized` / `tools/list`. **Gated on
  `Fault::None`**, which no existing test uses: serving the smoke on every arm
  would carry `ignore-shutdown` and `crash-after-ready` PAST the step they
  assert, turning their `orphan-shutdown` assertions into `shutdown-unclean`.
  Method matching is on the exact serialized strings including the closing
  quote — `notifications/initialized` contains `initialize`.
- `apps/desktop/README.md` — the macOS-only gate limitation and the
  `window-ready` attestation scope, both beside the existing m6 non-claims.

## Check gate results (measured at the final tree)

| gate | result | baseline at `7711f45` |
|---|---|---|
| `cargo fmt --all --manifest-path apps/desktop/Cargo.toml -- --check` | PASS (clean) | clean |
| `cargo clippy --locked ... --workspace --all-targets --all-features -- -D warnings` | PASS (clean) | clean |
| `cargo test --locked --workspace` | **20 passed** (8 + 12), 0 failed | 20 |
| `make desktop-conformance PYTHON=.venv/bin/python` | **exit 0** — 42 passed (contract) + **29** passed (child), **zero skips** | exit 0, 42 + 27 |
| `make test PYTHON=.venv/bin/python` | **exit 0** — 5091 passed, 60 skipped, 1 xfailed in 320.99 s | 5091 / 58 / 1 |
| `git status --porcelain` | clean | — |

The child count moves 27 to 29 (the two new tests) and `make test`'s skips move
58 to 60 for the same two: they are `requires_desktop_stack`, deselected by
default through the documented `_OPT_IN_MARKERS` mechanism, and run — passing,
with zero skips — inside `make desktop-conformance`. **The passed count is
identical at 5091**, so nothing regressed.

## Rect commit

- `rect(desktop): guard the window-ready gate`
  (`Reviewed-by: milestone-adversary-critic`, `Co-Authored-By: Claude Opus 5`),
  GPG-signed with `-S`. `Fixes #423` is deliberately **absent**: that issue's
  premise was refuted by measurement (see `implement/synthesis.md`) and its
  closure is the owner's call, not this pipeline's.

## external_writes_required — NOT executed here

- `git push origin main`

## Left for the main session (one-writer rule)

`checkpoint.py` was deliberately not run here. Remaining state writes:

```bash
CP=.claude/scripts/milestone-pipeline-checkpoint.py
FP=.claude/scripts/milestone-pipeline-findings.py
ID=adhoc-20260808-f62f387
.venv/bin/python "$CP" $ID --set fixed_findings="$(.venv/bin/python "$FP" summary $ID --field fixed_findings)"
.venv/bin/python "$CP" $ID --set deferred_findings="$(.venv/bin/python "$FP" summary $ID --field deferred_findings)"
.venv/bin/python "$CP" $ID --set invalidated_findings="$(.venv/bin/python "$FP" summary $ID --field invalidated_findings)"
.venv/bin/python "$CP" $ID --set rectification_commit=<rect sha>
.venv/bin/python "$CP" $ID --append regression_tests_added=tests/test_desktop_child.py
.venv/bin/python "$CP" $ID --append regression_tests_added=apps/desktop/crates/supervisor/src/main.rs
```

`findings.py gate adhoc-20260808-f62f387` already exits 0 ("no open findings").

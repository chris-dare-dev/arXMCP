# Implementation synthesis — adhoc-20260808-f62f387 (issue #423)

## Headline: the brief's Defect-1 baseline claim is REFUTED by controlled measurement

The brief asserted the committed build "owns 0 windows". Re-measured at base
`e28426f` on this box (macOS, GUI session), with the System Events probe
positive-controlled AND negative-controlled against the exact process identity:

| build variant | System Events windows of supervisor pid | `is_visible()` (instrumented) |
|---|---|---|
| committed (`.title("arXMCP").build()`) — 3 independent runs | **1, 1, 1** (AXStandardWindow, 800x600, title `arXMCP`, minimized=false, process visible, not background-only) | `true` |
| `.visible(false)` injected (negative control) | **0, 0, 0, 0, 0** | `false` |
| brief's three calls (`.visible(true)` + `show()` + `set_focus()`) | **1, 1, 1, 1, 1** | `true` |

Runs used the built supervisor driving the fixture sidecar on the `never-ready`
arm (stable live interval), probed by `count windows of (first application
process whose unix id is <pid>)`, with a same-run positive control (an unrelated
windowed process, e.g. ghostty pid 659 → 1). The negative-control row proves the
probe discriminates present-from-absent for THIS process — the committed build's
1 is a real observation, not probe noise.

**Minimal sufficient subset of {`.visible(true)`, `show()`, `set_focus()`}: the
EMPTY SET.** `visible` defaults to true in Tauri's builder; `build()` already
creates the on-screen native window; the three calls changed nothing observable
(1 → 1). None was kept. `set_focus()` in particular would add focus-stealing on
every launch with zero measured benefit. A comment at the builder now records
this so the refuted "fix" is not cargo-culted in later.

The brief's second measurement claim — "`is_visible()` returned Ok(true) in a
run with zero native windows" — is also refuted: instrumented, `is_visible()`
returned `false` for the hidden-window build and `true` for the default build.
It honestly tracks native visibility here. (Both brief claims appear to be
downstream of the same evidence failure the brief itself warns about: #423 was
filed on a `CGWindowListCopyWindowInfo` null → "no windows for every app"
misread; no raw probe transcript was left in `research/` to reconstruct the
researcher's exact query, but a plausible mechanism is resolving the target by
the wrong process identity, which their Ghostty/Chrome positive control could
not catch.)

## What changed

1. **`apps/desktop/crates/supervisor/src/lifecycle.rs` — `window-ready` no
   longer lies (Defect 2, real regardless of Defect 1).** `navigate_window`'s
   main-thread closure now, after `navigate()` succeeds, requires
   `window.is_visible()` == `Ok(true)`; `Ok(false)` fails the cycle with
   `"window not visible after navigate"` and `Err(_)` with
   `"window visibility unobservable"`. `window-ready` is emitted only on the
   attested path and now carries `{"visible": true}` — the event states what
   was observed. A supervisor whose window is missing now exits 1 with a named
   `lifecycle-failed` reason instead of reporting success.
   Chosen over rename/removal because a truthful discriminating observation
   exists (measured above); AC3's `window-ready` assertion stays valid.
2. **`apps/desktop/crates/supervisor/src/main.rs`** — comment-only change
   anchoring the measurement at the window build site (no behavior change; the
   builder is correct as committed).
3. **`tests/test_desktop_child.py` —
   `test_supervisor_owns_a_native_window_while_running`** (marked
   `requires_desktop_stack`; the marker already exists in `pyproject.toml` and
   `tests/conftest.py::_OPT_IN_MARKERS`, so nothing new to register).

## Regression's positive-control mechanism

Before the supervisor is spawned, the test sweeps System Events for ANY process
owning >= 1 window and then re-counts it via the SAME `_native_window_count`
function later aimed at the supervisor — validating both observation capability
and the unix-id query shape in the same run. Outcomes:

- osascript errors (Automation/AX denied) → **loud skip** naming the permission
  — permission-denied is never read as absence (#423's mistake);
- zero windows observable anywhere (headless) → **loud skip**;
- sweep/count disagree → **fail** naming the probe, not the supervisor;
- non-macOS → **loud skip** (no positive-controllable probe wired there).

Every skip is converted to a session FAILURE by the existing desktop-conformance
zero-skip gate (`tests/conftest.py` fails the session on any skip while
`DESKTOP_SUPERVISOR_BIN`/`ARXMCP_FIXTURE_SIDECAR` is set), honoring "never pass
silently". Only then does it spawn the supervisor (never-ready arm), wait for
`child-bound`, and require >= 1 native window attributed to the supervisor's pid
within 15 s plus the window title containing `arXMCP`.

## Demonstration that the regression and the gate discriminate

Pre-fix behaviour cannot be "reverted to" (no builder change exists); the
defect #423 alleges — registered window, no native window — was INJECTED with
`.visible(false)` on the committed builder:

- **Injected build, regression test:** FAILED —
  `AssertionError: supervisor pid 35504 owns 0 native windows while running —
  issue #423 regressed. The probe is NOT blind: pid 659 showed 1 window(s)
  this same run.`
- **Injected build, AC3 (real child, full cycle):** FAILED; event log ends
  `mcp-smoke-ok → lifecycle-failed {"reason":"window not visible after
  navigate"} → orphan-shutdown {"child_exit":0}`, supervisor exit 1, **no
  `window-ready` event** — where the pre-change code emitted `window-ready` and
  exited 0 on the same hidden-window build.
- **Real build:** regression PASSES; full conformance PASSES (window-ready
  emitted as `{"visible": true}`).

## Gates (all green, measured at the final tree)

- `cargo fmt --all --manifest-path apps/desktop/Cargo.toml -- --check` — clean.
- `cargo clippy --locked … --target-dir /private/tmp/arxmcp-desktop-target
  --workspace --all-targets --all-features -- -D warnings` — clean.
- `cargo test --locked --workspace` — **20 passed** (8 + 12), 0 failed.
- `make desktop-conformance PYTHON=.venv/bin/python` — **42 passed** (contract)
  + **27 passed** (child; baseline 26 + the new regression), **zero skips**.
- `make test PYTHON=.venv/bin/python` — **5091 passed, 58 skipped, 1 xfailed**
  in 315.89 s. Baseline was 5091/57/1: passed count identical; the +1 skip is
  the new opt-in-marked regression deselected by default (the documented
  `_OPT_IN_MARKERS` mechanism) and run — passing — inside desktop-conformance.

## Deviation from the brief (declared)

The brief's "verified fix direction" (add visible/show/set_focus) was not
applied: the milestone's own instruction was to determine the minimal
sufficient subset by measurement, and the measurement — positive- and
negative-controlled — shows the subset is empty because the defect does not
exist in the committed builder. What ships instead is the evidence-bearing
`window-ready` gate (so a genuinely missing window can never again be reported
as success, on any environment where it might reproduce) and an OS-level
regression test that fails on true window absence while refusing to mistake a
blind probe for one.

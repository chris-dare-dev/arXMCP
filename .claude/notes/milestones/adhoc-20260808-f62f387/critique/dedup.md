# Critique — adhoc-20260808-f62f387 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** e28426f..7711f45
**Diff stats:** 7 files, 348 LOC (345 insertions, 3 deletions; 137 of them code/test, 211 `.claude/notes` artifacts)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. The refutation of the brief's Defect-1 premise is sound and
well-controlled, the `is_visible()` gate is a real improvement over an event
that asserted nothing, and the failure path correctly falls into `run_cycle`'s
Err arm so the child is still reaped and `orphan-shutdown` recorded. The one
material gap is that the behaviour actually shipped — the gate — has no
committed regression: revert the `is_visible()` match and every test in the
tree still passes, because the new test only proves a window exists and the
sole `window-ready` assertion checks existence, not the payload or the failure
arm. The rest are doc-accuracy and probe-attribution issues, all cheap.

## Executive summary

- [HIGH] Reverting the new gate breaks nothing: `tests/test_desktop_child.py:457`
  asserts only that `window-ready` exists, and the new test passes with or
  without the visibility check. The evidence for the gate is a manual,
  uncommitted `.visible(false)` build.
- [MEDIUM] `is_visible()` resolves to `NSWindow.isVisible` (tao-0.35.3
  `platform_impl/macos/window.rs:1075`), which Apple defines as on-screen *even
  when obscured* — so occluded, off-screen-positioned, zero-sized and
  other-Space windows all return `Ok(true)`. `{"visible": true}` and the new
  doc comment's "observably visible" claim more than that.
- [MEDIUM] The 15 s poll swallows every `RuntimeError` from the probe, so at
  the moment the test concludes absence it has no live evidence the probe still
  works — and its failure message asserts probe-liveness from an observation
  taken before the supervisor was spawned.
- [MEDIUM] The module docstring (`tests/test_desktop_child.py:11`) still says
  `requires_desktop_stack` tests here "carry NO secondary skip guard"; the new
  test adds three.
- [MEDIUM] The non-darwin skip plus the zero-skip gate means the child half of
  `make desktop-conformance` can no longer pass on Linux, a declared
  portability target (`apps/desktop/README.md:12-17`), and nothing records that.
- [LOW] The positive control is two separate osascript invocations, so a
  swept process closing its last window in between fails the test.
- No CRITICALs. Both commits are GPG-signed (`%G? = G`, `gpgsig` header present
  on each), both carry `Co-Authored-By: Claude Opus 5`, subjects are
  conventional and ≤ 50 chars, `server/**` is untouched, no `plans/` or
  roadmap file is touched, and the diff performs no external write.
- Diff is 348 changed LOC (137 excluding `.claude/notes`), below the 400-LOC
  threshold, so the mandatory diff-size auto-finding is **not** filed —
  `allow_large_diff` is `false` in `state.json` and was not needed.

## Findings

**H1 — The shipped visibility gate has no committed regression** (HIGH)

**Where:** `apps/desktop/crates/supervisor/src/lifecycle.rs:411`
**Anchor:** `match window.is_visible() {`
**What:** Deleting the `is_visible()` match (restoring the pre-diff
`navigate(url)`-only behaviour) fails no test in the tree: the new
`test_supervisor_owns_a_native_window_while_running` asserts a window exists,
which is true with or without the gate; the only `window-ready` assertion,
`tests/test_desktop_child.py:457`, checks event presence and never the new
`{"visible": true}` payload; and no test exercises the
`lifecycle-failed {"reason":"window not visible after navigate"}` arm.
**Why it matters:** The one behavioural change this milestone ships is
unguarded — its entire evidence base is a manual, uncommitted `.visible(false)`
build described in `implement/synthesis.md:82-97`, which the next agent cannot
re-run and CI cannot enforce, so a later refactor silently returns
`window-ready` to claiming what it did not observe.
**Proposed fix:** Two parts. Cheap and immediate: tighten
`tests/test_desktop_child.py:457` to assert the payload, e.g.
`assert [e["fields"] for e in by_name("window-ready")] == [{"visible": True}]`,
which pins the attested field so removing the gate fails the suite. Proper:
add a test-only supervisor plan knob beside the existing ones in
`apps/desktop/crates/supervisor/src/main.rs:41-57` (e.g. `test_hide_window:
Option<bool>` calling `window.hide()` on the main thread before navigate),
refuse it outside smoke mode in `validate_plan` at `main.rs:88-95`, add it to
the production-plan `assert_eq!(plan.test_*, None)` unit test at
`main.rs:312-315`, and add an m6-style fault arm asserting supervisor exit 1,
`lifecycle-failed` with the exact reason string, `orphan-shutdown`, and **no**
`window-ready` — i.e. commit the injection the synthesis ran by hand.
**Regression-guard:** the payload assertion at
`tests/test_desktop_child.py:457` plus
`tests/test_desktop_child.py::test_fault_hidden_window_fails_the_cycle`.
**Source critic:** milestone-adversary-critic
**Source axis:** Test discipline / acceptance coverage

**M1 — `{"visible": true}` claims more than `NSWindow.isVisible` measures** (MEDIUM)

**Where:** `apps/desktop/crates/supervisor/src/lifecycle.rs:395`
**Anchor:** `/// Ok additionally attests the native window is observably visi`
**What:** `WebviewWindow::is_visible()` dispatches to tao's macOS
implementation, which is a bare `self.ns_window.isVisible()`
(`~/.cargo/registry/.../tao-0.35.3/src/platform_impl/macos/window.rs:1075-1077`),
and AppKit defines that property as "true when the window is onscreen **even if
it's obscured by other windows**" — so a fully occluded window, one positioned
off every display, a zero-sized one, and one on another Space all return
`Ok(true)`, and nothing about the WebView's render state is read at all; the
only absence mechanism the milestone actually discriminated was
`.visible(false)` (ordered-out).
**Why it matters:** This milestone exists because an event asserted more than
it observed; the residual over-claim is far smaller but the same category, and
the doc comment ("observably visible") plus the event key (`visible`) will be
read by the next agent as proof a user can see the window.
**Proposed fix:** Docs only, ≤ 10 LOC. Narrow the comment to the predicate
actually evaluated — "attests the native window is ordered in
(`NSWindow.isVisible` on macOS); it does not establish that the window is
unoccluded, on-screen, non-zero-sized, or has rendered" — and either keep
`visible` with that caveat recorded or rename the field to what is measured
(`{"window_ordered_in": true}`), consistent with CLAUDE.md §4.9's "no axis
inferred from another".
**Regression-guard:** n/a (MEDIUM; the H1 payload assertion pins whichever key
is chosen).
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift / trust language

**M2 — Absence is concluded with no live proof the probe still works** (MEDIUM)

**Where:** `tests/test_desktop_child.py:1369`
**Anchor:** `            with contextlib.suppress(RuntimeError):`
**What:** Every `RuntimeError` raised by `_native_window_count` inside the 15 s
poll is suppressed and discarded, so a probe that goes blind mid-loop — System
Events erroring, Accessibility access lost, or the supervisor having exited —
is indistinguishable from a supervisor that owns no window; the assertion at
`:1374` then declares "issue #423 regressed" and defends itself with "The probe
is NOT blind: pid X showed N window(s) this same run", a claim about an
observation taken *before the supervisor was even spawned*.
**Why it matters:** Reading a probe failure as verified absence is exactly the
mistake that produced #423, and `apps/desktop/README.md:131-137` states this
repo's own discipline more strictly than the test implements it — every absence
query there "rides the same invocation as a control", not a control from an
earlier invocation.
**Proposed fix:** ~15 LOC. Bind the suppressed exception
(`except RuntimeError as exc: last_probe_error = exc`) instead of discarding
it; on timeout, re-probe `control_pid` before asserting — if the control now
raises or reads 0, `pytest.skip`/fail naming the probe rather than the
supervisor — and include `last_probe_error` in the message. While there,
consider that a denied Accessibility grant may surface as a per-process error
swallowed by the inner `try` in `_any_windowed_pid`, which then skips with the
"headless session?" wording at `:1350`; naming both causes in that message
keeps the diagnosis honest.
**Regression-guard:** n/a (MEDIUM).
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness / evidence discipline

**M3 — Module docstring contradicts the test the file just gained** (MEDIUM)

**Where:** `tests/test_desktop_child.py:11`
**Anchor:** `precedent, they carry NO secondary skip guard:`
**What:** The module docstring states that the `requires_desktop_stack` tests
in this file, "following the `requires_latexmlc` precedent, carry NO secondary
skip guard: opting in with a missing prerequisite fails loudly" — the new test
adds three secondary guards (`sys.platform != "darwin"` at `:1335`, probe
unavailable at `:1341`, zero windows anywhere at `:1348`).
**Why it matters:** The docstring is the stated convention for every future
desktop test in this file; leaving it asserting the opposite of what the file
does is the doc-drift class CLAUDE.md §4.5 already had to correct once for this
marker.
**Proposed fix:** Amend the docstring to record the single exception and why it
is sound: a probe that could report absence must be positive-controllable, so
this one skips rather than raising, and the desktop-conformance zero-skip gate
(`tests/conftest.py:49,63,79-86`) converts that skip into a session failure
rather than a silent pass.
**Regression-guard:** n/a (MEDIUM).
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**M4 — `make desktop-conformance` can no longer pass on Linux** (MEDIUM)

**Where:** `tests/test_desktop_child.py:1335`
**Anchor:** `    if sys.platform != "darwin":`
**What:** `Makefile:161` runs this suite with `DESKTOP_SUPERVISOR_BIN` set,
which `tests/conftest.py:49,63,79-86` treats as "this session is the
authoritative gate and must have ZERO skips" — so the non-darwin skip makes the
child half of the gate fail unconditionally off macOS. Before this diff
`tests/test_desktop_child.py` contained no `sys.platform` guard at all.
**Why it matters:** `apps/desktop/README.md:12-17` names Linux x86-64 and
Windows x86-64 as portability targets for the same workspace, and CLAUDE.md
§4.5 documents this marker's Linux prerequisites (`apt install lsof` /
`procps`), so an operator following those docs on Linux now gets a red gate
with no way to make it green and no note explaining why.
**Proposed fix:** Pick one and record it: either allow this single nodeid to
skip on non-darwin inside the conftest gate (an explicit, named exemption
rather than a blanket weakening), or declare the child conformance gate
macOS-only and say so in `apps/desktop/README.md` §"Supported boundary" and the
module docstring. Note the precedent is already mixed —
`tests/test_desktop_contract.py:650`'s win32 `skipif` trips the same gate under
`ARXMCP_FIXTURE_SIDECAR`, so Windows was already affected; Linux is the newly
broken case.
**Regression-guard:** n/a (MEDIUM).
**Source critic:** milestone-adversary-critic
**Source axis:** Repo-gate compliance / doc drift

**L1 — Positive control races across two osascript invocations** (LOW)

**Where:** `tests/test_desktop_child.py:1354`
**Anchor:** `    control_count = _native_window_count(control_pid)`
**What:** `_any_windowed_pid()` and `_native_window_count()` are separate
osascript round trips; if the swept process closes its last window between
them, the self-check assertion fails the test outright rather than re-sweeping.
**Why it matters:** A gate failure attributed to an unrelated application — the
message is honest about it, but the run is red for a reason that has nothing to
do with the supervisor.
**Proposed fix:** Retry the sweep two or three times before failing, or fold
the sweep and the by-unix-id re-count into ONE osascript invocation, which is
also the same-invocation control shape `apps/desktop/README.md:131-137`
prescribes.
**Regression-guard:** n/a (LOW).
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

## What was done well

- The brief was refuted by measurement rather than obeyed: a negative control
  (`.visible(false)` → 0, 0, 0, 0, 0) is what makes the committed build's `1`
  a real observation instead of probe noise, and three independent runs plus a
  same-run positive control is more rigour than the brief itself carried.
- Refusing to apply `.visible(true)` / `show()` / `set_focus()` when the
  measured minimal subset was empty is the right call — `set_focus()` in
  particular would have added focus-stealing on every launch for zero benefit —
  and the deviation is declared explicitly rather than buried.
- The failure path is correct and does not reintroduce the m6 hazard: an Err
  from `navigate_window` lands in `run_cycle`'s Err arm
  (`lifecycle.rs:88-96`), which takes the `ChildControl` set at `:181`, runs
  `shutdown_child`, and records `orphan-shutdown` — the child is reaped and the
  listener released exactly as the other fault arms are.
- Splitting `Ok(false)` from `Err(_)` into two distinct reason strings
  ("window not visible after navigate" vs "window visibility unobservable")
  keeps observation failure separate from observed absence, which is precisely
  the §4.9 distinction the repo's own policy demands.
- Deliberately not using `CGWindowListCopyWindowInfo`, and saying in the
  docstring exactly why (null without Screen Recording permission reads as "no
  windows for every app"), turns the root cause of #423 into a durable
  in-repo warning.
- The probe's two blind-failure modes both terminate in a loud skip rather
  than a pass: a `tell`-level osascript error raises and skips, and an
  all-processes-zero sweep skips — and the existing zero-skip gate turns either
  into a session failure. `TimeoutExpired` and `OSError` are deliberately
  outside the `contextlib.suppress`, so those propagate loudly too.
- Choosing the `never-ready` arm is a good test-design call: it parks the
  supervisor in a stable live interval and the window is built in `setup()`
  long before readiness, so the probe window is wide and deterministic.
- Scope was held exactly: `server/**` untouched, no contract or MCP-surface
  change, the window-builder bytes identical to the baseline, and the only
  `main.rs` delta is a comment recording the measurement so the refuted "fix"
  is not cargo-culted back in.
- Commit hygiene is clean — two conventional, ≤ 50-char subjects, both
  GPG-signed with a `gpgsig` header and `%G? = G`, both carrying the mandated
  `Co-Authored-By` trailer, and the implementation/notes split honours the
  repo's per-milestone commit pattern.

Severity counts: C0 H1 M4 L1

## Recommended rectification order

H1, M2, M1, M3, M4, L1

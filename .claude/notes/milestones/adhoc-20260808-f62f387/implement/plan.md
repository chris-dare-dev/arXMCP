# Implementation plan — adhoc-20260808-f62f387 (issue #423)

- **Defect 1:** determine empirically which of `.visible(true)` / `show()` / `set_focus()` is
  the minimal sufficient subset to create a native window, by building one variant per call and
  probing the running supervisor (never-ready fault plan, fixture sidecar child) with the
  System Events window count, positive-controlled in the same run. Keep only what is proven
  necessary in `main.rs::setup()`.
- **Defect 2:** gate the `window-ready` event in `lifecycle.rs` on an observation that a native
  window genuinely exists (macOS: `NSWindow`-backed check via tauri's window handle or an
  outer-size/native-handle probe evaluated on the main thread), or rename the event to what it
  actually establishes if no in-process observation is trustworthy (`is_visible()` measured
  lying). Decision recorded in the synthesis.
- **Regression:** new `requires_desktop_stack` test in `tests/test_desktop_child.py` driving the
  built supervisor against the fixture sidecar (never-ready arm = stable probe window). Probe =
  osascript System Events `count windows of (process whose unix id = pid)`. Positive control in
  the SAME run: the same probe function must first report >=1 window for some process on the
  machine; if it cannot (headless / Automation denied / non-macOS), skip LOUDLY naming the
  capability — the conformance session's zero-skip gate then fails, per discipline. Marker
  already registered in pyproject + `_OPT_IN_MARKERS`; no new marker.
- **Demonstration:** run the new test against the pre-fix supervisor binary (stash the fix,
  rebuild) — must FAIL; rebuild with the fix — must PASS. Evidence quoted in synthesis.
- **Validation:** cargo fmt --check, clippy -D warnings, `make desktop-conformance`,
  `make test`; `git status --porcelain` empty; single signed conventional commit, scope
  `desktop`, no `Fixes #423`, never push.

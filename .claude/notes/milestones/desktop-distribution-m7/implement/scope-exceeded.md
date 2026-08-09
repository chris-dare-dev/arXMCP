# Scope record — desktop-distribution-m7 (--allow-large-diff)

Final diff: ~1,258 insertions / 14 files vs base `81d04ec` (excludes the
orchestrator-owned state.json). Over the 800-LOC soft-abort line; the owner
pre-authorized `--allow-large-diff` at dispatch, so the 350-LOC/6-file
mid-flight STOP did not apply.

Why the size is intrinsic, not padding (matches brief-3's re-derived
490–920-LOC estimate, top half):

- AC3 is greenfield (`freeze_support` + a real frozen-subprocess proof), not
  verification — the brief's single biggest scope correction.
- AC1's closed exception set required a two-build harness with per-file
  manifests, plus spec-level normalization of the two measured ordering
  drifts — the honest design brief-3 demanded over an open exception list.
- AC5's scanner had to reach INSIDE nested zips and the executables'
  embedded PYZ archives (compressed .pyc bytes are invisible to a raw grep);
  that nested pass is what caught the real `_sysconfigdata` leak.
- ~347 of the lines are tests; ~42 are the generated hash lockfile.

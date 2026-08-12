# Rectify summary — desktop-distribution-m10

Critique: `.claude/notes/milestones/desktop-distribution-m10/critique/dedup.md`
(merged ids from three critics). Commit range rectified against:
`b102c85..3327edb`. Dispositions are written through
`milestone-pipeline-findings.py set` (the sole status writer);
`findings.py gate` exits 0 with no open findings.

**29 findings: C1 H4 M16 L8. 21 fixed, 8 deferred, 0 invalidated
(invalidation rate 0%).** Every CRITICAL and HIGH anchor was re-verified
against live code before fixing; none had drifted.

## Dispositions

| id | sev | disposition | detail |
|----|-----|-------------|--------|
| C1 | CRITICAL | fixed | `apps/desktop/README.md` no longer says launch-plan authoring "is not here yet" — this milestone is what put it there |
| H1, H3 | HIGH | fixed | version coupling documented at the call site and pinned by an unmarked test |
| H2 | HIGH | fixed | owner authorized `allow_large_diff`; see the scope note below |
| H4 | HIGH | fixed | layout/component constants derived and pinned, not copied |
| M1 | MEDIUM | fixed | `pathlib_normalize` — AC5's parity claim was false, now true |
| M2, M14 | MEDIUM | fixed | fixture-override rationale corrected; a discriminating test added |
| M3 | MEDIUM | fixed | `CLAUDE.md` §4.5 marker prose amended for m10 |
| M4, M5, M6, M8 | MEDIUM | fixed | same change as H4 |
| M7 | MEDIUM | fixed | lazy home lookup; the second divergence is gone |
| M9 | MEDIUM | fixed | caption now claims only what it asserts |
| M10 | MEDIUM | fixed | `args_os()` — no panic on non-UTF-8 argv |
| M11 | MEDIUM | fixed | scope recorded (below) rather than absorbed |
| M12 | MEDIUM | fixed | sibling-write risk ranked first and written for operators |
| M13 | MEDIUM | fixed | symlinked payload root refused |
| M15 | MEDIUM | fixed | Windows branch pinned on both sides by source |
| M16 | MEDIUM | fixed | no-orphan asserted on the `smoke: false` arm |
| L1–L8 | LOW | deferred | owner decision; reasons recorded per finding |

## The three findings that were real defects, not hygiene

**M1 — an acceptance criterion was false, and the test was too weak to say
so.** AC5 claimed byte-for-byte `data_root` parity across an env matrix. The
matrix contained no path-normalizing value, so `HOME=/a//b` and `HOME=/a/./b`
derived `/a//b/Library/...` in Rust against Python's `/a/b/Library/...`. In
production that is a silent bifurcation: the application reads one corpus
location while the CLI and every ops tool write another, so the app looks
empty and the operator's ingest lands where it is never read. The critic
measured it against the built binary rather than reasoning about it. Fixed by
porting `PurePosixPath`'s construction semantics (including POSIX's
exactly-two-leading-slashes rule) and adding the six rows that reproduced it.

**M13 — the containment check did not check the root.** `resolve_inside`
canonicalized both sides, but the root was whatever
`<supervisor dir>/arxmcp-desktop-child` canonicalized TO. Symlink that entry
at `/tmp/evil` and the canonical root moves with it, the candidate resolves
inside it, containment holds, and an arbitrary binary executes. The unit test
staged a symlinked CHILD and never a symlinked ROOT, so the doc comment's
"a symlink out of the payload root cannot" was false for exactly the shape an
attacker would use. Now refused via `symlink_metadata` before canonicalizing,
with a test staging that shape.

**H1/H3 — two unrelated version lines compared for equality.** The
self-authored plan sent `env!("CARGO_PKG_VERSION")` as the CHILD's expected
executable-identity version. `lifecycle.rs` puts it in the launch frame and
`server/desktop_child.py:182` refuses on mismatch, where the child reports
`importlib.metadata.version("arxmcp")`. They agreed only because both happen
to read `0.1.0` today, and the fixture compiles the same constant, so no test
could ever have caught the divergence. Now asserted on every `make test`.

## Scope, recorded rather than absorbed (H2 / M11)

- Implementation commit range: **770 insertions / 10 deletions across 4 code
  files** (991/10 including notes), against a ~520 LOC pre-authorization.
- Rectification adds **457 insertions / 32 deletions across 7 files**.
- Total m10 code footprint: **~1,227 insertions**, roughly 2.4× the original
  estimate.

The process defect H2 names is real and is the orchestrator's, not the
implementer's: `allow_large_diff` was pre-authorized in the dispatch prompt
but never written to state — **the identical omission that produced m8's H2**.
Twice in consecutive milestones is a pattern, not an accident.

**m15 should re-base off the measured 1,227, not off a fresh guess.** It
re-points the same two functions (`child_payload_root`, `resolve_inside`),
re-runs m7/m8/m9's guards over an assembled artifact, and owns a
bundle-mechanism ADR — there is no reason to expect it smaller than m10.

## What the fixes do NOT close

- **AC1 still proves the green arm against the fixture sidecar** staged in
  m7's onedir shape, not the real ~0.75 GB frozen bundle. No committed gate
  builds the Rust supervisor and the PyInstaller bundle in one session. This
  was true before rectification and remains m15's to close; the critics
  honored the scope fence and did not file it.
- **`std::env::current_exe()` is still not a security primitive.** The
  PATH-search and hardlink classes stay open by decision. They carry no
  privilege gradient on a non-setuid binary, which is why M12 ranked the
  sibling-write class above them rather than closing either.
- **The Windows data-root branch is still unexecuted.** M15's fix pins both
  sides by source so a one-sided edit fails; it does not run the branch,
  because no Windows runner exists.

## Gate results (orchestrator-measured, serialized)

| gate | result |
|---|---|
| `make test` | exit 0 — **5152 passed, 97 skipped, 1 xfailed, 0 failed** |
| `make desktop-conformance` | exit 0 — cargo **20 + 8 passed**, fmt + clippy `-D warnings` clean, pytest **42 + 30 + 33 + 24 = 129 passed, zero skips** |

Both were re-run to completion after the final edit, serially, with full logs
and the real exit code captured.

### One gate failure during this phase, and what it was

The first post-rectification conformance run failed 2 of the m10 module's
tests. Cause: two parity rows added for M7 (`XDG_DATA_HOME` and
`LOCALAPPDATA` with no `HOME`) are structurally **unreachable on macOS** — it
has no platform base variable of its own, so a HOME-less row there lands on
the documented divergence instead. The rows are now platform-conditional and
the per-platform laziness is pinned in Rust by
`the_home_lookup_is_lazy_like_pythons`, which runs everywhere `cargo test`
does. The failure was the orchestrator's bad test data, not a code defect —
and the test refusing to pretend otherwise is the behavior wanted.

Separately, an earlier conformance run failed
`test_thirty_cycles_distinct_pids_no_orphans_no_listeners` under
orchestrator-induced concurrency (three runs racing one `target/` dir and the
same loopback ports). Serialized, it passes. Recorded as finding **L6**
(deferred) because the sensitivity is real even though the failure was not.

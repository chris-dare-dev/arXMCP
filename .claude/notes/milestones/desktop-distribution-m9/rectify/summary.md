# Rectify summary — desktop-distribution-m9

Rect commit: 539c806 (GPG %G? = G), NOT pushed.

Rectifier: milestone-rectifier (exception path). Critique: `critique/dedup.md`
(C0 H2 M3 L1). Commit range rectified: `2f319af..0b11bbc`.

## Dispositions

| id | severity | disposition | detail |
|----|----------|-------------|--------|
| H1 | HIGH   | fixed | `TestBuiltArtifactDeclaresTheFloor::test_binaries_report_the_declared_minos` reads `minos` off `LC_BUILD_VERSION` via `otool -l` for both binaries; wired into `make desktop-conformance` |
| H2 | HIGH   | fixed | Scanner broadened + negation narrowed to the governing clause; `TestScannerControls` now runs a 12-case positive and 10-case negative corpus |
| M1 | MEDIUM | fixed | `_shipped_docs()` derived from the tree (35 files, was 3 + `docs/**`); new `_shipped_event_sources()` scans 12 Rust/Python files for AC4's "or event" half |
| M2 | MEDIUM | fixed | README restores the spike's `(inferred)` marker on the M4-Max-cannot-boot-14 claim |
| M3 | MEDIUM | fixed | README restores the `lenient` qualifier and its direction (can under-report, never over-report) on the symbol scan |
| L1 | LOW    | fixed | README states the repo-root CWD requirement as a correctness precondition and names the 11.0-default consequence |

Nothing invalidated, deferred, or handed back. Every anchor re-verified against
`HEAD` before editing; all six were still live.

## H1 — demonstration (failing before passing)

Four arms, three of which must fail. The stale binary was produced by building
the sidecar with an out-of-tree config forcing `MACOSX_DEPLOYMENT_TARGET =
"11.0"` — the exact drift the implementer hit with a warm cargo cache.

| arm | expected | observed |
|-----|----------|----------|
| `ARXMCP_FIXTURE_SIDECAR` -> binary built at `minos 11.0` | FAIL | `1 failed, 1 passed` — `AssertionError: fixture-sidecar declares minos ['11.0'], not '14.0'` |
| both env vars unset | RAISE, never skip | `2 failed` — `RuntimeError: ARXMCP_FIXTURE_SIDECAR is unset` |
| `otool` absent from `PATH` | RAISE, never skip | `2 failed` — `RuntimeError: otool is required to read LC_BUILD_VERSION` |
| real binaries from `make desktop-conformance` | PASS | `2 passed` |

`otool -l` on the real artifacts reports `minos 14.0 / sdk 26.5` for both. An
empty `minos` parse also raises rather than passing — an absent
`LC_BUILD_VERSION` is an evidence failure, not a clean floor (m6 `lsof`
positive-control precedent).

## H2 — demonstration (failing before passing)

The new positive corpus was executed against the SHIPPED scanner extracted from
`git show 0b11bbc:tests/test_desktop_support_floor.py`:

```
OLD scanner misses 8 of 12 positive corpus cases:
  MISS: macOS 14 support is verified.
  MISS: The supervisor was tested successfully on macOS 14.
  MISS: The app runs fine on macOS 14.
  MISS: macOS 14 compatibility confirmed on the release runner.
  MISS: We ran the full suite on macOS 14.4 and it was green.
  MISS: The bundle installs cleanly on macOS 14.
  MISS: | macOS 14 | tested |
  MISS: There is no CI yet, and the app runs on macOS 14.
OLD scanner false-positives on 0 negative cases
```

That is the critic's measured 8-of-10 set exactly. Post-fix all 12 positives are
flagged and all 10 negatives — the README's real honest wording, verbatim, plus
near-misses — stay clean, so the fix is not a keyword sweep pointing the other
way. `test_the_shipped_readme_is_in_the_negative_corpus` asserts the negative
corpus quotes the live README rather than a paraphrase of it.

Three mechanism changes: up to three intervening tokens between the evidence
verb and its preposition; noun-form claims (`macOS 14 support is verified`,
`macOS 14 compatibility confirmed`) and Markdown support-matrix cells; and a
negation exemption that now cuts the lookback window at the nearest clause
boundary, so an unrelated cue earlier in the sentence no longer launders a real
claim. Per the critique's option (c), the module docstring and the README both
now state the scan is best-effort — a clean run means "no claim in the known
shapes", not "no claim".

## M1 — surface derivation

`_shipped_docs()` derives root `*.md` (minus `CLAUDE.md`/`AGENTS.md`),
`docs/**/*.md`, and `apps/**/*.md`: 35 files, up from the hand-listed 3 +
`docs/**`, so `SECURITY.md`, `CONTRIBUTING.md`, `OWNERS.md`, `CONTRIBUTORS.md`
and any future shipped doc are covered by default — matching the derivation
discipline of `test_wheel_packaging` / `test_assert_ban` /
`test_marker_doc_consistency`. `_shipped_event_sources()` adds AC4's event half:
12 files (`apps/desktop/crates/**/*.rs` + `server/desktop_child.py`). Both sets
carry a non-empty guard, and the event set asserts `lifecycle.rs` is in it.
Zero offenders across all 47 files.

## Test deltas

- `tests/test_desktop_support_floor.py` — 11 tests -> 33. New:
  `TestBuiltArtifactDeclaresTheFloor` (H1, 2 parametrized),
  `TestScannerControls` corpus (H2, 22 parametrized + 2),
  `test_event_source_set_is_nonempty_and_covers_the_supervisor` and
  `test_shipped_events_carry_no_unearned_macos14_claim` (M1).
- `Makefile` — `desktop-conformance` gains a third pytest line running the
  support-floor file with BOTH env vars set, so the artifact check runs where
  the binaries exist and cannot degrade to a skip (conftest zero-skip guard).

## Gate results

| gate | result |
|---|---|
| `cargo fmt --all --manifest-path apps/desktop/Cargo.toml -- --check` | PASS (clean) |
| `cargo clippy --locked ... --workspace --all-targets --all-features -- -D warnings` | PASS |
| `make desktop-conformance PYTHON=.venv/bin/python` | exit 0 — 42 + 29 + 33 passed, ZERO skips |
| `ruff check .` | PASS — All checks passed |
| `make test PYTHON=.venv/bin/python` | exit 0 — **5122 passed / 62 skipped / 1 xfailed / 0 failed** in 331s (baseline 5102/60/1; +20 passed, +2 default-skipped opt-in). Re-measured against the FINAL tree after a comment-only edit landed mid-run. |

`git status --porcelain` shows only this rectification's files plus artifacts
owned by the concurrent session in this clone (`build/`) and the critic's own
`.claude/agent-memory/milestone-adversary-critic/lessons.md`. Staging was
path-explicit; no `git add -A`.

## external_writes_required

- `git push origin main` — NOT executed. The main session gates it with explicit
  user confirmation.

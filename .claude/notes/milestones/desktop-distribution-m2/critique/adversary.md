# Critique — desktop-distribution-m2 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** 092ab7b5f6e6d30dd2b6358074d0a7b97b12d57d..3e2dd21819f7cf2ce8d5cb26934c8c59194b5253
**Diff stats:** 9 files, 952 LOC
**Critique format version:** 1.0

## Verdict

DO-NOT-SHIP

Both implementation commits are unsigned, which is a repository-level contract violation. The relocation work is directionally sound, but the smoke does not observe writes beside the installed environment and does not prove that the settings sentinel was persisted; its metadata-only observer also has a reproduced equal-size-rewrite blind spot. The cumulative 952-LOC range independently trips the mandatory review-size gate.

## Executive summary

- [CRITICAL] Both implementation commits report `%G? = N` despite the mandatory GPG-signing rule.
- [HIGH] The cumulative implementation is 952 changed LOC, over twice the mandatory 400-LOC review limit.
- [HIGH] The smoke watches the venv but not its parent, so a write beside the installed application passes unnoticed.
- [HIGH] The settings writer is called, but the only postcondition is existence of a database the live server already created.
- [MEDIUM] The metadata-only manifests can miss an equal-size content rewrite when mtime is preserved or restored.

## Findings

**C1 — Implementation commits are unsigned** (CRITICAL)

**Where:** no specific file
**Anchor:** `be709d9b3cb0bcab6dfd5f22c276e4ead64bbc01 N`
**What:** `git log --format='%H %G?'` reports `N` for both `be709d9` and `3e2dd21`, although `CLAUDE.md` requires GPG signing on every commit.
**Why it matters:** Unsigned implementation commits violate the repository's load-bearing commit-integrity contract and are a release blocker under the canonical severity rubric.
**Proposed fix:** Before any push, recreate both implementation commits with GPG signing enabled while preserving their conventional subjects and required co-author trailers, then verify every commit in the implementation range with `git verify-commit`.
**Regression-guard:** Add the implementation-range preflight `git verify-commit <sha>` for each commit and fail Phase 3 fan-in if any command exits non-zero.
**Source critic:** milestone-adversary-critic
**Source axis:** Commit hygiene

**H1 — Cumulative diff exceeds the review limit** (HIGH)

**Where:** no specific file
**Anchor:** `9 files changed, 901 insertions(+), 51 deletions(-)`
**What:** The cumulative range changes 952 LOC while `allow_large_diff` is false, exceeding the mandatory greater-than-400-LOC review threshold.
**Why it matters:** This is the rubric's defect-detection cliff: path wiring, subprocess control, filesystem observation, and 315 lines of tests are too much independent behavior for one review unit.
**Proposed fix:** Re-scope the delivery into separately dispatched, test-bearing slices under 400 changed LOC (Config consumer wiring, observer primitives, and installed-wheel orchestration), and rerun the full critique/gate cycle for each slice before integration.
**Regression-guard:** Have the pipeline compute cumulative insertions plus deletions before implementation fan-in and hard-stop above 400 LOC unless the canonical policy explicitly permits a split or continuation.
**Source critic:** milestone-adversary-critic
**Source axis:** Diff size

**H2 — Application-parent writes escape observation** (HIGH)

**Where:** `tools/wheel_install_check.py:658`
**Anchor:** `"installed environment": filesystem_metadata_manifest(venv),`
**What:** The boot smoke snapshots the venv subtree and a separate boot sandbox, but never snapshots `venv.parent`, so a runtime write such as `venv.parent / "leak.db"` changes none of the watched manifests.
**Why it matters:** The milestone explicitly requires proof that no write lands beside the installed application, and this observer permits exactly that escape while still reporting confinement success.
**Proposed fix:** Snapshot the complete wheel-check work directory (`venv.parent`) after build/install and require it to remain unchanged during boot, while retaining the separate data-root allowance only for the boot sandbox's `data/` subtree.
**Regression-guard:** Add a synthetic test that creates a sibling file beside `venv` between snapshots and asserts the application-parent guard raises `CheckFailed` naming that path.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**H3 — Settings write has no persisted-effect check** (HIGH)

**Where:** `tools/wheel_install_check.py:765`
**Anchor:** `data_dir / "cache" / "notebooks.db",`
**What:** The smoke treats `notebooks.db` existence as proof of the settings write even though server startup creates that same file before `_WRITER_PROBE` calls `set_setting`, so a no-op settings writer still passes every postcondition.
**Why it matters:** The explicit acceptance criterion requires an observed settings write beneath the root, not merely a successful function call against a pre-existing notebook database.
**Proposed fix:** Read `desktop_relocation_probe` back from `config.notebooks_db_path` with `get_setting` inside the installed probe, fail unless its value is exactly `"ok"`, and include the verified value in the structured parent report.
**Regression-guard:** Add a probe test with `set_setting` replaced by a no-op and require the persisted-effect assertion to fail even when `notebooks.db` already exists.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**M1 — Metadata manifest misses equal-size rewrites** (MEDIUM)

**Where:** `tools/wheel_install_check.py:454`
**Anchor:** `File contents are not hashed: hashing a dependency-complete venv would`
**What:** `filesystem_metadata_manifest` records type, size, mtime, mode, and symlink target but no regular-file digest, so rewriting `AAAA` to `BBBB` and restoring the original mtime produces an identical manifest.
**Why it matters:** The before/after comparison can certify an unchanged checkout, CWD, or installed tree even though file bytes changed, weakening the smoke's no-outside-write evidence.
**Proposed fix:** Stream a content digest for regular files into each manifest entry (and include the watched root itself); if hashing the full venv is too costly, use a content-aware project-package manifest plus a platform-appropriate change-time/inode guard for the remaining dependency tree.
**Regression-guard:** Extend the manifest tests with an equal-size regular-file rewrite whose mtime is restored and assert `changed_manifest_paths` reports the file.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

## What was done well

- The implementation threads one immutable `Config.application_paths` layout through HTTP routes, per-notebook retrieval, UI previews, and MCP resources instead of adding mutable global rebinding.
- Slug validation, symlink containment, and the existing `base=` helper seams remain in place on every changed notebook path.
- The installed child environment removes inherited arXMCP, Python, virtualenv, and dynamic-loader influence before first import and redirects known mutable library roots beneath the data root.
- The full smoke invokes the absolute wheel-installed console script from an unrelated CWD, verifies import provenance under site-packages, and polls the real `/healthz` endpoint in bootstrap mode.
- Real notebook, retrieval-cache, and corpus-marker writers are exercised, with stdout/stderr capture located beneath the canonical logs directory.
- The always-on regressions poison legacy module globals and run real writer probes from two distinct working directories.
- The focused relocation suite, the broader path/route/resource suite, Ruff, and the independently rerun canonical `make test` gate all passed (`5014 passed, 47 skipped, 1 xfailed`).
- No dependency, MCP tool schema, prompt-cache hash, roadmap progress record, or external system was mutated by the implementation range.

Severity counts: C1 H3 M1 L0

## Recommended rectification order

C1, H2, H3, M1, H1

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:

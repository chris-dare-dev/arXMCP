# Critique — desktop-distribution-spike-1 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** 10b8641a509b140ab5dcfd3e132e9578a169531a..ddd1d508bf8d01cf099a4ef2750e17bc824fdc3e
**Diff stats:** 5 files, 332 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The disposable bundle establishes host-scoped PyInstaller feasibility, and the production-facing arXMCP invariants are untouched. The recorded artifact size is materially wrong because the evidence pass followed and double-counted symlinks, while the before/after manifest can miss equal-size byte mutations. Correct those two evidence defects before treating the ADR as the durable input to m2.

## Executive summary

- [HIGH] The ADR overstates raw bundle size by about 46% and allocated size by about 45% because 19 symlink targets were counted again as files.
- [MEDIUM] The immutability manifest hashes only path, mode, and size, so an equal-size content rewrite produces the same digest.

## Findings

**H1 — Artifact size double-counts symlink targets** (HIGH)

**Where:** `.claude/notes/spikes/desktop-distribution-spike-1.md:25`
**Anchor:** `| Artifact | 1,107,353,958 raw bytes; 1,`
**What:** The recorded 1,107,353,958 raw bytes and 1,119,813,632 allocated bytes follow 19 symlinks and count their referents twice; `lstat` totals are 759,839,875 logical bytes including link payloads and 772,259,840 allocated bytes.
**Why it matters:** Artifact size is an explicit acceptance datum and a bundling-mode decision input, so a roughly 350 MB overstatement makes the spike's durable evidence incorrect.
**Proposed fix:** Recompute the artifact metrics with `lstat`, report regular files and symlinks separately, count each regular-file payload once, and update the ADR's raw, allocated, file-count, and largest-file values; retain the ZIP value only after independently confirming whether its tool preserves or follows symlinks.
**Regression-guard:** Add a measurement fixture containing one large regular file and one symlink to it, then assert that payload bytes are counted once and the link is reported separately.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M1 — Manifest misses equal-size content mutations** (MEDIUM)

**Where:** `tools/desktop_sidecar_spike.py:64`
**Anchor:** `        row = f"{path.relative_to(root)}`
**What:** The manifest row hashes only relative path, mode, and size, so replacing `one` with same-length `two` or retargeting a symlink to an equal-length target leaves the digest unchanged.
**Why it matters:** The before/after equality underpinning the ADR's immutability claim can pass after a byte-level mutation, weakening the read-only relocation evidence.
**Proposed fix:** Hash regular-file contents and `os.readlink()` values in deterministic path order in addition to `lstat` metadata, streaming large files rather than loading them whole.
**Regression-guard:** Extend `test_tree_manifest_detects_bundle_mutation` with an equal-size overwrite and add a same-length symlink-retarget case; both must change the digest.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

## What was done well

- Cache byte-stability is clean: the diff does not touch `ALL_TOOLS`, prompts, tool-result envelopes, or either pinned schema/prompt hash.
- Math fidelity is clean: no LaTeX, MathML, parser, preamble, chunker, or embedding transform changed.
- Security coverage is preserved: the probe pins loopback, strips ambient Python and dynamic-loader paths, keeps model access offline, and records the BGE-M3 pickle exception as a release blocker rather than hiding it.
- MCP spec compliance is clean: no transport, session, method, schema, pagination, or tool-content shape changed.
- The local-first constraint is respected: mutable probe data and model caches are routed to an explicit external data root, with no S3 or multi-host dependency.
- Tier sequencing is clean: the exact brief declares no dependency, prior E10/E11/E13 infrastructure is shipped, and the spike consumes no pending E14 follow-up.
- The no-fork axis is clean: there is no dependency, submodule, vendored-source, or existing `arxiv-mcp` code change in the range.
- The test surface is otherwise proportionate: all eight focused tests and targeted Ruff pass independently, the macOS `KMP_DUPLICATE_LIB_OK` test guard remains untouched, and no model, credential, or generated binary entered Git.

Severity counts: C0 H1 M1 L0

## Recommended rectification order

H1, M1

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:

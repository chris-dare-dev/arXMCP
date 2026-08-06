# Critique — desktop-distribution-spike-1 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** 10b8641a509b140ab5dcfd3e132e9578a169531a..ddd1d508bf8d01cf099a4ef2750e17bc824fdc3e
**Diff stats:** 5 files, 332 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The relocatable sidecar result remains credible, but its durable evidence overstates artifact size and native-file count, cannot detect equal-size bundle mutations, and omits an embedded build-root path. Correct the evidence and strengthen its regression guards before treating this spike as the measurement baseline for m2.

## Executive summary

- [HIGH] Artifact byte and Mach-O totals follow 19 symlinks and count their targets twice.
- [MEDIUM] The before/after manifest ignores regular-file contents and symlink targets.
- [MEDIUM] Bundled distribution metadata retains an absolute temporary build path omitted by the ADR's host-path account.

## Findings

**H1 — Artifact census double-counts symlink targets** (HIGH)

**Where:** `.claude/notes/spikes/desktop-distribution-spike-1.md:25`
**Anchor:** `| Artifact | 1,107,353,958 raw bytes;`
**What:** The recorded census follows 19 in-tree symlinks, so it counts 347,514,688 target bytes twice and likewise reports 199 Mach-O entries where the bundle contains 180 regular Mach-O files plus 19 links.
**Why it matters:** Exact artifact size and native-file counts are explicit acceptance evidence and bundling-mode inputs, so the reported 1,107,353,958 raw bytes and 1,119,813,632 allocated bytes materially overstate the bundle.
**Proposed fix:** Recompute with `lstat()`, report regular files and symlinks separately, count each regular payload once, and update the ADR with the corrected regular-file totals (759,839,270 raw bytes and 772,259,840 allocated bytes) after independently confirming ZIP semantics.
**Regression-guard:** Add a bundle-statistics fixture with one regular Mach-O-like file and one symlink to it; assert payload bytes and native targets are counted once while the symlink is reported separately.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**M1 — Manifest misses equal-size content mutations** (MEDIUM)

**Where:** `tools/desktop_sidecar_spike.py:64`
**Anchor:** `row = f"{path.relative_to(root)}\0{stat.st_mode:o}`
**What:** `tree_manifest()` hashes only relative names, modes, and sizes, so an equal-size file rewrite or equal-length symlink retarget leaves its digest unchanged.
**Why it matters:** Equality of the before/after digests does not substantiate the ADR's byte-level immutability claim, even though the existing test passes for a size-changing rewrite.
**Proposed fix:** Stream each regular file's bytes into the digest, hash `os.readlink()` for symlinks, include root metadata, and preserve deterministic relative-path ordering without following links outside the bundle.
**Regression-guard:** Extend `test_tree_manifest_detects_bundle_mutation` with `abc` to `xyz` and add an equal-length symlink-retarget case; both must change the digest.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**M2 — Host-path scan omits bundled build metadata** (MEDIUM)

**Where:** `.claude/notes/spikes/desktop-distribution-spike-1.md:30`
**Anchor:** `| Host paths | Runtime guard required`
**What:** The retained `_internal/arxmcp-0.1.0.dist-info/direct_url.json` contains `file:///private/tmp/arxmcp-sidecar-spike1.hAKhhD/wheel-final/arxmcp-0.1.0-py3-none-any.whl`, while the ADR records no build-host path exception and the retained evidence has no scan result.
**Why it matters:** This inert metadata does not defeat runtime relocation, but it makes the host-path evidence incomplete and could disclose a developer-local build path in a later bundle.
**Proposed fix:** Exclude or sanitize `direct_url.json` during collection, scan all regular bundle files for the exact build root rather than only selected binary strings, and amend the ADR to record any intentional inert exception.
**Regression-guard:** Add a post-build scan assertion that no file contains the experiment root or staging-wheel URI, with an explicit reviewed allowlist if metadata must retain one.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

## What was done well

- The disposable bundle, model, logs, archive, and raw build products remained outside Git as required.
- The live probe exercised real FAISS search, LanceDB, Kùzu, PyArrow, Torch, tokenizers, uvloop, httptools, and a local safetensors reload/forward path.
- The launch environment is loopback-only, explicitly offline, and routes mutable data and caches outside the read-only application tree.
- The ADR clearly limits the result to the tested macOS 26.6 arm64 host and does not overclaim macOS 14 support.
- The OpenMP collision, real-model exception, and production signing/notarization work are recorded as release blockers rather than hidden behind a workaround.
- Wheel, lockfile, PyInstaller, and hooks-contrib hashes match the retained inputs.
- The commit adds proportionate focused tests, introduces no runtime dependency, and leaves MCP schemas, prompts, and cache-stability contracts untouched.
- The commit message is conventional and trailered, and the orchestrator's independent verification established a valid GPG signature.

Severity counts: C0 H1 M2 L0

## Recommended rectification order

H1, M1, M2

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:

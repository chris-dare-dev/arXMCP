# Critique — desktop-distribution-m3 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** d6b7d69100d2cf3d8bbe0c85f85e569bf13228fe..e61a449fbc1ea2b49eb5177908288fd33fff6795
**Diff stats:** 26 files, 2702 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The bounded control channel, token handling, fixture process, and shared canonical fixtures are substantial and mostly coherent. Before shipping, the contract needs to stop rejecting a documented class of compatible-minor extensions and its positive fixture set must become host-independent so the advertised Windows workspace can run it. The mandatory 2,702-LOC review-size finding remains HIGH despite the owner-authorized large-diff path, and two smaller parity/test defects should be closed cheaply.

## Executive summary

- [HIGH] The 2,702-LOC, 26-file implementation exceeds the mandatory 400-LOC review threshold.
- [HIGH] Every positive golden uses a POSIX-only `/opt/...` root, so both host-native validators reject the shared fixtures on Windows.
- [HIGH] Both readers reject nested compatible-extension keys that the README restricts only at the top-level namespace.
- [MEDIUM] Python accepts executable versions containing spaces while Rust rejects the identical frame.
- [MEDIUM] The invalid-launch process test scans stderr for a token different from the one it actually sends.
- [CLEAN] No external write, roadmap-progress edit, floating dependency, secret-bearing argv/environment, or unsigned commit was found.

## Findings

**H1 — Cumulative diff exceeds the review limit** (HIGH)

**Where:** no specific file
**Anchor:** `26 files changed, 2702 insertions(+)`
**What:** The implementation range adds 2,702 LOC across 26 files—more than six times the mandatory greater-than-400-LOC threshold and materially above the research estimate of 1,100–1,700 LOC in 12–18 files, even though the owner authorized the pipeline's large-diff path.
**Why it matters:** This is the rubric's defect-detection cliff: two validators, a control protocol, an HTTP fixture process, golden bytes, packaging wiring, and 536 test lines are too much independent behavior for one review unit.
**Proposed fix:** Before release, partition review and verification into independently owned slices for the Rust codec, Python mirror, and sidecar/process boundary; rerun each slice's focused gates and record its disposition separately. Future work of this size should be split into separately dispatched milestones or reviewable commits below the threshold.
**Regression-guard:** Make Phase 2 report cumulative insertion-plus-deletion LOC and file count before commit, and require an explicit split/review matrix whenever either exceeds the canonical threshold, even when `allow_large_diff` permits continuation.
**Source critic:** milestone-adversary-critic
**Source axis:** Diff size

**H2 — Positive fixtures are not Windows-portable** (HIGH)

**Where:** `apps/desktop/contract-fixtures/launch-v1.jsonl:1`
**Anchor:** `{"contract":{"major":1,"minor":0},"data_`
**What:** All positive fixtures encode `/opt/arXMCP fixture/数学` as the data root, but Rust `Path::is_absolute` and Python `WindowsPath.is_absolute` reject that drive-less path on Windows, so both positive round-trip suites fail before testing canonical bytes.
**Why it matters:** The milestone establishes a cross-platform workspace and names Windows x86-64 as a portability target, yet its shared contract fixtures—the acceptance evidence—cannot run there.
**Proposed fix:** Make contract-level path validation lexical and host-independent, keeping wire paths as strings until the platform adapter validates/materializes a native path; mirror that rule in `server/desktop_contract.py`. Alternatively add explicit path-style fixtures and have both languages consume the same host-selected canonical set without changing bytes at runtime.
**Regression-guard:** Run the positive Rust and Python fixture suites on Windows and add unit cases proving the contract parser handles both a POSIX absolute fixture path and a drive-qualified Windows path deterministically in both languages.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**H3 — Nested extension fields violate minor compatibility** (HIGH)

**Where:** `apps/desktop/crates/desktop-contract/src/lib.rs:489`
**Anchor:** `if !valid_extension_key(key, false) {`
**What:** Rust rejects every nested extension-object key outside its lowercase ASCII grammar, and Python repeats the restriction at `server/desktop_contract.py:445`, although the README documents the ASCII/namespaced rule only for top-level extension keys; a same-major frame containing `{"org.arxmcp.future":{"camelCase":1}}` is rejected by both readers.
**Why it matters:** An otherwise documented compatible minor addition can break launch, directly violating the milestone's version-tolerance acceptance criterion and turning the extension escape hatch into a hidden schema lock.
**Proposed fix:** Enforce the namespace grammar only on keys directly beneath `extensions`; let nested extension payloads contain arbitrary JSON string keys subject to the existing UTF-8, depth, safe-number, and frame-size limits. Apply the same change in `server/desktop_contract.py`.
**Regression-guard:** Commit one compatible-minor fixture with a nested mixed-case key and require Rust and Python to parse and re-emit it byte for byte while continuing to reject an unnamespaced top-level extension key.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**M1 — Executable-version validation diverges by language** (MEDIUM)

**Where:** `server/desktop_contract.py:368`
**Anchor:** `and all(character.isascii() and character.isprintable() for character in version)`
**What:** Python's `isascii() and isprintable()` predicate accepts an embedded ASCII space, so it parses version `"v 1.0"`, while Rust's `is_ascii_graphic()` rejects the identical frame.
**Why it matters:** The two claimed mirror implementations do not define one wire language, creating a latent one-side-accepts/other-side-rejects failure that the shared fixtures do not expose.
**Proposed fix:** Define one explicit executable-version grammar and implement it byte-for-byte in both readers—for the current Rust behavior, require every byte to be ASCII `0x21..=0x7e` excluding `/` and `\\` in Python too.
**Regression-guard:** Add one shared fixture for the boundary value (positive or negative according to the documented grammar) and assert the same result in both language suites.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**M2 — Invalid-token stderr guard checks the wrong canary** (MEDIUM)

**Where:** `tests/test_desktop_contract.py:391`
**Anchor:** `assert token.expose().encode() not in completed.stderr`
**What:** The test sends `invalid_token` (the valid token with its first character changed) but asserts only that the original `token` is absent, so an implementation that logs the exact 64-character input—or 63 of the secret's 64 characters—still passes.
**Why it matters:** The regression guard does not protect the stated no-token-in-errors/logs invariant on the malformed launch path it is meant to exercise.
**Proposed fix:** Assert that `invalid_token.encode()` is absent from both captured streams and the persisted log, while retaining the valid-token canary test for typed validation failures.
**Regression-guard:** Temporarily inject the received invalid token into the sidecar error string and require this test to fail; then remove the injection and keep the exact-input assertion.
**Source critic:** milestone-adversary-critic
**Source axis:** Test discipline

## What was done well

- The protocol separates secret-bearing `launch`/`shutdown` frames from a token-free `bound` frame and reserves stdout exclusively for control bytes.
- Live capabilities come from 32 OS-random bytes, use redacted object representations, and are compared in constant time for readiness and shutdown.
- The fixture accepts no command-line configuration, receives a cleared environment, validates launch before binding, and retains an exact `127.0.0.1:0` listener.
- Both readers reject duplicate keys, floats, unsafe integers, malformed framing, wildcard endpoints, URL-authority mismatches, and unsupported majors before typed lifecycle work.
- Positive fixtures round-trip byte for byte in Rust and Python, and both suites independently pin the aggregate fixture digest.
- The live sidecar tests exercise unauthenticated health, authenticated readiness, invalid and valid shutdown, stdin EOF, token-free output, and artifact scans without importing a model or corpus.
- Direct Rust dependencies are exactly pinned, the lockfile is committed, and the production Python module is added to the installed-wheel contents guard.
- Rust format, locked offline tests, strict Clippy, and the unsandboxed 22-test lifecycle gate passed independently; the full sandboxed repository run's only failures were the known loopback-bind denials.
- Both implementation commits contain `gpgsig` objects, carry the required co-author trailer, and were independently reported as good signatures outside the managed sandbox.
- The range leaves MCP tool schemas, prompt-cache pins, roadmap progress, production CLI wiring, and external systems untouched.

Severity counts: C0 H3 M2 L0

## Recommended rectification order

H3, H2, M1, M2, H1

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:

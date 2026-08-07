# Critique (merged) — desktop-distribution-m3

**Critics:** milestone-adversary-critic, milestone-arxmcp-critic
**Commit range:** d6b7d69100d2cf3d8bbe0c85f85e569bf13228fe..e61a449fbc1ea2b49eb5177908288fd33fff6795
**Diff stats:** 26 files, 2702 LOC
**Critique format version:** 1.0

> **Merge note.** Each critic authored its ids from 1 within its own file, so
> they collided across files. `findings.py merge` renumbered them into one
> gapless per-severity sequence in critic dispatch order; bodies are verbatim.
> **Phase 4 dispositions attach to the MERGED ids below**, not to the ids in
> the per-critic files. Re-running merge after a critic file changes will shift
> these ids - see milestone-pipeline-critique-format.md.
>
> - `milestone-adversary-critic` (adversary.md): ids unchanged
> - `milestone-arxmcp-critic` (arxmcp.md): H1->H4, H2->H5, M1->M3, M2->M4

## Verdict

**SHIP-WITH-FIXES** — the most severe of the per-critic verdicts below.

### milestone-adversary-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES

The bounded control channel, token handling, fixture process, and shared canonical fixtures are substantial and mostly coherent. Before shipping, the contract needs to stop rejecting a documented class of compatible-minor extensions and its positive fixture set must become host-independent so the advertised Windows workspace can run it. The mandatory 2,702-LOC review-size finding remains HIGH despite the owner-authorized large-diff path, and two smaller parity/test defects should be closed cheaply.

### milestone-arxmcp-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES

The contract has strong framing, loopback, and deterministic-fixture foundations, but two reachable security/identity paths violate the milestone's explicit boundary: malformed secret-bearing frames retain the capability in their exception graph, and the fixture sidecar never verifies the executable digest it claims. The cross-language path validators also disagree on filesystem-canonical paths, while the repository's canonical Python gate skips the live sidecar tests unless a binary was built separately. Fix the two HIGH findings before treating the contract as the M4 trust boundary.

## Executive summary — milestone-adversary-critic

- [HIGH] The 2,702-LOC, 26-file implementation exceeds the mandatory 400-LOC review threshold.
- [HIGH] Every positive golden uses a POSIX-only `/opt/...` root, so both host-native validators reject the shared fixtures on Windows.
- [HIGH] Both readers reject nested compatible-extension keys that the README restricts only at the top-level namespace.
- [MEDIUM] Python accepts executable versions containing spaces while Rust rejects the identical frame.
- [MEDIUM] The invalid-launch process test scans stderr for a token different from the one it actually sends.
- [CLEAN] No external write, roadmap-progress edit, floating dependency, secret-bearing argv/environment, or unsigned commit was found.

## Executive summary — milestone-arxmcp-critic

- [HIGH] Python chains raw decoder exceptions that retain the complete secret-bearing frame.
- [HIGH] The sidecar echoes the requested SHA-256 without hashing or verifying its executable.
- [MEDIUM] Rust performs lexical path checks while Python resolves the host filesystem, so identical bytes can receive opposite verdicts.
- [MEDIUM] `make test` skips every live sidecar lifecycle test when no separately built binary is present.

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

**H4 — Decoder causes retain the startup token** (HIGH)

**Where:** `server/desktop_contract.py:206`
**Anchor:** `raise DesktopContractError("control frame`
**What:** Malformed JSON is re-raised with `from exc`, leaving a `JSONDecodeError.doc` containing the entire decoded launch frame—including `startup_token`—reachable through `DesktopContractError.__cause__`; the Unicode branch similarly retains raw bytes in `UnicodeDecodeError.object`.
**Why it matters:** A structured exception recorder or diagnostic that walks exception attributes can persist the startup capability, violating the milestone's no-token-in-errors-or-logs security invariant even though the outer exception's string and repr are redacted.
**Proposed fix:** Convert decoder failures to a sanitized error only after leaving the `except` block so neither `__cause__` nor `__context__` retains the decoder exception or payload; apply the same pattern to UTF-8 failures and keep all operator-visible messages static.
**Regression-guard:** Add malformed UTF-8 and malformed-JSON launch frames containing a live canary, then recursively inspect `__cause__`, `__context__`, `args`, `doc`, and `object` on every raised exception and assert the canary bytes/text are absent.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage

**H5 — Sidecar reflects rather than verifies executable SHA** (HIGH)

**Where:** `apps/desktop/crates/fixture-sidecar/src/main.rs:122`
**Anchor:** `sha256: launch.executable.sha256.clone(),`
**What:** The child validates only component and version, then copies the supervisor-supplied digest into `bound`, so any same-version binary accepts and claims any well-formed SHA-256 value.
**Why it matters:** The executable-identity field supplies no integrity evidence and a supervisor comparison against `bound` will always succeed, defeating the contract's stable executable identity invariant and its pre-signing tamper check.
**Proposed fix:** Hash `std::env::current_exe()` inside the sidecar before binding, compare that digest with the launch expectation using a fixed-time comparison, reject mismatches before side effects, and emit the independently computed digest in `bound`.
**Regression-guard:** Spawn the real fixture with one changed hex digit in `launch.executable.sha256` and assert exit 2, empty stdout, no listener announcement, and a token-free static identity error; retain a matching-digest success case.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage

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

**M3 — Path validation is not cross-language deterministic** (MEDIUM)

**Where:** `apps/desktop/crates/desktop-contract/src/lib.rs:434`
**Anchor:** `if !path.is_absolute()`
**What:** Rust calls a lexical `is_absolute`/component check while Python calls `Path.resolve(strict=False)`, so the same frame using an absolute symlink spelling such as macOS `/var` is accepted by Rust but rejected by Python as non-canonical.
**Why it matters:** Contract acceptance depends on which language and host filesystem parses the bytes, undermining the promised shared deterministic contract and creating a launch that passes the supervisor-side validator but fails in the child before binding.
**Proposed fix:** Define one language-independent lexical wire rule and move filesystem canonicalization to an explicit runtime validation step against the already resolved `ApplicationPaths.root`, or add equivalent context-aware canonicalization APIs in both languages; pin symlink and platform-path parity cases in both suites.
**Regression-guard:** Optional; add a shared path-parity matrix covering a symlink spelling, `..`, Unicode/spaces, and Windows-native absolute syntax, and require Rust and Python to return the same accept/reject result for every case.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first + Docker constraint

**M4 — Canonical gate skips the live sidecar tests** (MEDIUM)

**Where:** `tests/test_desktop_contract.py:280`
**Anchor:** `pytest.skip("build fixture-sidecar or set ARX`
**What:** All four process-level sidecar tests skip when `ARXMCP_FIXTURE_SIDECAR` is unset and `apps/desktop/target/debug/fixture-sidecar` is absent, which is the normal state after the documented out-of-tree Cargo build and during `make test`.
**Why it matters:** The repository's authoritative gate can pass while executable identity, loopback ownership, readiness authentication, token absence, and shutdown/EOF behavior are wholly unexecuted.
**Proposed fix:** Add a deterministic desktop conformance target that performs the locked sidecar build and runs the focused Python suite with the resulting absolute path, then make the milestone gate invoke it; if Rust is intentionally optional for the global Python suite, make the dedicated release gate fail rather than skip and document it as mandatory.
**Regression-guard:** Add a gate test or Make dry-run assertion proving the desktop target builds `fixture-sidecar` before pytest and exports `ARXMCP_FIXTURE_SIDECAR`; the focused run must report zero skips.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

## What was done well

### From milestone-adversary-critic

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

### From milestone-arxmcp-critic

- Cache byte-stability is preserved: `server/tools.py`, `server/prompts.py`, MCP result envelopes, and both pinned hashes are untouched; fixture ordering and aggregate hashing are explicit and deterministic.
- Math fidelity is axis-verified clean: no LaTeX, MathML, raw-paper, chunking, macro, or theorem/proof path changed.
- The security baseline is otherwise strong: the fixture binds literal `127.0.0.1:0`, retains the selected listener, uses a 256-bit OS-random capability, rejects CLI configuration, clears nonessential environment variables, and keeps the token out of `bound` and normal diagnostics.
- MCP 2025-06-18 compliance is axis-verified clean: the MCP tool surface and Streamable HTTP implementation are unchanged, and the fixture derives `/mcp` from the single validated loopback authority rather than changing MCP framing.
- The local-first constraint is preserved: the fixture has no model, corpus, cloud, object-store, or multi-host service dependency, and mutable locations remain rooted in the supplied application data root.
- Tier sequencing is clean: `desktop-distribution-m1` and `desktop-distribution-spike-3` are complete, while research explicitly resolves `desktop-distribution-e2` as the parent outcome rather than an unshipped prerequisite.
- The no-fork axis is clean: there is no submodule, fork URL, lifted `arxiv-mcp` source, runtime Anthropic dependency, or dependency-pin drift.
- The shared positive and negative fixtures cover major-version rejection, extension-only minor evolution, duplicate/core-field rejection, exact loopback URLs, frame bounds, Unicode, and byte-for-byte re-emission in both language suites.

Severity counts: C0 H5 M4 L0

## Recommended rectification order

H3, H2, H1, H4, H5, M1, M2, M3, M4

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:

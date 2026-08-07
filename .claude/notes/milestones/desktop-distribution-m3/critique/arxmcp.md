# Critique — desktop-distribution-m3 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** d6b7d69100d2cf3d8bbe0c85f85e569bf13228fe..e61a449fbc1ea2b49eb5177908288fd33fff6795
**Diff stats:** 26 files, 2702 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The contract has strong framing, loopback, and deterministic-fixture foundations, but two reachable security/identity paths violate the milestone's explicit boundary: malformed secret-bearing frames retain the capability in their exception graph, and the fixture sidecar never verifies the executable digest it claims. The cross-language path validators also disagree on filesystem-canonical paths, while the repository's canonical Python gate skips the live sidecar tests unless a binary was built separately. Fix the two HIGH findings before treating the contract as the M4 trust boundary.

## Executive summary

- [HIGH] Python chains raw decoder exceptions that retain the complete secret-bearing frame.
- [HIGH] The sidecar echoes the requested SHA-256 without hashing or verifying its executable.
- [MEDIUM] Rust performs lexical path checks while Python resolves the host filesystem, so identical bytes can receive opposite verdicts.
- [MEDIUM] `make test` skips every live sidecar lifecycle test when no separately built binary is present.

## Findings

**H1 — Decoder causes retain the startup token** (HIGH)

**Where:** `server/desktop_contract.py:206`
**Anchor:** `raise DesktopContractError("control frame`
**What:** Malformed JSON is re-raised with `from exc`, leaving a `JSONDecodeError.doc` containing the entire decoded launch frame—including `startup_token`—reachable through `DesktopContractError.__cause__`; the Unicode branch similarly retains raw bytes in `UnicodeDecodeError.object`.
**Why it matters:** A structured exception recorder or diagnostic that walks exception attributes can persist the startup capability, violating the milestone's no-token-in-errors-or-logs security invariant even though the outer exception's string and repr are redacted.
**Proposed fix:** Convert decoder failures to a sanitized error only after leaving the `except` block so neither `__cause__` nor `__context__` retains the decoder exception or payload; apply the same pattern to UTF-8 failures and keep all operator-visible messages static.
**Regression-guard:** Add malformed UTF-8 and malformed-JSON launch frames containing a live canary, then recursively inspect `__cause__`, `__context__`, `args`, `doc`, and `object` on every raised exception and assert the canary bytes/text are absent.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage

**H2 — Sidecar reflects rather than verifies executable SHA** (HIGH)

**Where:** `apps/desktop/crates/fixture-sidecar/src/main.rs:122`
**Anchor:** `sha256: launch.executable.sha256.clone(),`
**What:** The child validates only component and version, then copies the supervisor-supplied digest into `bound`, so any same-version binary accepts and claims any well-formed SHA-256 value.
**Why it matters:** The executable-identity field supplies no integrity evidence and a supervisor comparison against `bound` will always succeed, defeating the contract's stable executable identity invariant and its pre-signing tamper check.
**Proposed fix:** Hash `std::env::current_exe()` inside the sidecar before binding, compare that digest with the launch expectation using a fixed-time comparison, reject mismatches before side effects, and emit the independently computed digest in `bound`.
**Regression-guard:** Spawn the real fixture with one changed hex digit in `launch.executable.sha256` and assert exit 2, empty stdout, no listener announcement, and a token-free static identity error; retain a matching-digest success case.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage

**M1 — Path validation is not cross-language deterministic** (MEDIUM)

**Where:** `apps/desktop/crates/desktop-contract/src/lib.rs:434`
**Anchor:** `if !path.is_absolute()`
**What:** Rust calls a lexical `is_absolute`/component check while Python calls `Path.resolve(strict=False)`, so the same frame using an absolute symlink spelling such as macOS `/var` is accepted by Rust but rejected by Python as non-canonical.
**Why it matters:** Contract acceptance depends on which language and host filesystem parses the bytes, undermining the promised shared deterministic contract and creating a launch that passes the supervisor-side validator but fails in the child before binding.
**Proposed fix:** Define one language-independent lexical wire rule and move filesystem canonicalization to an explicit runtime validation step against the already resolved `ApplicationPaths.root`, or add equivalent context-aware canonicalization APIs in both languages; pin symlink and platform-path parity cases in both suites.
**Regression-guard:** Optional; add a shared path-parity matrix covering a symlink spelling, `..`, Unicode/spaces, and Windows-native absolute syntax, and require Rust and Python to return the same accept/reject result for every case.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first + Docker constraint

**M2 — Canonical gate skips the live sidecar tests** (MEDIUM)

**Where:** `tests/test_desktop_contract.py:280`
**Anchor:** `pytest.skip("build fixture-sidecar or set ARX`
**What:** All four process-level sidecar tests skip when `ARXMCP_FIXTURE_SIDECAR` is unset and `apps/desktop/target/debug/fixture-sidecar` is absent, which is the normal state after the documented out-of-tree Cargo build and during `make test`.
**Why it matters:** The repository's authoritative gate can pass while executable identity, loopback ownership, readiness authentication, token absence, and shutdown/EOF behavior are wholly unexecuted.
**Proposed fix:** Add a deterministic desktop conformance target that performs the locked sidecar build and runs the focused Python suite with the resulting absolute path, then make the milestone gate invoke it; if Rust is intentionally optional for the global Python suite, make the dedicated release gate fail rather than skip and document it as mandatory.
**Regression-guard:** Add a gate test or Make dry-run assertion proving the desktop target builds `fixture-sidecar` before pytest and exports `ARXMCP_FIXTURE_SIDECAR`; the focused run must report zero skips.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

## What was done well

- Cache byte-stability is preserved: `server/tools.py`, `server/prompts.py`, MCP result envelopes, and both pinned hashes are untouched; fixture ordering and aggregate hashing are explicit and deterministic.
- Math fidelity is axis-verified clean: no LaTeX, MathML, raw-paper, chunking, macro, or theorem/proof path changed.
- The security baseline is otherwise strong: the fixture binds literal `127.0.0.1:0`, retains the selected listener, uses a 256-bit OS-random capability, rejects CLI configuration, clears nonessential environment variables, and keeps the token out of `bound` and normal diagnostics.
- MCP 2025-06-18 compliance is axis-verified clean: the MCP tool surface and Streamable HTTP implementation are unchanged, and the fixture derives `/mcp` from the single validated loopback authority rather than changing MCP framing.
- The local-first constraint is preserved: the fixture has no model, corpus, cloud, object-store, or multi-host service dependency, and mutable locations remain rooted in the supplied application data root.
- Tier sequencing is clean: `desktop-distribution-m1` and `desktop-distribution-spike-3` are complete, while research explicitly resolves `desktop-distribution-e2` as the parent outcome rather than an unshipped prerequisite.
- The no-fork axis is clean: there is no submodule, fork URL, lifted `arxiv-mcp` source, runtime Anthropic dependency, or dependency-pin drift.
- The shared positive and negative fixtures cover major-version rejection, extension-only minor evolution, duplicate/core-field rejection, exact loopback URLs, frame bounds, Unicode, and byte-for-byte re-emission in both language suites.

Severity counts: C0 H2 M2 L0

## Recommended rectification order

H1, H2, M1, M2

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: <finding ids>
- Deferred: <finding ids>
- Invalidated: <finding ids with reasons>
- Regression tests added: <file paths>

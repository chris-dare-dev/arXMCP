# Spike — verification-feedback-spike-2

**Question (from `plans/verification-feedback-roadmap.md`):** Confirm a local
Lean 4 REPL (`lake exe repl`) can be installed on the target workstation and
driven as a non-blocking `asyncio` subprocess; decide raw
`leanprover-community/repl` JSON protocol vs the LeanDojo Python API as the
backend for the `verification-feedback-m1` → m2 `lean_verify` tool.

**Validates `[MUST]` assumption:** "A local Lean 4 toolchain can be installed
and driven as a non-blocking `asyncio` subprocess."

**Date:** 2026-05-22 · **Budget:** ≤ 3 days (discovery item) · **Effort spent:** ~1 session.

---

## Verdict: **YES — feasible. Proceed with m2.** Backend recommendation: **raw `leanprover-community/repl` JSON.**

---

## What was done

1. **Installed the Lean toolchain.** `elan` (the Lean version manager) installed
   on this Windows workstation from the official release zip
   (`elan-x86_64-pc-windows-msvc.zip`); `elan-init -y --default-toolchain stable`
   pulled Lean **4.29.1** + Lake **5.0.0** into `~/.elan/`.
2. **Built the REPL.** Cloned `leanprover-community/repl` (depth-1) and
   `lake build` — 24 jobs, **completed successfully in well under a minute**.
   The repl's `lean-toolchain` pins `leanprover/lean4:v4.30.0-rc2`; `elan`
   auto-fetched that toolchain transparently during the build. **No mathlib
   build was required** — the REPL package depends only on Lean core.
3. **Validated the subprocess interface.** A throwaway POC
   (`~/lean-repl-spike/validate_repl.py`) spawned `lake exe repl` via
   `asyncio.create_subprocess_exec`, drove it over stdin/stdout JSON, and
   exercised the three response shapes m2's `lean_verify` needs.

## Results — all three `lean_verify` response shapes confirmed

| Case | Input | Response | Round-trip |
|---|---|---|---|
| **ok** | `theorem t : 1 + 1 = 2 := rfl` | `{"env": 0}` — 0 error messages | 0.61 s |
| **compile-error** | `theorem t : 1 + 1 = 3 := rfl` | `{"messages": [...], "env": 0}` — 2 messages, first `severity="error"` **with a `pos` source position** and structured `data` ("Type mismatch …") | 0.42 s |
| **sorry-goal** | `theorem t (n : Nat) : n = n := by sorry` | `{"env", "messages", "sorries"}` — `sorries[0].goal = "n : Nat\n⊢ n = n"` (hypotheses + turnstile + goal) | 0.39 s |

Subprocess **spawn cost ≈ instant**; per-command elaboration **sub-second** for
simple snippets. The non-blocking `asyncio` round-trip works end-to-end.

## Backend decision: raw REPL JSON, not LeanDojo

| | raw `leanprover-community/repl` | LeanDojo |
|---|---|---|
| Dependency weight | one small Lean package; `lake build` ~30 s; **no mathlib** | heavy Python pkg + Lean + lake + (typically) a mathlib build |
| Interface | stdin/stdout JSON: `{"cmd": "..."}` → `{"env","messages","sorries"}` | Python API wrapping the same REPL |
| Protocol surface | exactly the three shapes m2 needs — validated above | larger, ML-extraction-oriented |
| no-fork / local-first fit | clean — wrap the protocol natively, no import | a runtime Python dependency |

**Recommendation:** m2 wraps the raw REPL JSON protocol natively. It is the
lighter, more local-first-aligned choice and the protocol is exactly what
`lean_verify` needs. (This matches the capability-scout's research-frontier
brief §2.1 and the m2 synthesis open question.)

## Findings the m2 implementation MUST honour

1. **Resolve the toolchain exe path explicitly.** On Windows,
   `asyncio.create_subprocess_exec` does **not** PATH-search a bare name
   (`"lake"` → `FileNotFoundError [WinError 2]`). m2 must spawn the REPL with
   the **absolute path** to `lake.exe` (or the built `repl` exe). A new
   `Config` field (e.g. `ARXMCP_LAKE_PATH` / `ARXMCP_LEAN_REPL_*`) should hold
   it, default-resolved from `~/.elan/bin` / `PATH` at startup.
2. **Run mode.** `lake exe repl` with **`cwd` = the repl package directory** —
   `lake` sets `LEAN_PATH` for the package. m2 needs the repl package built
   and its directory known to the server.
3. **Protocol.** Commands: a JSON object then a blank line. Responses: a JSON
   object terminated by a blank line. Reader must accumulate stdout lines
   until a blank line, then `json.loads`.
4. **Unicode.** Proof states contain non-ASCII (the turnstile `⊢` U+22A2, Greek
   identifiers, etc.). Fine over the UTF-8 MCP transport; any Windows-console
   tooling around it must force UTF-8 stdout.
5. **Lean is a system dependency, not a pip dep.** `pyproject.toml` cannot
   declare it. m2's `ARXMCP_ENABLE_LEAN` flag must default OFF; a
   `requires_lean_repl` pytest marker skips Lean-dependent tests when the
   toolchain/repl is absent (CI / fresh checkout / non-Lean machines).
6. **Toolchain-version coupling.** The repl pins its own `lean-toolchain`
   (`v4.30.0-rc2`); a paper-corpus / autoformalizer targeting a different Lean
   version is a separate concern — `lean_verify` reports what the pinned repl
   toolchain says.

## Environment note

This validation ran on the **Windows** secondary checkout. arXMCP's primary
environment is macOS (`chris.dare`); the install + build + subprocess approach
is even more straightforward there. The Windows-specific finding (#1, absolute
exe path) is the one portability item m2 must carry.

## Spike artifacts (throwaway POC — not committed to the repo)

- `~/.elan/` — installed Lean toolchain (elan 4.29.1 + repl's v4.30.0-rc2).
- `~/lean-repl-spike/repl/` — cloned + built `leanprover-community/repl`.
- `~/lean-repl-spike/validate_repl.py` — the validation POC.

These are sandboxed outside the arXMCP repo per the spike discipline (POC code
is throwaway; the durable artifact is this findings note).

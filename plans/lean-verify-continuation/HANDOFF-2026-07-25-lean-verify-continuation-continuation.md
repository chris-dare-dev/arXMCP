---
project: lean-verify-continuation
type: handoff
status: complete
authorship: agent-generated
handoff_kind: continuation
date: 2026-07-25
companion: HANDOFF-2026-07-25-lean-verify-continuation-session-review.md
roadmap: plans/verification-feedback-roadmap.md
resume_target: opus
tags:
- project/lean-verify-continuation
- type/handoff
- authorship/agent-generated
- handoff/continuation
- project/arxmcp
aliases:
- lean-verify-continuation — continuation handoff (2026-07-25)
---

# CONTINUATION HANDOFF — lean-verify-continuation (2026-07-25)

> **Audience:** a fresh opus session picking up the Lean verification surface. The companion
> review handoff ([[HANDOFF-2026-07-25-lean-verify-continuation-session-review]]) covers *what
> shipped and why* — THIS doc says **exactly where to resume and what's left**. Lineage roadmap:
> `plans/verification-feedback-roadmap.md` (this milestone is the de-facto m5); strategic home is
> the R3 brief `.claude/roadmap-briefs/R3-verification-contract.md`.
>
> **Program goal:** turn `lean_verify` from a one-shot snippet checker into a real
> autoformalizer/tactician substrate — reuse a warm environment, step proofs incrementally, and
> never lie about a verification outcome.

## 1. Current state (as of this handoff)

| Milestone | Status |
|---|---|
| lean-verify-continuation-m1 — env + proofState continuation through `lean_verify` | ✅ SHIPPED + PUSHED (`755dc5e`, `37a1e02`; origin/main = `37a1e02`) |
| Mathlib built into the REPL package (`C:\Users\cedar\lean-repl-spike\repl`) | ✅ LIVE (outside the arXMCP repo; env prerequisite) |
| Startup Mathlib **preload** / operator warm-env handle | ⬜ ← RESUME HERE (natural next increment; not started) |
| R3 verification-contract proper (5-op split, `audit_axioms`, OS isolation, strict replay) | ⬜ NOT STARTED (the strategic P0 this milestone is a foundation for) |

Load-bearing live facts right now:
- `lean_verify` (the 8th MCP tool) now takes opaque `env` / `proof_state` continuation tokens and a
  `mode="tactic_step"`; tokens are per-REPL-spawn generation-guarded and fail closed on
  stale/unknown/malformed. **Off by default** — the tool answers `lean_status:"disabled"` unless
  `ARXMCP_ENABLE_LEAN=true` + both path vars are set at server start (see §6).
- **A latent FAIL-OPEN was fixed**: the REPL's `{"message":"Unknown environment."}` reply used to
  normalize to `status:"ok"`. Now three-shape dispatch fails it closed.
- **⚠ Local `main` is 1 commit AHEAD of origin with someone else's work:** `5335c58`
  `feat(server): compact search content[0] + truthful cap comment` (Chris Dare, 2026-07-25) is
  committed locally but **NOT pushed** and is **not from this session**. Do not blind-`git push` —
  see §5.1.

## 2. RESUME HERE — startup Mathlib preload + a first-class warm-env handle

**Goal:** make the "import Mathlib once, then reuse" pattern work without a manual pre-warm.

Facts already decided/measured this session:
- Env reuse works end-to-end (demonstrated live): a `def` / `import` in one call is reusable via
  the returned `env` token in later calls at **~0.00–0.02 s** vs the cold import.
- The blocker: `lean_verify`'s **per-call** timeout is `DEFAULT_QUERY_TIMEOUT_S = 30 s`
  (`server/lean_repl.py`), and a cold `import Mathlib` measured **14.5 s – 235 s** (high variance,
  235 s this session under load). So an agent call that does `import Mathlib` **times out**, gets
  killed+respawned, and the next call pays cold cost again — a persistent loop.
- The working pattern (shown in the demo, `scratchpad/demo_v2.py`): an **operator/startup step**
  pays the import once with a generous budget (a direct `LeanRepl.query({"cmd":"import Mathlib"},
  timeout=300)`), then agents reuse the resulting env token — inside the 30 s cap.

What to build (proposed m2 — run it through `/milestone-pipeline`, this is >3 files + tests):
1. A startup preload: when `ARXMCP_ENABLE_LEAN=true` and a configured named env (e.g.
   `ARXMCP_LEAN_PRELOAD="Mathlib"`), `Resources.startup` (`server/resources.py:1016-1027`) warms
   the REPL with a long timeout and stashes the resulting **env token** on `Resources`.
2. Surface it to agents: either a new tool result field or a tiny resource
   (`arxmcp://lean-env`) that hands out the current warm Mathlib env token, so a tactician passes
   `env=<that token>` instead of `imports=["Mathlib"]`.
3. Respawn coherence: on a timeout-respawn the generation changes and the preloaded token expires —
   the preload must re-run and the resource must return the NEW token. This is the seam that ties
   into R3's warm-pool (m7) work; keep it simple here (single warm env), leave pooling to R3.

**GATE:** this changes the served tool/resource surface. If you add an input field or a resource,
re-pin `EXPECTED_TOOL_SCHEMA_SHA256` (and `EXPECTED_BP1_SHA256` if a description changes) — see the
cascade note in §5.2. A new *resource* (not a tool) may not touch the tools/list hash; verify.

Alternative resume path: skip m2 and start **R3 verification-contract proper** — the trust-gate
(parse/elaborate-signature/check-declaration/`audit_axioms`/strict-replay split, OS isolation on
Windows via Job Object, adversarial attack suite). That is the strategic P0; m1 deliberately built
the continuation-token + fail-closed foundation it sits on. Recommend m2 first (small, high-value,
unblocks real Mathlib use); R3 is a multi-milestone program.

## 3. Definition of done for the in-flight milestone

lean-verify-continuation-m1 is **already DONE** (all four pipeline phases ran; critique + rectify
complete; `make test` green; pushed). Its closure checklist for reference:
- ✅ Research (live REPL protocol probe + blast-radius map), Implement, Critique (independent
  adversary, 6 axes), Rectify (F1–F5 fixed, F7 deferred).
- ✅ `make test` (clean-env config) green: ruff clean, 0 pytest failures; real-REPL integration
  (`ARXMCP_ENABLE_LEAN=true`) green including the fail-open + F1/F2 regression guards.
- ✅ State machine at `.claude/notes/milestones/lean-verify-continuation-m1/state.json` =
  `complete`; research-synthesis + implementation-summary + critique-adversary notes written.
- ✅ Pushed (per-event authorization given this session).
- ⚠ NOT done the fleet-standard way: it landed as **2 commits** (feat folds in the rectification),
  not the repo's 3-commit `feat`/`rect`/`chore` triple — because the critique ran on the working
  tree, so there was no pre-rectify commit to anchor a `rect` commit against. Rationale recorded in
  the state.json `rectification_note`. A resumer following §4.3 strictly should know this was a
  deliberate, documented deviation, not an oversight.

## 4. Remaining epics / milestones

- **m2 — Mathlib preload / warm-env handle** (proposed, §2). Gate to advance: the reuse pattern is
  reachable by an agent without a manual pre-warm, and the preloaded token survives (or correctly
  re-mints across) a respawn. Carry-forward gotcha: the 30 s per-call cap is the hard constraint;
  do not "fix" it by raising the timeout globally (a runaway elaboration must still be killed).
- **R3 verification-contract** (strategic, `.claude/roadmap-briefs/R3-verification-contract.md`).
  The five-operation honest surface + OS isolation + `audit_axioms` (transitive closure vs
  propext/Quot.sound/Classical.choice) + strict independent replay + named immutable environments +
  content-addressed result caching + warm pooled workers (**m7** owns the F7 env-lifecycle fix,
  per this session's deferral). Gate: no trust-bearing artifact ships over an unsound verifier;
  R4/R5 depend on R3's gates.

## 5. Cross-cutting follow-ups (landmines you'll trip on)

1. **Concurrent-session unpushed commit on `main`.** `5335c58` (search handler, not this
   session's) sits unpushed on local `main`. Before any `git push`, confirm with the owner whether
   `5335c58` should go up — a blind push publishes it. `git ls-remote origin refs/heads/main` =
   `37a1e02` (this session's tip). Concurrent sessions edited `main` throughout 2026-07-24/25;
   always re-verify HEAD + origin before committing/pushing.
2. **Two background chips dispatched this session, run in SEPARATE sessions:**
   (a) *Fix stale stub list in CLAUDE.md §7* — status unknown from here (may or may not have
   landed); (b) *Add live-env cap to Lean REPL (F7)* — **resolved** as a documentation/coordination
   handoff to R3 m7 (it edited `.claude/roadmap-briefs/R3-verification-contract.md` and
   `.claude/docs/lean-sandbox-design.md`; no `server/` code). Don't re-do F7 as a handler change —
   the pinned REPL has **no env-eviction command** (append-only snapshot arrays), so a per-env cap
   is impossible without forking the REPL internals.
3. **Schema-version cascade is a red-suite trap.** Any change to a `lean_verify` / `search_papers`
   input field or ToolMeta description bumps `TOOL_SCHEMA_VERSION` (`server/tools.py:186`) and
   forces re-pinning `EXPECTED_TOOL_SCHEMA_SHA256` AND every `server/schemas/*.json` `version`+`$id`
   echo in lockstep. Order: bump version first, then `pytest tests/test_server_tool_schema.py
   --update-tool-schema-hash`; `EXPECTED_BP1_SHA256` (`tests/test_prompts.py`) is a **manual**
   re-pin, only when a ToolMeta *description* changes. A missed schema-file echo is exactly what
   turned `main` RED for two days on 2026-07-14 (CLAUDE.md §3).
4. **Running the full suite with `ARXMCP_ENABLE_LEAN=true` fails ~17 server-startup/security/metrics
   tests** — the server-startup fakes use a pid-less `_FakeProc`, and enable-lean makes
   `Resources.startup` spawn Lean through it. This is a **pre-existing test-fake limitation, not a
   regression**. Run `make test` with the Lean env vars UNSET (the default config); run the
   `requires_lean_repl` marker separately WITH the env vars.

## 6. Environment / resume notes (how to reconnect)

- **Repo:** `C:\Users\cedar\Documents\Personal Projects\Source Code\arXMCP`, branch `main`. Repo
  venv python: `./.venv/Scripts/python.exe` (system Python311 lacks deps; the Makefile is
  bash-only). Always `PYTHONUTF8=1` on Windows (cp1252 UnicodeEncodeError landmine on ⊢/ℝ output).
- **Lean toolchain (installed):** `C:\Users\cedar\.elan\bin\{lake,lean,elan}.exe`; toolchains
  present: v4.29.1, v4.30.0-rc2, **v4.31.0**.
- **Mathlib-enabled REPL (built this session):** `C:\Users\cedar\lean-repl-spike\repl`. **Pin
  triple — these MOVE TOGETHER:** repl commit `0cc6026` + Mathlib `v4.31.0` (`fabf563a…`, a
  `[[require]]` git+rev in `lakefile.toml`) + toolchain `leanprover/lean4:v4.31.0`. Oleans came via
  `lake update`'s post-update `cache get` (8542 files, cache hit — never source-build Mathlib;
  watch for `Building Mathlib.*` = a 3–10+ CPU-hour runaway, abort). See memory
  [[arxmcp-lean-env]].
- **Enable the tool** (no launch script sets these — hand-set at server start):
  `ARXMCP_ENABLE_LEAN=true`, `ARXMCP_LAKE_PATH=C:/Users/cedar/.elan/bin/lake.exe`,
  `ARXMCP_LEAN_REPL_DIR=C:/Users/cedar/lean-repl-spike/repl`. Both path vars are FATAL-if-unresolvable
  under enable-lean.
- **Milestone artifacts:** `.claude/notes/milestones/lean-verify-continuation-m1/` (state.json,
  research-synthesis.md, implementation-summary.md, critique-adversary.md).
- **Demo scripts** (session scratchpad, not committed): `demo_v2.py` (pre-warm + reuse + stepping +
  fail-closed), `protocol_probe.py` / `rectify_probe.py` (exact REPL response shapes). Under
  `…\scratchpad\` — regenerate if the scratchpad is gone; the probe findings are in research-synthesis.md.

## 7. Key values you'll need (copy-paste reference)

    repo:            C:\Users\cedar\Documents\Personal Projects\Source Code\arXMCP
    origin/main:     37a1e02  (this session's tip; 5335c58 = concurrent, UNPUSHED)
    session commits: 755dc5e (feat) , 37a1e02 (chore notes)   base 6ade74e
    tool_schema_ver: 20        (server/tools.py:186)
    lean_repl_dir:   C:\Users\cedar\lean-repl-spike\repl   (repl 0cc6026 / Mathlib v4.31.0 / toolchain v4.31.0)
    lake:            C:\Users\cedar\.elan\bin\lake.exe
    enable flags:    ARXMCP_ENABLE_LEAN=true  ARXMCP_LAKE_PATH=<lake>  ARXMCP_LEAN_REPL_DIR=<repl_dir>
    timeout:         DEFAULT_QUERY_TIMEOUT_S = 30.0  (server/lean_repl.py)  ← the m2 constraint
    test (default):  ./.venv/Scripts/python.exe -m ruff check . && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest
    test (real lean): + ARXMCP_ENABLE_LEAN/LAKE_PATH/LEAN_REPL_DIR set, run: pytest -m requires_lean_repl

*Full review of what shipped: [[HANDOFF-2026-07-25-lean-verify-continuation-session-review]].*

# Research synthesis — desktop-distribution-m5

Mode: `--single`. Brief: `research/brief-1.md` (38 KB, implementation-ready).
Brief source: `legacy-prose plans/desktop-distribution-roadmap.md` (7 ACs).

Upstream input, treated as settled and NOT re-derived: the committed
`--deep` fan-out for `desktop-distribution-m4`
(`.claude/notes/milestones/desktop-distribution-m4/research/`, 4 artifacts).

## 1. Design decisions this brief SETTLED (new since m4 research)

- **Entry point: `python -m server.desktop_child`** — not a `--desktop-child`
  flag on `server/cli.py`. The flag was rejected because it contradicts
  `server/cli.py:23-29`'s explicit "config comes from the environment, not
  flags; no second source of truth" rationale. A new console script was
  rejected as needless packaging churn. `python -m server.desktop_child` is
  exactly analogous to the documented `python -m server.main` equivalence.
- **`bound` frame emission point.** Hand-drive `uvicorn.Server.startup()` /
  `main_loop()` / `shutdown()` rather than `Server.run(...)`, and emit the
  single `bound` frame at the point corresponding to installed
  `uvicorn/server.py:195`. That point is provably after BOTH the socket is
  listening AND FastAPI's eager BGE-M3 lifespan warm-up has completed, which
  is what makes AC1's "reaches health/readiness" honest rather than a race.
- **`/readyz` capability middleware scoping — the clean solution.** A plain
  object-wrapper ASGI middleware constructed ONLY inside `desktop_child.py`,
  never registered in `create_app`. Consequence: all 14 existing `/readyz`
  test files are *structurally* unreachable from it, so Docker, `make up`,
  and every existing caller are unaffected by construction rather than by a
  runtime conditional. Satisfies the owner's 2026-08-07 decision and the
  pure-ASGI requirement without touching `Config` or adding an env var.
- **Tauri needs no capabilities/permissions JSON and no CSP or
  `OriginValidationMiddleware` change.** At the HTTP layer the Tauri webview
  loading `/ui/` is indistinguishable from any other loopback client. This
  retires open question 4 from the m4 synthesis.

## 2. Scope — the gate fires AGAIN

| Component | Files | LOC |
|---|---:|---:|
| `server/desktop_child.py` | 1 | 300–450 |
| `apps/desktop/crates/supervisor/` | 5–6 | 500–750 |
| `tests/test_desktop_child.py` | 1 | 200–320 |
| supervisor race test (AC3) | 1–2 | 120–220 |
| Config regression test (AC5) | 1 | 20–50 |
| workspace + Makefile edits | 2 | 30–60 |
| **Total** | **~11–13** | **~1,170–1,850** |

The m4→m5/m6 split did real work — it removed the fault matrix, the 30-cycle
stress, and two of the supervisor's four render states, roughly halving the
surface from 2,100–3,750. But a first-ever Tauri crate plus a first-ever
real-server desktop boot test still exceeds 800 LOC.

**m5 is the minimal COHERENT slice.** Neither half is independently
demonstrable: every one of m5's 7 acceptance criteria requires the supervisor
driving the real child, so a Python-only slice would satisfy none of them and
a supervisor-only slice would have nothing to drive. Further subdivision
produces an enabler milestone with zero demonstrable criteria, not a smaller
reviewable increment.

Remaining trim room named by the brief: reuse the AC3 race test's spawn code
as a thin wrapper over AC1's real-child spawn rather than a parallel
implementation.

## 3. Open decision — BLOCKING Phase 2

`--allow-large-diff` for m5. Requires explicit owner authorization; must not
be inherited from the m3 approval.

## 4. Affected files

New: `server/desktop_child.py`, `apps/desktop/crates/supervisor/{Cargo.toml,
build.rs, tauri.conf.json, src/main.rs}`, `tests/test_desktop_child.py`,
supervisor race test.
Modified: `apps/desktop/Cargo.toml` (workspace member), `Makefile`
(`desktop-conformance` builds + runs the supervisor bin).
Explicitly NOT modified: `server/config.py` (`validate_port_range` unchanged,
AC5), `server/main.py` `create_app`, `server/middleware.py`, `server/tools.py`,
`pyproject.toml`.

## 5. Acceptance criteria → test mapping

Per brief §4, each AC's test also carries the assertion that defeats the
corresponding cheap implementation from m4 brief-3's falsifiability table:
production-entry-point argv assertion (AC1), live-bytes hash against
`EXPECTED_TOOL_SCHEMA_SHA256` (AC2), barrier-released simultaneous launch
(AC3), probe-success assertion (AC4), unchanged-validator regression (AC5),
14-file `/readyz` unreachability argument (AC6).

## external_writes_required

- `git push origin main` (per-event authorization; `CLAUDE.md` §4.4).
  m5 does NOT close issue #397 — m6 does — so no `Fixes` trailer on m5.

## Estimated diff size + file count (Phase-2 gate input)

**~1,170–1,850 LOC across ~11–13 files. Exceeds the 800-LOC ABORT.**

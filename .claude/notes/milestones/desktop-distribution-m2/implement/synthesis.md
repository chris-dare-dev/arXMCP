# Implement synthesis — desktop-distribution-m2

## Built

- **AC1 — installed server relocation:** `tools/wheel_install_check.py:618`
  now creates the dependency-complete venv at its final random location,
  scrubs inherited Python/arXMCP/loader state before the first child import,
  starts the absolute installed `arxmcp-server` from an unrelated CWD, proves
  `server.__file__` is below that venv's site-packages, and requires
  `/healthz == 200` in bootstrap mode.
- **AC2 — observed writes are confined:** `tools/wheel_install_check.py:721`
  POSTs a notebook through the live installed HTTP route, then runs the
  installed production cache, operator-settings, and corpus-marker writers.
  The harness log is captured at `logs/server-boot.log`; the gate requires the
  notebook directory, both SQLite files, corpus marker, and log beneath the
  selected root and prints the complete before/after application-data delta.
- **AC3 — existing launch modes stay compatible:** the wheel contents gate,
  `tests/test_application_paths.py`, `tests/test_compose_server.py`, and
  `tests/test_k8s_manifests.py` all pass unchanged. Docker/Compose still mount
  `/app/var/arxmcp`, `make up` remains source-root based, and the seven
  compatibility aliases retain source-mode external compatibility plus
  installed-mode escape rejection.
- **AC4 — CWD/repository regressions fail cheaply:**
  `tests/test_installed_path_consumers.py:171` covers child-environment
  scrubbing, manifest escape detection, and two real installed-mode writer
  probes from unrelated CWDs. The earlier tests in the same module poison
  import-time notebook/corpus defaults and prove HTTP, UI, retrieval, and MCP
  resource consumers use the live Config layout.
- **AC5 — repository gate:** Ruff and all 5,014 applicable tests pass. No MCP
  tool definition, prompt, Kùzu path/pin, stdout logging behavior, or macOS
  FAISS guard changed.

## Branching note

The continuation landed on the orchestrator-provided detached worktree at
`be709d9`; this worktree cannot check out the main-only repository's `main`
while the shared checkout owns it. The orchestrator must integrate the local
continuation commit onto `main`.

## Files touched

- `server/routes/notebooks.py` — inject Config-owned paths into notebook HTTP
  writers and registry repair.
- `server/routes/ui.py` — resolve preview notebook/corpus reads from Config.
- `server/resources.py` — pass the configured notebook base to per-notebook
  table opens and freshness probes.
- `server/mcp_resources.py` — use the live Config layout for notebook and
  corpus-manifest resources.
- `tools/wheel_install_check.py` — add the clean environment, installed writer
  probe, watched-tree manifests, live notebook request, exact artifacts, and
  application-data delta inventory.
- `tests/test_installed_path_consumers.py` — add six cumulative Config/path
  consumer and relocation regressions (three from the checkpoint, three from
  this continuation).
- `.claude/notes/milestones/desktop-distribution-m2/implement/scope-exceeded.md`
  — retain the required first-pass scope-stop record.

## Deferred

- No acceptance criterion is deferred. The research synthesis made explicit
  Docker/Compose `ARXMCP_DATA_DIR` wiring conditional on proving the current
  deployment depends on CWD. Existing mount/source detection and container
  tests stayed green, and the orchestrator directed that no speculative
  manifest edit be made without such a regression, so those files remain
  byte-identical.
- Frozen native sidecar packaging remains the completed spike's downstream
  desktop-release concern; m2 proves wheel-installed path confinement only.

## external_writes_required

- `git push origin main` — Phase 4 only; not performed here.

## Test deltas

- `tests/test_installed_path_consumers.py` — six cumulative tests cover HTTP/UI
  path injection, per-notebook retrieval, MCP resources, hermetic child env,
  manifest escape rejection, and real writer CWD independence.

## Check gate results

- Focused installed-path tests: **PASS** (`6 passed`).
- Fast `make wheel-check`: **PASS** in a fresh no-dependency venv.
- Real `make wheel-check-full`: **PASS**; installed `/healthz` 200, notebook
  POST 201, all expected writers observed, no watched-tree escape.
- Application-path/wheel/Compose/k8s focused set: **PASS**.
- `make test`: **PASS** (`5014 passed, 47 skipped, 1 xfailed`; Ruff clean).
  The managed sandbox's first run denied fourteen loopback binds with EPERM;
  the exact approved unsandboxed rerun passed, matching the project memory.
- Tool-schema and prompt-cache hashes: **unchanged**.
- `git status --porcelain`: clean after the implementation commit.

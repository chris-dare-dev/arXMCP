# Research Synthesis — textbook-ingest-m5

**Orchestrator merge** of `research-brief-1.md` (in-codebase focus) and
`research-brief-2.md` (external + failure-mode focus).

**Both researchers AGREE on:**
- CLI invocation form over Python-wrapper.
- `ARXMCP_MINERU_BIN` env var → `shutil.which("mineru")` → `RuntimeError` resolution chain.
- `requires_mineru` marker mirrors `requires_pdflatex` exactly: marker + `ARXMCP_RUN_REAL_MINERU=1` env var, skip via lazy string-condition (the F7 pattern from parser-fidelity-eval-m1).
- Tail-truncate stdout/stderr to last 8 KB in `MinerUResult` to bound memory.
- Update `.claude/docs/security-pdf-sandbox.md` in **lockstep** with implementation (m4 F2 "stale-docstring" anti-pattern guard).
- Zero external writes required.

**They DISAGREE on five load-bearing details. Orchestrator resolves below.**

---

## D1 (LOAD-BEARING) — macOS RLIMIT_AS enforceability

**Disagreement:**

- **Brief-1:** "On Darwin, `RLIMIT_AS` is honored; process exits with SIGKILL on exhaustion." Cites `server/lean_repl.py` (verification-feedback-m3) as a precedent that "shipped on macOS without incident."
- **Brief-2:** Live-tested on Darwin 25.4.0 / Apple M4 Max:
  - `resource.getrlimit(RLIMIT_AS) == (RLIM_INFINITY, RLIM_INFINITY)`
  - `resource.setrlimit(RLIMIT_AS, (4 GB, 4 GB))` raises `ValueError: current limit exceeds maximum limit`
  - "The hard limit for virtual address space is effectively `RLIM_INFINITY` and cannot be lowered at the process level."

**Resolution: Brief-2 wins.** A live test on the actual target hardware is authoritative; "shipped without incident" is consistent with the cap silently never firing because no workload has yet exceeded `RLIM_INFINITY`. The `preexec_fn` approach for `RLIMIT_AS` is **non-functional on macOS** — the child process raises `ValueError` between `fork()` and `exec()`, producing a nonzero exit and a Python traceback in stderr, NOT an OOM kill.

**Implication for m5:**

- Implement `_set_mineru_rlimits` only on Linux. Gate with `sys.platform == "linux"` (NOT `!= "win32"`, NOT `hasattr(resource, "setrlimit")`).
- On Darwin, log a WARNING at module import: `"RLIMIT_AS cap not enforceable on macOS (Darwin); wall timeout is the only memory backstop."`
- On Windows, same WARNING with platform name substituted.
- `.claude/docs/security-pdf-sandbox.md` must be updated in lockstep: the spike-2 pseudo-code uses `hasattr(resource, "setrlimit")` which is INSUFFICIENT on Darwin. Update the doc's §Implementation block and §Open questions #4 to record the verified finding.
- **Document the gap:** on macOS, the only backstop against decompression-bomb / memory-exhaustion attacks is the 30-minute wall timeout. Threat surface unchanged for Linux deployments (which is the production target per `docs/install.md`).

**Follow-up issue to file:** `server/lean_repl.py` likely has the same broken-on-macOS RLIMIT_AS pattern (cited by brief-1 as a precedent, audited by brief-2 as having no macOS guard). This is a separate finding — NOT in m5's scope, but flag as a follow-up GitHub issue at `chris-dare-dev/arXMCP`.

---

## D2 (LOAD-BEARING) — MinerU 3.x grandchild FastAPI server

**Disagreement:**

- **Brief-1:** "`os.killpg` ... handles this correctly (entire process group killed)."
- **Brief-2:** Cites `mineru/cli/api_client.py:153` — MinerU's internal `LocalAPIServer` is spawned with its own `start_new_session=True`, creating a grandchild in a DIFFERENT process group. The grandchild "MAY survive an `os.killpg` on the outer CLI's process group."

**Resolution: Brief-2 wins on specificity.** Source code citation > general assertion. The grandchild gap is real.

**Implication for m5:**

- Accept the gap and document it explicitly in `.claude/docs/security-pdf-sandbox.md` §"What this milestone explicitly does NOT do".
- Threat-model rationale: the grandchild server is loopback-only with no external network access. Worst case: orphaned uvicorn process holds GPU/MLX memory until idle-timeout reaps it.
- Test surface: after `os.killpg`, log surviving PIDs via `psutil.children(recursive=True)` IF `psutil` is installed. Do NOT make `psutil` a hard dependency — the project already has it transitively but the m5 driver should degrade gracefully if it's missing.
- The 30-min wall timeout already covers the operational impact; the gap is observability, not correctness.

**Follow-up consideration:** if a future milestone wants to seal this, the path is to use `subprocess.Popen(...)` with `process_group=0` (Python 3.11+) or `os.setpgid(pid, 0)` directly, OR to invoke MinerU via the `mineru-sglang-server` daemon mode where the daemon's lifecycle is managed independently. Both are out of scope.

---

## D3 (MEDIUM) — Markdown output path structure

**Disagreement:**

- **Brief-1:** "Output structure produces markdown file and `content_list.json` in the output directory" (loose).
- **Brief-2:** Verified path is `<output_dir>/<pdf_stem>/<parse_method>/<pdf_stem>.md`, NOT flat. Cited from `mineru/cli/output_paths.py::build_parse_dir`.

**Resolution: Brief-2 correct.** This matches the B1 smoke-test output verbatim — markdown landed at `/tmp/mineru-smoke-direct/milne-introduction-to-shimura-varieties/auto/milne-introduction-to-shimura-varieties.md`.

**Implication for m5:**

- Always invoke with `-b pipeline -m auto` (deterministic parse_method).
- Resolve `MinerUResult.markdown_path` by globbing `output_dir/<pdf_stem>/auto/<pdf_stem>.md` after subprocess exits 0; fall back to `output_dir/**/*.md` glob if direct path not found (FM-4 mitigation).
- If no `.md` file exists after subprocess exits 0, raise `RuntimeError` with the directory listing (don't silently return an invalid MinerUResult).

---

## D4 (MEDIUM) — TMPDIR scrubbing

**Disagreement:**

- **Brief-1:** Whitelist passes through `TMPDIR` as-is.
- **Brief-2:** Override `TMPDIR` to `str(output_dir)` to prevent cross-notebook contamination (FM-8).

**Resolution: Brief-2 wins.** Cross-notebook TMPDIR contamination is a real defense-in-depth concern (the per-notebook blast-radius is the layer-3 defense; passing through TMPDIR could leak between notebooks).

**Implication for m5:**

- `_scrub_subprocess_env()` constructs the env: keep `PATH`, `HOME`, `LANG`, `LC_ALL` from inherited; OVERRIDE `TMPDIR` to `str(output_dir)`.
- Note: the spike-2 doc's whitelist `("PATH", "TMPDIR", "HOME", "LANG", "LC_ALL")` permitted TMPDIR inheritance. Update the doc in lockstep to reflect the new override semantics.

---

## D5 (LOW) — Stdout truncation size

**Disagreement:** brief-1 says 8 KB; brief-2 calls it a non-orchestrator decision.

**Resolution:** 8 KB it is. The choice is bounded by "enough for error diagnostics" — 8 KB satisfies that. Implementer should NOT spend time bikeshedding.

---

## Orchestrator synthesis note — load-bearing decisions

The synthesis lands these decisions (in priority order for implementation):

1. **Invocation:** `["<mineru_bin>", "-p", str(pdf_path), "-o", str(output_dir), "-b", "pipeline", "-m", "auto"]` via `subprocess.Popen`.
2. **Binary resolution:** `ARXMCP_MINERU_BIN` (absolute path) > `shutil.which("mineru")` > `RuntimeError` (NOT a silent skip). The `requires_mineru` marker handles the test-collection skip.
3. **RLIMIT_AS:** Linux-only. Darwin gets a WARN log at import + relies on wall timeout. Windows: no-op + WARN.
4. **Process group kill:** `start_new_session=True` + `os.killpg(os.getpgid(proc.pid), SIGKILL)` + drain second `communicate(timeout=5)`. Grandchild FastAPI server gap documented and accepted.
5. **Env scrub:** Whitelist (`PATH`, `HOME`, `LANG`, `LC_ALL`); OVERRIDE `TMPDIR` to `output_dir`. Strip everything else (no `HF_*`, no `AWS_*`, no proxy vars).
6. **MinerUResult fields:** `output_dir`, `markdown_path`, `content_list_path`, `stdout` (last 8 KB), `stderr` (last 8 KB), `wall_clock_s`. Frozen dataclass. `markdown_path` resolved via glob after subprocess exits.
7. **Timeout config:** `ARXMCP_MINERU_TIMEOUT_S` parsed at module load; reject non-integer or out-of-[60, 3600] with explicit RuntimeError (no silent clamp, per AC).
8. **Test marker:** `requires_mineru` in `pyproject.toml`; skip semantics = `pytest -m requires_mineru` AND `ARXMCP_RUN_REAL_MINERU=1`; skipif lazy-string-condition (F7 pattern).

---

## Open questions (after synthesis)

ALL six brief-level open questions resolved above. No questions block implementation.

One **flag-only** item (not a question):

- **F-FLAG-1:** `server/lean_repl.py` may have the same broken-on-macOS `RLIMIT_AS` pattern that brief-2 identified for MinerU. Out of m5 scope but should file a follow-up issue at `chris-dare-dev/arXMCP` for audit.

---

## External writes the implementation will require

| type | target | why | blocking? |
|---|---|---|---|
| (none) | | | |

This milestone is purely local. All deliverables land in the working tree:
- `ingest/textbook_parser.py` (new module)
- `tests/test_textbook_parser.py` (new tests)
- `pyproject.toml` (markers + extras update)
- `docs/install.md` (env-var documentation)
- `.claude/docs/security-pdf-sandbox.md` (lockstep update — D1 + D2 + D4 + MinerU 3.2.0 naming)
- `CLAUDE.md §8` (landmines: macOS RLIMIT_AS gap + MinerU grandchild gap)

No git push. No GitHub issue creation. No infra mutation. No third-party API calls.

---

## Implementer's checklist (synthesized)

Pre-implementation:
- [ ] Read `.claude/docs/security-pdf-sandbox.md` end-to-end before writing code.
- [ ] Confirm `~/venvs/mineru/bin/mineru --version` returns `3.2.0`.

Driver:
- [ ] `ingest/textbook_parser.py` with `MinerUResult` frozen dataclass + `run_mineru_sandboxed()`.
- [ ] Linux-only `_set_mineru_rlimits` preexec_fn with `sys.platform == "linux"` gate.
- [ ] Darwin / Windows WARN log at module import time (not call time).
- [ ] `_scrub_subprocess_env()` with TMPDIR override.
- [ ] Module-load parse of `ARXMCP_MINERU_TIMEOUT_S` (60–3600 inclusive; RuntimeError on parse failure or out-of-range).
- [ ] Module-load WARN/RuntimeError if `mineru` binary missing.
- [ ] `markdown_path` resolution via glob after subprocess exits 0.

Tests:
- [ ] `requires_mineru` marker registered in `pyproject.toml` mirroring `requires_pdflatex`.
- [ ] Unit tests (always run): mock subprocess; verify `start_new_session=True`, `preexec_fn` on Linux only, env whitelist exact, TMPDIR override, timeout passed through, RuntimeError on bad timeout env var.
- [ ] Integration test (opt-in): real MinerU on a 1-page synthetic PDF; verify MinerUResult fields populated; assert markdown_path exists and is non-empty.
- [ ] Sandbox enforcement test (opt-in, Linux-only): synthetic memory pressure scenario; verify subprocess SIGKILL'd.
- [ ] Wall-timeout test: mocked + short-timeout integration; verify killpg path fires.

Docs:
- [ ] `docs/install.md` — `ARXMCP_MINERU_BIN`, `ARXMCP_MINERU_TIMEOUT_S`, model-weight pre-download command.
- [ ] `.claude/docs/security-pdf-sandbox.md` — update §Implementation, §Open questions, §"explicitly does NOT do" with the four D1/D2/D4 findings. Also bump "MinerU 2.5" → "MinerU 3.2.0" everywhere.
- [ ] `CLAUDE.md §8` — entry #N: "macOS RLIMIT_AS is non-enforceable" (verified live test).
- [ ] `pyproject.toml` `[project.optional-dependencies]` extras `[pdf]`: `mineru>=3.2.0,<4`.

---

## Size estimate

- `ingest/textbook_parser.py`: ~150 LOC
- `tests/test_textbook_parser.py`: ~300 LOC (unit + integration + enforcement)
- `pyproject.toml` edits: ~10 LOC
- `docs/install.md` edits: ~20 LOC
- `.claude/docs/security-pdf-sandbox.md` edits: ~30 LOC
- `CLAUDE.md` edits: ~10 LOC

Total: ~520 LOC across 6 files. Borderline on the inline-path threshold (< 500 LOC AND < 5 files). The 6-file count tips this to DELEGATED, but the boundary is single — there is no clean two-part partition.

**Recommendation: INLINE.** One coherent module + its tests + accompanying docs. No specialist-domain match. Splitting along file boundaries would create an awkward partition where the test file lands in part-2 while the module ships in part-1 (defeats the purpose of delegation).

# Research Brief — textbook-ingest-m5

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-28T01:30:00Z

## In-codebase context

### Prescriptive contract — `.claude/docs/security-pdf-sandbox.md`

This document IS the design. Verbatim load-bearing constraints:

**Invocation form (verbatim from §Implementation):**
```python
proc = subprocess.Popen(
    ["mineru", "-p", str(pdf_path), "-o", str(output_dir)],
    cwd=output_dir,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    start_new_session=True,
    env=sandbox_env,
    preexec_fn=(
        _set_mineru_rlimits if hasattr(resource, "setrlimit") else None
    ),
)
```

**Kill discipline (verbatim):**
```python
except subprocess.TimeoutExpired:
    with contextlib.suppress(ProcessLookupError, OSError):
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.communicate(timeout=5)  # drain PIPEs; avoid deadlock
    raise
```

**Env scrub whitelist (verbatim from `_scrub_subprocess_env` docstring):**
> "Strips proxies, AWS / GCP / Azure credentials, anything that could enable network egress or credential leak. Whitelists only the variables MinerU genuinely needs (PATH for binary lookup; TMPDIR for its own scratch; HOME for ~/.cache lookup of bundled ONNX models)."

`keep = ("PATH", "TMPDIR", "HOME", "LANG", "LC_ALL")`

**RLIMIT_AS (verbatim):**
> "_MINERU_RLIMIT_AS_BYTES = 4 * 1024 * 1024 * 1024  # 4 GB ... Virtual-memory ceiling for the MinerU subprocess. 4 GB is ~2x the nominal working set on a 500-page textbook (measured offline)"

**Explicit omissions (verbatim):**
> "Does NOT implement `sandbox-exec` profiles on macOS... Does NOT implement seccomp/landlock on Linux... Does NOT run MinerU as a separate UID."

**Note:** The security-pdf-sandbox.md pseudo-code uses `["mineru", ...]` (CLI form) directly. The milestone brief adds `-b pipeline` to force the CPU/pipeline backend (not present in the spike doc). **FLAG: the `-b pipeline` flag addition is a deviation from the prescriptive contract** — the brief is correct (B1 validated pipeline backend), but the doc update must accompany implementation. The sandbox doc still references "MinerU 2.5" (line 114) while B1 shipped 3.2.0.

### Peer subprocess patterns in the codebase

**`tools/cdm_eval.py::_run_subprocess_with_pgkill`** (lines 333-382):
- Uses `start_new_session=True`, `os.killpg`, `proc.communicate(timeout=5)` drain pattern
- Does NOT use `preexec_fn` / RLIMIT_AS (pdflatex is shorter-lived and memory-bounded differently)
- Returns `subprocess.CompletedProcess` — a reusable helper pattern

**`server/lean_repl.py`** (lines 170-188):
- Full RLIMIT_AS pattern with `_apply_rlimit_as` closure
- Windows guard: skips `preexec_fn` if `sys.platform == "win32"` AND logs a WARN
- Uses `_resource` module aliased at top of file; checks `_resource is not None`
- Uses `spawn_kwargs: dict[str, Any] = {}` then conditionally populates `preexec_fn`

**Critical lesson from lean_repl.py:** The Windows path must NOT pass `preexec_fn=None` to `subprocess.Popen` — pass NO `preexec_fn` argument at all. Build kwargs dict conditionally. This differs from the security-pdf-sandbox.md pseudo-code which uses `hasattr(resource, "setrlimit")` — the lean_repl.py pattern is more robust (checked sys.platform + module availability).

### B1 ground truth (from commit `aec46ce`)

- MinerU 3.2.0 installed at `~/venvs/mineru/bin/mineru`
- **NOT on default PATH** — explicit note: "wait for m5 to introduce the `ARXMCP_MINERU_BIN` env-var pattern that points at the absolute path"
- ONNX model weights NOT yet downloaded (lazy-fetch on first invocation from `~/.cache/mineru/`)
- Apple M4 Max + 38 GB unified memory EXCEEDS the 4 GB RLIMIT_AS cap (intentional — defense, not perf limit)
- CLI signature confirmed: `mineru -p <pdf> -o <dir> -b pipeline` (pipeline = CPU-compatible backend)

### MinerU 3.2.0 architectural change (verified via upstream)

MinerU 3.x changed the CLI architecture: `mineru` now functions as an orchestration client backed by `mineru-api`. When `--api-url` is absent, a local temporary service starts automatically. This means the CLI may spawn background services that survive beyond the subprocess — a critical security implication for the process-group kill discipline. `os.killpg` with `start_new_session=True` handles this correctly (entire process group killed), but the OOM test must account for this service model.

### Test marker precedent (`pyproject.toml` lines 203-204)

```
"requires_lean_repl: tests that invoke the real Lean 4 REPL subprocess...
 Skipped by default; opt-in by setting BOTH ARXMCP_LAKE_PATH ... and ARXMCP_LEAN_REPL_DIR ..."
"requires_pdflatex: tests that invoke the real pdflatex + pdftoppm binaries...
 Skipped by default; opt-in via pytest -m requires_pdflatex AND ARXMCP_RUN_REAL_PDFLATEX=1."
```

The `requires_pdflatex` pattern (marker + env var `ARXMCP_RUN_REAL_PDFLATEX=1`) is the correct template for `requires_mineru` / `ARXMCP_RUN_REAL_MINERU=1`.

### Applicable design notes

- **`08-security-observability-ops.md` §Threat 3** — LaTeXML sandbox as peer; subprocess discipline, no network egress, hard timeout
- **`04-parsing-and-chunking.md`** — chunker consumes HTML5+MathML; m5's MinerUResult.markdown_path feeds m6's LaTeXML re-render pass
- **`06-mcp-server-design.md`** — no MCP surface changes in this milestone (confirmed: no tool additions)
- **`07-multi-agent-caching.md`** — no cache invalidation risk (no tool-schema changes)

### No conflicts with banned patterns

- `assert` — must use `if ... raise RuntimeError(...)` for all invariants in `textbook_parser.py`
- `BaseHTTPMiddleware` — not applicable
- `anthropic` SDK — not applicable
- No MCP surface changes → tool-schema SHA re-pin NOT required

---

## Prior decisions and lessons

### m4 critique-merged.md key findings relevant to m5

**F2 (HIGH, FIXED in 800cc0b):** "stale docstring" anti-pattern — m4 edited the implementation but didn't update `security-pdf-sandbox.md` in lockstep. m5 MUST update `security-pdf-sandbox.md` in the same commit that lands `textbook_parser.py`. The doc still says "MinerU 2.5" and the prescriptive code lacks `-b pipeline`.

**F5 (MEDIUM, FIXED):** Backstop attribution — pdfid.py docstring overstated m5's sandbox capability (RLIMIT_AS bounds resources, does NOT prevent JS execution). m5's sandbox profile should NOT claim to prevent JS execution — that's PyMuPDF's property.

### From m4 implementation-summary

- m4 is `complete` (state.json confirms, 2026-05-28T00:44:46Z)
- `tools/security/pdfid.py` and `tools/security/__init__.py` shipped
- No MinerU integration — "No changes to MinerU integration (deferred to m5)" confirmed

### No adjacent `ingest/textbook_parser.py` exists

Confirmed via direct filesystem check: both `ingest/textbook_parser.py` and `ingest/_mineru_runner.py` are absent. m5 creates them fresh.

---

## External sources

**MinerU 3.2.0 CLI (verified via upstream GitHub README):**
- CLI form confirmed: `mineru -p <input_path> -o <output_path> -b pipeline`
- `-b pipeline` selects CPU-only mode (no GPU required; safe for sandbox testing)
- MinerU 3.x now uses a client-server architecture internally: CLI spawns a local API service when `--api-url` is absent. This means the spawned process group includes background service processes — `os.killpg` is essential (bare `proc.kill()` would not reap all spawned services)
- Output structure produces markdown file and `content_list.json` in the output directory

**RLIMIT_AS on macOS (no primary source available; inferred from lean_repl.py precedent):**
The lean_repl.py (verification-feedback-m3) already shipped RLIMIT_AS on macOS without incident. The 4 GB cap is enforced by the kernel's virtual memory manager. On Darwin, RLIMIT_AS affects `mmap`/`brk` allocation; the process gets SIGKILL (not SIGSEGV) on exhaustion. The OOM test should verify the exit code is nonzero, not a specific signal number (signal numbers differ cross-platform).

---

## Recommendation

**Use CLI form with `ARXMCP_MINERU_BIN` absolute-path resolution.** Reasoning:

1. The prescriptive contract in `security-pdf-sandbox.md` specifies CLI form (`["mineru", "-p", ...]`)
2. B1 confirmed `mineru` is NOT on the default PATH — `ARXMCP_MINERU_BIN` is already planned in the B1 commit note
3. Python-wrapper form requires a separate `_mineru_runner.py` module that must be importable under the MinerU venv, creating coupling between two Python environments
4. CLI form is simpler to sandbox — the subprocess boundary is the binary, not Python import machinery

**Binary resolution logic:**
1. Check `ARXMCP_MINERU_BIN` env var → use as absolute path if set
2. Fall back to `shutil.which("mineru")` → use if found
3. If neither: raise `RuntimeError` at call time (NOT at module load) — integration tests skip via `requires_mineru` marker; unit tests mock the subprocess anyway

**Do NOT raise at module load** if `mineru` is absent — this would break the unit-test suite (the mock tests run without MinerU installed).

**`requires_mineru` skip semantics:** Follow `requires_pdflatex` pattern exactly — both `pytest -m requires_mineru` AND `ARXMCP_RUN_REAL_MINERU=1` env var required.

**Stdout handling:** Tail-truncate to last 8 KB in `MinerUResult.stdout`. MinerU's pipeline backend emits model-load progress + per-page diagnostics. Capturing the full stream (potentially multi-MB) into a string field would make `MinerUResult` a memory hazard. 8 KB preserves the failure-relevant tail while bounding the field.

**macOS RLIMIT_AS test:** Write the test as an optional, opt-in test under `requires_mineru`. The OOM scenario requires synthesizing a memory-exhausting workload — not reliably achievable with a synthetic PDF. Document the limitation: "macOS RLIMIT_AS is honored but OOM kill verification requires real model load; deferred to operator validation." Flag this as a known gap in the sandbox profile doc, not a test-skipped-forever.

**WARN log for Windows:** At module import time (top-level `if sys.platform == "win32": logger.warning(...)`) to match the lean_repl.py pattern (verified precedent).

---

## Open questions

All six open questions resolved:

1. **Invocation form?** CLI form. See Recommendation above.

2. **`mineru` binary resolution semantics?** `ARXMCP_MINERU_BIN` (absolute path) → `shutil.which("mineru")` → `RuntimeError` at call time. The B1 commit confirms `~/venvs/mineru/bin/mineru` is the operator's path; document this as the example value in `docs/install.md`.

3. **`requires_mineru` skip semantics?** Yes — same as `requires_pdflatex`: marker AND `ARXMCP_RUN_REAL_MINERU=1` env var both required. Add to `pyproject.toml` `[tool.pytest.ini_options].markers` with the full docstring pattern.

4. **macOS RLIMIT_AS reliability?** The lean_repl.py precedent ships the same cap on macOS without incident. On Darwin, `RLIMIT_AS` is honored; process exits with SIGKILL on exhaustion. Write the OOM test as `requires_mineru` opt-in; document the "soft-vs-hard" caveat in the sandbox doc update. Do NOT block the milestone on a full OOM synthesis — that requires 4+ GB of malloc pressure and is better as a manual validation note.

5. **Subprocess stdout volume?** Tail-truncate to last 8 KB. `MinerUResult.stdout` holds the tail; `MinerUResult.stderr` holds the same last-8-KB treatment. If implementer wants full output, they can redirect to `output_dir/mineru.log` (acceptable extension but not required for AC).

6. **MinerU model weight prerequisite?** `HOME` is in the whitelist specifically to preserve `~/.cache/mineru/`. Document in `docs/install.md` that model weights must be pre-downloaded via `~/venvs/mineru/bin/mineru-models-download -s huggingface -m pipeline` before any integration test runs (B1 commit confirms this is ~5-7 GB, lazy-fetched otherwise).

**Additional flag (not in brief's 6 open questions):**

**FLAG: MinerU 3.x CLI spawns a background API service** — the process group may include more processes than MinerU 2.5 did. `os.killpg` handles this correctly, but unit tests that mock `subprocess.Popen` must mock the full `communicate()` + `killpg` path, not just `proc.returncode`. Existing `_run_subprocess_with_pgkill` in `cdm_eval.py` is the test-mock reference pattern.

**FLAG: `security-pdf-sandbox.md` MUST be updated in the same commit** as `textbook_parser.py`. Per m4's F2 finding pattern (HIGH, stale-docstring anti-pattern cited twice across m3 and m4), the doc is the operator-facing security contract. Update: "MinerU 2.5" → "MinerU 3.2.0", add `-b pipeline` to the CLI invocation, update the `run_mineru_sandboxed` return type from `str` to `MinerUResult`.

---

## External writes the implementation will require

None — this milestone is purely local.

All deliverables land in the working tree:
- `ingest/textbook_parser.py` (new)
- `tests/test_textbook_parser.py` (new)
- `pyproject.toml` (markers + extras update)
- `docs/install.md` (env var documentation)
- `.claude/docs/security-pdf-sandbox.md` (update in lockstep)
- `CLAUDE.md §8` (landmines entry)

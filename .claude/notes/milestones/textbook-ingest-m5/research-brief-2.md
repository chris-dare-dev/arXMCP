# Research Brief — textbook-ingest-m5

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-28T01:30:00Z

## In-codebase context

The prescriptive contract lives at `.claude/docs/security-pdf-sandbox.md`. All
load-bearing pseudo-code is verbatim from that document; the implementer must
follow it, deviating only where reality forces it. The brief makes this explicit:
"implement per spec, deviating only where reality forces it (macOS OOM behavior)."

**Load-bearing from `.claude/docs/security-pdf-sandbox.md` §Implementation:**
```python
proc = subprocess.Popen(
    ["mineru", "-p", str(pdf_path), "-o", str(output_dir)],
    ...
    start_new_session=True,
    env=sandbox_env,
    preexec_fn=(
        _set_mineru_rlimits if hasattr(resource, "setrlimit") else None
    ),
)
```

The spike-2 doc uses `hasattr(resource, "setrlimit")` as the POSIX guard, which
would PASS on macOS (the `resource` module exists) while still failing at runtime
inside the child. The CORRECT guard must additionally check at call-time whether
the cap can actually be set — or use `sys.platform` to skip on Darwin.

**Peer sandbox precedents found in codebase:**
- `tools/cdm_eval.py::_run_subprocess_with_pgkill` — the closest reusable pattern
  (process-group kill + PIPE drain). Does NOT use `preexec_fn` (pdflatex does not
  need a memory cap). Has this explicit comment: "mirrors parse_with_latexml
  discipline."
- `server/lean_repl.py::spawn` — uses `preexec_fn` for RLIMIT_AS, guards on
  `sys.platform != "win32"` AND `_resource is not None`. Does NOT guard on macOS
  specifically; logs a WARNING for Windows but silently proceeds on macOS.

**CONFLICT FLAGGED:** The spike-2 doc's `preexec_fn=(_set_mineru_rlimits if
hasattr(resource, "setrlimit") else None)` guard is INSUFFICIENT on macOS. The
`resource` module IS present on Darwin (it provides RLIMIT_AS), but
`setrlimit(RLIMIT_AS, (4GB, 4GB))` raises `ValueError: current limit exceeds
maximum limit` at runtime. The check `hasattr(resource, "setrlimit")` passes on
macOS, the preexec_fn is set, but the child process crashes with ValueError before
exec — this is a silent broken state. The security document claims RLIMIT_AS is
"honored" on Darwin with a "soft-vs-hard distinction," but the actual Darwin
behavior is that RLIM_AS hard limit = RLIM_INFINITY and cannot be lowered.

**MinerU 3.x vs spike-2's "MinerU 2.5" naming:** B1 shipped 3.2.0. The CLI
invocation form in the spike-2 doc (`["mineru", "-p", ..., "-o", ..., "-b",
"pipeline"]`) IS still valid for MinerU 3.2.0.

**CONFLICT FLAGGED:** MinerU 3.x CLI default backend is `hybrid-auto-engine`,
NOT `pipeline`. The brief specifies `-b pipeline`. This is correct to specify
explicitly; without it, MinerU 3.x would use `hybrid-auto-engine` which has
different output-tree layout and model dependencies.

**Output tree structure for `-b pipeline`:** MinerU 3.2.0 source code
(`mineru/cli/output_paths.py::build_parse_dir`) produces:
```
<output_dir>/<pdf_stem>/<parse_method>/<pdf_stem>.md
<output_dir>/<pdf_stem>/<parse_method>/<pdf_stem>_content_list.json
```
For `-b pipeline -m auto` (default parse_method): `<output_dir>/<stem>/auto/<stem>.md`.
`MinerUResult.markdown_path` must resolve via this subdirectory path, NOT at
`<output_dir>/<stem>.md`. If the parse_method is not specified, it defaults to
`auto`. The implementer must pass `-m auto` explicitly (or document the default)
to make the output path deterministic.

**MinerU 3.x internal architecture:** CRITICAL FINDING. MinerU 3.2.0 CLI does NOT
execute as a simple single subprocess. When invoked as `mineru -b pipeline ...`,
the CLI internally spawns a FastAPI/uvicorn server on a random local port, then
communicates with it via HTTP to perform the parse. The internal server is itself
a subprocess (`LocalAPIServer`, started with `start_new_session=True` internally).
This means `os.killpg` on the outer `mineru` PID will kill the CLI process AND
its internal server process (same process group, since the outer Popen uses
`start_new_session=True` which puts the CLI process in a new session, but MinerU
internally uses its own `start_new_session=True` for the FastAPI server, creating
a GRANDCHILD in a DIFFERENT session/process group). The grandchild server process
MAY survive an `os.killpg` on the outer CLI's process group.

**KMP_DUPLICATE_LIB_OK:** The macOS segfault guard in `tests/conftest.py` is
load-bearing. The MinerU process tree includes PyTorch + ONNX workers, which are
exactly the co-load pattern that triggers this guard. This milestone must NOT
remove it. No changes to `tests/conftest.py` expected.

## Prior decisions and lessons

Recent git log shows m4 shipped cleanly (`rect` + `feat` at `4d99e31`). The 5
pre-flight vectors are complete. The pattern from m4 research-brief-2 (which
covered failure modes in the upload perimeter) is directly reusable here at the
subprocess layer.

From `lean_repl.py` pattern: RLIMIT_AS preexec_fn is guarded POSIX-only but does
NOT additionally exclude macOS — this is a known behavioral gap in the existing
codebase (the lean REPL docs note "POSIX-only" but Darwin's enforcement is weak).
The implementer should follow the lean_repl.py structural pattern but add explicit
Darwin handling (either a WARNING-and-skip or a runtime test).

`requires_pdflatex` marker in `pyproject.toml` is the right template for
`requires_mineru`. That marker requires BOTH `pytest -m requires_pdflatex` AND
`ARXMCP_RUN_REAL_PDFLATEX=1`.

`_run_subprocess_with_pgkill` in `tools/cdm_eval.py` is the closest extraction
candidate. It handles the PIPE-drain-on-timeout correctly (uses `communicate`
not `wait`).

## External sources

### MinerU 3.2.0 CLI (verified against installed binary at `~/venvs/mineru/`)

Actual CLI signature (from `mineru --help`):
```
mineru -p PATH -o PATH [-b {pipeline|vlm-http-client|hybrid-http-client|
       vlm-auto-engine|hybrid-auto-engine}] [-m {auto|txt|ocr}] ...
```
Default backend: `hybrid-auto-engine` (NOT pipeline). Default parse method: `auto`.
The `-b pipeline` flag is valid and routes to the pipeline backend.

Output tree for `-b pipeline -m auto`:
```
<output_dir>/<stem>/auto/<stem>.md
<output_dir>/<stem>/auto/<stem>_content_list.json
<output_dir>/<stem>/auto/<stem>_middle.json
<output_dir>/<stem>/auto/images/
```
The markdown path is NOT flat; it has two nested subdirs.

**CRITICAL architecture finding:** MinerU 3.x spawns an internal FastAPI server
subprocess. The outer `mineru` process is a thin CLI client; the actual parsing
happens in a child FastAPI process. When `os.killpg` fires on the outer process
group, the grandchild FastAPI server (which uses its own `start_new_session=True`)
may NOT be in the same process group and may survive the kill.

### Python `resource.setrlimit(RLIMIT_AS, ...)` on macOS

**VERIFIED by live test on this machine (Darwin 25.4.0, Apple M4 Max):**
- `resource.getrlimit(RLIMIT_AS)` returns `(RLIM_INFINITY, RLIM_INFINITY)`
- `resource.setrlimit(RLIMIT_AS, (4GB, 4GB))` raises `ValueError: current limit
  exceeds maximum limit`
- `resource.setrlimit(RLIMIT_AS, (4GB, RLIM_INFINITY))` ALSO raises `ValueError`
- RLIMIT_RSS shows identical behavior

This is a documented macOS kernel constraint: the hard limit for virtual address
space is effectively RLIM_INFINITY and cannot be lowered at the process level.
The macOS kernel enforces memory limits via `ulimit -v` shell built-in, which
operates differently from Python's `resource.setrlimit`. The `preexec_fn` approach
for RLIMIT_AS is **non-functional on macOS** — it raises ValueError in the child
process before exec, which surfaces as a Python traceback in `proc.stderr` and a
nonzero exit code but NOT an OOM kill.

**Mitigation:** The RLIMIT_AS preexec_fn must be guarded with platform detection.
On Darwin, the wall timeout is the ONLY enforced memory backstop (MinerU's
process will be killed after 30 min regardless, but NOT on memory limit breach).
Document this gap explicitly per the milestone AC: "If macOS does not enforce
hard kill on overflow, document the gap."

### Python `subprocess.Popen(preexec_fn=...)` deprecation status (Python 3.12)

From Python 3.12 docs: `preexec_fn` is **NOT deprecated** but is subject to a
thread-safety warning and a subinterpreter restriction (raises RuntimeError in
subinterpreters since 3.8). The docs note that `start_new_session` and
`process_group` parameters "should take the place of code using preexec_fn to
call os.setsid() or os.setpgid()". For RLIMIT_AS specifically, there is no
alternative parameter — `preexec_fn` remains the correct approach. No deprecation
warning is issued in Python 3.12 for normal use.

**CONFLICT resolved:** The spike-2 pseudo-code's use of `preexec_fn` is NOT
deprecated and should be retained. The concern from Open question #4 is about
macOS RLIMIT_AS enforcement (the cap silently fails), not about `preexec_fn`
deprecation.

### `os.killpg` + `start_new_session` under MinerU's subprocess fan-out

`start_new_session=True` places the outermost MinerU process in a new process
group (same pgid as its own pid). On timeout, `os.killpg(os.getpgid(proc.pid),
SIGKILL)` sends SIGKILL to all processes sharing that pgid. This covers: the
MinerU CLI process + any direct children that didn't call `setsid()` or
`setpgrp()`.

The risk: MinerU 3.x's internal FastAPI server is launched with its OWN
`start_new_session=True` (confirmed in `mineru/cli/api_client.py` line 153:
`return {"start_new_session": True}`). This creates a grandchild in a NEW
process group — it will NOT be reaped by `os.killpg` on the outer CLI's pgid.
MinerU internally handles its own cleanup via `LocalAPIServer.stop()`, but if
the outer process is SIGKILL'd, that cleanup may not run.

**Mitigation:** Use `psutil.children(recursive=True)` before SIGKILL to find
and kill the grandchild server (if psutil is available), OR document this as
an accepted gap (MinerU's internal server is loopback-only with no external
network access; it will exit when its parent pipe closes).

## Failure-mode analysis

**FM-1: preexec_fn raises ValueError on macOS (RLIMIT_AS)**
- Trigger: `_set_mineru_rlimits` called inside child; macOS raises ValueError.
- Symptom: subprocess exits with nonzero before parsing begins; RuntimeError
  with stderr showing Python traceback, NOT an OOM kill.
- Mitigation: Guard with `sys.platform != "darwin"` (or `sys.platform == "linux"`
  for strict POSIX); on Darwin, log WARNING at module import; rely on wall timeout.

**FM-2: MinerU grandchild FastAPI server survives killpg**
- Trigger: wall timeout fires; `os.killpg` kills outer CLI pgid; internal FastAPI
  server (different pgid) continues running on a random loopback port.
- Symptom: orphaned uvicorn process holding GPU memory; next invocation may fail
  to find a free port, OR the orphan exits when the listening socket is reclaimed.
- Mitigation: After killpg, wait briefly, then kill by pid lookup (`pkill -f
  mineru-api`) OR accept the gap (the orphan is loopback-only; worst case it
  exits on idle timeout). Document as known gap.

**FM-3: MinerU writes to ~/.cache/mineru/ even with scrubbed HOME**
- Trigger: MinerU model loading checks `HOME/.cache/mineru/` for weights; if
  HOME is scrubbed/overridden to a temp dir, MinerU tries to re-download weights.
- Symptom: network egress attempt during parsing; download failure causes parse
  failure OR silent fallback to OCR mode.
- Mitigation: The milestone whitelist correctly INCLUDES `HOME` to preserve the
  existing model weight cache path. This is documented in the milestone AC. The
  risk is that `HOME` also carries e.g. `~/.aws/credentials`; the trade-off is
  accepted (HOME is required for MinerU to find its weights).

**FM-4: MinerU output path resolution fails after minor version bump**
- Trigger: MinerU 3.x minor update changes `build_parse_dir` logic (e.g. parse
  method renamed, subdirectory removed, stem truncated for long filenames).
- Symptom: `MinerUResult.markdown_path` points to a nonexistent file; `m6`'s
  LaTeXML step fails with FileNotFoundError.
- Mitigation: After subprocess exits 0, probe for existence of
  `markdown_path`; if missing, glob `output_dir/**/`*.md` to find the actual
  path. Raise `RuntimeError` with found paths if no `.md` exists (don't silently
  return empty).

**FM-5: MinerU stdout/stderr pipe buffer exhaustion → deadlock**
- Trigger: MinerU pipeline backend prints multi-MB progress to stdout (model
  load, per-page diagnostics); `proc.communicate(timeout=...)` buffers in memory.
  NOT a deadlock risk because `communicate()` already drains both PIPEs using
  threads internally. BUT the result is a multi-MB `MinerUResult.stdout` field.
- Symptom: `MinerUResult.stdout` is 10-50 MB for a 500-page textbook; serializing
  MinerUResult to a log or returning it to caller wastes memory.
- Mitigation: Tail-truncate stdout to last 8 KB (sufficient for diagnostics);
  emit the full stdout to `output_dir/mineru-stdout.log` if debug logging enabled.

**FM-6: Corrupt or empty markdown output (silent success)**
- Trigger: MinerU exits 0 but the markdown file is empty or contains only
  headers (common with scanned PDFs that pass the pre-flight page-count check
  but have no extractable text in text-mode).
- Symptom: `MinerUResult.markdown_path` exists, size is >0 but content is
  `\n# Page 1\n` × N; downstream LaTeXML step produces empty HTML; no error.
- Mitigation: After subprocess exits, check `markdown_path.stat().st_size > 100`
  (or parse header count vs content ratio); emit WARNING log if suspicious;
  propagate as a parse quality flag, not a hard error (m6 can decide).

**FM-7: `ARXMCP_MINERU_TIMEOUT_S` parses to non-integer**
- Trigger: Operator sets `ARXMCP_MINERU_TIMEOUT_S=foo` or `ARXMCP_MINERU_TIMEOUT_S=`
  (empty string).
- Symptom: `int(os.environ["ARXMCP_MINERU_TIMEOUT_S"])` raises ValueError at
  module load; server crashes on startup.
- Mitigation: Parse at module load with explicit try/except; raise RuntimeError
  with a clear message if non-integer; clamp to [60, 3600] with an explicit
  RuntimeError if out-of-range (the milestone AC says "reject out-of-range...
  with a clear RuntimeError, not silent clamp").

**FM-8: MinerU subprocess inherits a leaked TMPDIR from another notebook operation**
- Trigger: A concurrent request sets `TMPDIR` pointing to notebook A's directory;
  the scrubbed env whitelist passes through the current process's `TMPDIR`.
- Symptom: MinerU's temp scratch files land in notebook A's tree.
- Mitigation: In `_scrub_subprocess_env()`, override `TMPDIR` to `output_dir`
  (the per-invocation directory, not the inherited process TMPDIR). This limits
  scratch writes to the already-sandboxed output_dir.

**FM-9: Binary resolution — `mineru` not on PATH**
- Trigger: `ARXMCP_MINERU_BIN` unset; `shutil.which("mineru")` returns None
  (common: MinerU is in `~/venvs/mineru/bin/`, not on the project venv's PATH).
- Symptom: `FileNotFoundError` from `subprocess.Popen`; test suite does not skip
  cleanly without the `requires_mineru` guard.
- Mitigation: In `run_mineru_sandboxed`, resolve the binary via
  `ARXMCP_MINERU_BIN` first, then `shutil.which("mineru")`; if both fail, raise
  `RuntimeError` with a clear install message. The `requires_mineru` pytest marker
  must check binary availability at collection time (not at run time) to produce a
  clean skip rather than a hard failure.

**FM-10: MinerU model weights absent from ~/.cache/mineru/**
- Trigger: Fresh workstation; operator runs integration test before `B1` smoke
  test that pre-downloads models.
- Symptom: MinerU makes network egress during subprocess (model download); scrubbed
  env doesn't block network (no firewall rule); download succeeds but violates the
  "no network" contract; OR download fails because no internet access.
- Mitigation: Document in `requires_mineru` marker description that model weights
  MUST be pre-downloaded; add a model-weight presence check to the skip condition.

## Recommendation

**Use the CLI form** (`["mineru", "-p", ..., "-o", ..., "-b", "pipeline", "-m",
"auto"]`) with binary resolution via `ARXMCP_MINERU_BIN` env var. Reasoning: the
CLI is the documented stable interface; the Python `do_parse` API is internal to
the `mineru` package and has already changed between 2.5 and 3.x. The CLI interface
is stable across minor versions. Binary resolution: if `ARXMCP_MINERU_BIN` unset,
use `shutil.which("mineru")` and raise a RuntimeError (not skip) if not found —
that way the `requires_mineru` marker at test collection time is the skip guard,
not a silent missing-binary failure at runtime.

**On RLIMIT_AS:** Implement the preexec_fn with a `sys.platform == "linux"` guard
only (not just "not win32"). On macOS, log a WARNING at module import: "RLIMIT_AS
cap not enforceable on macOS (Darwin); wall timeout is the only memory backstop."
Do NOT use `hasattr(resource, "setrlimit")` as the guard — it's true on Darwin but
the call fails in the child. This contradicts the spike-2 pseudo-code guard but is
the correct behavior given verified live test results.

**On output_dir:** Always override `TMPDIR` in the scrubbed env to `str(output_dir)`
to prevent cross-notebook TMPDIR contamination (FM-8).

**On markdown_path resolution:** Always glob `output_dir/<stem>/<parse_method>/`
after the process exits 0; do NOT hardcode the path. The subdirectory structure
is `output_dir/<pdf_stem>/<parse_method>/<pdf_stem>.md` for pipeline backend.

**On process-group kill for grandchild FastAPI server:** Accept the gap; document
it. The grandchild is loopback-only. A clean implementation note: after SIGKILL,
log the PID of any surviving children if psutil is available, but do not make
psutil a hard dependency.

## Open questions

1. **MinerU stdout tail-truncation size.** 8 KB is a reasonable default (enough
   for error diagnostics). The implementer can pick 4 KB or 16 KB — any small
   bounded value satisfies the requirement. Not a decision that needs orchestrator
   resolution.

2. **`requires_mineru` env var name.** Established precedent: `requires_pdflatex`
   uses `ARXMCP_RUN_REAL_PDFLATEX=1`. For mineru: `ARXMCP_RUN_REAL_MINERU=1`.
   This is not actually open — just needs to follow the pattern.

3. **macOS OOM test feasibility.** The milestone AC says "verify subprocess exits
   with nonzero or signal, NOT a soft hang. If macOS does not enforce hard kill,
   document the gap and defer." Given the verified finding that macOS does NOT
   enforce RLIMIT_AS, the test should be written as: assert that the attempt to
   set RLIMIT_AS in a child produces either (a) the expected OOM kill (Linux path)
   or (b) a documented WARNING on macOS. This resolves Open question #4 in the
   milestone brief — it is answered by the live test: macOS does not enforce.

No open questions that block implementation — the implementer can proceed on the
above recommendations.

## External writes the implementation will require

None — this milestone is purely local. No git push, no GitHub issue, no infra
mutation. All writes are local file creation under `ingest/`, `tests/`,
`pyproject.toml`, and `docs/install.md`. The sandbox profile doc update is to
`.claude/docs/security-pdf-sandbox.md` (local).

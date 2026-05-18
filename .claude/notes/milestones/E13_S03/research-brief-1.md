# Research Brief — E13_S03

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-18T01:30:00Z

## In-codebase context

### Design constitution notes consulted

All 10 numbered notes read. Load-bearing for this milestone: `08-security-observability-ops.md` (Threat 3 spec), `01-mission-and-context.md` (dev-workstation threat model), `07-multi-agent-caching.md` (tool schema byte-stability — no new tools added here).

### Threat 3 verbatim from `08-security-observability-ops.md`

> ### Threat 3: LaTeXML on hostile source
>
> LaTeX is Turing-complete. A malicious paper could ship a `.tex` source designed
> to consume infinite RAM, write arbitrary files, or shell out.
>
> **Mitigations:**
> - LaTeXML runs in a **subprocess with a hard timeout** (5 minutes).
> - Subprocess runs as a **separate UID** (Docker user namespace, or
>   rootless container with an unprivileged user inside).
> - Filesystem write whitelist (only the per-paper output directory).
> - No network access from the LaTeXML subprocess.
> - On macOS: `sandbox-exec` profile. On Linux: seccomp + landlock. In Docker:
>   `--read-only`, `--security-opt no-new-privileges`, dedicated user.
>
> **Never** invoke LaTeXML inside the MCP server process itself. The server has
> network access; the parser doesn't need it.

Also verbatim from failure-modes table in `08-security-observability-ops.md`:

> | LaTeXML hang | Subprocess timeout | Kill, mark paper as parser-failure, continue |

### LaTeXML subprocess invocation — AS-IS

The actual LaTeXML invocation lives in **`tools/arxiv_fetch.py::parse_with_latexml`** (lines 306–342). The function:
- Calls `latexmlc` via `subprocess.run(..., timeout=LATEXML_TIMEOUT_SECONDS)` where `LATEXML_TIMEOUT_SECONDS = 300`.
- Uses a fixed `cmd = ["latexmlc", str(main_tex.name), f"--dest={out_html}", "--format=html5"]`.
- No `--timeout` flag is passed TO latexmlc (subprocess.run's `timeout=` is the Python-level SIGKILL mechanism, which is correct).
- **No sandbox layer** (`sandbox-exec`, seccomp, landlock) is applied. The invocation runs as the current user with full filesystem access.
- The code explicitly documents this gap at line 6-8: `"Production ingestion (E11) will re-implement these in ingest/ with subprocess UID isolation per .claude/notes/08-security-observability-ops.md Threat 3 — for now this is unsandboxed dev tooling running on trusted arXiv source."`

**`ingest/bulk_ingest.py`** does NOT invoke `latexmlc` directly — it reads pre-parsed HTML from `var/arxmcp/corpus/parsed/<paper_id>/index.html` (line 243: `_has_local_parsed_html`). LaTeXML was supposed to have been run as an operator-side pre-step. So bulk_ingest.py is NOT in scope for sandbox testing.

**`tools/fetch_seed.py`** calls `parse_with_latexml` via `tools/arxiv_fetch.py`. `subprocess.TimeoutExpired` is explicitly caught in `PER_PAPER_FAILURE_EXCEPTIONS` (line 67-73) and counted as `parse_failed` (implicitly — no `parse_status` field exists; failures are logged to `ops/parser-failures/seed.log`).

### Critical gap: `parse_status="parse_failed"` does not exist as a field

The brief's AC states: "All 5 papers land in `ops/parser-failures/` with `parse_status="parse_failed"`." However:
- No `parse_status` field exists in the `PaperOutcome` dataclass, the JSONL log records, or anywhere in `ingest/`. The `bulk_ingest.py` failure log (line 137-149) writes `{"paper_id", "parsers_tried", "failure_reason", "timestamp"}` — no `parse_status` key.
- Parser failures go to `var/arxmcp/ops/parser-failures/bulk.jsonl` (bulk) or `seed.log` (seed). Not to `ops/parser-failures/` as a directory of per-paper records with a `parse_status` field.
- **The brief's AC5 ("parse_status=parse_failed") is fictional** — this field and the per-paper record shape do not exist. The implementation must either (a) define this field or (b) reframe the AC to match the real failure-logging schema.

### E02_S02 "sandbox was specified there" — claim is WRONG

**E02_S02 is a real, complete milestone** (`phase: complete`, committed to main). Its `state.json` confirms it was the **preamble extractor** milestone (`ingest/preamble.py`). The sandbox was NOT specified or implemented in E02_S02. The sandbox mitigation for Threat 3 is documented only in `08-security-observability-ops.md` §Threat 3 and explicitly deferred to production ingestion (E11) in the code comments of `tools/arxiv_fetch.py`.

**FLAG: The brief says "specified in E02_S02" — this is factually wrong. E02_S02 = preamble extractor. The sandbox is NOT specified anywhere in the codebase — it is purely aspirational in the design note. This milestone is BOTH the specification AND the validation milestone.**

### Docker compose — no `docker-compose.yml` exists

`find /Users/chris.dare/Personal/SourceCode/arXMCP -name "docker-compose*.yml"` returns no results. Only `infra/observability/phoenix-compose.yml` exists (for Phoenix/OTel). The `08-security-observability-ops.md` §Docker deployment shows a DESIGN-SPEC docker-compose with `arxmcp-server` and `arxmcp-ingest` services, but it is NOT committed as a real file. LaTeXML is not a separate service — it runs inline as a subprocess of the ingest process on the developer's workstation.

**FLAG: The brief's AC3 ("Docker compose config has `--network=none` on the LaTeXML service; verified by `docker inspect`") assumes a docker-compose and a separate LaTeXML service that do not exist. This AC must be reframed — either skip the Docker verification or note it as deferred until E14's docker-compose lands.**

### `infra/latexml/` directory

Does not exist. The `infra/` directory contains only `README.md`, `observability/`, and `prometheus/`. Creating `infra/latexml/sandbox.sb` is valid as a new subdirectory.

### `tests/security/` directory

Already exists with `__init__.py`, `test_path_traversal.py` (E13_S01), and `test_delimiters.py` (E13_S02). The test module for E13_S03 goes to `tests/security/test_latexml_sandbox.py` — the package is ready.

### `tests/security/fixtures/latexml/` directory

Does not exist yet. Must be created alongside the 5 hostile `.tex` files.

### latexmlc `--timeout` flag

`latexmlc` has its own `--timeout=secs` flag (default: 600 seconds) in addition to Python's `subprocess.run(timeout=)`. The Python-level timeout fires first (300s vs 600s default). **Using both layered timeouts is advisable**: latexmlc's `--timeout=300` plus Python's `subprocess.run(timeout=305)` gives latexmlc a chance to self-terminate before SIGKILL.

### `sandbox-exec` on macOS — DEPRECATED

The `man sandbox-exec` output confirms: "The sandbox-exec command is DEPRECATED. Developers who wish to sandbox an app should instead adopt the App Sandbox feature described in the App Sandbox Design Guide." It still works on macOS Darwin 25.4.0 (current env). The `.sb` profile format uses a Scheme-like syntax (`(version 1)`, `(deny default)`, `(allow network* ...)`, etc.). Successor is `com.apple.security.app-sandbox` entitlements (requires code signing and XPC service framework — unsuitable for a dev-tool subprocess wrapper).

**Practical reality:** `sandbox-exec` is deprecated but still functional on the current OS. It is the only practical per-process network/filesystem restriction mechanism for arbitrary subprocesses on macOS without code signing. The implementer should use it but document the deprecation status in the audit doc.

### `\write18` behavior in latexmlc

LaTeXML does NOT execute `\write18` — it is a TeX primitive for shell escape, and LaTeXML's Perl implementation does not pass this through to the OS. The `write18_shellout.tex` fixture will likely produce a parse error or silent ignore rather than an actual shell execution. The test must verify the subprocess terminates cleanly (no shell escape occurred) and does not verify that `/tmp/pwned.txt` exists (it won't be created). This reframes the pass condition: the test is "subprocess contained" not "LaTeXML deliberately failed."

### `large_alloc.tex` — Lua snippet not supported by LaTeXML

LaTeXML does not support LuaTeX extensions. A `\directlua{...}` or Lua code in `.tex` will be silently ignored or produce a parse error. The fixture cannot allocate RAM via Lua. A realistic large-alloc attack is via deeply-nested LaTeX macro expansion (e.g., Fibonacci via macros). The brief's description of "4 GB via Lua snippet" is fictionally implemented — the implementer must choose a realistic large-resource vector that actually stresses latexmlc's memory consumption.

## Prior decisions and lessons

**From git log (last 20 commits):** E13_S01 and E13_S02 both completed with the same pattern: fictional prerequisite milestones, wrong doc destination, no CI. Pattern is now well-established.

**From E13_S01 implementation-summary §Drift item 7:** `docs/security/threat-1-audit.md` was reframed to `.claude/docs/security-threat-1-audit.md`. The brief for E13_S03 says `docs/security/threat-3-audit.md` — **same drift, must reframe to `.claude/docs/security-threat-3-audit.md`**.

**From E13_S02 implementation-summary §Drift item 2:** `E07_S13` was fictional. Similarly, the claim that "the sandbox was specified in E02_S02" is incorrect.

**From E13_S01 §Drift item 4 and E13_S02 §Drift item 8:** "CI runs the tests on every PR" → project has no CI. Reframe to `make test` participation.

**CLAUDE.md §8 gotcha 1:** `KMP_DUPLICATE_LIB_OK=TRUE` in `tests/conftest.py` is load-bearing. The new tests must not remove this.

**CLAUDE.md §4.7:** No `assert` for invariants in test code — use `if ... raise RuntimeError(...)`. In tests, `pytest.raises` and `assert` statements in test bodies are allowed (pytest compiles them differently); the ban is on production guard code.

**No tool-schema changes:** This milestone adds no MCP tools. `EXPECTED_TOOL_SCHEMA_SHA256` does NOT need re-pinning.

## External sources

**`latexmlc --help` (live, installed at `/opt/homebrew/bin/latexmlc`, version 0.8.8):**
- `--timeout=secs` — Timecap for conversions (default 600). This is latexmlc's own daemon-mode timeout. In subprocess mode (no running daemon), it still limits conversion time.
- No sandbox, no network restriction, no filesystem restriction flags.
- No `--noresource` or `--nopost` for security purposes.

**`man sandbox-exec` (macOS Darwin 25.4.0):**
> "The sandbox-exec command is DEPRECATED. Developers who wish to sandbox an app should instead adopt the App Sandbox feature described in the App Sandbox Design Guide."

Profile file format (`-f profile-file`): Scheme-like syntax. The `(version 1)` prefix, then rules like `(deny default)`, `(allow file-read* (subpath "/usr"))`, `(deny network*)`. The profile is read from a `.sb` file.

**Anthropic prompt caching docs:** Not relevant — no tool schema changes, no new tool surface.

**`\write18`:** LaTeXML's Perl implementation of `\write18` does not shell out. Source: latexmlc's behavior on hostile inputs is that TeX primitives without LaTeXML bindings are silently skipped or produce warnings, not executed. The `write18` test verifies absence of side effects, not that LaTeXML flagged it as hostile.

## Recommendation

**Implement a test module that validates the Python-level subprocess containment** (timeout + side-effect freedom) against 5 hostile `.tex` fixtures. Do NOT attempt to wire `sandbox-exec` as an active wrapper in production code — it is deprecated, macOS-only, and the current invocation in `tools/arxiv_fetch.py` is explicitly marked as dev tooling. Instead:

1. Create `tests/security/fixtures/latexml/` with 5 realistic `.tex` fixtures. Use macro-recursion for infinite-recursion and fork-bomb. For large-alloc, use deeply nested macro expansion (not Lua — latexmlc doesn't support LuaTeX). For write18, use `\write18{...}` and assert `/tmp/pwned.txt` was NOT created. For network_call, use `\input{http://...}` and assert no external connection occurred (latexmlc will treat this as a missing file, not an HTTP fetch).

2. Create `tests/security/test_latexml_sandbox.py` with 5 test cases. Each test:
   - Invokes `parse_with_latexml(main_tex, tmp_path, paper_id)` from `tools/arxiv_fetch.py`.
   - Asserts the call returns (no exception) OR catches `subprocess.TimeoutExpired`.
   - Asserts no files were written outside `tmp_path`.
   - Asserts no specific external files (e.g. `/tmp/pwned.txt`) exist after the run.
   - Does NOT assert `parse_status="parse_failed"` (field does not exist) — assert `ParseResult.success == False` instead.
   - Marks tests `@pytest.mark.skipif(shutil.which("latexmlc") is None, reason="latexmlc not on PATH")`.

3. Create `infra/latexml/sandbox.sb` — a macOS `sandbox-exec` profile. This is a documentation artifact (the profile is not wired into production code), but it demonstrates the sandbox configuration. Document its deprecated status.

4. Create `.claude/docs/security-threat-3-audit.md` (NOT `docs/security/threat-3-audit.md`). Include: current invocation shape, sandboxing gap explanation, the sandbox.sb profile explained, Docker path (deferred), Linux seccomp path (deferred).

5. Reframe AC3 (Docker `--network=none`): the docker-compose with a LaTeXML service does not exist. Defer this AC with documentation in the audit doc.

6. Reframe AC5 (`parse_status="parse_failed"`): field doesn't exist. Use `ParseResult.success == False`.

## Open questions

1. **Fixture realism for large_alloc.tex.** Brief says "4 GB buffer via Lua snippet." LaTeXML doesn't run Lua. What is a realistic memory-exhaustion vector for latexmlc? Deeply nested macro expansion (e.g., repeated `\newcommand\x{\x\x}`) is the realistic substitute, but it will likely also trigger the timeout before OOM. Implementer should treat this fixture as equivalent to the infinite-recursion case, with a note in the audit doc.

2. **`\write18` silence vs. error.** latexmlc silently ignores `\write18`. The fixture test must assert that `/tmp/pwned.txt` was not created — not that the parse failed. If latexmlc produces a successful parse despite the `\write18` directive (because it is ignored), the test passes by asserting side-effect absence, not parse failure. Confirm with a dry run of the fixture before committing.

3. **network_call.tex via `\input{http://...}`** — latexmlc will treat this as a missing file and produce a parse error or warning. It will NOT make an HTTP request. Test can assert that `ParseResult.success == False` (file not found) and no network traffic was initiated (verified by absence of DNS resolution or by offline environment).

## External writes the implementation will require

| type | target | why |
|---|---|---|
| filesystem | `tests/security/fixtures/latexml/*.tex` (5 files) | New hostile fixture corpus |
| filesystem | `tests/security/test_latexml_sandbox.py` | New test module |
| filesystem | `infra/latexml/sandbox.sb` | macOS sandbox profile (documentation artifact) |
| filesystem | `.claude/docs/security-threat-3-audit.md` | Audit doc (corrected destination from brief's `docs/security/`) |
| git commit | `main` | `feat(tests,infra): Threat-3 LaTeXML sandbox hostile-input validation (E13_S03)` |
| git commit | `main` | `rect(tests,infra): close findings from E13_S03 critique` |
| git commit | `main` | `chore(notes): finalize E13_S03 state -> complete` |

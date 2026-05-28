# Implementation Summary — textbook-ingest-m5

**Summary:** Sandboxed MinerU 3.2.0 subprocess driver (`ingest/textbook_parser.py`) implementing the layer-2 PDF parsing defense from `.claude/docs/security-pdf-sandbox.md`. Linux-only RLIMIT_AS, process-group kill, scrubbed env with TMPDIR override, configurable wall timeout, MinerUResult dataclass.

**Commit range:** `8dda5ae6..HEAD` (single feat commit + this summary).

## Acceptance criteria status

### Core driver
- [x] `ingest/textbook_parser.py` exposes `run_mineru_sandboxed(pdf_path, output_dir, *, timeout_s=None) -> MinerUResult`.
- [x] `MinerUResult` frozen dataclass with `output_dir`, `markdown_path`, `content_list_path`, `stdout`, `stderr`, `wall_clock_s`.
- [x] RLIMIT_AS 4 GB via `preexec_fn=_set_mineru_rlimits` (Linux-only per research-synthesis §D1 — `sys.platform == "linux"` gate; verified-live macOS gap).
- [x] Default 30-min wall timeout configurable via `ARXMCP_MINERU_TIMEOUT_S` (60–3600; RuntimeError on parse failure or out-of-range, NOT silent clamp).
- [x] Process-group kill via `start_new_session=True` + `os.killpg(SIGKILL)` + drain `communicate(timeout=5)`.
- [x] Scrubbed env: whitelist `(PATH, HOME, LANG, LC_ALL)`; TMPDIR OVERRIDDEN to `str(output_dir)` per §D4 (FM-8 mitigation).

### Invocation form
- [x] CLI form chosen per research-synthesis §Decision 1: `["<mineru_bin>", "-p", pdf, "-o", output, "-b", "pipeline", "-m", "auto"]`.
- [x] Binary resolution: `ARXMCP_MINERU_BIN` → `shutil.which("mineru")` → `RuntimeError` (not silent skip).

### Tests
- [x] `requires_mineru` marker in `pyproject.toml` (mirrors `requires_pdflatex`).
- [x] Unit tests (45 always-run): env parse, binary resolve, env scrub, tail truncation, output locator, run_mineru_sandboxed surface w/ mocked Popen (happy path, env scrub, timeout-killpg, nonzero exit, invalid pdf/output_dir, out-of-range timeout, missing binary, default timeout). Frozen-dataclass regression.
- [x] Integration test (1, `requires_mineru` opt-in): real MinerU on synthetic 1-page PDF generated in-test via pure stdlib (no test-only dep).
- [x] Wall-timeout enforcement test (1, opt-in): expects `subprocess.TimeoutExpired` from cold-cache MinerU under 60s timeout.

### Configuration + docs
- [x] `docs/install.md` documents `ARXMCP_MINERU_BIN`, `ARXMCP_MINERU_TIMEOUT_S`, macOS RLIMIT_AS gap, model-weight pre-download command.
- [x] `pyproject.toml` `[project.optional-dependencies].pdf = ["mineru[pipeline]>=3.2.0,<4"]`.
- [x] `CLAUDE.md §8` entries #9 (macOS RLIMIT_AS) + #10 (MinerU grandchild gap) added.
- [x] `.claude/docs/security-pdf-sandbox.md` updated in lockstep — m4 F2 anti-pattern guard:
  - "MinerU 2.5" → "MinerU 3.2.0" everywhere
  - CLI form updated: `-b pipeline -m auto` flags added
  - `_scrub_subprocess_env` signature: takes `output_dir`, TMPDIR override
  - RLIMIT_AS guard: Linux-only `sys.platform` gate (was `hasattr(resource, "setrlimit")`)
  - Open questions §1-4 closed (resolved by m5/B1)
  - Two new entries in §"explicitly does NOT do": grandchild FastAPI gap + macOS RLIMIT_AS gap
  - Outstanding follow-up: `server/lean_repl.py` audit (separate issue)

### Out-of-scope deferrals — unchanged
- LaTeXML re-rendering (m6)
- Upload route wiring (m6)
- `search_papers` filter (e4)
- Hierarchical chunker (e3)
- CDM bake-off Phase C (blocked on B2 fixture curation)
- Perf optimization beyond B1 baseline (~0.09 pages/sec)
- `sandbox-exec` / seccomp / landlock (deferred per spike-2)

## New / changed test paths

- `tests/test_textbook_parser.py` (NEW; 47 tests, 45 always-run + 2 `requires_mineru` opt-in)

## Files changed (6)

- `ingest/textbook_parser.py` (NEW; ~300 LOC)
- `tests/test_textbook_parser.py` (NEW; ~480 LOC)
- `pyproject.toml` (+12 LOC: `[pdf]` extras + `requires_mineru` marker)
- `docs/install.md` (+44 LOC: MinerU install + env vars)
- `.claude/docs/security-pdf-sandbox.md` (~+45 / −45 LOC: lockstep doc update)
- `CLAUDE.md` (+20 LOC: 2 landmines entries)

## External writes required

None — purely local. `git push` deferred to user authorization at end of pipeline.

## Test counts

- `make test` (ruff + pytest): 2948 passed, 28 skipped, 1 xfailed, **3 failed (pre-existing, environment-only)**.
  - `tests/test_drift_check.py::TestIntegrationRealLatexmlc::*` — `latexmlc` SIGABRT (latexmlc env issue on this machine; pre-existing).
  - `tests/test_tools_all.py::TestToolsSmoke::test_cite_neighbors_wired` — Kùzu graph DB path mismatch (pre-existing E09 stub finding per CLAUDE.md §7).
- New tests delta: +45 always-run, +2 opt-in skip (the `requires_mineru` integration tests run only when `ARXMCP_RUN_REAL_MINERU=1` + `ARXMCP_MINERU_BIN` set).

## Deviations from the brief

None of substance. Two design-time decisions deserved explicit recording in the synthesis:

- **macOS RLIMIT_AS is non-enforceable** (research-brief-2 verified live test). The brief asked researchers to "verify via test, not assumption" — answer is NEGATIVE on Darwin. Implementation gates `_set_mineru_rlimits` on `sys.platform == "linux"`, WARNS on other platforms. Documented in install.md + security-pdf-sandbox.md + CLAUDE.md §8.
- **MinerU 3.x grandchild FastAPI server** (research-brief-2, sourced from `mineru/cli/api_client.py:153`) survives `os.killpg`. Gap is accepted (loopback-only) and documented in security-pdf-sandbox.md §"explicitly does NOT do".

These are findings, not deviations — the brief explicitly framed both as "researchers must resolve" open questions, and the answers shaped the implementation rather than diverging from a fixed design.

## What downstream consumes

The `MinerUResult` dataclass is the contract m6 will consume. `markdown_path` is the LaTeX-flavored markdown MinerU emits; m6's LaTeXML re-render reads from here. `content_list_path` is the structured block-level JSON useful for downstream chunker boundaries (e3).

The driver does NOT touch:
- LanceDB / corpus state (m6 + e3)
- MCP tool surface (e4)
- `search_papers` filters (e4)
- Notebook record (m6 wires the upload route)
- BP1 / cache-stability (no tool-schema change)

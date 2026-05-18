# Implementation Summary — E13_S03

**One-line summary:** Close Threat-3 Phase 1 — process-group kill discipline in parse_with_latexml + 5 hostile fixtures + sandbox profile + Docker isolation config + audit doc.
**Commit range:** b687111..HEAD (pending feat SHA)
**Branch:** main
**Date:** 2026-05-18

## What landed

Closes Threat 3 Phase 1 (LaTeXML sandbox hostile-input validation)
from `.claude/notes/08-security-observability-ops.md` § Threat 3.
Phase 2 (production sandbox-exec / seccomp+landlock wiring) is
deferred to E11 per the audit doc's phasing table.

Pre-milestone audit found:
- **`parse_with_latexml`** lacked process-group kill discipline.
  `subprocess.run(timeout=)` only kills the direct child; Perl
  helpers forked by LaTeXML would survive as orphans.
- **`E02_S02` was real but for a different topic** (preamble
  extractor). The brief's "sandbox was specified in E02_S02"
  claim is factually wrong — same pattern as E07_S12 / E07_S13
  drift in E13_S01 / E13_S02. This milestone is BOTH spec AND
  validation.
- **No `docker-compose.yml` exists at v1.** AC3 ("Docker compose
  config has `--network=none`") tests nonexistent infrastructure.
- **`parse_status` field is fictional.** AC5 reframed to
  `ParseResult.success == False`.
- **2 of 5 fixtures don't actually exercise the named attack**
  against LaTeXML — `\write18` is silently ignored (Perl, not
  pdflatex); `\input{}` of URL is treated as local file. Both
  reframed to test side-effect absence.
- **`large_alloc.tex` Lua snippet doesn't work** — LaTeXML is
  Perl-based, not LuaTeX. Redesigned with deeply-nested math.

## Files changed

| Path | Change | Synthesis ref |
|---|---|---|
| `tools/arxiv_fetch.py` | MODIFIED: `parse_with_latexml` rewrites `subprocess.run` → `Popen(start_new_session=True)` + `communicate(timeout=)` + `os.killpg` on TimeoutExpired. Process-group kill discipline (R2 FM-1) | D1 |
| `tests/security/fixtures/latexml/infinite_recursion.tex` | NEW — macro self-recursion `\def\rec{\rec}\rec` | brief AC1 |
| `tests/security/fixtures/latexml/write18_shellout.tex` | NEW — `\immediate\write18{...}` attempting `/tmp/arxmcp_pwned_e13s03.txt`; tests side-effect absence (LaTeXML doesn't shell out) | brief AC1, FM-3 |
| `tests/security/fixtures/latexml/fork_bomb.tex` | NEW — exponential expansion `\newcommand{\fb}{\fb\fb}\fb`; accepts OOM-kill OR timeout | brief AC1, FM-10 |
| `tests/security/fixtures/latexml/large_alloc.tex` | NEW — deeply-nested math (REDESIGNED from Lua; LaTeXML is Perl-based) | brief AC1, FM-4 |
| `tests/security/fixtures/latexml/network_call.tex` | NEW — `\input{http://...}`; tests no outbound socket egress | brief AC1, FM-5 |
| `tests/security/test_latexml_sandbox.py` | NEW — 15 tests across 4 classes: containment harness (5 fixtures), sandbox profile static validation, Docker config static validation, process-group kill regression guard | D1, FM-7 |
| `infra/latexml/sandbox.sb` | NEW — macOS sandbox-exec profile (deny default, deny network*, file-write* scoped to OUTPUT_DIR + TMPDIR_SUBDIR). Documentation artifact + test fixture; not wired into production code at v1 | D3 |
| `infra/latexml/docker-compose.latexml.yml` | NEW — standalone Docker config documenting network_mode: none + read_only + no-new-privileges + non-root user + cap_drop ALL + memory/CPU caps (AC3 reframe per D2) | D2 |
| `.claude/docs/security-threat-3-audit.md` | NEW operator-internal audit doc with phasing table, per-fixture coverage, defense layers | doc-placement reframe |
| `tests/test_rectifications.py` | MODIFIED — updated `test_nonzero_exit_returns_failure_parseresult` to mock `subprocess.Popen` (was `subprocess.run`); E13_S03 changed the underlying API | regression |

## Drift from brief (deliberate; same pattern as E13_S01 / E13_S02)

1. **Doc placement.** Brief said `docs/security/threat-3-audit.md`.
   CLAUDE.md §1: `docs/` is operator-only. Landed at
   `.claude/docs/security-threat-3-audit.md`.

2. **Fictional prerequisite reframe.** Brief: "sandbox was specified
   in E02_S02." Reality: E02_S02 was the preamble extractor; the
   sandbox is aspirational in note 08 only. This milestone is BOTH
   the specification AND the validation. Same pattern as fictional
   E07_S12 (E13_S01) and E07_S13 (E13_S02).

3. **AC3 (Docker `--network=none` verified by `docker inspect`)
   reframed.** No `docker-compose.yml` exists at v1. Created
   standalone `infra/latexml/docker-compose.latexml.yml` documenting
   the intended config; `TestDockerLatexmlConfig` parses it
   statically. Full `docker inspect` verification deferred to E14.

4. **AC4 ("tested in CI") reframed to `make test`.** Project has no
   CI per CLAUDE.md §4.1.

5. **AC5 (`parse_status="parse_failed"`) reframed to
   `ParseResult.success == False`.** The `parse_status` field is
   fictional — does not exist anywhere in the codebase.

6. **`large_alloc.tex` redesigned.** Brief: "4 GB via custom Lua
   snippet." LaTeXML is Perl-based, not LuaTeX. Redesigned with
   deeply-nested LaTeX math (Perl heap exhaustion).

7. **`write18_shellout.tex` and `network_call.tex` reframed.**
   LaTeXML does NOT pass `\write18` to the shell and does NOT
   follow `\input{URL}` as HTTP. Both fixtures now test side-effect
   absence (no canary file; no outbound socket connection) rather
   than attack-trigger. Documented in fixture file headers + audit
   doc.

8. **`sandbox-exec` not wired into production code.** Synthesis D3:
   sandbox-exec is macOS-only and deprecated. Shipping the profile
   as a documentation artifact + test fixture; production wiring
   deferred to E11. The cross-platform defense E13_S03 ships TODAY
   is the process-group kill discipline.

9. **Process-group kill added to `parse_with_latexml` (NEW from R2 FM-1).**
   Real defense improvement, not just a test artifact. Without
   this, the fork_bomb fixture would leave Perl helpers behind
   after Python timeout fires. ~30 LOC change in
   `parse_with_latexml`.

## Test count delta

* Pre-milestone (post-E13_S02 — d8c9d99..b687111): 1960 passed, 9 skipped, 1 xfailed.
* Post-feat: 1975 passed (+15 net):
  - 5 in `TestLatexmlSandboxContainment` (one per fixture)
  - 4 in `TestSandboxProfile` (file exists, deny default, deny network*, version 1)
  - 5 in `TestDockerLatexmlConfig` (file exists, network_mode: none, no-new-privileges, read_only, non-root user)
  - 1 in `TestProcessGroupKill` (AST-based regression guard)
* `ruff check .` — clean (3 SIM105 errors auto-rewritten to `contextlib.suppress`).

## Acceptance criteria status (reframed from brief)

- [x] **AC1** — `pytest tests/security/test_latexml_sandbox.py` passes.
  15 tests, all 5 fixtures contained. `latexmlc`-dependent tests
  skip cleanly if `latexmlc` not on PATH.
- [x] **AC2** — Each fixture: subprocess terminates within 10 s test
  timeout (production timeout 300 s); no canary at
  `/tmp/arxmcp_pwned_e13s03.txt`; no outbound socket for
  network_call fixture.
- [~] **AC3** — Reframed: `infra/latexml/docker-compose.latexml.yml`
  documents `network_mode: none` + `read_only: true` +
  `no-new-privileges` + non-root user + cap_drop ALL; static-
  validated by `TestDockerLatexmlConfig`. Full `docker inspect`
  verification deferred to E14.
- [~] **AC4** — Reframed: `infra/latexml/sandbox.sb` committed and
  static-validated by `TestSandboxProfile`. Not wired into
  production code at v1 (deferred to E11). Tested via `make test`
  (project has no CI).
- [~] **AC5** — Reframed: `ParseResult.success == False` (the
  `parse_status` field is fictional). Parser failures recorded in
  `var/arxmcp/ops/parser-failures/` per existing schema.

## What this milestone does NOT cover

- **`sandbox-exec` production wiring in `parse_with_latexml`.**
  Deferred to E11 — the current invocation is dev-tooling-only per
  its own docstring; production sandbox wiring should be added
  when the LaTeXML subprocess moves into the production ingest
  pipeline.
- **Linux seccomp + landlock filter.** Deferred to E11.
- **Main `docker-compose.yml` with the LaTeXML service.**
  Deferred to E14 (observability-ops epic).
- **Resource exhaustion at the host level** (cgroup CPU caps,
  memory limits beyond the Docker config). E13_S04 (Threat 4) is
  the dedicated milestone.
- **CVEs in LaTeXML's Perl runtime** that allow code execution
  outside `\write18` / `\input{}` surfaces. Out of scope; covered
  by Threat 6 (dependency pinning) + E13_S06.
- **Threats 4–9.** Each is its own milestone.

## External writes the orchestrator must authorize

**None — purely local.** All deliverables are local file changes
and local commits. `git push` to `origin/main` at end is gated by
the standard Phase 4 user-authorization checkpoint.

## Threat-coverage matrix snapshot

After E13_S03:

| Threat | Status |
|---|---|
| 1. Path traversal via paper_id | ✅ E13_S01 |
| 2. Indirect prompt injection | ✅ E13_S02 |
| 3. LaTeXML sandbox hostile input (Phase 1) | ✅ E13_S03 |
| 4. Resource exhaustion | ⏳ E13_S04 |
| 5. Origin spoofing / DNS rebinding | ⏳ E13_S05 (partial — Origin/Host shipped in E06_S05) |
| 6. Model SHA pinning / safetensors | ⏳ E13_S06 (partial — BGE-M3 SHA pinned) |
| 7. Source ingestion TLS | ⏳ E13_S07 |
| 8. Log redaction | ⏳ E13_S08 |
| 9. Localhost binding regression test | ⏳ E13_S09 |

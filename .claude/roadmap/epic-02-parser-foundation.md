# E02 — Parser Foundation (Tier 1a)

**Epic dependencies:** E01.

**Goal:** replace the hand-driven LaTeXML invocation from Tier 0 with a real parser fallback chain — ar5iv HTML cache (primary), local LaTeXML (cache miss), Nougat (last resort), skip-and-log (failure). Wire in the per-failure logging that drives the weekly degraded-coverage review.

**Effort:** 1–2 weeks calendar.

**References:** `04-parsing-and-chunking.md` § Parser fallback chain, § Failure modes during parsing; `03-ingestion-pipeline.md` § Source 6 (ar5iv); `08-security-observability-ops.md` Threat 3 (LaTeXML on hostile source — sandbox required).

---

### E02_S01 — ar5iv HTTP client with on-disk cache

**Description.** Build the primary parser path: an HTTP client that fetches `https://ar5iv.labs.arxiv.org/html/<arxiv_id>` (and falls back to the successor `https://arxiv.org/html/<arxiv_id>`), caches the body keyed by `arxiv_id` under `var/arxmcp/cache/ar5iv/`, and returns the cached HTML on subsequent calls. Per `03-ingestion-pipeline.md` § Source 6, this saves weeks of CPU on the initial corpus pass.

**Acceptance criteria.**
- [ ] `ingest/parsers/ar5iv.py` exposes `fetch(arxiv_id) -> ParsedHTML | NotFound`.
- [ ] Cache key is `arxiv_id` (no version suffix at this layer); responses written atomically (`.tmp` then rename).
- [ ] On 404, returns `NotFound` (not an exception) so the fallback chain can advance.
- [ ] On 5xx, retries with exponential backoff (max 3 retries, max 30 s).
- [ ] `User-Agent` header is `arXMCP/0.1 (mailto:<configurable>)` per arXiv TOS politeness.
- [ ] Unit test with a recorded HTTP fixture (vcrpy or similar) for the 200 and 404 paths.

**Dependencies.** none (within E02; depends on E01 being complete).

**Complexity.** M.

**Labels.** `area:parser`, `kind:feature`.

---

### E02_S02 — Local LaTeXML subprocess wrapper with hard timeout

**Description.** Run LaTeXML as a subprocess on `/e-print/` source per `04-parsing-and-chunking.md` § Parser fallback chain step 2. The subprocess must be sandboxed: hard timeout (5 minutes), no network access, filesystem write whitelist to the per-paper output directory only. This is a critical Threat 3 mitigation from `08-security-observability-ops.md`.

**Acceptance criteria.**
- [ ] `ingest/parsers/latexml.py` exposes `run(source_dir, output_dir) -> ParsedHTML | LaTeXMLFailure`.
- [ ] Subprocess uses `subprocess.run(..., timeout=300, env={"PATH": ...}, cwd=source_dir)`.
- [ ] On timeout, the subprocess group is killed (`os.killpg`) and the failure recorded.
- [ ] Subprocess runs as a dedicated unprivileged UID inside Docker; documented in `infra/Dockerfile.ingest`.
- [ ] Subprocess has no network access (verified via `--network=none` on Docker, or seccomp on Linux host).
- [ ] On macOS, fallback uses `sandbox-exec` profile committed under `infra/sandbox/latexml.sb`.
- [ ] Unit test: malformed `.tex` exits cleanly with `LaTeXMLFailure`, no orphan processes.

**Dependencies.** E02_S01.

**Complexity.** L.

**Labels.** `area:parser`, `area:security`, `risk:high`.

---

### E02_S03 — Nougat last-resort parser wrapper

**Description.** Ship a Nougat invocation path per `04-parsing-and-chunking.md` § Parser fallback chain step 3. Nougat runs on the PDF (fetched from arXiv if needed) and emits markdown+LaTeX. Confidence is lower; results are tagged so downstream layers can demote them. Note Nougat is "largely unmaintained as of late 2024" — keep the integration thin and easy to swap for Marker if needed.

**Acceptance criteria.**
- [ ] `ingest/parsers/nougat.py` exposes `run(pdf_path) -> ParsedMarkdown | NougatFailure`.
- [ ] Wrapper detects GPU and falls back to CPU with a logged warning.
- [ ] Heuristic equation-count check: if `equation_count > pdf_pages * 30`, demote confidence to "low" (per `04-parsing-and-chunking.md` § Failure modes "Nougat hallucinated equation indices").
- [ ] Returned object includes a `confidence` enum (`high | medium | low`).
- [ ] Wrapper sandbox parity with E02_S02 (no network, FS whitelist, timeout).
- [ ] Documented swap path for Marker (`https://github.com/VikParuchuri/marker`) in module docstring.

**Dependencies.** E02_S02.

**Complexity.** M.

**Labels.** `area:parser`, `kind:feature`.

---

### E02_S04 — Parser fallback chain orchestrator

**Description.** Wire the three parsers (ar5iv → LaTeXML → Nougat → skip) into a single function that takes an arxiv ID and returns a `ParsedPaper` or marks it as a parser-failure. Failures route to `var/arxmcp/ops/parser-failures/<arxiv_id>.json` with structured cause data per `04-parsing-and-chunking.md` § Failure modes.

**Acceptance criteria.**
- [ ] `ingest/parsers/__init__.py` exposes `parse(arxiv_id) -> ParsedPaper | ParserFailure`.
- [ ] Order: ar5iv → LaTeXML local → Nougat → skip-and-log, exactly as `04-parsing-and-chunking.md` § Parser fallback chain prescribes.
- [ ] On each fall-through, a structured log line records which parser was tried and why it failed.
- [ ] On all-parsers-failure, a JSON record is written to `parser-failures/` with fields `{arxiv_id, attempted: [...], errors: [...], timestamp}`.
- [ ] Returned `ParsedPaper` carries `parser_used` ∈ `{ar5iv, latexml_local, nougat}` and `confidence` ∈ `{high, medium, low}`.
- [ ] Integration test: one paper that ar5iv 404s, LaTeXML accepts, returns a `ParsedPaper` with `parser_used="latexml_local"`.

**Dependencies.** E02_S01, E02_S02, E02_S03.

**Complexity.** M.

**Labels.** `area:parser`, `kind:feature`.

---

### E02_S05 — Source-tarball corruption handling and re-fetch

**Description.** Per `04-parsing-and-chunking.md` § Failure modes "Source tarball corrupt": detect malformed/truncated `.tar.gz`, re-fetch once from `/e-print/`, and only then mark as failure. Avoids spurious failures when an arXiv mirror serves a half-baked response.

**Acceptance criteria.**
- [ ] `ingest/parsers/source.py` exposes `fetch_source(arxiv_id, max_retries=1) -> SourceTarball | SourceFailure`.
- [ ] On `tarfile.ReadError` or non-`.tar.gz` content, the cached file is deleted and re-fetched once.
- [ ] After one re-fetch, persistent failure is final.
- [ ] Re-fetch honors the same 3-second-per-IP politeness rule as E01_S03.
- [ ] Test fixture: a truncated tarball file triggers exactly one re-fetch.

**Dependencies.** E02_S04.

**Complexity.** S.

**Labels.** `area:ingestion`, `kind:infra`.

---

### E02_S06 — Parser-failure aggregation and weekly report scaffolding

**Description.** Per `04-parsing-and-chunking.md` § Failure modes — "weekly review of failures drives parser improvements" — emit a script that summarizes the last 7 days of `parser-failures/*.json` into a markdown report (counts by parser, top-N error messages, sample arxiv IDs) and writes it to `var/arxmcp/ops/reports/parser-failures-<date>.md`. Run via cron in E14; this issue ships the script.

**Acceptance criteria.**
- [ ] `tools/parser_failures_report.py` reads JSON records from `parser-failures/` filtered by mtime in the last 7 days.
- [ ] Report includes total count, breakdown by parser used (`ar5iv | latexml_local | nougat | none`), top 10 error patterns, and 5 sample failing arxiv IDs per category.
- [ ] Report file is markdown, written atomically.
- [ ] Output is deterministic for a fixed input (sorted lists, no timestamps in the body).
- [ ] Unit test fixture: 12 mock failure JSONs produce a stable report.

**Dependencies.** E02_S04.

**Complexity.** S.

**Labels.** `area:observability`, `kind:infra`.

---

### E02_S07 — Banned-parser CI guard

**Description.** Per `04-parsing-and-chunking.md` § Tools we considered and rejected — pure `pypdf`, `pymupdf`, `pdfplumber` are banned from the parser chain because they mangle math. Add a CI lint that fails the build if any non-test, non-metadata-fallback module imports these libraries.

**Acceptance criteria.**
- [ ] `tools/lint_banned_imports.py` greps `ingest/parsers/` and `server/` for `import pypdf`, `import pymupdf`, `import fitz`, `import pdfplumber`.
- [ ] Allow-listed locations: `ingest/metadata_fallback.py` only (if/when it exists).
- [ ] Script exits non-zero on any unauthorised import.
- [ ] Wired into `pyproject.toml` test target / pre-commit.
- [ ] README note explains the rationale + cites `04-parsing-and-chunking.md`.

**Dependencies.** E02_S04.

**Complexity.** S.

**Labels.** `area:parser`, `kind:infra`.

---

### E02_S08 — Bounded recursion guard for macro expansion infinite loops

**Description.** Per `04-parsing-and-chunking.md` § Failure modes "Macro expansion infinite loop": LaTeXML macro expansion can recurse unboundedly on adversarial input. Add a max-depth guard (50) inside the LaTeXML wrapper config; on hit, mark paper as degraded.

**Acceptance criteria.**
- [ ] LaTeXML invocation includes a configurable `--max-recursion-depth` flag (or wrapper-side enforcement when LaTeXML lacks the flag).
- [ ] On hit, the `ParsedPaper.confidence` is set to `low` and a structured log records the trigger.
- [ ] Test fixture: a synthetic `.tex` with `\newcommand{\X}{\X}` triggers the guard and exits within 5 s, not 5 minutes.
- [ ] Counter `arxmcp_parser_recursion_guard_total` is incremented (Prometheus metric scaffold; full wiring in E14).

**Dependencies.** E02_S02.

**Complexity.** S.

**Labels.** `area:parser`, `area:security`.

---

### E02_S09 — Parsed-IR persistence and idempotent re-parse

**Description.** Persist parsed papers as `var/arxmcp/corpus/parsed/<paper_id>.html` (HTML5 + MathML) plus `<paper_id>.meta.json` (parser_used, confidence, parser_version). Re-parsing a paper whose source is unchanged should be a no-op. This is the boundary the chunker (E04) reads from.

**Acceptance criteria.**
- [ ] `parse(arxiv_id)` writes `parsed/<paper_id>.html` and `parsed/<paper_id>.meta.json` atomically.
- [ ] If a `meta.json` already exists with a matching `source_sha256`, the parser short-circuits and returns the cached IR.
- [ ] `parser_version` is part of the meta record and bumped when E02 code changes meaningfully.
- [ ] Test: calling `parse(id)` twice in a row is idempotent and the second call is <100 ms.
- [ ] Test: bumping `parser_version` invalidates the short-circuit on next run.

**Dependencies.** E02_S04, E02_S05.

**Complexity.** M.

**Labels.** `area:parser`, `kind:feature`.

---

### E02_S10 — Re-run E01 seed corpus through the parser chain

**Description.** Smoke-test the new fallback chain on the 50-paper seed from E01_S03. Expect ar5iv to cover the majority; LaTeXML to cover the rest; ≤5 papers to land in `parser-failures/`. Compare to the E01_S03 baseline to ensure no regression.

**Acceptance criteria.**
- [ ] All 50 seed papers re-parsed via `parse(arxiv_id)`.
- [ ] ≥45 papers complete with `confidence=high`.
- [ ] Per-parser-used distribution recorded in a checked-in `var/arxmcp/ops/seed-parse-stats.json` (committed for posterity).
- [ ] No paper takes >5 minutes wall clock.
- [ ] Differences vs. E01 baseline (papers that previously parsed but now fail, or vice versa) are listed in `docs/tier-1a-parse-diff.md`.

**Dependencies.** E02_S04, E02_S09.

**Complexity.** S.

**Labels.** `area:parser`, `kind:research`.

---

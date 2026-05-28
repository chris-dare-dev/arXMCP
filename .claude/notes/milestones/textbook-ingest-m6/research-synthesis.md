# Research Synthesis — textbook-ingest-m6

**Orchestrator merge** of `research-brief-1.md` (in-codebase focus) and
`research-brief-2.md` (external + failure-mode focus).

**Both researchers AGREE on:**
- **Background task mechanism:** reuse the existing `IngestTaskTracker` pattern from `server/ingest_tracker.py` (`asyncio.create_task` + `asyncio.Semaphore(1)` + lifespan-aware shutdown). NOT FastAPI's `BackgroundTasks` — researcher-2 verified that `BackgroundTasks` does not hook into the Starlette lifespan, so server shutdown abandons in-flight tasks without DB update.
- **Concurrency policy:** **serialize via Semaphore(1)**. GPU/MLX memory pressure on Apple Silicon is the binding constraint; two concurrent MinerU invocations risk OOM on the lower-end M-series hardware.
- **Server-restart recovery:** implement `mark_orphaned_parses_failed()` mirroring the existing `NotebooksStore.mark_orphaned_runs_failed()` at line 467. Run in lifespan startup to flip any stuck `parse_status='running'` rows to `failed`.
- **MinerU output_dir retention:** retain the raw MinerU output tree (debug PDFs, JSONs, images/) under `var/arxmcp/notebooks/<slug>/parsed/<flat_paper_id>/`. No auto-cleanup.
- **HTML5 output:** `<!DOCTYPE html>`, `text/html; charset=UTF-8`, minimal `<head>` (title from PDF filename, generator meta tag). NO MathJax CDN script — local-first constraint; LaTeXML emits native MathML readable by modern browsers without JS. Matches the existing ar5iv precedent verified by researcher-2 at `var/arxmcp/corpus/parsed/1510.04089/index.html`.
- **textbook_id derivation:** `flat_paper_id = paper_id.replace("/", "_").replace(":", "_")` per the existing upload handler convention at `server/routes/notebooks.py:882`.
- **Atomic write:** `index.html.tmp` → `os.replace()`. Matches m8 precedent at the upload handler line 888-890.
- **BP1 cache-stability:** **no re-pin needed.** The new `parse_status` columns are on the `notebooks` SQLite table, not on `chunks` (LanceDB) or `ALL_TOOLS` (server/tools.py). `EXPECTED_TOOL_SCHEMA_SHA256` does not drift; `TOOL_SCHEMA_VERSION` stays at 13.
- **Notebook schema bump 3→4:** ADDITIVE `ALTER TABLE` only — never DROP+RECREATE (would lose operator data).
- **External writes:** zero. Purely local milestone.

**They DISAGREE on one major axis: rendering strategy.** Orchestrator resolves below.

---

## D1 (LOAD-BEARING) — Rendering strategy: A vs C

**Disagreement:**

- **Brief-1 (Strategy C):** Use `markdown-it-py` (claimed transitive via `transformers`) for prose → HTML; per-block `latexmlmath` for math. Argues `latexmlc` cannot consume markdown without a full markdown→LaTeX preprocessor.
- **Brief-2 (Strategy A):** Wrap MinerU markdown in a minimal `\documentclass{article}\begin{document}…\end{document}` envelope; pass to `latexmlc` once. Argues LaTeXML is tolerant of non-LaTeX text and recovers per-equation on errors.

**External-source verifications that decide this:**

1. **Researcher-2's live test on latexmlmath:** "Each call takes ~1s cold start (Perl startup overhead). For a 500-page textbook with potentially thousands of equations, this serializes to hours. Strategy B/C are operationally infeasible." → CRITICAL throughput finding for C.

2. **Researcher-2's grep of `pyproject.toml`:** "Neither [markdown-it-py nor mistune] is in `pyproject.toml` (zero matches)." → C requires either adding a new direct dep OR depending on a transitive chain. The `markdown-it-py` package may or may not be present in the current lock depending on the transformers version churn (the m5 rect oscillated between v4 and v5; v4 brought markdown-it-py transitively, v5 may have dropped it). **Relying on transitive deps for project-functional code is a known anti-pattern** — researcher-1's claim is fragile.

3. **MinerU markdown shape (from B1 smoke-test artifact at `/tmp/mineru-smoke-direct/.../milne-introduction-to-shimura-varieties.md`):** Math is embedded inline in prose blocks as `$...$` / `$$...$$` strings, NOT as discrete `type:equation` blocks. Strategy B (the original brief option) is **dead** — researcher-2 verified `content_list.json` has zero equation blocks. Strategy C still works but only by regex-extracting math from markdown text (no advantage over A in that case).

4. **LaTeXML error recovery (from researcher-2):** "Under Strategy A, `latexmlc` processes the whole document with error-recovery semantics — individual equation failures get `<math class="ltx_ERROR">` annotations in the output, NOT a total failure. The existing `parse_with_latexml` helper in `tools/arxiv_fetch.py` uses exactly this discipline." → A's worst case is graceful degradation; C's worst case is a 1000-subprocess serial chain.

**Resolution: Strategy A wins.**

But with one explicit acknowledgment of researcher-1's concrete concern: `latexmlc` is a LaTeX compiler, NOT a markdown parser. Markdown prose constructs (`## Section`, `**bold**`, `[link](url)`, bullet lists, etc.) WILL render as literal characters in the HTML output. **This is acceptable for v1** because:
- The project's mission per `01-mission-and-context.md` is math-aware retrieval, not visual presentation. The math renders correctly as MathML; that is the load-bearing requirement.
- Operators viewing the HTML get readable math + literal-character prose — usable, not pretty. m7 (a future milestone) can add a markdown pre-processor if presentation matters.
- The chunker (e3) consumes math blocks and structural metadata via `content_list.json`, NOT prose layout from `index.html`. So prose-render imperfection is invisible at the retrieval layer.

**Implementation:**
- New module `ingest/textbook_renderer.py` with public function `render_mineru_to_html(result: MinerUResult, parsed_dir: Path, paper_id: str) -> RenderResult`.
- Internally: read `result.markdown_path`; construct a minimal LaTeX envelope (`\documentclass{article}\usepackage{amsmath,amssymb}\begin{document}\n<markdown>\n\end{document}\n`); write to a temp `.tex` file in `parsed_dir / flat_paper_id /`; call `tools/arxiv_fetch.py::parse_with_latexml(main_tex, parsed_dir, paper_id)`; copy MinerU's `images/` dir alongside the resulting `index.html`.
- `RenderResult` frozen dataclass: `output_html_path: Path`, `wall_clock_s: float`, `stdout_tail: str`, `stderr_tail: str`, `latex_error_annotations: int` (count of `<math class="ltx_ERROR">` tags found post-render; emits as a quality metric).
- Subprocess discipline inherited from `parse_with_latexml` (which already mirrors `_run_subprocess_with_pgkill`).

**Document in commit body** that Strategy A's prose-rendering is best-effort (literal markdown chars survive); operator-facing implications captured in `.claude/docs/security-pdf-sandbox.md` lockstep update.

---

## D2 (MEDIUM) — `parse_status` column DEFAULT semantics

**Disagreement (raised by researcher-1):**

- The brief states `parse_status TEXT NOT NULL DEFAULT 'pending'` AND "arxiv-kind notebooks land with `parse_status='skipped'`". These are incompatible: a single column-level default backfills ALL existing arxiv rows as `'pending'`.

**Resolution: brief-1 correct.**

Column-level: `ALTER TABLE notebooks ADD COLUMN parse_status TEXT NOT NULL DEFAULT 'skipped'`. Then the create-notebook route handler EXPLICITLY sets `parse_status='pending'` when inserting a textbook-kind row. Existing arxiv rows backfill to `'skipped'` correctly.

Same logic for `parse_error` and `parsed_html_path` (both default `''`).

---

## Open questions (after synthesis)

All milestone-brief open questions resolved above. One residual:

**Residual-1 (acceptable to resolve at impl time):** Does `latexmlc` need a special flag to handle markdown's `#` headers and `*` emphasis chars gracefully, or do we just let them render as literal characters? **Decision: let them render literal.** No flag tuning. This is part of the "Strategy A prose-rendering is best-effort" acknowledgment.

Both researchers also flagged the `markdown-it-py` dependency status as fragile. The synthesis decision (Strategy A) avoids the dep entirely — no markdown library added.

---

## Failure-mode coverage summary (from researcher-2, all 8 carried forward)

| ID | Trigger | Mitigation chosen |
|---|---|---|
| FM-1 | MinerU emits garbled markdown | LaTeXML error recovery + log stderr tail |
| FM-2 | LaTeXML fails on specific equation | Strategy A's `<math class="ltx_ERROR">` annotation — recorded as `latex_error_annotations` count |
| FM-3 | Two concurrent textbook uploads | Semaphore(1) global cap via `ParseTaskTracker` |
| FM-4 | Server restart mid-parse | Lifespan startup sweep `mark_orphaned_parses_failed(cutoff_iso)` |
| FM-5 | `flat_paper_id` collision (textbook:my-book vs textbook:my_book) | Documented limitation; namespaced under per-notebook `var/arxmcp/notebooks/<slug>/parsed/` so cross-notebook collision impossible; intra-notebook collision is operator error (would already collide on PDF upload at `pdfs/<flat>.pdf`). Defer to future milestone. |
| FM-6 | Broken `<img>` refs (no images extracted) | Copy MinerU's `images/` dir alongside `index.html`; broken refs are non-failures per v1 |
| FM-7 | Disk-space exhaustion mid-render | `ENOSPC` in error path → `parse_status='failed'` + parse_error="disk full"; cleanup `.tmp` |
| FM-8 | SQL injection via slug | `validate_slug(slug)` at route boundary + sqlite3 parameterized queries |

---

## Orchestrator synthesis note — load-bearing decisions

1. **Strategy:** A — wrap MinerU markdown as a minimal LaTeX document and pass through `tools/arxiv_fetch.py::parse_with_latexml`. Prose rendering is best-effort (literal markdown characters survive); math renders as MathML. Operator-facing implication: HTML5 output is for retrieval-grounded indexing, not visual presentation.
2. **Background task:** `ParseTaskTracker` in `server/parse_tracker.py` mirroring `IngestTaskTracker`. `asyncio.create_task` on `app.state.parse_tracker`. Global `Semaphore(1)`. DB row created BEFORE task dispatch (m9 FM-7 closure pattern). Wired into lifespan.
3. **Concurrency:** Serialize. Single MinerU + LaTeXML at a time across all notebooks.
4. **Restart recovery:** `mark_orphaned_parses_failed()` in `NotebooksStore`, called from lifespan startup. Same shape as the m9 ingest-runs equivalent.
5. **Output retention:** Keep the raw MinerU output tree under `var/arxmcp/notebooks/<slug>/parsed/<flat_paper_id>/auto/`. `index.html` lives at `var/arxmcp/notebooks/<slug>/parsed/<flat_paper_id>/index.html` (alongside, not nested).
6. **HTML5 wrapper:** `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{stem}</title><meta name="generator" content="arXMCP/m6/mineru+latexml"></head><body>` + LaTeXML output + `</body></html>`. No MathJax. `text/html`, not `application/xhtml+xml`.
7. **textbook_id:** `flat_paper_id = paper_id.replace("/", "_").replace(":", "_")` per existing convention.
8. **Atomic write:** `index.html.tmp` + `os.replace()`.
9. **Schema bump 3→4:** `ALTER TABLE notebooks ADD COLUMN parse_status TEXT NOT NULL DEFAULT 'skipped'`. Plus `parse_error TEXT NOT NULL DEFAULT ''`, `parsed_html_path TEXT NOT NULL DEFAULT ''`. Route handler explicitly sets `parse_status='pending'` for textbook-kind inserts.
10. **BP1:** no re-pin needed (verified by both researchers).
11. **Lockstep doc update mandatory:** `.claude/docs/security-pdf-sandbox.md` must document the new latexmlc invocation as a peer subprocess to the MinerU sandbox profile. m4 F2 + m5 F2 anti-pattern guard — DO NOT SKIP this.

---

## External writes the implementation will require

| type | target | why | blocking? |
|---|---|---|---|
| (none) | | | |

Purely local. All deliverables land in the working tree:
- `ingest/textbook_renderer.py` (new)
- `server/parse_tracker.py` (new — mirrors `server/ingest_tracker.py`)
- `server/notebooks_store.py` (schema v3→v4 + `mark_orphaned_parses_failed`)
- `server/routes/notebooks.py` (upload handler dispatches to ParseTaskTracker for textbook; new `/parse-status` route)
- `server/main.py` (wire `ParseTaskTracker` in lifespan)
- `tests/test_textbook_renderer.py` (new)
- `tests/test_parse_tracker.py` (new)
- `tests/test_notebooks_routes.py` (extend existing)
- `tests/test_notebooks_store.py` (extend existing — schema migration test)
- `.claude/docs/security-pdf-sandbox.md` (lockstep update)
- `docs/install.md` (parse-status endpoint + async behavior documentation)

No `git push`. No GitHub issue. No infra mutation.

---

## Size estimate

- `ingest/textbook_renderer.py`: ~150 LOC
- `server/parse_tracker.py`: ~250 LOC (mirrors ingest_tracker)
- `server/notebooks_store.py` edits: ~80 LOC (migration + 3 new methods)
- `server/routes/notebooks.py` edits: ~100 LOC (handler extension + new /parse-status route)
- `server/main.py` edits: ~15 LOC (lifespan wiring)
- Tests: ~600 LOC across 4 test files
- Doc updates: ~50 LOC

**Total: ~1245 LOC across 10 files.** This is squarely in the **DELEGATED** path per the milestone-pipeline decision tree (≥ 500 LOC AND ≥ 5 files). BUT:

There is NO clean two-part partition. Every piece is interlocked — the renderer needs the tracker; the tracker needs the schema migration; the schema migration needs the route handler; etc. Splitting along file boundaries would create merge pain.

**Recommendation: INLINE despite size.** The work is one coherent module-family (textbook ingest end-to-end) and the alternative is a delegated pair where each half hits the same touchpoints. INLINE preserves the coherent commit; the size is justified by the milestone's "value-type" closure-of-epic semantics. The implementer's outer test loop catches any incoherence — 1 commit, then test, then rect.

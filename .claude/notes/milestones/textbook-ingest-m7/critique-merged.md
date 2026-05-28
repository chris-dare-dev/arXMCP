# Critique — textbook-ingest-m7

**Critic:** adversary
**Generated:** 2026-05-28T00:00:00Z
**Commit range:** 03bdcbe..1656ec6
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the chunker spine is correct on the common path (golden fixture, dedup, cross-chapter pairing, chunk-id round-trip, resilience all verified green), but two latent chapter-label correctness foot-guns and a defense-in-depth regression should be closed before e4 surfaces these chunks.
- 0 CRITICAL, 0 HIGH, 3 MEDIUM, 2 LOW.
- Highest-risk: `ingest/textbook_chunker.py:150-167` (`_section_title_text` recursive fallback) — a chapter heading lacking `ltx_title` mislabels chunks with a nested SECTION title as their `chapter`.
- Axis 1 (cache byte-stability), Axis 4 (MCP), Axis 5 (local-first), Axis 6 (tier sequencing), Axis 7 (no-fork) all axis-verified clean — no `server/`, `pyproject.toml`, `uv.lock`, `conftest.py`, or tool-schema touch; no `write_chunks` call.
- The golden test is NOT a tautology: structural assertions (`test_six_chunks`, `test_chunk_kinds`, `test_chapter_labels_populated`, `test_cross_chapter_pairing_terminates`) assert against hand-written constants, providing real independent coverage.
- The dedup test (FM-4) is NOT too weak: simulated, removing the dedup loop makes the returned list carry two same-id section chunks → `len(ids)=1 != 2` fails the assertion. Verified clean.
- `assert` ban clean (no `assert` in source); `_extract_section_chunks(soup,...)` / `_extract_chunks_from_container(root,...)` call pattern matches `_chunk_paper_impl` exactly; `flat_paper_id` collision not reachable (slug regex forbids `_`).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Cross-critic agreement

_None — no file:line region was flagged by ≥ 2 critics._

<!-- end:cross-critic-agreement -->

## Findings

### F1 — Chapter heading without ltx_title mislabels chunks with section title

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/textbook_chunker.py:161-167
- **What:** `_section_title_text` first tries `section_tag.find(True, class_=_has_ltx_title, recursive=False)`, then falls back to a RECURSIVE `section_tag.find(True, class_=_has_ltx_title)`. When an `ltx_chapter` element's own heading lacks the `ltx_title` class (some LaTeXML configs emit `ltx_title_chapter` only, or wrap the heading differently), the recursive fallback descends into the chapter's first nested `ltx_section` and returns the SECTION's title. Empirically confirmed: a chapter `<h2 class="ltx_chapter_heading">` + nested `<h3 class="ltx_title ltx_title_section">1.1 Nested Title</h3>` yields `_collect_chapter_titles(soup) == {"1.1 Nested Title"}`.
- **Why it matters:** `_collect_chapter_titles` then holds a SECTION title masquerading as a chapter title. `_chapter_for_chunk` (`:200-203`) matches any `section_path` breadcrumb against that set, so a section chunk gets `chapter="1.1 Nested Title"` — a section label stamped into the `chapter` field. Violates the m7 contract ("`chapter` = chapter breadcrumb"). The arXiv `_extract_section_path` has the same recursive fallback (chunker.py:397) but it is bounded to ancestors of a deep element, never the chapter element itself, so the divergence is m7-specific (m7 calls `_section_title_text` ON the chapter element directly via `_collect_chapter_titles`).
- **Proposed fix:** In `_section_title_text`, drop the recursive fallback (or scope the recursive `find` to stop at the first nested `_SECTION_DIV_CLASSES` element). For the chapter case, prefer matching the title element that itself carries `ltx_title_chapter` when present:
  ```python
  # in _collect_chapter_titles, match the chapter-specific title class first
  def _has_chapter_title(c): return isinstance(c, str) and "ltx_title_chapter" in c.split()
  t = el.find(True, class_=_has_chapter_title, recursive=False) or _section_title_text(el)
  ```
- **Regression guard:** Add a `_collect_chapter_titles` unit feeding a chapter whose `<h2>` lacks `ltx_title` but whose nested section has `ltx_title ltx_title_section`; assert the section title is NOT in the returned set.

### F2 — Two chapters with identical title text are indistinguishable by `chapter`

- **Severity:** MEDIUM
- **File:** ingest/textbook_chunker.py:170-188
- **What:** `_collect_chapter_titles` returns a `set[str]`; two `ltx_chapter` elements with the same title text (e.g. both `"Introduction"` or `"Preliminaries"`, plausible in multi-part textbooks/lecture notes) collapse to ONE set entry. Empirically confirmed: two chapters both titled `Introduction` → `_collect_chapter_titles == {"Introduction"}`. Both chapters' chunks then resolve `chapter="Introduction"`.
- **Why it matters:** Chunks from two genuinely distinct chapters become indistinguishable on the `chapter` field. At e4, an operator filtering or grouping by `chapter` cannot separate them; the field stops being a faithful chapter discriminator. Not data loss (chunk-ids are still content-addressable + unique), but a correctness foot-gun on a realistic input class.
- **Proposed fix:** v0-acceptable mitigation: document the limitation in the module docstring AND in `.claude/docs/textbook-chunker-fixtures.md` "v0 scope reminders" (label-only, not an ID; identical titles collapse). A fuller fix (qualify the label with chapter ordinal / element id) is m8 scope — record there. If fixing now, prefer the doc note (cheap) over a positional rewrite (>30 LOC, larger blast radius).
- **Regression guard:** Add a `_collect_chapter_titles` unit with two same-text chapters asserting current behavior (one entry) so the limitation is pinned, not silent; flip the assertion when m8 disambiguates.

### F3 — chunk_textbook omits the notebook_dir symlink/containment guard

- **Severity:** MEDIUM
- **File:** ingest/textbook_chunker.py:238-242, 104-119
- **What:** `chunk_textbook` validates the slug via `validate_slug(slug)` (the regex — primary defense) but then builds paths directly from `NOTEBOOKS_BASE / slug / ...` in `_textbook_html_path`, `_textbook_chunks_dir`, `_textbook_chunk_log_path`. Every other m6 notebook tool (`notebook_init.py:87-88`, `notebook_fetch.py:100-101`, `notebook_ingest.py:70-71`, `notebook_purge.py:182-183`) pairs `validate_slug(slug)` with `notebook_dir(slug)`, which adds the belt-and-braces symlink-refusal + `.resolve()`-containment check that closed F3 of the m6 critique.
- **Why it matters:** The slug regex makes path traversal unreachable, so this is not an exploitable hole — it is a defense-in-depth REGRESSION against the established m6 pattern. If a `var/arxmcp/notebooks/<slug>` directory were pre-created out-of-band as a symlink (the exact red flag m6's F3 blocks), the textbook chunker would happily read/write through it where the m6 tools refuse. Inconsistent posture across the notebook surface invites future drift.
- **Proposed fix:** Resolve the notebook root through `notebook_dir(slug)` once at the top of `_chunk_textbook_impl` (or in `chunk_textbook` after validation) and build the parsed/chunks/ops paths under that resolved, symlink-checked base instead of bare `NOTEBOOKS_BASE / slug`. `notebook_dir` already accepts a `base=` kwarg for the test-patch path.
- **Regression guard:** Test that `chunk_textbook` raises (does not read/write) when `NOTEBOOKS_BASE/<slug>` is a symlink, mirroring the m6 `notebook_dir` symlink-refusal test.

### F4 — No regression guard for the chapter-title-extraction divergence

- **Severity:** LOW
- **File:** tests/test_textbook_chunker.py:122-145
- **What:** `TestCollectChapterTitles` covers only the happy path (chapter headings WITH `ltx_title ltx_title_chapter`) and the empty case. There is no test where the chapter heading lacks `ltx_title` — the exact shape that triggers F1. `test_chapter_labels_populated` (`:199-204`) asserts `chapter` equals the `<h2 ltx_title_chapter>` text, but only for the fixture's well-formed shape.
- **Why it matters:** Without this guard, the F1 divergence ships silently and any future LaTeXML config change that drops `ltx_title` from chapter headings corrupts `chapter` labels with no test failure.
- **Proposed fix:** Add the unit described in F1's regression guard.
- **Regression guard:** (same as F1) — fold this into the F1 fix.

### F5 — Synthetic fixture theorem ids are not LaTeXML-auto-id-shaped

- **Severity:** LOW
- **File:** tests/fixtures/textbook_chunker/two-chapter-book/index.html:21,55 and expected.json:21,67
- **What:** The fixture uses `id="Ch1.S1.Thm1"` / `id="Ch2.S1.Lem1"`. `_extract_theorem_label` returns the id verbatim unless it matches `_AUTO_ID_RE` (`^S\d+...\.Thm\w+\d+$`). Confirmed: `Ch1.S1.Thm1` does NOT match (starts `Ch`), so it is treated as a user `\label{}` and stamped into `theorem_label`. Real LaTeXML auto-ids would match the auto pattern and yield `theorem_label=None`.
- **Why it matters:** The golden `expected.json` blesses `theorem_label="Ch1.S1.Thm1"` — a value that would not arise from real LaTeXML output for an unlabeled theorem. The golden test therefore validates against a slightly unrealistic artifact, weakening confidence that real textbook output produces the expected `theorem_label=None` for auto-id'd theorems.
- **Proposed fix:** Either (a) add a second theorem in the fixture with a realistic auto-id (e.g. `id="S1.Thmtheorem1"`) to exercise the `theorem_label=None` path, or (b) note in the fixtures runbook that the fixture intentionally uses explicit labels and add a separate inline-HTML unit asserting `_extract_theorem_label` returns `None` for an auto-id'd textbook theorem.
- **Regression guard:** Inline-HTML unit: a textbook theorem with a LaTeXML-auto-id → emitted chunk has `theorem_label is None`.

## What was done well

- Correctly did NOT call `_compute_chunk_id` (which hardcodes `arxiv:`); `_compute_textbook_chunk_id` (`:127-142`) emits `textbook:<slug>:<sha>` with identical NFC→UTF-8→sha256→16-hex discipline and round-trips through `is_valid_chunk_id` (test verified).
- The FM-4 dedup loop (`:324-344`) is faithfully replicated from `_chunk_paper_impl` and the dedup test genuinely catches a no-dedup regression (simulated: 2 same-id chunks → assertion fails). Load-bearing and tested.
- Cleanup-before-assembly (`:274-279`) mirrors `chunk_paper`'s F1 fix — a downstream raise leaves the dir empty rather than retaining stale JSONs.
- Resilience envelope (`:238-254`) matches `chunk_paper` exactly: `PER_PAPER_FAILURE_EXCEPTIONS` caught → failure-log row → `[]`; validation runs OUTSIDE the envelope so bad slug/paper_id surfaces to the caller; programmer bugs propagate.
- Did NOT write LanceDB (no `write_chunks` call) — keeps the spike-3 per-notebook isolation boundary untouched, exactly as the synthesis mandated for m7.
- No BP1 / tool-schema / `pyproject.toml` / `conftest.py` change; output is byte-stable (`to_dict()` sorted keys, NFC hash, no timestamps; manifest content carries no pid/uuid/timestamp — those live only in the `.tmp` filename).
- `_extract_section_chunks(soup,...)` then `_extract_chunks_from_container(root,...)` call pattern matches `_chunk_paper_impl` precisely — no double-emit or missed-chunk divergence.
- `flat_paper_id` underscore-collision is not reachable: `_validate_paper_id` rejects `textbook:my_book` (slug regex forbids `_`) before any flatten, so `-`-vs-`_` collisions cannot occur for valid inputs.
- No `assert` for invariants in source (uses `raise`); `TEXTBOOK_CHUNKER_VERSION` correctly separate from `chunker_types.CHUNKER_VERSION` so a textbook change cannot force arXiv re-embedding; single-source-of-truth guard satisfied via descriptive reference.
- Clear, honest docstrings: every v0 deferral (empty preamble, NULL pages, no definition/exercise levels) carries an accurate `# TODO(m8)` marker, and the fixtures runbook documents the regeneration discipline.

## Recommended rectification order

1. F1 — highest correctness leverage; the recursive-fallback fix is small and directly fixes the mislabeling. Fold F4's regression guard into the same change.
2. F3 — route paths through `notebook_dir(slug)`; restores parity with the m6 notebook surface and is a small, contained edit.
3. F2 — cheapest as a doc note in the module docstring + fixtures runbook "v0 scope reminders"; pin current behavior with a unit. Full disambiguation is m8.
4. F5 — fixture-realism nit; add the auto-id unit or a runbook note. Defer if rectification budget is tight.

## Rectification status (filled by Phase 4)

- F1 (MEDIUM) — FIXED in `ingest/textbook_chunker.py`: new `_chapter_title_text` prefers a non-recursive `ltx_title_chapter` class match before the generic `_section_title_text` fallback, so a chapter heading lacking the generic `ltx_title` class no longer pulls a nested section title into the chapter-titles set. `_collect_chapter_titles` now calls it. Regression (also closes F4): `test_chapter_heading_without_ltx_title_does_not_pull_section`.
- F2 (MEDIUM) — FIXED (documented + pinned): the identical-chapter-titles-collapse v0 limitation is now documented in the `_collect_chapter_titles` docstring AND `.claude/docs/textbook-chunker-fixtures.md` §"v0 scope reminders", and pinned by `test_identical_chapter_titles_collapse_v0_limitation`. Full disambiguation (ordinal/id) deferred to m8 per the adversary's recommendation (a positional rewrite is >30 LOC, larger blast radius).
- F3 (MEDIUM) — FIXED in `ingest/textbook_chunker.py`: `chunk_textbook` now resolves the notebook dir via `tools._notebook_common.notebook_dir(slug, base=NOTEBOOKS_BASE)` (`_resolve_notebook_dir`), which adds the m6-F3 symlink-refusal + `.resolve()` containment guard. The read/write/log paths are built under that resolved dir (path-builder helpers now take `nb_dir`). Restores parity with notebook_init/fetch/ingest/purge. Regression: `test_symlink_notebook_dir_refused`.
- F4 (LOW) — FIXED: folded into F1's regression guard.
- F5 (LOW) — FIXED: added `TestTheoremLabelAutoId::test_auto_id_theorem_label_is_none` — a textbook theorem with a LaTeXML auto-id (`S1.Thmtheorem1`, matches `_AUTO_ID_RE`) yields `theorem_label=None`, exercising the path the fixture's explicit `Ch`-prefixed ids do not.

**Invalidation rate:** 0% (all 5 findings matched the cited file:line on re-verify; the adversary had empirically reproduced F1 + F2).

**Golden fixture unchanged:** the F1 fix preserves well-formed `ltx_title_chapter` extraction, so `expected.json` did not need regeneration (the golden-diff test stayed green).

**External writes:** none required.

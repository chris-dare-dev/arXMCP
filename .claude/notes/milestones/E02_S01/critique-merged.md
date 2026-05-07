# Critique — E02_S01

**Critic:** adversary
**Generated:** 2026-05-07T00:00:00Z
**Commit range:** 005657b..c0a7d55
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES: chunker logic is sound but two CRITICALs damage the
  project's core invariants — math fidelity (mission DP1) and path-traversal
  defense (Threat 1 in `08-security-observability-ops.md`).
- Counts: 2 CRITICAL, 4 HIGH, 6 MEDIUM, 2 LOW.
- Highest-risk file: `ingest/chunker.py:213` (`_element_text` → `get_text()`)
  silently strips MathML, dropping the very content the project exists to
  preserve.
- Cross-axis pattern: missing `paper_id` validation appears in `chunk_paper()`
  and propagates into the failure-log filename — a single defect with two
  exposure paths.
- Tier sequencing concern: the "≥300 chunks across 50 seed papers" acceptance
  criterion is silently waived ("DEFERRED" in implementation-summary). The
  parsed corpus is empty in this worktree; no integration evidence exists.
- Determinism: `_extract_section_chunks` iterates classes-then-find_all, which
  reorders sections relative to document order — non-deterministic chunk
  numbering across reorderings within section_class buckets.
- Re-run safety: the chunker never cleans `var/arxmcp/corpus/chunks/<paper_id>/`
  on re-entry, so stale `idxN.json` from longer prior runs leaks into the new
  output set.
- "What was done well" includes 8 bullets — critic is earning its keep.

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

### F1 — `_element_text` strips MathML and `alttext`, destroying math content

- **Severity:** CRITICAL
- **Source:** adversary
- **File:** ingest/chunker.py:211-213
- **What:** `_element_text(tag)` calls `tag.get_text(separator=" ")` on the
  whole subtree. LaTeXML emits inline math as
  `<math alttext="\\mathcal{F}"><mi class="ltx_font_mathcaligraphic">ℱ</mi></math>`.
  `get_text()` discards the `alttext` attribute (which holds the original
  LaTeX) and keeps only the rendered Unicode glyph(s) inside `<mi>`. Display
  equations with structure (`<msup>`, `<mfrac>`, `<munderover>`) collapse to
  concatenated symbols with no operator/structure information.
- **Why it matters:** This violates `01-mission-and-context.md` § "Why current
  arXiv-context tools fail for research math" verbatim — "treats papers as
  plain text via `pypdf` or similar. **This destroys LaTeX equations.** For
  papers in math.AG, math.NT, hep-th, math-ph, the equations *are the
  content*." The chunker's `body_text` is the input both BM25 (E02_S03) and
  the embedder (E03_S01) will consume. Lossy math means downstream retrieval
  is structurally crippled before any of those milestones run. Mission DP1
  ("Math fidelity over coverage") is the most-quoted design philosophy in
  the notes; this chunk shape silently violates it.
- **Proposed fix:** In `_element_text`, before calling `get_text()`, walk the
  tree and replace each `<math>` element with a sentinel string built from
  `alttext` (e.g. `"$" + alttext + "$"`). Fall back to inner-text only when
  `alttext` is absent. Add an option to also retain serialized MathML
  alongside body_text (a separate `body_mathml` field on `ChunkRecord` is the
  cleanest path; deferred-friendly).
- **Regression guard:** Add a fixture paper with a theorem containing
  `<math alttext="\\mathcal{F}">…</math>` and `<math alttext="\\int_0^1 f \\, dx">…</math>`.
  Assert that the resulting `body_text` contains `\\mathcal{F}` or at least the
  raw LaTeX form, and never the bare ℱ glyph alone. Add a test that
  `body_text.count("$")` is ≥ the number of `<math>` elements in the source.

### F2 — `paper_id` is unvalidated; arbitrary path traversal in writes and logs

- **Severity:** CRITICAL
- **Source:** adversary
- **File:** ingest/chunker.py:592-647 and ingest/chunker.py:666-680
- **What:** `chunk_paper(paper_id)` accepts any string and concatenates it
  into filesystem paths in three places: `PARSED_DIR / paper_id / "index.html"`
  (read), `CHUNKS_DIR / paper_id / f"{idx}.json"` (write), and the
  `paper_id` field substituted into the TSV failure log. There is no
  `^\d{4}\.\d{4,5}(v\d+)?$` regex check anywhere in the module.
  `chunk_paper("../../etc/passwd_dir")` would create
  `var/arxmcp/etc/passwd_dir/<idx>.json`. `chunk_paper("a/../../foo")` is
  also accepted. The failure log row also gets the unsanitized `paper_id`
  embedded in TSV — a `\t` or `\n` in `paper_id` corrupts log parsing.
- **Why it matters:** `08-security-observability-ops.md` Threat 1 explicitly
  enumerates this attack vector ("An LLM that has been prompt-injected by
  something it read in an arXiv abstract could pass `paper_id="../../../etc/passwd"`")
  and prescribes the regex mitigation. The chunker is invoked from a
  not-yet-written batch driver that will eventually consume IDs from the OAI
  feed and from MCP tool args — both of which carry untrusted strings.
- **Proposed fix:** Add `_PAPER_ID_RE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$|^[a-z\-]+/\d{7}(v\d+)?$")`
  at module top. At entry to `chunk_paper`, raise `ValueError` (which the
  outer `except` will log) if `_PAPER_ID_RE.match(paper_id)` is `None`. Also
  reject `paper_id` containing tab or newline before writing the failure log.
- **Regression guard:** Tests asserting that `chunk_paper("../etc/passwd")`,
  `chunk_paper("a/b")`, `chunk_paper("foo\nbar")`, and `chunk_paper("")`
  all return `[]` and write a failure-log row, AND that no file is created
  outside `tmp_path / "chunks"` after the call.

### F3 — Re-running chunker leaves stale `idxN.json` files (output not idempotent)

- **Severity:** HIGH
- **Source:** adversary
- **File:** ingest/chunker.py:646-647
- **What:** `out_dir.mkdir(parents=True, exist_ok=True)` is the only directory
  preparation. Existing files are not removed. If run 1 produces 6 chunks
  (`idx0.json`–`idx5.json`) and run 2 — after, say, a chunker version bump —
  produces only 4 (`idx0.json`–`idx3.json`), the run-2 output is
  `[idx0..idx3 (new)] + [idx4..idx5 (stale from run 1)]`. The downstream
  embedder enumerating `glob("*.json")` will silently re-embed dead chunks.
- **Why it matters:** Determinism (mission DP2) requires reproducible bytes
  per `(paper_id, chunker_version)`. A re-run is supposed to be a no-op or a
  full rebuild, never a half-overlay. This is also a cache-invariant
  violation: a chunk_id collision across versions becomes a corpus
  inconsistency that the MVCC story in E04_S02 cannot detect because the
  chunker is the source of truth.
- **Proposed fix:** Before writing, atomically replace `out_dir`: write to
  `out_dir.with_suffix(".tmp")`, then `shutil.rmtree(out_dir, ignore_errors=True)`,
  then `Path.rename(.tmp, out_dir)`. Or, simpler, delete every existing
  `*.json` in `out_dir` before the write loop.
- **Regression guard:** Test: write a sentinel `out_dir/idx99.json` then call
  `chunk_paper`; assert `idx99.json` is gone after the call.

### F4 — Section chunks emitted out of document order (determinism breaker)

- **Severity:** HIGH
- **Source:** adversary
- **File:** ingest/chunker.py:537-538
- **What:** `_extract_section_chunks` iterates the OUTER loop over
  `_SECTION_DIV_CLASSES = ["ltx_chapter", "ltx_section", "ltx_subsection",
  "ltx_subsubsection", …]` and calls `soup.find_all(True, class_=sec_class)`
  per class. All `ltx_section` chunks are emitted before any
  `ltx_subsection` chunk, regardless of document order. A paper structured
  `Sec1 → SubSec1.1 → Sec2 → SubSec2.1` will produce section chunks in the
  order `[Sec1, Sec2, SubSec1.1, SubSec2.1]`, never the document order
  `[Sec1, SubSec1.1, Sec2, SubSec2.1]`.
- **Why it matters:** The `chunk_id` placeholder embeds a monotonic counter
  driven by emission order. Two structurally-identical papers can produce
  different `(paper_id, idx)` orderings, and the hashed ID in E02_S04
  inherits that ordering. `07-multi-agent-caching.md` § Property 2 names
  "Sort results by `(score_desc, chunk_id_asc)`" and "Use deterministic
  chunk IDs" as load-bearing for prompt-cache reuse — emission-order drift
  in the source of truth makes those guarantees meaningless.
- **Proposed fix:** Walk the document tree once in document order and dispatch
  on class membership at each node. Or: call `soup.find_all(True,
  class_=lambda c: c in _SECTION_DIV_CLASSES)` (single pass returning
  document-order results), then partition.
- **Regression guard:** Fixture with two top-level sections each containing a
  subsection that emits a section chunk; assert that emitted section chunks
  appear in document order (i.e. interleaved, not grouped by class).

### F5 — Statement chunk truncation loses entire trailing text without warning to consumer

- **Severity:** HIGH
- **Source:** adversary
- **File:** ingest/chunker.py:461-470
- **What:** When `stmt_tokens > STMT_MAX_TOKENS`, the chunker silently
  encodes, slices to 512, and re-decodes. The resulting `body_text` is
  shorter than the source — no boundary marker, no truncation flag in the
  chunk record, no count of dropped tokens. Worse: the brief explicitly
  reserves the budget for `preamble + body`, but the chunker enforces only
  the body cap (acknowledged as deferred). A 511-token body with a 200-token
  preamble will pass this cap and overflow at embed time.
- **Why it matters:** A truncated theorem statement is a wrong-answer chunk;
  the embedder learns from a partial proposition. Downstream consumers
  cannot distinguish "this was the entire statement" from "this is the
  first 512 tokens of a 900-token statement." The acceptance criterion
  "no chunk's embedding-input view exceeds 512 BGE-M3 tokens" was rebadged
  to "(body-only)" without surfacing this gap to the chunk consumer.
- **Proposed fix:** Add a `truncated: bool` field on `ChunkRecord` (defaults
  False; set True when the statement was sliced). At minimum, log at
  WARN with the original token count so it's visible in ops. Alternatively,
  if a stmt body is over-budget, demote `kind` to `proof`-windowed so the
  caller knows multiple windows exist.
- **Regression guard:** Test: build a synthetic theorem with body > 512
  tokens. Assert the emitted chunk has `truncated=True` (after fix) or that
  the WARN log line is captured.

### F6 — `_window_proof_text` round-trips through encode/decode, mutating whitespace

- **Severity:** HIGH
- **Source:** adversary
- **File:** ingest/chunker.py:328-352
- **What:** Even when `len(token_ids) <= PROOF_MAX_TOKENS` the windowing
  function returns `[proof_text]` unchanged — but when splitting, every
  window goes through `_decode_tokens(token_ids)` which is BGE-M3's
  WordPiece-style detokenizer. WordPiece detokenization is NOT a round-trip
  for whitespace, control characters, or non-BMP Unicode. A chunk whose
  source body had `\n\n` paragraph breaks will return as `\n` or single
  spaces. `body_text` is no longer the verbatim source text the spec
  claims (`chunker_types.py:46-49`: "Plain-text extraction of the
  environment body").
- **Why it matters:** Determinism under the `(source_html_bytes →
  body_text)` map is required for content-addressable hashing in E02_S04.
  If the same source produces different `body_text` after a tokenizer
  upgrade, every chunk_id changes for no semantic reason, which torches
  the entire embedding cache and the LanceDB MVCC strategy from E04_S02.
- **Proposed fix:** Window on character offsets keyed off
  `tokenizer.encode_plus(text, return_offsets_mapping=True)` (BGE-M3's
  fast tokenizer supports this) so that each window slice is a substring
  of the original `proof_text`. The token-count check still uses the
  encoded ids, but the chunk text is a `proof_text[char_start:char_end]`
  slice. Same approach for the truncation branch in F5.
- **Regression guard:** Test: round-trip property. For a proof body that
  fits in one window, assert `_window_proof_text(text) == [text]` (already
  there). Add: for a long proof, assert that the concatenation of all
  windows minus overlap equals the original `body_text` byte-for-byte.

### F7 — Failure log rows include arbitrary exception messages and unsanitized paper_id (TSV corruption)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/chunker.py:666-680
- **What:** `f"{paper_id}\tfail\t{elapsed_s:.1f}\t{message}\n"` — `message`
  is `str(exc)` from a broad `except Exception`. An exception whose message
  contains `\n` or `\t` (anything that wraps a path with a newline, or an
  HTML snippet from a parser error) breaks the TSV row count downstream.
  `paper_id`, per F2, is also unsanitized.
- **Why it matters:** TSV log parsing in the weekly parser-failures review
  (per `08-security-observability-ops.md` § "Daily ops cadence") will
  produce silent off-by-one corruption — the exact failure mode that
  weekly review exists to catch.
- **Proposed fix:** Sanitize `message` before write: `message.replace("\t",
  " ").replace("\n", " ")`. Same for `paper_id`. Or escape with `repr()`
  on the message column.
- **Regression guard:** Test that simulates a `_chunk_paper_impl` raising
  `RuntimeError("a\tb\nc")` and asserts the log line has exactly 4
  tab-separated columns and no embedded newline.

### F8 — Broad `except Exception` masks programming bugs in dev

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/chunker.py:614
- **What:** The `try / except Exception as exc` swallow at the top of
  `chunk_paper` matches the resilience pattern from `01c6579`, but it
  also swallows `AttributeError`, `KeyError`, and `TypeError` from
  programmer bugs in the chunker itself. The `logger.error(... exc_info=True)`
  helps, but only if anyone is reading WARN+ logs. Tests already cover
  graceful degradation; this swallow primarily hides regressions.
- **Why it matters:** A future refactor that breaks the section-path
  walker for one fixture won't fail the test — the test will see `[]` and
  the assertion `len(chunks) >= 1` will fail with no diagnostic about why.
- **Proposed fix:** Define a `PER_PAPER_FAILURE_EXCEPTIONS` tuple
  (per the c486b26 / 01c6579 pattern referenced in the docstring),
  containing only `(OSError, BeautifulSoup-specific errors, ValueError,
  FileNotFoundError)`. Programmer-bug exceptions propagate.
- **Regression guard:** Test that `chunk_paper` re-raises `AttributeError`
  rather than swallowing it (mock `_extract_chunks_from_container` to
  raise AttributeError; assert `chunk_paper` propagates).

### F9 — `find_all(re.compile(r"^h[1-6]$"))` accidentally finds nested headings

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/chunker.py:295-299
- **What:** `_extract_theorem_name` calls `tag.find_all(re.compile(r"^h[1-6]$"),
  class_="ltx_title")` recursively. If a theorem environment contains a
  display equation with an `<h6 class="ltx_title">` somewhere inside (rare
  but legal), or a nested theorem (also legal under `_THEOREM_LIKE_ENVNAMES`
  via amsmath nesting tricks), the parenthetical from the wrong heading is
  returned.
- **Why it matters:** `theorem_name` is downstream input to E10_S02's dedup
  pass. The brief says: "if it has a display name … parse and emit the
  name as `theorem_name`." A wrong name causes false-positive dedups.
- **Proposed fix:** Restrict to the immediate `<h1-h6>` children of `tag`,
  not recursive descendants. `tag.find(re.compile(r"^h[1-6]$"),
  class_="ltx_title", recursive=False)` for the top-level case, then a
  bounded depth-1 fallback.
- **Regression guard:** Fixture: theorem containing a nested theorem with a
  `(NestedName)` heading; outer theorem's `theorem_name` must come from
  the OUTER heading or be `None`, never `"NestedName"`.

### F10 — Section_path lambda relies on undocumented bs4 behavior

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/chunker.py:251-254 and 257-260
- **What:** `class_=lambda c: c and "ltx_title" in c.split()`. bs4 invokes
  the lambda once per CLASS string, so `c` is a single class name like
  `"ltx_title"` and `c.split()` returns `["ltx_title"]`. The check
  reduces to `"ltx_title" in ["ltx_title"]` which works only when the
  exact class is `ltx_title`. A heading with class
  `"ltx_titlepage_title ltx_centering"` (real LaTeXML output for some
  paper styles) misses. Also, if bs4 ever changes to call the lambda
  with the full list (as the documentation suggests is possible), the
  `.split()` call raises AttributeError on a list — F8's swallow then
  hides it.
- **Why it matters:** Empty `section_path` for whole sections silently
  reduces metadata that downstream BM25 filtering and citation graph
  joins (E09_S0x) depend on.
- **Proposed fix:** Replace with `class_=lambda c: c == "ltx_title" or
  (isinstance(c, str) and "ltx_title" in c.split())` — explicit string
  guard. Or better: drop the lambda and use a helper function that works
  on the parent's full class list.
- **Regression guard:** Fixture with a heading that has multiple classes
  including `ltx_title` plus another (e.g. `ltx_title ltx_title_section
  ltx_centering`); assert section_path is correctly populated.

### F11 — Acceptance criterion "≥300 chunks across 50 seed papers" is silently waived

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** .claude/notes/milestones/E02_S01/implementation-summary.md:18
- **What:** The implementation summary records this acceptance criterion as
  "✗ DEFERRED" with the rationale "Parsed corpus not materialized in this
  worktree." The `var/arxmcp/corpus/parsed/` directory is empty in the
  worktree (E01_S03 was on the prior branch, not re-fetched here). No
  integration-style test counts emitted chunks against any paper subset —
  not even one synthetic 5-paper batch.
- **Why it matters:** The criterion exists because theorem-aware chunking
  *should* produce ~6 chunks per paper on average. If the implementation
  emits only 1–2 chunks per paper because of an extraction bug, the per-
  fixture tests would still pass and the project would not learn until
  E03_S01 fails its own corpus-wide validation. Acceptance criteria are
  the load-bearing handoff contract — silently downgrading them ships
  technical debt as success.
- **Proposed fix:** Add a `make verify-chunker-density` target that runs the
  chunker against a small built-in synthetic corpus of 5 fixture papers
  with realistic theorem density and asserts ≥30 chunks emitted (linear
  scaling of the ≥300/50 target). The test does not require the seed
  corpus.
- **Regression guard:** The new test target is itself the regression guard;
  CI fails if average chunks-per-paper drops below the threshold.

### F12 — `_count_tokens` called per chunk causes 50× tokenizer thrash on large papers

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/chunker.py:178-187, 461, 565
- **What:** Every chunk pays one `_count_tokens(text)` call. On the
  windowing path the same text is encoded once for `_encode_tokens` and
  re-encoded for `_count_tokens` upstream. The BGE-M3 tokenizer is fast
  but not free — the milestone's quoted goal is "loads tokenizer vocab
  only" yet the per-chunk hot loop still calls Python-side tokenizer
  glue. On a paper with 200 chunks this is 400+ tokenizer calls.
- **Why it matters:** This is purely a wall-clock concern (the brief calls
  out parse cost as a 1–2 day job for 50k papers; per-chunk overhead
  multiplies). Not a correctness bug.
- **Proposed fix:** In `_window_proof_text`, return token_ids alongside
  windows so the caller doesn't re-encode. Alternatively, cache the
  encoding per `text` via `functools.lru_cache(maxsize=256)` keyed on
  `text` (token_ids are small, fits in cache).
- **Regression guard:** Benchmark test in CI: chunking a synthetic 100-
  theorem paper completes in < N seconds (set N = 2× current measured
  baseline so regressions surface).

### F13 — `_extract_chunks_from_container` recursion has no depth bound

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/chunker.py:418-428
- **What:** Recursive `chunks.extend(_extract_chunks_from_container(child,
  paper_id, counter))` for every nested `<section>` / `<div>` /
  `<article>` / "unknown structural element." Adversarial HTML with
  100k nested `<div>`s blows the Python recursion limit
  (`RecursionError`) or eats the stack. The broad `except` catches
  `RecursionError`, returning `[]`, but the paper is silently dropped
  with no useful diagnostic.
- **Why it matters:** Threat 4 in `08-security-observability-ops.md`
  ("Resource exhaustion via tool arguments") is for the MCP server, but
  Threat 3 ("LaTeXML on hostile source") covers ingestion. A malicious
  arXiv submission could trivially hit this.
- **Proposed fix:** Add a `depth: int = 0` parameter; raise or short-circuit
  if depth > 50. Log a warning on truncation.
- **Regression guard:** Test with synthetic HTML containing
  `("<div>" * 5000) + ("</div>" * 5000)`; chunker must return without
  raising and without consuming > 100 MB RAM.

### F14 — `body_tokens=None` and `preamble_ref=None` are ambiguous (deferred vs absent)

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/chunker_types.py:68-69
- **What:** The schema treats `null` for `body_tokens` and `preamble_ref` as
  "deferred to a later milestone." But `null` is also the natural value
  for "BM25 tokenization not applicable" or "this chunk has no preamble."
  A downstream consumer in E02_S03 cannot distinguish "not yet computed"
  from "intentionally absent."
- **Why it matters:** Future-self foot-gun. When E02_S03 lands, the
  migration test "all chunks emitted by chunker_version v1.0 have
  body_tokens=null AND chunker_version v1.1 have body_tokens=list" is
  the only invariant; if v1.1 ever sets `body_tokens` to `null`
  intentionally, the fix-detection logic gets confused.
- **Proposed fix:** Document explicitly in the dataclass docstring that
  `null` means "deferred for chunker_version v1.0; populated by v1.1."
  Add a sentinel `_DEFERRED = object()` if real semantics ever require
  the distinction (probably not for v1, hence LOW).
- **Regression guard:** N/A (documentation-only).

### F15 — Hardcoded model name `BAAI/bge-m3` not configurable

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/chunker.py:174
- **What:** `AutoTokenizer.from_pretrained("BAAI/bge-m3")` is a literal.
  Per `08-security-observability-ops.md` Threat 6, model SHAs should be
  pinned. The current import also lacks a `revision=<sha>` kwarg.
- **Why it matters:** A compromised HF upload could ship a malicious
  tokenizer (less risky than full model code, but `AutoTokenizer` does
  load `tokenizer_config.json` and may load `tokenization_*.py` if
  `trust_remote_code=True` is ever flipped on).
- **Proposed fix:** Add a module-level `BGE_M3_MODEL = "BAAI/bge-m3"`
  and `BGE_M3_REVISION = "<pinned-sha>"`, pass `revision=` to the
  tokenizer constructor. Pinning the SHA is the load-bearing change.
- **Regression guard:** Test that `_get_tokenizer()` was called with a
  `revision=` argument (mock `AutoTokenizer.from_pretrained` and
  inspect call kwargs).

## What was done well

- The dual-column emission (stmt + proof) directly closes H3 from the
  research-synthesis backlog — the chunker enforces the 512-tok cap
  structurally, not by post-hoc trimming.
- `ChunkRecord.to_dict()` uses an explicit alphabetical key listing
  rather than relying on dict iteration order — the right way to honor
  BP1 byte-stability.
- Per-paper exception handling mirrors the c486b26 / 01c6579 pattern,
  keeping failure isolation consistent across the ingestion stack.
- Token budget constants (`BGE_M3_MAX_TOKENS`, `PROOF_HEADER_RESERVE`,
  `PROOF_WINDOW_OVERLAP`) are named and centralized, not magic numbers.
- The proof windowing math is correct for the common case: window N+1
  starts at `endN - 64`, not at `endN`, so the 64-token overlap is real.
- Auto-id regex correctly distinguishes LaTeXML's `S<N>.Thm<env><N>`
  pattern from user-supplied `\label{}` keys; tests cover both cases.
- The lazy tokenizer load via `_get_tokenizer()` keeps the import cheap
  and avoids loading torch into the chunker process.
- 128 unit tests pass, including a coverage checklist in the test module
  docstring that maps each test class to the brief's acceptance criteria.

## Recommended rectification order

1. **F2** (paper_id validation) — security baseline; touch first because
   F3 and F7 fixes also need to assume `paper_id` is safe.
2. **F1** (MathML stripping) — mission-critical; data-loss bug; F6 fix
   strategy may depend on the same DOM-walk infrastructure.
3. **F3** (stale chunks on re-run) — directory-wide invariant fix; lands
   cleanly before F4.
4. **F4** (section ordering) — affects chunk_id ordering which E02_S04
   will depend on; do this before E02_S04 lands.
5. **F6** (encode/decode whitespace mutation) — depends on understanding
   the DOM-walk; tackle alongside F1.
6. **F5** (silent stmt truncation) — surface-only after F1 fixes the
   underlying body_text content question.
7. **F7, F8, F9, F10** (cluster of correctness/observability medium fixes).
8. **F11** (chunk-density verification target) — adds a CI signal that
   guards the rest.
9. **F12, F13** (perf / DoS hardening).
10. **F14, F15** (LOW / docs / supply-chain pinning) — defer if time.

## Rectification status (filled by Phase 4)

Re-verify gate: 0 of 6 CRITICAL+HIGH findings invalidated (0% — well below 40% threshold).

- F1 — fixed in rect commit; regression tests `tests/test_chunker.py::TestF1MathMLPreservation` (3 tests verify alttext preserved, dollar-marker count, fallback path)
- F2 — fixed in rect commit; regression tests `tests/test_chunker.py::TestF2PaperIDValidation` (8 tests: valid new/old style, path traversal rejection, embedded tab/newline, empty string, no file creation on rejection)
- F3 — fixed in rect commit; regression test `tests/test_chunker.py::TestF3StaleFileCleanup::test_stale_files_removed_before_write`
- F4 — fixed in rect commit (single document-order traversal); regression test `tests/test_chunker.py::TestF4SectionDocumentOrder::test_section_chunks_interleave_subsections`
- F5 — fixed in rect commit (added `truncated: bool` to `ChunkRecord`); regression tests `tests/test_chunker.py::TestF5StmtTruncationFlag` (long stmt sets flag, normal stmt does not)
- F6 — fixed in rect commit (offset-mapping char-substring slicing); regression tests `tests/test_chunker.py::TestF6CharOffsetWindowing` (short-proof identity + long-proof substring property)
- F7 — fixed in rect commit; regression tests `tests/test_chunker.py::TestF7TSVLogSanitization` (tab strip, newline strip, end-to-end with problematic exception message)
- F8 — fixed in rect commit (`PER_PAPER_FAILURE_EXCEPTIONS = (OSError, ValueError, FileNotFoundError)`); regression tests `tests/test_chunker.py::TestF8ProgrammerBugsPropagate` (AttributeError propagates; ValueError is caught)
- F9 — fixed in rect commit (immediate-children scan only); regression test `tests/test_chunker.py::TestF9TheoremNameNoNestedLeak`
- F10 — fixed in rect commit (`isinstance(c, str)` guard in `_has_ltx_title` predicate)
- F11 — DEFERRED: synthetic 5-paper density target (~50 LOC) not built; tracked for follow-up. The unit-test surface covers logical invariants; the 50-paper check remains user-verifiable.
- F12 — DEFERRED: per-chunk tokenizer thrash optimization. Performance, not correctness; defer until a benchmark identifies it as a real bottleneck.
- F13 — fixed in rect commit (`_MAX_CONTAINER_DEPTH = 50`); regression test `tests/test_chunker.py::TestF13RecursionDepthBound::test_deep_nesting_does_not_raise`
- F14 — DEFERRED (LOW): doc-only ambiguity acknowledged; E02_S03 will disambiguate body_tokens semantics when populating it.
- F15 — DEFERRED (LOW): BGE-M3 model SHA pinning belongs in E13_S06 (security hardening epic).

# Critique — E02_S02

**Critic:** adversary
**Generated:** 2026-05-07T12:32:00Z
**Commit range:** ef66061..f1e0dcc
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES: extraction logic is sound and the determinism
  contract (sort + dedup + SHA-256[:16]) is correct, but a path-traversal
  vector via symlinked `.tex` candidates and a silent malformed-cache bug
  (TypeError uncaught in `_read_existing_preamble`) are reachable on the
  common path and must be fixed before the seed run.
- Counts: 0 CRITICAL, 3 HIGH, 6 MEDIUM, 4 LOW.
- Highest-risk file: `ingest/preamble.py:312` (`find_main_tex` result is
  read without verifying it is inside `raw_paper_dir`).
- BP1 byte-identical caching is the milestone's load-bearing invariant
  (per `07-multi-agent-caching.md` and `08-security-observability-ops.md`),
  yet `preamble_text` is not Unicode-normalized (NFC) and source decode
  is `errors="replace"` — both can quietly diverge across hosts.
- Idempotency cache is not robust: a corrupted `preamble.json` whose
  `macros` field is a string (not a list) silently produces a
  `PreambleDoc` with one-character "macros" and a wrong hash, because
  `_read_existing_preamble` does not catch TypeError.
- Concurrent runs on the same `paper_id` race on a single shared
  `preamble.json.tmp` filename — no PID/randomness in the temp name
  and no file lock (flagged in the brief; unaddressed).
- Test surface omits the prompt's specifically-requested edge cases:
  the `\\{` brace-scanner regression case, malformed-cache TypeError,
  symlink-escape, and hash-collision exercise across two papers.
- The chunker integration's `except ImportError: return None` swallows
  real install/transitive import failures — chunks ship with
  `preamble_ref=None` instead of surfacing the bug.

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

### F1 — Symlink escape: `find_main_tex` result not confined to raw_paper_dir

- **Severity:** HIGH
- **Source:** adversary
- **File:** ingest/preamble.py:312
- **What:** `extract_preamble` calls `find_main_tex(raw_paper_dir, paper_id)`
  which does `raw_dir.rglob("*.tex")` (tools/arxiv_fetch.py:180). The
  returned `Path` is passed straight to `main_tex.read_bytes()` in
  `_extract_preamble_impl`. arXiv tarballs are user-supplied content;
  a tarball can include a symlink `mypaper.tex -> /etc/passwd` (or
  `-> ../../../some-secret`) which `extract` lays down on disk. The
  extractor then reads through that symlink, hashes the content, and
  writes the contents under `var/arxmcp/corpus/preamble/<paper_id>/`.
- **Why it matters:** Threat 1 in `08-security-observability-ops.md`
  (path traversal on attacker-controlled paper content). The chunker
  closes this for the parsed-HTML directory via `_validate_paper_id`;
  the preamble extractor inherits ID validation but adds a NEW unsafe
  read against a path it computed via `rglob`. The attack surface is
  exactly the e-print tarball pipeline.
- **Proposed fix:** Before reading, resolve and re-check:
  `resolved = main_tex.resolve(); raw_resolved = raw_paper_dir.resolve();
   if not resolved.is_relative_to(raw_resolved): raise FileNotFoundError(...)`.
  Additionally reject `main_tex.is_symlink()` outright (Tier 0 doesn't
  need symlink support).
- **Regression guard:** `tests/test_preamble.py::TestSymlinkConfinement`
  with two cases: (a) a symlink inside the paper dir pointing outside
  raises FileNotFoundError; (b) a non-symlink real `.tex` inside still
  works.

### F2 — `_read_existing_preamble` does not catch TypeError on corrupt cache

- **Severity:** HIGH
- **Source:** adversary
- **File:** ingest/preamble.py:272-279
- **What:** `_read_existing_preamble` catches
  `(json.JSONDecodeError, KeyError, OSError)`. `PreambleDoc.from_dict`
  does `list(data["macros"])`. If a corrupted/legacy `preamble.json`
  has `macros: "..."` (a string), `list("abc")` succeeds and returns
  `["a","b","c"]` — no exception is raised. The cached doc is then
  treated as authoritative; `extract_preamble` returns it from the
  idempotent fast path on subsequent calls without re-extracting.
  More importantly, even on a fresh run the `cached.source_hash` may
  still match the input hash (if the source_hash field is intact),
  short-circuiting to nonsense macros.
- **Why it matters:** Silent data corruption on cache reload. The
  embedder will then read `preamble_text="a\nb\nc"`, hash it, and the
  chunk's `preamble_ref` will point to a hash that no honest extractor
  would ever produce. BP1 byte-identical caching invariant violated.
- **Proposed fix:** Add `TypeError` to the except tuple in
  `_read_existing_preamble`. Additionally have `from_dict` verify
  `isinstance(data["macros"], list)` and `all(isinstance(m, str) for m in data["macros"])`,
  raising TypeError otherwise.
- **Regression guard:**
  `tests/test_preamble.py::TestCacheCorruption::test_macros_as_string_rejected`
  writes `{"paper_id":"...","macros":"oops",...}` and asserts
  `_read_existing_preamble` returns None (forcing re-extraction).

### F3 — `except ImportError: return None` masks real install failures

- **Severity:** HIGH
- **Source:** adversary
- **File:** ingest/chunker.py:851-860
- **What:** `_resolve_preamble_ref` wraps the lazy import in
  `try: from ingest.preamble import ... except ImportError: return None`.
  An ImportError here usually means a transitive dependency is broken
  (e.g. `tools.arxiv_fetch` cannot be resolved because the wheel was
  built without the `tools/` package). The chunker then silently
  emits chunks with `preamble_ref=None` for every paper, indefinitely,
  instead of surfacing the failure.
- **Why it matters:** The whole milestone's caching contract depends
  on `preamble_ref` being populated. Silently dropping it for the
  entire corpus because of a packaging bug is exactly the kind of
  failure mode the design constitution treats as a load-bearing
  regression. The implementation summary's stated rationale — "keeps
  chunker importable in partial environments (e.g. tests that patch
  sys.modules)" — describes a TEST need, not a production need; tests
  should patch the module, not rely on import failure.
- **Proposed fix:** Drop the `except ImportError` envelope. If the
  preamble module is genuinely missing, let the chunker raise on
  import; if a test wants to skip preamble extraction it should patch
  `_resolve_preamble_ref` directly. Keep only the per-paper
  PER_PAPER_FAILURE_EXCEPTIONS guard that surrounds the actual call.
- **Regression guard:** Add a test that asserts
  `from ingest.chunker import _resolve_preamble_ref` performs the
  inner `from ingest.preamble import extract_preamble` successfully
  on the project's import path (i.e. no broken packaging).

### F4 — Atomic-write tmp filename collides on concurrent same-paper runs

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/preamble.py:266-269
- **What:** `tmp = out_path.with_suffix(out_path.suffix + ".tmp")` always
  resolves to `<paper>/preamble.json.tmp`. Two processes ingesting the
  same paper (e.g. `make ingest` re-run while a `pytest -k preamble`
  fixture sweep is in progress, or a multi-worker driver) both write
  to the same tmp path. `tmp.write_text` is not atomic; one process's
  truncate-then-write can be interleaved with the other's `os.replace`
  picking up a half-written file.
- **Why it matters:** Brief explicitly listed concurrent extraction as
  an unaddressed risk. The output is small so the window is short, but
  the failure mode is silent corruption of `preamble.json` rather than
  a clean error.
- **Proposed fix:** Use a per-process suffix, e.g.
  `out_path.with_suffix(f".{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")`,
  and add a `try/finally` to remove the tmp on exception.
- **Regression guard:** Unit test that runs two threads against the
  same paper_id and verifies both succeed and the final
  `preamble.json` parses; or a simpler test that asserts tmp filenames
  differ across two simultaneous calls.

### F5 — Temp file leaks on exception during atomic write

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/preamble.py:266-269
- **What:** If `tmp.write_text(payload, ...)` succeeds but `os.replace`
  fails (out of space on the destination filesystem, mount being
  torn down, EPERM in container restart), the `.tmp` file is left
  behind. No `try/finally` to clean it up.
- **Why it matters:** A run-of-the-mill operational hiccup leaves
  stale `preamble.json.tmp` files inside the corpus directory. They
  do not invalidate the cache (the load path only reads
  `preamble.json`), but they accumulate and can confuse forensic
  inspection of why a paper "looks half-extracted".
- **Proposed fix:** Wrap in `try: write+replace; finally: tmp.unlink(missing_ok=True)`
  AFTER the replace would have moved tmp away (so cleanup only runs
  on the failure path).
- **Regression guard:** Test that monkeypatches `os.replace` to raise
  OSError, calls `_write_preamble_json`, and asserts no `.tmp` file
  remains in the output directory.

### F6 — No Unicode normalization (NFC) of preamble_text

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/preamble.py:339-342
- **What:** `tex_source = source_bytes.decode("utf-8", errors="replace")`
  followed by regex extraction and `"\n".join(macros)`. There is no
  `unicodedata.normalize("NFC", ...)` step. A `.tex` file that contains
  precomposed characters (e.g. `é` U+00E9) and another that contains
  the decomposed form (`e` + U+0301) but is otherwise byte-identical
  in the macros' visible meaning will produce different `preamble_text`
  and different `preamble_hash` values.
- **Why it matters:** The brief and `08-security-observability-ops.md`
  § BP1 demand byte-identical caching across runs and across hosts;
  a re-tar'd source on a Mac vs. a Linux host can quietly switch
  normalization form on filename and even body content. Math.AG
  papers are the lowest-risk corpus for this, but the contract is
  load-bearing for the embedder, not just convenient.
- **Proposed fix:** After decoding and BEFORE comment stripping,
  `tex_source = unicodedata.normalize("NFC", tex_source)`. Document
  the choice in the module docstring.
- **Regression guard:** Test that constructs the same macro twice
  (once NFC, once NFD) and asserts both extractions yield the same
  `preamble_text`.

### F7 — `errors="replace"` on UTF-8 decode silently masks corrupt input

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/preamble.py:339
- **What:** `source_bytes.decode("utf-8", errors="replace")` substitutes
  U+FFFD for any invalid byte. arXiv tarballs occasionally contain
  Latin-1 or ISO-8859 source. The substitution is silent; the
  resulting `preamble_text` may contain replacement characters that
  the embedder then ingests as part of its byte-identical caching key.
- **Why it matters:** A non-UTF8 source produces a hash that is stable
  ONLY for the same Python version and `errors=` policy. Future
  changes to the decode policy invalidate every cached preamble.
  More immediately: U+FFFD inside a macro body silently changes the
  macro, but the failure does not surface in the parser-failures log.
- **Proposed fix:** Use `errors="strict"`; on `UnicodeDecodeError`,
  log to `preamble.log` and re-raise as a `ValueError` (already in
  `PER_PAPER_FAILURE_EXCEPTIONS`). Optional: try a `latin-1` fallback
  ONCE with explicit logging if strict UTF-8 fails.
- **Regression guard:** Test with a `.tex` containing an invalid UTF-8
  byte that asserts the extractor raises and writes a log row.

### F8 — Hash-collision behavior between papers is not exercised

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_preamble.py
- **What:** The prompt explicitly asked for a test that two papers
  producing the same `preamble_text` agree on `preamble_ref`. None of
  the 46 tests exercise this. Semantically it is correct (same content
  → same ref), but the test surface should pin the behavior so a
  future change that, say, mixes paper_id into the hash (a real
  refactoring temptation) is caught.
- **Why it matters:** The cache contract relies on cross-paper
  identical preambles producing the same hash so the embedder can
  share embedding-input cache hits. Without a test, a "fix" that
  scopes the hash per-paper would silently halve cache hit rate on
  the corpus.
- **Proposed fix:** New test:
  ```
  def test_identical_preamble_across_papers_yields_same_ref(tmp_path):
      tex = r"\newcommand{\R}{\mathbb{R}}"
      _stage_paper(tmp_path, "2307.00001", tex)
      _stage_paper(tmp_path, "2307.00002", tex)
      d1 = _patched_extract(tmp_path, "2307.00001")
      d2 = _patched_extract(tmp_path, "2307.00002")
      assert d1.preamble_hash == d2.preamble_hash
  ```
- **Regression guard:** the test above is the guard.

### F9 — Brace scanner: missing regression test for `\\{` (escaped backslash + open-brace)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_preamble.py:125-145
- **What:** The prompt called out `\\{` (escaped backslash followed
  by literal opening brace) as worth a regression test — the scanner
  reads `\\` as one escape-pair (`i += 2`), then sees `{`, increments
  depth. The implementation looks correct but no test exercises it.
  The existing brace-balanced tests cover `\{` and `\}` only.
- **Why it matters:** The scanner is the load-bearing piece for
  multi-line macros. A future "optimization" to the escape rule
  could break this without any test catching it; the prompt's
  axis sweep flagged it explicitly.
- **Proposed fix:** Add to `TestBraceBalancedScan`:
  ```
  def test_escaped_backslash_followed_by_open_brace(self):
      text = r"{a\\{b}c}"  # \\ is an escaped backslash, then {b}c
      end = _scan_balanced_body(text, 1)
      assert end == len(text)
  ```
- **Regression guard:** the test above is the guard.

### F10 — `find_main_tex` rglob picks up nested non-paper .tex files

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tools/arxiv_fetch.py:180 (consumed by ingest/preamble.py:312)
- **What:** `find_main_tex` uses `raw_dir.rglob("*.tex")` — recursive.
  arXiv tarballs occasionally include vendored class samples, e.g.
  `samples/template.tex`, that contain `\documentclass` and several
  `\newcommand`s. The fall-back ordering "first containing
  `\documentclass`" combined with `sorted()` (alphabetical) means
  that a `samples/template.tex` will be picked over an unnamed
  `paper.tex` if the paper file is not named `<paper_id>.tex` and
  there are multiple candidates.
- **Why it matters:** The preamble extractor would then extract
  macros from a vendored sample, not the actual paper, while the
  chunker (which reads `parsed/<paper_id>/index.html`) is unaffected.
  The chunks would carry a `preamble_ref` that points to the wrong
  preamble entirely.
- **Proposed fix:** Restrict to top-level `.tex` files first
  (`raw_dir.glob("*.tex")`), only fall back to `rglob` if zero
  candidates at the top level, and explicitly de-prioritize any path
  whose components include `samples`, `templates`, or `examples`.
  Alternatively, gate by paper-internal file size: pick the largest
  `.tex` (the original brief language).
- **Regression guard:** Test fixture that stages `paper_dir/main.tex`
  AND `paper_dir/samples/template.tex`, both with `\documentclass`,
  and asserts `find_main_tex` returns `main.tex`.

### F11 — `_LET_RE` `charlit` accepts any non-space, non-backslash char

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/preamble.py:121-124
- **What:** The regex `(?P<charlit>[^\s\\])` matches `}`, `{`, `%`,
  even punctuation. Real `\let` targets are control sequences or
  character tokens; the syntax `\let\foo}` is not valid TeX.
- **Why it matters:** Adversarial input could surface as a
  spuriously "extracted" macro, but it is structurally bounded to a
  single line and small.
- **Proposed fix:** Tighten `charlit` to `[A-Za-z0-9]`.
- **Regression guard:** none required.

### F12 — Macro names with `_` are silently dropped

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/preamble.py:93-124
- **What:** `[A-Za-z@]+` for command names misses macros containing
  `_` (e.g. `\my_macro`). These are uncommon outside `\@_` style
  internal macros and the LaTeX kernel.
- **Why it matters:** Marginal — math.AG papers rarely use `_` in
  macro names. Worth a comment in the code rather than a fix.
- **Proposed fix:** Document the limitation in the module docstring;
  optionally widen the class to `[A-Za-z@_]+` (TeX makes `_` a
  catcode-8 char in math mode but not in macro names by default).
- **Regression guard:** none required.

### F13 — Performance: four full-text regex sweeps per paper

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/preamble.py:214-252
- **What:** `_extract_macros` runs `_BRACED_HEAD_RE.finditer`,
  `_DECL_MATH_OP_HEAD_RE.finditer`, `_DEF_HEAD_RE.finditer`, and
  `_LET_RE.finditer` over the full source.
- **Why it matters:** At seed scale (50 papers) and even at 200K-paper
  scale, preambles are tiny and regex compilation is amortized. The
  cost is negligible.
- **Proposed fix:** None required; could combine into one alternation
  if anyone profiles a hot spot, but YAGNI.
- **Regression guard:** none.

### F14 — `\providecommand` extension beyond brief is undocumented in commit message

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/preamble.py:24-30 (module docstring)
- **What:** The milestone brief lists `\newcommand`, `\renewcommand`,
  `\DeclareMathOperator`, `\def`, `\let`. The implementation also
  handles `\providecommand`, `\edef`, `\gdef`, `\xdef`. The decision
  is reasonable and documented in `implementation-summary.md`, but
  the diverging acceptance-criterion language ("3 `\newcommand` and
  1 `\DeclareMathOperator` produces a macros list of length 4") is
  taken as a floor in the test, not a strict equality. A future
  reviewer should not have to reason about whether the broader scope
  was intentional.
- **Why it matters:** Process / traceability, not correctness.
- **Proposed fix:** None required; the module docstring already
  enumerates the in-scope set explicitly.
- **Regression guard:** none.

## What was done well

- The determinism contract is correctly implemented: `dict.fromkeys`
  preserves first-seen ordering, `sorted` enforces canonical order,
  and `"\n".join(macros)` produces a stable byte sequence per
  `04-parsing-and-chunking.md` § Preamble extraction.
- Reusing `_validate_paper_id`, `InvalidPaperIDError`, and
  `_sanitize_log_field` from the chunker is the right call — single
  source of truth for Threat 1 path-traversal defense.
- Reusing `find_main_tex` from `tools/arxiv_fetch.py` instead of
  duplicating the heuristic is correct (modulo the rglob issue in
  F10).
- The brace-balanced scanner correctly handles `\{` and `\}` via the
  `i + 1 < n` guard and `i += 2` skip; the comment-stripper correctly
  honors `\%` and `\\%` per the TeX rule, and a test for the
  even-count case (`\\%` IS a comment) exists.
- Module docstring rejects Anthropic contextual retrieval explicitly,
  with rationale tying back to BP1 byte-identical caching — directly
  satisfies the acceptance criterion.
- Idempotency via source_hash short-circuit is correctly implemented
  for the happy path; the `mtime`-based regression test is the right
  way to verify "no rewrite" semantics.
- Fixture .tex covers a richer set of macros than the milestone floor
  required, including the `\\%` literal-percent edge case.
- Atomic write via `tmp + os.replace` is the standard pattern (modulo
  F4 and F5).
- The chunker integration is structurally minimal and correct: one
  resolve call after both chunk passes, in-place stamp, fall-through
  to `None` on extractor failure (modulo F3 for ImportError).
- `PER_PAPER_FAILURE_EXCEPTIONS` is targeted (not a bare `Exception`),
  matching the codebase convention from `tools/arxiv_fetch.py` and
  `ingest/chunker.py`.

## Recommended rectification order

1. **F1** (symlink escape) — security, single-file change, must land
   before any seed run reads attacker-controlled tarball contents.
2. **F2** (TypeError on corrupt cache) — silent data corruption,
   trivial fix (one line in the except tuple plus a from_dict guard).
3. **F3** (ImportError swallowed in chunker) — load-bearing
   correctness on the chunker's common path; remove the envelope.
4. **F6** (NFC normalization) — the BP1 contract requires it; cheap
   to add (`unicodedata.normalize("NFC", tex_source)`).
5. **F7** (decode `errors="replace"`) — same family as F6, fix in
   the same change.
6. **F4** + **F5** (tmp filename race + leak) — same code path, fix
   together with one PID/uuid suffix and a try/finally.
7. **F10** (rglob picks up nested non-paper .tex) — fix once, with
   the F1 fix nearby in the same function.
8. **F8** (hash-collision test) — test-only, low risk, high value.
9. **F9** (brace-scanner regression test) — test-only.
10. **F11**–**F14** — defer; record under `deferred_findings`.

## Rectification status (filled by Phase 4)

Re-verify gate: 0 of 3 CRITICAL+HIGH findings invalidated (0% — well below 40% threshold).

- F1 — fixed in rect commit (resolve + is_relative_to + is_symlink check); regression tests `tests/test_preamble.py::TestF1SymlinkConfinement` (symlink-escape rejected, real file still works).
- F2 — fixed in rect commit (TypeError + ValueError added to except tuple; from_dict validates `macros` is list of strings); regression tests `tests/test_preamble.py::TestF2CacheCorruption` (macros-as-string, non-string entries, corrupt-cache triggers re-extraction).
- F3 — fixed in rect commit (dropped `except ImportError` envelope from `_resolve_preamble_ref`); regression test `tests/test_preamble.py::TestF3ChunkerImportFailureSurfaces` (static source check that the construct is gone).
- F4 — fixed in rect commit (per-process PID + UUID suffix on tmp filename); regression test `tests/test_preamble.py::TestF4F5AtomicWriteCleanup::test_tmp_suffix_is_unique_per_call`.
- F5 — fixed in rect commit (try/finally with `contextlib.suppress(OSError)` on tmp.unlink); regression test `tests/test_preamble.py::TestF4F5AtomicWriteCleanup::test_tmp_cleaned_up_when_replace_fails`.
- F6 — fixed in rect commit (`unicodedata.normalize("NFC", tex_source)` before extraction); regression test `tests/test_preamble.py::TestF6NFCNormalization::test_nfc_and_nfd_produce_identical_hash`.
- F7 — fixed in rect commit (strict UTF-8 decode; `UnicodeDecodeError → ValueError` caught by PER_PAPER_FAILURE_EXCEPTIONS); regression test `tests/test_preamble.py::TestF7StrictUTF8Decode::test_invalid_utf8_raises_and_logs`.
- F8 — fixed in rect commit (regression test only — behavior was already correct); `tests/test_preamble.py::TestF8HashCollisionAcrossPapers::test_identical_preamble_across_papers_yields_same_ref`.
- F9 — fixed in rect commit (regression test only — behavior was already correct); `tests/test_preamble.py::TestF9BraceScannerEscapedBackslash::test_escaped_backslash_followed_by_open_brace`.
- F10 — fixed in rect commit (`_select_root_tex` prefers top-level .tex; only falls back to recursive search when none); regression tests `tests/test_preamble.py::TestF10TopLevelTexPreferred` (top-level over samples; nested fallback).
- F11 — DEFERRED (LOW): `_LET_RE` charlit accepts any non-space, non-backslash char. Adversarial input would surface as a spuriously "extracted" macro but is structurally bounded.
- F12 — DEFERRED (LOW): macro names with `_` are silently dropped. Marginal — math.AG papers rarely use `_` in macro names.
- F13 — DEFERRED (LOW): four full-text regex sweeps per paper. Performance only; cost is negligible at all corpus scales.
- F14 — DEFERRED (LOW): `\providecommand` extension noted in implementation summary; commit-message traceability is process, not correctness.

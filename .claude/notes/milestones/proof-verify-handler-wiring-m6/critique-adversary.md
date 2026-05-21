# Critique — proof-verify-handler-wiring-m6

**Critic:** adversary
**Generated:** 2026-05-21T00:00:00Z
**Commit range:** `0555ea2..b4e5dd53562bfd18861e4a582fb2e6f5f2fac828`
**Verdict:** DO-NOT-SHIP

## Executive summary

- DO-NOT-SHIP: a CRITICAL path-traversal in `notebook_purge._purge_corpus_assets` lets a malformed `papers.txt` entry drive `shutil.rmtree` outside the corpus tree.
- Counts: 1 CRITICAL, 2 HIGH, 3 MEDIUM, 2 LOW.
- Highest-risk site: `tools/notebook_purge.py:110-122` — `target = base_dir / paper_id; shutil.rmtree(target)` with no `is_valid_paper_id` or containment check.
- BM25 path collision (HIGH): the implementer's documented deviation ("global path, per-notebook version-integer separation") fails the moment two notebooks reach the same per-notebook LanceDB version (e.g. v1 from a fresh ingest each) — the second build is silently skipped by `build_bm25_index`'s idempotent gate, leaving notebook B serving notebook A's stale BM25 chunk_ids.
- Path-traversal defense-in-depth is asymmetric: `notebook_dir()` and `notebook_fetch` validate the slug AND validate paper_ids, but `notebook_purge` validates the slug then trusts arbitrary strings as paper_ids — this is the exact gap the synthesis warned about ("`os.path.commonpath` is the wrong primitive; use set difference") but the set-difference doesn't restore the missing validation.
- All 8 documented FMs have at least one test, but FM-1's test only covers the legitimate-double-membership case, not the malformed-id-membership case that is the actual exploit path.
- 35 tests pass; full suite green per implementation summary; no `assert`-for-invariants regressions; no fork dependencies.
- Cache byte-stability + MCP spec axes are not applicable (no tool surface touched); confirmed clean.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — purge can rmtree outside corpus via malformed papers.txt

- **Severity:** CRITICAL
- **Source:** adversary
- **File:** `tools/notebook_purge.py:110-122` (`_purge_corpus_assets`) and `tools/notebook_purge.py:80-107` (`_compute_unique_paper_ids`)
- **What:** `_compute_unique_paper_ids` reads `papers.txt` via `read_paper_ids_from_papers_txt` which intentionally does NOT validate against `is_valid_paper_id` (per the helper's docstring at `tools/_notebook_common.py:97-117`, validation is "the caller's job"). The purge caller never performs that validation. `_purge_corpus_assets` then iterates `for paper_id in sorted(unique_ids):` and does `target = base_dir / paper_id; if target.is_dir(): shutil.rmtree(target)`. If `papers.txt` contains a line like `../../../home/user/important`, pathlib's `/` operator yields `<CORPUS_PARSED_DIR>/../../../home/user/important`, `target.is_dir()` follows the `..` segments and returns True for any pre-existing directory on the host, and `shutil.rmtree` silently deletes it. Demonstrated locally:
  ```
  target = /tmp/cv-test-base/../cv-victim-dir
  is_dir = True  → shutil.rmtree would delete /tmp/cv-victim-dir
  ```
- **Why it matters:** The destructive surface of this milestone is `notebook_purge.py`. The whole point of the typed-slug confirmation + set-difference is preventing accidental loss. A single malformed line in any notebook's `papers.txt` (operator typo OR a hostile shared notebook) escalates to arbitrary directory deletion under whatever uid runs the script. The synthesis explicitly called out FM-2 (slug path traversal) and FM-5 (malformed papers.txt) — both defenses exist for `notebook_fetch.py`, neither was applied to `notebook_purge.py`'s corpus-side deletion.
- **Proposed fix:** In `_compute_unique_paper_ids`, drop entries failing `is_valid_paper_id` from `this_ids` BEFORE the set difference. In `_purge_corpus_assets`, add belt-and-braces containment: after `target = base_dir / paper_id`, compute `resolved = target.resolve(); base_resolved = base_dir.resolve()` and `try: resolved.relative_to(base_resolved); except ValueError: continue` (skip the entry with a stderr warning). Both layers needed because validating-then-pathing is still vulnerable to symlink races. Surface skipped entries on stderr so operators see the reject.
  ```python
  from ingest.identifiers import is_valid_paper_id
  ...
  def _purge_corpus_assets(unique_ids: set[str]) -> int:
      removed = 0
      for paper_id in sorted(unique_ids):
          if not is_valid_paper_id(paper_id):
              print(f"WARN: skipping invalid paper_id {paper_id!r}", file=sys.stderr)
              continue
          for base_dir in (CORPUS_PARSED_DIR, CORPUS_CHUNKS_DIR, CORPUS_EMBEDDINGS_DIR):
              target = (base_dir / paper_id).resolve()
              try:
                  target.relative_to(base_dir.resolve())
              except ValueError:
                  print(f"WARN: refusing to delete {target} — outside {base_dir}", file=sys.stderr)
                  continue
              if target.is_dir():
                  shutil.rmtree(target)
                  removed += 1
      return removed
  ```
- **Regression guard:** New test `test_purge_corpus_too_rejects_malformed_paper_ids` — seed `papers.txt` with `"../../tmp/victim"`, create `/tmp/victim/` containing a sentinel file in the test's `tmp_path` (NOT a real `/tmp` write), assert the sentinel is untouched and the purge exits 0 with a WARN.

### F2 — BM25 path collision across notebooks silently corrupts search

- **Severity:** HIGH
- **Source:** adversary
- **File:** `tools/notebook_ingest.py:127-137` invokes `build_bm25_index(str(lancedb_path), corpus_version=corpus_version)`; collides with `ingest/bm25_indexer.py:104` (`BM25_INDEX_ROOT = REPO_ROOT / "var" / "arxmcp" / "index" / BM25_DIR_NAME`) and `ingest/bm25_indexer.py:313` (idempotent skip).
- **What:** `build_bm25_index` writes to the GLOBAL `BM25_INDEX_ROOT / v<corpus_version>/`. Each per-notebook LanceDB starts at version 1 (fresh staging dir). When notebook A ingests first and writes BM25 to `var/arxmcp/index/bm25/v1/`, notebook B's subsequent ingest at its own v1 hits the idempotent-skip at `bm25_indexer.py:313` (`if pkl_path.is_file() and ids_path.is_file(): return`) and the script logs `BM25 built for corpus_version=1` while silently keeping notebook A's pickle + chunk_ids. Notebook B's queries then resolve BM25 candidates that don't exist in its LanceDB — silent retrieval corruption.
- **Why it matters:** The implementer documented this as "deviation #1: BM25 path stays global; per-notebook `corpus_version` is unique per notebook" — but that rationale is wrong. Per-notebook `corpus_version` is unique only WITHIN one notebook; across notebooks the integer collides on every fresh ingest. The whole milestone is "Variant 1: per-notebook lancedb"; if BM25 doesn't follow, the lookup path is broken. AC #3 ("`notebook_ingest.py` exits 0 when ingest succeeds AND the per-notebook BM25 index is built") becomes false on the second notebook — the BM25 isn't built, it's skipped, and the operator sees success.
- **Proposed fix:** Either (a) fail-fast: detect the collision (`pkl_path.is_file()` while target slug differs from the index's prior writer) and raise; (b) namespace the BM25 path by slug. Cheapest correct fix is (a) plus a documented punt to a follow-up milestone for (b). For (a), write a sentinel file `var/arxmcp/index/bm25/v<N>/.slug` containing the slug on first build; on re-build, if the sentinel slug ≠ the current slug, raise a `NotebookError` instructing the operator to run `notebook_purge.py` on the prior slug first OR to pass a new flag overriding. Document the limitation prominently in `notebook_ingest.py`'s docstring (the current docstring at lines 17-21 misleads operators by claiming version-integer separation is sufficient).
- **Regression guard:** New test `test_ingest_detects_bm25_collision` — monkeypatch `BM25_INDEX_ROOT` to a `tmp_path`, run ingest twice (slug A then slug B) where both reach version 1, assert second call raises and instructs operator how to recover.

### F3 — notebook_dir() containment check is not effective against symlink attack

- **Severity:** HIGH
- **Source:** adversary
- **File:** `tools/_notebook_common.py:68-94` (`notebook_dir`)
- **What:** The containment check resolves both `nb_base` and `target` with `.resolve()` (strict=False per docstring), then asserts `target.relative_to(nb_base)`. The slug regex `^[a-z][a-z0-9-]{2,30}$` rejects `..`, `/`, and other meta — but the regex does NOT prevent an operator from pre-creating `var/arxmcp/notebooks/safe-slug` as a SYMLINK pointing to `/etc/`. After the symlink is created (e.g. by a malicious shared notebook bundle, a buggy ops script, or a careful tarball extraction), `notebook_dir("safe-slug").resolve()` returns the symlink target. The `relative_to` check then catches it ONLY if the target is outside `nb_base` — but a symlink to `<nb_base>/another-notebook` would pass the containment check and let `notebook_purge.py safe-slug` `shutil.rmtree` the OTHER notebook.
- **Why it matters:** The synthesis explicitly identified this as FM-2's belt-and-braces target. The current implementation defends against `slug = "../escape"` (rejected by regex) but NOT against the post-mkdir symlink case. The slug regex says "this slug name is safe," not "the path it points to today is safe."
- **Proposed fix:** Before returning `target`, also assert `target.is_symlink() is False` AND, if `target.exists()`, that `target` is a real directory (`os.path.realpath(target) == str(target)` after both are normalized). Most cleanly: refuse to act on any notebook whose `nb_dir` itself is a symlink, raising a `NotebookError` directing the operator to investigate. Acceptable to skip the cross-symlink-within-base case for v1, but document the limitation.
  ```python
  if target.exists() and target.is_symlink():
      raise NotebookError(
          f"notebook path {target} is a symlink — refusing for safety; "
          f"investigate before proceeding"
      )
  ```
- **Regression guard:** New test `test_notebook_dir_rejects_symlink` — create `nb_base/safe-slug` as a symlink to a sibling directory, assert `notebook_dir("safe-slug")` raises.

### F4 — fetch's > 1024-byte cache-hit heuristic admits corrupt HTML

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/notebook_fetch.py:84-87`
- **What:** Before calling `try_cache`, the script short-circuits with `if parsed_path.is_file() and parsed_path.stat().st_size > 1024: from_cache.append(paper_id); continue`. `try_cache` itself (`ingest/ar5iv_fetch.py:147-155`) requires BOTH `cache_path` AND `parsed_path` to exist before returning a hit. The script's bare-size heuristic accepts any 1025+-byte file regardless of content — no `<math` body check, no `_AR5IV_ERROR_BANNER` check. An operator's manually-dropped invalid file (or a half-written file from a crashed pre-m6 run) counts as a cache hit; the ingest downstream then chunks empty/corrupt HTML and the operator gets zero chunks with no signal at the fetch step.
- **Why it matters:** Delegating to `try_cache` was the synthesis's resolution (Disagreement 1) precisely to inherit its security/validity checks. The short-circuit re-introduces drift. The synthesis said "Concrete shape: ... loops calling `try_cache(...)` with `time.sleep(3.0)` between non-first calls" — it did NOT prescribe an out-of-band cache-hit heuristic.
- **Proposed fix:** Drop the size heuristic entirely. Always call `try_cache`; trust its hit-detection logic (which is the same `parsed_path.is_file() && cache_path.is_file()` predicate the milestone is trying to wrap). To preserve the no-sleep optimization on guaranteed-cached paths, call `try_cache` first with sleep=0; only sleep BEFORE the next call if the prior result was a real network fetch (look at `result.reason`: `"ok_local_cache"` means no fetch, `"ok"` means fetch happened).
- **Regression guard:** New test `test_fetch_does_not_short_circuit_corrupt_parsed_file` — seed `parsed_path` with 2 KB of `<html></html>` (no `<math>`); without the fix the script counts it `from_cache`; with the fix `try_cache` is called and a controlled mock returns `no_math_in_body`, surfaced as `missing`.

### F5 — _gather_pdf_deferred_warnings crashes on non-dict manifest.json

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/notebook_purge.py:64-71`
- **What:** `manifest = pdf_dir / "manifest.json"; data = json.loads(manifest.read_text(...)); titles = data.get("manual_titles") or {}`. The try/except catches `OSError, json.JSONDecodeError`. If the JSON parses successfully to a non-dict (e.g. `[1,2,3]` or `"oops"` or `null`), `data.get(...)` raises `AttributeError` on a list/str/None, which propagates uncaught and aborts the purge AFTER computing pdf_warn_lines partially but BEFORE the rmtree. The operator sees a Python traceback and may infer the notebook was purged when it wasn't (or vice versa, depending on where the WARN print landed).
- **Why it matters:** The WARN is informational only, but a corrupt manifest should not abort the whole purge. Defensive contract: a malformed pdf-deferred manifest must not block destructive operations the operator already confirmed.
- **Proposed fix:** Add `isinstance(data, dict)` check before `data.get`. Catch `AttributeError` in the existing except clause for completeness. Cheaper variant: `titles = (data if isinstance(data, dict) else {}).get("manual_titles") or {}` and validate `isinstance(titles, dict)` too.
- **Regression guard:** New test `test_purge_warns_about_pdf_deferred_with_non_dict_manifest` — seed `manifest.json` with `"[1,2,3]"`; assert purge proceeds (return code 0), PDFs are still listed without titles, no traceback.

### F6 — typed-slug confirmation: EOFError catch is dead code

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/notebook_purge.py:185-189`
- **What:** `typed = in_stream.readline().strip()` is wrapped in `try: ... except (EOFError, KeyboardInterrupt):`. `file.readline()` does NOT raise `EOFError` on EOF — it returns `""`. So on EOF, `typed = "".strip() = ""`, then the next branch (`if typed != slug:`) catches it as "aborted: typed `''`, expected `'demo'`". That works, but emits the confusing diagnostic "typed '', expected 'demo'" rather than the intended "aborted (EOF)". `KeyboardInterrupt` IS reachable but only because Python re-raises `SIGINT` — and a Ctrl-C during a destructive prompt should abort cleanly with a clear message.
- **Why it matters:** Adversary axis: the confirmation gate is the second line of defense (after the slug regex). Its UX should be unambiguous. The current handler silently treats EOF as "wrong slug" rather than "aborted on EOF," which is misleading at best and can hide automation bugs at worst.
- **Proposed fix:** Replace with `if not typed: print("aborted (EOF or empty input)", file=sys.stderr); return 2`. Keep `KeyboardInterrupt` in the except since Ctrl-C IS distinct from EOF.
- **Regression guard:** New test `test_purge_aborts_cleanly_on_eof` — pass `io.StringIO("")` (empty input → readline returns `""`); assert rc == 2 and stderr says "aborted" (not "typed ''").

### F7 — FM-7 (stale BM25) coverage punted to indexer tests without integration

- **Severity:** LOW
- **Source:** adversary
- **File:** `tools/notebook_ingest.py` (no specific line — absence of integration test) + implementation summary §FM-7 row
- **What:** The implementer's coverage table at `implementation-summary.md:62` admits "FM-7 ... no separate test — covered by indexer's own tests." But the synthesis's FM-7 ("Stale BM25 from prior runs ... `notebook_ingest.py` should log a warning if multiple `v<N>` directories exist for the same notebook's lancedb") is NOT just about the indexer skipping rebuilds — it's about `notebook_ingest.py` SURFACING the situation to the operator. No code in `notebook_ingest.py` checks for multiple `v<N>` dirs.
- **Why it matters:** The synthesis was specific. An operator who has run `notebook_ingest.py` 3 times (each writing a new version) will have `var/arxmcp/index/bm25/v1/, v2/, v3/` and won't know without manual inspection that older versions are unused. This is paired with F2 above — both reflect the BM25 path discipline being incomplete.
- **Proposed fix:** Either implement the warning the synthesis specified, or document the deferral in the implementation summary + add a TODO in the script. The least-effort path: after `build_bm25_index` returns, list `BM25_INDEX_ROOT.glob("v*")` and log a `WARN` if `len(entries) > 1` suggesting `notebook_purge.py --purge-corpus-too` (or a future BM25-prune flag).
- **Regression guard:** New test `test_ingest_warns_about_stale_bm25_versions` — mock BM25_INDEX_ROOT containing v1, v2, v3 directories before running ingest; assert WARN appears in captured logs/stderr.

### F8 — notebook_init race on parallel invocation

- **Severity:** LOW
- **Source:** adversary
- **File:** `tools/notebook_init.py:89-92`
- **What:** `if nb_dir.exists(): print(...); return 0` is followed by `nb_dir.mkdir(parents=True, exist_ok=False)`. Two parallel `notebook_init.py same-slug` invocations TOCTOU race: both see `exists() == False`, both attempt `mkdir(exist_ok=False)`, the loser gets `FileExistsError` propagated as a bare Python traceback (NOT wrapped in `NotebookError`).
- **Why it matters:** Operator workflow is single-threaded by intent, so impact is low. But the trace from CLI is ugly and the script is supposed to be idempotent. CLAUDE.md §4.7 bans `assert` for invariants — same spirit applies here: file-system races should produce clean diagnostics, not Python tracebacks.
- **Proposed fix:** Wrap `mkdir(parents=True, exist_ok=False)` in `try/except FileExistsError`, treat as the same idempotent skip ("notebook exists; skipping (created by concurrent invocation)").
- **Regression guard:** No regression test required — a unit test covering this would need to mock concurrent processes. Document the fix is for defensive UX, no behavior change for the single-operator case.

## What was done well

- Slug regex `^[a-z][a-z0-9-]{2,30}$` is correctly applied as the first action in every script's `run()` entry point (verified at `_notebook_common.py:47-65` and each script's `run()`).
- `run_bulk_ingest` integration uses the right kwargs (`lancedb_staging_path`, `failures_path`, `log_path`) — verified against `ingest/bulk_ingest.py:338-349`. The implementer correctly caught the brief's `ARXMCP_LANCEDB_PATH` error.
- Synthesis-prescribed FM coverage table is honest: implementer explicitly flagged FM-7 as not directly tested, didn't silently claim coverage.
- 35 tests all pass; test file's docstring maps each test to AC/FM (excellent self-documentation).
- All four scripts cleanly separate `run()` (pure-function, testable) from `main()` (argparse + sys.exit wiring), enabling direct test calls.
- No `assert` statements in production scripts (verified — CLAUDE.md §4.7 compliance is clean).
- Tests use `tmp_path` everywhere; no live `var/arxmcp/` writes.
- Delegating ar5iv fetches to `ingest.ar5iv_fetch.try_cache` is the right call — inherits the 100 MB cap, 429/503 handling, `<math` body check, and User-Agent contract for free.
- `NotebookError(RuntimeError)` subclass + explicit "use raise, not assert" docstring honors the project's invariant-as-runtime-check discipline.
- The pdf-deferred WARN-regardless-of-`--force` design honors the synthesis Disagreement 3 resolution exactly.
- `_compute_unique_paper_ids` correctly uses set difference (not `os.path.commonpath`) per FM-1.

## Recommended rectification order

1. **F1 (CRITICAL).** Block ship. Smallest blast radius to fix — ~15 LOC across `_compute_unique_paper_ids` + `_purge_corpus_assets` + one new test. Highest leverage: closes arbitrary directory deletion.
2. **F2 (HIGH).** Touches `notebook_ingest.py`; either implement the slug-sentinel guard OR raise/document explicitly. Fast loser test: try two ingests with different slugs that produce overlapping `corpus_version=1`.
3. **F3 (HIGH).** Symlink defense in `notebook_dir()` — ~10 LOC + one test.
4. **F4 (MEDIUM).** Remove the size heuristic in `notebook_fetch.py`. Trivial code change; one new test.
5. **F5, F6, F7 (MEDIUM × 2 + LOW).** Defensive UX cleanups; can bundle into one commit.
6. **F8 (LOW).** Deferrable if Phase 4 is time-pressed; record under `deferred_findings`.

## Rectification status

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->

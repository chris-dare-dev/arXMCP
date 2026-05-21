# Research Brief — proof-verify-handler-wiring-m6

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-21T22:00:00Z
**Focus:** Failure-mode analysis and security/safety surface of `notebook_purge.py`

---

## In-codebase context

**Design constitution notes that apply:**

- `08-security-observability-ops.md` §Threat 1: "strict regex on every arxiv ID input:
  `^\d{4}\.\d{4,5}(v\d+)?$` for new-style IDs, `^[a-z\-]+/\d{7}(v\d+)?$` for old-style.
  Reject at the JSON-Schema level so it never reaches handlers." — the notebook scripts
  are not MCP tool handlers but should apply the same `is_valid_paper_id` gate at the
  boundary where `papers.txt` lines are consumed.

- `08-security-observability-ops.md` §Threat 7: "Content-length sanity checks (a single
  paper > 100 MB source is suspicious)." Already enforced in `ingest/ar5iv_fetch.py`
  (`AR5IV_MAX_RESPONSE_BYTES = 100 * 1024 * 1024`). `notebook_fetch.py` must delegate to
  `ingest.ar5iv_fetch.try_cache` rather than re-implementing HTTP to inherit this.

- `CLAUDE.md §4.7`: "`assert` is BANNED for invariants." All guard conditions in the
  notebook scripts must use `if … raise RuntimeError(…)` or `if … raise ValueError(…)`.

- `CLAUDE.md §4.7`: "Pure-ASGI middleware required." Not applicable — these are CLI tools,
  not middleware.

- `CLAUDE.md §4.6` (doc placement): Script docstrings documenting Variant 1 layout are
  fine. Any companion `.md` must go under `.claude/` — NOT in `tools/` or `docs/` unless
  referenced from the root README.

**Slug regex from the roadmap:** The roadmap validates its own slug at line 379:
`"proof-verify-handler-wiring" matches ^[a-z][a-z0-9-]{2,30}$`. The `notebook_init.py`
script MUST enforce the same pattern before creating any directories — this is the canonical
slug constraint for the notebook subsystem.

**Existing notebooks on disk:** `var/arxmcp/notebooks/{bridgeland-stability,shimura-varieties}/`
already exist with `papers.txt`, `queries.json`, `lancedb/`, and (for shimura-varieties)
`pdf-deferred/` with a `manifest.json`. The `notebook_init.py` idempotency contract
(no-op on existing slug) must NOT clobber `pdf-deferred/` or the existing lancedb.

**PDF-deferred directory:** `var/arxmcp/notebooks/shimura-varieties/pdf-deferred/manifest.json`
exists and documents that PDFs are deferred pending Nougat PDF support (E11_S01 D2). The
`notebook_purge.py` script must detect and warn when `pdf-deferred/` exists under the
target notebook before proceeding with destructive deletion.

**`bulk_ingest` CLI interface:** `ingest/bulk_ingest.py` accepts `--paper-ids-file`,
`--lancedb-staging-path`, `--ar5iv-cache-dir`, `--limit`, `--dry-run`. The staging path
defaults to `var/arxmcp/index/lancedb-staging/`. `notebook_ingest.py` must override
`--lancedb-staging-path` to `var/arxmcp/notebooks/<slug>/lancedb` — the milestone brief
says "runs the existing `bulk_ingest`" which means subprocess invocation or direct Python
call with the right path argument.

**BM25 path vs notebook path:** `ingest/bm25_indexer.py` hardcodes
`BM25_INDEX_ROOT = REPO_ROOT / "var" / "arxmcp" / "index" / "bm25"`. Building a
**per-notebook** BM25 at `var/arxmcp/notebooks/<slug>/index/bm25/v<N>/` requires passing
a custom output directory to `build_bm25_index`. The function signature is
`build_bm25_index(lancedb_path, corpus_version, ...)` — the implementer needs to verify
whether `build_bm25_index` accepts a custom output dir or whether the BM25_INDEX_ROOT is
hardcoded. If hardcoded, `notebook_ingest.py` must call the builder differently or the
indexer needs a new `output_dir` param.

**`ar5iv_fetch.try_cache` handles 429/503 as miss:** Per `ingest/ar5iv_fetch.py` lines
231–251, `urllib.error.HTTPError` (including 429 and 503) is caught and returned as
`Ar5ivResult(hit=False, reason="http_429")`. No retry occurs. `notebook_fetch.py` should
surface 429 responses distinctly in its summary line (not lumped into `missing=K`) so the
operator knows to re-run rather than manually drop those paper IDs.

---

## Failure-mode analysis (PRIMARY FOCUS — 8 modes)

**FM-1: `notebook_purge.py --purge-corpus-too` deletes papers shared with other notebooks.**

Trigger: paper_id `2303.07061` appears in both `bridgeland-stability/papers.txt` and
`shimura-varieties/papers.txt`. Operator runs
`notebook_purge.py bridgeland-stability --purge-corpus-too`.

Observable symptom: `var/arxmcp/corpus/parsed/2303.07061/` deleted; shimura-varieties
notebook silently loses an ingested paper on next re-ingest.

**Root cause of risk:** The "paper_ids unique to this notebook" check requires reading ALL
sibling notebooks' `papers.txt` files and computing set difference. `os.path.commonpath`
is the WRONG primitive — it returns the common path prefix, not paper membership. The
correct implementation is:

```python
all_other_ids = set()
for nb_dir in notebooks_base.iterdir():
    if nb_dir.name == slug:
        continue
    pt = nb_dir / "papers.txt"
    if pt.exists():
        all_other_ids |= _read_paper_ids(pt)
unique_ids = this_notebook_ids - all_other_ids
```

Mitigation: implement exactly this set-difference pattern. Log a warning for each
non-unique paper_id that will be skipped from corpus deletion.

**FM-2: `notebook_purge.py` with slug containing `..` or shell metacharacters.**

Trigger: `uv run python tools/notebook_purge.py ../corpus` or
`uv run python tools/notebook_purge.py bridgeland; rm -rf /`.

Observable symptom without defense: `shutil.rmtree(notebooks_base / "../corpus")` resolves
to `var/arxmcp/corpus/`, deleting the entire parsed corpus.

Experimental verification: `pathlib.Path('/var/arxmcp/notebooks') / '../corpus'` resolves
to `/var/arxmcp/corpus` — the traversal succeeds.

Mitigation: validate slug against `^[a-z][a-z0-9-]{2,30}$` regex BEFORE constructing any
path. Then additionally verify:

```python
target = (notebooks_base / slug).resolve()
if not str(target).startswith(str(notebooks_base.resolve())):
    raise RuntimeError(f"slug {slug!r} resolves outside notebooks_base — aborting")
```

Note: `pathlib.Path.resolve(strict=True)` is INSUFFICIENT here because it raises
`FileNotFoundError` for non-existent paths — a new notebook directory doesn't exist yet
when `notebook_init.py` runs. The regex gate is the primary defense; the resolved-path
check is the belt-and-braces secondary for existing notebooks. The regex MUST be the first
check applied.

**FM-3: `notebook_init.py` idempotency gap — partial-state overwrite.**

Trigger: `notebook_init.py bridgeland-stability` is run when the directory exists but
`papers.txt` is present and `queries.json` is absent (partial state from a failed first
run or manual deletion of one file).

Observable symptom: Brief says "re-running on an existing notebook is a no-op." A naive
check `if notebook_dir.exists(): skip` will skip the missing `queries.json` silently,
leaving the notebook in permanent partial state. Conversely, if the check is per-file
("create if missing"), it may silently overwrite a user-edited `papers.txt` on a fresh
run after the user renamed their file.

Mitigation: The idempotency check should gate on the notebook directory level, not
file-by-file. If `notebook_dir.exists()`, log "notebook exists; skipping" and exit 0
regardless of which files are present. Document in the docstring that partial-state
recovery requires manually deleting the notebook directory and re-running.

**FM-4: `notebook_fetch.py` 429 from ar5iv silently counted as "missing."**

Trigger: ar5iv is rate-limiting the ingest client; returns HTTP 429 for 5 of 40 papers.

Observable symptom: `ar5iv_fetch.try_cache` returns `Ar5ivResult(hit=False, reason="http_429")`.
If `notebook_fetch.py` lumps all miss reasons into `missing=K`, the operator sees
`missing=5` and drops those 5 IDs from `papers.txt`, when actually they should re-run
after a backoff.

Mitigation: distinguish `reason` categories in the summary output:
`fetched=N from_cache=M missing=K rate_limited=R`. Print rate-limited paper IDs
separately with the message "retry after backoff — do NOT drop these." ar5iv lacks a
`Retry-After` header (CDN-fronted static cache), so recommend a fixed 60s backoff.

**FM-5: `notebook_fetch.py` malformed entries in `papers.txt` cause silent skip.**

Trigger: `papers.txt` contains `https://arxiv.org/abs/2303.07061` (URL instead of ID) or
`2303.07061v1` (versioned ID) or a blank line not filtered.

Observable symptom: `ingest.ar5iv_fetch.try_cache` raises `ValueError` (per line 136-141
of `ar5iv_fetch.py`: "raises ValueError for malformed paper_id"). If `notebook_fetch.py`
catches ValueError broadly, the line is silently dropped into `missing=K`.

Mitigation: pre-validate every line of `papers.txt` against `is_valid_paper_id` from
`ingest/identifiers.py` BEFORE calling `try_cache`. Invalid lines should be printed as a
distinct `malformed=J` category in the summary. Also: `is_valid_paper_id` accepts both
new-style (`2303.07061`) AND old-style (`hep-th/0001234`). The `tools/arxiv_fetch.py`
`PAPER_ID_RE` only accepts new-style. Use `ingest.identifiers.is_valid_paper_id` for
full coverage including old-style papers in bridgeland-stability (e.g. `0705.3794`).

**FM-6: `notebook_ingest.py` lancedb dir doesn't exist when `bulk_ingest` runs.**

Trigger: Operator runs `notebook_ingest.py bridgeland-stability` before running
`notebook_init.py` (m6 dependency on m4 is "required by m4" but m6 itself has no enforced
dependency on `notebook_init.py` having been run first).

Observable symptom: `bulk_ingest.run_bulk_ingest` writes to
`var/arxmcp/notebooks/bridgeland-stability/lancedb`; LanceDB's `lancedb.connect()` creates
the directory on first write, so this is actually NOT a hard failure. However, the `ops/`
subdirectory for logs (`var/arxmcp/notebooks/<slug>/ops/`) must also be created before the
logger tries to write there.

Mitigation: `notebook_ingest.py` should call `notebook_dir.mkdir(parents=True, exist_ok=True)`
and `(notebook_dir / "ops").mkdir(parents=True, exist_ok=True)` before invoking `bulk_ingest`.
This makes `notebook_ingest.py` resilient to being run without a prior `notebook_init.py`.

**FM-7: `notebook_ingest.py` partial BM25 build from prior failed ingest conflicts.**

Trigger: A previous run of `notebook_ingest.py` wrote chunks to lancedb (corpus_version=1)
but crashed before completing the BM25 build, leaving only `bm25.pkl` (no `chunk_ids.json`).
A re-run tries to detect the existing BM25 as "already built" and short-circuits.

Observable symptom: `ingest/bm25_indexer.py` checks for BOTH `bm25.pkl` AND
`chunk_ids.json` before skipping (per docstring: "A partial state — only one file present
— falls through to a full rebuild"). So partial state is handled correctly by the
indexer itself. However: if the lancedb staging path now has `corpus_version=2` (because
a second run added more papers), the old `v1/bm25.pkl` remains alongside a newly built
`v2/bm25.pkl`. The server reads the highest-version BM25 — this is correct behavior, but
the stale `v1/` directory wastes disk. `notebook_ingest.py` should log a warning when
multiple version directories exist, directing the operator to prune old ones via
`notebook_purge.py`.

**FM-8: `notebook_purge.py --purge-corpus-too` on a notebook containing PDF-deferred papers.**

Trigger: `notebook_purge.py shimura-varieties --purge-corpus-too`. The shimura-varieties
notebook has `pdf-deferred/` with `manifest.json` documenting two PDFs. These PDFs are
not tracked in `papers.txt` (they have no arXiv IDs). They are also not in
`var/arxmcp/corpus/parsed/` (PDF ingest is deferred).

Observable symptom: The `--purge-corpus-too` logic iterates `papers.txt` to find
per-paper corpus assets to delete. The PDF-deferred entries in `manifest.json` are
NOT in `papers.txt`, so they don't trigger corpus deletion — correct. But the
`pdf-deferred/` directory WILL be deleted when `shutil.rmtree(notebook_dir)` runs.
Those PDFs are not recoverable without re-downloading from original URLs.

Mitigation: Before `shutil.rmtree`, detect `pdf-deferred/manifest.json`. If present,
print a warning: "WARN: pdf-deferred/ contains <N> PDFs not backed by corpus assets.
Deleting these requires re-downloading from original URLs. Confirm? [type slug]"
This warning must appear even when `--force` is passed — `--force` skips the
interactive confirmation gate but should NOT suppress the pdf-deferred warning.
Alternatively, document in the script that `--force` silently deletes pdf-deferred,
so the operator is forewarned.

---

## Prior decisions and lessons

From git log, E13_S01 through E13_S10 (security audit cycle) established path-traversal
defense as the top security concern. The `_safe_extract` function in `tools/arxiv_fetch.py`
uses `dest_resolved = dest.resolve(); member_path.relative_to(dest_resolved)` as the
canonical pattern for path-containment checks. The same pattern (resolve both paths, check
`relative_to`) should be used in `notebook_purge.py` for the slug-to-path validation.

The `is_valid_paper_id` in `ingest/identifiers.py` is the single source of truth for paper
ID validation (established at E06_S03 F11 closure). Both `notebook_fetch.py` and
`notebook_purge.py --purge-corpus-too` MUST use this function, not `tools/arxiv_fetch.py`'s
narrower `PAPER_ID_RE` (which is new-style-only and would reject old-style IDs like
`0705.3794` which are present in `bridgeland-stability/papers.txt`).

Memory note (established across E13 milestones): `assert` is banned. All invariant checks
in the 4 scripts must use `if ... raise RuntimeError(...)` or `if ... raise ValueError(...)`.

**Conflict with brief's description of `notebook_ingest.py`:** The brief says the script
"runs the existing `bulk_ingest` with the per-notebook lancedb path
(`ARXMCP_LANCEDB_PATH=var/arxmcp/notebooks/<slug>/lancedb`)." However, `bulk_ingest.py`
does not read `ARXMCP_LANCEDB_PATH` from the environment — it uses `--lancedb-staging-path`
as a CLI argument (line 445-453 of `ingest/bulk_ingest.py`). **The brief's description of
environment-variable wiring is incorrect.** The implementer must use the `--lancedb-staging-path`
CLI argument, or invoke `run_bulk_ingest()` directly with the `lancedb_staging_path`
parameter.

---

## External sources

**`urllib.request` behavior on HTTP 429/503:** `urllib.request.urlopen` raises
`urllib.error.HTTPError` for any non-2xx status including 429. The exception carries
`e.code = 429` and `e.headers`. The body is accessible via `e.read()` but is NOT returned
as a regular response. `ingest/ar5iv_fetch.py` (lines 231-242) already handles this
correctly: `except urllib.error.HTTPError as exc: return Ar5ivResult(hit=False, reason=f"http_{exc.code}")`.
The `notebook_fetch.py` script inherits this behavior by delegating to `try_cache`.

**`pathlib.Path.resolve(strict=True)` for path traversal defense:** When `strict=True`,
`Path.resolve()` raises `FileNotFoundError` if the path does not exist. This is UNSUITABLE
as the primary path-traversal defense in `notebook_purge.py` because:
(a) It only blocks traversal to non-existent paths; if `../corpus` exists, `strict=True`
resolves it successfully.
(b) Tested experimentally: `resolve(strict=True)` returns the traversed-outside path when
the target exists. The correct defense is: regex-validate the slug first, then check that
`(notebooks_base / slug).resolve()` starts with `notebooks_base.resolve()`.

**`os.path.commonpath` for uniqueness check:** `os.path.commonpath([path_a, path_b])`
returns the common path prefix — NOT paper membership. It is the wrong primitive for
determining whether a paper_id is unique to one notebook. The correct implementation reads
all sibling `papers.txt` files and computes set difference (see FM-1 above).

---

## Recommendation

Implement all four scripts with slug validation (`^[a-z][a-z0-9-]{2,30}$`) as the FIRST
check in every script's `main()`, before any path construction. The slug regex is the
primary path-traversal defense; `(notebooks_base / slug).resolve()` containment check is
the secondary. Use `ingest.identifiers.is_valid_paper_id` (not `tools.arxiv_fetch.PAPER_ID_RE`)
for all paper ID validation — the bridgeland corpus contains old-style IDs that the
narrower regex rejects. Delegate HTTP fetching entirely to `ingest.ar5iv_fetch.try_cache`
to inherit the existing 429/503 handling and 100 MB cap. For `notebook_purge.py`, compute
per-paper uniqueness via set difference across sibling `papers.txt` files and warn on
`pdf-deferred/` before any rmtree call (even with `--force`).

The `notebook_ingest.py` script must invoke `bulk_ingest.run_bulk_ingest()` programmatically
(not via subprocess env var) using the `--lancedb-staging-path` argument or direct Python
call — the brief's `ARXMCP_LANCEDB_PATH` environment variable wiring is a documented
mismatch with `bulk_ingest.py`'s actual CLI interface.

New `tests/tools/` directory will need an `__init__.py` (it does not exist yet). Tests for
`notebook_purge.py` should use `tmp_path` fixture to create synthetic notebook trees rather
than touching the live `var/arxmcp/notebooks/` directories.

---

## Open questions

1. **BM25_INDEX_ROOT hardcoding:** Does `ingest.bm25_indexer.build_bm25_index` accept a
   custom output directory for the per-notebook BM25? The current implementation hardcodes
   `BM25_INDEX_ROOT = REPO_ROOT / "var/arxmcp/index/bm25/"`. If not, `notebook_ingest.py`
   cannot write to `var/arxmcp/notebooks/<slug>/index/bm25/v<N>/` without modifying
   `bm25_indexer.py`. The implementer must check the `build_bm25_index` signature and
   either add an `output_dir` parameter or accept the global BM25 path (not per-notebook).
   **This is a potential scope expansion** (modifying `ingest/bm25_indexer.py`).

2. **`--force` on `notebook_purge.py` and pdf-deferred:** Should `--force` suppress the
   pdf-deferred warning? The recommendation above says warn regardless of `--force` — but
   the brief doesn't specify. The implementer should choose: warn always (conservative),
   or suppress only with `--force --purge-pdf-deferred-too` (explicit third flag).

---

## External writes the implementation will require

None — this milestone is purely local. All four scripts write to `var/arxmcp/` (gitignored
data tree). No git push, no GitHub issue creation, no infra mutation, no third-party API
call is required by the implementation itself. Tests run against `tmp_path` synthetic trees.

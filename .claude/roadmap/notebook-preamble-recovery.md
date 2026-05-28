# notebook-preamble-recovery — Fetch raw .tex on the ar5iv path so preambles can be extracted

**Owner:** Chris Dare
**Created:** 2026-05-27
**Status:** scoped
**Source:** post-`make re-embed-all` log triage on the embedder-truncation-m1 cutover

**Related artifacts (read these first):**

- [`.claude/notes/scans/preamble-without-raw-tex-2026-05-27.md`](../notes/scans/preamble-without-raw-tex-2026-05-27.md)
  — the canonical research brief. Diagnoses the gap, surveys five
  remediation options, recommends **Option A** explicitly, lists
  files/tests/ACs. **This roadmap milestone is the implementation
  of Option A.**
- [`.claude/notes/milestones/embedder-truncation-m1/operator-followup.md`](../notes/milestones/embedder-truncation-m1/operator-followup.md)
  — the immediate-prior milestone whose `make re-embed-all` exposed
  this gap on every ar5iv-only paper (~65 in the live notebook tree).

**Why now.** The Phase-4-shipped `chore(ingest): quiet structural noise
in re-embed logs` commit (b489048) demoted the per-paper preamble
ERROR + traceback to a single WARNING line. That cleans up the
**symptom** in the log. This milestone fixes the **root cause**:
`extract_preamble` requires raw `.tex` on disk, and the ar5iv-only
ingest path never fetches it. Today, 100% of ar5iv-only papers have
`preamble_ref=null` and `get_definitions` returns
`{definitions: [], total: 0, index_status: "absent"}` for them.

---

### notebook-preamble-recovery-m1 — Extend `notebook_fetch.py` to also pull raw `.tex` via `fetch_eprint`

**Description.** Per the scan brief's Option A: after every ar5iv-cache
hit in `tools/notebook_fetch.py`, also call
`tools.arxiv_fetch.fetch_eprint(...)` to download the arXiv `/e-print/`
tarball and extract it under `var/arxmcp/corpus/raw/<paper_id>/`. The
existing `ingest/preamble.py::extract_preamble` then short-circuits to
its happy path without modification — it reads from
`RAW_DIR / paper_id`, runs the macro regex, and emits
`var/arxmcp/corpus/parsed/<paper_id>/preamble.json` which downstream
indexers (`index_definitions.py`) and the embedder's
`load_preamble(...)` already consume.

The `fetch_eprint` helper is shipped: see `tools/arxiv_fetch.py`. It
respects the 3-second politeness contract per request to
`export.arxiv.org` and honors the same 100 MB Threat 7 cap as
`ar5iv_fetch`. No new HTTP layer, no LaTeXML subprocess, no new
dependency.

Two surfaces to extend:

1. **`tools/notebook_fetch.py`** — after a successful `try_cache(...)`
   hit, invoke a new `fetch_raw_tex_if_missing(paper_id)` helper.
   Skip-and-log on failure (treat 503 / network error the same way
   the ar5iv path treats LaTeXML miss). Keeps the notebook ingest
   robust against transient arXiv outages.

2. **`tools/_notebook_common.py`** — new
   `fetch_raw_tex_if_missing(paper_id)` helper wrapping `fetch_eprint`
   with the skip-and-log semantics. Returns `True` on success, `False`
   on skip; the caller (notebook_fetch) does not abort on `False`.

3. **`Makefile`** — add a `make ingest-recover-preambles` target that
   back-fills the 65+ already-ingested ar5iv papers without rerunning
   the full ingest. Walks
   `var/arxmcp/corpus/parsed/*/index.html` → checks for
   `var/arxmcp/corpus/raw/<paper_id>/` → if absent, calls
   `fetch_eprint` + `extract_preamble`. Idempotent.

**Acceptance criteria.**

- **[AC1]** Given a notebook with N papers ingested via
  `tools/notebook_fetch.py`, When the fetch completes, Then for every
  paper whose ar5iv pull succeeded, the directory
  `var/arxmcp/corpus/raw/<paper_id>/` exists and contains at least one
  `.tex` file. (Skip-and-log on per-paper failure is allowed and must
  be surfaced in the run summary, mirroring ar5iv's
  `fetched=N rate_limited=R missing=K` format.)
- **[AC2]** Given a paper whose raw `.tex` fetch succeeded, When
  `ingest.preamble.extract_preamble(paper_id)` runs against it, Then
  the call returns a `PreambleDoc` (not `None`) and writes
  `var/arxmcp/corpus/parsed/<paper_id>/preamble.json`.
- **[AC3]** Given the back-fill target (`make ingest-recover-preambles`),
  When run against the current tree (65+ ar5iv-only papers without
  preambles), Then ≥ 90% of those papers gain a `preamble.json` (the
  other ≤10% may legitimately have no recoverable preamble — withdrawn
  papers, malformed tarballs, etc.).
- **[AC4]** Given an arXiv 503 / network failure on a single paper's
  `/e-print/` fetch, When the notebook ingest continues, Then the
  notebook-level run does NOT abort. The paper is logged to
  `var/arxmcp/ops/parser-failures/preamble.log` with a recoverable
  status code that distinguishes "rate-limited" from "404 / withdrawn".
- **[AC5]** Given a paper whose preamble has been back-filled, When
  the next `make re-embed-all` runs against the notebook, Then the
  emitted records carry a non-null `preamble_ref` and the chunk_ids
  rotate accordingly (because `_compute_chunk_id` is preamble-
  sensitive). This is the **intended** behavior — LanceDB MVCC
  handles the version bump cleanly per the chunker-fixtures runbook.
- **[AC6]** Given a paper whose preamble has been back-filled, When
  the `get_definitions` MCP tool is invoked for that paper, Then the
  result envelope contains `total > 0` definition rows (assuming the
  paper's preamble has any `\newcommand` / `\DeclareMathOperator`
  definitions — most do). Spot-check on one canary paper in the
  implementation summary.
- **[AC7]** `ARXMCP_CONTACT_EMAIL` becomes required for
  `tools/notebook_fetch.py` (previously only required for
  `fetch_seed.py`). Document in the `notebook_fetch.py` docstring and
  the `make` target wrapper. Fail loudly with a clear error message
  if unset.
- **[X-1]** `EXPECTED_TOOL_SCHEMA_SHA256` UNCHANGED (no MCP surface
  edit; `get_definitions` already accepts `paper_id`).
- **[X-2]** `EXPECTED_BP1_SHA256` UNCHANGED.
- **[X-3]** `ruff check .` clean and `make test` green; 2778+ tests
  passing on macOS / Linux.
- **[X-4]** No `CHUNKER_VERSION` bump in this milestone — the chunker
  isn't changed. Chunk_id rotation on AC5 happens via body-content
  change (preamble bytes flow into the hash), not via a global
  version bump.

**Out of scope (Won't list).**

- Re-running `make re-embed-all` as part of this milestone. The
  re-embed is operator-driven (3-8 hour wall-clock); the AC5
  measurement happens on the operator's next `make re-embed-all` run.
- Switching to a 32K-context embedder (out of scope; deferred from
  embedder-truncation-m1).
- Sub-chunking oversized statement chunks (separate milestone).
- Changing `get_definitions`' index-status semantics. The handler
  already documents "empty result, not an error" for missing
  preambles; the fix is upstream (populate the preambles), not in
  the handler.
- A new MCP tool for preamble inspection. The
  `get_definitions` surface is sufficient.
- Threading raw-tex fetch into the FastAPI `notebooks` upload route
  (`server/routes/notebooks.py::add_paper`). That route adds a junction
  row only; ingest happens out-of-band via `notebook_ingest.py`.

**Dependencies.** None blocking. `embedder-truncation-m1`'s re-embed
ran successfully (operator confirmed); this milestone's AC5 builds
on that re-embed having landed.

**Complexity.** S (≈½ day per the scan brief's estimate).

**Specialist suggestions.** `security-reviewer` (Threat 7 surface —
adding a second egress path to `export.arxiv.org`, mirroring the
existing `arxiv_fetch.fetch_eprint` pattern).

**External writes the implementation will require.** None — the only
external request is `GET https://export.arxiv.org/e-print/<paper_id>`,
which is the SAME endpoint `tools/fetch_seed.py` already uses with
the SAME politeness contract. No new external endpoint, no PR, no
git push, no infra mutation.

**Notes for the researcher agents (phase 1).**

1. Confirm `tools/arxiv_fetch.fetch_eprint` is import-stable and that
   its return contract is compatible with extracting into
   `var/arxmcp/corpus/raw/<paper_id>/`. Check the existing usage in
   `tools/fetch_seed.py`.
2. The scan brief's option-survey (A through E) is canonical; do NOT
   re-litigate the choice of Option A unless you find a load-bearing
   constraint the scan brief missed.
3. Inspect `var/arxmcp/ops/parser-failures/preamble.log` to size the
   real back-fill scope (65 was a rough estimate from the live tree;
   confirm by walking `var/arxmcp/corpus/parsed/*/index.html` and
   diffing against `var/arxmcp/corpus/raw/*/`).
4. The politeness sleep is per-request to `export.arxiv.org`, NOT
   shared with the ar5iv budget (per the scan brief and
   `ingest/ar5iv_fetch.py:29-33`). Sleep budgets compose additively;
   make sure the helper doesn't double-sleep.
5. The `make ingest-recover-preambles` target should accept
   `ARGS="--notebook=<slug>"` to scope the back-fill to one notebook,
   matching the existing `make` target convention. Default is "all
   parsed papers."

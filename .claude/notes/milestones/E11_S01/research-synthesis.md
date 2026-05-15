# E11_S01 — Research Synthesis

Merged from [research-brief-1.md](research-brief-1.md) (reusable
primitives + MVCC reality check) and [research-brief-2.md](research-brief-2.md)
(per-paper pipeline mechanics + fallback ladder). The two briefs
converge sharply; the most consequential finding is shared:

---

## 1. Headline findings (consensus)

| # | finding | resolution |
|---|---|---|
| 1 | **The brief's `/var/arxmcp/index/lancedb/vN+1/` language is wrong.** Both researchers verified: LanceDB uses internal MVCC inside a SINGLE dataset directory. There are no `vN+1/` subdirectories; `corpus_version` is an integer LanceDB increments per write. `.claude/notes/05-storage-and-indexing.md:162-169` is explicit: "No manual version subdirectories. LanceDB MVCC manages corpus versions natively." | Use a **staging LanceDB path** (D5) to isolate bulk-ingest writes from the active dataset. The "AC: corpus-version.json still pins old version" requirement is satisfied because the active path is untouched. E11_S05 promotes by swapping. |
| 2 | **`write_chunks` advances `corpus-version.json` as a postcondition of every write** (Researcher 1 confirmed in `ingest/store.py`). Writing directly into the active dataset would break the brief's AC2 ("corpus-version.json still pins OLD version"). | Same as #1 — staging path keeps `corpus-version.json` advancement out of the active path. |
| 3 | **The 1-2 day ingest run is operator scope.** Multi-hundred-GB BitTorrent download, GPU embedding, live network calls to ar5iv/arxiv/OpenAlex/INSPIRE-HEP. **This session ships SCAFFOLDING; operator runs the ingest.** Same pattern as E10_S03b. | Synthesis explicitly splits ACs into "verifiable at code-ship" and "operator-gated." See §6. |
| 4 | **Nougat is heavy and out of practical scope at v1.** 1.2B-param Vision Transformer, ~5 GB model download, GPU-dependent throughput. The design note `.claude/notes/03-ingestion-pipeline.md:195-197` already scopes out pre-2007 PostScript. | **Defer Nougat to a follow-up.** v1 fallback ladder: ar5iv → LaTeXML → skip + log. Most no-tex papers are pre-2007 or withdrawn. |
| 5 | **Fallback ladder inversion.** The existing `tools/fetch_seed.py` fetches from `/e-print/` first; the design note `03-ingestion-pipeline.md:87-95` is explicit: "Run our local LaTeXML only on ar5iv cache misses. Saves weeks of CPU." | **ar5iv-first.** New `ingest/ar5iv_fetch.py`. LaTeXML only on cache miss. |
| 6 | **`make ingest` is currently a stub** (`exit 1`). | E11_S01 is the project landmark that makes it real. Replace with `python -m ingest.bulk_ingest`. |
| 7 | **The eval AC (`pytest --hybrid --ndcg-min=0.70`)** depends on `tests/eval/fixtures/queries.json` having a curated set. Researcher 1 noted the fixture has 4 queries (not 20) — underpowered. | Reframe the AC: **"if the fixture is curated AND corpus-version.json points at the new corpus, the test runs; else SKIPS (vacuously satisfied)."** Operator gates on E11_S04 (re-labeling) before this AC has teeth. |
| 8 | **`write_chunks` is single-writer-per-dataset** (documented in `ingest/store.py` lines 44-55). | Bulk ingest is **single-process sequential** at the write boundary. No parallel `write_chunks` calls. Loop is linear; GPU batching happens inside `embed_paper`. |

---

## 2. Load-bearing quotes

### MVCC — `.claude/notes/05-storage-and-indexing.md:162-169`

> "No manual version subdirectories (v0001/, v0002/, etc.) and no
> symlinks. LanceDB MVCC manages corpus versions natively."

### Ar5iv-first — `.claude/notes/03-ingestion-pipeline.md:87-95`

> "Run our local LaTeXML only on ar5iv cache misses. Saves weeks of
> CPU."

### Single-writer — `ingest/store.py:44-55`

> "Callers running concurrent ingest from multiple processes against
> the same dataset must serialize writes externally (e.g. a flock on
> `<lancedb_path>/.write-lock`). The Tier-0 ingestion pipeline has
> exactly one writer."

### Pre-2007 PostScript out of scope — `.claude/notes/03-ingestion-pipeline.md:195-197`

> "Pre-2007 PostScript-only papers are intentionally NOT supported at
> this layer; they go through Nougat or are skipped."

---

## 3. Design decisions

### D1. Scaffolding-only scope at code-ship; operator runs the ingest

The session delivers:
- `ingest/bulk_ingest.py` orchestrator (per-paper loop)
- `ingest/ar5iv_fetch.py` HTTP fetch + on-disk cache
- `ingest/bulk_download.sh` stub with aria2c invocation skeleton + operator instructions
- `tests/test_bulk_ingest_sanity.py` (marked `requires_full_corpus`; skipped by default — analogous to `requires_model`)
- `tests/test_ar5iv_fetch.py` mock-based unit tests
- `tests/test_bulk_ingest.py` smoke test against ONE paper (synthetic; verifies the orchestrator's call sequence)
- `docs/ops/bulk-ingest-runbook.md` operator runbook
- Updated `Makefile::ingest` target
- Updated `docs/install.md` with `aria2c` install note

The actual 1-2 day ingest (download + parse + embed + Kùzu population) is **operator scope**.

### D2. Fallback ladder: ar5iv → LaTeXML → skip-and-log

Per-paper sequence:
1. **`ar5iv_fetch.try_cache(paper_id)`** — GET `https://ar5iv.labs.arxiv.org/html/<arxiv_id>` with 5s timeout. 200 → write to `var/arxmcp/corpus/parsed/<paper_id>/index.html` and proceed.
2. **LaTeXML fallback** — only on ar5iv miss/error. If the operator has the .tex on disk (from Academic Torrents extraction), run `parse_with_latexml` via the existing `tools/arxiv_fetch.py` primitive. Without local .tex, skip.
3. **Total failure** — append JSON line to `ops/parser-failures/bulk.jsonl`. Continue.
4. **Continue** — chunker → embedder → store write.

**Nougat is deferred.** A future milestone wires it for the .tex-less case. v1 logs the failure and moves on.

### D3. ar5iv cache module — `ingest/ar5iv_fetch.py`

- HTTP GET with 5s timeout (no rate limiting; static CDN).
- 200 → cache to `var/arxmcp/cache/ar5iv/<paper_id>.html` (Makefile bootstrap already creates this dir), write a copy to the canonical parsed path.
- 404 → return None (cache miss).
- Other status / timeout → log + return None (treat as miss; LaTeXML will try the local path).
- Validation: response body must contain `<math` (sanity guard against ar5iv error pages).

### D4. Single linear loop, not job-queue

The single-writer-per-dataset constraint means the write boundary serializes regardless. GPU batching happens inside `embed_paper`. A job queue adds operational complexity (broker, workers, state) for negligible throughput gain at v1. Loop is sorted by `paper_id` for crash-resume reproducibility.

### D5. Staging LanceDB path

The active dataset stays at `config.lancedb_path` (`var/arxmcp/index/lancedb/`); bulk ingest writes to a configurable staging path defaulting to `var/arxmcp/index/lancedb-staging/`. The server's `Resources.startup` reads from `config.lancedb_path`, so it never sees the staging data until E11_S05's promotion (an atomic `mv` of `lancedb-staging/` into `lancedb/`).

**The CLI flag is `--lancedb-staging-path` with a sensible default.**

### D6. CLI flags

- `--paper-ids-file=<path>` — required at v1. The operator points at a file of newline-separated paper ids. No default 200K corpus.
- `--limit=N` — process the first N paper ids only (for smoke testing).
- `--resume` — skip papers whose chunks + embeddings sidecar already exist (idempotent re-run; the embedder's existing sidecar check makes this effectively free).
- `--dry-run` — print the per-paper action plan (which fallback path WOULD fire) without writing to LanceDB.
- `--lancedb-staging-path=<path>` — staging LanceDB; defaults to `var/arxmcp/index/lancedb-staging/`.
- `--ar5iv-cache-dir=<path>` — defaults to `var/arxmcp/cache/ar5iv/`.

### D7. Parser-failures format — JSON lines

```jsonl
{"paper_id": "2401.00001", "parsers_tried": ["ar5iv", "latexml"], "outcome": "no_tex_source", "message": "...", "timestamp": "2026-05-15T12:00:00Z"}
```

One file: `ops/parser-failures/bulk.jsonl`. Append-only. NOT one file per paper.

### D8. Progress log — every 1000 papers

Per the brief. Append to `ops/ingestion.log` (single file, structured key=value records). Include cumulative ar5iv hit rate, LaTeXML invocations, parser failures.

### D9. AC framing — verifiable now vs. operator-gated

| Brief AC | Status at code-ship |
|---|---|
| New LanceDB version ≥ 100K chunks | Operator-gated; test marked `requires_full_corpus` |
| `corpus-version.json` still pins old version | Verifiable: staging path means active marker untouched. **Test asserts the active corpus_version is unchanged after smoke ingest.** |
| `ops/parser-failures/` contains failed papers | Verifiable: smoke test against a known-broken paper id confirms the file gets a row |
| pytest --hybrid --ndcg-min=0.70 passes | Operator-gated (depends on fixture curation + ingest completion) |
| ar5iv cache hit rate ≥ 70%, logged | Operator-gated (real network access) |

The synthesis is honest: the session ships scaffolding + a smoke test. The actual 70%+ ar5iv hit rate and 100K+ chunks are operator-runtime assertions.

### D10. Smoke test — `ingest_one_paper`

A new test (`tests/test_bulk_ingest.py`) verifies the orchestrator's call sequence end-to-end against a SYNTHETIC fixture:
1. Stage a tiny `.tex` paper + a mock ar5iv response.
2. Invoke `ingest_one_paper(paper_id, ...)` via the orchestrator.
3. Assert: chunks table grew by ≥1 row, the embedder's NPZ sidecar exists, parser-failures.jsonl is empty.

Mocks the ar5iv HTTP call (`responses` library) and skips LaTeXML when ar5iv hit succeeds.

### D11. Makefile integration

Replace `ingest:` stub with:
```makefile
ingest:
	$(PYTHON) -m ingest.bulk_ingest $(ARGS)
```

Operator runs: `make ingest ARGS="--paper-ids-file=tools/seed-papers.txt --limit=5 --dry-run"`.

### D12. `bulk_download.sh` is a stub with operator instructions

```bash
#!/usr/bin/env bash
# E11_S01 — Academic Torrents bulk download (operator script).
# Reading this? You're about to download ~300 GB of arXiv source.
# 1. `command -v aria2c` (install: brew install aria2 / apt install aria2)
# 2. Find the current arXiv source magnet at
#    https://academictorrents.com/browse.php?search=arxiv
# 3. aria2c --file-allocation=none --seed-ratio=0 <magnet>
# 4. Extract to var/arxmcp/corpus/raw/
# 5. Run `make ingest ARGS="--paper-ids-file=..."`
set -euo pipefail
command -v aria2c >/dev/null || {
    echo "aria2c not found; install via brew/apt" >&2; exit 1
}
echo "OPERATOR: see comments above for the manual workflow"
exit 0
```

Documented + safe (won't accidentally start a 300 GB download).

### D13. Runbook — `docs/ops/bulk-ingest-runbook.md`

Operator-facing per the doc-layout rule. Linked from the root README's Operations section (already created in E10_S04). Covers:
- Prerequisites (aria2c, GPU optional, ARXMCP_CONTACT_EMAIL set)
- Step-by-step bulk download
- The dry-run safety valve
- `--limit=N` smoke test
- Resume semantics
- Reading `ops/ingestion.log`
- What to do when parser-failures pile up
- Pointer to E11_S05 for the actual cutover

### D14. No tool-schema changes

No new MCP tools. No tool description changes. `TOOL_SCHEMA_VERSION` stays at 6. No hash repins.

---

## 4. Forced cross-file changes

| File | Change | Why |
|---|---|---|
| `ingest/ar5iv_fetch.py` (NEW) | HTTP fetch + on-disk cache | D2, D3 |
| `ingest/bulk_ingest.py` (NEW) | Orchestrator (per-paper loop, CLI) | D1, D2, D4, D6 |
| `ingest/bulk_download.sh` (NEW) | Operator-instruction stub | D12 |
| `tests/test_ar5iv_fetch.py` (NEW) | Mock-based unit tests | D3 |
| `tests/test_bulk_ingest.py` (NEW) | Smoke test for `ingest_one_paper` | D10 |
| `tests/test_bulk_ingest_sanity.py` (NEW) | `requires_full_corpus`-marked test for 100K chunks | D9 |
| `tests/conftest.py` (or pyproject.toml markers) | Register `requires_full_corpus` marker | D9 |
| `pyproject.toml` | Add the marker | D9 |
| `Makefile` | Replace `ingest:` stub | D11 |
| `docs/ops/bulk-ingest-runbook.md` (NEW) | Operator procedure | D13 |
| `docs/install.md` | aria2c install note | D12 |

NOT touched: `server/tools.py`, hash-anchored test files, server schemas (no tool surface change).

---

## 5. Landmines

1. **MVCC layout — DO NOT create `vN+1/` subdirectories.** Use staging LanceDB path.
2. **`write_chunks` advances `corpus-version.json`** — staging path keeps it isolated.
3. **Single-writer constraint** — sequential loop, not parallel `write_chunks`.
4. **ar5iv-first** — invert the existing fetch-seed ladder.
5. **Nougat deferred** — log no-tex papers as failures.
6. **The 1-2 day ingest is operator scope** — ship scaffolding + smoke test.
7. **`tests/eval/fixtures/queries.json` is underpowered** (4 queries, not 20).
8. **`make ingest` was a stub — first real implementation.**
9. **`assert` banned** — `if … raise RuntimeError(…)`.
10. **HEREDOC commits, GPG signed, no `--no-verify`.**

---

## 6. Test surface

### AC coverage at code-ship

- **AC1 (≥100K chunks)**: marked `requires_full_corpus`, skipped by default. Operator runs with marker enabled after the bulk ingest.
- **AC2 (corpus-version.json untouched)**: smoke test asserts the active `corpus-version.json` (at `var/arxmcp/index/lancedb/`) is byte-identical before and after the smoke ingest (which writes to staging path).
- **AC3 (parser-failures populated)**: smoke test against a known-malformed paper id asserts a row appears in `ops/parser-failures/bulk.jsonl`.
- **AC4 (eval --hybrid passes)**: operator-gated. The eval test already exists; with the empty/underpowered fixture it SKIPS — vacuously satisfied.
- **AC5 (ar5iv hit rate ≥70%, logged)**: operator-gated. Smoke test asserts the ar5iv fetcher records hit/miss counts in `ops/ingestion.log` (logging mechanism present, not the actual hit rate).

### Beyond-AC tests

- `ar5iv_fetch` happy path: 200 response → file written.
- `ar5iv_fetch` miss path: 404 → returns None.
- `ar5iv_fetch` timeout path: connection timeout → returns None, no raise.
- `ar5iv_fetch` validation: 200 with no `<math` content → treat as miss.
- `bulk_ingest --dry-run` prints expected action plan, no writes.
- `bulk_ingest --limit=N` processes only the first N papers.
- `bulk_ingest --resume` skips papers with extant embedder sidecars.
- `bulk_ingest --paper-ids-file` reads the file correctly.
- Smoke test: one paper through the full pipeline against the seed.

---

## 7. Open questions remaining

None blocking. D1-D14 resolve every open question both briefs surfaced.

---

## 8. External writes required at code-ship

**None.** Operator runtime writes:
- ~300 GB to `var/arxmcp/corpus/raw/` (Academic Torrents extraction)
- HTML cache to `var/arxmcp/cache/ar5iv/`
- LanceDB rows to `var/arxmcp/index/lancedb-staging/`
- Network reads from ar5iv, arxiv.org, OpenAlex, INSPIRE-HEP
- Kùzu citation graph (existing modules)

All of these are gated on operator action.

---

## 9. Suggested implementation order

1. `ingest/ar5iv_fetch.py` — pure HTTP module; testable in isolation.
2. `tests/test_ar5iv_fetch.py` — mock-based unit tests for ar5iv.
3. `ingest/bulk_ingest.py` — orchestrator skeleton with CLI flags.
4. `tests/test_bulk_ingest.py` — smoke test against the seed.
5. `tests/test_bulk_ingest_sanity.py` — `requires_full_corpus`-marked.
6. `pyproject.toml` — register `requires_full_corpus` marker.
7. `Makefile` — replace `ingest:` stub.
8. `ingest/bulk_download.sh` — operator stub.
9. `docs/ops/bulk-ingest-runbook.md` — operator runbook.
10. `docs/install.md` — aria2c note.
11. `make test`; commit.

---

## 10. Done-when checklist

- [ ] All 5 brief ACs accounted for (some operator-gated; documented).
- [ ] `make ingest` is real (no longer `exit 1`).
- [ ] Staging-path discipline implemented — active `corpus-version.json` untouched.
- [ ] ar5iv-first ladder shipped.
- [ ] Smoke test green; `requires_full_corpus`-marked sanity test skips by default.
- [ ] Implementation summary explicitly notes:
  - Scaffolding-only scope; operator gates the actual ingest.
  - Nougat deferred to a future milestone.
  - The MVCC reality (no `vN+1/`).
  - Honest AC mapping (which verifiable at ship, which gated on operator).
- [ ] No `TOOL_SCHEMA_VERSION` bump.
- [ ] `make test` green; ruff clean.

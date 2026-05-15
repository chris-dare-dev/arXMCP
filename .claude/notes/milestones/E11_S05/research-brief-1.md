# E11_S05 Research Brief — Axis 1: Cutover Mechanics + Activation Criteria + Rollback

**Researcher:** Agent A (parallel research axis 1 of 2)
**Date:** 2026-05-15
**Milestone:** E11_S05 — Backup/restore runbook and 200K cutover activation

---

## 1. In-codebase context — actual state today

### ingest/store.py

Key constants and functions (verbatim):

```python
DEFAULT_LANCEDB_PATH = REPO_ROOT / "var" / "arxmcp" / "index" / "lancedb"
CORPUS_VERSION_MARKER_NAME = "corpus-version.json"
```

`write_corpus_version_marker` writes the marker **atomically** (PID +
UUID-suffixed `.tmp` + `os.replace`) co-located with the LanceDB dataset
directory. The marker schema is:

```json
{"chunk_count": 847, "chunker_version": "...", "created_at": "...",
 "embedder_version": "...", "paper_count": 50, "version": 3}
```

The `version` integer is the LanceDB **post-index** dataset version — the
version after `_create_indices` ran, so readers pinning to it get HNSW-
indexed ANN results. The module docstring states:

> **MVCC handshake (E04_S02).** No symlink swaps. LanceDB version int IS
> the corpus_version. Writers use the current dataset; readers call
> `dataset.checkout(version=N)`.

### ingest/bulk_ingest.py

```python
DEFAULT_LANCEDB_STAGING_PATH = (
    REPO_ROOT / "var" / "arxmcp" / "index" / "lancedb-staging"
)
```

Module docstring: *"The active `corpus-version.json` (under
`var/arxmcp/index/lancedb/`) is left untouched; E11_S05 advances it via an
atomic directory swap."* — This is the load-bearing claim: E11_S05 performs
a **directory swap**, not just a marker rewrite.

### server/corpus.py

`read_corpus_version` reads `<lancedb_path>/corpus-version.json`. Returns
`None` on absent file. Returns `CorpusVersionInfo` on success.

`open_chunks_table(lancedb_path, version)` calls `lancedb.connect(path)` →
`db.open_table("chunks")` → `tbl.checkout(version)`. The checkout is an
**in-place mutation** of the table handle. The function returns a **fresh
handle per call** — callers must not call `checkout` on a cached handle.

**Version pinning discipline (load-bearing):** the server calls
`open_chunks_table` ONCE at startup, caches the handle for process lifetime,
and **never re-checks** `corpus-version.json` during its lifetime. From
`server/resources.py`:

> The brief is load-bearing on this — the server never auto-switches
> versions; restart the process to pick up a new corpus.

And from `server/main.py` (paraphrase of lifespan): `Resources.startup` is
called once; `app.state.resources` is set; no re-startup path exists.
Cutover **requires a process restart** — there is no warm-reload path.

`/readyz` from `server/health.py` returns 200 only when
`resources.warm == True`. `warm` is set in `Resources.startup` after all
resources load. It checks `embedder`, `lancedb`, and (if enabled)
`reranker`. There is no lazy-warm path — all three must complete before
`warm = True`.

### server/main.py + server/resources.py — startup sequence

`Resources.startup`:
1. `read_corpus_version(config.lancedb_path)` — raises `CorpusNotIngestedError` if absent.
2. `open_chunks_table(lancedb_path=config.lancedb_path, version=corpus_info.version)` — pins version at startup; run in executor.
3. Eager BGE-M3 load (`_get_model`, `_get_tokenizer`).
4. Optional reranker load.
5. BM25Phase startup (loads `bm25.pkl` from staging path).
6. ANNPhase, RerankPhase.
7. RetrievalCache open.
8. Optional definitions/equations/theorem-names tables.
9. `warm = True`.

From `docs/install.md` referenced in CLAUDE.md: BGE-M3 eager load takes
~5–30s on warm HF cache. BM25 pkl load is fast (<1s). LanceDB open is fast.
**60s for `/readyz` after restart is generous** given the load sequence.

### ingest/re_embed.py — E11_S03 state sentinel

```python
DEFAULT_STATE_PATH = REPO_ROOT / "var" / "arxmcp" / "ops" / "re-embed-state.json"
```

State file has a `"status"` field. Watchdog blocks on
`{"in_progress", "starting", "interrupted"}`. Activation criterion 3 should
check for `status == "complete"` in this file.

### ops/watchdog_eval.py — E11_S04 sentinels

```python
DEFAULT_QUARANTINE_FLAG_PATH = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "eval-quarantine.flag"
)
DEFAULT_REPORT_DIR = REPO_ROOT / "var" / "arxmcp" / "ops" / "eval-reports"
RE_EMBED_STATE_PATH = REPO_ROOT / "var" / "arxmcp" / "ops" / "re-embed-state.json"
```

`find_prior_report(report_dir, current_version)` picks the most-recent
report with `corpus_version < current_version`. Reports are named
`corpus_v<N>-<ts>.json`. The `WatchdogReport` includes `ndcg5_mean`,
`alert_triggered`, `regression_pct`, `underpowered`.

The watchdog runs against `DEFAULT_LANCEDB_STAGING_PATH` by default — its
`--lancedb-staging-path` CLI argument selects the corpus to evaluate. For
the post-activation sanity check (AC5), the watchdog must be invoked with
`--lancedb-staging-path=DEFAULT_LANCEDB_PATH` (the now-active corpus).

### .claude/TIER-GATES.md — Tier-5 cutover (verbatim)

```
### Conditions (both must hold)

1. **Backfill complete:** the full 200 K paper corpus is ingested
   to a single LanceDB table.
2. **Drift watchdog stable:** the latest scheduled
   nDCG@5 measurement (per E11_S04's drift watchdog) is within 5 %
   of the previous baseline. "Within 5 %" means
   `|aggregate.ndcg5_mean - prior.ndcg5_mean| / prior.ndcg5_mean
   <= 0.05`.
```

Note: TIER-GATES.md specifies 5% for the gate definition; E11_S04's default
threshold ships at 10% for statistical robustness. `cutover.sh` should check
BOTH: the quarantine flag (watchdog's own threshold) AND that the most
recent report's `ndcg5_mean` >= 0.80.

### E11 implementation summaries — staging-discipline contracts

**E11_S01:** *"No `vN+1/` subdirectories. LanceDB uses internal MVCC
inside ONE dataset directory... We use a staging path
(`var/arxmcp/index/lancedb-staging/`) so the active dataset's
`corpus-version.json` is never advanced by bulk ingest."*

**E11_S02:** *"The delta loop writes to `var/arxmcp/index/lancedb-staging/`
via `ingest_one_paper(lancedb_staging_path=...)`. The active
`corpus-version.json` is NOT advanced; activation is E11_S05."*

**E11_S03:** *"Staging-path discipline: writes go to
`var/arxmcp/index/lancedb-staging/`. The active `corpus-version.json` is
NEVER touched."*

**E11_S04:** *"Watchdog refuses to run when the E11_S03 re-embed state file
at `var/arxmcp/ops/re-embed-state.json` reports `status='in_progress'`."*

The staging-discipline contract is consistent: **all four prior milestones
write exclusively to `lancedb-staging/`; the active path is virgin until
E11_S05 fires**.

---

## 2. Activation criteria — how cutover.sh checks each one

**Check order: cheap-first (file reads before eval runs).**

### Criterion 3 (cheapest — file read, sequential before eval)
Check `var/arxmcp/ops/re-embed-state.json` for `status == "complete"`.
If absent or `status != "complete"`, refuse with error. This confirms E11_S01
ingest completed AND E11_S03 re-embed (if applicable) finished. The brief
also says "LanceDB verify clean" — the practical check is that
`var/arxmcp/index/lancedb-staging/corpus-version.json` exists AND is parseable
(confirming `write_corpus_version_marker` ran successfully post-ingest).

### Criterion 4 (cheap — file existence check)
Check for `var/arxmcp/ops/restore-drill-passed.flag`. No such sentinel exists
today. **Recommend:** the restore drill script (peer researcher's axis)
writes this flag atomically on successful drill completion. `cutover.sh`
refuses if absent.

### Criterion 2 (medium — file read + JSON parse)
Check that `var/arxmcp/ops/eval-quarantine.flag` is **absent**. If present,
the watchdog detected a regression — refuse. Also read the most recent
report from `var/arxmcp/ops/eval-reports/` (highest-version `corpus_v<N>-*.json`
matching the staging version) and confirm `ndcg5_mean >= 0.80` AND
`alert_triggered == false`.

### Criterion 1 (medium — file read)
The brief says this "already passed before E11 begins." Practical check:
read `var/arxmcp/ops/eval/aggregate-<seed_version>.json` (produced by the
E05 eval gate for the seed corpus). The `seed_version` integer comes from the
**active** `corpus-version.json` at run start (the seed corpus IS the current
active). Confirm `ndcg5_mean >= 0.80`. If absent, the Tier-1 → Tier-2 gate
was never reached — refuse.

**Why criterion 1 before criterion 2?** Criterion 1 is a single file read;
criterion 2 requires listing a directory and parsing JSON. Both are fast in
practice. But criterion 1 represents the baseline — if the baseline eval
result is missing, running the regression check (criterion 2) has no meaning.
So: **3 → 4 → 1 → 2** is the recommended check order.

---

## 3. The MVCC activation contract — the critical point

`open_chunks_table(lancedb_path, version)` calls `lancedb.connect(path)` and
then `tbl.checkout(version)`. The `path` argument is the **filesystem path
to the LanceDB dataset directory**. The `version` integer is a LanceDB-
internal version number scoped to THAT dataset.

This creates the critical ambiguity: **the staging dataset at
`lancedb-staging/` and the active dataset at `lancedb/` are DIFFERENT
datasets.** A version integer from the staging dataset (e.g. version 4711)
is NOT the same as version 4711 in the active dataset. You cannot simply copy
`corpus-version.json` from staging to active and restart — the version integer
refers to the staging dataset, which is now at the wrong path.

**Resolution: the activation IS a directory swap.** The staging directory
MUST become the active directory. The corpus-version.json from staging is
correct as-is (it records the staging dataset's version integer, and after
the swap, the staging directory IS the active directory).

**Atomic-rename plan (POSIX atomic on same filesystem):**

```
Step 1: os.rename("lancedb/", "lancedb-prev/")
Step 2: os.rename("lancedb-staging/", "lancedb/")
```

Caveat: `os.rename` on directories fails on some platforms if the target
exists. `lancedb-prev/` must NOT exist at step 1 start. Use
`os.replace` where possible — but `os.replace` on directories fails on Linux
when the destination is non-empty. Correct approach:

- If `lancedb-prev/` exists from a prior failed cutover, abort with an
  error message instructing the operator to investigate.
- Otherwise, `os.rename("lancedb/", "lancedb-prev/")` — atomic on Linux
  (POSIX rename(2) on same-FS renames directories).
- Then `os.rename("lancedb-staging/", "lancedb/")` — atomic on same FS.

**Risk window:** between step 1 and step 2 there is a brief window where
`lancedb/` does not exist. If the server is running against `lancedb/`, its
cached handle continues to work (LanceDB table handles don't re-stat the
path on each query — they hold open file descriptors). New server starts in
this window would fail at `Resources.startup` with `FileNotFoundError`. The
window is bounded by the time between two Python `os.rename` calls —
microseconds on a local filesystem. This risk is acceptable for a single-
operator, localhost deployment.

After step 2, `lancedb/` contains the staging data. `lancedb/corpus-version.json`
exists (written by `write_corpus_version_marker` at end of bulk ingest).
Server restart reads it and gets the correct version integer — the one valid
in the now-active `lancedb/` dataset. **No rewrite of corpus-version.json
is needed.** The staging marker is correct.

---

## 4. Rollback semantics — "< 30 seconds"

The brief says: "stop server, revert `corpus-version.json`, restart."
This is incomplete. The full rollback procedure:

1. **Stop server** (signal or systemctl stop).
2. **Reverse the directory swap:**
   - `os.rename("lancedb/", "lancedb-failed-cutover-<ts>/")` — saves the
     failed-cutover data for forensics.
   - `os.rename("lancedb-prev/", "lancedb/")` — restores the pre-cutover
     active dataset.
3. **Restart server** — reads the now-restored `lancedb/corpus-version.json`
   (the old seed marker). No corpus-version.json rewrite is needed.

Two `os.rename` calls on a local filesystem: microseconds. Server stop +
restart: ~10–30s for BGE-M3 warm-up. Total well under 30 seconds.

**The brief's "revert corpus-version.json" is wrong in isolation.** The
version integer in the marker refers to the staging dataset's internal
version, not the active dataset's. After rollback, `lancedb-prev/` (now
`lancedb/`) has its own `corpus-version.json` with the correct old version
integer. Reverting the marker separately would point the server at the wrong
dataset version.

---

## 5. Post-activation health

### AC4: /readyz returns 200 within 60s

`server/health.py::readyz` returns 200 iff `resources.warm == True`.
`resources.warm` is set only after `Resources.startup` completes all 9 steps.
The slow steps are BGE-M3 load (~5–30s warm HF cache) and BM25 pkl load
(<1s). LanceDB open is fast once the directory exists. Total: ~10–35s on a
warm machine. 60s is generous — the AC is achievable.

`cutover.sh` should poll `/readyz` with `curl --fail --retry 12 --retry-delay 5`
(total budget: 60s) rather than a fixed `sleep`. This avoids a race where
the server is ready in 8s but the script sleeps 60s unnecessarily.

### AC5: watchdog reports nDCG@5 >= 0.80 on 200K corpus

This is a post-activation sanity check run by `cutover.sh` AFTER the server
restart. The watchdog's default is `--lancedb-staging-path=DEFAULT_LANCEDB_STAGING_PATH`
which after cutover is the OLD staging path (now either renamed or empty).
The post-activation check must target the NEW active corpus:

```bash
python -m ops.watchdog_eval \
  --lancedb-staging-path=var/arxmcp/index/lancedb \
  --ndcg-min=0.80
```

The watchdog uses `find_prior_report(report_dir, current_version)` to find
the prior baseline. After cutover, `current_version` is the staging corpus
version (N+K). The prior report is the most recent report with version < N+K
— likely the seed corpus eval. This comparison is valid: it confirms the
200K corpus is at least as good as the seed baseline.

---

## 6. Open questions for the implementer

**Q1: Python (`ops/cutover.py`) vs Bash (`ops/cutover.sh`)?**
Recommendation: **Python**. The brief says `.sh`, but the activation logic
involves JSON parsing (reading corpus-version.json, aggregate JSON, watchdog
reports), two `os.rename` calls, HTTP polling of `/readyz`, and subprocess
invocation of `python -m ops.watchdog_eval`. Bash + `jq` can do all of this
but error handling is harder to test. Python allows the same atomic patterns
as the rest of the codebase (`os.replace`, `os.rename`), structured logging,
and unit testability. Ship `ops/cutover.py` with an `ops/cutover.sh` thin
wrapper (`exec python -m ops.cutover "$@"`). The brief's `.sh` deliverable
is satisfied by the wrapper.

**Q2: Where does cutover.sh find the seed eval report?**
Read the active `corpus-version.json` before any swap. Its `version` integer
is the seed corpus version (N). The seed eval report is
`var/arxmcp/ops/eval/aggregate-<N>.json`. The staging corpus version (N+K)
comes from `lancedb-staging/corpus-version.json`. This means criterion 1
reads the active marker BEFORE the swap. Correct — the baseline must be
established before changing state.

**Q3: In-flight client sessions during server restart.**
From `server/main.py` lifespan: shutdown drains in-flight requests with
`asyncio.wait_for(..., timeout=30)`. After process exit, all session-id
state is gone (in-memory). The MCP shim re-establishes new sessions against
the new corpus on the next call. This is the "brief unavailability window"
the brief acknowledges. Nothing to fix; document it in the runbook.

**Q4: LanceDB `verify` command?**
The brief mentions "LanceDB verify clean." LanceDB's Python API has
`lancedb.connect(path).open_table("chunks").count_rows()` as a basic
integrity check. A deeper check is `table.checkout(version).to_arrow().num_rows`.
There is no `lancedb verify` CLI. The practical criterion 3 check is:
open the staging table at the staged version, call `count_rows()`, confirm
`> 0`. This exercises the read path without requiring a non-existent CLI.

**Q5: What if `lancedb-prev/` exists from a prior failed cutover?**
cutover.sh must check before proceeding. Recommended: refuse with:
```
FATAL: lancedb-prev/ already exists. A prior cutover may have failed.
Investigate, then rename or remove lancedb-prev/ before retrying.
```
Do not silently delete `lancedb-prev/` — it's the operator's rollback
lifeline.

---

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| `os.rename` (directory) | `var/arxmcp/index/lancedb/` → `var/arxmcp/index/lancedb-prev/` | Save old active for rollback |
| `os.rename` (directory) | `var/arxmcp/index/lancedb-staging/` → `var/arxmcp/index/lancedb/` | Promote staging to active |
| File write (atomic) | `var/arxmcp/ops/restore-drill-passed.flag` | Sentinel written by restore drill; consumed by cutover.sh criterion 4 |
| HTTP GET poll | `http://127.0.0.1:7733/readyz` | Post-restart health check (AC4) |
| subprocess | `python -m ops.watchdog_eval --lancedb-staging-path=lancedb/` | Post-activation nDCG@5 check (AC5) |
| File read | `var/arxmcp/index/lancedb/corpus-version.json` | Read active version for criterion 1 |
| File read | `var/arxmcp/index/lancedb-staging/corpus-version.json` | Read staging version for criterion 3 |
| File read | `var/arxmcp/ops/re-embed-state.json` | Criterion 3 — re-embed complete? |
| File read | `var/arxmcp/ops/eval-quarantine.flag` | Criterion 2 — watchdog quarantine absent? |
| File read | `var/arxmcp/ops/eval/aggregate-<N>.json` | Criterion 1 — seed nDCG@5 >= 0.80? |
| File read | `var/arxmcp/ops/eval-reports/corpus_v<N+K>-*.json` | Criterion 2 — staging watchdog report |
| systemctl / kill | `arxmcp-server.service` | Stop server before directory swap |
| systemctl / exec | `arxmcp-server.service` | Restart server after swap |

The two `os.rename` directory operations on the active LanceDB path are the
most consequential writes in this milestone. Both are POSIX-atomic on a
same-filesystem rename (inode reparent, no data copy), but there is a
microsecond window between them where `lancedb/` does not exist. This is
documented as acceptable for a localhost single-operator deployment.

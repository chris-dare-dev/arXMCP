# E14_S05 Research Brief 1 — In-codebase context

## 1. Load-bearing source quotes

### 1.1 The failure-mode table (verbatim, `.claude/notes/08-security-observability-ops.md` § "Failure modes and graceful degradation")

| Failure | Detection | Response |
|---|---|---|
| Embedder model API outage (when using hosted) | Timeout + 5xx counter exceeds threshold | Fall back to local embedder; tag results `degraded=true` so reranker can deprioritize cross-model hits |
| LanceDB corrupt on restart | Open fails | Fall back to previous dataset version via `dataset.checkout(version=N-1)` (see E04_S02 …); alert. No symlink swap. |
| MCP OOM from large result | Memory pressure | Hard cap `k <= 50`; hard cap response bytes 256 KB; refuse beyond |
| Reranker model load slow on cold start | Readiness probe fails | Pre-warm at server startup; readiness probe blocks shim until ready |
| LaTeXML hang | Subprocess timeout | Kill, mark paper as parser-failure, continue |
| Singleflight deadlock | (defensive) | Always pop inflight key in `try/finally` |
| Disk full | Prometheus alert on free space | Block ingestion, allow reads to continue, page operator |
| OAI-PMH endpoint 503 | HTTP retry exhausted | Pause delta loop with exponential backoff (max 1 hour) |
| arxiv.org per-paper 503 | HTTP retry exhausted | Pause `/e-print/` fetcher; queue for retry next cycle |

**That is 9 rows — the brief's "8 failure modes" undercounts by one.** The runbook must cover all 9; collapsing OAI-PMH and arxiv-per-paper into a single bucket is the only honest way to reach 8.

### 1.2 Backup and restore (verbatim § "Backup and restore")

> Strategy: nightly snapshot via `restic` (https://restic.net) to a local NAS or to Backblaze B2 … Restore drill: quarterly. Document the runbook.

What to back up: `/var/arxmcp/corpus/`, `/var/arxmcp/index/lancedb/`, `/var/arxmcp/index/kuzu/`. Caches NOT backed up.

## 2. What E11_S05 already shipped (overlap is enormous)

E11_S05 (`6d3a1fe — feat(ops): 200K cutover activation + backup/restore`, plus rectifier `03ca0a3`) **already** shipped the entire restic surface. The brief's "infra/restic/" paths are wrong — the project convention is `ops/`. Same path-drift pattern the E14_S04 brief had.

Already present at HEAD:

- **`ops/cron/arxmcp-backup.sh`** — full restic wrapper: `flock -n` reentrancy guard at `var/arxmcp/ops/.backup.lock`; sources `ops/restic-env.sh` (gitignored); calls `restic backup --json` on `var/arxmcp/index/lancedb`, `var/arxmcp/index/kuzu`, `var/arxmcp/corpus/chunks`; treats exit 3 as PARTIAL; applies retention `--keep-daily 7 --keep-weekly 4 --keep-monthly 12`; emits `var/arxmcp/ops/backup-status.json` atomically (two-phase write).
- **`ops/restic-env.sh.template`** — env template; `RESTIC_PASSWORD_FILE` discipline ("Losing the restic password = PERMANENT DATA LOSS").
- **`ops/systemd/arxmcp-backup.{service,timer}`** — Linux unit pair.
- **`ops/restore_drill.sh`** + **`ops/restore_drill_check.py`** — operator-invoked drill that restores most-recent snapshot to `/tmp/arxmcp-restore-drill/`, opens LanceDB (`row_count > 0`) + Kùzu (optional), writes `var/arxmcp/ops/restore-drill-passed.flag` (consumed by `ops/cutover.py` C4), cleans up.
- **`docs/ops/backup-restore.md`** (330 lines) — first-time setup, scheduling (systemd + cron), retention table, restore drill instructions, full catastrophic-recovery procedure, failure modes (network drop / password loss / disk full / stale lock), state-file schemas, NAS vs B2 trade-offs, **and an E14_S01 metrics-surface section** (`arxmcp_backup_last_success_timestamp_seconds`, `arxmcp_backup_status{state}`).
- **`tools/quarterly_drill_reminder.sh`** + `ops/cron/arxmcp-quarterly-drill.sh` (E14_S04) — quarterly cadence.
- **`tests/test_backup_wrapper.py`**, **`tests/test_restore_drill.py`** — already exist.

`RESTIC_PASSWORD` is **already** never in source — `ops/restic-env.sh` is gitignored and the password lives at `RESTIC_PASSWORD_FILE` (root-owned mode 0400 on Linux; owner-only on macOS).

**Restic retention vs MVCC fallback (the risk note's concern).** The wrapper backs up the **directories**, not LanceDB versions; `restic forget --prune` only prunes restic snapshots, never the live `lancedb/` directory's MVCC version dirs. The risk note is therefore directed at the wrong layer. The relevant risk is **LanceDB's own `dataset.cleanup_old_versions()`**, which `ingest/store.py` may or may not call — this brief's implementation must NOT trigger that during ingest (verify it doesn't), so the on-disk N−1 version dir survives for the F1 fallback.

## 3. What the brief is genuinely asking for (the deltas)

### 3.1 LanceDB corruption fallback in `server/resources.py` (NEW)

Today's behavior is the OPPOSITE of what the brief mandates. `server/corpus.py:185` raises `ValueError` when `tbl.checkout(version)` fails with `(ValueError, LookupError, KeyError)`; `server/resources.py:316` calls `open_chunks_table(..., version=corpus_info.version)` and lets that exception propagate; the lifespan in `server/main.py` then crashes the process. There is **no** N−1 fallback. There is **no** `degraded` state on `Resources`.

`server/health.py:160` `readyz()` only returns 200/503 with `{"status": "ready"|"not_ready", "warm": {...}}`. There is no `"status": "degraded"`, no `reason` field.

Implementation requires:
- A new `degraded: bool` + `degraded_reason: str | None` on `Resources` (or a dedicated state enum).
- In `Resources.startup()`: catch the `ValueError` from `open_chunks_table`, log `ERROR`, retry with `version=corpus_info.version - 1` (gate at `>= 1` since `version: 1` is the floor per `CorpusVersionInfo.from_dict`'s domain check), set `degraded=True, degraded_reason="corpus_corruption"`. If N−1 also fails, propagate as today (refuse to start — no point degrading past the floor).
- `readyz()` returns 503 with `{"status":"degraded", "reason":"corpus_corruption", "warm": {...}}` when `degraded=True`.

### 3.2 Reranker warm-up dummy inference (NEW — NOT shipped in E07_S07)

The brief claims "E07_S07 supposedly shipped this." **E07_S07 was never executed.** The shipped E07 milestones are only `E07_S01`–`E07_S04` (BM25, ANN, RerankPhase, integration). The reranker WARM-UP-TO-MODEL-LOAD step exists (`server/resources.py:339` calls `_load_reranker_or_raise()`), but the spec wants a *dummy inference* on **"10 randomly selected cached chunk embeddings"**. No such call exists anywhere — `grep -nE "dummy|warm" server/retrieval/rerank.py` returns nothing.

Implementation: extend `Resources.startup()` step 4 — after `_load_reranker_or_raise()`, when `config.enable_rerank=True`, sample 10 chunk rows from the freshly-opened `chunks_table`, build dummy `(query, chunk_text)` pairs, run one forward pass through the reranker model inside the executor. Block `/readyz` until done. Surface a new gauge `arxmcp_resources_warm{resource="reranker_warmed"}` if a separate signal is wanted; otherwise the existing `reranker` warm-bit covers it once we re-order.

### 3.3 Disk-full alert + `ingest-paused` sentinel (NEW — partial overlap)

- **`infra/prometheus/alerts.yml` does NOT exist.** `infra/observability/` contains only `phoenix-compose.yml`. Per the brief the file goes at `infra/prometheus/alerts.yml`; per repo convention I'd argue for `infra/observability/alerts.yml` (single subdir for all observability infra) — defer to E14_S05 implementer.
- **`var/arxmcp/ops/ingest-paused` sentinel does NOT exist.** Zero hits in the codebase (`grep -rln "ingest-paused"` returns only the roadmap brief itself).
- **`ops/cron/arxmcp-delta.sh` does NOT check any sentinel before running.** The wrapper jumps straight into `flock -n ... uv run python -m ingest.oai_delta`. `ingest/oai_delta.py` does write a **timeout** sentinel (line 600 `wrote sentinel to`), but reads no `ingest-paused` sentinel.
- The new wiring: cron wrapper checks for `${REPO_ROOT}/var/arxmcp/ops/ingest-paused`; if present, exit 0 with a log line (cron mailer surfaces it). Mirror the same guard inside `ingest/oai_delta.py` so manual invocations also honor it. The `promtool check rules` AC requires `promtool` on the dev machine — note for the implementer.

### 3.4 Hosted-embedder outage fallback (NEW — feature does not yet exist)

`server/query_encoder.py` is **BGE-M3 only**. Zero references to `voyage`, `ARXMCP_QUERY_EMBED_PROVIDER`, or any hosted-embedder path anywhere in `server/`. `server/config.py:100-213` has no `query_embed_provider` field. **This milestone introduces the configuration knob AND the fallback path.** Scope balloons fast — implementing voyage as a real provider is out of proportion to the milestone size; the right move is:
- Add `ARXMCP_QUERY_EMBED_PROVIDER` enum (`local` default; `voyage` accepted but routed through a feature-flagged stub that immediately raises a sentinel exception in v1).
- Implement the FALLBACK PATH (catch the sentinel, return local BGE-M3 result, tag `degraded=True` on result rows).
- Defer real voyage HTTP wiring to a follow-up (call it out in the brief).

## 4. Tests already passing that this milestone must not regress

`tests/test_backup_wrapper.py` and `tests/test_restore_drill.py` exist. New `tests/test_failure_modes.py` adds synthetic-corruption tests; do not duplicate the backup ones.

## 5. Documentation deltas

- `docs/ops/backup-restore.md` already covers what `docs/ops/restore-runbook.md` would. **DO NOT create a second file.** Drop or rename — keep `backup-restore.md` and add a "Restore-only" anchor section if needed.
- `docs/ops/failure-modes.md` is NEW (referenced in AC) — author it; cover all 9 failure modes from § 1.1.

## 6. Prior decisions / lessons

- E14_S04 had the same `infra/cron/` vs `ops/cron/` path-drift; resolved by following `ops/` convention.
- E14_S01 (`d20d190`) wired backup sentinels into `/metrics` via `refresh_sentinel_metrics(ops_dir)`; reuse that same `ops_dir` for an `ingest-paused` gauge.
- E11_S05's critique closed a CRITICAL + 3 HIGH + 4 MEDIUM + 1 LOW; no open retention follow-up — the partial-success "exit 3" path was the critical close.
- HANDOFF.md (`2026-05-10`) does not reference any deferred E07/E11 failure-mode work.

## Open questions

1. **`ops/cron/arxmcp-backup.sh` already implements everything the brief asks `infra/restic/nightly.sh` to provide.** Recommendation: this milestone's restic scope is a **no-op confirm** + add the retention-vs-N−1 paragraph to `docs/ops/backup-restore.md` clarifying that LanceDB version dirs live OUTSIDE restic's prune surface.
2. **`docs/ops/backup-restore.md` already covers the restore runbook.** Drop the AC's `docs/ops/restore-runbook.md` line; document `backup-restore.md` as the canonical location in the rectifier commit.
3. **Reranker warm-up is NOT explicit today** — E07_S07 never shipped. This milestone makes it explicit; sample 10 chunks from `chunks_table.to_arrow().slice(0, 10)` (deterministic, not random — random would change `/readyz` time non-deterministically per restart).
4. **`ARXMCP_QUERY_EMBED_PROVIDER` is NEW.** Default `local`; `voyage` accepted as v1 stub that triggers the fallback path. Real voyage HTTP client is out-of-scope.
5. The 9 failure modes for `docs/ops/failure-modes.md`: (1) hosted-embedder outage, (2) LanceDB corruption, (3) MCP OOM, (4) reranker cold-start, (5) LaTeXML hang, (6) singleflight deadlock (defensive), (7) disk full, (8) OAI-PMH 503, (9) arxiv.org per-paper 503.
6. **Restic retention vs LanceDB version dirs** — `ops/cron/arxmcp-backup.sh` does NOT touch LanceDB version dirs (restic prunes its own snapshots only). The actual hazard is `ingest.store` calling `dataset.cleanup_old_versions()`; grep confirms it does not. Document in the new failure-modes doc.

## External writes the implementation will require

Zero beyond local commits. The restore-drill writes test data to `/tmp/arxmcp-restore-drill/` (sandboxed); the synthetic-corruption test writes to a `tmp_path` fixture; no network egress; no remote repository writes.

---
name: storage-schema-cache-gotchas
description: LanceDB/kuzu/sqlite storage-layer landmines — cast nullability inference, per-notebook cache-path collisions, WAL busy-checkpoint corruption, uv.lock transitive downgrades.
metadata:
  type: feedback
---

Storage-layer traps where a plausible-looking change silently diverges on disk. Reproduce
each against the real backend before accepting the milestone's claim.

- **lancedb-cast-nullability-inference** (textbook-ingest-m2): `tbl.add_columns({col:
  "cast('literal' as string)"})` yields `nullable=False` because the SQL infers non-null from
  the literal — divergent from a fresh table that declared the column `nullable=True`. Always
  build BOTH the fresh and migrated paths and compare `tbl.schema.field(col).nullable`. Fix:
  `alter_columns` or COALESCE-against-typed-NULL.
- **forkC-structural-isolation-vs-persisted-cache** (notebook-retrieval-m1, HIGH): "per-X
  isolation is automatic because one process = one X" holds WITHIN a process but breaks across
  relaunches against shared on-disk state. The Tier-1 cache (`cache_sqlite.py`) keys on
  `(query,filters,k,corpus_version,level)` with NO notebook slug, and the notebook validator
  rewrites only `lancedb_path`, not `cache_db_path` (default `var/arxmcp/cache/retrieval.db`).
  corpus_version is the per-dataset LanceDB MVCC int (bridgeland=369, shimura=49 — NOT unique),
  so a fresh small notebook can collide → cross-notebook wrong results within the 1h TTL
  (`RetrievalCache.open` rehydrates all unexpired rows, no purge_other_corpus_versions).
  **General rule:** when a config validator rewrites ONE path, enumerate ALL sibling path
  fields (cache_db_path, ops_dir, data_dir, notebooks_db_path) and decide per-field whether
  sharing is benign (data_dir/ops_dir) or a collision vector (cache_db_path = HIGH).
- **busy-truncate-checkpoint-corrupts-not-staleness** (notebook-ops-hardening-m1, HIGH): a
  backup wrapper that TRUNCATE-checkpoints WAL-mode sqlite and EXCLUDES the -wal/-shm sidecars
  is WRONG to "WARN-not-fail on busy." Live-verified on Darwin: a checkpoint blocked by a
  concurrent read txn returns (busy=1) and does NOT truncate WAL — copying the main file alone
  then raises "database disk image is malformed" on open AND `PRAGMA integrity_check`. So a
  busy checkpoint ships an unreadable snapshot; the quarterly restore drill may catch it after
  retention aged out the last good copy. Fix: retry-with-backoff then mark backup PARTIAL, or
  include sidecars; never silently proceed. HIGH not CRITICAL (needs concurrent reader in the
  idle window). Also: `python3 helper 2>/dev/null || echo error` in an ops wrapper collapses
  all failure causes into one opaque token — MEDIUM on data-durability paths.
- **uv-lock-transitive-major-version-downgrade** (textbook-ingest-m5, HIGH): adding a
  `[project.optional-dependencies].<extra>` entry can silently DOWNGRADE an existing direct dep
  by a major version. m5's `mineru[pipeline]` pinned `transformers<5` → dropped 5.8.0 → 4.57.6.
  Check: `git diff <range> -- uv.lock | grep "^[-+]version = "` + `grep "^-name = "`;
  cross-check removed packages against transitive deps of direct deps. Major-version downgrade
  of a core dep (transformers powers BGE-M3 + reranker) with `requires_model` tests skipped =
  unverified change.

Related: [[synthesis-api-claim-vs-real-binding-return]], [[cli-direct-sqlite-vs-destructive-v0-v1]].

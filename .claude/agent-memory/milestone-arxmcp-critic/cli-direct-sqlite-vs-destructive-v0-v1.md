---
name: cli-direct-sqlite-vs-destructive-v0-v1
description: CLI helper that bypasses async store + writes via raw sqlite3 + leaves user_version=0 gets wiped by store's v0→v1 DROP TABLE on next server boot — CRITICAL data loss class
metadata:
  type: feedback
---

When a milestone introduces a CLI helper that directly writes via
`sqlite3.connect` + `CREATE TABLE IF NOT EXISTS notebooks (…)` + `INSERT
OR IGNORE` and DELIBERATELY does NOT touch `PRAGMA user_version` (per a
synthesis decision to avoid clobbering an async store's migration
tracker), trace the async store's v0→v1 migration:

- If v0→v1 uses `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE` → safe;
  the CLI-created table coexists.
- If v0→v1 uses `DROP TABLE IF EXISTS notebooks; CREATE TABLE
  notebooks (…)` (the destructive recreate pattern from Tier1Store-
  style migrations) → CRITICAL data loss. The CLI's row is wiped
  silently the first time the async store opens the file.

**onboarding-uplift-m2 hit this:** `tools/notebook_init.py::_register_notebook_in_sqlite`
opted out of touching `user_version` per synthesis §3 D1 (to protect
`NotebooksStore`'s migration tracker), but `NotebooksStore.open`'s v0→v1
at `server/notebooks_store.py:154-156` is `DROP TABLE IF EXISTS … ;
CREATE TABLE …` — the protection inverted into a wiper.

**The trap:** the milestone's own regression test PASSED because the
repo's `var/arxmcp/cache/notebooks.db` was already at `user_version=4`
from pre-m2 server runs. Test isolation against tmp_path would have
caught it. AND because the test fixture (line 96-127) writes to the
SHARED real DB which is already migrated.

**Why:** the synthesis treated "CLI writes notebooks row" and "server
v0→v1 migration is destructive" as independent decisions. They are
not — the destructive v0→v1 + the non-touching CLI = silent wipe on
first server boot.

**How to apply:** when reviewing any milestone that adds a CLI direct-
SQLite writer to a file owned by an async store:
1. Read the async store's v0→v1 block. Look for `DROP TABLE`.
2. If destructive, the CLI MUST either (a) set `PRAGMA user_version =
   <current store SCHEMA_VERSION>` after its CREATE TABLE so v0→v1
   becomes a no-op, OR (b) reuse the async store via `await
   Store.open()` to perform the write through the same migration
   path.
3. Demand a regression test on a FRESH tmp_path DB (user_version=0)
   that runs the CLI write THEN opens the async store THEN asserts
   the row survives. Do not accept tests that write to the shared
   repo DB — they mask the very failure.

The reciprocal of the [[synthesis-api-claim-vs-real-binding-return]]
class but on the migration-tracker axis: synthesis says "neither store
needs the other to have run first" — verify by independently running
"CLI cold → server open" AND "server open → CLI" sequences against a
fresh DB and asserting both directions are non-destructive.

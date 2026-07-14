# Critique — source-truth-m3 — merged (adversary + arxmcp)

**Critic:** milestone-adversary-critic + milestone-arxmcp-critic (orchestrator-merged, id-remapped)
**Commit range:** 624fd94..d2d9fe6
**Diff stats:** 5 files, +1355/-4 LOC (code +561, tests +697, notes +97)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. **C0 H0.** The core properties are correctly implemented and genuinely (not
vacuously) tested: content-hash determinism (`snapshot`-only, `revisions` array explicitly sorted,
canonicalization reused verbatim from `_serialize_tools`), AC2 invalidation with SYNTHETIC
withdrawn+superseded fixtures, the 3-way license census, registry-absent degrade, and the net-new
tools/list byte-stability pin (`EXPECTED_TOOL_SCHEMA_SHA256` untouched + green). One substantive
MEDIUM: the manifest `resources/read` is **not pure** — it creates the `operator_settings` table
on a file-present/table-absent `notebooks.db` (empirically confirmed), contradicting the module's
own read-only claim (benign per §4.8's operational-write carve-out, but the absolute claim is false
+ the test gap is real). Plus the diff-size flag and two LOWs.

## Executive summary

- [MEDIUM] A manifest `resources/read` WRITES to `notebooks.db`: `OperatorSettingsStore.open()` runs `CREATE TABLE IF NOT EXISTS operator_settings` + a sentinel INSERT when the table is absent (the `is_file()` guard prevents FILE creation, not TABLE creation) — contradicting `corpus_manifest.py`'s "read NEVER writes" docstring + brief-2 §5. The sole read-purity test covers only the absent-FILE case, not the reachable file-present/table-absent path.
- [MEDIUM] Code diff is +561 LOC (412 logic LOC in one cohesive new module), over the 400-LOC review-burden auto-flag — flag for conscious acceptance, not a defect.
- [LOW] Per-notebook failure isolation is piece-wise (cross-critic): `_read_override` (`:455`) + the `_build_notebook_block` loop (`:486`) sit OUTSIDE any block-level `try/except`; a non-`(DatabaseError|OSError|ValueError)` exception would fail the WHOLE `resources/read`. Holds today; fragile to future edits.
- [LOW] The injection-surface claim ("`override.note` is the only operator-freeform field") understates it — `set_by`/`set_at`/`note` are all operator-authored (the payload-wide escape-on-emit protects all three, so no functional gap; only an inaccurate narrowing).
- [CLEAN] Both hashes verified (Axis 1); allowlist-by-projection; `<retrieved_manifest>` wrap; override fail-safe (6 branches tested); registry-absent never opens a missing db.

## Findings

**M1 — Manifest `resources/read` creates the `operator_settings` table (a write) despite the read-only claim** (MEDIUM)

**Where:** `server/corpus_manifest.py:354`
**Anchor:** `store = await OperatorSettingsStore.open`
**What:** `_read_override` guards only on `settings_db_path.is_file()`, then calls `OperatorSettingsStore.open()`, whose `_open_sync` → `_apply_migrations` unconditionally runs `CREATE TABLE IF NOT EXISTS operator_settings` + (when the table was absent) an `INSERT OR REPLACE` sentinel row — so a `resources/read` writes to `notebooks.db`.
**Why it matters:** It contradicts the module's own binding claim (`corpus_manifest.py:33-39` "Read-only (§4.8) ... no `set_setting`/`.set()` anywhere in this path"; brief-2 §5 "No write call appears anywhere in this path"); downstream R4/R5 receipts are meant to cite this resource as provably read-only. Reachable on any server whose operator never persisted a setting (the lifespan never opens the settings store). Empirically confirmed: build_manifest against a freshly-created `notebooks.db` turned `operator_settings` from absent to present. MEDIUM not HIGH: §4.8's binding scope is *corpus* state and explicitly carves out server-internal operational SQLite writes — a benign, idempotent bookkeeping write, not a corpus mutation or security exposure. The defect is the false absolute claim + the test gap.
**Proposed fix:** Make the override read genuinely pure — open a read-only sqlite3 connection (`sqlite3.connect(f"file:{path}?mode=ro", uri=True)`) or first `SELECT name FROM sqlite_master WHERE type='table' AND name='operator_settings'` and return `_OVERRIDE_DISABLED` if absent, bypassing `OperatorSettingsStore.open`'s migration. (If the benign table-creation is instead accepted, correct the three docstrings + brief-2 §5 and add the covering test.)
**Regression-guard:** A test that opens a `NotebooksStore` on a fresh `notebooks.db` (operator_settings absent), snapshots `sqlite_master` table names, runs `build_manifest(..., settings_db_path=<that db>)`, and asserts the table set is unchanged.
**Source critic:** milestone-adversary-critic
**Source axis:** Data-plane boundary (read-only, §4.8)

**M2 — Code diff exceeds the 400-LOC review-burden threshold** (MEDIUM)

**Where:** `server/corpus_manifest.py:1`
**Anchor:** `"""Content-addressed corpus manifest buil`
**What:** The diff adds 561 code LOC (506 in the new `corpus_manifest.py`, ~412 logic; +40 `mcp_resources.py`, +15 `tools.py`), over the 400-LOC code auto-flag.
**Why it matters:** ">400 LOC" maps to a review-risk flag. Here the excess is a single cohesive, single-concern new module (~40% docstrings), fully covered by 697 test LOC / 24 tests, no cross-cutting edits — risk materially below the rubric's worst case.
**Proposed fix:** Accept the diff size as-is (splitting a self-contained provenance module adds churn without reducing risk); record the conscious acceptance in the Phase-4 disposition.
**Regression-guard:** N/A (governance flag).
**Source critic:** milestone-adversary-critic
**Source axis:** Diff size / review burden

**L1 — Per-notebook failure isolation is piece-wise, not a blanket guard** (LOW)

**Where:** `server/corpus_manifest.py:455`
**Anchor:** `block["override"] = await _read_override(`
**What:** `_build_notebook_block` isolates the corpus-version read (`_safe_read_corpus_version`) and the registry read (`_load_records`, `try/except (sqlite3.DatabaseError, OSError, ValueError)`), but the final `_read_override` call — and the per-notebook loop in `build_manifest` (`:486`) — sit OUTSIDE any block-level `try/except`, relying solely on `_read_override`'s narrower internal `(sqlite3.DatabaseError, OSError)` catch.
**Why it matters:** The milestone's headline property (brief-2 §1.3/§5/risk-4) is that one unhealthy notebook degrades to `registry_present:false` and never fails the whole `resources/read`. A non-`(DatabaseError|OSError|ValueError)` exception (e.g. `sqlite3.InterfaceError`, a sibling of `DatabaseError`) would escape and fail the entire read. Holds today (all reachable exceptions are caught); fragile to future edits.
**Proposed fix:** Wrap the `_build_notebook_block(...)` call in the loop in a blanket `except Exception` that degrades that one notebook to `{registry_present:False, registry_error:type(exc).__name__}` (reusing the existing degrade shape + no-path-leak discipline), so the invariant holds unconditionally.
**Regression-guard:** A test seeding two notebooks where one raises a non-`(DatabaseError|OSError|ValueError)` exception during block assembly (monkeypatch `_read_override` to raise `RuntimeError`) and asserting the sibling still resolves + the manifest still hashes.
**Source critic:** milestone-adversary-critic + milestone-arxmcp-critic
**Source axis:** Per-notebook failure isolation / Axis 3

**L2 — Injection-surface described as one field when three are operator-freeform** (LOW)

**Where:** `server/corpus_manifest.py:391`
**Anchor:** `"set_by": parsed.get("set_by"),`
**What:** `_read_override` surfaces `set_by`, `set_at`, and `note` verbatim from the operator-authored JSON blob (uncoerced), but brief-2 §5 + `corpus_manifest.py:252-253`/`mcp_resources.py:219` describe `override.note` as "the only operator-freeform field."
**Why it matters:** All three carry operator strings into the hashed, wrapped payload. NO functional gap today — `wrap_retrieved_text` escapes the delimiter over the whole serialized payload, so all three are equally protected — but the "one field" framing is a latent trap: a future refactor to per-field escaping would silently miss `set_by`/`set_at`.
**Proposed fix:** Reword the claim to "three operator-authored fields (`set_by`/`set_at`/`note`), all neutralized by the payload-wide escape-on-emit"; optionally coerce the three to `str` in `_read_override`. Extend `test_override_note_delimiter_breakout_is_escaped` to place the breakout payload in `set_by` too.
**Regression-guard:** (optional for LOW) the extended delimiter-breakout test above.
**Source critic:** milestone-adversary-critic
**Source axis:** Injection surface / §4.9 trust language

## What was done well

- **Content-hash determinism handled correctly** — `compute_manifest_hash` hashes `snapshot` ALONE with the exact `_serialize_tools` canonicalization; the three wire fields sit structurally outside the boundary; the array-order landmine is closed by explicitly sorting both `revisions` and the `rollup` input by `(work_id, arxiv_version)`; read-stability verified across two reads.
- **AC2 proven with SYNTHETIC `withdrawn` AND `superseded` fixtures** (not a vacuous live-only pass), plus the free `0-invalidated → rollup == active_rollup` invariant; invalidated rows excluded from `active_rollup_sha256` yet retained in the full list + `rollup_sha256` + `count_total`.
- **tools/list byte-stability pinned with a net-new manifest-specific test** that recomputes vs `EXPECTED_TOOL_SCHEMA_SHA256` rather than re-pinning; the wrap-tag lives in `wrap_retrieved_text`, never `ALL_TOOLS`.
- **The wrap-tag landmine correctly fixed** — `_WRAP_TAG_MANIFEST` + a `"manifest"` dispatch entry; payload verifiably wraps as `<retrieved_manifest>`, with an `override.note` delimiter-breakout escaped end-to-end.
- **Registry-absent degrade never opens a missing `documents.db`** (`is_file()`-guarded, tested); a corrupt DB is isolated to one notebook and the whole manifest still hashes.
- **Override fail-safe is thorough** — absent key, missing file, malformed JSON, missing `enabled`, non-bool `enabled`, unreadable store each degrade to disabled (WARNING-logged, never raised); all tested.
- **§4.9 honored** — 3-way census imports the `LICENSE_STATUS_*` constants (not literals), `unknown` never folded, `total` explicit, registry vs corpus counts kept independent (no false reconcile).
- **Clean process** — no `assert`-for-invariant in production; GPG-signed with the `Co-Authored-By: Claude Opus 4.8` trailer; conventional `feat(server):` subject <50 chars; no `roadmap.yaml`/`state.json` edit (one-writer respected).

Severity counts: C0 H0 M2 L2

## Recommended rectification order

M1, L1, L2, M2

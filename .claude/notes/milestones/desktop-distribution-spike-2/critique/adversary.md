# Critique — desktop-distribution-spike-2 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** e8f149dbba496a951a8a971a572d8a60fab4a906..fd5e625bd668731d38ff29e46d0870270b24f116
**Diff stats:** 4 files, 328 LOC
**Critique format version:** 1.0

## Verdict

DO-NOT-SHIP

The spike is correctly scoped and its core path-containment primitive is sound, but the evidence does not yet support its conditional GO. The supposedly exact inventory misses and misclassifies live writers, while the launcher proof leaves known Windows MinerU state variables outside the root. Two smaller prototype holes should be closed at the same time because they can silently admit alias escapes or destroy an existing probe-named file.

## Executive summary

- [HIGH] The runtime-write inventory is neither exhaustive nor exact, leaving AC1 and AC4 unmet.
- [HIGH] The launcher redirect set omits Windows profile/AppData variables that the current MinerU subprocess explicitly inherits for mutable state.
- [MEDIUM] The resolver ignores compatibility aliases present in its environment mapping, so strict alias containment is not proved end to end.
- [MEDIUM] The fixed-name writability probe overwrites and deletes a pre-existing file.

## Findings

**H1 — Runtime-write inventory omits and misclassifies live writers** (HIGH)

**Where:** `.claude/notes/spikes/desktop-distribution-spike-2.md:35`
**Anchor:** `| Area / mode | Exact remaining owners | Current default or destination |`
**What:** The table labelled “Exact remaining owners” omits the installed `server/health.py::refresh_disk_free_metric` writer, misclassifies its `tools.ingest_sentinel` write path as offline-only, omits write-capable `tools/arxiv_fetch.py` and `tools/quarterly_drill_reminder.sh`, and names nonexistent `ops/backup.sh`.
**Why it matters:** A migration driven by this inventory can leave active writes on legacy repo/CWD/profile paths, so the milestone's inventory and exact-call-site acceptance criteria are not met.
**Proposed fix:** Replace the grouped prose list with a checked owner-by-owner inventory containing module and symbol, current default/override, installed-versus-offline mode, and current containment status; include the omitted owners and correct the backup script to `ops/cron/arxmcp-backup.sh`.
**Regression-guard:** Add `test_inventory_covers_known_write_owners`, backed by a machine-readable owner list, and require it to include the lifespan disk-pressure sentinel path, arXiv fetch extraction, and quarterly reminder writer.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**H2 — Windows MinerU state still escapes the launcher root** (HIGH)

**Where:** `tests/test_desktop_data_root_spike.py:110`
**Anchor:** `"ARXMCP_DATA_DIR": ".", "HF_HOME": "cache/huggingface",`
**What:** `launcher_environment()` redirects `HOME` and temp/cache variables but omits `USERPROFILE`, `LOCALAPPDATA`, and `APPDATA`, although `ingest/textbook_parser.py` explicitly preserves those Windows variables as MinerU configuration and cache locations.
**Why it matters:** Applying this necessarily partial environment as a launcher overlay on Windows leaves known mutable MinerU state outside `ARXMCP_DATA_DIR`, contradicting the one-root decision and invalidating the cross-platform GO evidence.
**Proposed fix:** Assign all three Windows profile/AppData variables to deliberate descendants of the data root and model the resulting overlay through the MinerU scrubber; document any variable that cannot be redirected as a NO-GO/fallback trigger.
**Regression-guard:** Add a platform-independent Windows-environment fixture that starts with host `USERPROFILE`/`LOCALAPPDATA`/`APPDATA`, applies the launcher redirects and MinerU scrub, then asserts every known mutable destination canonicalizes below the root.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**M1 — Fixed probe name can destroy an existing file** (MEDIUM)

**Where:** `tests/test_desktop_data_root_spike.py:121`
**Anchor:** `marker = self.path("tmp") / ".arxmcp-write-probe"`
**What:** `prepare()` overwrites the fixed `.arxmcp-write-probe` path and unconditionally deletes it, so a pre-existing file at that name is lost.
**Why it matters:** A nominally diagnostic preparation step can destroy operator data and concurrent preparations race on the same pathname.
**Proposed fix:** Create the probe with an exclusive unique temporary-file primitive inside `tmp/`, retain the exact path returned by that primitive, and unlink only the file this invocation created.
**Regression-guard:** Add a test that seeds `tmp/.arxmcp-write-probe`, runs `prepare()`, and verifies the seeded bytes and pathname survive unchanged.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**M2 — Resolver does not enforce aliases supplied in its environment** (MEDIUM)

**Where:** `tests/test_desktop_data_root_spike.py:64`
**Anchor:** `raw = env.get("ARXMCP_DATA_DIR", "")`
**What:** `resolve()` consumes only `ARXMCP_DATA_DIR`, so an installed environment containing `ARXMCP_CACHE_DB_PATH=/outside` succeeds unless a separate caller remembers to invoke `compatibility_alias()` manually.
**Why it matters:** The executable prototype does not prove strict installed-mode alias precedence end to end, allowing the production migration to copy a resolver that silently accepts the escape AC4 is meant to prevent.
**Proposed fix:** Have `resolve()` canonicalize every non-empty retained alias from the supplied environment into a frozen alias mapping, or expose one mandatory environment-validation operation that returns the complete typed object; do not rely on optional per-alias calls.
**Regression-guard:** Add a test that passes an out-of-root alias in the same environment mapping as an otherwise valid installed root and asserts resolution fails with the offending variable and resolved path.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

## What was done well

- The implementation respected the spike boundary: no production consumer, manifest, dependency, MCP schema, or prompt hash changed.
- The frozen, slotted value object cleanly separates pure resolution from filesystem preparation.
- `resolve(strict=False)` followed by `relative_to` is the right primitive for existing-prefix symlinks and lexical containment.
- Source fallback, installed platform-default injection, explicit container roots, relative-root deprecation, Unicode, whitespace, and missing-root behavior all have focused executable coverage.
- The ADR states the symlink TOCTOU limit honestly instead of claiming descriptor-level confinement.
- The compatibility section preserves the seven current aliases and records a sensible migration order before changing installed defaults.
- The six focused tests and focused Ruff gate pass independently; the reported full gate is also recorded in the implementation synthesis.
- The implementation commit is GPG-signed, carries the required co-author trailer, performs no external write, and stays below the 400-LOC review threshold.

Severity counts: C0 H2 M2 L0

## Recommended rectification order

H1, H2, M2, M1

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:

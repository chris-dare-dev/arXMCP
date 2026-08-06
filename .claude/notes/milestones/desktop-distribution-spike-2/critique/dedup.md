# Critique (merged) — desktop-distribution-spike-2

**Critics:** milestone-adversary-critic, milestone-arxmcp-critic
**Commit range:** e8f149dbba496a951a8a971a572d8a60fab4a906..fd5e625bd668731d38ff29e46d0870270b24f116
**Diff stats:** 4 files, 328 LOC
**Critique format version:** 1.0

> **Merge note.** Each critic authored its ids from 1 within its own file, so
> they collided across files. `findings.py merge` renumbered them into one
> gapless per-severity sequence in critic dispatch order; bodies are verbatim.
> **Phase 4 dispositions attach to the MERGED ids below**, not to the ids in
> the per-critic files. Re-running merge after a critic file changes will shift
> these ids - see milestone-pipeline-critique-format.md.
>
> - `milestone-adversary-critic` (adversary.md): ids unchanged
> - `milestone-arxmcp-critic` (arxmcp.md): H1->H3, H2->H4, M1->M3, M2->M4

## Verdict

**DO-NOT-SHIP** — the most severe of the per-critic verdicts below.

### milestone-adversary-critic — DO-NOT-SHIP

DO-NOT-SHIP

The spike is correctly scoped and its core path-containment primitive is sound, but the evidence does not yet support its conditional GO. The supposedly exact inventory misses and misclassifies live writers, while the launcher proof leaves known Windows MinerU state variables outside the root. Two smaller prototype holes should be closed at the same time because they can silently admit alias escapes or destroy an existing probe-named file.

### milestone-arxmcp-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES

The resolver is a disciplined, local-first prototype and the focused suite is green, but its only real write can escape the selected root through a pre-existing probe symlink. The ADR's inventory also cannot support the promised migration because it omits and misclassifies active installed writers while labelling the owner list exact. Two narrower fixture gaps leave Windows read-only behavior and the container mount half of the contract unproved.

## Executive summary — milestone-adversary-critic

- [HIGH] The runtime-write inventory is neither exhaustive nor exact, leaving AC1 and AC4 unmet.
- [HIGH] The launcher redirect set omits Windows profile/AppData variables that the current MinerU subprocess explicitly inherits for mutable state.
- [MEDIUM] The resolver ignores compatibility aliases present in its environment mapping, so strict alias containment is not proved end to end.
- [MEDIUM] The fixed-name writability probe overwrites and deletes a pre-existing file.

## Executive summary — milestone-arxmcp-critic

- [HIGH] `prepare()` follows a predictable pre-existing marker symlink, overwrites its target outside `ARXMCP_DATA_DIR`, and then removes the symlink; the spike's symlink-containment claim is therefore false for its only write.
- [HIGH] The ADR labels its owner column exact but omits the installed disk-full sentinel chain and installed `arxiv_fetch` writer, while classifying `tools/ingest_sentinel.py` as offline-only.
- [MEDIUM] The only read-only-application test is skipped wholesale on Windows, despite the research synthesis calling for a portable injected-failure/write-observation companion.
- [MEDIUM] The container case checks environment strings under a temporary directory but models no writable mount, so it cannot prove the required root-to-volume agreement.
- [CLEAN] Cache byte-stability, math fidelity, MCP wire behavior, tier sequencing, and the no-fork policy are untouched; no production consumer, schema, prompt, dependency, or manifest changed.

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

**H3 — Write probe follows a pre-existing symlink outside the root** (HIGH)

**Where:** `tests/test_desktop_data_root_spike.py:125`
**Anchor:** `        marker.write_bytes(b"probe")`
**What:** The fixed `.arxmcp-write-probe` path is opened non-exclusively and with normal symlink following, so a symlink already present at that name is not checked by `resolve()` and causes `prepare()` to truncate its out-of-root target before line 127 unlinks the symlink; an existing regular file at the marker name is likewise overwritten and deleted.
**Why it matters:** This violates the milestone's load-bearing one-root and symlink-containment invariant on the prototype's only actual write, so copying this contract into m1 would permit out-of-root modification or local data loss without any race being required.
**Proposed fix:** Create the probe with an exclusive, no-follow operation (for example `os.open` with `O_CREAT | O_EXCL | O_WRONLY` and `O_NOFOLLOW` where available, or an equivalently secure temporary-file primitive in the already-canonicalized `tmp` directory), close it, and unlink only the inode that this invocation created; retain the ADR's separate acknowledgement of directory-swap TOCTOU.
**Regression-guard:** Add one test that pre-creates `.arxmcp-write-probe` as a symlink to an outside sentinel and one with a regular sentinel, then assert `prepare()` fails without changing either target or deleting either pre-existing entry.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage

**H4 — The runtime-write inventory is not exact or exhaustive** (HIGH)

**Where:** `.claude/notes/spikes/desktop-distribution-spike-2.md:35`
**Anchor:** `| Area / mode | Exact remaining owners |`
**What:** The column labelled `Exact remaining owners` omits the installed `server/main.py:521` → `server/metrics_refresh.py` → `server/health.py:1231,1260` → `tools/ingest_sentinel.py` write/clear chain (and instead places `tools/ingest_sentinel.py` in the `Offline tools` row), omits `tools/arxiv_fetch.py` even though installed notebook fetch reaches its filesystem writes through `tools/_notebook_common.py:311`, and omits write-capable scoped scripts such as `ingest/bulk_download.sh`, `tools/quarterly_drill_reminder.sh`, and `tools/sbom.sh` from the developer/ingest classifications.
**Why it matters:** AC1 and AC4 require all runtime writes, correct installed-versus-developer classification, and exact remaining call sites; m1 following this table can migrate every named row and still leave an always-on installed writer or spawned writer on its legacy path.
**Proposed fix:** Replace the grouped brace lists with a reproducible inventory appendix containing one row per concrete `file:symbol` (or shell line), current default/destination, writer versus read-only role, installed/spawned/offline/external classification, and intended resolver child or explicit exception; include indirect call chains where a module has more than one runtime role.
**Regression-guard:** Add a frozen inventory-coverage test or checked script that enumerates known filesystem-mutating primitives and subprocess/output owners in `server/`, `ingest/`, `tools/`, `shim/`, and `ops/`, then requires every discovered file to have a classified inventory entry or an explicit reviewed exemption.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first constraint

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

**M3 — Read-only application coverage disappears on Windows** (MEDIUM)

**Where:** `tests/test_desktop_data_root_spike.py:183`
**Anchor:** `@pytest.mark.skipif(sys.platform == "win32", reason="chmod is not authoritative")`
**What:** The sole read-only-application fixture is skipped on Windows and no platform-neutral injected write denial or write-observation fixture replaces the non-portable `chmod` evidence.
**Why it matters:** AC3 claims read-only application locations are verified, but a desktop-distribution implementation can regress to a package- or CWD-relative write on Windows without this spike supplying any executable guard.
**Proposed fix:** Keep the POSIX permission test as native evidence and add a platform-neutral companion that instruments or injects filesystem operations so writes to the simulated package/CWD raise while writes below the data root are recorded and allowed; run that companion on every platform.
**Regression-guard:** A non-skipped test on Windows and POSIX that fails if any observed create/write/rename/unlink target is outside `ApplicationPaths.root` and proves `prepare()` still succeeds with the application location denied.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M4 — Container fixture proves paths but not the mounted root** (MEDIUM)

**Where:** `tests/test_desktop_data_root_spike.py:210`
**Anchor:** `    mount = tmp_path / "container-mount"`
**What:** The container fixture names a host temporary directory `mount` and checks only that returned environment values are descendants, without representing a container volume target, its read/write mode, or the required one-to-one agreement between `ARXMCP_DATA_DIR` and the mounted path.
**Why it matters:** A container can satisfy every current assertion while the declared root is unmounted, mounted read-only, or different from the one writable volume, which is the exact Docker/Compose failure the spike is meant to expose before fallback behavior changes.
**Proposed fix:** Add a test-only container fixture carrying environment plus volume declarations and validate that the canonical root is covered by exactly one writable application-data mount; keep the current Compose file as negative evidence and add a prospective overlay fixture rather than changing production manifests in this spike.
**Regression-guard:** Parameterize missing, read-only, mismatched, duplicate, and matching-RW mount cases; only the matching single mount should pass container resolution.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first constraint

## What was done well

### From milestone-adversary-critic

- The implementation respected the spike boundary: no production consumer, manifest, dependency, MCP schema, or prompt hash changed.
- The frozen, slotted value object cleanly separates pure resolution from filesystem preparation.
- `resolve(strict=False)` followed by `relative_to` is the right primitive for existing-prefix symlinks and lexical containment.
- Source fallback, installed platform-default injection, explicit container roots, relative-root deprecation, Unicode, whitespace, and missing-root behavior all have focused executable coverage.
- The ADR states the symlink TOCTOU limit honestly instead of claiming descriptor-level confinement.
- The compatibility section preserves the seven current aliases and records a sensible migration order before changing installed defaults.
- The six focused tests and focused Ruff gate pass independently; the reported full gate is also recorded in the implementation synthesis.
- The implementation commit is GPG-signed, carries the required co-author trailer, performs no external write, and stays below the 400-LOC review threshold.

### From milestone-arxmcp-critic

- The spike respected its prototype-only boundary: no production path consumer, dependency lock, MCP schema, prompt constant, Dockerfile, Compose file, or K8s manifest changed.
- `ApplicationPaths` is frozen and slotted, and resolution is cleanly separated from directory preparation; constructing a missing root performs no write.
- Explicit installed/container roots are required to be absolute, while the temporary source-relative compatibility path is resolved once against the captured startup CWD and emits a deprecation warning.
- Canonicalization uses `resolve(strict=False)` plus `relative_to`, correctly rejecting the tested existing descendant-symlink escape and canonicalizing a symlinked root.
- The fixed index layout preserves the canonical `index/kuzu` spelling, keeps all first-party paths local, and introduces no cloud or multi-host dependency.
- Compatibility aliases are allow-listed and out-of-root absolute targets are rejected rather than silently weakening the one-root claim.
- The ADR is unusually candid about residual limits: current Compose and K8s gaps, symlink-swap TOCTOU, migration ordering, and a genuine NO-GO fallback are all stated rather than hidden behind the conditional GO.
- The six focused tests and focused Ruff check pass independently; the macOS `KMP_DUPLICATE_LIB_OK` guard remains intact in `tests/conftest.py`.
- Cache byte-stability, math-content fidelity, MCP 2025-06-18 response semantics, tier sequencing, and the no-fork policy are axis-verified clean because the diff does not touch their production surfaces.

Severity counts: C0 H4 M4 L0


## Cross-critic agreement

The following findings cluster within 5 lines of each other in the same file. Multiple critics flagged the same area - these are the strongest signals to fix first.

- **H1, H4** at `.claude/notes/spikes/desktop-distribution-spike-2.md:35-35` (HIGH): Runtime-write inventory omits and misclassifies live writers; The runtime-write inventory is not exact or exhaustive
- **M1, H3** at `tests/test_desktop_data_root_spike.py:121-125` (HIGH): Fixed probe name can destroy an existing file; Write probe follows a pre-existing symlink outside the root

## Recommended rectification order

H1, H2, H3, H4, M2, M1, M3, M4

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:

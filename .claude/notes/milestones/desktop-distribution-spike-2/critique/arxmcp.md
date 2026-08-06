# Critique — desktop-distribution-spike-2 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** e8f149dbba496a951a8a971a572d8a60fab4a906..fd5e625bd668731d38ff29e46d0870270b24f116
**Diff stats:** 4 files, 328 LOC (+328/-0)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The resolver is a disciplined, local-first prototype and the focused suite is green, but its only real write can escape the selected root through a pre-existing probe symlink. The ADR's inventory also cannot support the promised migration because it omits and misclassifies active installed writers while labelling the owner list exact. Two narrower fixture gaps leave Windows read-only behavior and the container mount half of the contract unproved.

## Executive summary

- [HIGH] `prepare()` follows a predictable pre-existing marker symlink, overwrites its target outside `ARXMCP_DATA_DIR`, and then removes the symlink; the spike's symlink-containment claim is therefore false for its only write.
- [HIGH] The ADR labels its owner column exact but omits the installed disk-full sentinel chain and installed `arxiv_fetch` writer, while classifying `tools/ingest_sentinel.py` as offline-only.
- [MEDIUM] The only read-only-application test is skipped wholesale on Windows, despite the research synthesis calling for a portable injected-failure/write-observation companion.
- [MEDIUM] The container case checks environment strings under a temporary directory but models no writable mount, so it cannot prove the required root-to-volume agreement.
- [CLEAN] Cache byte-stability, math fidelity, MCP wire behavior, tier sequencing, and the no-fork policy are untouched; no production consumer, schema, prompt, dependency, or manifest changed.

## Findings

**H1 — Write probe follows a pre-existing symlink outside the root** (HIGH)

**Where:** `tests/test_desktop_data_root_spike.py:125`
**Anchor:** `        marker.write_bytes(b"probe")`
**What:** The fixed `.arxmcp-write-probe` path is opened non-exclusively and with normal symlink following, so a symlink already present at that name is not checked by `resolve()` and causes `prepare()` to truncate its out-of-root target before line 127 unlinks the symlink; an existing regular file at the marker name is likewise overwritten and deleted.
**Why it matters:** This violates the milestone's load-bearing one-root and symlink-containment invariant on the prototype's only actual write, so copying this contract into m1 would permit out-of-root modification or local data loss without any race being required.
**Proposed fix:** Create the probe with an exclusive, no-follow operation (for example `os.open` with `O_CREAT | O_EXCL | O_WRONLY` and `O_NOFOLLOW` where available, or an equivalently secure temporary-file primitive in the already-canonicalized `tmp` directory), close it, and unlink only the inode that this invocation created; retain the ADR's separate acknowledgement of directory-swap TOCTOU.
**Regression-guard:** Add one test that pre-creates `.arxmcp-write-probe` as a symlink to an outside sentinel and one with a regular sentinel, then assert `prepare()` fails without changing either target or deleting either pre-existing entry.
**Source critic:** milestone-arxmcp-critic
**Source axis:** security threat-model coverage

**H2 — The runtime-write inventory is not exact or exhaustive** (HIGH)

**Where:** `.claude/notes/spikes/desktop-distribution-spike-2.md:35`
**Anchor:** `| Area / mode | Exact remaining owners |`
**What:** The column labelled `Exact remaining owners` omits the installed `server/main.py:521` → `server/metrics_refresh.py` → `server/health.py:1231,1260` → `tools/ingest_sentinel.py` write/clear chain (and instead places `tools/ingest_sentinel.py` in the `Offline tools` row), omits `tools/arxiv_fetch.py` even though installed notebook fetch reaches its filesystem writes through `tools/_notebook_common.py:311`, and omits write-capable scoped scripts such as `ingest/bulk_download.sh`, `tools/quarterly_drill_reminder.sh`, and `tools/sbom.sh` from the developer/ingest classifications.
**Why it matters:** AC1 and AC4 require all runtime writes, correct installed-versus-developer classification, and exact remaining call sites; m1 following this table can migrate every named row and still leave an always-on installed writer or spawned writer on its legacy path.
**Proposed fix:** Replace the grouped brace lists with a reproducible inventory appendix containing one row per concrete `file:symbol` (or shell line), current default/destination, writer versus read-only role, installed/spawned/offline/external classification, and intended resolver child or explicit exception; include indirect call chains where a module has more than one runtime role.
**Regression-guard:** Add a frozen inventory-coverage test or checked script that enumerates known filesystem-mutating primitives and subprocess/output owners in `server/`, `ingest/`, `tools/`, `shim/`, and `ops/`, then requires every discovered file to have a classified inventory entry or an explicit reviewed exemption.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first constraint

**M1 — Read-only application coverage disappears on Windows** (MEDIUM)

**Where:** `tests/test_desktop_data_root_spike.py:183`
**Anchor:** `@pytest.mark.skipif(sys.platform == "win32", reason="chmod is not authoritative")`
**What:** The sole read-only-application fixture is skipped on Windows and no platform-neutral injected write denial or write-observation fixture replaces the non-portable `chmod` evidence.
**Why it matters:** AC3 claims read-only application locations are verified, but a desktop-distribution implementation can regress to a package- or CWD-relative write on Windows without this spike supplying any executable guard.
**Proposed fix:** Keep the POSIX permission test as native evidence and add a platform-neutral companion that instruments or injects filesystem operations so writes to the simulated package/CWD raise while writes below the data root are recorded and allowed; run that companion on every platform.
**Regression-guard:** A non-skipped test on Windows and POSIX that fails if any observed create/write/rename/unlink target is outside `ApplicationPaths.root` and proves `prepare()` still succeeds with the application location denied.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M2 — Container fixture proves paths but not the mounted root** (MEDIUM)

**Where:** `tests/test_desktop_data_root_spike.py:210`
**Anchor:** `    mount = tmp_path / "container-mount"`
**What:** The container fixture names a host temporary directory `mount` and checks only that returned environment values are descendants, without representing a container volume target, its read/write mode, or the required one-to-one agreement between `ARXMCP_DATA_DIR` and the mounted path.
**Why it matters:** A container can satisfy every current assertion while the declared root is unmounted, mounted read-only, or different from the one writable volume, which is the exact Docker/Compose failure the spike is meant to expose before fallback behavior changes.
**Proposed fix:** Add a test-only container fixture carrying environment plus volume declarations and validate that the canonical root is covered by exactly one writable application-data mount; keep the current Compose file as negative evidence and add a prospective overlay fixture rather than changing production manifests in this spike.
**Regression-guard:** Parameterize missing, read-only, mismatched, duplicate, and matching-RW mount cases; only the matching single mount should pass container resolution.
**Source critic:** milestone-arxmcp-critic
**Source axis:** local-first constraint

## What was done well

- The spike respected its prototype-only boundary: no production path consumer, dependency lock, MCP schema, prompt constant, Dockerfile, Compose file, or K8s manifest changed.
- `ApplicationPaths` is frozen and slotted, and resolution is cleanly separated from directory preparation; constructing a missing root performs no write.
- Explicit installed/container roots are required to be absolute, while the temporary source-relative compatibility path is resolved once against the captured startup CWD and emits a deprecation warning.
- Canonicalization uses `resolve(strict=False)` plus `relative_to`, correctly rejecting the tested existing descendant-symlink escape and canonicalizing a symlinked root.
- The fixed index layout preserves the canonical `index/kuzu` spelling, keeps all first-party paths local, and introduces no cloud or multi-host dependency.
- Compatibility aliases are allow-listed and out-of-root absolute targets are rejected rather than silently weakening the one-root claim.
- The ADR is unusually candid about residual limits: current Compose and K8s gaps, symlink-swap TOCTOU, migration ordering, and a genuine NO-GO fallback are all stated rather than hidden behind the conditional GO.
- The six focused tests and focused Ruff check pass independently; the macOS `KMP_DUPLICATE_LIB_OK` guard remains intact in `tests/conftest.py`.
- Cache byte-stability, math-content fidelity, MCP 2025-06-18 response semantics, tier sequencing, and the no-fork policy are axis-verified clean because the diff does not touch their production surfaces.

Severity counts: C0 H2 M2 L0

## Recommended rectification order

H1, H2, M1, M2

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: <finding ids>
- Deferred: <finding ids>
- Invalidated: <finding ids with reasons>
- Regression tests added: <file paths>

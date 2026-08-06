# Rectify summary — desktop-distribution-m2

- **Rect commit:** `edfc05a2b752a398d6f13fb4db79999c74776869` —
  `rect(desktop-distribution-m2): close H2-H4,M1-M2`
- **Fixed (5):** H2, H3, H4, M1, M2.
- **Deferred:** none.
- **Invalidated (2):** C1, H1.
- **External write:** `git push origin main` remains pending per-event user
  authorization.

## Re-verification and invalidations

- **C1 — implementation commits were unsigned:** invalidated. Both
  implementation commits verify as valid GPG-signed commits outside the
  critic's isolated keyring (`git verify-commit` and `%G?=G`).
- **H1 — the cumulative diff exceeded the unapproved large-diff limit:**
  invalidated. The user explicitly approved the large diff before the
  continuation implementation, and `state.json` records
  `allow_large_diff: true`.

The two invalidations are 40% of the five blocking findings, so the pipeline's
greater-than-40% stale-critique restart threshold did not trigger.

## Fixed

- **H2 — confinement observed too narrow a tree.** The full wheel gate now
  snapshots the installed application's parent, not only the virtual
  environment. Its opt-in manifests hash regular-file bytes and retain
  metadata, inode, and change time, so sibling writes and equal-size rewrites
  are both visible.
- **H3 — settings persistence was not proved.** The installed writer probe
  writes `desktop_relocation_probe`, reads it back through the settings store,
  and requires the exact value `ok` before the gate can pass.
- **H4 — installed UI ingest retained package-root defaults.** The server
  passes the canonical data root to notebook-ingest children through
  `ARXMCP_DATA_DIR`; mutable defaults in ar5iv fetch, chunking, embedding,
  storage, and bulk ingest now derive from `ApplicationPaths.resolve()`. The
  installed wheel invokes the real notebook-ingest module to report those
  paths and proves every one is below the temporary data root.
- **M1 — metadata-only manifests missed restored-mtime rewrites.** The full
  relocation proof now includes SHA-256 content digests. A regression rewrites
  a file with the same byte count and restores its mtime, then verifies that
  the manifest still detects the mutation.
- **M2 — provenance used a string-prefix check.** Provenance is now canonical
  `Path.resolve()` plus `relative_to()` containment. Regressions reject both a
  sibling-prefix directory and a symlink that escapes site-packages.

## Regression coverage

- `tests/test_installed_path_consumers.py` covers application-parent writes,
  equal-size rewrites, canonical provenance, symlink escape, child environment
  inheritance, installed ingest defaults, and settings read-back.
- `tests/test_oai_delta.py` isolates the CLI dry-run contract from the
  operator's real low-disk pause sentinel.
- `tests/test_status_endpoint.py` makes healthy-status assertions independent
  of host free capacity; threshold and hysteresis behavior remains covered in
  `tests/test_failure_modes.py`.

## Verification

- Targeted relocation and ingest tests: **PASS**.
- `make wheel-check PYTHON=.venv/bin/python`: **PASS**.
- `make wheel-check-full PYTHON=.venv/bin/python`: **PASS** — installed server
  reached `/healthz` with HTTP 200, notebook creation returned HTTP 201, all
  reported writer paths remained under the relocated root, and no watched
  tree changed.
- `make test PYTHON=.venv/bin/python`: **PASS** — Ruff clean; **5,021 passed,
  43 skipped, 1 xfailed**.
- Findings register: **no open findings**.

The first full-suite attempt exposed real host state rather than a product
regression: disk free space crossed the 10 GiB safety threshold, which created
the expected `var/arxmcp/ops/ingest-paused` sentinel and made four tests depend
on workstation state. Disposable spike and pytest artifacts were removed; the
operator safety sentinel was deliberately preserved, and the affected unit
tests now isolate their intended contracts.

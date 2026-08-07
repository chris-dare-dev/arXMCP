# Rectify summary — desktop-distribution-m3

- **Rect commit:** pending — `rect(desktop-distribution-m3): close H2-H5`
- **Fixed (8):** H2, H3, H4, H5, M1, M2, M3, M4.
- **Deferred (1):** H1.
- **Invalidated:** none; every HIGH anchor re-verified against live code.
- **External write:** `git push origin main` remains pending per-event user
  authorization.

## Fixed

- **H2/M3 — cross-platform path parity:** Rust and Python now preserve paths
  as platform-neutral wire strings and enforce the same lexical grammar for
  POSIX absolute and uppercase drive-qualified Windows absolute paths. Shared
  positive fixtures exercise both styles on every host; native filesystem
  canonicalization occurs only in the sidecar runtime adapter.
- **H3 — compatible nested extensions:** only direct children of
  `extensions` require namespaced ASCII keys. Nested extension objects accept
  ordinary JSON string keys under the existing frame, depth, and safe-number
  bounds. The compatible-minor fixture includes a mixed-case nested key and
  round-trips byte-for-byte in both languages.
- **H4 — payload-free decoder errors:** UTF-8 and JSON decoder failures return
  payload-free sentinels before the public error is raised. Regression tests
  recursively traverse causes, contexts, args, decoder documents, and source
  objects and prove malformed canaries are absent.
- **H5 — executable identity evidence:** the sidecar hashes
  `current_exe()` before binding, compares the expected digest in fixed time,
  and emits the independently computed value. A one-nibble mismatch exits 2
  with static stderr, empty stdout, and no endpoint announcement.
- **M1 — executable-version parity:** Python now matches Rust's visible ASCII
  `0x21..=0x7e` grammar excluding slashes. Both readers reject the shared
  embedded-space fixture.
- **M2 — exact malformed-token guard:** the pre-bind rejection test scans for
  both the original capability and the exact invalid token sent to the child.
- **M4 — zero-skip desktop gate:** `make desktop-conformance` performs locked
  Rust format/test/Clippy/build steps before exporting the explicit sidecar
  path to the Python lifecycle suite. A clean boundary run cannot silently
  skip executable identity, loopback, authentication, or shutdown evidence.

## Deferred

- **H1 — review-size signal:** the user explicitly approved the pipeline's
  large-diff path before implementation. Rewriting signed history solely to
  repartition the same code would be destructive and would not improve the
  already completed review. Risk was mitigated with two independent critics,
  shared Rust/Python fixtures, the zero-skip live gate, the wheel boundary
  check, and the full repository suite. The finding remains honestly deferred
  rather than invalidated.

## Regression coverage

- `apps/desktop/crates/desktop-contract/tests/contract.rs` consumes the shared
  Windows-path, compatible nested-extension, and invalid-version fixtures.
- `tests/test_desktop_contract.py` mirrors fixture acceptance, recursively
  scans decoder exception graphs, proves pre-bind digest rejection, checks the
  exact malformed capability, and pins the combined Make gate ordering.
- The live sidecar test still covers matching identity, retained port-zero
  ownership, readiness authentication, authenticated shutdown, stdin EOF, and
  token-free artifacts.

## Verification

- `make desktop-conformance PYTHON=.venv/bin/python`: **PASS — 8 Rust tests,
  strict Clippy, and 27 Python tests with zero skips**.
- Bounded lifecycle stress rerun: **PASS — 20/20 parameterized process cases**.
- `make wheel-check PYTHON=.venv/bin/python`: **PASS — 191 wheel entries and
  24 required files present in both wheel and clean install**.
- `make test PYTHON=.venv/bin/python`: **PASS — Ruff clean; 5,060 passed,
  43 skipped, 1 xfailed**.
- MCP tool-schema and BP1/BP2 prompt files remain unchanged; no hash re-pin is
  warranted.
- Findings register: **no open findings**.

The first full-suite run exposed the fixture's 200 ms HTTP read deadline as
too aggressive under repository load. Raising the still-bounded deadline to
two seconds stabilized 20 consecutive lifecycle cases and the subsequent
full-suite rerun; no failed evidence was promoted.

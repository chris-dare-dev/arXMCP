# Critique — E02_S04

**Critic:** adversary
**Generated:** 2026-05-07T13:52:22Z
**Commit range:** 802520d..62f36df
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES. Core hash formula, CHUNKER_VERSION constant,
  and manifest atomicity are all correct, but the duplicate-chunk_id
  abort path leaves the on-disk corpus in a stale-but-not-cleaned state
  that contradicts the implementation's own "fail loudly so the manifest
  is internally consistent" comment.
- Counts: 0 CRITICAL, 1 HIGH, 4 MEDIUM, 3 LOW.
- Highest-risk file: `ingest/chunker.py:840-863` (collision-abort skips
  cleanup).
- Cross-axis pattern: documentation drift — the module docstring
  (`chunker.py:39-41`) and dataclass field docs (`chunker_types.py:37-69`)
  still describe the retired `idx<N>` placeholder, contradicting the
  shipped behavior. Three findings touch this same surface (M3, L1).
- Brief's "fresh Python process" determinism risk is only simulated
  within one Python process; cross-process is not actually exercised.
- The `"v1.0"` static-source check is brittle — only catches the
  double-quoted form, has no defense against `'v1.0'`, f-strings, or
  reassignment elsewhere in the package.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Duplicate-chunk_id abort leaves stale on-disk corpus

- **Severity:** HIGH
- **Source:** adversary
- **File:** ingest/chunker.py:840-863
- **What:** The `seen_chunk_ids` collision check at line 847 raises
  `ValueError` BEFORE the stale-cleanup loop at line 862. `ValueError` is
  a member of `PER_PAPER_FAILURE_EXCEPTIONS` (line 127), so the outer
  envelope at line 778 catches it, logs a TSV row, and returns `[]`. The
  prior run's `<hash>.json` files and `chunk_manifest.json` remain on
  disk untouched, but the in-memory result is empty and the manifest
  bytes do not reflect the current chunker output.
- **Why it matters:** The implementation comment (line 845–846) claims
  the raise exists "so the manifest is internally consistent". The
  actual behavior is the opposite: the stale manifest from the previous
  run survives, lists chunk_ids that may no longer represent the current
  parser's view of the paper, and the eval harness (E05_S01) will trust
  that manifest as ground truth. Worse, downstream embedder runs see
  the stale per-chunk JSONs as if the chunker had succeeded. This
  silently violates the BP1 byte-stable caching contract on the recovery
  path: a re-run that resolves the collision (e.g. by chunker version
  bump) will not invalidate the prior corrupt artifacts because cleanup
  only happens INSIDE the success path.
- **Proposed fix:** Move the collision check to AFTER the cleanup glob,
  OR move the cleanup to the top of `_chunk_paper_impl` (before any
  ChunkRecord assembly). The latter is cleaner: cleanup becomes
  unconditional on entry, so any subsequent failure leaves the directory
  empty rather than stale. Alternatively, write all per-chunk JSONs +
  manifest into a tmp staging dir, then `os.replace` swap at the end —
  matches the atomic-write discipline already used for the manifest
  itself.
- **Regression guard:** Add a test in `tests/test_chunker_ids.py`
  that (1) seeds `chunks/<paper_id>/` with a fake stale `chunk_manifest.json`
  and a fake `<hash>.json`, (2) patches `_compute_chunk_id` to return a
  duplicate, (3) calls `chunk_paper`, and asserts the directory contains
  ZERO files (or only the result of the next successful run, never the
  stale seed). Today this test would pass with the stale files still
  present.

### F2 — Duplicate-body collision raise is reachable on legitimate input

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/chunker.py:843-852
- **What:** The "duplicate chunk_id" branch fires on TWO disjoint cases:
  (a) a 64-bit SHA-256 prefix collision (~1-in-90k at 200K-paper scale),
  and (b) two chunks in the same paper with byte-identical
  `(preamble_text, body_text)` tuples. Case (b) is reachable on
  legitimate input — e.g. a paper that contains a duplicated proof, an
  empty-body section that survives the 80-char minimum (impossible in
  the current `_extract_section_chunks` path, but a future
  theorem-environment-without-statement could land here), or a
  pathological LaTeXML output that emits two identical environments.
  The code conflates "collision" (random) with "duplicate content" (a
  parser bug) into one error message.
- **Why it matters:** A real-world paper hitting (b) is silently dropped
  (returns `[]` via the per-paper envelope) instead of getting a
  per-chunk de-duplication. The per-paper drop is the worst kind of
  silent failure for a corpus build — the paper is just missing from
  the index with no indication except a log line. The error message
  blames "collision" in the user-visible string, misdirecting any
  operator who reads the log.
- **Proposed fix:** Distinguish the two cases. If a duplicate
  `chunk_id` is detected, log a `DEBUG`-level warning naming the two
  duplicate chunks (kinds + section_path), then SKIP the duplicate
  rather than raising. A genuine 64-bit prefix collision is still
  preventable post-hoc by appending the chunk's structural index when
  the duplicate is detected. Pure body-text duplication should
  deterministically dedupe to a single chunk, since by construction the
  embedding is byte-identical.
- **Regression guard:** Add a test that constructs a paper with two
  body-identical `<div class="ltx_theorem_*">` siblings and asserts
  `chunk_paper` returns ONE chunk for that body, not zero (today the
  code raises and returns []). Required for HIGH+CRITICAL only — flag
  for MEDIUM consideration if the rectifier judges it cheap.

### F3 — Stored body_text NFC discipline divergence from chunk_id input

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/chunker.py:946-950, ingest/chunker_types.py:81
- **What:** `_compute_chunk_id` hashes `preamble_text + NFC(body_text)`
  but stores the un-normalised `chunk.body_text` on disk and in the
  ChunkRecord. The implementation summary's BP1 cross-host stability
  argument (item 2) only holds if every consumer of `chunk.body_text`
  re-normalises before doing anything content-addressed. If the
  embedder's downstream cache key includes anything derived from the
  stored bytes (e.g. an embedding-input hash that did NOT NFC-normalise
  for symmetry), two hosts with different default Unicode forms will
  produce identical chunk_ids but distinct embedding-input hashes —
  cache miss on what should have been a cross-host hit.
- **Why it matters:** The brief's risk note pins "BP1 byte-identical
  caching" as the linchpin reason this milestone exists. The current
  arrangement makes chunk_id stable but leaves the body_text bytes
  underneath each chunk_id host-dependent. Any future code that
  recomputes a hash over the stored body_text (a debug audit, a
  per-chunk content-validation tool, or a re-embed path that hashes the
  body for its own cache key) will silently break across hosts even
  though chunk_id is stable.
- **Proposed fix:** Either (a) NFC-normalise `chunk.body_text` at
  storage time so that `body_text` and the chunk_id hash input agree
  byte-for-byte, OR (b) document this asymmetry as a load-bearing
  invariant in the chunker_types.py docstring and in the canonical
  embedding-input contract (referenced in `04-parsing-and-chunking.md`).
  The NFC-on-store option is preferred because it eliminates a category
  of cross-host bugs at no per-chunk cost.
- **Regression guard:** N/A for MEDIUM unless rectifier picks (a), in
  which case add a test that asserts `unicodedata.normalize("NFC",
  chunk.body_text) == chunk.body_text` for every emitted chunk.

### F4 — "Single source of truth" static-source check is bypass-prone

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_chunker_ids.py:344-356
- **What:** `TestSingleVersionDefinition::test_v1_0_literal_count_in_chunker_modules`
  scans only `ingest/chunker.py` and `ingest/chunker_types.py` for the
  literal `'"v1.0"'`. It does NOT catch (a) single-quoted `'v1.0'`,
  (b) f-string forms like `f"v{major}.{minor}"`, (c) the literal in any
  OTHER `ingest/` module (e.g. `ingest/preamble.py`, `ingest/embed.py`
  when added in E03_S01), or (d) tests that hard-code `"v1.0"`
  themselves (`test_chunker_ids.py:184` already does this — `assert
  CHUNKER_VERSION == "v1.0"` is fine, but a future engineer who adds a
  comparator like `if rec.chunker_version == "v1.0":` in `ingest/foo.py`
  defeats the acceptance criterion silently).
- **Why it matters:** The acceptance criterion is "CHUNKER_VERSION is
  the only place `'v1.0'` is defined". The static check is the entire
  enforcement mechanism for that criterion, and its scope is two files.
  When E03_S02's re-embed skip logic and E04_S02's MVCC writer land,
  they are EXPECTED to consume `CHUNKER_VERSION` by import — not by
  hard-coding `"v1.0"` — but nothing in the repo prevents the latter
  from creeping in undetected.
- **Proposed fix:** Broaden the scan to all `ingest/**.py` files
  (excluding `chunker_types.py`), look for both `"v1.0"` and `'v1.0'`,
  and exempt only the canonical assignment in `chunker_types.py`. A
  6-line test rewrite suffices.
- **Regression guard:** The widened scan IS the regression guard.

### F5 — "Fresh Python process" determinism risk is only simulated

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_chunker_ids.py:120-133
- **What:** The brief's risk note explicitly calls out "the test must
  simulate a fresh Python process to catch any non-determinism from
  object ordering". The shipped test
  (`test_two_runs_same_paper_identical_ids`) runs both runs in the SAME
  Python process — two `tmp_path` subdirectories are not the same as a
  fresh interpreter. Within-process determinism is verified, but the
  brief's specific concern (cross-process insertion-order drift, e.g.
  from a future stdlib `dict` change or a third-party hash-randomization
  patch) is NOT exercised.
- **Why it matters:** The cache hit/miss behavior on a re-run is the
  entire point of E02_S04. If a future Python upgrade reshuffles
  hash-randomized container iteration order in a way that affects
  `all_chunks` assembly, the in-process test still passes (because
  PYTHONHASHSEED is fixed within one process) but production runs across
  workers/hosts/Python versions silently divergence. The brief's
  injunction was not a wishlist — it was a load-bearing test scope
  decision.
- **Proposed fix:** Add a single subprocess-based test that invokes
  `python3 -c "import json; from ingest.chunker import chunk_paper; ..."`
  twice via `subprocess.run`, captures the chunk_ids, and compares.
  Cost: ~15 LOC. Use `PYTHONHASHSEED=random` on each subprocess to
  actively perturb hash randomization. Today the within-process test
  passes trivially.
- **Regression guard:** The subprocess test IS the regression guard.

### F6 — `.tmp` files from crashed prior runs are not cleaned up

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/chunker.py:862, 982-992
- **What:** The cleanup glob `out_dir.glob("*.json")` catches per-chunk
  JSONs and the prior `chunk_manifest.json`, but NOT
  `chunk_manifest.json.<pid>.<uuid>.tmp` files left by a crashed prior
  run that died between `tmp.write_text` and `os.replace`. These
  accumulate silently on every crash recovery.
- **Why it matters:** Disk-fill is unlikely (each tmp is small and
  crashes are rare), but the clean-cwd invariant typical of
  atomic-write patterns is violated. Operators reading the chunks
  directory will see leftover `.tmp` files and may mistake them for
  active state.
- **Proposed fix:** Extend the cleanup glob to also match
  `chunk_manifest.json.*.tmp` (or `*.tmp` if the directory has no other
  legitimate `.tmp` files).
- **Regression guard:** N/A (LOW).

### F7 — Module + dataclass docstrings still describe the `idx<N>` placeholder

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/chunker.py:39-41, ingest/chunker_types.py:37-69
- **What:** The chunker module docstring at lines 39-41 says "Chunk IDs
  use the monotonic placeholder ``arxiv:<paper_id>:idx<N>`` until E02_S04
  lands the content-addressable SHA-256 hash". E02_S04 has landed in
  the same commit. The dataclass docstring in `chunker_types.py` lines
  37-39 (`chunk_id: Monotonic placeholder ... until E02_S04 replaces
  it`), 64-66 (`body_tokens: Reserved for E02_S03`), and 67-69
  (`preamble_ref: Reserved for E02_S02`) all describe pre-this-milestone
  state.
- **Why it matters:** The docstring is the first thing a new contributor
  reads when reasoning about chunk_id semantics. Stale docstrings in a
  shipped module are a moderate maintenance hazard — readers waste time
  reconciling docs against code, or worse, trust the docs. Not a
  correctness bug.
- **Proposed fix:** Update the three docstring blocks to reflect the
  current shipped behavior. The module docstring should describe the
  content-addressable formula directly. The field docstrings should drop
  "Reserved for ..." and describe what the field IS now.
- **Regression guard:** N/A (LOW).

### F8 — `_compute_chunk_id` argument-order docstring drift

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/chunker.py:832
- **What:** Comment on line 832 says
  ``arxiv:<paper_id>:<sha256(preamble_text + body_text)[:16]>`` (no NFC).
  The actual implementation at line 946 normalises body_text via NFC
  before hashing. Minor doc drift, but the file's invariant pin is
  the comment block, so accuracy matters.
- **Why it matters:** Same risk class as F7 — readers trust the comment
  and may be surprised that the chunk_id depends on NFC form rather than
  raw bytes.
- **Proposed fix:** Edit line 832 to say
  ``arxiv:<paper_id>:<sha256(preamble_text + NFC(body_text))[:16]>``.
- **Regression guard:** N/A (LOW).

## What was done well

- The CHUNKER_VERSION constant placement (chunker_types.py, not
  chunker.py) correctly avoids the circular-import that the brief's
  literal text would have created. Both researchers caught this and the
  rationale is documented inline.
- The `_compute_chunk_id` function is pure: same inputs → same digest,
  no global state, no I/O. Easy to test, easy to reason about.
- NFC normalisation discipline matches `tokenize_body` and
  `extract_preamble` — three call sites all using the same form.
- `test_compute_chunk_id_uses_documented_formula` pins the exact bytes
  that go into the hash. This is the right kind of pin for a
  content-addressable identifier; future refactors that subtly change
  the hash input will fail loudly.
- Atomic-write discipline for `chunk_manifest.json` reuses the
  PID + UUID-suffix tmp pattern from E02_S02's preamble.py — consistency
  with established conventions.
- The `seen_chunk_ids` set check exists at all. Even though it has
  ergonomics issues (F2), the principle of failing on within-paper
  duplicates rather than silently letting the second JSON overwrite the
  first is correct.
- `test_paper_id_in_hash_input_via_prefix_only` correctly documents that
  same-content cross-paper chunks intentionally share the hash suffix.
  This is a load-bearing future-cache-design decision; pinning it as a
  test is right.
- The `_resolve_preamble_ref` → `_resolve_preamble_doc` rename is
  motivated by avoiding a second `extract_preamble` call. The rename is
  a pure win in the package-internal API.
- `chunk_manifest.json` schema is minimal (chunk_id + kind only). No
  timestamps, no per-chunk byte counts, nothing that varies across runs.
  The right call for BP1 stability.
- All 22 new tests are organized into named TestCase classes that map
  directly to acceptance criteria. The coverage map at the top of
  `test_chunker_ids.py` is exemplary documentation discipline.

## Recommended rectification order

1. **F1** — collision-abort cleanup ordering. Real recovery-path
   correctness bug; leaves the corpus in a state that contradicts
   manifest content. Highest leverage to fix.
2. **F4** — broaden the static-source `"v1.0"` scan. Acceptance-criterion
   enforcement gap that will be exploited by E03_S02 / E04_S02 lands
   later.
3. **F2** — disambiguate the collision-vs-duplicate raise path. May be
   subsumed by F1's rewrite (if you switch to staging-dir pattern, the
   raise path can be dropped entirely in favor of dedupe).
4. **F5** — subprocess determinism test. Cheap to add (~15 LOC) and the
   brief's risk note explicitly named this as required.
5. **F3** — NFC-normalize `chunk.body_text` at storage time, OR document
   the asymmetry. Pick one and pin it.
6. **F7, F8** — docstring drift. Trivial edits; bundle with any other
   chunker_types.py change.
7. **F6** — `.tmp` cleanup. Defer if budget tight.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate. -->

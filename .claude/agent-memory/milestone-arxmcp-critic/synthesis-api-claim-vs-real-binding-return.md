---
name: synthesis-api-claim-vs-real-binding-return
description: When a synthesis claims a native-binding API "returns only X", reproduce against a real object — stub-only tests mask the real return shape (m3 D2 false-clean)
metadata:
  type: feedback
---

When a research-synthesis makes a claim about what a native/3rd-party binding
API RETURNS (e.g. "`list_indices()` returns ANN/vector indexes only") and the
implementation's correctness rule depends on that claim, REPRODUCE it against a
real object before declaring the logic clean.

**Why:** corpus-integrity-observability-m3. Synthesis §2 asserted lancedb
0.30.2 `tbl.list_indices()` "returns ANN/vector indexes only". FALSE — it also
returns the scalar `paper_id` BTree index (`ingest/store.py` builds it
unconditionally via `create_scalar_index`). `compute_unindexed_rows` iterated
ALL indexes with no `index_type` filter, counting the scalar index toward
`index_count`. This breaks the cardinal D2 sentinel: a corpus with a scalar
index but NO vector index returns `0` ("clean") instead of `-1` ("could not
determine") — the exact false-clean D2 exists to prevent. ALL 42 tests stubbed
`list_indices` with fake `SimpleNamespace(name=...)` objects that have NO
`index_type` and NO scalar index, so the defect was invisible to the suite —
only a real seeded LanceDB table surfaces it (`(0, ['embedding_stmt_idx=0',
'paper_id_idx=0'])`).

**How to apply:** On any milestone whose correctness hinges on a binding's
return shape (`list_indices`, `index_stats`, schema introspection, MVCC
version handles), build a 1-paragraph repro script that seeds a real
fixture and prints the actual returned objects + their type/attr fields. If
every test STUBS the binding call, the stub almost certainly under-represents
the real return (missing a type discriminator, an extra index kind, a None
case) — that gap is the finding. This is the binding-level cousin of
[[spy-passthrough-vs-binding-forward]]: there the spy proved PASSED-not-
FORWARDED; here the stub proves the LOGIC-over-an-idealized-shape, not over
the real one. Pairs with the "verified by reading, not pinned" e3 class.

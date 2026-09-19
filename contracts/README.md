# contracts/ — the producer-owned bridge contract

This directory is the versioned, machine-checkable contract for every artifact
that crosses the arXMCP ⇄ consumer (⇄ future orchestrator) boundary.
arXMCP **produces** the contract (decision D2, Stage-2); consumers vendor
pinned copies and validate on read. The bridge is git-mediated files on one
workstation — it never crosses the network.

| File | What it is |
|---|---|
| `registry.json` | Artifact-type → current version map (single source of truth; the future `GET /bridge/contracts` handshake serves this + schema SHA-256s) |
| `envelope.v1.schema.json` | The common envelope every artifact carries (substrate block: `corpus_version`, notebook, `filter_echo`, `retrieval_mode`, `tool_schema_sha256`) |
| `<type>.v<MAJOR>.schema.json` | One JSON Schema per artifact type per MAJOR |
| `examples/` | One committed, test-validated example artifact per type |
| `CONTRACTS.md` | The changelog — every version bump lands here with a migration note |

**Loading the schemas (consumer contract):** schema `$id`s are opaque,
never-fetched URNs (`urn:arxmcp:bridge:<type>:v<MAJOR>`). Build a local
`referencing.Registry` mapping each schema's `$id` to its contents. See
`tests/_bridge_helpers.py` for the reference loader.

**Payload schemas are not vendored here.** A payload's schema belongs to the
consumer that publishes it; this repository pins the *envelope* and passes the
interior through untouched. `retrieval-evidence`'s `payload` is therefore an
open object in this contract, which is a statement about ownership and not a
licence to add fields — the consumer's own schema is the strict one, and a
validator that needs the payload shape loads it from there.

Rules (enforced as tests in `tests/test_bridge_contracts.py` and
`tests/test_bridge_versioning_rules.py`):

1. Per-artifact-type MAJOR.MINOR. MINOR = additive only; consumers ignore
   unknown fields. MAJOR = breaking; consumers refuse unknown MAJOR with a
   precise diagnostic.
2. Enums are append-only within a MAJOR.
3. `retrieval_mode` is pinned to `dense_only` (D8); any change is a versioned,
   deliberately-batched event.
4. Verdict vocabularies do **not** unify across domains.
5. Every bump is recorded in `CONTRACTS.md`.

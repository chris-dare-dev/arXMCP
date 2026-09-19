# CONTRACTS.md — bridge contract changelog

Every version bump of any artifact type in `registry.json` is recorded here
with a migration note (mirrors the `CHANGES.md` discipline at the repo root).
Format per entry: date, type, old → new version, what changed, migration note.

Doc-placement note: this file is a deliberate, Stage-2-mandated exception to
the "only README/CLAUDE Markdown in subdirs" rule (CLAUDE.md §1) — the
Stage-1 bridge-contract decision (D2) names `contracts/CONTRACTS.md` as the
changelog location so consumers can vendor the directory wholesale.

## Versioning rules (normative)

1. **Per-artifact-type MAJOR.MINOR** — not repo-global. MINOR bumps are
   additive-only; consumers MUST ignore unknown fields (schemas here therefore
   never set `additionalProperties: false`, with the one documented exception
   below). MAJOR bumps are breaking (rename/remove/semantic change/constraint
   tightening); consumers MUST refuse an unknown MAJOR with a diagnostic that
   names both the artifact's version and the supported version.
2. **Enums are append-only within a MAJOR** (codifies the m5 precedent that
   kept the `notebooklm` enum value so 28 historical artifacts still
   validate). The append-only gate is executable:
   `tests/test_bridge_versioning_rules.py` compares every enum in every schema
   against `tests/fixtures/contracts/enum-baseline.json` — removals fail;
   appends pass (extend the baseline in the same change).
3. **Producers embed the version; consumers validate on read.**
4. **Registry + handshake:** `registry.json` is the source of truth; the
   WS-A `GET /bridge/contracts` endpoint serves it plus per-schema SHA-256s.
   Consumers vendor pinned copies and preflight-compare before any run.
5. **`retrieval_mode` is contract data (D8):** the envelope pins the enum to
   `dense_only`, the sole live mode (hybrid modules exist but are unwired
   behind the 2026-05-21 CLOSED-NO verdict — finding 211 R-B). Re-opening
   hybrid requires a new measured verdict at materially larger corpus scale
   AND a deliberate contract version bump recorded here; never a side effect.
6. **Verdict vocabularies do not unify.** `verdict-record` carries a `domain`
   tag; each domain has its own vocabulary (SP2 measured exactly
   `["VERIFIED"]` overlap across pipelines). Cross-domain enum leaks are
   schema violations.

### Documented exception: retrieval-evidence payload strictness

`retrieval-evidence` v1.0 wraps the proof-verify triangulation payload
**byte-for-byte unchanged**. The payload's schema is owned and published by
the consumer and is NOT vendored here, so this contract declares `payload` an
open object and constrains nothing about its interior. That openness is an
ownership statement, not a relaxation: the consumer's schema sets
`additionalProperties: false` at the payload's top level, additive evolution
happens inside its open `result` object, and any NEW top-level payload field
is a breaking (MAJOR) event for this type. With no vendored copy to pin, the
executable meaning of "unchanged" is the historical-artifact tests in
`tests/test_bridge_contracts.py`: real pre-contract artifacts still validate
inside a v1.0 envelope with zero payload modification. The
envelope levels (`bridge`, `substrate`) stay MINOR-tolerant like every other
type.

### v0 stub types: content-authoring window

Types at `status: stub` (version 0.x) are placement stubs whose payload
content is still being authored by the named `content_owner`. Within 0.x the
content owner MAY tighten payload constraints (add required fields, pin item
shapes) in a 0.MINOR bump — the additive-only MINOR guarantee of rule 1 binds
from 1.0, when the type is promoted to `stable`. Consumers should treat 0.x
artifacts as pre-contract: validate, but expect churn. Promotion to 1.0 is a
deliberate registry event recorded here.

### Known gap: cite-audit verdict vocabulary unpinned at v1.0

`verdict-record` accepts `domain: "cite-audit"` but does not constrain its
verdict vocabulary — no code-verified ground truth for that enum existed at
authoring time. Pinning a vocabulary where none existed is constraint
tightening, i.e. a MAJOR bump — so the pin must land either as
`verdict-record` v2.0 or before the first cite-audit producer ships against
this contract. Do not ship a cite-audit producer against the unpinned v1.0
without recording the vocabulary here.

## Registry state

| Type | Version | Status | Notes |
|---|---|---|---|
| envelope | 1.0 | stable | substrate block: server, corpus_version, notebook, filter_echo, retrieval_mode, tool_schema_sha256 |
| arxmcp.bridge/notebook-ref | 1.0 | stable | slug + URI + corpus_version pin (+ optional export-manifest digest) |
| arxmcp.bridge/retrieval-evidence | 1.0 | stable | payload = proof-verify triangulation, verbatim (see exception above) |
| arxmcp.bridge/verdict-record | 1.0 | stable | domains: lean, proof-verify, cite-audit (unpinned), proving |
| arxmcp.bridge/ingest-receipt | 1.0 | stable | before/after corpus_version, paper/chunk deltas, parse failures |
| arxmcp.bridge/corpus-snapshot | 1.0 | stable | server-scoped (null notebook substrate branch) |
| arxmcp.bridge/run-ledger-entry | 1.0 | stable | outcome enum: completed, failed, halted, escalated, abandoned |
| arxmcp.bridge/proof-task | 0.3 | draft | WS-D content authored (arx-d3, moved in at integration per IF-5): field_lane enum, target_verdict_floor, typed budget block; v0.1 pins preserved (task_id + statement_latex). 0.3 (stage3/proving-r3): OPTIONAL skeptic-check `discharges` refutation-linkage declaration (additive; missing => fail closed) |
| arxmcp.bridge/evidence-bundle | 0.2 | draft | WS-D content authored (arx-d3, moved in at integration per IF-5): bundle laws (refuted => counterexample; proven-formal => faithfulness record; publishable proven-formal => signed checkbox), skeptic block pins prover_cycles const 0; v0.1 pins preserved (task_id + verdict, D9 five-verdict enum) |
| arxmcp.bridge/proposed-notebook-manifest | 0.2 | stub | WS-E content authored (arx-e1): source_citation required per paper (AC-E.4), open-problem source shape pinned, channels/dedup blocks; 1.0 promotion pending |

## Changelog

### 2026-07-05 — proof-task 0.2 → 0.3: refutation statement-linkage declaration (stage3/proving-r3)

- `arxmcp.bridge/proof-task` **0.2 → 0.3** — additive, back-compatible
  0.MINOR bump (the v0-stub content-authoring window, rule "v0 stub types"
  above). Each `skeptic_checks.lean[]` and `skeptic_checks.cas[]` entry MAY
  now carry an OPTIONAL `discharges` object naming which claim-derived
  proposition that witness/scan discharges:
  `{"proposition": <Lean text>, "refutes_claim": true,
  "justification"?: <prose>}`.
- **Why:** round-3 closes the statement-linkage CLASS bug on the refutation
  side. The verdict-award choke-point (`server/proving/verdict_linkage.py`)
  routes EVERY verdict-award path through one check; for an author-supplied
  `witness`/`cas` refutation it kernel-checks the witness's proved statement
  against `discharges.proposition` (the author's declared string is never
  trusted over the kernel result) and requires `refutes_claim: true`. A
  `refuted` with no valid declared-and-checked linkage is capped
  (abstained) / escalated — it does not earn a confident `refuted`.
- **Back-compat / fail-closed:** the field is optional, so 0.2 producers
  still validate. But a 0.2-style task whose author-supplied refutation
  carries no `discharges` no longer earns a confident `refuted` (it caps /
  escalates) — a MISSING declaration fails CLOSED, never opens. `search`
  hits are linked by construction and ignore the field. No consumer-visible
  field was removed, renamed, or tightened, so this is MINOR, not MAJOR.

### 2026-07-04 — WS-D proving content moved in at integration (stage2/arx-d3 → stage2-integration, IF-5)

- `arxmcp.bridge/proof-task` **0.1 → 0.2** (stub → DRAFT; WS-D content
  authored on `stage2/arx-d3` and moved into this registry at the Stage-2
  integration step per the IF-5 custody split — WS-C hosts and versions the
  types, WS-D authors the payload content). v0.1 pins preserved (`task_id` +
  `statement_latex` required). New at 0.2: `field_lane` enum,
  `target_verdict_floor`, typed `budget` block, closed `statement_context`
  v0 shape.
- `arxmcp.bridge/evidence-bundle` **0.1 → 0.2** (stub → DRAFT; same custody
  move). v0.1 pins preserved (`task_id` + `verdict` with the D9
  five-verdict enum). New at 0.2: bundle laws as schema — `refuted`
  REQUIRES a counterexample artifact, `proven-formal` REQUIRES the
  faithfulness record, publishable `proven-formal` REQUIRES the signed
  human checkbox; CAS artifacts carry the AC-D.11 replay floor
  (code + params + timeout); the skeptic block pins `prover_cycles`
  `const 0` (AC-D.10 as schema).
- The v0.2 examples (`proof-task.v0.example.json`,
  `evidence-bundle.v0.example.json`,
  `evidence-bundle.v0.proven-formal.example.json`) re-homed under
  `examples/`; the slice-custody vendored envelope copy deleted
  (`server/proving/contracts.py` now loads from this directory).

### 2026-07-04 — WS-E manifest content authored (stage2/arx-e1)

- `arxmcp.bridge/proposed-notebook-manifest` **0.1 → 0.2** (stub; WS-E
  content authoring per the v0-stub window above). Changes on the v0.1
  propose→confirm spine:
  - `payload.papers[]` items now REQUIRE a non-empty `source_citation`
    (AC-E.4: no unsourced "this is open" claims; every proposal names its
    provenance — Atom window hit, citation-graph edge, or open-problem
    source entry). Optional `primary_category`, `abstract_head`, and
    `corroborations[]` (extra provenance lines) added.
  - `payload.open_problem_sources[]` items pinned to a named-source shape
    (`name` required; `kind`/`url`/`retrieved_at`/`entries_considered`/
    `entries_matched` optional).
  - Optional `payload.channels` block (atom + cite_neighbors run records,
    incl. `graph_status` mirroring the handler's
    present/absent/unavailable degradation semantics) and optional
    `payload.dedup` block (AC-E.2 exclusion record).
  - Optional `payload.window.months` (3-12; producer-validated).

  Migration note: constraint tightening is permitted here because the type
  is a 0.x stub (see "v0 stub types" above). No consumers of 0.1 existed at
  bump time. Producer: `tools/exploration` (exploration pipeline v0,
  `.claude/exploration/README.md`).

### 2026-07-04 — initial contract core (stage2/arx-c1)

- `envelope` **→ 1.0** (new). Common envelope with the substrate block; the
  anti-stale-substrate device (kills the spike-1/2/3 probe-cycle failure
  class). `retrieval_mode` pinned to `dense_only` per D8/finding 211 rec 3.
- `arxmcp.bridge/notebook-ref` **→ 1.0** (new).
- `arxmcp.bridge/retrieval-evidence` **→ 1.0** (new). Wraps the existing
  triangulation payload unchanged. The payload's schema is owned and published
  by the consumer and is not vendored here, so this type pins the envelope and
  passes the interior through.
- `arxmcp.bridge/verdict-record` **→ 1.0** (new). Domain-tagged; vocabularies
  pinned for lean (`ok|sorry|error|timeout|unavailable`, from
  `server/handlers/lean_verify.py` `_normalize_response`), proof-verify
  (`VERIFIED|UNVERIFIED|LIKELY-WRONG|DISPUTED|OUT-OF-CORPUS`, from the
  website's `claim.schema.json`), and proving (the D9 five-verdict taxonomy).
  cite-audit accepted but unpinned (see Known gap above).
- `arxmcp.bridge/ingest-receipt` **→ 1.0** (new).
- `arxmcp.bridge/corpus-snapshot` **→ 1.0** (new).
- `arxmcp.bridge/run-ledger-entry` **→ 1.0** (new).
- `arxmcp.bridge/proof-task` **→ 0.1** (new, STUB — WS-D authors content).
- `arxmcp.bridge/evidence-bundle` **→ 0.1** (new, STUB — WS-D authors
  content; five-verdict enum + task binding pinned as the soundness core).
- `arxmcp.bridge/proposed-notebook-manifest` **→ 0.1** (new, SKELETON —
  WS-E authors content).

Migration note: no consumers exist yet at these versions; the website vendors
its first pins from this state. Historical triangulation artifacts remain
valid as `retrieval-evidence` payloads without modification (backward-compat
fixtures: `tests/fixtures/contracts/historical/`).

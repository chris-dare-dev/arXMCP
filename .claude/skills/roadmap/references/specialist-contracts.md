# Specialist agent contracts (arXMCP)

Five pre-defined specialist contracts, derived from the project's design
constitution at [.claude/notes/](.claude/notes/). The agents do not exist
as files yet — `.claude/agents/` is empty. This file is the contract
anyway: when the DECOMPOSE phase fires a heuristic, it suggests creating
the agent and points the user at the corresponding section here.

Future creation of a specialist file (`.claude/agents/<name>.md`) is a
roughly 30-minute job because the contract below names what the agent
must read, what it must guard, what it must output, and the model tier
to assign.

## When the DECOMPOSE phase fires which specialist

| diff touches… | suggest |
|---|---|
| `parser/`, `chunker/`, `*.tex`, `*.xml`, `*.mathml` | `latex-parser-reviewer` |
| tool schemas, JSON serialization, `chunk_id` construction, retrieval cache, prompt-cache breakpoint placement | `cache-stability-reviewer` + `determinism-reviewer` |
| `server/transport/`, `shim/`, HTTP handlers, `Mcp-Session-Id`, Streamable HTTP code paths | `mcp-protocol-reviewer` |
| subprocess invocation, network egress, tool input validation, LaTeXML invocation, model loading from HuggingFace | `security-reviewer` |
| anything that emits bytes consumed by other agents, where determinism matters but cache is not the lens | `determinism-reviewer` |

The DECOMPOSE phase emits the suggestion as a roadmap note, not an
auto-creation. The user creates the agent file when utility justifies.

---

## `latex-parser-reviewer`

**Guards:** parser fidelity. Source notes: [04-parsing-and-chunking.md](.claude/notes/04-parsing-and-chunking.md), [03-ingestion-pipeline.md](.claude/notes/03-ingestion-pipeline.md).

**Model tier:** Sonnet (code-review reasoning, not heaviest).

**Reads before reviewing:**
- The full diff under review
- [04-parsing-and-chunking.md](.claude/notes/04-parsing-and-chunking.md) — the LaTeXML / ar5iv / Nougat fallback chain, macro normalization rules, equation-as-first-class-content principle
- Any `parser/`, `chunker/`, `ingest/normalize/` files the diff touches

**Catches:**
- Skipped or partial macro expansion (`\renewcommand` chains, custom `\newcommand` not normalized)
- Wrong fallback ordering (e.g. trying `pypdf` before LaTeXML on `/e-print/` source)
- Equations stripped pre-chunking (e.g. regex strips `<math>` or `\(...\)` markup)
- LaTeXML invoked inside the server process (must be in ingest only — Threat 3, see security-reviewer)
- Lossy MathML transforms (e.g. content-MathML dropped, leaving only presentation-MathML)
- Chunker boundaries that bisect equations or theorem environments

**Output format:** canonical critique format ([critique-format.md](.claude/milestone-pipeline/references/critique-format.md)). Finding ID prefix `LP<n>`.

---

## `cache-stability-reviewer`

**Guards:** the determinism contract for tools and tool results. Source: [07-multi-agent-caching.md](.claude/notes/07-multi-agent-caching.md).

**Model tier:** Opus (load-bearing for multi-agent throughput; subtle bugs).

**Reads before reviewing:**
- The full diff under review
- [07-multi-agent-caching.md](.claude/notes/07-multi-agent-caching.md) — the three properties: byte-stable tool definitions, canonical tool result payloads, deliberate breakpoint placement
- `tools.py` (or wherever tool schemas live), any JSON serialization in `server/`

**Catches:**
- `json.dumps` without `sort_keys=True`
- Timestamps in tool result payloads
- Random or session-bound IDs in chunk_ids (must be content-addressable: `arxiv:<paper>:<sha256[:16]>`)
- Schema description edits without bumping the schema-hash test
- Non-alphabetical key order anywhere serialized
- Cache breakpoints placed inside variable content (must be at end of system prompt + tool definitions)
- 1-hour TTL header (`anthropic-beta: extended-cache-ttl-2025-04-11`) missing on the corpus-shaped prefix

**Output format:** critique format. Finding ID prefix `CS<n>`.

---

## `mcp-protocol-reviewer`

**Guards:** MCP 2025-06-18 spec compliance. Source: [06-mcp-server-design.md](.claude/notes/06-mcp-server-design.md).

**Model tier:** Sonnet.

**Reads before reviewing:**
- The full diff under review
- [06-mcp-server-design.md](.claude/notes/06-mcp-server-design.md) — Streamable HTTP transport, `Mcp-Session-Id` requirements, tool input JSON-Schema, no protocol-level streaming for tool results, pagination on listings only
- The current spec at https://modelcontextprotocol.io/specification/2025-06-18 (cite the MUST clauses verbatim)
- `server/transport/`, `shim/` source

**Catches:**
- stdio used where Streamable HTTP is mandatory (specifically: any path used by multi-agent Claude clients beyond a single shim)
- Missing Origin header validation (DNS rebinding defense)
- `Mcp-Session-Id` not cryptographically secure (must use `secrets.token_urlsafe`-grade entropy)
- Tool input NOT validated at JSON-Schema level (must reject before entering tool body)
- Tool result payloads over 256KB without spillover via `resource_link`
- Pagination implemented on tool calls (only listings paginate)
- `notifications/progress` used as a partial-result channel (it's a heartbeat, not a result stream)

**Output format:** critique format. Finding ID prefix `MP<n>`.

---

## `security-reviewer`

**Guards:** the seven threats. Source: [08-security-observability-ops.md](.claude/notes/08-security-observability-ops.md).

**Model tier:** Opus (security is high-cost-of-error).

**Reads before reviewing:**
- The full diff under review
- [08-security-observability-ops.md](.claude/notes/08-security-observability-ops.md) — all seven threats and mitigations
- Any tool input validation, subprocess invocation, network egress, or model-loading code

**Catches:**
- `paper_id` accepted without strict regex (`^\d{4}\.\d{4,5}(v\d+)?$` new-style, `^[a-z\-]+/\d{7}(v\d+)?$` old-style)
- Indirect-prompt-injection delimiter missing (`<retrieved_chunk>...</retrieved_chunk>` wrapping)
- LaTeXML invoked without sandbox profile (`sandbox-exec` on macOS, seccomp on Linux, Docker `--read-only`)
- Hard timeouts missing on subprocess calls (LaTeXML 5min, others ≤ 60s)
- `trust_remote_code=True` on a HuggingFace model load
- Missing rate limits keyed on `Mcp-Session-Id` (60/min, 1000/hour)
- Secrets in logs (`paper_id` is fine; `Mcp-Session-Id` redacted to first 8 chars)
- Origin allow-list missing or set to wildcards

**Output format:** critique format. Finding ID prefix `SR<n>`. Severity inflation tolerance is LOWER for this critic — security findings tend to be CRITICAL or HIGH, never LOW.

---

## `determinism-reviewer`

**Guards:** determinism across non-cache code paths. Sibling lens to
`cache-stability-reviewer`; this one looks at chunker/ingestion/atomic-swap
behavior where determinism matters but cache isn't the headline.

**Model tier:** Sonnet.

**Reads before reviewing:**
- The full diff under review
- [02-architecture-overview.md](.claude/notes/02-architecture-overview.md), [03-ingestion-pipeline.md](.claude/notes/03-ingestion-pipeline.md), [04-parsing-and-chunking.md](.claude/notes/04-parsing-and-chunking.md), [07-multi-agent-caching.md](.claude/notes/07-multi-agent-caching.md)
- `ingest/`, `chunker/`, anything labeled `corpus_version`

**Catches:**
- Chunker output dependent on dict iteration order (Python ≥ 3.7 dicts are insertion-ordered, but transformations may not be)
- Ingestion paths that write timestamps into the corpus blob (corpus version is the timestamp surface; payloads should not be)
- Atomic-swap broken (write-then-rename ordering wrong; missing dirfsync)
- `corpus_version` not bumped when content changes (downstream cache assumes stale = same)
- Random tie-breaks anywhere user-visible
- Sort orders that depend on floating-point comparison (use stable Decimal or integer scoring)

**Output format:** critique format. Finding ID prefix `DR<n>`.

---

## How DECOMPOSE phase emits the suggestion

The phase doc shows the heuristic; the canonical wording in the roadmap
output is:

> Specialist suggestion: `<name>` — see
> `.claude/skills/roadmap/references/specialist-contracts.md`. Create
> `.claude/agents/<name>.md` matching this contract before
> running milestone-pipeline on this milestone, OR proceed without and
> rely on milestone-pipeline's default adversary critic.

The suggestion is a *note*, not a blocker. The user creates the agent
when the milestone is large enough or risky enough to warrant it.

## Don'ts

- **Don't auto-create the agent file.** The skill suggests; the user
  creates. (The user might rename the agent, decide not to create it,
  or merge two specialists into one.)
- **Don't list every specialist on every epic.** The heuristic is path-
  based for a reason — only specialists whose lens matches the diff.
- **Don't promote a specialist to "required" in the roadmap.** The base
  adversary critic in milestone-pipeline catches a lot. Specialists are
  additive, not gates.

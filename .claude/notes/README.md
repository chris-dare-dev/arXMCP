# arXMCP — Design Context

This directory is the load-bearing context for the arXMCP project. Every implementation
decision should trace back to one of these notes. If you're an agent working on this repo
and you don't know why something is built a particular way, the answer is in here.

## What arXMCP is

A local-first, Docker-deployable MCP (Model Context Protocol) server that exposes a
research-mathematics arXiv corpus (math.AG, math.NT, math-ph, hep-th) to multiple Claude
agents in an agentic pipeline. Think of it as the durable, programmatic substrate that
plays the role NotebookLM plays for the Gemini ecosystem — but for Claude Code, with
full multi-agent caching semantics, math-aware parsing (LaTeXML + macro expansion),
and zero dependence on paid cloud services.

The intended consumer is a multi-agent math-proof workflow:
sketcher → autoformalizer → tactician → fixer, each a Claude sub-agent, all sharing
a common paper corpus through this server.

## Hard constraints

- **No AWS S3 / no requester-pays buckets.** Object storage in general is fine
  (Backblaze B2, etc.) but the arXiv ingestion path must not depend on `s3://arxiv/`.
- **No forking** of existing arXiv-MCP repos. Steal ideas freely; don't import code.
- **Must run locally in Docker.** Single workstation deployment is the design target.
  Multi-host scaling is explicit non-goal for v1.
- **Multiple concurrent Claude sub-agents** must be able to use this server with shared
  caches across their separate context windows.

## Reading order

1. [01-mission-and-context.md](01-mission-and-context.md) — Why this exists. The
   research-math agent pipeline pattern, why math is structurally harder than code for
   adversarial review, and what NotebookLM-equivalent means in the Claude ecosystem.
2. [02-architecture-overview.md](02-architecture-overview.md) — Headline architecture
   decisions. The full diagram. The two corrections (HTTP transport, macro expansion)
   that override naive designs.
3. [03-ingestion-pipeline.md](03-ingestion-pipeline.md) — How to acquire the corpus
   without S3. Academic Torrents seed + OAI-PMH delta + `/e-print/` fetches +
   INSPIRE-HEP and OpenAlex enrichment.
4. [04-parsing-and-chunking.md](04-parsing-and-chunking.md) — LaTeXML as primary
   engine, ar5iv as cache, macro expansion, the chunking strategy for research-math
   papers (theorem+proof pairing, equation atoms, hierarchical levels).
5. [05-storage-and-indexing.md](05-storage-and-indexing.md) — LanceDB for vectors+BM25,
   Kùzu for the citation graph, dual-representation embedding, ColBERT for long
   technical chunks.
6. [06-mcp-server-design.md](06-mcp-server-design.md) — Streamable HTTP transport
   with stdio shim, tool surface, deterministic canonicalization for cache reuse.
7. [07-multi-agent-caching.md](07-multi-agent-caching.md) — Anthropic prompt cache
   semantics, three-tier retrieval cache, singleflight on the embedder, cache-killers
   to avoid (especially non-deterministic tool-use IDs).
8. [08-security-observability-ops.md](08-security-observability-ops.md) — Threat
   model, observability stack, failure modes, daily ops.
9. [09-feature-priorities.md](09-feature-priorities.md) — Features ranked by ROI.
   The vertical-slice ordering for v1 → v2.
10. [10-references-and-prior-art.md](10-references-and-prior-art.md) — Projects to
    study (PaperQA2, LeanDojo, DeepSeek-Prover-V2, Goedel-Prover), repos to read,
    papers to know.

## Caveat on numeric claims

The research that produced these notes was synthesized from training knowledge through
January 2026 because live web access was denied during the research session. Repo
URLs, project names, and protocol behaviors are reliable; specific version numbers,
exact pricing, exact rate limits, and current product status (especially for closed
players like Harmonic, Morph Labs, Math Inc.) should be verified against live docs
before being committed to in code.

The two URLs to re-check before any cache or transport decision lands in code:

- `https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching`
- `https://modelcontextprotocol.io/specification/2025-06-18`

## Editing this directory

These notes are the project's design constitution. Update them when a design decision
changes — don't let code drift away from them. If you (an agent) discover that a note
contradicts what the code actually does, raise it explicitly rather than silently
reconciling.

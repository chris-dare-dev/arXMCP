# Notebook discovery model

**Status:** authoritative for the `notebook-paper-discovery` roadmap (milestones m1–m4).
**Established:** notebook-paper-discovery-m1 (2026-05-31).
**Supersedes:** nothing — this is the first cross-milestone note for the discovery feature.

This note fixes the shared model the four discovery milestones build on, so m2–m4 do
NOT re-litigate field schema, the propose→confirm contract, or where channel results are
deduplicated. It is the design constitution for paper discovery; quote it by filename in
later milestone briefs rather than re-deriving these decisions.

Origin: capability-scout `2026q2-crawl4ai-paper-discovery` (crawl4ai REJECTED — arXiv
rate-limits by IP, `robots.txt` disallows `/search`/`/api/`/`/oai2/`/`/e-print/` and
mandates a 15s crawl-delay, and Playwright is a heavyweight dep for zero gain) → roadmap
`plans/notebook-paper-discovery-roadmap.md`.

---

## 1. Field schema (m1 — SHIPPED)

A notebook gains a machine-readable research interest via two additive columns on the
`notebooks` table (`server/notebooks_store.py`, SCHEMA_VERSION 5):

| Column | Type | Validation | Consumer |
|---|---|---|---|
| `discovery_category` | `TEXT NOT NULL DEFAULT ''` | enum `{math.AG, math.NT, math-ph, hep-th}` **or empty**; enforced at the route layer by `server/routes/notebooks.py::_validate_discovery_category` (`if … raise`, NOT `assert` per CLAUDE.md §4.7) | the arXiv `cat:` filter in the m2 Atom channel; the m3 driver's query |
| `description` | `TEXT NOT NULL DEFAULT ''` | free text, `max_length=512`, control chars stripped before storage; rendered **autoescaped** (never `\| safe`) | the `abs:`/`ti:` keyword clause in the m2/m3 query; operator-facing context |

**Decisions locked here:**
- Both fields are operator-supplied and optional. An empty `discovery_category` means "no
  category declared" and MUST never be rejected (FM-1).
- `discovery_category` is a fixed enum, NOT free text — it feeds an arXiv `cat:` filter
  directly, so it must be a valid arXiv category code. The four values are arXMCP's target
  categories (CLAUDE.md §2). Adding categories is a deliberate schema change, not a v1 knob.
- `description` carries the free-text topic/keywords (e.g. "Bridgeland stability on K3
  surfaces"). It is the `abs:`/`ti:` keyword source for the keyword channel.
- Edit surface: a **dedicated** `PATCH /ui/api/notebooks/{slug}/topic` route +
  `NotebookTopicUpdate` model, kept separate from the rename endpoint so the rename
  endpoint's mass-assignment defense stays intact.
- Backup: the columns live in `var/arxmcp/cache/notebooks.db`, already an explicit entry
  in `ops/cron/arxmcp-backup.sh` and called out in `08-security-observability-ops.md` as
  non-regenerable user state. **No backup-script change is needed** — the AC "new columns
  in restic scope" is satisfied by the existing file-level include.

---

## 2. The propose → confirm model (m2–m4 contract)

Discovery is a **deterministic, LLM-free, human-confirmed** flow. This is load-bearing and
non-negotiable:

1. **Deterministic ingest job, not an LLM-in-the-loop crawl.** The discovery driver issues
   official-API queries (arXiv Atom in m2; Semantic Scholar / OpenAlex in m3; local
   citation-graph in m4), deduplicates, and returns a ranked candidate list. No `anthropic`
   SDK at runtime (CLAUDE.md §4.7) — the server NEVER calls an LLM to score relevance.
   Relevance judgment belongs to the calling agent retrieving over the expanded corpus, or
   to the operator reviewing candidates.
2. **Propose → confirm, never auto-ingest (v1).** Candidates are *proposed* in the operator
   console; the operator clicks "Add" to route a paper through the existing
   `ingest_one_paper` pipeline into the notebook's LanceDB. This honors
   `01-mission-and-context.md`'s "power tool, not autopilot". An opt-in auto-ingest
   threshold is explicitly deferred (Won't, this cycle).
3. **Candidate queue is ephemeral in v1.** The proposed list is not persisted; the panel is
   labeled "Refresh to re-run discovery". If a future milestone needs the queue to survive
   restarts, add a `notebook_discovery_candidates` table — do NOT assume one exists.
4. **No new MCP tool in v1.** The discovery surface is the operator console, not the MCP
   tool surface — so `EXPECTED_TOOL_SCHEMA_SHA256` and the BP1 prefix stay byte-stable. An
   agent-facing `discover_papers` MCP tool is a deferred v2 (it forces a BP1 cold-start
   cache bust that must be batched with other tool additions — `07-multi-agent-caching.md`).

---

## 3. Channel-dedup boundary (m3 contract — CC-3)

When multiple channels run (arXiv Atom + Semantic Scholar + OpenAlex), **deduplication
happens AFTER channel aggregation, not inside each channel.** The orchestrator:

1. runs each channel, collecting raw candidates;
2. merges all channel results into one list;
3. deduplicates the merged list (by arXiv id) against itself AND against the notebook's
   existing `notebook_papers` junction rows;
4. ranks and proposes the survivors.

Rationale: running channels in parallel and deduping inside each channel races on the same
`notebook_papers` reads and can propose the same paper twice from two channels. A single
post-aggregation dedup pass is the only correct boundary. Each channel is therefore a pure
"query → raw candidates" function; the orchestrator owns dedup + ranking + the propose step.

---

## 4. What m1 deliberately did NOT do

- No discovery driver, no arXiv-API library, no new channel (m2+).
- No relevance scoring / SPECTER2 / novelty-threshold stopping (deferred; the calling agent
  reads abstracts in v1).
- No OAI-PMH topic-filter hook (CAND-8, Won't this cycle).
- No candidate-queue persistence table (queue is ephemeral until a milestone needs otherwise).

---

## 5. Cross-references

- Roadmap: `plans/notebook-paper-discovery-roadmap.md`
- Scout report: `.claude/notes/capability-scouts/2026q2-crawl4ai-paper-discovery/artifacts/final-report.md`
- Schema: `server/notebooks_store.py` (SCHEMA_VERSION 5, v4→v5 block)
- Routes: `server/routes/notebooks.py` (`_validate_discovery_category`, `NotebookTopicUpdate`, `PATCH /notebooks/{slug}/topic`)
- Constraints: CLAUDE.md §1 (doc placement), §4.7 (no `assert`, no runtime `anthropic` SDK), §2 (target categories); `01-mission-and-context.md` (power-tool framing); `07-multi-agent-caching.md` (BP1 stability).

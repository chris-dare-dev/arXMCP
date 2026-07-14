# Critique (merged) — license-serving-removal-m1

Critics run: 1 independent adversary (general-purpose agent, hand-driven — the
bespoke `milestone-arxmcp-critic` / `milestone-adversary-critic` types are not
loadable from this non-repo session) + orchestrator (Opus) adversarial pass.
Reviewed commit range `2698ac8..b6b77be`.

Severity counts: CRITICAL 0, HIGH 0, MEDIUM 0, LOW 2

Core change verified clean on all high-severity axes: correctness (no dangling
name / dead branch in `chunk.py`), leak/consumer (get_chunk is the only
full-body surface; no `.py` imports `server.license_policy`; nothing reads
`truncated_for_license`), version machinery (`TOOL_SCHEMA_VERSION==19`
consistent across tools.py, both `*_result.json`, and every asserting test; the
critic recomputed the pinned hash `126512c0…` byte-for-byte), and coverage
(full-body serving for non-OA/unknown/null tokens + byte-cap still fires).

**L1 — trust-language census lists the removed truncated_for_license field** (LOW)
**Where:** `.claude/docs/trust-language-policy.md:212`
**What:** Appendix B "current MCP-surface trust-vocabulary census" still lists
`truncated_for_license` in the `get_chunk` row.
**Why it matters:** This doc is binding (CLAUDE.md §4.9); after this milestone
`get_chunk` never emits that field, so the "fields today" inventory is
inaccurate. Mitigating: the census is a dated 2026-07-12 snapshot (it already
omits m5's source-truth fields).
**Proposed fix:** Strike `truncated_for_license` from the get_chunk row with an
inline "removed in license-serving-removal-m1" note; leave the snapshot date.
**Source critic:** general-purpose adversary

**L2 — design/security notes describe the removed e5 gate as live/forthcoming** (LOW)
**Where:** `.claude/notes/05-storage-and-indexing.md:70`
**What:** This note (and `.claude/docs/security-pdf-sandbox.md:350-351` and
`:467`) reference the e5 `truncated_for_license` enforcement as active/planned.
**Why it matters:** The gate was removed by this milestone, so the notes
describe a non-existent feature as live/forthcoming. Lower stakes: design /
PDF-planning notes, no test guards them.
**Proposed fix:** Append a "removed in license-serving-removal-m1" note at each
of the three sites.
**Source critic:** general-purpose adversary

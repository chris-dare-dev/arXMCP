# E12 — Full Corpus Cutover (Scoped Out — Folded into E11)

Epic dependencies: E11

Goal: This epic is **scoped out**. Its content has been folded entirely into E11_S01 through E11_S05. The original E12 covered the 200K-paper Academic Torrents seed download, bulk parse/chunk/embed, HNSW + Tantivy index build, atomic corpus swap, citation-graph population at full scale, and the 7-consecutive-night daily-delta validation. All of those milestones now live in E11, which owns the complete Tier-5 scale cutover. Backup/restore work (original E12_S08–S09) is folded into E14_S05. This file is retained as an empty placeholder so the README's E01–E14 epic table and critique-remediation matrix remain consistent with the milestone numbering.

Effort: 0 — no new engineering work.

References: `.claude/roadmap/E11-scale-cutover.md` (E11_S01–E11_S05 absorb all former E12 scope)

---

### E12_S01 — SCOPED OUT: content folded into E11_S01–E11_S05

**Status:** SCOPED_OUT_FOLDED_INTO E11_S01..E11_S05
**Tier:** 5
**Effort:** —
**Dependencies:** E11_S05

**Description.** The work originally planned for E12 — preflight hardware validation, Academic Torrents seed download, bulk parse/chunk/embed across ~200K papers, HNSW/Tantivy/B-tree index build, atomic MVCC corpus-version swap, citation-graph population at full scale (OpenAlex + INSPIRE-HEP), full-corpus retrieval-quality eval, 7-night daily-delta validation, and restic backup/restore — is fully covered by E11_S01 (bulk ingest), E11_S02 (OAI-PMH delta loop), E11_S03 (citation-graph enrichment), E11_S04 (drift watchdog + eval re-labeling), and E11_S05 (activation criteria + atomic swap). The decision to consolidate followed the realization that E12's scope was ~90% a direct continuation of E11 with no architectural boundary between them; keeping them separate added overhead without clarity. Backup and restore is handled by E14_S05.

**Out of scope.** Everything — this milestone exists only to satisfy the README's epic table and is never executed.

**Labels.** `area:infra`, `kind:infra`, `tier:5`

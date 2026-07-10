---
name: bp1-description-vs-handler-validator-drift
description: When a coordinated BP1 invalidation milestone edits a ToolMeta.description to "document widened acceptance", verify the actual handler validator was widened in lockstep
metadata:
  type: feedback
---

When an arXMCP milestone is positioned as a "coordinated BP1 cache-
invalidation checkpoint" that bundles a multi-milestone family's
re-pins and announces (via `ToolMeta.description` edit) a widened
contract — STOP and grep the matching handler validator. The
description edit is the *announcement*; the handler validator is the
*reality*. If these drift, every agent that obeys the new description
gets hard-errored on the common path.

**Why:** textbook-ingest-m3 (2026-05-27) shipped a SEARCH_PAPERS
description edit promising "validated against the arXiv or textbook:
<slug> format" while `server/handlers/search.py:175` still called
`is_valid_arxiv_paper_id` (textbook-rejecting). The m1 docstring on
`is_valid_arxiv_paper_id` explicitly said "once m2 ships, [callers]
opt into the union by switching to `is_valid_paper_id`". m3 was the
milestone that should have performed the switch; the synthesis
miscited which validator the search handler uses.

**How to apply:** On every coordinated-BP1-bump milestone where the
description edit widens an acceptance contract:

1. Read the description edit in `server/tools.py` carefully — note
   what new shape/value/format it promises.
2. `grep -n is_valid_arxiv_paper_id\|is_valid_paper_id
   server/handlers/*.py` (or the analogous narrow vs. union validator
   pair).
3. Identify which handler's validator is named in the description's
   contract (search vs. lemma vs. paper vs. definitions vs. chunk).
4. If the handler uses the narrow validator but the description
   promises the wider contract — flag HIGH.

The trap is symmetric with the m1 critique F1 (`stale-docstring-anti-
pattern` memory): the description claims one thing while the load-
bearing code says another. Both shipped because the milestone re-
verified at the description layer but not at the handler layer.

[[stale-docstring-anti-pattern]]

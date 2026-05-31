# Implementation Summary — corpus-integrity-completion-spike-1

**One-line summary:** Spike resolved — ship variant **(a) ONLY** for the e1 WAP gate, redefined as a marker-file readback verify; the roadmap's pre-recommendation of (c) is REFUTED. Binding decision artifact at `.claude/notes/milestones/corpus-integrity-completion-spike-1/decision.md` (~180 LOC Markdown).

**Commit range:** `297b690..HEAD` (single feat commit; spike has no source code changes — only the decision artifact + research artifacts).

**Implementation path:** inline (orchestrator main session). Zero source-code changes; one decision document; trivial under the 500 LOC / 5 files threshold.

## Acceptance criteria status

The parent roadmap's §Spike lane entry is the spike's sole AC:

- [x] **Pick the WAP gate variant for e1.** **MET.** Binding pick: variant **(a) ONLY**, redefined as marker-file readback verify (read `corpus-version.json` back from disk; parse `chunk_count`; compare against fresh `tbl.count_rows()`; raise on mismatch). Roadmap pre-recommendation of (c) explicitly refuted. Variant (b) explicitly does not ship.

- [x] **Address the tautology issue at `ingest/store.py:938-942`.** **MET.** Per R1's verbatim verification: `stats.total_rows_after_commit = chunk_count` is set BEFORE `write_corpus_version_marker(...)` is called; a second `count_rows()` under single-writer is `chunk_count == chunk_count` (identity). The decision document redefines (a) to compare two *different observations of different state surfaces* (marker file's stored value, read back from disk, vs. fresh `tbl.count_rows()`).

- [x] **Spike budget ≤ ½ day.** **MET.** Single decision artifact authored end-to-end; no source code changes; total wall-clock under a half-day budget.

- [x] **Unblock the Should-lane epic `e1`.** **MET.** The decision document includes the exact code shape (~25 LOC), test plan (3 mutation tests + 1 positive + 1 sanity), behavioral-contract change (preserve the existing m1-era best-effort swallow; add the readback gate as a second validation step that raises only on detected divergence), and a clear failure-mode coverage matrix.

## Decisions surfaced beyond the AC

The spike surfaced FIVE concrete decisions for the future e1 milestone, beyond just "pick a variant":

1. **The literal "second `count_rows()`" recommendation is tautological** under the single-writer-per-dataset model. The correct gate compares the **marker FILE's stored value** (read back from disk) against a fresh `count_rows()` — two different observations of two different state surfaces.

2. **Variant (b) cannot ship** because of `merge_insert` upsert semantics on resumable bulk runs. The staging-LanceDB design is structurally idempotent (per-paper sidecar checks + merge_insert), so `expected_total = sum(len(chunks))` overcounts re-processed papers while `tbl.count_rows()` correctly reports distinct rows. A 200K-paper bulk operator running in stages would trigger constant false-positives — the gate becomes noise.

3. **The existing best-effort swallow is preserved.** The gate is an *additional* validation step inside the existing `try:` block; it raises only when divergence is detected, not on every transient I/O hiccup. This is R2's "option (ii)" and is strictly safer than removing the swallow.

4. **`ingest/re_embed.py`'s twice-per-paper `write_chunks` calls** are automatically covered by the in-`write_chunks` gate (a). No separate wiring required. This is a structural advantage of (a) over (b).

5. **Sibling marker writers** (`server/routes/notebooks._rewrite_corpus_version_marker`, `tools/notebook_reconcile_marker.py`) remain out-of-scope per m3 follow-up F2-extension. The spike documents the deferral; e1 doesn't add coverage there.

## New / changed test paths

**None** — this is a spike (discovery milestone). Zero code changes. The future e1 milestone will land:
- `tests/test_write_chunks_wap_gate.py` (NEW) — 3 mutation tests + 1 positive + 1 sanity, per decision §3 test plan.

## Project check status

- `ruff check .` — N/A (no source code changes).
- `pytest` — N/A.
- This is a discovery milestone; the project check command is irrelevant for the spike itself. The future e1 milestone will run the project check at its own Phase 2 + 4.

## External writes the orchestrator must authorize

**None.** This is a purely-local decision artifact. The eventual `git push origin main` after Phase 4 is a separate per-event authorization. The synthesis §9 recorded `external_writes_required = []` and both researchers agreed.

## Deviations from the brief's design

The spike's job was to confirm or refute the roadmap's pre-recommendation of (c). The spike **refuted (c)** with concrete codebase grounding. This is a deliberate deviation from the brief's pre-recommendation — but it's what spikes are FOR. Both researchers independently caught problems with the pre-recommendation:
- R1 caught the tautology refinement (the literal (a) needs to be marker-file readback, not second `count_rows()`).
- R2 caught the (b) false-positive landmine (merge_insert idempotency).

Either finding alone would have invalidated the (c) pre-recommendation. Together they produce a tighter, more honest binding implementation contract for e1.

## Adversary critic preparation

The adversary critic will fire (always-on per pipeline rules). The infra-safety critic will NOT fire — zero infra changes. Likely critique axes:

- **Cache byte-stability:** N/A (no MCP surface or code).
- **Math fidelity:** N/A.
- **Security:** N/A (no tool input, no LaTeXML).
- **MCP spec:** N/A.
- **Local-first:** N/A.
- **Tier sequencing:** the decision document references m1's table-derived count fix, m2's runbook, m3's multi-call integration fixture — all shipped. No tier-gap.
- **No-fork:** N/A.
- **Test surface:** the spike adds NO tests directly. Future e1's test plan is documented in the decision §3.

Likely deeper critique angles:

- **The synthesis claims R1 + R2 disagreed but collapsed.** The adversary may push: is R1's (c) recommendation genuinely refuted, or just deferred to a different form? Synthesizer judgment: R1's escape hatch ("use `WriteStats.total_rows_after_commit` from the last call") IS R2's "(b) collapses into (a)" — same operation, different framing. The synthesis surfaces this collapse explicitly in §4. Open for adversary review.

- **The "best-effort swallow" preservation is a behavioral contract decision.** A critic could argue the swallow is itself a code smell that the WAP gate should clean up. Synthesizer judgment: defer to e1's discretion. The decision document says option (ii) is "strictly safer"; option (i) (remove the swallow entirely) is also "acceptable — the important thing is the gate EXISTS." This is a structural-not-binding decision that e1's implementer can refine.

- **Variant (b) deferral honesty.** The decision §6 says "no (b) variant ever ships" — that's a strong claim. The critic may push: under what future state would (b) become viable? Synthesizer's already-documented answer: "If future work needs caller-arithmetic detection, the right shape is to ADD a `chunks_written_distinct` field to `WriteStats` and have the bulk driver track distinct chunk_ids — but this is out-of-scope for the corpus-integrity-completion epic." Open for adversary review.

- **The spike's "binding" character.** Spikes are discovery; their output is advice. The decision document calls itself "binding implementation contract." A critic could push back on the strength of that language. Synthesizer judgment: the document IS binding because both researchers reached the same surgical recommendation through independent paths AND the recommendation is grounded in concrete codebase quotes (single-writer constraint, idempotent merge_insert). The strength is appropriate; the e1 milestone can deviate only with explicit justification.

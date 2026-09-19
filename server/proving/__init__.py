"""WS-D proving-lane library (stage2/arx-d3).

Subpackage for the agentic math-proving workflows' soundness-critical
components:

- :mod:`server.proving.contracts` — ProofTask / EvidenceBundle schema
  loading + validation (WS-D-authored v0.2 content for the WS-C stubs;
  custody moves to ``contracts/`` at Stage-2 integration per IF-5 —
  see ``server/proving/README.md``).
- :mod:`server.proving.skeptic` — the D-5 counterexample-first skeptic
  lane (runs BEFORE any prover cycle; a counterexample hit yields the
  verdict ``refuted``; AC-D.10).
- :mod:`server.proving.sympy_runner` — the sandboxed SymPy/CAS
  subprocess runner (``ARXMCP_ENABLE_SKEPTIC_CAS``-gated, default OFF;
  AC-D.11).
- :mod:`server.proving.faithfulness` — the D-3 statement-faithfulness
  gate (L1): dual independent formalization + kernel-checked
  equivalence + blind back-translation diff + human sign-off; the
  AC-D.5 award rule.
- :mod:`server.proving.orchestrator` — the D-6 orchestrator v0: one
  ProofTask → one schema-valid EvidenceBundle, abstained by default,
  skeptic lane first, budget-boxed, field-tiered via
  ``lane_config.json`` (AC-D.13/14/15; pipeline home:
  ``.claude/proving/``).

Nothing in this package registers anything on the MCP surface — the
``tools/list`` bytes (BP1) are untouched, exactly like ``server/kat.py``.
"""

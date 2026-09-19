"""Mathlib-REPL integration tests (Stage-2 slice arx-d1 / WS-D D-1).

The verification-feedback-era ``requires_lean_repl`` tests exercise the
REPL protocol against ANY built ``leanprover-community/repl`` package —
including the original zero-dependency spike build, which cannot
elaborate ``import Mathlib.*``. This module pins the D-1 deliverable:
``lean_verify`` (and the underlying harness) against a **mathlib-built**
REPL environment (`.claude/docs/lean-mathlib-toolchain.md`).

Gating — two tiers, mirroring the ``requires_model`` + per-model env-var
discipline (CLAUDE.md §4.5):

1. ``@pytest.mark.requires_lean_repl`` — skipped unless BOTH
   ``ARXMCP_LAKE_PATH`` and ``ARXMCP_LEAN_REPL_DIR`` are set.
2. ``ARXMCP_LEAN_REPL_HAS_MATHLIB=1`` — the operator's assertion that
   ``ARXMCP_LEAN_REPL_DIR`` points at a mathlib-enabled workspace (a
   Lake package requiring both mathlib and REPL). Without it these
   tests SKIP rather than fail against a core-Lean-only REPL.

Latency note: mathlib module imports here measured 5-14 s *warm* on
the reference workstation, but a first-of-day COLD import of the
Analysis tower exceeded ``DEFAULT_QUERY_TIMEOUT_S`` (30 s) and timed
out through the handler (measured 2026-07-04). The autouse
``_prewarm_mathlib_oleans`` fixture below therefore warms the OS file
cache through a raw ``LeanRepl`` (whose ``query`` takes an explicit
generous timeout) before any 30 s-budget handler test runs — the same
pre-warm production needs (a D-2/D-7 design input, recorded in
`.claude/docs/lean-mathlib-toolchain.md` §3). A full ``import
Mathlib`` is deliberately NOT exercised through the handler: its cold
load (33 s measured) is likewise a pre-warm concern, not a D-1 test.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest

from server.config import Config
from server.handlers.lean_verify import handle_lean_verify
from server.lean_repl import LeanRepl
from server.tools import reset_resources_for_tests, set_resources

# ---------------------------------------------------------------------------
# Opt-in detection (base pair mirrors test_lean_repl.py; the mathlib
# assertion env var mirrors ARXMCP_RUN_REAL_BGE_RERANKER discipline)
# ---------------------------------------------------------------------------

_LAKE_PATH = os.environ.get("ARXMCP_LAKE_PATH")
_REPL_DIR = os.environ.get("ARXMCP_LEAN_REPL_DIR")
_HAS_MATHLIB = os.environ.get("ARXMCP_LEAN_REPL_HAS_MATHLIB") == "1"
_mathlib_skip = pytest.mark.skipif(
    not (_LAKE_PATH and _REPL_DIR and _HAS_MATHLIB),
    reason=(
        "set ARXMCP_LAKE_PATH + ARXMCP_LEAN_REPL_DIR (pointing at a "
        "mathlib-enabled REPL workspace) + ARXMCP_LEAN_REPL_HAS_MATHLIB=1"
    ),
)

#: The handler's own docstring example module (AC-D.3 seed): the import
#: that fails against the no-mathlib spike REPL and must succeed here.
_GROUP_DEFS = "Mathlib.Algebra.Group.Defs"

#: Every module the 30 s-budget handler tests import. The pre-warm
#: fixture loads the UNION closure in one REPL command (one env — the
#: fresh-env-per-command RSS accumulation documented in
#: lean-mathlib-toolchain.md §3 makes one combined import cheaper than
#: three sequential ones).
_PREWARM_IMPORTS = (
    _GROUP_DEFS,
    "Mathlib.Analysis.SpecialFunctions.Sqrt",
    "Mathlib.NumberTheory.Real.Irrational",
)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module", autouse=True)
def _prewarm_mathlib_oleans():
    """Warm the OS file cache for the handler tests' olean closures.

    ``handle_lean_verify`` runs every query under the fixed
    ``DEFAULT_QUERY_TIMEOUT_S`` (30 s). Cold-cache reality on the
    reference workstation (2026-07-04): the first
    ``Mathlib.Analysis.SpecialFunctions.Sqrt`` import of the day took
    > 30 s and the handler returned ``lean_status: "timeout"``; the
    identical query re-run warm finished in ~11 s. Pre-warming once
    per module makes the handler-tier tests deterministic instead of
    OS-cache-dependent.

    No-ops (cheaply) when the mathlib gate is off so collection-only
    and skip runs pay nothing.
    """
    if not (_LAKE_PATH and _REPL_DIR and _HAS_MATHLIB):
        yield
        return

    async def _go() -> None:
        repl = await LeanRepl.spawn(lake_path=_LAKE_PATH, repl_dir=_REPL_DIR)
        try:
            import_block = "\n".join(f"import {m}" for m in _PREWARM_IMPORTS)
            await repl.query({"cmd": import_block}, timeout=240.0)
        finally:
            await repl.close()

    _run(_go())
    yield


class _FakeCorpusInfo:
    """``envelope()`` reads ``get_resources().corpus_info.version``
    (BP1 corpus_version echo) — mirror test_handlers_lean_verify."""

    version = 1


def _attach_real_resources(lean_repl: Any) -> None:
    """Attach a minimal Resources stand-in carrying a REAL LeanRepl.

    Mirrors ``test_handlers_lean_verify._attach_fake_resources`` — the
    handler consults ``.lean_repl``, ``.corpus_info`` (envelope), and
    (on the respawn path) ``.config``.
    """
    cfg = Config(
        enable_lean=True,
        lake_path=_LAKE_PATH,
        lean_repl_dir=_REPL_DIR,
    )

    class _Res:
        pass

    res = _Res()
    res.config = cfg
    res.corpus_info = _FakeCorpusInfo()
    res.lean_repl = lean_repl
    set_resources(res)


@pytest.mark.requires_lean_repl
@_mathlib_skip
class TestMathlibHarness:
    """Raw LeanRepl round-trips — the exact server spawn contract
    (``lake exe repl``, cwd=ARXMCP_LEAN_REPL_DIR) against mathlib."""

    def test_mathlib_import_elaborates_clean(self):
        """A Group-theory theorem via a Mathlib import returns a clean
        environment (no error messages) — the D-1 existence proof."""

        async def _go():
            repl = await LeanRepl.spawn(lake_path=_LAKE_PATH, repl_dir=_REPL_DIR)
            try:
                return await repl.query(
                    {
                        "cmd": (
                            f"import {_GROUP_DEFS}\n"
                            "theorem arx_d1_smoke (G : Type) [Group G] "
                            "(a b : G) : a * b * b⁻¹ = a := by simp"
                        )
                    },
                    timeout=120.0,
                )
            finally:
                await repl.close()

        resp = _run(_go())
        errors = [
            m
            for m in resp.get("messages", [])
            if m.get("severity") == "error"
        ]
        assert errors == [], resp
        assert "env" in resp, resp


@pytest.mark.requires_lean_repl
@_mathlib_skip
class TestMathlibLeanVerify:
    """``handle_lean_verify`` against the mathlib REPL — the tool-level
    contract D-2/D-4 build on. Each test spawns its own REPL (the
    ``TestRealLeanRepl`` pattern)."""

    @staticmethod
    async def _setup() -> LeanRepl:
        repl = await LeanRepl.spawn(lake_path=_LAKE_PATH, repl_dir=_REPL_DIR)
        _attach_real_resources(repl)
        return repl

    @staticmethod
    async def _teardown(repl: LeanRepl) -> None:
        try:
            await repl.close()
        finally:
            reset_resources_for_tests()

    def test_group_defs_import_succeeds(self):
        """AC-D.3 seed: ``imports=["Mathlib.Algebra.Group.Defs"]`` — the
        handler's own docstring example, which fails against the
        no-mathlib spike REPL — verifies clean here."""

        async def _go():
            repl = await self._setup()
            try:
                return await handle_lean_verify(
                    snippet=(
                        "theorem arx_d1_one_mul (G : Type) [Group G] "
                        "(a : G) : 1 * a = a := one_mul a"
                    ),
                    imports=[_GROUP_DEFS],
                )
            finally:
                await self._teardown(repl)

        result = _run(_go())
        assert result["status"] == "ok", result
        assert result["compilation_success"] is True
        assert result["lean_status"] == "available"

    def test_analysis_lemma_succeeds(self):
        """A lemma through the Analysis tower (`Real.sqrt` basics) —
        the target mathematics actually lives above Algebra."""

        async def _go():
            repl = await self._setup()
            try:
                return await handle_lean_verify(
                    snippet=(
                        "theorem arx_d1_sqrt_nonneg : "
                        "0 ≤ Real.sqrt 2 := Real.sqrt_nonneg 2"
                    ),
                    imports=["Mathlib.Analysis.SpecialFunctions.Sqrt"],
                )
            finally:
                await self._teardown(repl)

        result = _run(_go())
        assert result["status"] == "ok", result
        assert result["compilation_success"] is True

    def test_irrational_sqrt_two_succeeds(self):
        """The KAT-suite TRUE-known-formal classic (acceptance-criteria
        §WS-D): √2 is irrational via mathlib's ``irrational_sqrt_two``."""

        async def _go():
            repl = await self._setup()
            try:
                return await handle_lean_verify(
                    snippet=(
                        "theorem arx_d1_irr : Irrational (Real.sqrt 2) "
                        ":= irrational_sqrt_two"
                    ),
                    imports=["Mathlib.NumberTheory.Real.Irrational"],
                )
            finally:
                await self._teardown(repl)

        result = _run(_go())
        assert result["status"] == "ok", result
        assert result["compilation_success"] is True

    def test_false_mathlib_statement_rejected(self):
        """Negative control (MA-4 discipline): a false statement in
        mathlib vocabulary must come back ``error``, proving the oracle
        is not vacuously green against this environment."""

        async def _go():
            repl = await self._setup()
            try:
                return await handle_lean_verify(
                    snippet=(
                        "theorem arx_d1_bad (G : Type) [Group G] "
                        "(a b : G) : a * b = b * a := by simp"
                    ),
                    imports=[_GROUP_DEFS],
                )
            finally:
                await self._teardown(repl)

        result = _run(_go())
        assert result["status"] == "error", result
        assert result["compilation_success"] is False
        assert any(
            m["severity"] == "error" for m in result["messages"]
        ), result

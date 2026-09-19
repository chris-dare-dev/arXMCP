#!/usr/bin/env python3
"""D-6 proving-pipeline driver (stage2/arx-d3 — WS-D).

The CLI half of the ``.claude/proving/`` pipeline: the Claude role
loop (sketcher → autoformalizer → tactician → fixer) writes its role
outputs to a JSON file, and THIS driver runs the deterministic engine
(``server.proving.orchestrator``) over one envelope-wrapped ProofTask:

1. **KAT controls first** (AC-D.8): a seeded control subset
   (≥ 1 TRUE-formal, ≥ 1 FALSE, ≥ 1 OPEN) is resolved against the real
   verifier and scored. Any proven-* on a FALSE/OPEN control raises
   the AC-D.9 hard halt (exit 3) BEFORE the task runs — a pipeline
   that cannot pass its controls has no business emitting verdicts.
2. **The pipeline**: skeptic lane (counterexample-first, AC-D.10) →
   prover cycles → D-3 faithfulness gate → pure verdict award —
   abstained by default; budget-boxed (AC-D.15).
3. The emitted EvidenceBundle is schema-validated and written to
   ``--out``. It is ALWAYS ``publishable: false``: this driver cannot
   sign the D-3 human checkbox — that is ``tools/sign_bundle.py``, an
   operator-invoked surface.

Lean wiring follows the gated-test discipline: set
``ARXMCP_LAKE_PATH`` + ``ARXMCP_LEAN_REPL_DIR`` (D-1 toolchain:
``…/_toolchains/mathlib-repl/project``); without them the engine runs
with no verifier and every formal resolution honestly degrades (the
controls then fail reportability — by design, not by accident).

Exit codes: 0 = bundle emitted; 2 = input/validation error;
3 = KAT escalation (RED ALARM — halt for human review);
4 = the bundle itself is escalated (evidence conflict / false-accept
defense) — emitted for audit, but the run must stop.

Usage::

    python -m tools.prove_task --task task.json \
        [--role-outputs roles.json] --controls-seed 20260704 \
        [--skip-controls] [--cas-on] --out bundle.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from server.config import Config
from server.handlers.lean_verify import handle_lean_verify
from server.kat import KatEscalation
from server.lean_repl import LeanRepl
from server.proving.contracts import ContractValidationError
from server.proving.orchestrator import (
    RoleOutputs,
    run_kat_controls,
    run_proving_pipeline,
)
from server.tools import reset_resources_for_tests, set_resources

#: Generous one-off timeout for the olean prewarm (D-1 lesson: the
#: first heavy mathlib import of a session can exceed the handler's
#: 30 s budget; prewarming is raw-REPL, outside the handler).
PREWARM_TIMEOUT_S = 300.0


def _read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _collect_imports(task: dict, role_outputs_doc: dict | None) -> list[str]:
    """Union of every mathlib import the run will touch, for one
    prewarm query."""
    mods: set[str] = set()
    payload = task.get("payload") or {}
    for check in ((payload.get("skeptic_checks") or {}).get("lean") or ()):
        mods.update(check.get("imports") or ())
    for key in ("formal",):
        block = payload.get(key) or {}
        mods.update(block.get("imports") or ())
    if role_outputs_doc:
        for key in ("formalization_a", "formalization_b"):
            rec = role_outputs_doc.get(key) or {}
            mods.update(rec.get("imports") or ())
        for attempt in role_outputs_doc.get("attempts") or ():
            mods.update(attempt.get("imports") or ())
    return sorted(mods)


class _CliResources:
    """Minimal Resources stand-in for direct handler calls (the gated
    tests' pattern; no server process is involved)."""

    class _CorpusInfo:
        version = 0

    def __init__(self, config: Config, repl: LeanRepl) -> None:
        self.config = config
        self.corpus_info = self._CorpusInfo()
        self.lean_repl = repl


async def _amain(args: argparse.Namespace) -> int:
    task = _read_json(args.task)
    role_outputs_doc = _read_json(args.role_outputs) if args.role_outputs else {}
    role_outputs = RoleOutputs.from_dict(role_outputs_doc)

    lake_path = os.environ.get("ARXMCP_LAKE_PATH")
    repl_dir = os.environ.get("ARXMCP_LEAN_REPL_DIR")
    repl: LeanRepl | None = None
    resources: _CliResources | None = None
    verifier = None

    if lake_path and repl_dir:
        repl = await LeanRepl.spawn(lake_path=lake_path, repl_dir=repl_dir)
        config = Config(
            result_byte_cap=256 * 1024,
            enable_lean=True,
            lake_path=Path(lake_path),
            lean_repl_dir=Path(repl_dir),
        )
        resources = _CliResources(config, repl)
        set_resources(resources)

        async def verifier(snippet: str, imports: list[str]) -> dict:
            return await handle_lean_verify(snippet=snippet, imports=imports)

        prewarm = _collect_imports(task, role_outputs_doc)
        if prewarm and not args.no_prewarm:
            print(f"prewarming oleans: {', '.join(prewarm)}", file=sys.stderr)
            cmd = "\n".join(f"import {m}" for m in prewarm)
            await repl.query({"cmd": f"{cmd}\n#eval 1"}, timeout=PREWARM_TIMEOUT_S)
    else:
        print(
            "NOTE: ARXMCP_LAKE_PATH/ARXMCP_LEAN_REPL_DIR not set — running "
            "with no Lean verifier (formal resolutions degrade honestly; "
            "controls will be non-reportable)",
            file=sys.stderr,
        )

    try:
        controls = None
        if not args.skip_controls:
            report, controls = await run_kat_controls(
                lean_verify=verifier, seed=args.controls_seed
            )
            print(
                f"controls: run={report.run_id} reportable={report.reportable} "
                f"abstention_rate={report.abstention_rate:.2f} "
                f"ids={[o.entry_id for o in report.outcomes]}",
                file=sys.stderr,
            )

        result = await run_proving_pipeline(
            task=task,
            role_outputs=role_outputs,
            lean_verify=verifier,
            cas_on=True if args.cas_on else None,
            controls=controls,
        )
    finally:
        if repl is not None:
            try:
                current = resources.lean_repl if resources is not None else None
                if current is not None:
                    await current.close()
                if current is not repl:
                    await repl.close()
            finally:
                reset_resources_for_tests()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result.bundle, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"verdict={result.verdict} escalated={result.escalated} "
        f"cost={result.budget} -> {out_path}"
    )
    for reason in result.verdict_reasons:
        print(f"  reason: {reason}")
    if result.escalated:
        print(
            "ESCALATED: the bundle is emitted for audit but the run must "
            "halt for human review",
            file=sys.stderr,
        )
        return 4
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.prove_task",
        description="Run one ProofTask through the D-6 proving pipeline.",
    )
    parser.add_argument("--task", required=True, help="envelope-wrapped ProofTask JSON file")
    parser.add_argument(
        "--role-outputs",
        help="role-loop outputs JSON (sketch, formalizations, attempts, ...)",
    )
    parser.add_argument("--out", required=True, help="EvidenceBundle output path")
    parser.add_argument(
        "--controls-seed",
        type=int,
        default=None,
        help="seed for the AC-D.8 control sample (required unless --skip-controls)",
    )
    parser.add_argument(
        "--skip-controls",
        action="store_true",
        help="dev-only: skip the per-run KAT controls (production runs must not)",
    )
    parser.add_argument(
        "--cas-on",
        action="store_true",
        help="enable the sandboxed CAS runner for this run "
        "(equivalent to ARXMCP_ENABLE_SKEPTIC_CAS=true)",
    )
    parser.add_argument(
        "--no-prewarm",
        action="store_true",
        help="skip the olean prewarm query (cold first calls may time out)",
    )
    args = parser.parse_args(argv)
    if not args.skip_controls and args.controls_seed is None:
        parser.error("--controls-seed is required (or pass --skip-controls for dev runs)")

    try:
        return asyncio.run(_amain(args))
    except KatEscalation as exc:
        print(f"KAT ESCALATION (AC-D.9 halt): {exc}", file=sys.stderr)
        return 3
    except (ContractValidationError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Operator sign-off surface for the D-3 faithfulness gate
(stage2/arx-d3 — WS-D; AC-D.5's human checkbox).

THIS is the only sanctioned caller of
``server.proving.faithfulness.record_human_signoff`` — an
operator-invoked CLI, never pipeline automation (binding rule in
``server/proving/README.md``; the D-6 orchestrator and
``tools/prove_task.py`` cannot sign by construction and a source-scan
test pins that). The ``--i-am-a-human-operator`` flag is the grep-able
tripwire, not a proof of humanity: any automated invocation is visible
in review.

Flow: read a pipeline-emitted EvidenceBundle (always
``publishable: false``), review it YOURSELF (the whole point), then::

    python -m tools.sign_bundle --bundle bundle.json \
        --by "Chris Dare" [--note "checked statement + closure"] \
        --i-am-a-human-operator --out bundle.published.json

The tool signs the bundle's faithfulness record
(``record_human_signoff`` refuses if any machine-checkable element
fails) and re-derives the publishable award fail-closed
(``make_publishable_bundle``): anything short of a full
``proven-formal`` award refuses. The output validates against the
bundle schema, whose own law requires the signed checkbox on every
``publishable: true`` + ``proven-formal`` bundle.

Exit codes: 0 = published bundle written; 2 = refusal (unsigned gate
elements failing, no formal award, malformed input).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from server.proving.contracts import ContractValidationError
from server.proving.faithfulness import record_human_signoff
from server.proving.orchestrator import make_publishable_bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.sign_bundle",
        description=(
            "Record the operator's D-3 sign-off on an EvidenceBundle and "
            "emit its publishable form."
        ),
    )
    parser.add_argument("--bundle", required=True, help="pipeline-emitted EvidenceBundle JSON")
    parser.add_argument("--by", required=True, help="signer identity (you)")
    parser.add_argument("--note", help="optional review note recorded with the signature")
    parser.add_argument("--out", required=True, help="output path for the publishable bundle")
    parser.add_argument(
        "--i-am-a-human-operator",
        action="store_true",
        help=(
            "REQUIRED attestation that a human operator is invoking this "
            "command after reviewing the bundle. Pipeline automation must "
            "never pass this flag."
        ),
    )
    args = parser.parse_args(argv)

    try:
        bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
        block = (bundle.get("payload") or {}).get("faithfulness")
        if block is None:
            raise ValueError(
                "bundle carries no faithfulness record — the L1 gate did not "
                "run; there is nothing to sign"
            )
        signed = record_human_signoff(
            block,
            by=args.by,
            note=args.note,
            i_am_a_human_operator=args.i_am_a_human_operator,
        )
        published = make_publishable_bundle(bundle, signed)
    except (ContractValidationError, PermissionError, ValueError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(published, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    signoff = published["payload"]["faithfulness"]["human_signoff"]
    print(
        f"published: verdict=proven-formal publishable=true "
        f"signed_by={signoff['by']!r} at={signoff['at']} -> {out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

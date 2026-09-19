"""Envelope-wrapped proposed-notebook-manifest assembly (WS-E v0).

Builds ``arxmcp.bridge/proposed-notebook-manifest`` v0.2 artifacts
under the C1 bridge envelope (``contracts/envelope.v1.schema.json``)
and checks them twice:

1. :func:`conformance_violations` — the WS-E acceptance rules the JSON
   Schema alone cannot express (AC-E.2 window membership, AC-E.4
   non-empty provenance, 3-12-month window).
2. :func:`validate_against_contracts` — full JSON Schema validation
   against the repo's ``contracts/`` registry (the same Draft-07 +
   referencing stack as ``tests/_bridge_helpers.py``; re-implemented
   here because production/tool code must not import from ``tests/``).

Substrate block: the manifest is a SERVER-SCOPED artifact (it proposes
a notebook that does not exist yet), so ``corpus_version`` /
``notebook`` / ``filter_echo`` are null per the envelope's documented
server-scoped branch. ``tool_schema_sha256`` carries the BP1 pin
(:data:`TOOL_SCHEMA_SHA256_PIN`, kept in lockstep with
``tests/test_server_tool_schema.py::EXPECTED_TOOL_SCHEMA_SHA256`` by a
dedicated test).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.exploration.windowing import Window, paper_id_month, parse_window

ARTIFACT_TYPE = "arxmcp.bridge/proposed-notebook-manifest"
ARTIFACT_VERSION = "0.2"
PRODUCER = "exploration-scout-v0"

#: Vendored copy of EXPECTED_TOOL_SCHEMA_SHA256 (the BP1 tools/list
#: byte-stability pin, tests/test_server_tool_schema.py). Tool code
#: must not import from tests/; the lockstep test
#: tests/tools/test_exploration_pipeline.py::test_tool_schema_pin_lockstep
#: fails this constant the moment the real pin moves.
TOOL_SCHEMA_SHA256_PIN = "11ad4b0bebff8efcf228d405c4131c3d47f4f56634176b79e3cdf712a511ea68"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONTRACTS_DIR = REPO_ROOT / "contracts"


def build_manifest(
    *,
    topic: dict[str, Any],
    window: Window,
    papers: list[dict[str, Any]],
    textbooks: list[dict[str, Any]],
    open_problem_sources: list[dict[str, Any]] | None = None,
    channels: dict[str, Any] | None = None,
    dedup: dict[str, Any] | None = None,
    produced_at: str | None = None,
    tool_schema_sha256: str = TOOL_SCHEMA_SHA256_PIN,
) -> dict[str, Any]:
    """Assemble the envelope-wrapped manifest dict (no I/O)."""
    if produced_at is None:
        produced_at = (
            datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
    payload: dict[str, Any] = {
        "topic": topic,
        "window": window.as_payload(),
        "papers": papers,
        "textbooks": textbooks,
    }
    if open_problem_sources is not None:
        payload["open_problem_sources"] = open_problem_sources
    if channels is not None:
        payload["channels"] = channels
    if dedup is not None:
        payload["dedup"] = dedup
    return {
        "bridge": {
            "artifact": ARTIFACT_TYPE,
            "version": ARTIFACT_VERSION,
            "producer": PRODUCER,
            "produced_at": produced_at,
            "substrate": {
                "server": "arxmcp",
                "corpus_version": None,
                "notebook": None,
                "filter_echo": None,
                "retrieval_mode": "dense_only",
                "tool_schema_sha256": tool_schema_sha256,
            },
        },
        "payload": payload,
    }


def conformance_violations(manifest: dict[str, Any]) -> list[str]:
    """WS-E acceptance rules beyond the JSON Schema (empty list = pass).

    - AC-E.2: every proposed paper's date falls inside the manifest's
      window. Papers with a ``published`` date must have it in-window;
      papers WITHOUT one (citation-graph candidates — the graph carries
      no dates, finding 01 §2.a.1) must have a new-style arXiv id whose
      YYMM submission month lies entirely inside the window. A paper
      with neither signal cannot be shown recent and fails.
    - AC-E.4: every paper carries a non-empty ``source_citation``.
    - Window: parseable and 3-12 months (re-checked from the artifact
      itself so a hand-edited manifest cannot smuggle a bad window).
    """
    violations: list[str] = []
    payload = manifest.get("payload", {})
    window_block = payload.get("window", {})
    try:
        window = parse_window(
            str(window_block.get("from", "")), str(window_block.get("to", ""))
        )
    except ValueError as exc:
        return [f"window: {exc}"]

    for i, paper in enumerate(payload.get("papers", [])):
        ident = paper.get("arxiv_id") or paper.get("url") or f"papers[{i}]"
        citation = str(paper.get("source_citation", "") or "").strip()
        if not citation:
            violations.append(
                f"{ident}: missing source_citation (AC-E.4 — no unsourced proposals)"
            )
        published = str(paper.get("published", "") or "")
        if published:
            if not window.contains(published):
                violations.append(
                    f"{ident}: published {published!r} is not inside the window "
                    f"{window.start.isoformat()}..{window.end.isoformat()} (AC-E.2)"
                )
        else:
            ym = paper_id_month(str(paper.get("arxiv_id", "") or ""))
            if ym is None or not window.contains_month(*ym):
                violations.append(
                    f"{ident}: no published date and the arXiv-id month is not "
                    f"entirely inside the window "
                    f"{window.start.isoformat()}..{window.end.isoformat()} (AC-E.2)"
                )
    return violations


def validate_against_contracts(
    manifest: dict[str, Any], contracts_dir: Path | None = None
) -> None:
    """Validate against the repo contracts registry; raise on failure.

    Uses the same Draft-07 + ``referencing`` resolution the contract
    test suite uses. ``jsonschema`` arrives transitively in the
    project venv; degrade with a clear message if it is missing.
    """
    try:
        import jsonschema
        from referencing import Registry, Resource
        from referencing.jsonschema import DRAFT7
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError(
            "jsonschema/referencing not importable — run `uv sync --extra dev` "
            "or pass --skip-contract-validation"
        ) from exc

    cdir = contracts_dir if contracts_dir is not None else CONTRACTS_DIR
    registry_manifest = json.loads((cdir / "registry.json").read_text(encoding="utf-8"))
    entry = registry_manifest["artifact_types"][ARTIFACT_TYPE]
    if entry["version"] != ARTIFACT_VERSION:
        raise RuntimeError(
            f"producer emits {ARTIFACT_TYPE} v{ARTIFACT_VERSION} but the registry "
            f"pins v{entry['version']} — update tools/exploration/manifest.py and "
            "contracts/ together (CONTRACTS.md rule 3)"
        )

    schema_paths = sorted(cdir.glob("*.schema.json")) + sorted(
        (cdir / "payloads").glob("*.schema.json")
    )
    resources = []
    for path in schema_paths:
        schema = json.loads(path.read_text(encoding="utf-8"))
        resources.append(
            (schema["$id"], Resource.from_contents(schema, default_specification=DRAFT7))
        )
    registry = Registry().with_resources(resources)
    schema = json.loads((cdir / entry["schema"]).read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema, registry=registry)
    errors = [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in validator.iter_errors(manifest)
    ]
    if errors:
        raise RuntimeError(
            "manifest does not validate against "
            f"{entry['schema']}: " + "; ".join(errors)
        )


def write_manifest(manifest: dict[str, Any], out_path: Path) -> None:
    """Write the manifest as UTF-8 JSON (trailing newline, 2-space indent).

    The ONLY write the exploration pipeline performs (AC-E.1).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


__all__ = [
    "ARTIFACT_TYPE",
    "ARTIFACT_VERSION",
    "CONTRACTS_DIR",
    "PRODUCER",
    "TOOL_SCHEMA_SHA256_PIN",
    "build_manifest",
    "conformance_violations",
    "validate_against_contracts",
    "write_manifest",
]

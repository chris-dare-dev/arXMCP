"""Gate a staged Bridgeland notebook before any cutover."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

from ingest.embedder import EMBED_INPUT_POLICY_VERSION, EMBEDDER_VERSION
from server.application_paths import ApplicationPaths
from tools.arxiv_fetch import find_main_tex

REQUIRED_FORMAL = {
    "1607.08199", "1711.08504", "2411.18554", "math/0210114",
    "textbook:ko95", "textbook:orl93", "1309.5035", "1802.01134",
    "1405.3857",
}
REQUIRED_LINKED_PROOF = REQUIRED_FORMAL - {"1405.3857"}
NO_FORMAL_EXPECTED = {"hep-th/0002037"}
FORMAL_KINDS = {
    "stmt", "theorem", "lemma", "proposition", "corollary",
    "definition", "remark", "example", "claim", "conjecture",
}


def validate(staging: Path) -> dict:
    import lancedb

    marker = json.loads((staging / "corpus-version.json").read_text())
    db = lancedb.connect(str(staging))
    table = db.open_table("chunks")
    index_names = {index.name for index in table.list_indices()}
    rows = table.to_arrow().select([
        "paper_id", "kind", "chunk_id", "truncated", "embedder_version",
        "embed_input_policy_version", "embedding_stmt", "embedding_proof",
        "part_index", "part_count", "source_start", "source_end",
        "body_text", "page_start", "page_end", "theorem_label",
        "printed_number", "parser_used",
    ]).to_pylist()
    errors: list[str] = []
    for index_name in {"embedding_stmt_idx", "embedding_proof_idx", "paper_id_idx"}:
        if index_name not in index_names:
            errors.append(f"missing staged index: {index_name}")
    papers = {row["paper_id"] for row in rows}
    if len(papers) != 358:
        errors.append(f"expected 358 papers, found {len(papers)}")
    if len(rows) != marker.get("chunk_count"):
        errors.append("marker chunk_count does not match staged rows")
    if len(papers) != marker.get("paper_count"):
        errors.append("marker paper_count does not match staged papers")
    if marker.get("embed_input_policy_version") != EMBED_INPUT_POLICY_VERSION:
        errors.append("marker embedding input policy differs from current policy")
    if marker.get("embedder_version") != EMBEDDER_VERSION:
        errors.append("marker embedder version differs from current model")
    formal = Counter(
        row["paper_id"] for row in rows if row["kind"] in FORMAL_KINDS
    )
    for paper_id in REQUIRED_FORMAL:
        if formal[paper_id] == 0:
            errors.append(f"no recovered formal chunk for {paper_id}")
        if not any(
            row["printed_number"] for row in rows
            if row["paper_id"] == paper_id and row["kind"] in FORMAL_KINDS
        ):
            errors.append(f"no printed result number for {paper_id}")
        labels = {
            row["theorem_label"] for row in rows
            if row["paper_id"] == paper_id and row["kind"] in FORMAL_KINDS
            and row["theorem_label"]
        }
        if paper_id in REQUIRED_LINKED_PROOF:
            proofs = [
                row for row in rows
                if row["paper_id"] == paper_id and row["kind"] == "proof"
            ]
            if not proofs:
                errors.append(f"no recovered proof chunk for {paper_id}")
            elif not any(row["theorem_label"] in labels for row in proofs):
                errors.append(f"no proof linked to a local result in {paper_id}")
    for paper_id in NO_FORMAL_EXPECTED:
        if paper_id not in papers:
            errors.append(f"statement-free paper missing: {paper_id}")
        if formal[paper_id]:
            errors.append(f"unexpected formal chunks in {paper_id}")
    tex_sources: dict[str, str] = {}
    for row in rows:
        chunk_id = row["chunk_id"]
        if row["truncated"] is not False:
            errors.append(f"shortened or unverified chunk: {chunk_id}")
        if row["embed_input_policy_version"] != EMBED_INPUT_POLICY_VERSION:
            errors.append(f"mixed embedding policy: {chunk_id}")
        if row["embedder_version"] != EMBEDDER_VERSION:
            errors.append(f"mixed model version: {chunk_id}")
        if row["part_index"] is None or row["part_count"] is None or not (
            1 <= row["part_index"] <= row["part_count"]
        ):
            errors.append(f"invalid part order: {chunk_id}")
        start, end = row["source_start"], row["source_end"]
        if row["part_count"] and row["part_count"] > 1 and start is None:
            errors.append(f"window source span missing: {chunk_id}")
        if start is not None and (end is None or end - start != len(row["body_text"])):
            errors.append(f"source span does not cover body: {chunk_id}")
        if row["parser_used"] == "tex" and start is not None and end is not None:
            paper_id = row["paper_id"]
            if paper_id not in tex_sources:
                raw = ApplicationPaths.resolve().corpus / "raw" / paper_id
                main = find_main_tex(raw, paper_id)
                if main is None:
                    errors.append(f"authentic TeX source missing: {paper_id}")
                    tex_sources[paper_id] = ""
                else:
                    tex_sources[paper_id] = main.read_text(encoding="utf-8", errors="replace")
            if tex_sources[paper_id][start:end] != row["body_text"]:
                errors.append(f"TeX source span mismatch: {chunk_id}")
        if row["paper_id"] in {"textbook:ko95", "textbook:orl93"} and (
            row["page_start"] is None or row["page_end"] is None
        ):
            errors.append(f"textbook page span missing: {chunk_id}")
        vec = row["embedding_proof"] if row["kind"] == "proof" else row["embedding_stmt"]
        if vec is None:
            errors.append(f"embedding missing: {chunk_id}")
        else:
            array = np.asarray(vec, dtype=np.float32)
            norm = float(np.linalg.norm(array))
            if not np.isfinite(array).all() or abs(norm - 1.0) > 1e-3:
                errors.append(f"embedding not a finite unit vector: {chunk_id}")
    return {
        "ok": not errors, "paper_count": len(papers), "chunk_count": len(rows),
        "formal_counts": {p: formal[p] for p in sorted(REQUIRED_FORMAL)},
        "error_count": len(errors), "errors": errors[:50],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("staging", type=Path)
    args = parser.parse_args()
    result = validate(args.staging)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

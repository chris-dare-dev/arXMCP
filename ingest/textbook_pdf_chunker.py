"""Page-aware, lossless extraction for text PDFs with printed result labels."""

from __future__ import annotations

import re
import subprocess

from ingest.chunk import ChunkRecord, _compute_textbook_chunk_id
from ingest.chunker import STMT_MAX_TOKENS, _validate_paper_id, _window_text_spans
from ingest.textbook_chunker import _resolve_notebook_dir
from ingest.tokenizer import tokenize_body

_LABEL = re.compile(
    r"^\s*(?:(?P<number>\d+(?:\.\d+)*\.)\s*"
    r"(?P<number_kind>Theorem|Lemma|Proposition|Corollary|Definition|Remark|Example)\b"
    r"|(?P<kind>Theorem|Lemma|Proposition|Corollary|Definition|Remark|Example)"
    r"\s+(?P<kind_number>\d+(?:\.\d+)*))\b",
    re.IGNORECASE,
)
_PROOF = re.compile(r"^\s*Proof\b[.:]?", re.IGNORECASE)


def chunk_textbook_pdf(slug: str, paper_id: str) -> list[ChunkRecord]:
    """Emit complete text plus isolated formal results, retaining PDF pages."""
    _validate_paper_id(paper_id)
    if not paper_id.startswith("textbook:"):
        raise ValueError("PDF textbook chunker requires a textbook: paper ID")
    notebook = _resolve_notebook_dir(slug)
    pdf = notebook / "pdfs" / f"{paper_id.replace(':', '_')}.pdf"
    if not pdf.is_file():
        raise FileNotFoundError(pdf)
    result = subprocess.run(
        ["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), "-"],
        check=True, capture_output=True, text=True, timeout=180,
    )
    records: list[ChunkRecord] = []
    seen: set[str] = set()
    last_statement: str | None = None
    for page_number, page in enumerate(result.stdout.split("\f"), 1):
        if not page.strip():
            continue
        starts: list[tuple[int, str, str | None]] = [(0, "section", None)]
        cursor = 0
        for line in page.splitlines(keepends=True):
            match = _LABEL.match(line)
            if match:
                kind = (match.group("number_kind") or match.group("kind")).lower()
                number = (match.group("number") or match.group("kind_number")).rstrip(".")
                starts.append((cursor, kind, number))
            elif _PROOF.match(line):
                starts.append((cursor, "proof", None))
            cursor += len(line)
        starts.append((len(page), "", None))
        for index in range(len(starts) - 1):
            start, kind, number = starts[index]
            end = starts[index + 1][0]
            body = page[start:end]
            if not body.strip():
                continue
            if kind not in {"section", "proof"}:
                last_statement = number
            linkage = (
                f"pdf:{paper_id}:{last_statement}"
                if kind != "section" and last_statement else None
            )
            windows = _window_text_spans(body, STMT_MAX_TOKENS)
            for part_index, (window, local_start, local_end) in enumerate(windows, 1):
                chunk_id = _compute_textbook_chunk_id(
                    slug, f"{paper_id}:page:{page_number}:offset:{start + local_start}", window
                )
                if chunk_id in seen:
                    raise ValueError(f"duplicate PDF chunk id: {chunk_id}")
                seen.add(chunk_id)
                records.append(ChunkRecord(
                    chunk_id=chunk_id,
                    paper_id=paper_id,
                    kind="stmt" if kind == "theorem" else kind,
                    section_path=[],
                    theorem_name=None,
                    theorem_label=linkage,
                    body_text=window,
                    body_tokens=tokenize_body(window),
                    chunker_version="tpdf1.0",
                    source_kind="textbook",
                    textbook_slug=slug,
                    parser_used="pdftotext",
                    page_start=page_number,
                    page_end=page_number,
                    printed_number=(
                        number if number is not None else
                        last_statement if kind == "proof" else None
                    ),
                    part_index=part_index,
                    part_count=len(windows),
                    source_start=start + local_start,
                    source_end=start + local_end,
                ))
    return records

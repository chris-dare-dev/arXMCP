"""Extract formal environments directly from authentic arXiv TeX sources."""

from __future__ import annotations

import re
from bisect import bisect_left

from ingest.chunk import CHUNKER_VERSION, ChunkRecord, _compute_chunk_id
from ingest.chunker import STMT_MAX_TOKENS, _window_text_spans
from ingest.tokenizer import tokenize_body
from server.application_paths import ApplicationPaths
from tools.arxiv_fetch import find_main_tex

_DECL = re.compile(
    r"\\newtheorem(?P<star>\*)?\{(?P<env>[^}]+)\}"
    r"(?:\[(?P<shared>[^]]+)\])?\{(?P<title>[^}]+)\}"
    r"(?:\[(?P<reset>[^]]+)\])?"
)
_BEGIN = re.compile(r"\\begin\{([^}]+)\}")
_LABEL = re.compile(r"\\label\{([^}]+)\}")
_SECTION = re.compile(r"\\(?:sub)*section\*?(?:\[[^]]*\])?\{([^}]+)\}")
_NUMBERED_SECTION = re.compile(r"\\section(?:\[[^]]*\])?\{")
_KIND = {
    "theorem": "stmt", "lemma": "lemma", "proposition": "proposition",
    "corollary": "corollary", "definition": "definition",
    "remark": "remark", "example": "example", "proof": "proof",
    "claim": "claim", "conjecture": "conjecture", "fact": "fact",
    "question": "question", "exercise": "exercise",
}


def chunk_tex_formals(paper_id: str) -> list[ChunkRecord]:
    """Extract complete labeled results and proofs, retaining TeX offsets."""
    raw = ApplicationPaths.resolve().corpus / "raw" / paper_id
    main = find_main_tex(raw, paper_id)
    if main is None:
        raise FileNotFoundError(f"authentic TeX source missing for {paper_id}")
    source = main.read_text(encoding="utf-8", errors="replace")
    mapping = dict(_KIND)
    counters: dict[str, tuple[str, str | None] | None] = {}
    for declaration in _DECL.finditer(source):
        env = declaration.group("env")
        mapping[env] = _KIND.get(declaration.group("title").strip().lower(), "stmt")
        shared = declaration.group("shared")
        counters[env] = (
            None if declaration.group("star") else
            counters.get(shared) if shared else (env, declaration.group("reset"))
        )
    section_offsets = [match.start() for match in _NUMBERED_SECTION.finditer(source)]
    counter_values: dict[tuple[str, int], int] = {}
    records: list[ChunkRecord] = []
    seen: set[str] = set()
    formal_spans: list[tuple[int, int]] = []
    last_label: str | None = None
    last_number: str | None = None
    for begin in _BEGIN.finditer(source):
        env = begin.group(1)
        kind = mapping.get(env)
        if kind is None:
            continue
        terminator = re.compile(rf"\\(begin|end)\{{{re.escape(env)}\}}")
        depth = 1
        end_match = None
        for match in terminator.finditer(source, begin.end()):
            depth += 1 if match.group(1) == "begin" else -1
            if depth == 0:
                end_match = match
                break
        if end_match is None:
            raise ValueError(f"unclosed {env} environment at offset {begin.start()}")
        formal_spans.append((begin.start(), end_match.end()))
        body = source[begin.end():end_match.start()]
        if not body.strip():
            continue
        label_match = _LABEL.search(body)
        if kind != "proof":
            last_label = label_match.group(1) if label_match else f"tex:{begin.start()}"
            spec = counters.get(env)
            if spec is None:
                last_number = None
            else:
                counter_name, reset = spec
                section_number = bisect_left(section_offsets, begin.start())
                key = (counter_name, section_number if reset == "section" else 0)
                counter_values[key] = counter_values.get(key, 0) + 1
                last_number = (
                    f"{section_number}.{counter_values[key]}"
                    if reset == "section" else str(counter_values[key])
                )
        theorem_label = last_label
        preceding_section = list(_SECTION.finditer(source, 0, begin.start()))
        section_path = [preceding_section[-1].group(1)] if preceding_section else []
        windows = _window_text_spans(body, STMT_MAX_TOKENS)
        for part_index, (window, local_start, local_end) in enumerate(windows, 1):
            # Repeated short proofs are distinct source events. Include the
            # TeX offset in the identity so dedup cannot erase either one.
            # This is a position value, not the preamble, so ADR rule 1
            # leaves these ids unchanged (chunk-module-m2).
            chunk_id = _compute_chunk_id(
                paper_id, window, position=f"tex-offset:{begin.end() + local_start}"
            )
            if chunk_id in seen:
                raise ValueError(f"duplicate TeX chunk id: {chunk_id}")
            seen.add(chunk_id)
            records.append(ChunkRecord(
                chunk_id=chunk_id, paper_id=paper_id, kind=kind,
                section_path=section_path, theorem_name=None,
                theorem_label=theorem_label, body_text=window,
                printed_number=last_number,
                body_tokens=tokenize_body(window),
                chunker_version=CHUNKER_VERSION, parser_used="tex",
                part_index=part_index, part_count=len(windows),
                source_start=begin.end() + local_start,
                source_end=begin.end() + local_end,
            ))
    document_begin = source.find(r"\begin{document}")
    document_end = source.rfind(r"\end{document}")
    if document_begin < 0 or document_end <= document_begin:
        raise ValueError(f"document body missing in {main}")
    cursor = document_begin + len(r"\begin{document}")
    for span_start, span_end in sorted(formal_spans) + [(document_end, document_end)]:
        if span_start > cursor:
            prose = source[cursor:span_start]
            if prose.strip():
                sections = list(_SECTION.finditer(source, 0, cursor))
                section_path = [sections[-1].group(1)] if sections else []
                windows = _window_text_spans(prose, STMT_MAX_TOKENS)
                for part_index, (window, local_start, local_end) in enumerate(windows, 1):
                    source_start = cursor + local_start
                    chunk_id = _compute_chunk_id(
                        paper_id, window, position=f"tex-offset:{source_start}"
                    )
                    if chunk_id in seen:
                        raise ValueError(f"duplicate TeX chunk id: {chunk_id}")
                    seen.add(chunk_id)
                    records.append(ChunkRecord(
                        chunk_id=chunk_id, paper_id=paper_id, kind="section",
                        section_path=section_path, theorem_name=None,
                        theorem_label=None, body_text=window,
                        body_tokens=tokenize_body(window),
                        chunker_version=CHUNKER_VERSION, parser_used="tex",
                        part_index=part_index, part_count=len(windows),
                        source_start=source_start,
                        source_end=cursor + local_end,
                    ))
        cursor = max(cursor, span_end)
    return records

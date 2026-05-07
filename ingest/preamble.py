"""Per-paper preamble extractor (E02_S02).

Reads the root .tex file under ``var/arxmcp/corpus/raw/<paper_id>/`` and
extracts every macro-definition directive into a deterministic
``preamble.json`` under ``var/arxmcp/corpus/preamble/<paper_id>/``. The
chunker (E02_S01) reads this back to populate ``ChunkRecord.preamble_ref``
with the preamble's content hash so the embedder (E03_S01) can reproduce
``preamble_text + "\\n\\n" + body_text`` exactly across runs.

**Anthropic contextual retrieval is rejected — preamble is deterministic;
see ``04-parsing-and-chunking.md`` § Preamble extraction.** The notes
explicitly call out determinism as load-bearing for BP1 byte-identical
caching across multi-agent fan-out (``08-security-observability-ops.md``);
LLM-generated chunk context would produce different bytes per run, would
incur per-chunk API cost, and would introduce a circular Anthropic-API
dependency in the ingestion path. Macro-definition extraction gives the
exact mathematical-notation context downstream agents need at zero
runtime cost.

Public API: ``extract_preamble(paper_id: str) -> PreambleDoc``. Idempotent:
re-running on a paper whose .tex source is unchanged short-circuits to the
cached ``PreambleDoc`` (verified via a SHA-256 of the source bytes).

In-scope macro forms:
    \\newcommand{\\name}[n][default]{body}
    \\renewcommand{\\name}[n][default]{body}
    \\providecommand{\\name}[n][default]{body}
    \\DeclareMathOperator{\\name}{text}     \\DeclareMathOperator*{...}
    \\def\\name{body}     \\edef\\name{body}     \\gdef\\name{body}     \\xdef\\name{body}
    \\let\\name=\\other   \\let\\name\\other

Out of scope (deferred to Tier 2 or other milestones):
    macro expansion / body evaluation, \\DeclareRobustCommand,
    \\newenvironment / \\renewenvironment, \\input{} / \\include{}
    chasing, .sty / .cls files.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path

# Reuse the chunker's paper_id validator + log-field sanitiser to avoid
# duplicating the regex and to inherit its security guarantees (Threat 1).
from ingest.chunker import (
    _sanitize_log_field,
    _validate_paper_id,
)
from ingest.chunker_types import ChunkRecord  # noqa: F401  (re-export indirect)
from ingest.preamble_types import PreambleDoc

# Reuse the existing root-tex heuristic from the fetcher tooling rather than
# re-implementing it. The function lives in tools/arxiv_fetch.py and the
# project's package layout puts both `tools/` and `ingest/` on sys.path.
from tools.arxiv_fetch import find_main_tex

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" / "raw"
PREAMBLE_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" / "preamble"
PREAMBLE_LOG_PATH = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "parser-failures" / "preamble.log"
)


# ---------------------------------------------------------------------------
# Per-paper exception envelope (mirror of chunker.py's pattern)
# ---------------------------------------------------------------------------

# Catch only resilience-pattern exceptions; programmer bugs propagate.
PER_PAPER_FAILURE_EXCEPTIONS = (OSError, ValueError, FileNotFoundError)


# ---------------------------------------------------------------------------
# Macro directive regexes
# ---------------------------------------------------------------------------

# Directives whose body is brace-balanced (\newcommand-style).
# Matches the head: directive name + the command name being defined +
# optional [n] and [default] arguments. The body { ... } is consumed by
# the brace-balanced scanner below.
_BRACED_HEAD_RE = re.compile(
    r"\\(?P<directive>newcommand|renewcommand|providecommand)"
    r"\s*\*?\s*"               # optional `*` for starred form
    r"(?:"
    r"\{\\(?P<name1>[A-Za-z@]+)\}"   # \newcommand{\foo}
    r"|\\(?P<name2>[A-Za-z@]+)"      # \newcommand\foo
    r")"
    r"(?:\s*\[(?P<nargs>\d+)\])?"
    r"(?:\s*\[(?P<default>[^\]]*)\])?"
    r"\s*\{"                         # opening brace of body
)

# \DeclareMathOperator{\name}{body} (and starred form). Body is brace-balanced
# but always single-arg, so reuse the brace-balanced scanner.
_DECL_MATH_OP_HEAD_RE = re.compile(
    r"\\DeclareMathOperator\s*\*?\s*"
    r"\{\\(?P<name>[A-Za-z@]+)\}\s*\{"
)

# \def, \edef, \gdef, \xdef — body is brace-balanced.
_DEF_HEAD_RE = re.compile(
    r"\\(?P<directive>def|edef|gdef|xdef)"
    r"\s*\\(?P<name>[A-Za-z@]+)"
    r"(?P<param_text>[^{]*)"   # parameter text up to the body brace
    r"\s*\{"
)

# \let — single-line: \let\name=\other or \let\name\other.
_LET_RE = re.compile(
    r"\\let\s*\\(?P<name>[A-Za-z@]+)\s*=?\s*"
    r"(?:\\(?P<target>[A-Za-z@]+)|(?P<charlit>[^\s\\]))"
)


# ---------------------------------------------------------------------------
# Comment stripping
# ---------------------------------------------------------------------------


def _strip_tex_comments(text: str) -> str:
    """Strip TeX comments while honoring the ``\\%`` escape.

    Rule: an unescaped ``%`` starts a comment that runs to end-of-line. A
    ``%`` is escaped iff the count of consecutive preceding backslashes
    is odd. ``\\%`` is therefore a literal percent (one backslash, odd);
    ``\\\\%`` is a comment (two backslashes, even).

    The naive regex ``re.sub(r'(?<!\\\\)%.*$', ...)`` misclassifies
    ``\\\\%`` (which IS a comment under TeX rules), so we scan
    character-by-character.
    """
    out_chars: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "%":
            # Count consecutive preceding backslashes.
            bs = 0
            j = i - 1
            while j >= 0 and text[j] == "\\":
                bs += 1
                j -= 1
            if bs % 2 == 0:
                # Unescaped — strip to end-of-line (keep the newline so line
                # boundaries survive for the next stage).
                while i < n and text[i] != "\n":
                    i += 1
                continue
            # Escaped — keep the percent.
        out_chars.append(ch)
        i += 1
    return "".join(out_chars)


# ---------------------------------------------------------------------------
# Brace-balanced body scanner
# ---------------------------------------------------------------------------


def _scan_balanced_body(text: str, start: int) -> int | None:
    """Return the index AFTER the matching closing brace.

    ``start`` is the index of the character immediately after the opening
    ``{`` (i.e. inside the body). Returns the index of the character after
    the matching ``}``, or ``None`` if braces never balance (truncated
    source).
    """
    depth = 1
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            # Skip the next character — handles \{, \}, \\, etc.
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


# ---------------------------------------------------------------------------
# Whitespace normalisation
# ---------------------------------------------------------------------------


def _normalise(macro: str) -> str:
    return re.sub(r"\s+", " ", macro).strip()


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------


def _extract_macros(tex_source: str) -> list[str]:
    """Return the deduplicated, sorted list of normalised macro definitions."""
    cleaned = _strip_tex_comments(tex_source)
    raw_macros: list[str] = []

    # Helper: walk the cleaned text once per regex family. Each scan is
    # independent — the directives don't nest meaningfully at the
    # extraction level (a macro body is captured verbatim, not parsed).

    # \newcommand / \renewcommand / \providecommand
    for match in _BRACED_HEAD_RE.finditer(cleaned):
        body_end = _scan_balanced_body(cleaned, match.end())
        if body_end is None:
            continue
        raw_macros.append(cleaned[match.start():body_end])

    # \DeclareMathOperator
    for match in _DECL_MATH_OP_HEAD_RE.finditer(cleaned):
        body_end = _scan_balanced_body(cleaned, match.end())
        if body_end is None:
            continue
        raw_macros.append(cleaned[match.start():body_end])

    # \def / \edef / \gdef / \xdef
    for match in _DEF_HEAD_RE.finditer(cleaned):
        body_end = _scan_balanced_body(cleaned, match.end())
        if body_end is None:
            continue
        raw_macros.append(cleaned[match.start():body_end])

    # \let — single-line, no body to balance
    for match in _LET_RE.finditer(cleaned):
        raw_macros.append(match.group(0))

    # Normalise, dedupe (preserving first-seen for tie-breaking diagnostics),
    # then sort for canonical determinism.
    normalised = [_normalise(m) for m in raw_macros if _normalise(m)]
    deduped = list(dict.fromkeys(normalised))
    return sorted(deduped)


# ---------------------------------------------------------------------------
# Idempotent atomic write
# ---------------------------------------------------------------------------


def _write_preamble_json(out_path: Path, doc: PreambleDoc) -> None:
    """Atomically write ``preamble.json`` via temp-then-rename.

    Avoids leaving readers seeing a half-written file during a re-run.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    payload = json.dumps(doc.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, out_path)


def _read_existing_preamble(out_path: Path) -> PreambleDoc | None:
    if not out_path.exists():
        return None
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
        return PreambleDoc.from_dict(data)
    except (json.JSONDecodeError, KeyError, OSError):
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_preamble(paper_id: str) -> PreambleDoc:
    """Extract macro definitions from a paper's root .tex.

    Validates ``paper_id`` before any path concat. Returns a
    :class:`PreambleDoc` and writes ``preamble.json`` under
    ``var/arxmcp/corpus/preamble/<paper_id>/``. On a re-run with
    unchanged source, the cached doc is returned without rewriting.

    Raises :class:`InvalidPaperIDError` for malformed paper_ids.
    Per-paper resilience-pattern exceptions
    (:data:`PER_PAPER_FAILURE_EXCEPTIONS`) are logged to ``preamble.log``
    and re-raised — the public entry point does not swallow them; that
    decision belongs to the batch driver (mirrors the contract that
    ``tools/fetch_seed.py`` uses around ``tools/fetch_one_paper.py``).
    """
    _validate_paper_id(paper_id)

    start = time.monotonic()
    try:
        raw_paper_dir = RAW_DIR / paper_id
        if not raw_paper_dir.exists():
            raise FileNotFoundError(
                f"raw .tex source not found at {raw_paper_dir}; "
                "run tools/fetch_seed.py first"
            )
        main_tex = find_main_tex(raw_paper_dir, paper_id)
        if main_tex is None:
            raise FileNotFoundError(
                f"no .tex file found under {raw_paper_dir} for paper {paper_id}"
            )
        return _extract_preamble_impl(paper_id, main_tex)
    except PER_PAPER_FAILURE_EXCEPTIONS as exc:
        elapsed = time.monotonic() - start
        _log_preamble_failure(paper_id, elapsed, str(exc))
        logger.error(
            "[%s] extract_preamble failed: %s", paper_id, exc, exc_info=True
        )
        raise


def _extract_preamble_impl(paper_id: str, main_tex: Path) -> PreambleDoc:
    source_bytes = main_tex.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()

    out_dir = PREAMBLE_DIR / paper_id
    out_path = out_dir / "preamble.json"
    cached = _read_existing_preamble(out_path)
    if cached is not None and cached.source_hash == source_hash:
        # Idempotent short-circuit: source unchanged.
        return cached

    # (Re)extract.
    tex_source = source_bytes.decode("utf-8", errors="replace")
    macros = _extract_macros(tex_source)
    preamble_text = "\n".join(macros)
    preamble_hash = hashlib.sha256(preamble_text.encode("utf-8")).hexdigest()[:16]

    doc = PreambleDoc(
        paper_id=paper_id,
        source_hash=source_hash,
        macros=macros,
        preamble_text=preamble_text,
        preamble_hash=preamble_hash,
    )
    _write_preamble_json(out_path, doc)
    return doc


def load_preamble(paper_id: str) -> PreambleDoc | None:
    """Load a previously-extracted PreambleDoc, or ``None`` if absent.

    Caller-friendly accessor for the chunker and embedder. Does NOT trigger
    extraction; callers that want extract-or-cache semantics should call
    ``extract_preamble`` directly.
    """
    _validate_paper_id(paper_id)
    out_path = PREAMBLE_DIR / paper_id / "preamble.json"
    return _read_existing_preamble(out_path)


# ---------------------------------------------------------------------------
# Failure logging (mirrors chunker.py's _log_chunk_failure)
# ---------------------------------------------------------------------------


def _log_preamble_failure(paper_id: str, elapsed_s: float, message: str) -> None:
    PREAMBLE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = (
        f"{_sanitize_log_field(paper_id)}\tfail\t{elapsed_s:.1f}\t"
        f"{_sanitize_log_field(message)}\n"
    )
    try:
        with PREAMBLE_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(row)
    except OSError:
        logger.error("could not write to preamble.log: %s", PREAMBLE_LOG_PATH)

"""Shared helpers for the seed-corpus fetch scripts (E01_S02 + E01_S03).

The arXiv `/e-print/` contract, the LaTeXML invocation shape, and the
parse-success detector all live here so `fetch_one_paper.py` and
`fetch_seed.py` use one implementation. Production ingestion (E11) will
re-implement these in `ingest/` with subprocess UID isolation per
.claude/notes/08-security-observability-ops.md Threat 3 — for now this is
unsandboxed dev tooling running on trusted arXiv source.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import signal
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ARXIV_EPRINT_URL = "https://export.arxiv.org/e-print/{paper_id}"
ARXIV_USER_AGENT_TEMPLATE = "arXMCP/0.1 (mailto:{email})"

POLITENESS_SLEEP_SECONDS = 3.0
DEFAULT_503_BACKOFF_SECONDS = 30.0
MAX_503_BACKOFF_SECONDS = 300.0
LATEXML_TIMEOUT_SECONDS = 300

PAPER_ID_RE = re.compile(r"^[0-9]{4}\.[0-9]{4,5}$")
MIN_PARSED_HTML_BYTES = 1024

# Threat 7 in 08-security-observability-ops.md: refuse responses larger
# than this. A real arXiv source tarball >100 MB is suspicious; we use
# 200 MB as the operational cap.
MAX_RESPONSE_BYTES = 200 * 1024 * 1024


@dataclass(frozen=True)
class FetchResult:
    paper_id: str
    raw_dir: Path
    main_tex: Path | None
    http_status: int
    bytes_downloaded: int
    archive_kind: str  # "tar" (multi-file submission) | "tex" (single-file)


@dataclass(frozen=True)
class ParseResult:
    paper_id: str
    success: bool
    exit_code: int
    output_path: Path
    file_size: int
    mathml_node_count: int
    message: str


def build_user_agent(contact_email: str | None = None) -> str:
    """Format the User-Agent per arXiv TOS §3 (politeness contract).

    Reads ARXMCP_CONTACT_EMAIL from the environment if not given. Raises
    if neither source supplies a value — we never send anonymous traffic
    to arXiv.
    """
    email = contact_email or os.environ.get("ARXMCP_CONTACT_EMAIL")
    if not email:
        raise RuntimeError(
            "ARXMCP_CONTACT_EMAIL is required (arXiv TOS §3 — politeness contract). "
            "Export it in your shell before running any tool that hits arxiv.org."
        )
    return ARXIV_USER_AGENT_TEMPLATE.format(email=email)


def validate_paper_id(paper_id: str) -> None:
    """Reject anything that is not a new-style YYMM.NNNNN[N] arXiv ID.

    The seed corpus is post-2010 math.AG — old-style `subject/NNNNNNN`
    IDs do not appear there and pre-2007 OCR-only papers are an explicit
    non-goal per .claude/notes/09-feature-priorities.md.
    """
    if not PAPER_ID_RE.match(paper_id):
        raise ValueError(
            f"paper_id {paper_id!r} does not match new-style arXiv ID "
            f"(YYMM.NNNNN or YYMM.NNNNNN). Old-style and withdrawn IDs "
            f"are out of scope for the Tier-0 seed corpus."
        )


def is_tar_archive(content_type: str | None) -> bool:
    """Decide whether a Content-Type string declares a tar archive.

    Kept as a helper for callers that want a Content-Type hint, but the
    fetch path no longer dispatches on it: live responses sometimes
    arrive with a non-tar Content-Type and a tar body. See
    `_extract_eprint_response` for the bytes-based sniff that is now
    authoritative.
    """
    if not content_type:
        return False
    ct = content_type.split(";", 1)[0].strip().lower()
    return "tar" in ct


def parse_retry_after(value: str | None, default: float) -> float:
    """Honor a Retry-After header (seconds) if it parses cleanly."""
    if not value:
        return default
    try:
        seconds = float(value.strip())
    except ValueError:
        return default
    return max(seconds, default)


def detect_parse_success(output_path: Path, exit_code: int) -> ParseResult:
    """Apply the four-part success rule from the research synthesis (D4).

    success = exit_code == 0
              AND output_path exists
              AND file_size > MIN_PARSED_HTML_BYTES (1 KB)
              AND html contains "<math"   # MathML actually emitted

    LaTeXML can emit valid HTML with plain text where equations should
    be — exit code alone is insufficient. The `<math` check is the
    silent-math-loss guard.
    """
    if not output_path.exists():
        return ParseResult(
            paper_id=output_path.parent.name,
            success=False,
            exit_code=exit_code,
            output_path=output_path,
            file_size=0,
            mathml_node_count=0,
            message="output file missing",
        )

    file_size = output_path.stat().st_size
    text = output_path.read_text(encoding="utf-8", errors="replace")
    mathml_count = text.count("<math")

    success = (
        exit_code == 0
        and file_size > MIN_PARSED_HTML_BYTES
        and mathml_count > 0
    )

    if exit_code != 0:
        msg = f"latexmlc exit_code={exit_code}"
    elif file_size <= MIN_PARSED_HTML_BYTES:
        msg = f"output too small ({file_size} bytes)"
    elif mathml_count == 0:
        msg = "no <math> nodes — silent math loss"
    else:
        msg = f"ok ({mathml_count} math nodes, {file_size} bytes)"

    return ParseResult(
        paper_id=output_path.parent.name,
        success=success,
        exit_code=exit_code,
        output_path=output_path,
        file_size=file_size,
        mathml_node_count=mathml_count,
        message=msg,
    )


def find_main_tex(raw_dir: Path, paper_id: str) -> Path | None:
    r"""Pick the main .tex file from an extracted /e-print/ tarball.

    Heuristic: `<paper_id>.tex` if present, else the unique `.tex` file,
    else the first .tex alphabetically. arXiv submissions occasionally
    bundle multiple .tex (one main, several `\input{}`-ed); the main is
    usually the one containing `\documentclass`.
    """
    candidates = sorted(raw_dir.rglob("*.tex"))
    if not candidates:
        return None

    by_paper_id = raw_dir / f"{paper_id}.tex"
    if by_paper_id in candidates:
        return by_paper_id

    if len(candidates) == 1:
        return candidates[0]

    for tex in candidates:
        try:
            head = tex.read_text(encoding="utf-8", errors="replace")[:4096]
        except OSError:
            continue
        if "\\documentclass" in head:
            return tex

    return candidates[0]


def fetch_eprint(
    paper_id: str,
    raw_dir: Path,
    contact_email: str | None = None,
    timeout: float = 60.0,
) -> FetchResult:
    """Download and extract `https://export.arxiv.org/e-print/<paper_id>`.

    Honors the User-Agent + Retry-After contract. Raises urllib HTTPError
    for non-2xx responses (callers handle 503 backoff). Caller is
    responsible for the politeness sleep BEFORE invoking this — the
    function does not enforce inter-call spacing.
    """
    validate_paper_id(paper_id)
    raw_dir = raw_dir / paper_id
    raw_dir.mkdir(parents=True, exist_ok=True)

    url = ARXIV_EPRINT_URL.format(paper_id=paper_id)
    request = urllib.request.Request(  # noqa: S310 — fixed export.arxiv.org host
        url, headers={"User-Agent": build_user_agent(contact_email)}
    )

    with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
        content_length = resp.headers.get("Content-Length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                declared = -1
            if declared > MAX_RESPONSE_BYTES:
                raise RuntimeError(
                    f"response too large for {paper_id}: "
                    f"Content-Length {declared} > cap {MAX_RESPONSE_BYTES}"
                )
        body = resp.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise RuntimeError(
                f"response too large for {paper_id}: "
                f">{MAX_RESPONSE_BYTES} bytes (cap exceeded mid-read)"
            )
        http_status = resp.status

    bytes_downloaded = len(body)
    archive_kind = _extract_eprint_response(body, raw_dir, paper_id)

    return FetchResult(
        paper_id=paper_id,
        raw_dir=raw_dir,
        main_tex=find_main_tex(raw_dir, paper_id),
        http_status=http_status,
        bytes_downloaded=bytes_downloaded,
        archive_kind=archive_kind,
    )


def _extract_eprint_response(body: bytes, raw_dir: Path, paper_id: str) -> str:
    """Decompress an /e-print/ response and dispatch to tar or single-tex.

    arXiv responses are gzip-encoded. The inner content is either a tar
    archive (multi-file submission) or a bare .tex file (single-file
    submission). Content-Type does NOT reliably distinguish them — some
    multi-file submissions arrive with a non-tar Content-Type but the
    gzip-decompressed body IS a tar (caught during E01_S01-S03 Phase 4
    smoke test on 2605.03890). Sniff the decompressed bytes by trying
    `tarfile.open` first and falling back to bare-tex on TarError.
    """
    import gzip
    import io

    try:
        decompressed = gzip.decompress(body)
    except gzip.BadGzipFile:
        # Already raw bytes — rare path, but tolerate it.
        decompressed = body

    try:
        with tarfile.open(fileobj=io.BytesIO(decompressed), mode="r:") as tar:
            _safe_extract(tar, raw_dir)
        return "tar"
    except tarfile.TarError:
        target_tex = raw_dir / f"{paper_id}.tex"
        target_tex.write_bytes(decompressed)
        return "tex"


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """Reject path-traversal members before extraction.

    arXiv tarballs are trusted but the safety check is cheap and protects
    against a future supply-chain swap (cf. Threat 6 in
    .claude/notes/08-security-observability-ops.md).
    """
    dest_resolved = dest.resolve()
    for member in tar.getmembers():
        member_path = (dest / member.name).resolve()
        try:
            member_path.relative_to(dest_resolved)
        except ValueError as e:
            raise RuntimeError(
                f"refusing to extract path outside dest: {member.name}"
            ) from e
    tar.extractall(dest, filter="data")


def parse_with_latexml(
    main_tex: Path,
    parsed_dir: Path,
    paper_id: str,
    timeout: float = LATEXML_TIMEOUT_SECONDS,
) -> ParseResult:
    """Run `latexmlc` to emit HTML5+MathML and apply the success rule.

    LaTeXML is invoked with cwd set to the source directory so `\\input{}`
    relative paths resolve. No `--javascript=mathjax` (we do not want the
    output to depend on a CDN; the chunker reads the static HTML).

    **Process-group kill discipline (E13_S03 Threat 3 Phase 1).**
    The child `latexmlc` is launched in its own process group via
    ``start_new_session=True`` so a hostile `.tex` source that causes
    LaTeXML to fork Perl helpers cannot leave grandchildren behind
    when the timeout fires. On ``TimeoutExpired`` the entire process
    group receives SIGKILL via ``os.killpg`` so all descendants die
    atomically. ``subprocess.run(timeout=...)`` alone only kills the
    direct child — grandchildren survive as orphans and continue
    consuming resources. The full sandbox (sandbox-exec on macOS,
    seccomp+landlock on Linux, ``--read-only`` + ``no-new-privileges``
    in Docker) is Phase 2 of the Threat-3 mitigation and ships in a
    future milestone; see ``.claude/docs/security-threat-3-audit.md``.
    """
    if shutil.which("latexmlc") is None:
        raise RuntimeError(
            "latexmlc not on PATH. Install LaTeXML 0.8.x — "
            "`brew install latexml` (macOS) or `apt install latexml` (Debian/Ubuntu)."
        )

    out_dir = parsed_dir / paper_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_html = out_dir / "index.html"

    cmd = [
        "latexmlc",
        str(main_tex.name),
        f"--dest={out_html}",
        "--format=html5",
    ]
    # E13_S03: Popen with start_new_session=True puts latexmlc in its
    # own process group so we can SIGKILL the entire group on timeout.
    # On POSIX (macOS + Linux), start_new_session=True is equivalent to
    # ``os.setsid()`` after fork — the child becomes its own session/
    # process-group leader and any descendants share the new pgid.
    proc = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
        cmd,
        cwd=main_tex.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Kill the entire process group so any Perl helpers latexmlc
        # forked die with it. ProcessLookupError is benign — the
        # group may already be gone if the child exited between
        # ``communicate`` raising and ``killpg`` firing.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        # Drain the pipes so the child doesn't block on a full
        # buffer during teardown. If the group survived SIGKILL
        # (catastrophic — should not happen in practice) we
        # re-raise the original TimeoutExpired so callers see the
        # containment failure as a parse failure.
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.communicate(timeout=5)
        raise

    return detect_parse_success(out_html, proc.returncode)


def politeness_sleep(start_time: float, min_interval: float = POLITENESS_SLEEP_SECONDS) -> None:
    """Sleep so that the next request is at least `min_interval` after the previous one."""
    elapsed = time.monotonic() - start_time
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)

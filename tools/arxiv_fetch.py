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
import logging
import os
import re
import shutil
import signal
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

ARXIV_EPRINT_URL = "https://export.arxiv.org/e-print/{paper_id}"
ARXIV_USER_AGENT_TEMPLATE = "arXMCP/0.1 (mailto:{email})"

POLITENESS_SLEEP_SECONDS = 3.0
DEFAULT_503_BACKOFF_SECONDS = 30.0
MAX_503_BACKOFF_SECONDS = 300.0
LATEXML_TIMEOUT_SECONDS = 300

#: E13_S03b — repo-root-relative path to the macOS sandbox-exec
#: profile. Anchored to this file's location so the path resolves
#: regardless of the caller's CWD. The profile was authored and
#: hardened in E13_S03 (credential-directory denies + Perl/CPAN
#: allowlist + write-only on the per-paper OUTPUT_DIR).
SANDBOX_PROFILE_PATH = (
    Path(__file__).resolve().parent.parent
    / "infra" / "latexml" / "sandbox.sb"
)

#: E13_S03b — E13_S03b's initial draft included a
#: ``--timeout=300`` latexmlc CLI flag for defense-in-depth. The
#: adversary critique (F3) flagged that we have no live-integration
#: test proving the flag is accepted by the locally-installed
#: LaTeXML version — an older binary may reject the unknown option
#: and silently break the production path. The Python-side
#: ``subprocess`` ``timeout=`` argument + ``killpg`` discipline
#: already covers the timeout vector, so the additional flag was
#: removed in the F3 rectification. If a future milestone adds a
#: live-integration test (``latexmlc --timeout=300 --help``), the
#: flag can be re-introduced safely.

PAPER_ID_RE = re.compile(r"^[0-9]{4}\.[0-9]{4,5}$")
MIN_PARSED_HTML_BYTES = 1024

# Threat 7 in 08-security-observability-ops.md states "a single paper
# > 100 MB source is suspicious." E13_S07 aligns the cap with the
# threat-model budget exactly. The prior 200 MB value was a safety-net
# default; 100 MB is the Threat-7 cap and matches the per-fetch caps
# now applied uniformly on ingest/ar5iv_fetch.py and ingest/oai_delta.py.
MAX_RESPONSE_BYTES = 100 * 1024 * 1024


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

    Priority chain (onboarding-uplift-m2 D1 + D4):

    1. **Explicit ``contact_email``** — the caller already has it.
    2. **SQLite ``operator_settings.contact_email``** — persisted
       via ``make init NOTEBOOK=… EMAIL=…``. Sticky across shell
       restarts; the m2 canonical mechanism.
    3. **``ARXMCP_CONTACT_EMAIL`` env var** — the historical pre-m2
       contract.
    4. **Raise** :class:`RuntimeError` — no source supplied a value.
       We never send anonymous traffic to arXiv.
    """
    if contact_email:
        email: str | None = contact_email
    else:
        # m2: consult SQLite operator_settings before falling back to
        # the env var. ``get_contact_email`` returns ``None`` if the
        # file doesn't exist yet — that's the cold-bootstrap case
        # where only the env var has been set.
        from server.operator_settings import get_contact_email  # noqa: PLC0415

        email = get_contact_email() or os.environ.get("ARXMCP_CONTACT_EMAIL")
    if not email:
        raise RuntimeError(
            "no contact email available (arXiv TOS §3 — politeness contract). "
            "Run `make init NOTEBOOK=<slug> EMAIL=<addr>` to persist it, OR "
            "`export ARXMCP_CONTACT_EMAIL=<addr>` in this shell."
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
    ssl_context: ssl.SSLContext | None = None,
) -> FetchResult:
    """Download and extract `https://export.arxiv.org/e-print/<paper_id>`.

    Honors the User-Agent + Retry-After contract. Raises urllib HTTPError
    for non-2xx responses (callers handle 503 backoff). Caller is
    responsible for the politeness sleep BEFORE invoking this — the
    function does not enforce inter-call spacing.

    The ``ssl_context`` parameter is the E13_S07c CA-pinning injection
    point (Threat 7 mitigation #2). Pass ``None`` (the default) to
    use the system trust store; pass an :class:`ssl.SSLContext` built
    via :func:`server.ssl_pin.build_arxiv_ssl_context` to pin the
    bundle. ``export.arxiv.org`` chains to the same Let's Encrypt
    root (ISRG Root X1) as ``arxiv.org`` and ``ar5iv.labs.arxiv.org``,
    so the same vendored bundle covers all three.
    """
    validate_paper_id(paper_id)
    raw_dir = raw_dir / paper_id
    raw_dir.mkdir(parents=True, exist_ok=True)

    url = ARXIV_EPRINT_URL.format(paper_id=paper_id)
    request = urllib.request.Request(  # noqa: S310 — fixed export.arxiv.org host
        url, headers={"User-Agent": build_user_agent(contact_email)}
    )

    with urllib.request.urlopen(  # noqa: S310
        request, timeout=timeout, context=ssl_context
    ) as resp:
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


# ---------------------------------------------------------------------------
# E13_S03b — LaTeXML production sandbox wiring (Threat 3 Phase 2)
# ---------------------------------------------------------------------------


def _detect_sandbox_layer() -> str | None:
    """Return the name of the active sandbox layer or ``None``.

    Platform-detect at runtime; cached by ``_SANDBOX_LAYER`` below.

    - macOS (``darwin``): ``sandbox-exec`` IFF
      ``/usr/bin/sandbox-exec`` exists AND the SBPL profile at
      ``infra/latexml/sandbox.sb`` is readable.
    - Linux (``linux*``): ``bwrap`` (bubblewrap) IFF
      ``shutil.which("bwrap")`` finds the binary.
    - Anything else (Windows, BSDs, etc.): ``None`` — degraded.

    The function is pure; no side effects. The startup log line
    (visible at module import) is emitted ONCE from the
    ``_SANDBOX_LAYER`` initializer below.
    """
    if sys.platform == "darwin":
        if (
            Path("/usr/bin/sandbox-exec").is_file()
            and SANDBOX_PROFILE_PATH.is_file()
        ):
            return "sandbox-exec"
    elif sys.platform.startswith("linux"):
        if shutil.which("bwrap") is not None:
            return "bwrap"
    return None


#: Resolved at module import time. The startup log below reflects
#: the cached value so an operator sees the platform's posture in
#: the operational log (NOT per-paper noise during bulk ingest).
_SANDBOX_LAYER: str | None = _detect_sandbox_layer()

if _SANDBOX_LAYER is None:
    logger.info(
        "LaTeXML sandbox layer: NONE — running subprocess+timeout "
        "isolation only (Threat 3 partially mitigated; "
        "platform=%s). See .claude/docs/security-threat-3-audit.md.",
        sys.platform,
    )
else:
    logger.info(
        "LaTeXML sandbox layer: %s (Threat 3 ingest-path mitigation "
        "active).",
        _SANDBOX_LAYER,
    )


def _build_sandbox_cmd(
    cmd: list[str],
    source_dir: Path,
    output_dir: Path,
    tmpdir_subdir: Path,
) -> list[str]:
    """Prepend the platform-appropriate sandbox wrapper to ``cmd``.

    Returns ``cmd`` unchanged when no sandbox layer is available
    (the degraded path; the caller logs at DEBUG).

    - **sandbox-exec (macOS)**: prepends
      ``/usr/bin/sandbox-exec -f <profile> -D SOURCE_DIR=...
      -D OUTPUT_DIR=... -D HOME=... -D TMPDIR_SUBDIR=...`` so the
      ``.sb`` profile's ``(param ...)`` substitutions resolve to
      the per-invocation paths.
    - **bwrap (Linux)**: prepends ``bwrap`` with
      read-only binds for system dirs (/usr, /lib, /lib64 if
      present, /etc), a read-only bind on ``source_dir``, a
      read-write bind on ``output_dir``, ``--tmpfs /tmp``, network
      + PID namespace isolation, ``--die-with-parent``, and
      ``--new-session`` (so the existing
      ``start_new_session=True`` discipline + ``os.killpg``
      timeout-kill path traverse the bwrap wrapper cleanly).

    The function is PURE and platform-detect-only; the resolved
    layer comes from ``_SANDBOX_LAYER``. Mocking the layer in
    tests requires monkey-patching ``_SANDBOX_LAYER`` directly.
    """
    if _SANDBOX_LAYER == "sandbox-exec":
        return [
            "/usr/bin/sandbox-exec",
            "-f", str(SANDBOX_PROFILE_PATH),
            "-D", f"SOURCE_DIR={source_dir}",
            "-D", f"OUTPUT_DIR={output_dir}",
            "-D", f"HOME={Path.home()}",
            "-D", f"TMPDIR_SUBDIR={tmpdir_subdir}",
            *cmd,
        ]
    if _SANDBOX_LAYER == "bwrap":
        bwrap_args = ["bwrap", "--ro-bind", "/usr", "/usr"]
        # /lib + /lib64 only exist on some distros (Debian merged-usr,
        # 64-bit). E13_S03b F6 rectification — guard both with
        # existence checks so a minimal-image (e.g. Alpine, scratch)
        # operator doesn't trip ``bwrap: Can't bind /lib`` errors.
        if Path("/lib").exists():
            bwrap_args.extend(["--ro-bind", "/lib", "/lib"])
        if Path("/lib64").exists():
            bwrap_args.extend(["--ro-bind", "/lib64", "/lib64"])
        # /etc subset is needed for fontconfig + kpathsea + locale.
        bwrap_args.extend(["--ro-bind", "/etc", "/etc"])
        bwrap_args.extend([
            "--ro-bind", str(source_dir), str(source_dir),
            "--bind", str(output_dir), str(output_dir),
            "--tmpfs", "/tmp",
            # E13_S03b F1 — bwrap manpage: "When using --unshare-pid,
            # you really need to mount /proc, or all of the PIDs are
            # wrong in /proc and things will get confused." Perl
            # helpers (LaTeXML runtime) read /proc/self/exe and
            # /proc/cpuinfo for interpreter discovery and locale
            # resolution.
            "--proc", "/proc",
            # E13_S03b F2 — mount a minimal /dev with null, zero,
            # random, urandom, tty, full. Perl Math::Random,
            # Crypt::Random, fontconfig, and subprocesses redirecting
            # to /dev/null all require these device nodes.
            "--dev", "/dev",
            "--unshare-net",       # block ALL network egress
            "--unshare-pid",       # block visibility of host PIDs
            "--die-with-parent",   # cleanup on parent death
            "--new-session",       # plays nice with start_new_session=True
            "--",                  # end-of-bwrap-args marker
            *cmd,
        ])
        return bwrap_args
    return cmd


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

    # E13_S03b F3 rectification — the ``--timeout=300`` latexmlc
    # CLI flag was dropped (no live-integration test proves the
    # flag form). Python-side ``subprocess`` timeout + ``killpg``
    # remain the load-bearing timeout discipline.
    cmd = [
        "latexmlc",
        str(main_tex.name),
        f"--dest={out_html}",
        "--format=html5",
    ]
    # E13_S03b — Threat 3 Phase 2 sandbox wiring. The ``.sb``
    # profile (macOS) needs a TMPDIR_SUBDIR path that exists; use
    # a context-managed temp dir so cleanup is automatic and
    # nothing leaks across paper invocations.
    with tempfile.TemporaryDirectory(
        prefix=f"arxmcp-latexml-{paper_id}-"
    ) as tmpdir_str:
        cmd = _build_sandbox_cmd(
            cmd,
            source_dir=main_tex.parent,
            output_dir=out_dir,
            tmpdir_subdir=Path(tmpdir_str),
        )
        if _SANDBOX_LAYER is not None:
            logger.debug(
                "latexmlc invoked under %s sandbox for %s",
                _SANDBOX_LAYER,
                paper_id,
            )
        # E13_S03: Popen with start_new_session=True puts latexmlc
        # (or the sandbox wrapper) in its own process group so we
        # can SIGKILL the entire group on timeout. On POSIX (macOS
        # + Linux), start_new_session=True is equivalent to
        # ``os.setsid()`` after fork — the child becomes its own
        # session / process-group leader and any descendants
        # share the new pgid. The sandbox wrapper (sandbox-exec
        # or bwrap --new-session) preserves session semantics
        # through the wrapped exec, so killpg still targets the
        # full process tree including the wrapped latexmlc.
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
            # Kill the entire process group so any Perl helpers
            # latexmlc forked die with it. ProcessLookupError is
            # benign — the group may already be gone if the
            # child exited between ``communicate`` raising and
            # ``killpg`` firing.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            # Drain the pipes so the child doesn't block on a
            # full buffer during teardown. If the group survived
            # SIGKILL (catastrophic — should not happen in
            # practice) we re-raise the original TimeoutExpired
            # so callers see the containment failure as a parse
            # failure.
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.communicate(timeout=5)
            raise

    return detect_parse_success(out_html, proc.returncode)


def politeness_sleep(start_time: float, min_interval: float = POLITENESS_SLEEP_SECONDS) -> None:
    """Sleep so that the next request is at least `min_interval` after the previous one."""
    elapsed = time.monotonic() - start_time
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)

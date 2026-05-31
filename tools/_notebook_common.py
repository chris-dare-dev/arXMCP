"""Shared helpers for the notebook CLI tools (proof-verify-handler-wiring-m6).

This module is the single source of truth for the notebook slug regex and
the per-notebook path layout (Variant 1: global `corpus/`, per-notebook
`lancedb/`).  Importing it from each of the four ``tools/notebook_*.py``
CLI scripts guarantees the four scripts share the same path constants
and slug validation.

The slug regex (``^[a-z][a-z0-9-]{2,30}$``) is the FIRST-LINE defense
against path traversal — see Threat 1 in
``.claude/notes/08-security-observability-ops.md`` and FM-2 in
``.claude/notes/milestones/proof-verify-handler-wiring-m6/research-synthesis.md``.
A path containment check at ``(notebooks_base / slug).resolve()`` is
the belt-and-braces secondary check.
"""

from __future__ import annotations

import gzip
import logging
import re
import tarfile
import urllib.error
from pathlib import Path

logger = logging.getLogger("notebook_common")

# Repo root resolved from this file's location: tools/_notebook_common.py
# → tools/ → repo root.
REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# Variant 1 layout constants.
NOTEBOOKS_BASE: Path = REPO_ROOT / "var" / "arxmcp" / "notebooks"
CORPUS_PARSED_DIR: Path = REPO_ROOT / "var" / "arxmcp" / "corpus" / "parsed"
CORPUS_CHUNKS_DIR: Path = REPO_ROOT / "var" / "arxmcp" / "corpus" / "chunks"
CORPUS_EMBEDDINGS_DIR: Path = REPO_ROOT / "var" / "arxmcp" / "corpus" / "embeddings"
# notebook-preamble-recovery-m1: raw `.tex` source root. Used by the
# `fetch_raw_tex_if_missing` helper and the `tools/recover_preambles.py`
# back-fill script. `fetch_eprint` internally appends `paper_id` so this
# is the PARENT dir, never the per-paper subdir.
CORPUS_RAW_DIR: Path = REPO_ROOT / "var" / "arxmcp" / "corpus" / "raw"

# Slug regex — same constraint the roadmap skill applies to its own
# slugs. Lowercase ASCII + digits + hyphens, 3-31 chars, must start
# with a letter. Rejects ``..``, slashes, shell metacharacters,
# uppercase, leading hyphen.
SLUG_RE: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9-]{2,30}$")


class NotebookError(RuntimeError):
    """Raised by any notebook helper when a precondition fails.

    Prefer this over ``assert`` per CLAUDE.md §4.7 ("`assert` is BANNED
    for invariants — Python ``-O`` strips them").
    """


def validate_slug(slug: str) -> None:
    """Reject any slug that doesn't match :data:`SLUG_RE`.

    Raises :class:`NotebookError` (a :class:`RuntimeError` subclass).
    This is the FIRST check every script's ``main()`` performs, before
    any path construction. See FM-2 in the synthesis.
    """
    if not isinstance(slug, str):
        raise NotebookError(
            f"slug must be a string, got {type(slug).__name__}"
        )
    if not SLUG_RE.fullmatch(slug):
        raise NotebookError(
            f"invalid notebook slug {slug!r}: must match "
            f"{SLUG_RE.pattern!r} (lowercase letter start, then "
            f"3-30 chars of [a-z0-9-]). This rule rejects path "
            f"traversal (../, slashes), uppercase, and shell "
            f"metacharacters."
        )


def notebook_dir(slug: str, *, base: Path | None = None) -> Path:
    """Return the per-notebook dir under :data:`NOTEBOOKS_BASE`.

    Validates the slug AND verifies the resolved target stays inside
    ``base`` (defaults to :data:`NOTEBOOKS_BASE`). This is the
    belt-and-braces secondary defense from FM-2; the regex in
    :func:`validate_slug` is the primary defense.

    Closes F3 (HIGH) from the m6 critique: if ``nb_base/<slug>`` IS a
    symlink (regardless of where it points), refuse to operate on it.
    Both the regex-pass-then-pre-create-symlink and the legitimate-
    symlink-to-another-notebook cases are covered. Operators creating
    notebook directories via the m6 scripts will never produce symlinks;
    a symlink at the slug name implies the directory was pre-created
    out-of-band, which is a red flag worth blocking on.

    The ``base`` argument is for tests — production callers pass the
    default. Both ``base`` and the constructed target are resolved
    BEFORE comparison so symlinks don't sneak past the containment
    check. ``base`` may be a non-existent directory (tests use
    ``tmp_path`` subdirs that don't exist yet) — we use ``resolve
    (strict=False)`` semantics so non-existence is fine.
    """
    validate_slug(slug)
    nb_base = (base or NOTEBOOKS_BASE).resolve()
    # F3: refuse symlinks BEFORE resolving (we want to detect the
    # symlink itself, not its target). Use the un-resolved path so
    # is_symlink() reports True on the link, not the target.
    unresolved_target = nb_base / slug
    if unresolved_target.is_symlink():
        raise NotebookError(
            f"notebook path {unresolved_target} is a symlink — "
            f"refusing for safety. Investigate before proceeding; if "
            f"intentional, replace with a real directory."
        )
    target = unresolved_target.resolve()
    # Containment check: target must be a child of nb_base.
    try:
        target.relative_to(nb_base)
    except ValueError as exc:  # pragma: no cover — regex makes this unreachable
        raise NotebookError(
            f"slug {slug!r} resolves outside notebooks base "
            f"({target} not under {nb_base})"
        ) from exc
    return target


def notebook_lancedb_path(slug: str, *, base: Path | None = None) -> Path:
    """Return the per-notebook LanceDB dataset path for ``slug``.

    This is ``notebook_dir(slug) / "lancedb"`` — the same path
    ``tools/notebook_ingest.py`` writes to and the MCP server reads
    when notebook-scoped retrieval is active (notebook-retrieval-m1,
    fork C). It inherits :func:`notebook_dir`'s slug validation +
    symlink rejection + containment check (Threat 1), so the returned
    path is safe to hand to ``lancedb.connect``.

    **Shared seam (stepping-stone shaping, notebook-retrieval-m1 AC8):**
    both the fork-C startup path (`server/config.py` deriving
    ``lancedb_path`` from ``ARXMCP_NOTEBOOK``) AND the future fork-A
    per-request routing path (`filters.notebook=<slug>`) call THIS
    helper, so the C→A migration is additive — A does not re-derive
    the path or re-implement the slug-safety contract.

    The path may not exist yet (a notebook can be registered before
    it is ingested); callers that require an ingested corpus check
    for ``corpus-version.json`` / ``chunks.lance`` themselves.
    """
    return notebook_dir(slug, base=base) / "lancedb"


def resolve_contact_email(
    arg: str | None,
    *,
    db_path: Path | None = None,
) -> str:
    """Resolve the arXiv polite-pool ``contact_email`` for a CLI
    invocation (``onboarding-uplift-m2``).

    Priority chain (m2 synthesis §1 + §3 D1):

    1. **Explicit ``arg``** — the caller already has it (e.g. an
       ``--email`` CLI flag was passed). Wins outright.
    2. **SQLite via :func:`server.operator_settings.get_contact_email`**
       — the persisted operator pref set by
       ``make init NOTEBOOK=… EMAIL=…``. Sticky across shell restarts.
       This is the m2 mechanism that lets the CLI fetch tools work
       without re-exporting the env var every session.
    3. **``ARXMCP_CONTACT_EMAIL`` env var** — the historical pre-m2
       contract. Continues to work for operators who set it in their
       ``.envrc`` / shell init.
    4. **Raise :class:`NotebookError`** — every source exhausted; tell
       the operator the canonical fix is ``make init … EMAIL=…``.

    If both SQLite and the env var carry a (different) value, SQLite
    wins (per synthesis D1 — sticky pref over shell ephemera) and
    nothing is logged at INFO (would be noise on every CLI call); the
    operator's `make init EMAIL=...` is the documented override.

    The ``db_path`` argument is for tests — production callers pass
    the default (which resolves to
    ``var/arxmcp/cache/notebooks.db``).
    """
    if arg:
        return arg
    # Import locally to keep ``tools/_notebook_common.py``
    # import-cost light and to avoid a hard dependency on the
    # ``server`` package at module-import time (CLI tools may run in
    # a stripped-down virtualenv during early bootstrap).
    import os  # noqa: PLC0415

    from server.operator_settings import DEFAULT_DB_PATH, get_contact_email

    persisted = get_contact_email(db_path or DEFAULT_DB_PATH)
    env_value = os.environ.get("ARXMCP_CONTACT_EMAIL")
    if persisted:
        # m2 critique F4 rectification (MEDIUM): emit an INFO log when
        # the SQLite-persisted value shadows a different env-var value.
        # The shadowing is intentional (synthesis §3 D1 — sticky pref
        # over shell ephemera) but the synthesis FM-3 explicitly
        # prescribed surfacing it so operators can diagnose the
        # "but my export wasn't picked up" case. Operators who want
        # the env var to win can clear the SQLite pref with
        # ``make init NOTEBOOK=<slug> EMAIL=<new-addr>``.
        if env_value and env_value != persisted:
            logger.info(
                "resolve_contact_email: SQLite operator_settings.contact_email "
                "(%s) shadows env var ARXMCP_CONTACT_EMAIL (%s); "
                "set EMAIL= on `make init` to update the persisted value.",
                persisted,
                env_value,
            )
        return persisted
    # Final fallback — the historical env-var contract that the m1
    # carve-out still warns operators NOT to set for `make up`. The
    # CLI tools (this code path) have always read it directly; m2
    # additively offers the SQLite path.
    if env_value:
        return env_value
    raise NotebookError(
        "no contact email available: pass --email <addr>, OR run "
        "`make init NOTEBOOK=<slug> EMAIL=<addr>` to persist it in "
        "the operator_settings store, OR `export "
        "ARXMCP_CONTACT_EMAIL=<addr>` in this shell. The arXiv "
        "polite-pool User-Agent contract (arXiv TOS §3) requires a "
        "contact email on every request."
    )


def read_paper_ids_from_papers_txt(papers_txt: Path) -> list[str]:
    """Read a notebook's ``papers.txt``, skipping ``#``-comments and blanks.

    Mirrors :func:`ingest.bulk_ingest._read_paper_ids` but without
    validating against the arXiv ID regex — that's the caller's job
    (different callers want different categorization: ``notebook_fetch.py``
    surfaces malformed lines as ``malformed=J``, while
    ``notebook_purge.py`` only needs the union to compute set
    difference).
    """
    if not papers_txt.is_file():
        raise NotebookError(
            f"papers.txt not found at {papers_txt} — run "
            f"`tools/notebook_init.py {papers_txt.parent.name}` first"
        )
    out: list[str] = []
    for raw in papers_txt.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def fetch_raw_tex_if_missing(
    paper_id: str,
    raw_dir: Path,
    *,
    contact_email: str | None = None,
) -> bool:
    """Ensure raw `.tex` source for ``paper_id`` exists under ``raw_dir``.

    notebook-preamble-recovery-m1 — Option A from the scan brief at
    ``.claude/notes/scans/preamble-without-raw-tex-2026-05-27.md``.

    ``raw_dir`` is the PARENT directory (e.g. ``var/arxmcp/corpus/raw/``);
    ``fetch_eprint`` appends ``paper_id`` internally and creates the
    paper-specific subdir.

    Idempotency gate: if ``raw_dir / paper_id`` already exists AND
    contains at least one ``.tex`` file, return ``True`` without
    network egress. Operators can re-run the back-fill freely.

    Politeness: this helper does NOT sleep — the caller owns the
    politeness budget (3-second inter-request spacing per arXiv TOU,
    same contract `fetch_eprint` documents). Always call
    ``politeness_sleep(start_time)`` BEFORE invoking this helper if
    the previous call was a network request to ``export.arxiv.org``.

    Exception envelope (matches `fetch_seed.py`):
      - ``urllib.error.HTTPError`` — 404 (withdrawn paper), 503 (rate
        limit), any other non-2xx. Caller handles 503 backoff if needed.
      - ``RuntimeError`` — path-traversal attempt during tarball
        extraction (``_safe_extract`` Threat-1 mitigation). Logged at
        ERROR level (security event), not WARNING.
      - ``OSError`` — disk full, permission denied, gzip decode error
        propagated as OSError subclass.
      - ``tarfile.TarError`` — malformed tarball.
      - ``gzip.BadGzipFile`` — corrupt gzip payload.

    Returns
    -------
    ``True`` if raw `.tex` is now on disk (either was already there,
    or was successfully fetched and extracted). ``False`` on any
    per-paper failure — the notebook run / back-fill MUST continue
    past `False` returns (AC4).
    """
    paper_raw_dir = raw_dir / paper_id
    # F7 rect: use rglob (recursive) to match _select_root_tex's
    # actual search semantics in ingest/preamble.py. arXiv tarballs
    # occasionally extract `.tex` only into subdirs (e.g.
    # `chapters/intro.tex`); the previous top-level-only `.glob`
    # would re-fetch those papers on every back-fill re-run.
    if paper_raw_dir.is_dir() and any(paper_raw_dir.rglob("*.tex")):
        # Idempotent skip: raw .tex already present from a prior run.
        logger.debug(
            "[%s] raw_tex: skip — paper_raw_dir already has .tex files",
            paper_id,
        )
        return True

    # Late import to avoid cycles: tools.arxiv_fetch imports nothing
    # from _notebook_common, but keeping the import lazy means tests
    # that don't exercise the raw-tex path don't pay the import cost.
    from tools.arxiv_fetch import fetch_eprint  # noqa: PLC0415

    try:
        fetch_eprint(paper_id, raw_dir, contact_email=contact_email)
    except urllib.error.HTTPError as exc:
        # 404 (withdrawn), 503 (rate limit), and friends. Caller may
        # implement retry/backoff above; the inline notebook path
        # logs + returns False so the operator re-runs later.
        reason = "withdrawn_404" if exc.code == 404 else f"http_{exc.code}"
        logger.warning(
            "[%s] raw_tex: %s on /e-print/ (%s); preamble will be empty",
            paper_id, reason, exc,
        )
        return False
    except RuntimeError as exc:
        # F2 rect: fetch_eprint raises RuntimeError from TWO distinct
        # sites — _safe_extract (path-traversal, real security event)
        # AND _extract_eprint_response (100 MB Content-Length cap, a
        # DoS-mitigation reject). Disambiguate so ops review surfaces
        # the right category. Message-prefix matching is fragile but
        # acceptable here — both prefixes are stable Python literals
        # in tools/arxiv_fetch.py.
        msg = str(exc)
        if "outside dest" in msg:
            logger.error(
                "[%s] raw_tex: SECURITY EVENT (path traversal): %s",
                paper_id, exc,
            )
        elif "too large" in msg or "cap exceeded" in msg:
            # Oversize response — DoS-mitigation reject, NOT a
            # tarball-bomb. Log at WARNING (resource-exhaustion is
            # still a real signal, but not a path-traversal attempt).
            logger.warning(
                "[%s] raw_tex: oversized response rejected: %s",
                paper_id, exc,
            )
        else:
            # Unexpected RuntimeError shape. Log at ERROR so it
            # surfaces in ops review even if it's a new failure mode.
            logger.error(
                "[%s] raw_tex: unexpected RuntimeError: %s",
                paper_id, exc,
            )
        return False
    except (OSError, tarfile.TarError, gzip.BadGzipFile) as exc:
        # Disk failures, malformed tarballs, corrupt gzip. Recoverable
        # per-paper miss; notebook run continues.
        logger.warning(
            "[%s] raw_tex: extraction failed (%s); preamble will be empty",
            paper_id, exc,
        )
        return False

    logger.info("[%s] raw_tex: fetched + extracted", paper_id)
    return True


__all__ = [
    "CORPUS_CHUNKS_DIR",
    "CORPUS_EMBEDDINGS_DIR",
    "CORPUS_PARSED_DIR",
    "CORPUS_RAW_DIR",
    "NOTEBOOKS_BASE",
    "NotebookError",
    "REPO_ROOT",
    "SLUG_RE",
    "fetch_raw_tex_if_missing",
    "notebook_dir",
    "notebook_lancedb_path",
    "read_paper_ids_from_papers_txt",
    "validate_slug",
]

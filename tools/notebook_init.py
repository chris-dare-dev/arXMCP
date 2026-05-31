"""Scaffold a new notebook directory with empty papers.txt + queries.json
AND register the notebook in ``notebooks.db`` (``onboarding-uplift-m2``).

Variant 1 layout (proof-verify-handler-wiring-m6): global ``corpus/``,
per-notebook ``var/arxmcp/notebooks/<slug>/{papers.txt,queries.json,lancedb/}``.
This script creates the per-notebook dir + the two template files.

**m2 extension:** also writes a notebook row into
``var/arxmcp/cache/notebooks.db::notebooks`` via a direct synchronous
SQLite ``INSERT OR IGNORE``. This makes ``make add NOTEBOOK=<slug>
PAPER=<id>`` work against the live server immediately after
``make init`` — without the registry write, the REST endpoint at
``POST /ui/api/notebooks/<slug>/papers`` 404s on a fresh slug
(m2 synthesis §3 D2). Fully offline-capable; the server need not be
running.

**m2 extension:** ``--email <addr>`` persists the contact email to
``operator_settings`` (m2 synthesis §3 D4). Subsequent CLI fetch
tools (``tools/notebook_fetch.py``, etc.) read the value via
``tools/_notebook_common.py::resolve_contact_email`` without needing
``ARXMCP_CONTACT_EMAIL`` in the env.

Idempotent at every level — re-running on an existing notebook is a
no-op for the on-disk scaffold (skips, logs ``notebook exists``), for
the SQLite registry (``INSERT OR IGNORE``), and for the operator
settings (``INSERT OR REPLACE``, but only when ``--email`` is given).
Partial-state recovery (one of the two files manually deleted)
requires manual cleanup of the notebook dir before re-running.

Usage:

    uv run python tools/notebook_init.py <slug>
    uv run python tools/notebook_init.py <slug> --email you@example.com
    uv run python tools/notebook_init.py <slug> --no-register

Exit codes:
    0 — success or idempotent skip
    1 — slug validation failed (invalid slug → :class:`NotebookError`)
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from tools._notebook_common import (
    NotebookError,
    notebook_dir,
    notebook_lancedb_path,
    validate_slug,
)

PAPERS_TXT_TEMPLATE = """\
# {slug} notebook seed list (created {today})
#
# Add one arXiv paper_id per line. Both new-style (YYMM.NNNNN) and
# old-style (e.g., hep-th/0001234) formats are accepted; the bulk_ingest
# pipeline validates each against ingest.identifiers.is_valid_paper_id.
#
# Once IDs are listed:
#   1. tools/notebook_fetch.py {slug}   # fetches ar5iv HTML for any missing
#   2. tools/notebook_ingest.py {slug}  # chunks, embeds, indexes into per-notebook lancedb
"""


def _queries_template(slug: str) -> dict:
    return {
        "schema_version": "1.0",
        "notebook_slug": slug,
        "notebook_display_name": slug.replace("-", " ").title(),
        "created_at": date.today().isoformat(),
        "comment": (
            "Paper-level relevance labels. For each query, list the paper_ids "
            "in the notebook that ACTUALLY address the pointed sub-question."
        ),
        "queries": [
            {
                "id": "EXAMPLE-q1",
                "difficulty": "easy",
                "text": "replace this with a pointed sub-question",
                "expected_relevant_papers": [],
                "notes": (
                    "Fill in with the 3-8 paper_ids you'd expect a good "
                    "retrieval system to surface. Delete this example query "
                    "and add real ones."
                ),
            }
        ],
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "slug",
        help="Notebook slug (must match ^[a-z][a-z0-9-]{2,30}$).",
    )
    parser.add_argument(
        "--email",
        default=None,
        help=(
            "Operator's contact email for the arXiv polite-pool "
            "User-Agent. Persisted to operator_settings; subsequent "
            "CLI fetch tools read it from there without needing "
            "ARXMCP_CONTACT_EMAIL in the env."
        ),
    )
    parser.add_argument(
        "--no-register",
        dest="register",
        action="store_false",
        default=True,
        help=(
            "Skip the notebooks.db INSERT step. Default is to register "
            "the notebook in SQLite so `make add` works against the "
            "running server. Pass --no-register only when callers "
            "supply their own registry write (tests; pre-population "
            "from a backup tarball)."
        ),
    )
    return parser


def _register_notebook_in_sqlite(slug: str, *, db_path: Path) -> None:
    """Insert a notebooks.db row for ``slug`` via direct SQLite
    ``INSERT OR IGNORE`` — synchronous, no server dependency.

    Mirrors the four connection pragmas from
    :class:`server.notebooks_store.NotebooksStore` (m2 synthesis §2).
    Uses ``INSERT OR IGNORE`` so a re-run on an existing slug is a
    no-op — the m2 idempotency guarantee from AC1.

    The default-column values mirror the v4 schema of
    ``NotebooksStore``: ``display_name=''``, ``notebook_kind='arxiv'``,
    ``parse_status='skipped'``, ``parse_error=''``,
    ``parsed_html_path=''``. The ``lancedb_path`` is the per-notebook
    Variant-1 path; per m2 synthesis §3 D2 the default ``make ingest``
    path stays at the shared global corpus, so this column is recorded
    but does NOT pre-create the directory.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    nb_lancedb = notebook_lancedb_path(slug)
    now = (
        datetime.now(UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )

    conn = sqlite3.connect(
        str(db_path),
        isolation_level=None,
        check_same_thread=False,
    )
    try:
        # Match NotebooksStore.open's pragmas verbatim (m2 synthesis §2):
        # WAL + FULL + fullfsync + foreign_keys + a 5s busy_timeout. The
        # notebooks.db file's user_version is owned by NotebooksStore;
        # this script must NOT touch it (m2 synthesis §3 D1).
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA fullfsync=ON")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout=5000")

        # Defensive: if the file is brand-new (no NotebooksStore.open()
        # has run yet), the ``notebooks`` table does not exist. Create
        # it with the v4-shape columns so this script can run
        # standalone. The NotebooksStore migration path is also safe to
        # run later — its CREATE statements use IF NOT EXISTS from v1
        # onward.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS notebooks ("
            "  slug          TEXT PRIMARY KEY,"
            "  display_name  TEXT NOT NULL DEFAULT '',"
            "  lancedb_path  TEXT NOT NULL,"
            "  created_at    TEXT NOT NULL,"
            "  notebook_kind TEXT NOT NULL DEFAULT 'arxiv',"
            "  parse_status  TEXT NOT NULL DEFAULT 'skipped',"
            "  parse_error   TEXT NOT NULL DEFAULT '',"
            "  parsed_html_path TEXT NOT NULL DEFAULT ''"
            ")"
        )

        cur = conn.execute(
            "INSERT OR IGNORE INTO notebooks ("
            "  slug, display_name, lancedb_path, created_at, "
            "  notebook_kind, parse_status, parse_error, parsed_html_path"
            ") VALUES (?, ?, ?, ?, 'arxiv', 'skipped', '', '')",
            (slug, "", str(nb_lancedb), now),
        )
        if cur.rowcount > 0:
            print(f"registered notebook {slug!r} in {db_path}")
        else:
            print(f"notebook {slug!r} already registered in {db_path}")
    finally:
        conn.close()


def _persist_email(email: str, *, db_path: Path) -> None:
    """Write ``email`` to ``operator_settings`` via the m2 sync API.

    The store handles the chmod-0600-on-create + WAL + busy_timeout
    discipline. ``INSERT OR REPLACE`` is naturally idempotent.
    """
    from server.operator_settings import set_setting  # local import

    set_setting("contact_email", email, db_path=db_path)
    print(f"persisted contact_email to operator_settings ({db_path})")


def run(
    slug: str,
    *,
    email: str | None = None,
    register: bool = True,
    db_path: Path | None = None,
) -> int:
    """Pure function — accepts a slug + optional email + register
    flag, returns an exit code.

    Tests call this directly with synthetic slugs + paths; the CLI
    entry just wires argparse into it. The ``db_path`` arg is for
    tests; production callers pass ``None`` (defaults to
    ``var/arxmcp/cache/notebooks.db``).
    """
    validate_slug(slug)
    nb_dir = notebook_dir(slug)

    # On-disk scaffold — original idempotent behavior preserved.
    if nb_dir.exists():
        print(f"notebook exists; skipping (slug={slug!r}, path={nb_dir})")
    else:
        nb_dir.mkdir(parents=True, exist_ok=False)
        papers_txt = nb_dir / "papers.txt"
        papers_txt.write_text(
            PAPERS_TXT_TEMPLATE.format(slug=slug, today=date.today().isoformat()),
            encoding="utf-8",
        )
        queries_json = nb_dir / "queries.json"
        queries_json.write_text(
            json.dumps(_queries_template(slug), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"created {nb_dir}/ with papers.txt + queries.json")

    # m2 SQLite registration + email persistence — both idempotent.
    # Resolve the default db_path lazily so test callers can inject a
    # tmp_path-scoped DB.
    if (register or email is not None) and db_path is None:
        from server.operator_settings import DEFAULT_DB_PATH  # local

        db_path = DEFAULT_DB_PATH

    if register:
        _register_notebook_in_sqlite(slug, db_path=db_path)  # type: ignore[arg-type]

    if email is not None:
        _persist_email(email, db_path=db_path)  # type: ignore[arg-type]

    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        return run(args.slug, email=args.email, register=args.register)
    except NotebookError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

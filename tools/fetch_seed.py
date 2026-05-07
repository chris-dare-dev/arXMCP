#!/usr/bin/env python3
"""Walk tools/seed-papers.txt and fetch + LaTeXML-parse each paper.

E01_S03 main loop. Honors the politeness contract from
.claude/notes/03-ingestion-pipeline.md § Source 3:
- 3 second sleep between every /e-print/ request (not just on failure)
- Retry-After honored on 503 (floor: 30s exponential backoff, cap 5min)
- arXMCP/0.1 (mailto:$ARXMCP_CONTACT_EMAIL) User-Agent

Logs ALL outcomes (success and failure) to
var/arxmcp/ops/parser-failures/seed.log so the rate is the baseline E02
will improve against — not just failures. The log is rewritten after
every paper, so a SIGINT or crash mid-run leaves a recoverable state.

Idempotency: a paper whose parsed/<id>/index.html already exists at
start-up is treated as already done and skipped (no network fetch, no
LaTeXML run). This makes a re-run after a crash cheap.

Acceptance criterion is ≥45/50 successful parses; the script exits 0 if
that threshold is met, 1 otherwise.

Usage:
    export ARXMCP_CONTACT_EMAIL=you@example.com
    python tools/fetch_seed.py
    python tools/fetch_seed.py --allow-undersized   # dev-only escape hatch
"""

from __future__ import annotations

import argparse
import gzip
import http
import subprocess
import sys
import tarfile
import time
import urllib.error
from dataclasses import dataclass
from pathlib import Path

from tools.arxiv_fetch import (
    DEFAULT_503_BACKOFF_SECONDS,
    MAX_503_BACKOFF_SECONDS,
    MIN_PARSED_HTML_BYTES,
    POLITENESS_SLEEP_SECONDS,
    FetchResult,
    fetch_eprint,
    find_main_tex,
    parse_retry_after,
    parse_with_latexml,
    politeness_sleep,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_FILE = REPO_ROOT / "tools" / "seed-papers.txt"
RAW_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" / "raw"
PARSED_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" / "parsed"
LOG_PATH = REPO_ROOT / "var" / "arxmcp" / "ops" / "parser-failures" / "seed.log"

ACCEPTANCE_THRESHOLD = 45
EXPECTED_SEED_COUNT = 50

# Exception classes that an unrecoverable per-paper failure may raise.
# Threat 3 (LaTeXML hang) raises subprocess.TimeoutExpired — its MRO does
# NOT include OSError, so we catch it explicitly. Same for tarfile errors
# from corrupt /e-print/ tarballs.
PER_PAPER_FAILURE_EXCEPTIONS = (
    RuntimeError,
    OSError,
    ValueError,
    subprocess.TimeoutExpired,
    tarfile.TarError,
    gzip.BadGzipFile,
)


@dataclass(frozen=True)
class Outcome:
    paper_id: str
    success: bool
    message: str
    elapsed_s: float


def read_seed_list(path: Path) -> list[str]:
    """Read paper IDs from seed-papers.txt; skip blanks and # comments."""
    ids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        ids.append(stripped)
    return ids


def already_parsed(paper_id: str, parsed_dir: Path) -> bool:
    """Idempotency gate: skip papers whose parsed HTML already exists at size."""
    out_html = parsed_dir / paper_id / "index.html"
    return out_html.exists() and out_html.stat().st_size > MIN_PARSED_HTML_BYTES


def fetch_with_backoff(
    paper_id: str, raw_dir: Path
) -> tuple[Outcome, FetchResult | None]:
    """Fetch one paper with 503 backoff.

    Returns the outcome paired with the FetchResult on success (so the
    caller can read main_tex without re-deriving it via rglob).
    """
    backoff = DEFAULT_503_BACKOFF_SECONDS
    request_start = time.monotonic()

    while True:
        try:
            result = fetch_eprint(paper_id, raw_dir)
            elapsed = time.monotonic() - request_start
            return (
                Outcome(paper_id=paper_id, success=True, message="fetched", elapsed_s=elapsed),
                result,
            )
        except urllib.error.HTTPError as e:
            elapsed = time.monotonic() - request_start
            is_503 = e.code == http.HTTPStatus.SERVICE_UNAVAILABLE.value
            if is_503 and backoff < MAX_503_BACKOFF_SECONDS:
                wait = parse_retry_after(e.headers.get("Retry-After"), backoff)
                print(f"[{paper_id}] 503; backing off {wait:.0f}s", file=sys.stderr)
                time.sleep(wait)
                backoff = min(backoff * 2, MAX_503_BACKOFF_SECONDS)
                continue
            return (
                Outcome(
                    paper_id=paper_id,
                    success=False,
                    message=f"http {e.code}",
                    elapsed_s=elapsed,
                ),
                None,
            )
        except PER_PAPER_FAILURE_EXCEPTIONS as e:
            elapsed = time.monotonic() - request_start
            return (
                Outcome(
                    paper_id=paper_id,
                    success=False,
                    message=f"{type(e).__name__}: {e}",
                    elapsed_s=elapsed,
                ),
                None,
            )


def process_paper(paper_id: str) -> Outcome:
    """Fetch + parse one paper. Returns combined Outcome."""
    if already_parsed(paper_id, PARSED_DIR):
        return Outcome(
            paper_id=paper_id,
            success=True,
            message="already parsed (skipped)",
            elapsed_s=0.0,
        )

    fetch_outcome, fetch_result = fetch_with_backoff(paper_id, RAW_DIR)
    if not fetch_outcome.success or fetch_result is None:
        return fetch_outcome

    main_tex = fetch_result.main_tex or find_main_tex(fetch_result.raw_dir, paper_id)
    if main_tex is None:
        return Outcome(
            paper_id=paper_id,
            success=False,
            message="no .tex file in tarball",
            elapsed_s=fetch_outcome.elapsed_s,
        )

    parse_start = time.monotonic()
    try:
        parse = parse_with_latexml(main_tex, PARSED_DIR, paper_id)
        elapsed = fetch_outcome.elapsed_s + (time.monotonic() - parse_start)
        return Outcome(
            paper_id=paper_id,
            success=parse.success,
            message=parse.message,
            elapsed_s=elapsed,
        )
    except PER_PAPER_FAILURE_EXCEPTIONS as e:
        elapsed = fetch_outcome.elapsed_s + (time.monotonic() - parse_start)
        return Outcome(
            paper_id=paper_id,
            success=False,
            message=f"latexml {type(e).__name__}: {e}",
            elapsed_s=elapsed,
        )


def write_log(log_path: Path, outcomes: list[Outcome], total_elapsed: float) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# arXMCP seed corpus fetch — {len(outcomes)} papers",
        f"# total_wall_clock_seconds={total_elapsed:.1f}",
        f"# successes={sum(1 for o in outcomes if o.success)}",
        f"# failures={sum(1 for o in outcomes if not o.success)}",
        "# format: <paper_id>\\t<status>\\t<elapsed_s>\\t<message>",
    ]
    for o in outcomes:
        status = "ok" if o.success else "fail"
        lines.append(f"{o.paper_id}\t{status}\t{o.elapsed_s:.1f}\t{o.message}")
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed-file",
        type=Path,
        default=SEED_FILE,
        help=f"path to seed-papers.txt (default: {SEED_FILE.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--allow-undersized",
        action="store_true",
        help=(
            "permit a seed list with fewer than 50 IDs (dev-only escape hatch). "
            "Without this flag the script exits 2 if the list is undersized — "
            "E01_S03 acceptance criterion #1 requires 50."
        ),
    )
    args = parser.parse_args()

    paper_ids = read_seed_list(args.seed_file)
    if len(paper_ids) != EXPECTED_SEED_COUNT and not args.allow_undersized:
        try:
            seed_display = args.seed_file.relative_to(REPO_ROOT)
        except ValueError:
            seed_display = args.seed_file
        print(
            f"ERROR: seed list has {len(paper_ids)} IDs, expected {EXPECTED_SEED_COUNT} "
            f"(E01_S03 acceptance criterion #1).\n"
            f"Run `tools/curate_seed.py` to generate candidates, then commit 50 IDs to "
            f"{seed_display}.\n"
            f"Pass --allow-undersized to override (dev-only).",
            file=sys.stderr,
        )
        return 2

    print(
        f"fetching {len(paper_ids)} papers; politeness sleep "
        f"{POLITENESS_SLEEP_SECONDS}s between requests",
        file=sys.stderr,
    )

    outcomes: list[Outcome] = []
    overall_start = time.monotonic()
    last_request_at: float | None = None

    try:
        for i, paper_id in enumerate(paper_ids):
            if last_request_at is not None and not already_parsed(paper_id, PARSED_DIR):
                politeness_sleep(last_request_at)
            request_start = time.monotonic()
            outcome = process_paper(paper_id)
            outcomes.append(outcome)
            if outcome.message != "already parsed (skipped)":
                last_request_at = request_start
            status = "ok" if outcome.success else "FAIL"
            elapsed = time.monotonic() - request_start
            print(
                f"[{i + 1}/{len(paper_ids)}] {paper_id} {status} "
                f"({elapsed:.1f}s) — {outcome.message}"
            )
            write_log(LOG_PATH, outcomes, time.monotonic() - overall_start)
    except KeyboardInterrupt:
        print("\nInterrupted by user; partial log preserved.", file=sys.stderr)
        write_log(LOG_PATH, outcomes, time.monotonic() - overall_start)
        return 130

    total_elapsed = time.monotonic() - overall_start

    successes = sum(1 for o in outcomes if o.success)
    print(
        f"\nDone: {successes}/{len(paper_ids)} parsed successfully in "
        f"{total_elapsed:.0f}s ({total_elapsed / 60:.1f}min). Log: {LOG_PATH}"
    )

    if successes < ACCEPTANCE_THRESHOLD:
        print(
            f"FAIL: {successes} successes < threshold {ACCEPTANCE_THRESHOLD}/{EXPECTED_SEED_COUNT}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

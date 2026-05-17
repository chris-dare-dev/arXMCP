#!/usr/bin/env python3
"""Ingest-paused sentinel — pause/resume the OAI-PMH delta loop
(E14_S05).

The sentinel file lives at ``var/arxmcp/ops/ingest-paused``. When
present, the delta cron wrapper (``ops/cron/arxmcp-delta.sh``)
short-circuits and exits 0 with a log line; manual invocations of
``python -m ingest.oai_delta`` honor the same check at module
entry.

The file body is a JSON record::

    {
      "reason": "disk_low",
      "free_bytes": 5242880,
      "threshold_bytes": 10737418240,
      "written_at": "2026-05-17T03:00:00Z"
    }

Producers + consumers:

- **Producer (D4 disk-low):** the server's scrape-time refresh
  hook in :func:`server.health.refresh_metrics_from_singleton_state`
  calls :func:`write_pause` when ``shutil.disk_usage(data_dir)`` falls
  below 10 GB free; :func:`clear_pause` once free climbs back above 15
  GB (hysteresis).
- **Producer (manual):** the operator can run
  ``python -m tools.ingest_sentinel write --reason=maintenance``
  before manual maintenance.
- **Consumer (cron):** ``ops/cron/arxmcp-delta.sh`` checks for the
  file and exits 0.
- **Consumer (Python):** :func:`ingest.oai_delta.main` checks via
  :func:`is_paused` and exits 0.

The sentinel is **idempotent**: a second :func:`write_pause` with the
same reason overwrites the body (refreshes ``free_bytes`` /
``threshold_bytes``) but does not stack. :func:`clear_pause` removes
the file unconditionally — see "self-clearing vs operator-clearing"
in the E14_S05 research synthesis §D4.

Closes failure mode 7 (Disk full) from
``.claude/notes/08-security-observability-ops.md`` §"Failure modes
and graceful degradation".
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import pathlib
import sys
from dataclasses import dataclass

logger = logging.getLogger(__name__)


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Default sentinel path. The runtime resolves it via
#: ``Config.data_dir`` so a non-default ``ARXMCP_DATA_DIR`` is
#: honored. The fallback below is used by the CLI when no
#: explicit path is given.
DEFAULT_SENTINEL_PATH: pathlib.Path = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "ingest-paused"
)


@dataclass(frozen=True, slots=True)
class PauseRecord:
    """One sentinel record. Serialised as JSON to disk."""

    reason: str
    written_at: str
    free_bytes: int | None = None
    threshold_bytes: int | None = None

    def to_json(self) -> str:
        payload = {
            "reason": self.reason,
            "written_at": self.written_at,
        }
        if self.free_bytes is not None:
            payload["free_bytes"] = self.free_bytes
        if self.threshold_bytes is not None:
            payload["threshold_bytes"] = self.threshold_bytes
        return json.dumps(payload, sort_keys=True)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _resolve_sentinel_path(path: pathlib.Path | None = None) -> pathlib.Path:
    """Resolve the sentinel path. Explicit argument wins; else
    ``ARXMCP_DATA_DIR/ops/ingest-paused`` if the env var is set;
    else :data:`DEFAULT_SENTINEL_PATH`."""
    if path is not None:
        return path
    env_dir = os.environ.get("ARXMCP_DATA_DIR")
    if env_dir:
        return pathlib.Path(env_dir) / "ops" / "ingest-paused"
    return DEFAULT_SENTINEL_PATH


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def write_pause(
    reason: str,
    *,
    free_bytes: int | None = None,
    threshold_bytes: int | None = None,
    path: pathlib.Path | None = None,
) -> pathlib.Path:
    """Write the ingest-paused sentinel.

    Idempotent on identical ``reason`` — the file is overwritten with
    the latest ``free_bytes`` snapshot but a second call with the
    same reason does NOT stack. Different reasons OVERWRITE — the
    sentinel is one-at-a-time by design; the operator's "manual
    maintenance pause" wins over an automatic "disk_low" pause and
    vice versa, with the *latest* writer's record on disk.
    """
    sentinel = _resolve_sentinel_path(path)
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    record = PauseRecord(
        reason=reason,
        written_at=_now_iso(),
        free_bytes=free_bytes,
        threshold_bytes=threshold_bytes,
    )
    # Two-phase write so a concurrent reader never sees a partial
    # JSON body. Same discipline as ``ops/cron/arxmcp-backup.sh``'s
    # backup-status.json write.
    tmp = sentinel.with_suffix(sentinel.suffix + ".tmp")
    tmp.write_text(record.to_json() + "\n", encoding="utf-8")
    tmp.replace(sentinel)
    logger.info("ingest-paused written: reason=%s path=%s", reason, sentinel)
    return sentinel


def clear_pause(path: pathlib.Path | None = None) -> bool:
    """Remove the ingest-paused sentinel. Returns ``True`` if the
    sentinel was present and removed, ``False`` if it was already
    absent (idempotent).
    """
    sentinel = _resolve_sentinel_path(path)
    try:
        sentinel.unlink()
        logger.info("ingest-paused cleared: path=%s", sentinel)
        return True
    except FileNotFoundError:
        return False


def is_paused(path: pathlib.Path | None = None) -> dict | None:
    """Return the sentinel JSON body if present, ``None`` otherwise.

    Reading the body is the operator's signal for *why* ingest is
    paused. A malformed body returns a synthetic
    ``{"reason": "malformed_sentinel"}`` so callers don't have to
    handle ``json.JSONDecodeError`` themselves — the sentinel is
    documented as best-effort recovery state.
    """
    sentinel = _resolve_sentinel_path(path)
    try:
        raw = sentinel.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(
            "ingest-paused sentinel at %s is malformed; "
            "honor the pause and treat reason=malformed_sentinel",
            sentinel,
        )
        return {"reason": "malformed_sentinel"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="tools.ingest_sentinel",
        description=(
            "Manage the var/arxmcp/ops/ingest-paused sentinel. "
            "When present, the delta cron wrapper and "
            "ingest.oai_delta short-circuit and exit 0."
        ),
    )
    p.add_argument(
        "--path",
        type=pathlib.Path,
        default=None,
        help="override the sentinel path (default: ARXMCP_DATA_DIR/ops/"
             "ingest-paused, then var/arxmcp/ops/ingest-paused)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_write = sub.add_parser("write", help="write the sentinel")
    p_write.add_argument(
        "--reason",
        required=True,
        help="short slug identifying the pause cause "
             "(e.g. disk_low, maintenance, upgrade)",
    )
    p_write.add_argument(
        "--free", type=int, default=None,
        help="observed free bytes (optional; included in the JSON body)",
    )
    p_write.add_argument(
        "--threshold", type=int, default=None,
        help="threshold bytes (optional; included in the JSON body)",
    )

    sub.add_parser("clear", help="remove the sentinel")

    sub.add_parser("status", help="exit 0 if running, 2 if paused")

    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if args.cmd == "write":
        write_pause(
            reason=args.reason,
            free_bytes=args.free,
            threshold_bytes=args.threshold,
            path=args.path,
        )
        return 0
    if args.cmd == "clear":
        removed = clear_pause(path=args.path)
        print(
            f"{'cleared' if removed else 'no sentinel present'}; "
            f"path={_resolve_sentinel_path(args.path)}",
        )
        return 0
    if args.cmd == "status":
        record = is_paused(path=args.path)
        if record is None:
            print("running")
            return 0
        reason = record.get("reason", "unknown")
        print(f"paused; reason={reason}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

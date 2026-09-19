"""Scan-window parsing, validation, and recency filtering (WS-E v0).

The exploration pipeline scans 3-12-month literature windows
(workstreams.md §WS-E). This module is the single place window rules
live:

- :func:`parse_window` — parse + validate an explicit from/to pair.
- :func:`window_from_months` — derive a window ending today (or a given
  anchor date) spanning N months.
- :func:`Window.contains` — the AC-E.2 recency check: every proposed
  paper's date must fall inside the window.
- :func:`paper_id_month` / :func:`Window.contains_month` — a
  month-granularity fallback for citation-graph candidates, whose only
  date signal is the YYMM prefix of a new-style arXiv id. A graph-only
  candidate is admitted ONLY when its entire submission month lies
  inside the window (conservative: never admits a paper that could be
  outside).

All validation is ``if … raise`` (CLAUDE.md §4.7 — ``assert`` is
banned; ``-O`` strips it).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

MIN_WINDOW_MONTHS = 3
MAX_WINDOW_MONTHS = 12

#: New-style arXiv id: YYMM.NNNNN (optionally versioned). New-style ids
#: exist only from 2007-04 onward, so YY always maps to 20YY.
_NEW_STYLE_RE = re.compile(r"^(\d{2})(\d{2})\.\d{4,5}(v\d+)?\Z")


def _add_months(d: date, months: int) -> date:
    """Return ``d`` shifted by ``months`` (day clamped to month end)."""
    total = d.year * 12 + (d.month - 1) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    # clamp the day (e.g. Jan 31 + 1 month -> Feb 28/29)
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    raise ValueError(f"cannot shift {d.isoformat()} by {months} months")


def _parse_iso_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"window {field!r} is not an ISO date (YYYY-MM-DD): {value!r}") from exc


@dataclass(frozen=True)
class Window:
    """A validated 3-12-month scan window (inclusive of both endpoints)."""

    start: date
    end: date

    def contains(self, when: str) -> bool:
        """AC-E.2 recency check for an ISO date or RFC 3339 datetime string.

        Accepts the raw Atom ``<published>`` form (``2026-02-15T09:00:00Z``)
        or a bare date. Malformed/empty dates return False — an undatable
        candidate is never proposed as in-window.
        """
        if not when:
            return False
        text = when.strip()
        try:
            d = datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                d = date.fromisoformat(text[:10])
            except ValueError:
                return False
        return self.start <= d <= self.end

    def contains_month(self, year: int, month: int) -> bool:
        """True when the ENTIRE month lies inside the window (conservative)."""
        first = date(year, month, 1)
        next_first = _add_months(first, 1).replace(day=1)
        month_end = next_first - timedelta(days=1)
        return self.start <= first and month_end <= self.end

    def as_payload(self) -> dict[str, object]:
        """The manifest ``payload.window`` block (with approximate months)."""
        span = (self.end.year * 12 + self.end.month) - (self.start.year * 12 + self.start.month)
        months = min(MAX_WINDOW_MONTHS, max(MIN_WINDOW_MONTHS, span))
        return {
            "from": self.start.isoformat(),
            "to": self.end.isoformat(),
            "months": months,
        }


def parse_window(from_str: str, to_str: str) -> Window:
    """Parse and validate an explicit window.

    Rules: valid ISO dates; ``from`` < ``to``; span within
    [``MIN_WINDOW_MONTHS``, ``MAX_WINDOW_MONTHS``] months (measured by
    month arithmetic: ``from + 3 months <= to <= from + 12 months``).
    """
    start = _parse_iso_date(from_str, "from")
    end = _parse_iso_date(to_str, "to")
    if start >= end:
        raise ValueError(f"window 'from' ({start}) must precede 'to' ({end})")
    if end < _add_months(start, MIN_WINDOW_MONTHS):
        raise ValueError(
            f"window {start}..{end} is shorter than {MIN_WINDOW_MONTHS} months — "
            f"the exploration pipeline scans {MIN_WINDOW_MONTHS}-{MAX_WINDOW_MONTHS}-month "
            "windows (workstreams.md §WS-E)"
        )
    if end > _add_months(start, MAX_WINDOW_MONTHS):
        raise ValueError(
            f"window {start}..{end} is longer than {MAX_WINDOW_MONTHS} months — "
            f"the exploration pipeline scans {MIN_WINDOW_MONTHS}-{MAX_WINDOW_MONTHS}-month "
            "windows (workstreams.md §WS-E)"
        )
    return Window(start=start, end=end)


def window_from_months(months: int, end: date | None = None) -> Window:
    """A window spanning ``months`` months, ending at ``end`` (default today)."""
    if not MIN_WINDOW_MONTHS <= months <= MAX_WINDOW_MONTHS:
        raise ValueError(
            f"months must be {MIN_WINDOW_MONTHS}-{MAX_WINDOW_MONTHS}, got {months}"
        )
    end_date = end if end is not None else date.today()
    return Window(start=_add_months(end_date, -months), end=end_date)


def paper_id_month(paper_id: str) -> tuple[int, int] | None:
    """(year, month) from a new-style arXiv id's YYMM prefix, else None.

    Old-style ids (``hep-th/0001234``) and textbook ids return None —
    the caller must treat those as undatable (and therefore never
    in-window without an explicit date).
    """
    m = _NEW_STYLE_RE.match(paper_id.strip())
    if m is None:
        return None
    yy, mm = int(m.group(1)), int(m.group(2))
    if not 1 <= mm <= 12:
        return None
    return (2000 + yy, mm)


__all__ = [
    "MAX_WINDOW_MONTHS",
    "MIN_WINDOW_MONTHS",
    "Window",
    "paper_id_month",
    "parse_window",
    "window_from_months",
]

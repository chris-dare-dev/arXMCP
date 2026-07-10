---
name: ustar-name-field-100-not-255
description: USTAR's name field is 100 chars (+155 prefix), NOT 255 bytes — a milestone preflight using 255 admits filenames Python's tarfile then refuses
metadata:
  type: feedback
---

When any milestone builds a USTAR tar with a member-name preflight, the
correct limit is **100 chars** for the `name` field (POSIX USTAR header),
optionally split by Python's `tarfile._posix_split_name` against a 155-char
`prefix` field at the last slash that fits. A preflight that gates at
"USTAR's 255-byte limit" conflates POSIX `NAME_MAX` (filesystem) with the
on-tape field width and is wrong.

**Why:** notebook-surface-expansion-m6's `_EXPORT_USTAR_NAME_MAX = 255`
admits a 150-char single-segment filename (no slash to split on); tarfile's
`_posix_split_name` raises `ValueError: name is too long` — propagated as
an unhandled 500. Live-reproduced on Python 3.12.13 with a 150-char file
under a notebook dir → route returned 500. The synthesis ALSO had the
wrong number (D5: "names exceeding USTAR's 255-byte field") — implementer
faithfully implemented the wrong constant. Both researcher briefs and the
implementer missed it.

**How to apply:** On any milestone that builds a tar with manual
`TarInfo`, ASSERT the preflight gates at:
- ≤100 chars for the trailing component after the last splittable slash, OR
- ≤100 chars total if no internal slash exists in the path.

The strictly-safe check is `len(name) <= 100`. The "split-aware" check
is `tarfile._posix_split_name` itself; reproduce by `tarfile.open(...,
format=tarfile.USTAR_FORMAT)` and `tar.addfile(TarInfo(name=name), ...)`
against a candidate length to see whether it raises. If a milestone
needs longer names, USE PAX format — but then byte-determinism dies
unless `pax_headers` are explicitly zeroed (which is more delicate than
USTAR's mtime=0 trick).

Regression test pattern: plant a single 150-char filename under the
slug-dir, GET the export route, assert status_code == 200 (the file is
skipped + WARNed, not 500). The 150-char case is well within POSIX
NAME_MAX (255) so it's a plausible real-world filename.

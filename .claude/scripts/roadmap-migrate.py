#!/usr/bin/env python3
"""roadmap-migrate.py — convert a legacy prose roadmap into a roadmap/1 skeleton.

Usage:
  python3 roadmap-migrate.py <legacy.md> --slug <slug> [--project <key>]
      [--out-dir <plans-dir>] [--as-of ISO] [--force] [--dry-run]

Parses a legacy prose roadmap markdown for:
  - milestone headings   (^#{2,4} containing <slug>-mN; arXMCP `### <id> — <title>`;
                          bare `## M<N> — ...`)
  - epic headings        (<slug>-eN, bare E1/E2 style, or unnamed `## Epic — ...`
                          which get the next free <slug>-eN in document order)
  - spike ids            (<slug>-spike-N in headings or bullets, or `- **SP<N>**`)
  - checkbox lines       ([x]/[ ]/[/]/[-]) — acceptance criteria when under an
                          "Acceptance" label, otherwise tasks <slug>-t-<semantic>
  - acceptance criteria  (Given/When/Then bullets or labeled bullet lists)
  - MoSCoW markers       (`- **Must**: id, id` lists -> item priority)
  - Now/Next/Later lanes (bold `**Now**` markers and `... Now lane` headings)
  - RICE tables          (header with Reach/Impact/Effort -> item rice block)
  - goal sections        (HMW, Objective, Key Results, Assumptions, Won't)

and emits a skeleton for LLM-assisted completion:

  <out-dir>/<slug>/roadmap.yaml           roadmap/1 (phase: sequenced, status: active)
  <out-dir>/<slug>/progress/agent.jsonl   seeded done/in_progress journal events
  <out-dir>/<slug>/progress/.gitkeep

IDs found in the source are preserved VERBATIM (write-once rule — never
renumber). Prose the parser cannot map is listed in a `# MIGRATE-TODO:` YAML
comment block at the top of roadmap.yaml, together with every title/goal/
acceptance gap the LLM pass must fill. Each item carries an `origin.src`
pointer (`<file>:<line>`) back into the source doc.

The validator (roadmap-validate.py, same directory) runs on the output and its
result is printed. The skeleton MAY fail validation — that is what the
MIGRATE-TODO block and the LLM pass are for. Exit code is the validator's,
except with --dry-run (nothing written, always exit 0).

Stdlib + PyYAML only.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
CHECKBOX_RE = re.compile(r"^\s*[-*]\s*\[([ xX/\-])\]\s+(.*)$")
BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")
LABEL_RE = re.compile(r"^\s*(?:[-*]\s+)?\*\*([A-Za-z][^*\n]{0,60}?)[.:]?\*\*[.:]?\s*(.*)$")
BOLD_LANE_RE = re.compile(r"^(?:\s*[-*]\s+)?(?:[✅❌]\s*)?\*\*(Now|Next|Later)\b")
MOSCOW_RE = re.compile(r"^(?:\s*[-*]\s+)?\*\*(Must|Should|Could|Won'?t)\b")
LANE_HEADING_RE = re.compile(
    r"(?:\b(now|next|later)\b\W*\blanes?\b)|(?:\blanes?\b\W*\b(now|next|later)\b)"
    r"|(?:^\W*(now|next|later)\W*$)",
    re.I,
)
LINK_MD_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
DONE_MARK_RE = re.compile(r"✅|\bCOMPLETED\b|\bDONE\b|\bSHIPPED\b|\bVerdict:?\s*\**\s*(?:YES|NO)\b")
INPROG_MARK_RE = re.compile(r"\bIN[ _-]?PROGRESS\b|\bWIP\b", re.I)
MARK_DATE_RE = re.compile(r"(?:COMPLETED|SHIPPED|DONE)\**\s+(\d{4}-\d{2}-\d{2})")
EST_DAYS_RE = re.compile(r"[≤<]=?\s*(\d+(?:\.\d+)?)\s*(?:person-)?d(?:ays?)?\b")
SIZE_TOKEN_RE = re.compile(r"\b(XL|XS|[SML])\b")
CREATED_RE = re.compile(r"\*\*Created:?\*\*:?\s*(\d{4}-\d{2}-\d{2})")
SLUG_LINE_RE = re.compile(r"\*\*Slug:?\*\*:?\s*`?([a-z0-9-]+)`?")
SP_BULLET_RE = re.compile(r"^\s*[-*]\s+\*{0,2}SP(\d+)\*{0,2}\s*[:—–.\-]?\s*(.*)$")
ASSUMPTION_TIER_RE = re.compile(r"^`?\[?(MUST|SHOULD|COULD|MIGHT)\]?`?\s*[:—–\-]?\s*(.*)$")

ITEM_FIELD_ORDER = [
    "id", "kind", "title", "parent", "summary", "status", "lane", "priority",
    "size", "rice", "estimate_days", "target_start", "target_end", "owner",
    "tags", "acceptance", "depends_on", "links", "proclivity", "origin",
]


def strip_md(s: str) -> str:
    """Remove inline markdown decoration, collapse whitespace."""
    s = LINK_MD_RE.sub(r"\1", s)
    s = s.replace("**", "").replace("`", "").replace("__", "")
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"\1", s)  # *italics*
    return re.sub(r"\s+", " ", s).strip()


def first_sentence(text: str, cap: int = 110) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)
    out = parts[0].strip()
    if len(out) > cap:
        cut = out.rfind(" ", 0, cap)
        out = out[: cut if cut > 40 else cap].rstrip(" ,;:—–-") + "…"
    return out


KEBAB_STOPWORDS = {"the", "a", "an", "to", "of", "in", "on", "for", "with", "and", "is", "are"}


def kebab(text: str, max_words: int = 5) -> str:
    words = re.findall(r"[a-z0-9]+", strip_md(text).lower())
    kept = [w for w in words if w not in KEBAB_STOPWORDS] or words
    return "-".join(kept[:max_words])


STATUS_PREFIX_RE = re.compile(
    r"^(?:✅\s*)?(?:(?:DONE|COMPLETED|SHIPPED)\b|Verdict:?\s*(?:YES|NO)\b)"
    r"[^.·—–]*(?:[.·—–:]\s*|$)"
)


def clean_title_after_id(text: str) -> str:
    """Turn the text trailing an item id into a usable title."""
    t = strip_md(text)
    # Drop leading separators and status segments ("COMPLETED 2026-06-07 ·
    # Verdict: YES (conditional) —" etc.) until real title text starts.
    while True:
        prev = t
        t = re.sub(r"^[\s—–·:.*\-]+", "", t)
        t = STATUS_PREFIX_RE.sub("", t)
        if t == prev:
            return t.strip()


class Migrator:
    def __init__(self, src: Path, text: str, slug: str) -> None:
        self.src = src
        self.slug = slug
        self.fm_project: str | None = None
        self.created: str | None = None
        self.doc_title: str | None = None
        self.title_from_filename = False
        self.lines = self._preprocess(text)
        self.text = "\n".join(self.lines)
        self.headings: list[tuple[int, int, str]] = []  # (line_idx, level, text)
        self.items: dict[str, dict] = {}
        self.goal: dict = {}
        self.todos: list[str] = []
        self.notes: list[str] = []  # verify/informational MIGRATE-TODO entries
        self.consumed: set[int] = set()  # heading indices with extracted content
        self.inferred_parents: list[str] = []
        s = re.escape(slug)
        self.id_res = {
            "epic": re.compile(rf"\b({s}-e(\d+))\b"),
            "milestone": re.compile(rf"\b({s}-m(\d+))\b"),
            "spike": re.compile(rf"\b({s}-spike-(\d+))\b"),
            "task": re.compile(rf"\b({s}-t-[a-z0-9][a-z0-9-]*)\b"),
        }

    # ── preprocessing ─────────────────────────────────────────
    def _preprocess(self, text: str) -> list[str]:
        # Strip YAML frontmatter (capture project:), preserving line count.
        lines = text.splitlines()
        if lines and lines[0].strip() == "---":
            for i in range(1, min(len(lines), 60)):
                m = re.match(r"^project:\s*(\S+)\s*$", lines[i])
                if m:
                    self.fm_project = m.group(1).strip("'\"")
                if lines[i].strip() == "---":
                    lines[: i + 1] = [""] * (i + 1)
                    break
        # Blank out HTML comments and fenced code blocks (line count preserved
        # so origin.src line pointers stay true).
        blanked = "\n".join(lines)
        for pat in (re.compile(r"<!--.*?-->", re.S), re.compile(r"^```.*?^```", re.S | re.M)):
            blanked = pat.sub(lambda m: "\n" * m.group(0).count("\n"), blanked)
        return blanked.splitlines()

    def full_ids_in(self, text: str) -> list[str]:
        found = []
        for rex in self.id_res.values():
            for m in rex.finditer(text):
                if m.group(1) not in found:
                    found.append(m.group(1))
        return found

    def expand_bare_ids(self, text: str) -> list[str]:
        """`e1` / `m2` / `spike-3` -> full slug-prefixed ids (fallback only)."""
        out = []
        for pat, fmt in ((r"\bspike-(\d+)\b", "spike-{}"), (r"\be(\d+)\b", "e{}"),
                         (r"\bm(\d+)\b", "m{}")):
            for m in re.finditer(pat, text):
                fid = f"{self.slug}-{fmt.format(m.group(1))}"
                if fid not in out:
                    out.append(fid)
        return out

    # ── structure ─────────────────────────────────────────────
    def scan_headings(self) -> None:
        for i, line in enumerate(self.lines):
            m = HEADING_RE.match(line)
            if m:
                self.headings.append((i, len(m.group(1)), m.group(2)))
        for _, lvl, text in self.headings:
            if lvl == 1:
                self.doc_title = strip_md(text)
                break
        if not self.doc_title:
            self.doc_title = self.src.stem.replace("-", " ")
            self.title_from_filename = True
        m = CREATED_RE.search(self.text)
        if m:
            self.created = m.group(1)
        m = SLUG_LINE_RE.search(self.text)
        if m and m.group(1) != self.slug:
            print(f"warning: doc declares slug {m.group(1)!r} but --slug is "
                  f"{self.slug!r} — ids will use --slug", file=sys.stderr)

    def section_end(self, h_idx: int, *, strict: bool = False) -> int:
        """Line where heading h_idx's section ends (exclusive).

        strict=False: next heading of level <= this one (item sections).
        strict=True:  next heading of level <  this one (lane-context headings,
        which own same-level sibling item headings)."""
        _, lvl, _ = self.headings[h_idx]
        for j in range(h_idx + 1, len(self.headings)):
            nxt_line, nxt_lvl, _ = self.headings[j]
            if nxt_lvl < lvl or (not strict and nxt_lvl == lvl):
                return nxt_line
        return len(self.lines)

    def consume(self, line_no: int) -> None:
        for j, (i, lvl, _) in enumerate(self.headings):
            if i <= line_no < self.section_end(j):
                self.consumed.add(j)

    # ── items ─────────────────────────────────────────────────
    def ensure_item(self, iid: str, kind: str, line: int, title: str = "",
                    stub: bool = False) -> dict:
        it = self.items.get(iid)
        if it is None:
            it = {
                "id": iid, "kind": kind, "title": title, "_line": line,
                "_stub": stub, "acceptance": [], "depends_on": [], "tags": [],
                "_state": None, "_state_date": None, "_state_src": None,
                "_occ": [], "_title_spike_sec": False,
            }
            self.items[iid] = it
        else:
            if title and not it["title"]:
                it["title"] = title
                it["_stub"] = False
        return it

    def pass_heading_items(self) -> None:
        numbered_e = []
        for _, lvl, t in self.headings:
            if not (2 <= lvl <= 4):
                continue
            m = self.id_res["epic"].search(t)
            if m:
                numbered_e.append(int(m.group(2)))
            else:
                m = re.match(r"^E(\d+)\b", t)
                if m:
                    numbered_e.append(int(m.group(1)))
        next_e = (max(numbered_e) + 1) if numbered_e else 1
        for j, (i, lvl, text) in enumerate(self.headings):
            if not (2 <= lvl <= 4):
                continue
            iid = kind = None
            rest = ""
            for k in ("milestone", "epic", "spike"):
                m = self.id_res[k].search(text)
                if m:
                    iid, kind, rest = m.group(1), k, text[m.end():]
                    break
            if iid is None:
                m = re.match(r"^E(\d+)\b[\s:—–.\-]*(.*)$", text)
                if m:
                    iid, kind, rest = f"{self.slug}-e{m.group(1)}", "epic", m.group(2)
                else:
                    m = re.match(r"^M(\d+)\s*[:.—–\-]\s*(.*)$", text)
                    if m:
                        iid, kind, rest = f"{self.slug}-m{m.group(1)}", "milestone", m.group(2)
                    else:
                        m = re.match(r"^Epic\b[\s:—–.\-]*(.*)$", text)
                        if m:
                            iid, kind, rest = f"{self.slug}-e{next_e}", "epic", m.group(1)
                            next_e += 1
            if iid is None:
                continue
            it = self.ensure_item(iid, kind, i, clean_title_after_id(rest))
            it["_h_idx"] = j
            it["_occ"].append((i, text))
            self.consume(i)

    def in_spike_section(self, line_no: int) -> bool:
        for j, (i, _, text) in enumerate(self.headings):
            if i <= line_no < self.section_end(j) and re.search(r"\bspikes?\b", text, re.I):
                return True
        return False

    def pass_spike_bullets(self) -> None:
        spike_re = self.id_res["spike"]
        for i, line in enumerate(self.lines):
            bm = BULLET_RE.match(line)
            if not bm:
                continue
            m = spike_re.search(line)
            iid = None
            body = ""
            if m:
                iid = m.group(1)
                body = line[m.end():]
            else:
                sp = SP_BULLET_RE.match(line)
                if sp:
                    iid = f"{self.slug}-spike-{sp.group(1)}"
                    body = sp.group(2)
            if iid is None:
                continue
            it = self.ensure_item(iid, "spike", i)
            it["_occ"].append((i, line))
            # Prefer the bullet inside a spike-lane section for title/summary —
            # lane sections describe the spike; other mentions report outcomes.
            in_spike_sec = self.in_spike_section(i)
            t = clean_title_after_id(body)
            if t and "_h_idx" not in it and (
                    not it["title"] or (in_spike_sec and not it["_title_spike_sec"])):
                it["title"] = first_sentence(t)
                it["summary"] = re.sub(r"^[\s—–·:.*\-]+", "", strip_md(body))
                it["_title_spike_sec"] = in_spike_sec
                self.consume(i)

    def item_sections(self) -> list[tuple[str, int, int, int]]:
        """[(item_id, h_line, body_start, body_end)] for heading-defined items."""
        out = []
        for iid, it in self.items.items():
            j = it.get("_h_idx")
            if j is not None:
                h_line = self.headings[j][0]
                out.append((iid, h_line, h_line + 1, self.section_end(j)))
        return out

    def pass_sections(self) -> None:
        sections = self.item_sections()
        # owner of each line = the item whose heading is nearest above it
        owner: dict[int, str] = {}
        for iid, h_line, start, end in sections:
            for ln in range(start, end):
                cur = owner.get(ln)
                if cur is None or self.items[cur]["_line"] < h_line:
                    owner[ln] = iid
        for iid, h_line, start, end in sections:
            it = self.items[iid]
            # structural parent: heading nested inside another item's section
            for oid, oh, ostart, oend in sections:
                if oid != iid and ostart <= h_line < oend:
                    okind = self.items[oid]["kind"]
                    if (it["kind"], okind) in (("milestone", "epic"), ("spike", "epic"),
                                               ("task", "milestone"), ("task", "epic")):
                        it.setdefault("parent", oid)
            ac_mode = False
            summary_pending = False
            prose: list[str] = []
            for ln in range(start, end):
                if owner.get(ln) != iid:
                    continue
                line = self.lines[ln]
                if not line.strip():
                    summary_pending = False
                    continue
                hm = HEADING_RE.match(line)
                if hm:
                    ac_mode = bool(re.search(r"acceptance", hm.group(2), re.I))
                    continue
                cb = CHECKBOX_RE.match(line)
                if cb:
                    state, text = cb.group(1).lower(), cb.group(2).strip()
                    if ac_mode:
                        it["acceptance"].append(text)
                        if state in ("x", "/"):
                            it["_checked_ac"] = it.get("_checked_ac", 0) + 1
                    else:
                        self.add_checkbox_item(state, text, ln, parent=it)
                    self.consume(ln)
                    continue
                lb = LABEL_RE.match(line)
                bm = BULLET_RE.match(line)
                if bm and ac_mode:
                    it["acceptance"].append(bm.group(1).strip())
                    self.consume(ln)
                    continue
                if lb:
                    label, rest = lb.group(1).lower(), lb.group(2).strip()
                    ac_mode = "acceptance" in label
                    if ("description" in label or "outcome" in label) and "summary" not in it:
                        if rest:
                            it["summary"] = strip_md(rest)
                            self.consume(ln)
                        else:
                            summary_pending = True
                    elif "dependencies" in label:
                        deps = self.parse_deps(rest)
                        for d in deps:
                            if d != iid and d not in it["depends_on"]:
                                it["depends_on"].append(d)
                        if deps:
                            self.consume(ln)
                    elif "size" in label or "complexity" in label:
                        sm = SIZE_TOKEN_RE.search(rest)
                        if sm:
                            it["size"] = "S" if sm.group(1) == "XS" else sm.group(1)
                            self.consume(ln)
                    elif label == "type" and rest.split():
                        tag = strip_md(rest).split()[0].lower().strip(".,;")
                        if tag in ("enabler", "value") and tag not in it["tags"]:
                            it["tags"].append(tag)
                            self.consume(ln)
                    elif "status" in label:
                        self.apply_marker_text(it, rest, ln)
                    continue
                if bm and re.match(r"^\**Given\b", bm.group(1)):
                    crit = bm.group(1).strip()
                    if crit not in it["acceptance"]:
                        it["acceptance"].append(crit)
                        self.consume(ln)
                    continue
                if summary_pending and not bm:
                    it["summary"] = strip_md(line)
                    summary_pending = False
                    self.consume(ln)
                    continue
                if not bm and not line.startswith(("|", ">")):
                    prose.append(line.strip())
                if not bm:
                    ac_mode = False
            if "summary" not in it and prose:
                text = strip_md(" ".join(prose))
                if len(text) > 600:
                    text = text[:600].rsplit(" ", 1)[0] + "…"
                if text:
                    it["summary"] = text

    def add_checkbox_item(self, state: str, text: str, line: int, parent: dict | None) -> None:
        """A checkbox outside an acceptance list: task, or embedded known id."""
        embedded = self.full_ids_in(text)
        if embedded:
            for fid in embedded:
                kind = self.kind_of_id(fid)
                it = self.ensure_item(fid, kind, line, stub=True)
                it["_occ"].append((line, text))
                self.apply_checkbox_state(it, state, line)
            return
        tid = f"{self.slug}-t-{kebab(text) or 'item'}"
        base, n = tid, 2
        while tid in self.items and self.items[tid]["_line"] != line:
            tid, n = f"{base}-{n}", n + 1
        it = self.ensure_item(tid, "task", line, strip_md(text))
        if parent is not None and parent["kind"] in ("milestone", "epic"):
            it.setdefault("parent", parent["id"])
        self.apply_checkbox_state(it, state, line)

    def apply_checkbox_state(self, it: dict, state: str, line: int) -> None:
        if state == "x":
            it.update(_state="done", _state_src="checkbox")
        elif state == "/":
            it.update(_state="in_progress", _state_src="checkbox")
        elif state == "-":
            self.notes.append(f"[retire] {it['id']} was a '[-]' checkbox "
                              f"(line {line + 1}) — decide retire vs keep")
        m = MARK_DATE_RE.search(self.lines[line])
        if m:
            it["_state_date"] = m.group(1)

    def kind_of_id(self, fid: str) -> str:
        for k, rex in self.id_res.items():
            if rex.fullmatch(fid):
                return k
        return "task"

    def pass_global_checkboxes(self) -> None:
        """Checkboxes outside every item section become top-level tasks."""
        owned = set()
        for _, _, start, end in self.item_sections():
            owned.update(range(start, end))
        for i, line in enumerate(self.lines):
            if i in owned:
                continue
            cb = CHECKBOX_RE.match(line)
            if cb:
                self.add_checkbox_item(cb.group(1).lower(), cb.group(2).strip(), i, None)
                self.consume(i)

    def parse_deps(self, text: str) -> list[str]:
        t = re.split(r"does\s+not\s+depend|no\s+prior", text, flags=re.I)[0]
        if re.match(r"^\W*none\b", t, re.I):
            return []
        ids = self.full_ids_in(t)
        return ids if ids else self.expand_bare_ids(t)

    # ── lanes, priorities, rice ───────────────────────────────
    def pass_lane_headings(self) -> None:
        for j, (i, lvl, text) in enumerate(self.headings):
            m = LANE_HEADING_RE.search(text)
            if not m:
                continue
            lane = next(g for g in m.groups() if g).lower()
            end = self.section_end(j, strict=True)
            for k in range(j + 1, len(self.headings)):
                nl, _, ntext = self.headings[k]
                if nl >= end:
                    break
                if LANE_HEADING_RE.search(ntext):
                    end = nl
                    break
            hit = False
            for it in self.items.values():
                if i < it["_line"] < end and "lane" not in it:
                    it["lane"] = lane
                    hit = True
            if hit:
                self.consume(i)

    def pass_bold_lanes(self) -> None:
        lane = None
        marker_line = None
        for i, line in enumerate(self.lines):
            if HEADING_RE.match(line):
                lane = None
                continue
            bl = BOLD_LANE_RE.match(line)
            if bl:
                lane = bl.group(1).lower()
                marker_line = i
            elif MOSCOW_RE.match(line):
                lane = None  # a MoSCoW list ends any open lane run
                continue
            if lane is None:
                continue
            for fid in self.full_ids_in(line):
                it = self.items.get(fid) or self.ensure_item(
                    fid, self.kind_of_id(fid), i, stub=True)
                if "lane" not in it:
                    it["lane"] = lane
                    self.consume(marker_line if marker_line is not None else i)
                    self.consume(i)

    def pass_moscow(self) -> None:
        pri_map = {"must": "must", "should": "should", "could": "could",
                   "won't": "wont", "wont": "wont"}
        for i, line in enumerate(self.lines):
            m = MOSCOW_RE.match(line)
            if not m:
                continue
            pri = pri_map[m.group(1).lower()]
            rest = line[m.end():]
            ids = self.full_ids_in(rest)
            if not ids and ":" in rest:
                ids = [f for f in self.expand_bare_ids(rest.split(":", 1)[1])
                       if f in self.items]
            for fid in ids:
                it = self.items.get(fid) or self.ensure_item(
                    fid, self.kind_of_id(fid), i, stub=True)
                if "priority" not in it:
                    it["priority"] = pri
                    self.consume(i)

    def pass_rice_tables(self) -> None:
        header: list[str] | None = None
        col: dict[str, int] = {}
        rank = 0
        for i, line in enumerate(self.lines):
            if not line.strip().startswith("|"):
                header = None
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            low = [c.lower() for c in cells]
            if header is None:
                if any("reach" in c for c in low) and any("impact" in c for c in low) \
                        and any("effort" in c for c in low):
                    header = low
                    col = {}
                    for key, names in (("r", ("reach",)), ("i", ("impact",)),
                                       ("c", ("confidence",)), ("e", ("effort",)),
                                       ("score", ("score",))):
                        for ci, c in enumerate(low):
                            if any(n in c for n in names):
                                col[key] = ci
                                break
                    rank = 0
                continue
            if set("".join(cells)) <= set("-: "):
                continue
            ids = self.full_ids_in(cells[0]) if cells else []
            if not ids:
                continue
            it = self.items.get(ids[0])
            if it is None or "rice" in it:
                continue
            rice: dict = {}
            for key, ci in col.items():
                if ci >= len(cells):
                    continue
                raw = cells[ci].replace("*", "").replace("`", "").strip()
                pm = re.match(r"^(\d+(?:\.\d+)?)\s*%$", raw)
                try:
                    val = float(pm.group(1)) / 100 if pm else float(raw)
                except (ValueError, AttributeError):
                    continue
                rice[key] = int(val) if val == int(val) and key != "c" else round(val, 4)
            if rice:
                rank += 1
                rice["rank"] = rank
                it["rice"] = rice
                self.consume(i)

    # ── completion markers ────────────────────────────────────
    def apply_marker_text(self, it: dict, text: str, line: int) -> None:
        if it["_state"] == "done":
            pass
        elif DONE_MARK_RE.search(text):
            it.update(_state="done", _state_src=it["_state_src"] or "marker")
        elif it["_state"] is None and INPROG_MARK_RE.search(text):
            it.update(_state="in_progress", _state_src="marker")
        m = MARK_DATE_RE.search(text)
        if m and not it["_state_date"]:
            it["_state_date"] = m.group(1)
        if DONE_MARK_RE.search(text) or INPROG_MARK_RE.search(text):
            self.consume(line)

    def pass_completion(self) -> None:
        for it in self.items.values():
            for line_no, text in it["_occ"]:
                self.apply_marker_text(it, text, line_no)
            if it["kind"] == "spike" and it["_state"] is None:
                n = it["id"].rsplit("-", 1)[-1]
                for pat in (rf"\bspike-{n}'s\s+(?:YES|NO)\b",
                            rf"\bspike-{n}\s+ACCEPT'?d\b"):
                    if re.search(pat, self.text):
                        it.update(_state="done", _state_src="marker")
                        break
            if it["kind"] == "spike" and "estimate_days" not in it:
                for _, text in it["_occ"]:
                    m = EST_DAYS_RE.search(text)
                    if m:
                        v = float(m.group(1))
                        it["estimate_days"] = int(v) if v == int(v) else v
                        break

    # ── goal ──────────────────────────────────────────────────
    def goal_section(self, pattern: str) -> tuple[int, int] | None:
        claimed = {it.get("_h_idx") for it in self.items.values()}
        for j, (i, lvl, text) in enumerate(self.headings):
            if lvl < 2 or j in claimed or LANE_HEADING_RE.search(text):
                continue
            if re.search(pattern, text, re.I):
                self.consumed.add(j)
                self.consume(i)
                return i + 1, self.section_end(j)
        return None

    def body_paragraph(self, start: int, end: int) -> str:
        out: list[str] = []
        for ln in range(start, end):
            line = self.lines[ln]
            # A short pure-bold line is a label ("**Key results**"); a LONG
            # fully-bold line is emphasized prose (e.g. a bolded objective).
            if re.match(r"^\*\*[^*]+\*\*:?\s*$", line) and len(line) <= 60:
                break
            if HEADING_RE.match(line) or BULLET_RE.match(line) or \
                    line.startswith(("|", ">")) or re.match(r"^\d+\.\s", line):
                if out:
                    break
                continue
            if line.strip():
                out.append(line.strip())
            elif out:
                break
        return strip_md(" ".join(out))

    def list_items_in(self, start: int, end: int) -> list[str]:
        out = []
        for ln in range(start, end):
            m = re.match(r"^\s*(?:[-*]|\d+\.)\s+(.*)$", self.lines[ln])
            if m and m.group(1).strip():
                out.append(strip_md(m.group(1)))
                self.consume(ln)
        return out

    def pass_goal(self) -> None:
        span = self.goal_section(r"how\s+might\s+we")
        if span:
            hmw = self.body_paragraph(*span)
            if hmw:
                self.goal["hmw"] = hmw
        span = self.goal_section(r"\bobjective\b")
        obj_span = span
        if span:
            obj = self.body_paragraph(*span)
            if obj:
                self.goal["objective"] = obj
        krs: list[str] = []
        span = self.goal_section(r"\bkey\s+results?\b")
        if span:
            krs = self.list_items_in(*span)
        if not krs:
            search = [obj_span] if obj_span else []
            search.append((0, len(self.lines)))
            for s, e in search:
                for ln in range(s, e):
                    if re.match(r"^\*\*Key\s+results?\*\*:?\s*$", self.lines[ln], re.I):
                        krs = self.list_items_in(ln + 1, e)
                        self.consume(ln)
                        break
                if krs:
                    break
        if krs:
            self.goal["key_results"] = krs
        span = self.goal_section(r"\bassumptions?\b")
        if span:
            assumptions = []
            for raw in self.list_items_in(*span):
                m = ASSUMPTION_TIER_RE.match(raw)
                if not m:
                    continue
                tier = {"MUST": "must", "SHOULD": "should",
                        "COULD": "might", "MIGHT": "might"}[m.group(1)]
                body = m.group(2).strip()
                parts = re.split(r"\bvalidation:\s*", body, maxsplit=1, flags=re.I)
                a: dict = {"tier": tier, "text": parts[0].strip(" .;—–-")}
                if len(parts) > 1 and parts[1].strip():
                    a["validation"] = parts[1].strip()
                assumptions.append(a)
            if assumptions:
                self.goal["assumptions"] = assumptions
        span = self.goal_section(r"\bwon'?t\b")
        if span:
            wont = self.list_items_in(*span)
            if wont:
                self.goal["wont"] = wont

    # ── finalize ──────────────────────────────────────────────
    def infer_parents(self) -> None:
        for it in self.items.values():
            if it["kind"] != "milestone" or it.get("parent"):
                continue
            epics = [d for d in it["depends_on"] if self.kind_of_id(d) == "epic"]
            if len(epics) == 1:
                it["parent"] = epics[0]
                it["depends_on"].remove(epics[0])
                self.inferred_parents.append(f"{it['id']} -> {epics[0]}")

    def build_todos(self) -> None:
        add = self.todos.append
        if self.title_from_filename:
            add("[title] roadmap title derived from the filename — set a real one")
        items = self.ordered_items()
        for it in items:
            if not it["title"]:
                it["title"] = "TODO — fill title (migrated stub)"
                add(f"[title] {it['id']} has no parseable title "
                    f"(source line {it['_line'] + 1})")
        for it in items:
            if it["kind"] == "milestone" and not it["acceptance"]:
                add(f"[acceptance] {it['id']} has no acceptance criteria")
            if it["kind"] == "milestone" and "lane" not in it:
                add(f"[lane] {it['id']} has no lane (required at phase: sequenced)")
            if it["kind"] == "task" and it.get("lane") == "now" and not it["acceptance"]:
                add(f"[acceptance] now-lane task {it['id']} needs >=1 criterion")
            if it["_stub"] and it["title"].startswith("TODO"):
                pass  # already covered by the [title] entry
            if it.get("_checked_ac"):
                self.notes.append(f"[verify] {it['id']} had {it['_checked_ac']} "
                                  "checked acceptance box(es) — completion not itemized")
        if not self.goal.get("objective"):
            add("[goal] goal.objective not found (required at phase >= refined)")
        n_kr = len(self.goal.get("key_results") or [])
        if n_kr < 3:
            add(f"[goal] only {n_kr} key_results found (validator requires >= 3)")
        for a in self.goal.get("assumptions") or []:
            if a["tier"] == "must" and not a.get("validation"):
                add(f"[goal] MUST assumption {a['text'][:60]!r}… lacks a validation clause")
        epics = [it for it in items if it["kind"] == "epic"]
        scoped = [e for e in epics if e.get("priority") != "wont"]
        musts = [e for e in scoped if e.get("priority") == "must"]
        if scoped and len(musts) / len(scoped) > 0.60:
            add(f"[priority] must epics {len(musts)}/{len(scoped)} exceed the 60% cap")
        if not items:
            add("[structure] no items parsed at all — check --slug against the doc")
        else:
            if not epics:
                add("[structure] no epics found — group milestones/tasks under "
                    f"{self.slug}-eN epics if desired")
            if not any(it["kind"] == "milestone" for it in items):
                add("[structure] no milestones found — decompose lanes/prose into "
                    f"{self.slug}-mN items")
        if self.inferred_parents:
            self.notes.append("[verify] parent inferred from Dependencies lines: "
                              + ", ".join(self.inferred_parents))
        seeded = [it["id"] for it in items if it["_state"] and it["_state_src"] == "marker"]
        if seeded:
            self.notes.append("[verify] progress events seeded from prose status "
                              "markers (not checkboxes): " + ", ".join(seeded))
        claimed = {it.get("_h_idx") for it in self.items.values()}
        for j, (i, lvl, text) in enumerate(self.headings):
            if lvl < 2 or j in self.consumed or j in claimed:
                continue
            self.notes.append(f"[unmapped] section {strip_md(text)!r} (line {i + 1}) "
                              "not mapped — mine manually")

    def ordered_items(self) -> list[dict]:
        return sorted(self.items.values(), key=lambda it: it["_line"])

    def build_doc(self, project: str) -> dict:
        items_out = []
        for it in self.ordered_items():
            row = {}
            for key in ITEM_FIELD_ORDER:
                if key == "origin":
                    row["origin"] = {"src": f"{self.src.name}:{it['_line'] + 1}"}
                elif key in ("acceptance", "depends_on", "tags"):
                    if it.get(key):
                        row[key] = it[key]
                elif key in it and it[key] not in (None, ""):
                    row[key] = it[key]
            items_out.append(row)
        doc = {
            "schema": "roadmap/1",
            "slug": self.slug,
            "project": project,
            "title": self.doc_title,
            "status": "active",
            "phase": "sequenced",
            "brief": f"Skeleton migrated from {self.src.name} by roadmap-migrate.py; "
                     "resolve the MIGRATE-TODO block, then delete it.",
        }
        if self.goal:
            g = {}
            for key in ("hmw", "objective", "key_results", "assumptions", "wont"):
                if self.goal.get(key):
                    g[key] = self.goal[key]
            doc["goal"] = g
        gb_brief = f"source: {self.src.name}"
        if self.created:
            gb_brief += f" (created {self.created})"
        doc["generated_by"] = {"agent": "roadmap-migrate.py", "brief": gb_brief}
        doc["retired"] = []
        doc["items"] = items_out
        return doc

    def build_events(self, as_of: str) -> list[dict]:
        events = []
        for it in self.ordered_items():
            if it["_state"] not in ("done", "in_progress"):
                continue
            note = ("migrated from legacy checkbox" if it["_state_src"] == "checkbox"
                    else "migrated from legacy status marker")
            events.append({
                "id": it["id"],
                "field": "status",
                "value": it["_state"],
                "at": it["_state_date"] or as_of,
                "actor": "agent",
                "note": note,
            })
        return events

    def run(self) -> None:
        self.scan_headings()
        self.pass_heading_items()
        self.pass_spike_bullets()
        self.pass_sections()
        self.pass_global_checkboxes()
        self.pass_lane_headings()
        self.pass_bold_lanes()
        self.pass_moscow()
        self.pass_rice_tables()
        self.pass_completion()
        self.pass_goal()
        self.infer_parents()
        self.build_todos()


def emit_yaml(doc: dict, todos: list[str], notes: list[str], src_rel: str) -> str:
    body = yaml.dump(doc, sort_keys=False, allow_unicode=True,
                     default_flow_style=False, width=100000)
    lines = [f"# roadmap/1 skeleton migrated from {src_rel} by roadmap-migrate.py."]
    entries = todos + notes
    if entries:
        lines.append("# MIGRATE-TODO: the LLM completion pass must resolve these, then")
        lines.append("#   re-run roadmap-validate.py until it exits 0 and delete this block.")
        for e in entries:
            lines.append(f"#   - {e}")
    else:
        lines.append("# MIGRATE-TODO: none — parsed cleanly; verify content, then delete "
                     "this line.")
    return "\n".join(lines) + "\n" + body


def run_validator(path: Path) -> tuple[int, str]:
    validator = Path(__file__).resolve().parent / "roadmap-validate.py"
    if not validator.exists():
        return 0, f"warning: validator not found at {validator} — skipped"
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    proc = subprocess.run(
        [sys.executable, str(validator), str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.rstrip()


def main() -> int:
    ap = argparse.ArgumentParser(description="migrate a legacy prose roadmap to roadmap/1")
    ap.add_argument("legacy_md", type=Path)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--project", default=None)
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="plans dir to write <slug>/roadmap.yaml under "
                         "(default: the legacy file's directory)")
    ap.add_argument("--as-of", default=None,
                    help="ISO timestamp for seeded journal events "
                         "(default: legacy file mtime)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing roadmap.yaml/agent.jsonl")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the skeleton, write nothing, exit 0")
    args = ap.parse_args()

    if not SLUG_RE.match(args.slug):
        print(f"error: slug {args.slug!r} is not kebab-case", file=sys.stderr)
        return 2
    src = args.legacy_md
    if not src.is_file():
        print(f"error: {src} is not a file", file=sys.stderr)
        return 2
    if args.as_of and not re.match(r"^\d{4}-\d{2}-\d{2}", args.as_of):
        print(f"error: --as-of {args.as_of!r} is not ISO-8601", file=sys.stderr)
        return 2

    mig = Migrator(src, src.read_text(encoding="utf-8-sig"), args.slug)
    mig.run()

    project = args.project or mig.fm_project or src.resolve().parent.parent.name.lower()
    project = re.sub(r"[^a-z0-9-]+", "-", project.lower()).strip("-") or args.slug
    doc = mig.build_doc(project)
    as_of = args.as_of or datetime.datetime.fromtimestamp(
        src.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    events = mig.build_events(as_of)
    yaml_text = emit_yaml(doc, mig.todos, mig.notes, src.name)

    # ── report ────────────────────────────────────────────────
    items = mig.ordered_items()
    by_kind = {k: [it for it in items if it["kind"] == k]
               for k in ("epic", "milestone", "spike", "task")}
    print(f"== roadmap-migrate: {src.name} -> {args.slug} ==")
    print(f"items: {len(by_kind['epic'])} epics, {len(by_kind['milestone'])} milestones, "
          f"{len(by_kind['spike'])} spikes, {len(by_kind['task'])} tasks")
    for it in items:
        bits = [it["kind"]]
        for f in ("parent", "lane", "priority", "size"):
            if it.get(f):
                bits.append(f"{f}={it[f]}")
        if it.get("rice"):
            bits.append("rice")
        if it["acceptance"]:
            bits.append(f"acceptance={len(it['acceptance'])}")
        if it["depends_on"]:
            bits.append(f"deps={len(it['depends_on'])}")
        if it["_state"]:
            bits.append(f"state={it['_state']}")
        print(f"  {it['id']}  ({', '.join(bits)})")
    g = doc.get("goal", {})
    print(f"goal: objective={'yes' if g.get('objective') else 'NO'} "
          f"hmw={'yes' if g.get('hmw') else 'no'} "
          f"key_results={len(g.get('key_results') or [])} "
          f"assumptions={len(g.get('assumptions') or [])} "
          f"wont={len(g.get('wont') or [])}")
    print(f"journal events: {len(events)} "
          f"({sum(1 for e in events if e['value'] == 'done')} done, "
          f"{sum(1 for e in events if e['value'] == 'in_progress')} in_progress)")
    entries = mig.todos + mig.notes
    print(f"MIGRATE-TODO entries: {len(entries)}")
    for e in entries:
        print(f"  - {e}")

    # ── write / dry-run ───────────────────────────────────────
    out_dir = (args.out_dir or src.parent) / args.slug
    roadmap_path = out_dir / "roadmap.yaml"
    journal_path = out_dir / "progress" / "agent.jsonl"
    if args.dry_run:
        print("\n== roadmap.yaml (dry-run) ==")
        print(yaml_text)
        print("== agent.jsonl (dry-run) ==")
        for e in events:
            print(json.dumps(e, ensure_ascii=False))
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", delete=False, encoding="utf-8")
        try:
            tmp.write(yaml_text)
            tmp.close()
            _, out = run_validator(Path(tmp.name))
        finally:
            Path(tmp.name).unlink(missing_ok=True)
        print("== validator ==")
        print(out.replace(tmp.name, "<dry-run>"))
        print("[dry-run] nothing written; exit 0")
        return 0

    for p in (roadmap_path, journal_path):
        if p.exists() and not args.force:
            print(f"error: {p} already exists — pass --force to overwrite",
                  file=sys.stderr)
            return 2
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    (journal_path.parent / ".gitkeep").touch()
    roadmap_path.write_text(yaml_text, encoding="utf-8", newline="\n")
    with open(journal_path, "w", encoding="utf-8", newline="\n") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"wrote {roadmap_path}")
    print(f"wrote {journal_path} ({len(events)} event(s)) + .gitkeep")

    code, out = run_validator(roadmap_path)
    print("== validator ==")
    print(out)
    if code != 0:
        print("validator FAILED — expected for a skeleton; the MIGRATE-TODO block "
              "lists what the LLM pass must fill.")
    return code


if __name__ == "__main__":
    sys.exit(main())

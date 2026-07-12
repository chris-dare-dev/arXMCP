"""
source-truth-spike-2 extractor (fast, regex-based -- avoids full-DOM parse of
multi-MB MathML-laden LaTeXML output).

Counts theorem-like ltx_theorem divs (theorem/lemma/proposition/corollary/
definition ONLY -- excludes proof/remark/notation/acknowledgement/example/etc)
and measures how many have a recoverable printed number from the
ltx_tag_theorem markup.
"""
import json
import re
import sys
from pathlib import Path

repo = Path(r"C:/Users/cedar/Documents/Personal Projects/Source Code/arXMCP")
parsed_root = repo / "var/arxmcp/corpus/parsed"

COUNTED_KEYWORDS = {
    "theorem": "Theorem",
    "thm": "Theorem",
    "lemma": "Lemma",
    "lem": "Lemma",
    "proposition": "Proposition",
    "prop": "Proposition",
    "corollary": "Corollary",
    "cor": "Corollary",
    "definition": "Definition",
    "def": "Definition",
    "defn": "Definition",
}

DIV_OPEN_RE = re.compile(
    r'<div\b(?P<attrs>[^>]*\bclass="[^"]*\bltx_theorem\b[^"]*"[^>]*)>'
)
ATTR_CLASS_RE = re.compile(r'\bclass="([^"]*)"')
ATTR_ID_RE = re.compile(r'\bid="([^"]*)"')

# ltx_tag_theorem span open tag, allow class token order variance
TAG_SPAN_OPEN_RE = re.compile(
    r'<span\b[^>]*\bclass="[^"]*\bltx_tag_theorem\b[^"]*"[^>]*>'
)
TAG_STRIP_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")

LEADING_WORD_RE = re.compile(r"^([A-Za-z][A-Za-z.]*)")

NUMBER_TOKEN_RE = re.compile(
    r"(?:^|[\s(])"
    r"(?P<num>(?:[A-Za-z]\.)?\d+(?:\.\d+)*\'*[a-z]?)"
    r"\.?\)?\s*$"
)


def find_matching_span_text(html, start_pos, window=4000):
    """Find the ltx_tag_theorem span starting at/after start_pos (within window)
    and return its plain text (tags stripped), by balancing span depth."""
    m = TAG_SPAN_OPEN_RE.search(html, start_pos, start_pos + window)
    if not m:
        return None, None
    span_start = m.start()
    # Balance nested <span ...> ... </span> to find the matching close.
    depth = 0
    pos = m.start()
    end = None
    for tag_m in re.finditer(r"<span\b[^>]*>|</span>", html[m.start():m.start() + window]):
        t = tag_m.group(0)
        if t.startswith("</span"):
            depth -= 1
            if depth == 0:
                end = m.start() + tag_m.end()
                break
        else:
            depth += 1
    if end is None:
        return None, None
    raw_inner = html[m.end():end - len("</span>")]
    text = TAG_STRIP_RE.sub("", raw_inner)
    text = WS_RE.sub(" ", text).strip()
    # unescape a few common entities
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#160;", " ")
        .replace("&nbsp;", " ")
    )
    return text, (span_start, end)


def classify_leading_word(text):
    m = LEADING_WORD_RE.match(text.strip())
    if not m:
        return None
    word = m.group(1).rstrip(".").lower()
    return COUNTED_KEYWORDS.get(word)


def extract_number(text):
    stripped = text.strip()
    m = NUMBER_TOKEN_RE.search(stripped)
    if m:
        num = m.group("num")
        if re.search(r"\d", num):
            return num
    return None


def analyze_paper(pid):
    path = parsed_root / pid / "index.html"
    html = path.read_text(encoding="utf-8")

    total_divs = 0
    no_tag_span = 0
    excluded_kinds = {}
    counted = []

    for dm in DIV_OPEN_RE.finditer(html):
        total_divs += 1
        attrs = dm.group("attrs")
        cls_m = ATTR_CLASS_RE.search(attrs)
        id_m = ATTR_ID_RE.search(attrs)
        div_classes = cls_m.group(1) if cls_m else ""
        div_id = id_m.group(1) if id_m else None

        text, span_pos = find_matching_span_text(html, dm.end())
        if text is None:
            no_tag_span += 1
            continue
        kind = classify_leading_word(text)
        if kind is None:
            wm = LEADING_WORD_RE.match(text.strip())
            word = wm.group(1).rstrip(".") if wm else "(empty)"
            excluded_kinds[word] = excluded_kinds.get(word, 0) + 1
            continue
        num = extract_number(text)
        counted.append(
            {
                "div_id": div_id,
                "div_classes": div_classes,
                "tag_text": text,
                "kind": kind,
                "number": num,
            }
        )

    denom = len(counted)
    numer = sum(1 for c in counted if c["number"] is not None)
    return {
        "paper_id": pid,
        "total_ltx_theorem_divs": total_divs,
        "no_tag_span": no_tag_span,
        "excluded_kinds": excluded_kinds,
        "denominator": denom,
        "numerator": numer,
        "coverage_pct": round(100.0 * numer / denom, 1) if denom else None,
        "unnumbered": [c for c in counted if c["number"] is None],
        "counted": counted,
    }


if __name__ == "__main__":
    ids_arg = sys.argv[1:]
    results = []
    for pid in ids_arg:
        try:
            r = analyze_paper(pid)
        except Exception as e:
            import traceback

            r = {"paper_id": pid, "error": f"{e}\n{traceback.format_exc()}"}
        results.append(r)

    for r in results:
        if "error" in r:
            print(f"{r['paper_id']}: ERROR {r['error']}")
            continue
        print(
            f"{r['paper_id']}: denom={r['denominator']} numer={r['numerator']} "
            f"cov={r['coverage_pct']}% total_divs={r['total_ltx_theorem_divs']} "
            f"no_tag_span={r['no_tag_span']} excluded_kinds={r['excluded_kinds']}"
        )
        for u in r["unnumbered"]:
            print(f"    UNNUMBERED: {u['kind']} tag_text={u['tag_text']!r} classes={u['div_classes']}")

    out_path = Path(sys.argv[0]).parent / "results_fast.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {out_path}")

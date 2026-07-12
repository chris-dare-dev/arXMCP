"""
Independent cross-check for source-truth-spike-2 hand validation.

Finds ALL bold-text spans anywhere in the document that LOOK like a
theorem-style label (start with Theorem/Lemma/Proposition/Corollary/
Definition, in either "KEYWORD NUMBER" or "NUMBER. KEYWORD" order), and
reports whether each one falls inside an <div class="ltx_theorem ..."> or
not. This tests whether the denominator itself (based purely on ltx_theorem
divs) is missing real theorem-like statements rendered via a different path.
"""
import re
import sys
from pathlib import Path

repo = Path(r"C:/Users/cedar/Documents/Personal Projects/Source Code/arXMCP")
parsed_root = repo / "var/arxmcp/corpus/parsed"

KEYWORDS = r"(?:Theorem|Lemma|Proposition|Corollary|Definition)"

# Pattern A: "Theorem 3.2" / "Theorem A.2" style (keyword first)
PAT_A = re.compile(
    r'<span[^>]*class="[^"]*ltx_font_bold[^"]*"[^>]*>\s*'
    r'(?P<label>' + KEYWORDS + r'\s+(?:[A-Za-z]\.)?\d+(?:\.\d+)*\.?)'
    r'\s*</span>'
)
# Pattern B: "2.2. Theorem" style (number first, as seen in alg-geom/9606006)
PAT_B = re.compile(
    r'<span[^>]*class="[^"]*ltx_font_bold[^"]*"[^>]*>\s*'
    r'(?P<label>(?:[A-Za-z]\.)?\d+(?:\.\d+)*\.\s*' + KEYWORDS + r')'
    r'\s*</span>'
)

DIV_LTX_THEOREM_RE = re.compile(r'<div\b[^>]*\bclass="[^"]*\bltx_theorem\b[^"]*"[^>]*>')
DIV_ANY_OPEN_RE = re.compile(r'<div\b')
DIV_CLOSE_RE = re.compile(r'</div>')


def find_enclosing_div_classes(html, pos):
    """Walk backward from pos, balance div open/close tags, to find the
    nearest enclosing <div> and report whether it (or an ancestor within
    a short backward scan) has ltx_theorem in its class list.
    Cheap heuristic: look backward for the nearest unmatched <div ...> tag."""
    # Scan backward token by token (div opens/closes) with a bounded window.
    window_start = max(0, pos - 20000)
    segment = html[window_start:pos]
    depth = 0
    nearest_open = None
    # iterate matches in order, track balance from the end
    opens = [(m.start(), m.group(0)) for m in re.finditer(r"<div\b[^>]*>", segment)]
    closes = [m.start() for m in re.finditer(r"</div>", segment)]
    # merge and walk backward
    events = [(s, "open", tag) for s, tag in opens] + [(s, "close", None) for s in closes]
    events.sort(key=lambda e: e[0])
    stack = []
    for s, kind, tag in events:
        if kind == "open":
            stack.append(tag)
        else:
            if stack:
                stack.pop()
    # stack now holds unmatched opens up to pos, nearest is last
    if stack:
        nearest_open = stack[-1]
    return nearest_open


def analyze(pid):
    path = parsed_root / pid / "index.html"
    html = path.read_text(encoding="utf-8")

    hits = []
    for pat, style in [(PAT_A, "kw-first"), (PAT_B, "num-first")]:
        for m in pat.finditer(html):
            hits.append((m.start(), m.group("label").strip(), style))

    hits.sort()
    results = []
    for pos, label, style in hits:
        enclosing = find_enclosing_div_classes(html, pos)
        in_ltx_theorem = bool(enclosing and "ltx_theorem" in enclosing)
        results.append(
            {
                "pos": pos,
                "label": label,
                "style": style,
                "enclosing_div": enclosing,
                "in_ltx_theorem_div": in_ltx_theorem,
            }
        )
    return results


if __name__ == "__main__":
    pid = sys.argv[1]
    results = analyze(pid)
    inside = [r for r in results if r["in_ltx_theorem_div"]]
    outside = [r for r in results if not r["in_ltx_theorem_div"]]
    print(f"{pid}: total bold theorem-like labels found = {len(results)}")
    print(f"  inside ltx_theorem div: {len(inside)}")
    print(f"  OUTSIDE ltx_theorem div (potential MISS): {len(outside)}")
    for r in outside[:60]:
        print(f"    MISS: {r['label']!r} style={r['style']} enclosing={r['enclosing_div']!r}")

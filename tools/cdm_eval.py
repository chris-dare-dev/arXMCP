"""CDM (Character Detection Matching) parser-fidelity eval gate.

T2 spike from capability-scout pdf-ingest-2026. Implements the CDM
algorithm from arXiv:2409.03643 (Wang et al., CVPR 2025) for
evaluating math-formula extraction fidelity. Design-pattern lift from
opendatalab/OmniDocBench (Apache-2.0) per CLAUDE.md §4.7 no-fork rule
— ideas, not code.

Algorithm (4 stages):

1. **Colored token rendering.** Each LaTeX token is assigned a unique
   RGB color from a fixed-interval grid (interval 15, range
   (0,0,15) to (255,255,255) = 5,832 distinct colors). The
   ``\\mathcolor[RGB]{r,g,b}`` macro from the ``xcolor`` package
   wraps each token. Both predicted and ground-truth LaTeX render
   via ``pdflatex`` → ``pdftoppm`` to per-page PNG.
2. **Bbox detection via pixel color matching.** For each assigned
   color, ``numpy.where(image_array == color)`` extracts the exact
   bounding box. Pure NumPy — no edge detection, no
   connected-component analysis. This is the key insight that
   eliminates the OpenCV dependency (and its OpenMP-conflict
   segfault risk on macOS per CLAUDE.md §8 gotcha 1).
3. **Hungarian assignment.** Cost matrix combines token-identity
   cost (Lt), bbox-position cost (Lp), and ordering cost (Lo).
   Solved via ``scipy.optimize.linear_sum_assignment`` (BSD-3-Clause).
4. **F1-Score.** ``CDM = 2 * TP / (2 * TP + FP + FN)``.

Subprocess discipline mirrors :func:`tools.arxiv_fetch.parse_with_latexml`
exactly: ``start_new_session=True`` + ``os.killpg`` on
``TimeoutExpired`` + ``--no-shell-escape`` + ``--interaction=nonstopmode``.
See ``.claude/docs/security-cdm-sandbox.md`` for the full Threat-3
sandbox profile applied to ``pdflatex`` and ``pdftoppm``.

API:

>>> cdm_score(r"\\frac{a}{b}", r"\\frac{a}{b}")  # doctest: +SKIP
1.0
>>> cdm_score(r"\\sum_{i=0}^n x_i", r"\\sum_{i=1}^n x_i")  # doctest: +SKIP
0.875  # one token mismatch in subscript

CLI:

    python -m tools.cdm_eval --fixture tests/eval/textbook_fixtures/
    # → prints aggregate mean/median CDM + per-page table

The pure-Python helpers (color grid generation, LaTeX wrapping,
score computation) work without pdflatex installed; only the
end-to-end ``cdm_score`` rendering path requires the real binaries.
Tests use the ``requires_pdflatex`` pytest marker to gate.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Color-grid interval per CDM paper §3.1. Yields 5,832 distinct
#: colors at interval=15 across (0,0,15)..(255,255,255). Smaller
#: interval = more colors = supports longer formulas; larger
#: interval = safer against PDF anti-aliasing color drift. 15 is
#: the paper's chosen value and works for formulas up to ~5K tokens
#: which exceeds any conceivable math chunk.
_COLOR_INTERVAL: int = 15

#: Maximum number of tokens we can color-code with the interval-15
#: grid. (256 // 15) ** 3 = 17 ** 3 = 4913 (paper claims 5832 via
#: a slightly different grid scheme; we use the safer 17^3 lower
#: bound). If a formula exceeds this, ``cdm_score`` raises
#: RuntimeError rather than producing a garbage answer.
_MAX_TOKENS: int = 4913

#: Subprocess timeout for pdflatex / pdftoppm — chosen per
#: research-synthesis §D2. CDM renders single equations (not full
#: papers), so 30s is generous. Hard kill via os.killpg on the
#: process group if exceeded.
_SUBPROCESS_TIMEOUT_SECONDS: int = 30

#: Render resolution for pdftoppm. 150 DPI is the paper's default;
#: lower = faster but glyphs may anti-alias and blur the unique-color
#: contract; higher = slower with no fidelity gain. 150 is the
#: well-tested baseline.
_RENDER_DPI: int = 150

#: Cost-matrix weights from CDM paper §3.3.
#: Lmatch = Wt * Lt + Wp * Lp + Wo * Lo
_WEIGHT_TOKEN: float = 1.0
_WEIGHT_POSITION: float = 0.5
_WEIGHT_ORDER: float = 0.1

#: Per-token identity cost (Lt). 0 = exact match. 0.05 = same family
#: (e.g. both arithmetic ops); paper uses this for "soft" matches.
#: 1 = different tokens. We collapse to {0, 1} for v0 simplicity —
#: the soft 0.05 tier requires a token-family table the paper builds
#: empirically; out of scope for v0.
_LT_EXACT_MATCH: float = 0.0
_LT_MISMATCH: float = 1.0

#: Token regex — splits a LaTeX formula into atomic tokens. A token
#: is one of: a backslash-command (``\frac``, ``\alpha``), a single
#: character (digits, letters, operators), or a paired-delimiter
#: group treated atomically (``{...}``, ``[...]`` — handled by
#: nested-token splitting rather than greedy match).
_LATEX_TOKEN_RE: re.Pattern[str] = re.compile(
    r"\\[a-zA-Z]+|\\[^a-zA-Z]|[a-zA-Z0-9]|[^a-zA-Z0-9\s\\]"
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TokenBbox:
    """A LaTeX token with its assigned color and detected bbox.

    Attributes
    ----------
    token : str
        The LaTeX token text (e.g. ``\\frac``, ``a``, ``+``).
    index : int
        Position in the formula (0-indexed).
    color : tuple[int, int, int]
        RGB color assigned via the interval-15 grid.
    bbox : tuple[int, int, int, int] | None
        (row_min, col_min, row_max, col_max) in image-pixel
        coordinates, or None if the token was not detected in the
        render (which means the LaTeX did not produce a glyph for
        this token — typically a syntactic-only token like a brace).
    """

    token: str
    index: int
    color: tuple[int, int, int]
    bbox: tuple[int, int, int, int] | None = None


@dataclass
class CDMResult:
    """Output of :func:`cdm_score`. Includes the F1 score plus the
    per-token assignment details for debugging.

    Attributes
    ----------
    score : float
        CDM F1 score in [0, 1].
    true_positives : int
    false_positives : int
    false_negatives : int
    predicted_tokens : list[TokenBbox]
    ground_truth_tokens : list[TokenBbox]
    matches : list[tuple[int, int]]
        List of (pred_idx, gt_idx) for each matched pair.
    """

    score: float
    true_positives: int
    false_positives: int
    false_negatives: int
    predicted_tokens: list[TokenBbox] = field(default_factory=list)
    ground_truth_tokens: list[TokenBbox] = field(default_factory=list)
    matches: list[tuple[int, int]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pure-Python helpers (no subprocess required)
# ---------------------------------------------------------------------------


def tokenize_latex(formula: str) -> list[str]:
    """Split a LaTeX formula into atomic tokens for CDM.

    The CDM contract is that each "token" gets a unique color. We
    split on:
    - ``\\name`` backslash-commands (``\\frac``, ``\\alpha``,
      ``\\sum``, ...)
    - ``\\X`` single-char backslash escapes (``\\,``, ``\\!``,
      ``\\{``, ...)
    - Single alphanumeric chars (``a``, ``1``, ``X``, ...)
    - Single non-alphanumeric non-whitespace chars (``+``, ``=``,
      ``{``, ``}``, ``^``, ``_``, ...)

    Whitespace tokens are dropped (the renderer collapses them).

    >>> tokenize_latex(r"\\frac{a}{b}")
    ['\\\\frac', '{', 'a', '}', '{', 'b', '}']
    >>> tokenize_latex(r"\\sum_{i=0}^n x_i")
    ['\\\\sum', '_', '{', 'i', '=', '0', '}', '^', 'n', 'x', '_', 'i']
    """
    return _LATEX_TOKEN_RE.findall(formula)


def color_grid(n_colors: int, interval: int = _COLOR_INTERVAL) -> list[tuple[int, int, int]]:
    """Generate the first ``n_colors`` colors from the interval-N RGB
    grid used by CDM. Colors are in lexicographic order (r asc, then
    g asc, then b asc). The starting color (0,0,0) is skipped because
    black is also the default ink color and would alias with the
    actual formula glyphs.

    >>> color_grid(3)
    [(0, 0, 15), (0, 0, 30), (0, 0, 45)]
    >>> len(color_grid(100))
    100
    """
    if n_colors < 1:
        raise RuntimeError(f"color_grid: n_colors must be >= 1, got {n_colors}")
    if n_colors > _MAX_TOKENS:
        raise RuntimeError(
            f"color_grid: n_colors={n_colors} exceeds the interval-"
            f"{interval} grid capacity of {_MAX_TOKENS}. Formulas this "
            "long are outside the CDM design envelope."
        )
    colors: list[tuple[int, int, int]] = []
    for r in range(0, 256, interval):
        for g in range(0, 256, interval):
            for b in range(0, 256, interval):
                if r == 0 and g == 0 and b == 0:
                    continue  # skip pure black — aliases with ink
                colors.append((r, g, b))
                if len(colors) == n_colors:
                    return colors
    # Unreachable given _MAX_TOKENS guard above; defensive.
    raise RuntimeError(
        f"color_grid: exhausted grid before reaching {n_colors} colors"
    )


def wrap_formula_latex(
    formula: str, *, colored: bool = True
) -> str:
    """Wrap a math formula in a minimal standalone LaTeX document.

    The wrapper includes ``\\usepackage[x11names]{xcolor}`` for the
    ``\\mathcolor[RGB]{r,g,b}{...}`` macro and ``amsmath`` for
    extended math operators. The formula is rendered inside
    ``\\[ ... \\]`` (display math).

    When ``colored=True``, each token from :func:`tokenize_latex` is
    wrapped with a unique color from :func:`color_grid` for bbox
    detection.

    When ``colored=False``, the formula renders as-is in black —
    useful for human inspection / sanity-checking the fixture pages.
    """
    if colored:
        tokens = tokenize_latex(formula)
        if not tokens:
            raise RuntimeError(
                f"wrap_formula_latex: tokenize_latex returned no tokens "
                f"for {formula!r}"
            )
        colors = color_grid(len(tokens))
        body_parts: list[str] = []
        for token, color in zip(tokens, colors, strict=True):
            r, g, b = color
            # \mathcolor wraps the token in the assigned color.
            body_parts.append(f"\\mathcolor[RGB]{{{r},{g},{b}}}{{{token}}}")
        body = "".join(body_parts)
    else:
        body = formula
    return (
        "\\documentclass[12pt]{standalone}\n"
        "\\usepackage[x11names]{xcolor}\n"
        "\\usepackage{amsmath,amssymb}\n"
        "\\begin{document}\n"
        f"\\[ {body} \\]\n"
        "\\end{document}\n"
    )


# ---------------------------------------------------------------------------
# Subprocess discipline (pdflatex + pdftoppm)
# ---------------------------------------------------------------------------


def _run_subprocess_with_pgkill(
    cmd: Sequence[str],
    *,
    cwd: Path,
    timeout: int = _SUBPROCESS_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with the Threat-3 sandbox profile.

    Mirrors :func:`tools.arxiv_fetch.parse_with_latexml`'s discipline:
    ``start_new_session=True`` puts the child in its own process
    group; on ``TimeoutExpired`` we ``os.killpg`` the whole group so
    no orphaned descendants survive (pdflatex commonly spawns
    sub-binaries for font handling that would outlive a bare
    ``proc.kill()``).

    Per CLAUDE.md §4.7: ``assert`` is banned for invariants — bad
    inputs raise RuntimeError explicitly.
    """
    if not cmd:
        raise RuntimeError("_run_subprocess_with_pgkill: empty cmd")
    proc = subprocess.Popen(
        list(cmd),
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, OSError) as e:
            logger.warning(
                "failed to killpg pid=%d after timeout: %s", proc.pid, e,
            )
        proc.wait()
        raise
    return subprocess.CompletedProcess(
        args=list(cmd), returncode=proc.returncode,
        stdout=stdout, stderr=stderr,
    )


def render_latex_to_image(
    latex_doc: str, *, work_dir: Path | None = None,
) -> np.ndarray:
    """Render a full LaTeX document → PNG → numpy RGB array.

    Pipeline: pdflatex (with --no-shell-escape, --interaction=nonstopmode)
    → pdftoppm (poppler-utils) → load PNG with NumPy (via Pillow).

    Pillow is a transitive dep (via transformers / mcp); not declared
    explicitly. If the import fails the test harness skips gracefully
    via the ``requires_pdflatex`` marker (which already requires the
    binaries; Pillow is typically co-present).

    Returns
    -------
    np.ndarray of shape (H, W, 3), dtype uint8, RGB order.

    Raises
    ------
    RuntimeError
        If pdflatex or pdftoppm exits non-zero, if the output PNG is
        empty, or if the binaries are missing on PATH.
    subprocess.TimeoutExpired
        If either subprocess exceeds _SUBPROCESS_TIMEOUT_SECONDS.
    """
    pdflatex = shutil.which("pdflatex")
    pdftoppm = shutil.which("pdftoppm")
    if pdflatex is None:
        raise RuntimeError(
            "render_latex_to_image: pdflatex not on PATH. Install via "
            "`brew install --cask mactex-no-gui` (macOS) or "
            "`apt install texlive-base` (Debian/Ubuntu)."
        )
    if pdftoppm is None:
        raise RuntimeError(
            "render_latex_to_image: pdftoppm not on PATH. Install via "
            "`brew install poppler` (macOS) or "
            "`apt install poppler-utils` (Debian/Ubuntu)."
        )

    # Use a context-managed TMPDIR so the sandbox boundary is the OS-
    # provided per-process temp dir. work_dir override is for tests.
    if work_dir is None:
        ctx = tempfile.TemporaryDirectory(prefix="cdm_eval_")
        work = Path(ctx.name)
        owns_dir = True
    else:
        ctx = None
        work = work_dir
        work.mkdir(parents=True, exist_ok=True)
        owns_dir = False

    try:
        tex_path = work / "formula.tex"
        tex_path.write_text(latex_doc, encoding="utf-8")

        # Stage 1: pdflatex → PDF
        result = _run_subprocess_with_pgkill(
            [
                pdflatex,
                "--no-shell-escape",
                "--interaction=nonstopmode",
                "-output-directory", str(work),
                str(tex_path),
            ],
            cwd=work,
        )
        if result.returncode != 0:
            # Surface a useful tail of the pdflatex log without dumping
            # the entire (often huge) error report.
            log_tail = result.stdout[-500:] if result.stdout else ""
            raise RuntimeError(
                f"pdflatex failed (exit {result.returncode}). "
                f"Last 500 chars of stdout: {log_tail!r}"
            )

        pdf_path = work / "formula.pdf"
        if not pdf_path.is_file():
            raise RuntimeError(
                f"pdflatex succeeded (exit 0) but no PDF at {pdf_path}"
            )

        # Stage 2: pdftoppm → PNG
        png_prefix = work / "formula"
        result = _run_subprocess_with_pgkill(
            [
                pdftoppm,
                "-r", str(_RENDER_DPI),
                "-png",
                str(pdf_path),
                str(png_prefix),
            ],
            cwd=work,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"pdftoppm failed (exit {result.returncode}). "
                f"stderr: {result.stderr[-500:]!r}"
            )

        # pdftoppm names the output formula-1.png (page 1).
        png_path = work / "formula-1.png"
        if not png_path.is_file():
            # Try the no-page-number form (single-page heuristic).
            png_path = work / "formula.png"
            if not png_path.is_file():
                raise RuntimeError(
                    f"pdftoppm succeeded but no PNG at {work}/formula-*.png"
                )

        # Stage 3: PNG → numpy RGB array (via Pillow)
        try:
            from PIL import Image
        except ImportError as e:
            raise RuntimeError(
                "render_latex_to_image: Pillow not importable — it is "
                "typically a transitive dep but the env appears broken"
            ) from e
        with Image.open(png_path) as img:
            arr = np.asarray(img.convert("RGB"))
        if arr.size == 0:
            raise RuntimeError(f"loaded PNG is empty: {png_path}")
        return arr
    finally:
        if owns_dir and ctx is not None:
            ctx.cleanup()


# ---------------------------------------------------------------------------
# Bbox detection (pure NumPy)
# ---------------------------------------------------------------------------


def detect_bbox(
    image: np.ndarray, color: tuple[int, int, int],
    *, color_tolerance: int = 3,
) -> tuple[int, int, int, int] | None:
    """Find the bounding box of pixels matching ``color`` in ``image``.

    Tolerance accounts for anti-aliasing / sub-pixel rendering: a
    "matching" pixel is one whose channel-wise distance from
    ``color`` is ≤ ``color_tolerance`` in each of R/G/B. With
    interval-15 colors and tolerance-3, neighboring grid points are
    still distinguishable (their channel separation is 15 > 2*3+1).

    Returns
    -------
    (row_min, col_min, row_max, col_max) or None if no matching
    pixels found (which is normal for tokens that don't produce
    glyphs — braces, spaces, etc.).
    """
    if image.ndim != 3 or image.shape[2] != 3:
        raise RuntimeError(
            f"detect_bbox: expected HxWx3 RGB array, got shape {image.shape}"
        )
    target = np.asarray(color, dtype=np.int16)  # signed to allow negative diffs
    # Per-channel absolute distance ≤ tolerance, all channels must satisfy.
    diff = np.abs(image.astype(np.int16) - target)
    mask = (diff <= color_tolerance).all(axis=2)
    if not mask.any():
        return None
    rows, cols = np.where(mask)
    return (int(rows.min()), int(cols.min()), int(rows.max()), int(cols.max()))


def detect_all_bboxes(
    image: np.ndarray, tokens: list[TokenBbox],
    *, color_tolerance: int = 3,
) -> list[TokenBbox]:
    """Apply :func:`detect_bbox` to each token's assigned color.

    Returns a NEW list of TokenBbox with the ``bbox`` field
    populated (or None for tokens without detectable glyphs).
    """
    out: list[TokenBbox] = []
    for tok in tokens:
        bbox = detect_bbox(image, tok.color, color_tolerance=color_tolerance)
        out.append(
            TokenBbox(token=tok.token, index=tok.index, color=tok.color, bbox=bbox)
        )
    return out


# ---------------------------------------------------------------------------
# Cost matrix + Hungarian assignment + F1
# ---------------------------------------------------------------------------


def _normalize_bbox(
    bbox: tuple[int, int, int, int], image_shape: tuple[int, int, int],
) -> tuple[float, float, float, float]:
    """Normalize bbox to [0, 1] per image dimension. Center + width/height."""
    h, w = image_shape[:2]
    rmin, cmin, rmax, cmax = bbox
    cy = (rmin + rmax) / 2 / max(h, 1)
    cx = (cmin + cmax) / 2 / max(w, 1)
    bh = (rmax - rmin) / max(h, 1)
    bw = (cmax - cmin) / max(w, 1)
    return (cy, cx, bh, bw)


def _cost_matrix(
    predicted: Sequence[TokenBbox], ground_truth: Sequence[TokenBbox],
    *, pred_img_shape: tuple[int, int, int],
    gt_img_shape: tuple[int, int, int],
) -> np.ndarray:
    """Build the M×N cost matrix per CDM paper §3.3.

    Tokens without bboxes (None) are skipped from the matrix — they
    contribute neither TP nor FP/FN.
    """
    # Restrict to tokens with detected bboxes.
    pred_visible = [t for t in predicted if t.bbox is not None]
    gt_visible = [t for t in ground_truth if t.bbox is not None]
    m, n = len(pred_visible), len(gt_visible)
    if m == 0 or n == 0:
        return np.zeros((m, n), dtype=np.float64)
    cost = np.zeros((m, n), dtype=np.float64)
    for i, p in enumerate(pred_visible):
        p_norm = _normalize_bbox(p.bbox, pred_img_shape)  # type: ignore[arg-type]
        for j, g in enumerate(gt_visible):
            g_norm = _normalize_bbox(g.bbox, gt_img_shape)  # type: ignore[arg-type]
            # Lt — token identity (0 = exact match; 1 = mismatch)
            lt = _LT_EXACT_MATCH if p.token == g.token else _LT_MISMATCH
            # Lp — L1 distance between normalized bbox features
            lp = float(sum(abs(a - b) for a, b in zip(p_norm, g_norm, strict=True)))
            # Lo — normalized ordering distance
            lo = abs(p.index / max(m, 1) - g.index / max(n, 1))
            cost[i, j] = (
                _WEIGHT_TOKEN * lt
                + _WEIGHT_POSITION * lp
                + _WEIGHT_ORDER * lo
            )
    return cost


def cdm_score(
    predicted_latex: str, ground_truth_latex: str,
    *, work_dir: Path | None = None,
    cost_threshold: float = 0.5,
) -> CDMResult:
    """Compute the CDM F1 score between predicted and ground-truth LaTeX.

    A match is "correct" (true positive) when its assignment cost is
    ≤ ``cost_threshold``. The paper recommends 0.5 as the threshold
    (with default weights Wt=1.0, Wp=0.5, Wo=0.1, an exact-token
    match with small position drift stays under 0.5).

    Parameters
    ----------
    predicted_latex : str
        The parser-emitted LaTeX formula to evaluate.
    ground_truth_latex : str
        The reference LaTeX formula.
    work_dir : Path | None
        Optional working directory for pdflatex output. If None
        (default), uses a fresh TemporaryDirectory that is cleaned
        up on return.
    cost_threshold : float
        Maximum assignment cost for a match to count as TP. Default
        0.5 per CDM paper.

    Returns
    -------
    CDMResult with the F1 score in [0, 1] plus the per-token
    assignment details.

    Raises
    ------
    RuntimeError
        Bad inputs, missing binaries, render failures.
    subprocess.TimeoutExpired
        Either subprocess exceeded the 30s timeout.
    """
    if not predicted_latex.strip():
        raise RuntimeError("cdm_score: predicted_latex is empty")
    if not ground_truth_latex.strip():
        raise RuntimeError("cdm_score: ground_truth_latex is empty")

    # Tokenize + color-grid both inputs.
    pred_tokens_text = tokenize_latex(predicted_latex)
    gt_tokens_text = tokenize_latex(ground_truth_latex)
    pred_colors = color_grid(len(pred_tokens_text))
    gt_colors = color_grid(len(gt_tokens_text))
    pred_tokens = [
        TokenBbox(token=t, index=i, color=c)
        for i, (t, c) in enumerate(zip(pred_tokens_text, pred_colors, strict=True))
    ]
    gt_tokens = [
        TokenBbox(token=t, index=i, color=c)
        for i, (t, c) in enumerate(zip(gt_tokens_text, gt_colors, strict=True))
    ]

    # Render both colored documents to images.
    pred_doc = wrap_formula_latex(predicted_latex, colored=True)
    gt_doc = wrap_formula_latex(ground_truth_latex, colored=True)
    pred_image = render_latex_to_image(pred_doc, work_dir=work_dir)
    gt_image = render_latex_to_image(gt_doc, work_dir=work_dir)

    # Detect bboxes via color matching.
    pred_with_bboxes = detect_all_bboxes(pred_image, pred_tokens)
    gt_with_bboxes = detect_all_bboxes(gt_image, gt_tokens)

    # Build cost matrix + run Hungarian.
    cost = _cost_matrix(
        pred_with_bboxes, gt_with_bboxes,
        pred_img_shape=pred_image.shape,
        gt_img_shape=gt_image.shape,
    )
    pred_visible = [t for t in pred_with_bboxes if t.bbox is not None]
    gt_visible = [t for t in gt_with_bboxes if t.bbox is not None]
    m, n = len(pred_visible), len(gt_visible)
    if m == 0 and n == 0:
        # Both formulas have zero visible glyphs — trivially perfect.
        return CDMResult(
            score=1.0, true_positives=0, false_positives=0, false_negatives=0,
            predicted_tokens=pred_with_bboxes, ground_truth_tokens=gt_with_bboxes,
        )
    matches: list[tuple[int, int]] = []
    tp = 0
    if m > 0 and n > 0:
        row_ind, col_ind = linear_sum_assignment(cost)
        for i, j in zip(row_ind, col_ind, strict=True):
            if cost[i, j] <= cost_threshold:
                matches.append((int(i), int(j)))
                tp += 1
    fp = m - tp
    fn = n - tp
    if tp == 0 and (fp > 0 or fn > 0):
        score = 0.0
    elif tp == 0:
        score = 1.0  # already handled above; defensive
    else:
        score = 2 * tp / (2 * tp + fp + fn)
    return CDMResult(
        score=float(score),
        true_positives=tp, false_positives=fp, false_negatives=fn,
        predicted_tokens=pred_with_bboxes, ground_truth_tokens=gt_with_bboxes,
        matches=matches,
    )


# ---------------------------------------------------------------------------
# Aggregate scoring (fixture-level + CLI)
# ---------------------------------------------------------------------------


def aggregate_cdm(
    pairs: Iterable[tuple[str, str]], *, work_dir: Path | None = None,
) -> tuple[float, list[float]]:
    """Score every (predicted, ground_truth) pair; return (mean, per-pair).

    Pairs that raise during rendering are scored 0.0 with a warning
    logged — the fixture should be cleaned before scoring, but a
    single bad page should not abort the entire eval pass.
    """
    scores: list[float] = []
    for pred, gt in pairs:
        try:
            result = cdm_score(pred, gt, work_dir=work_dir)
            scores.append(result.score)
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            logger.warning("cdm_score failed for pair: %s", e)
            scores.append(0.0)
    if not scores:
        return (0.0, [])
    return (float(sum(scores) / len(scores)), scores)


__all__ = [
    "CDMResult",
    "TokenBbox",
    "aggregate_cdm",
    "cdm_score",
    "color_grid",
    "detect_all_bboxes",
    "detect_bbox",
    "render_latex_to_image",
    "tokenize_latex",
    "wrap_formula_latex",
]

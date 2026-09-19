/**
 * Math-rendering fixture page (AC-B.24): 20+ mixed inline/display
 * formulas from the corpus's target categories (math.AG, math.NT,
 * math-ph, hep-th) rendered through the chunk-surface track
 * (MathText → KaTeX), asserted by e2e to produce ZERO console errors.
 *
 * The stored-document track (LaTeXML MathML under script-src 'none')
 * is exercised by e2e/mathml-spike.spec.ts against the real preview
 * CSP; this page documents the split and links the entry points so
 * the two-track decision is legible in the product, not just in the
 * pipeline reports.
 */
import { MathText } from "../math/MathText";

/** Each entry is one editorial paragraph; $…$ inline, $$…$$ display —
 * 29 formulas total (23 inline + 6 display; AC-B.24 asks for 20 mixed). */
const FIXTURE_PARAGRAPHS: string[] = [
  // math.AG — stability conditions (the bridgeland-stability notebook)
  "A stability condition $\\sigma = (Z, \\mathcal{P})$ on a triangulated " +
    "category $D$ consists of a central charge $Z : K(D) \\to \\mathbb{C}$ " +
    "and full additive subcategories $\\mathcal{P}(\\phi)$ satisfying the " +
    "Harder–Narasimhan axioms.",
  "The Bogomolov inequality bounds the discriminant of a $\\mu$-semistable " +
    "sheaf $E$ on a smooth projective surface: " +
    "$$\\Delta(E) = 2 r c_2(E) - (r-1) c_1(E)^2 \\ge 0.$$",
  "For objects $E, F$ in the heart of a bounded t-structure the Euler " +
    "pairing $\\chi(E, F) = \\sum_i (-1)^i \\dim \\operatorname{Hom}(E, F[i])$ " +
    "descends to the numerical Grothendieck group.",
  // math.NT
  "The completed zeta function $\\xi(s) = \\pi^{-s/2} \\Gamma(s/2) \\zeta(s)$ " +
    "satisfies the functional equation $\\xi(s) = \\xi(1-s)$, and the " +
    "critical strip is $0 < \\operatorname{Re}(s) < 1$.",
  "$$\\zeta(s) = \\prod_{p \\text{ prime}} \\frac{1}{1 - p^{-s}}, " +
    "\\qquad \\operatorname{Re}(s) > 1.$$",
  "By quadratic reciprocity, for distinct odd primes $p$ and $q$: " +
    "$$\\left(\\frac{p}{q}\\right)\\left(\\frac{q}{p}\\right) = " +
    "(-1)^{\\frac{p-1}{2}\\cdot\\frac{q-1}{2}}.$$",
  // math-ph
  "The commutation relation $[\\hat{x}, \\hat{p}] = i\\hbar$ implies the " +
    "uncertainty bound $\\Delta x \\, \\Delta p \\ge \\hbar/2$ via the " +
    "Cauchy–Schwarz inequality $|\\langle u, v\\rangle|^2 \\le " +
    "\\langle u,u\\rangle \\langle v,v\\rangle$.",
  "$$i\\hbar \\frac{\\partial}{\\partial t} \\Psi(x, t) = " +
    "\\left(-\\frac{\\hbar^2}{2m} \\nabla^2 + V(x)\\right) \\Psi(x, t)$$",
  "The partition function $Z = \\operatorname{tr}\\, e^{-\\beta H}$ " +
    "generates thermal expectation values through " +
    "$\\langle A \\rangle = Z^{-1} \\operatorname{tr}(A\\, e^{-\\beta H})$.",
  // hep-th
  "The Yang–Mills action with coupling $g$ reads " +
    "$$S = -\\frac{1}{4 g^2} \\int d^4x \\, F^{a}_{\\mu\\nu} F^{a\\,\\mu\\nu}, " +
    "\\qquad F^{a}_{\\mu\\nu} = \\partial_\\mu A^a_\\nu - \\partial_\\nu A^a_\\mu " +
    "+ f^{abc} A^b_\\mu A^c_\\nu.$$",
  "In the AdS/CFT correspondence the bulk partition function with boundary " +
    "condition $\\phi_0$ equals the generating functional " +
    "$\\langle e^{\\int \\phi_0 \\mathcal{O}} \\rangle_{\\mathrm{CFT}}$.",
  // Fourier duality (the fourier-duality notebook)
  "The Fourier transform $\\hat{f}(\\xi) = \\int_{\\mathbb{R}^n} f(x) " +
    "e^{-2\\pi i x \\cdot \\xi} \\, dx$ interchanges translation and " +
    "modulation; Plancherel gives $\\|f\\|_2 = \\|\\hat{f}\\|_2$.",
  "$$\\sum_{n \\in \\mathbb{Z}} f(n) = \\sum_{k \\in \\mathbb{Z}} \\hat{f}(k)$$",
  "A Fourier–Mukai transform $\\Phi_{\\mathcal{K}} : D^b(X) \\to D^b(Y)$ " +
    "with kernel $\\mathcal{K} \\in D^b(X \\times Y)$ is " +
    "$\\Phi_{\\mathcal{K}}(E) = R\\pi_{Y*}(\\pi_X^* E " +
    "\\otimes^{L} \\mathcal{K})$.",
  "Deliberately malformed TeX renders as literal source, never a crash: " +
    "$\\frac{1}{$ (KaTeX throwOnError: false).",
];

export function MathFixturePage() {
  return (
    <article aria-labelledby="mathfix-h">
      <div className="section-header">
        <h2 id="mathfix-h">Math rendering fixture</h2>
      </div>

      <p className="reg-editorial">
        Two-track rendering (D7): chunk and discovery surfaces carry math as
        TeX strings and render through self-hosted KaTeX (this page); stored
        paper documents carry LaTeXML MathML and render natively under a
        zero-JS preview CSP — open any stored copy from a notebook&rsquo;s
        papers table to see that track.
      </p>

      <div data-testid="math-fixture-body">
        {FIXTURE_PARAGRAPHS.map((text, i) => (
          // eslint-disable-next-line react/no-array-index-key -- static fixture list
          <p className="reg-editorial" key={i}>
            <MathText text={text} />
          </p>
        ))}
      </div>
    </article>
  );
}

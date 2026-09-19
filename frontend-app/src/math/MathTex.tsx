/**
 * MathTex — KaTeX track of the two-track math-rendering decision (D7).
 *
 * Chunk/retrieval surfaces store math as `$TeX$` inside body_text
 * (211 R-D), so they render through synchronous KaTeX with self-hosted
 * fonts (katex CSS + woff2 flow into dist/assets under font-src
 * 'self'). Stored-document surfaces use the OTHER track: native
 * MathML Core, verified by the render spike (e2e/mathml-spike).
 *
 * KaTeX output uses the editorial math face conventions (MR-1):
 * .katex inherits sizing from the editorial register container.
 */
import katex from "katex";
import "katex/dist/katex.min.css";
import { useMemo } from "react";

interface MathTexProps {
  /** TeX source WITHOUT delimiters. */
  tex: string;
  display?: boolean;
}

export function MathTex({ tex, display = false }: MathTexProps) {
  const html = useMemo(
    () =>
      katex.renderToString(tex, {
        displayMode: display,
        throwOnError: false, // corpus TeX is not under our control
        // KaTeX's default errorColor (#cc0000) is an inline literal
        // that fails AA on the warm-dark paper; currentColor keeps
        // malformed TeX (rendered as literal source, title = error)
        // in the inherited ink — AA in both modes by construction.
        errorColor: "currentColor",
        output: "htmlAndMathml",
      }),
    [tex, display],
  );
  return (
    <span
      className="reg-math"
      // KaTeX escapes its own output; throwOnError:false renders bad
      // TeX as literal source in an error span rather than throwing.
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

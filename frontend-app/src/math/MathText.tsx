/**
 * MathText — editorial prose with embedded `$TeX$` / `$$TeX$$`
 * segments, the chunk-surface half of the two-track math decision
 * (D7 / 211 R-D, verdict recorded in the arx-b1 report):
 *
 *  - chunk/retrieval/discovery strings carry math as $TeX$ inside
 *    plain text → KaTeX (this component, via MathTex);
 *  - stored-document surfaces (paper preview) carry LaTeXML MathML →
 *    rendered natively by MathML Core with ZERO page JS under the
 *    preview CSP (script-src 'none') — the spike-verified track; the
 *    SPA only links there (PapersTable "stored copy" column).
 *
 * KaTeX is heavy (~120 kB gzip + fonts CSS), so MathTex is
 * lazy-loaded: prose without any TeX renders synchronously and never
 * pays the chunk; the Suspense fallback shows the raw text (with
 * delimiters) until KaTeX lands — honest, brief, and layout-stable
 * for inline segments.
 */
import { Fragment, lazy, Suspense, useMemo } from "react";

const LazyMathTex = lazy(() =>
  import("./MathTex").then((m) => ({ default: m.MathTex })),
);

export interface TexSegment {
  type: "text" | "inline" | "display";
  value: string;
}

// $$…$$ first (display), then $…$ (inline). Lookbehinds keep escaped
// \$ literal. Inline segments must be non-empty and $-free.
const TEX_SEGMENT_RE =
  /(?<!\\)\$\$([\s\S]+?)(?<!\\)\$\$|(?<!\\)\$([^$]+?)(?<!\\)\$/g;

export function splitTexSegments(text: string): TexSegment[] {
  const segments: TexSegment[] = [];
  let cursor = 0;
  TEX_SEGMENT_RE.lastIndex = 0;
  for (const m of text.matchAll(TEX_SEGMENT_RE)) {
    const index = m.index ?? 0;
    if (index > cursor) {
      segments.push({ type: "text", value: text.slice(cursor, index) });
    }
    if (m[1] !== undefined) {
      segments.push({ type: "display", value: m[1] });
    } else {
      segments.push({ type: "inline", value: m[2] });
    }
    cursor = index + m[0].length;
  }
  if (cursor < text.length) {
    segments.push({ type: "text", value: text.slice(cursor) });
  }
  return segments;
}

export function MathText({ text }: { text: string }) {
  const segments = useMemo(() => splitTexSegments(text), [text]);
  const hasTex = segments.some((s) => s.type !== "text");
  if (!hasTex) return <>{text}</>;
  return (
    <Suspense fallback={<>{text}</>}>
      {segments.map((s, i) =>
        s.type === "text" ? (
          // eslint-disable-next-line react/no-array-index-key -- segments are positional by construction
          <Fragment key={i}>{s.value}</Fragment>
        ) : (
          // eslint-disable-next-line react/no-array-index-key
          <LazyMathTex key={i} tex={s.value} display={s.type === "display"} />
        ),
      )}
    </Suspense>
  );
}

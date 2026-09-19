/**
 * Unified "add source" input classifier (brief §7.2 Add-by-URL).
 *
 * One entry point accepts every source form an operator commonly
 * holds and routes it to the right backend call:
 *
 *   - `https://arxiv.org/abs/<id>`                 → POST /papers (verbatim)
 *   - `https://ar5iv.labs.arxiv.org/html/<id>`     → POST /papers (verbatim)
 *   - `https://arxiv.org/html/<id>` (native HTML)  → POST /papers verbatim;
 *     the A1 spine rejects this host/prefix pair with 422 while the
 *     arx-a45 branch accepts it — the caller degrades to the canonical
 *     abs form on 422 (semantically lossless: the junction row stores
 *     only the paper_id; the fetch ladder picks the HTML rung
 *     server-side regardless of which URL form recorded the paper).
 *   - a bare arXiv id (`2401.00001`, `hep-th/0001234`, `1234.5678v2`)
 *     → canonicalized to the abs form.
 *   - a filename ending `.pdf` / `.html` is NOT a URL — the file leg
 *     (upload) owns those; classify returns "invalid" with a hint.
 *
 * The ID regexes mirror ingest/identifiers.py `_ARXIV_PAPER_ID_FULL_
 * PATTERN` (new style `\d{4}.\d{4,5}` + optional `v\d+`; old style
 * `[a-z][a-z-]` repeated, slash, `\d{7}`, optional version). The
 * server remains the trust boundary — this parser exists for inline
 * validation states and correct routing, never as a security gate.
 */

const NEW_STYLE_RE = /^\d{4}\.\d{4,5}(v\d+)?$/;
const OLD_STYLE_RE = /^[a-z][a-z-]*\/\d{7}(v\d+)?$/;

export function isValidArxivId(candidate: string): boolean {
  return NEW_STYLE_RE.test(candidate) || OLD_STYLE_RE.test(candidate);
}

export type SourceClass =
  | {
      kind: "abs" | "ar5iv" | "native-html" | "bare-id";
      paperId: string;
      /** The URL to POST as `arxiv_url` (canonical abs form for bare ids). */
      arxivUrl: string;
    }
  | { kind: "invalid"; reason: string };

/** Canonical abs-form URL for a validated paper id (the degrade target). */
export function absUrl(paperId: string): string {
  return `https://arxiv.org/abs/${paperId}`;
}

export function classifySource(raw: string): SourceClass {
  const input = raw.trim();
  if (input === "") {
    return { kind: "invalid", reason: "Enter an arXiv URL or paper id." };
  }

  // Bare id first: no scheme, no slash-path beyond the old-style form.
  if (isValidArxivId(input)) {
    return { kind: "bare-id", paperId: input, arxivUrl: absUrl(input) };
  }

  let url: URL;
  try {
    url = new URL(input);
  } catch {
    return {
      kind: "invalid",
      reason:
        "Not an arXiv URL or paper id. Accepted: arxiv.org/abs/…, " +
        "arxiv.org/html/…, ar5iv.labs.arxiv.org/html/…, or a bare id " +
        "like 2401.00001. PDF and HTML files go through the file upload below.",
    };
  }

  if (url.protocol !== "http:" && url.protocol !== "https:") {
    return { kind: "invalid", reason: `Unsupported scheme ${url.protocol}//.` };
  }

  const host = url.hostname;
  const path = url.pathname.replace(/\/+$/, "");
  const leg = (prefix: string): string | null =>
    path.startsWith(prefix) ? decodeURIComponent(path.slice(prefix.length)) : null;

  if (host === "arxiv.org" || host === "www.arxiv.org") {
    // www. is not in the server whitelist; normalize it client-side so
    // the common copy-paste variant still routes (server sees arxiv.org).
    const absId = leg("/abs/");
    if (absId !== null && isValidArxivId(absId)) {
      return { kind: "abs", paperId: absId, arxivUrl: absUrl(absId) };
    }
    const htmlId = leg("/html/");
    if (htmlId !== null && isValidArxivId(htmlId)) {
      return {
        kind: "native-html",
        paperId: htmlId,
        arxivUrl: `https://arxiv.org/html/${htmlId}`,
      };
    }
    if (path.startsWith("/pdf/")) {
      const pdfId = (leg("/pdf/") ?? "").replace(/\.pdf$/, "");
      if (isValidArxivId(pdfId)) {
        // arxiv.org/pdf/<id> is not an ingestible source (the pipeline
        // consumes LaTeXML-family HTML); route to the abs record.
        return { kind: "bare-id", paperId: pdfId, arxivUrl: absUrl(pdfId) };
      }
    }
    return {
      kind: "invalid",
      reason:
        "arxiv.org URL not in an accepted form — expected /abs/<id> or /html/<id>.",
    };
  }

  if (host === "ar5iv.labs.arxiv.org" || host === "ar5iv.org") {
    const id = leg("/html/") ?? leg("/abs/");
    if (id !== null && isValidArxivId(id)) {
      return {
        kind: "ar5iv",
        paperId: id,
        arxivUrl: `https://ar5iv.labs.arxiv.org/html/${id}`,
      };
    }
    return {
      kind: "invalid",
      reason: "ar5iv URL not in an accepted form — expected /html/<id>.",
    };
  }

  return {
    kind: "invalid",
    reason: `Host ${host} is not an accepted arXiv source (arxiv.org, ar5iv.labs.arxiv.org).`,
  };
}

/** Operator-facing one-liner for the inline validation state. */
export function describeSource(c: SourceClass): string {
  switch (c.kind) {
    case "abs":
      return `arXiv abstract page → paper ${c.paperId}`;
    case "native-html":
      return `arXiv native HTML → paper ${c.paperId}`;
    case "ar5iv":
      return `ar5iv HTML mirror → paper ${c.paperId}`;
    case "bare-id":
      return `arXiv id → ${c.arxivUrl}`;
    case "invalid":
      return c.reason;
  }
}

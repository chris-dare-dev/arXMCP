/**
 * Unified add-source classifier: the four mandated input forms (abs /
 * native HTML / ar5iv / file→invalid-hint) plus bare ids, version
 * suffixes, old-style ids, and rejection reasons. Mirrors (but never
 * replaces) the server-side gate in server/routes/notebooks.py.
 */
import { describe, expect, it } from "vitest";
import { absUrl, classifySource, describeSource, isValidArxivId } from "./sources";

describe("isValidArxivId", () => {
  it("accepts new-style, versioned, and old-style ids", () => {
    expect(isValidArxivId("2401.00001")).toBe(true);
    expect(isValidArxivId("2401.00001v3")).toBe(true);
    expect(isValidArxivId("0705.3794")).toBe(true);
    expect(isValidArxivId("hep-th/0001234")).toBe(true);
    expect(isValidArxivId("math/0212237v2")).toBe(true);
  });

  it("rejects malformed ids", () => {
    expect(isValidArxivId("")).toBe(false);
    expect(isValidArxivId("2401.001")).toBe(false); // 3-digit tail
    expect(isValidArxivId("textbook:foo-bar")).toBe(false); // not arXiv
    expect(isValidArxivId("2401.00001\n")).toBe(false); // trailing newline
  });
});

describe("classifySource", () => {
  it("routes abs URLs verbatim (canonicalized)", () => {
    const c = classifySource("https://arxiv.org/abs/2401.00001");
    expect(c).toEqual({
      kind: "abs",
      paperId: "2401.00001",
      arxivUrl: "https://arxiv.org/abs/2401.00001",
    });
  });

  it("handles version suffixes, trailing slashes, http, and www", () => {
    expect(classifySource("http://arxiv.org/abs/2401.00001v2/")).toMatchObject({
      kind: "abs",
      paperId: "2401.00001v2",
    });
    expect(classifySource("https://www.arxiv.org/abs/0705.3794")).toMatchObject({
      kind: "abs",
      paperId: "0705.3794",
    });
  });

  it("handles old-style ids in abs URLs", () => {
    expect(classifySource("https://arxiv.org/abs/hep-th/0001234")).toMatchObject({
      kind: "abs",
      paperId: "hep-th/0001234",
    });
  });

  it("classifies native arxiv.org/html URLs with the verbatim URL", () => {
    const c = classifySource("https://arxiv.org/html/2403.33333");
    expect(c).toEqual({
      kind: "native-html",
      paperId: "2403.33333",
      arxivUrl: "https://arxiv.org/html/2403.33333",
    });
  });

  it("classifies ar5iv URLs", () => {
    expect(
      classifySource("https://ar5iv.labs.arxiv.org/html/2402.22222v3"),
    ).toMatchObject({
      kind: "ar5iv",
      arxivUrl: "https://ar5iv.labs.arxiv.org/html/2402.22222v3",
    });
    // ar5iv.org redirects to the labs host; normalize client-side so
    // the server sees its whitelisted form.
    expect(classifySource("https://ar5iv.org/html/2402.22222")).toMatchObject({
      kind: "ar5iv",
      arxivUrl: "https://ar5iv.labs.arxiv.org/html/2402.22222",
    });
  });

  it("canonicalizes bare ids and pdf URLs to the abs form", () => {
    expect(classifySource("2401.00001")).toEqual({
      kind: "bare-id",
      paperId: "2401.00001",
      arxivUrl: absUrl("2401.00001"),
    });
    expect(classifySource("  hep-th/0001234  ")).toMatchObject({
      kind: "bare-id",
      paperId: "hep-th/0001234",
    });
    expect(classifySource("https://arxiv.org/pdf/2401.00001.pdf")).toMatchObject({
      kind: "bare-id",
      paperId: "2401.00001",
    });
  });

  it("rejects non-arXiv hosts, bad prefixes, and non-URLs with reasons", () => {
    expect(classifySource("https://example.com/abs/2401.00001")).toMatchObject({
      kind: "invalid",
    });
    expect(classifySource("https://arxiv.org/pdf/notanid")).toMatchObject({
      kind: "invalid",
    });
    expect(classifySource("ftp://arxiv.org/abs/2401.00001")).toMatchObject({
      kind: "invalid",
    });
    const file = classifySource("mypaper.pdf");
    expect(file.kind).toBe("invalid");
    if (file.kind === "invalid") {
      expect(file.reason).toContain("file upload");
    }
    expect(classifySource("")).toMatchObject({ kind: "invalid" });
    // ar5iv host with the wrong prefix is NOT silently accepted.
    expect(
      classifySource("https://ar5iv.labs.arxiv.org/papers/2401.00001"),
    ).toMatchObject({ kind: "invalid" });
  });

  it("describeSource names the route for the inline hint", () => {
    expect(describeSource(classifySource("https://arxiv.org/html/2403.33333")))
      .toContain("native HTML");
    expect(describeSource(classifySource("2401.00001"))).toContain(
      "https://arxiv.org/abs/2401.00001",
    );
  });
});

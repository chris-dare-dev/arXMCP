/**
 * Two-track math, chunk-surface half: the $TeX$ splitter and the
 * MathText component (lazy KaTeX; plain prose stays synchronous).
 */
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MathText, splitTexSegments } from "./MathText";

describe("splitTexSegments", () => {
  it("passes plain prose through as one text segment", () => {
    expect(splitTexSegments("no math here")).toEqual([
      { type: "text", value: "no math here" },
    ]);
  });

  it("splits inline and display segments in order", () => {
    expect(splitTexSegments("Let $x^2$ satisfy $$E = mc^2$$ today")).toEqual([
      { type: "text", value: "Let " },
      { type: "inline", value: "x^2" },
      { type: "text", value: " satisfy " },
      { type: "display", value: "E = mc^2" },
      { type: "text", value: " today" },
    ]);
  });

  it("keeps escaped dollars literal", () => {
    expect(splitTexSegments("costs \\$5 and $x$")).toEqual([
      { type: "text", value: "costs \\$5 and " },
      { type: "inline", value: "x" },
    ]);
  });

  it("leaves an unterminated delimiter as text", () => {
    expect(splitTexSegments("broken $x")).toEqual([
      { type: "text", value: "broken $x" },
    ]);
  });

  it("handles display math spanning newlines", () => {
    const segs = splitTexSegments("$$\\sum_{n}\nf(n)$$");
    expect(segs).toHaveLength(1);
    expect(segs[0].type).toBe("display");
  });
});

describe("MathText", () => {
  it("renders TeX segments through KaTeX (lazy chunk)", async () => {
    const { container } = render(
      <p>
        <MathText text="Bogomolov: $\Delta(E) \ge 0$ on surfaces" />
      </p>,
    );
    // Fallback shows raw text until the KaTeX chunk lands.
    await waitFor(() => {
      expect(container.querySelector(".katex")).not.toBeNull();
    });
    expect(screen.getByText(/Bogomolov:/)).toBeTruthy();
    // MathML annotation carries the source TeX (output: htmlAndMathml).
    expect(container.querySelector("annotation")?.textContent).toContain(
      "\\Delta(E)",
    );
  });

  it("renders plain prose synchronously with no KaTeX markup", () => {
    const { container } = render(<MathText text="just words" />);
    expect(container.textContent).toBe("just words");
    expect(container.querySelector(".katex")).toBeNull();
  });

  it("never throws on malformed TeX (renders literal source)", async () => {
    const { container } = render(<MathText text="bad $\frac{1}{$ input" />);
    await waitFor(() => {
      expect(container.querySelector(".katex-error, .katex")).not.toBeNull();
    });
  });
});

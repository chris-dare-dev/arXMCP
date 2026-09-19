/**
 * Display-math overflow containment (regression for the "display math
 * lacks overflow-x containment" finding). At a phone width, a wide
 * display equation (e.g. the Yang-Mills action) used to render with
 * overflow-x: visible and spill its ~549px of content straight out of
 * the 335px editorial column, so the equation clipped at the page edge
 * with no way to read the rest.
 *
 * The fix gives display math the same .table-scroll treatment tables
 * get: .katex-display (KaTeX chunk track) and standalone block MathML
 * (.ltx_Math, the LaTeXML stored-document track) become overflow-x:auto
 * scroll containers. The equation scrolls IN PLACE; its own box never
 * exceeds the column, so it never pushes the page.
 *
 * This asserts the per-block invariant (each display block is contained
 * and internally scrollable) rather than document scrollWidth, because
 * the app-shell <nav> has its own unrelated horizontal overflow at
 * 375px that would otherwise mask this signal.
 */
import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 375, height: 812 } });

test("display math is contained + internally scrollable at 375px", async ({
  page,
}) => {
  await page.goto("/app/specimen/math");
  await expect(
    page.getByRole("heading", { name: "Math rendering fixture" }),
  ).toBeVisible();
  // The lazy KaTeX chunk has rendered the first root.
  await expect(
    page.getByTestId("math-fixture-body").locator(".katex").first(),
  ).toBeVisible();
  // Give every display block a beat to lay out.
  await page.waitForLoadState("networkidle");

  const report = await page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const displays = Array.from(
      document.querySelectorAll<HTMLElement>(".katex-display"),
    );
    return {
      vw,
      count: displays.length,
      // A block "escapes" if its OWN border-box sticks past the viewport
      // right edge — that is the page-breaking condition the fix kills.
      escaping: displays
        .filter((el) => el.getBoundingClientRect().right > vw + 1)
        .map((el) => ({
          right: Math.round(el.getBoundingClientRect().right),
          overflowX: getComputedStyle(el).overflowX,
        })),
      // At least one display block must be genuinely wider than the
      // column (otherwise the test proves nothing) AND be a scroll
      // container (overflow-x: auto|scroll) so its content is reachable.
      wideScrollable: displays.filter((el) => {
        const cs = getComputedStyle(el);
        const scrollable = cs.overflowX === "auto" || cs.overflowX === "scroll";
        return scrollable && el.scrollWidth > el.clientWidth + 1;
      }).length,
      // Guard: no display block may use overflow-x: visible.
      visibleOverflow: displays.filter(
        (el) => getComputedStyle(el).overflowX === "visible",
      ).length,
    };
  });

  // There is display math on this fixture page.
  expect(report.count).toBeGreaterThan(0);
  // No display block spills past the viewport edge.
  expect(report.escaping).toEqual([]);
  // No display block falls back to overflow-x: visible.
  expect(report.visibleOverflow).toBe(0);
  // The wide Yang-Mills-class equation is present AND scrolls in place
  // (proves the containment is load-bearing, not vacuous).
  expect(report.wideScrollable).toBeGreaterThan(0);
});

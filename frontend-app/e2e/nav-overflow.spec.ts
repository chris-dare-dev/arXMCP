/**
 * App-shell horizontal-overflow regression (the chrome-side companion to
 * the display-math containment fix). The primary nav (`.shell-header nav`)
 * is a fixed horizontal row of domain links measuring ~393px. It had no
 * wrap and no shrink, so inside a 375px phone viewport it pushed the
 * shell-header — and therefore the whole document — out to ~493px,
 * scrolling the entire page sideways on EVERY route. The overflow is
 * chrome, independent of page content (it reproduced identically on the
 * notebooks index, the observability surfaces, and the design specimen).
 *
 * The fix lets `.shell-header` and its `nav` flex-wrap, so the nav rags
 * onto stacked rows instead of overrunning the column. This asserts the
 * document-level invariant that restores: at 375px no sampled route
 * scrolls the page horizontally, and the nav's own box stays within the
 * viewport (pinning the root cause, not just the symptom).
 *
 * networkidle is deliberately NOT used to settle: the observability
 * routes hold an SSE stream open, so the network never goes idle. Each
 * route instead waits on a concrete paint signal, then a double rAF.
 */
import { expect, test, type Page } from "@playwright/test";

const VW = 375;

test.use({ viewport: { width: VW, height: 812 } });

// Route-independent by construction: an index page, an SSE-backed
// observability surface, and the static design specimen. Each `ready`
// resolves once that route has painted meaningful content, so layout is
// measured settled rather than mid-load.
const ROUTES: Array<{ name: string; path: string; ready: (p: Page) => Promise<unknown> }> = [
  {
    name: "notebooks index",
    path: "/app/",
    ready: (page) => expect(page.getByTestId("notebooks-status")).toHaveText("2 notebooks"),
  },
  {
    name: "logs (SSE observability)",
    path: "/app/logs",
    ready: (page) => expect(page.getByTestId("logs-status")).toContainText("live (SSE)"),
  },
];

for (const route of ROUTES) {
  test(`no horizontal page scroll at ${VW}px — ${route.name}`, async ({ page }) => {
    await page.goto(route.path);
    await route.ready(page);
    // Let two frames paint so any post-ready layout shift settles.
    await page.evaluate(
      () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))),
    );

    const report = await page.evaluate((vw) => {
      const doc = document.documentElement;
      // Diagnostic only: elements whose OWN border-box sticks past the
      // viewport's right edge are candidate page-wideners. (Internally
      // scrollable blocks like .katex-display keep their box in-bounds,
      // so they never appear here.) Surface the worst few for triage.
      const offenders = Array.from(document.querySelectorAll<HTMLElement>("*"))
        .map((el) => ({ el, right: el.getBoundingClientRect().right }))
        .filter((x) => x.right > vw + 1)
        .sort((a, b) => b.right - a.right)
        .slice(0, 5)
        .map((x) => ({
          right: Math.round(x.right),
          tag: x.el.tagName.toLowerCase(),
          cls: typeof x.el.className === "string" ? x.el.className : null,
        }));
      const nav = document.querySelector("nav");
      return {
        scrollWidth: doc.scrollWidth,
        clientWidth: doc.clientWidth,
        navRight: nav ? Math.round(nav.getBoundingClientRect().right) : null,
        offenders,
      };
    }, VW);

    // The page does not scroll sideways: the document is no wider than the
    // viewport (1px slack for sub-pixel rounding). This is the invariant
    // the finding broke and the wrap restores.
    expect(
      report.scrollWidth,
      `document scrolls horizontally at ${VW}px; widest offenders: ${JSON.stringify(
        report.offenders,
      )}`,
    ).toBeLessThanOrEqual(report.clientWidth + 1);

    // Pin the root cause: the primary nav's own box is within the viewport
    // (it wrapped rather than overrunning to ~493px).
    expect(report.navRight, "nav must be present in the shell").not.toBeNull();
    expect(report.navRight!).toBeLessThanOrEqual(report.clientWidth + 1);
  });
}

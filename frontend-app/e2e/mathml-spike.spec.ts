/**
 * D7 MathML render spike (the 30-minute spike, made permanent).
 *
 * Question (211 R-D / E-9): does ar5iv-shaped presentation MathML
 * visually render via MathML Core under the preview route's
 * script-src 'none' CSP — i.e. with ZERO JavaScript?
 *
 * Method: /spike/mathml serves a committed fixture with the exact
 * stored-HTML markup shape (math.ltx_Math + semantics + x-tex
 * annotation) under the REAL CONTENT_SECURITY_POLICY_PREVIEW bytes.
 * A <script> canary proves CSP blocked execution; layout metrics
 * prove the math engine (not raw text fallback) did the rendering:
 * an <mfrac> stacks vertically, so its box is markedly taller than
 * the inline text reference.
 *
 * /spike/mathml-real replays the check on a REAL stored ar5iv paper
 * (0705.3794, 269 math elements) when the workstation cache has it.
 *
 * arx-b2 adds the OTHER track's acceptance check (AC-B.24): the
 * /app/specimen/math fixture (20+ mixed inline/display formulas
 * through MathText → KaTeX) renders with zero console errors and no
 * failed requests.
 */
import { expect, test } from "@playwright/test";

test("fixture MathML renders with zero JS under script-src 'none'", async ({ page }) => {
  await page.goto("/spike/mathml");

  // CSP canary: the inline script must NOT have executed.
  const executed = await page.evaluate(() => document.body.dataset.scriptExecuted);
  expect(executed, "script-src 'none' must block the canary").toBeUndefined();

  // MathML Core support: the fraction's box is much taller than an
  // inline text line (numerator over denominator), and the element
  // reports a laid-out size at all.
  const heights = await page.evaluate(() => {
    const ref = document.getElementById("inline-ref")!.getBoundingClientRect();
    const frac = document.getElementById("m-frac")!.getBoundingClientRect();
    const inline = document.getElementById("m-inline")!.getBoundingClientRect();
    return { ref: ref.height, frac: frac.height, inline: inline.height };
  });
  expect(heights.inline).toBeGreaterThan(0);
  expect(heights.frac).toBeGreaterThan(heights.ref * 1.5);

  // The browser actually exposes MathML Core (belt and braces).
  const mathmlCore = await page.evaluate(() => typeof (window as never)["MathMLElement"]);
  expect(mathmlCore).toBe("function");
});

test("real stored ar5iv paper renders MathML (workstation cache)", async ({ page }) => {
  const probe = await page.request.get("/spike/mathml-real");
  test.skip(probe.status() === 404, "no stored ar5iv sample on this machine");

  await page.goto("/spike/mathml-real");
  const stats = await page.evaluate(() => {
    const maths = Array.from(document.querySelectorAll("math"));
    const rendered = maths.filter((m) => {
      const r = m.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    });
    return { total: maths.length, rendered: rendered.length };
  });
  expect(stats.total).toBeGreaterThan(100); // 0705.3794 carries 269
  // Not every element is in-flow (some sit in hidden containers), but
  // the overwhelming majority must lay out.
  expect(stats.rendered).toBeGreaterThan(stats.total * 0.8);
});

test("KaTeX fixture page: 20+ formulas, zero console errors (AC-B.24)", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  await page.goto("/app/specimen/math");
  const body = page.getByTestId("math-fixture-body");
  await expect(body.locator(".katex").first()).toBeVisible();

  // 20+ mixed formulas actually rendered (the count is over KaTeX
  // roots, one per $…$/$$…$$ segment; display ones carry .katex-display).
  const katexCount = await body.locator(".katex").count();
  expect(katexCount).toBeGreaterThanOrEqual(20);
  const displayCount = await body.locator(".katex-display").count();
  expect(displayCount).toBeGreaterThanOrEqual(5);

  // The malformed-TeX control renders as literal source, not a crash.
  await expect(body.locator(".katex-error").first()).toBeVisible();

  expect(consoleErrors).toEqual([]);
});

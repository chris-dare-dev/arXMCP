/**
 * App-shell E2E: the SPA works under the strict CSP, talks only to
 * loopback, and renders the notebook index from the (mock) /api/v1.
 * This is the AC-B.20 E2E skeleton's first section — the full
 * create->upload->ingest->observe flow grows here as WS-A surfaces
 * land; the harness (mock API + network capture) is the deliverable
 * of this milestone.
 */
import { expect, test } from "@playwright/test";

test("serves the SPA under the strict /app CSP and renders notebooks", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (r) => requests.push(r.url()));

  const response = await page.goto("/app/");
  expect(response, "document response").not.toBeNull();

  // AC-B.2: the exact stricter policy, byte-for-byte from middleware.py.
  const csp = response?.headers()["content-security-policy"] ?? "";
  expect(csp).toContain("script-src 'self'");
  expect(csp.split("style-src")[0]).not.toContain("unsafe-inline");
  expect(csp).toContain("font-src 'self'");

  // The app must FUNCTION under that CSP (no inline-script dependence):
  // client-side data fetch + render happened.
  await expect(page.getByTestId("notebooks-status")).toHaveText("2 notebooks");
  const rows = page.getByTestId("notebook-list").locator("li");
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText("Bridgeland stability");
  await expect(rows.first()).toContainText("bridgeland-stability");

  // AC-B.2 network capture: loopback-only — fonts, JS, CSS, API.
  const offOrigin = requests.filter((u) => !u.startsWith("http://127.0.0.1:7799/"));
  expect(offOrigin, "zero external network requests").toEqual([]);
});

test("client-route reload gets the history fallback", async ({ page }) => {
  await page.goto("/app/specimen/math");
  await expect(page.getByTestId("math-fixture-body")).toBeVisible();
});

test("skip link and keyboard focus discipline", async ({ page }) => {
  await page.goto("/app/");
  await page.keyboard.press("Tab");
  const skip = page.locator(".skip-link");
  await expect(skip).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();
});

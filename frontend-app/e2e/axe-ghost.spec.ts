/**
 * AC-B.14 (traffic-less states): the same @axe-core zero-violation gate
 * as axe.spec.ts, but for the DESIGNED empty states that the read-only
 * fixture never reaches because it always seeds traffic. Regression for
 * the ghost-lane chip contrast defect: `.lane-canvas-ghost` used to dim
 * the lane head (role chip + cap-meter labels) with `opacity: 0.55`,
 * compositing that text to ~2.47:1 (light) / ~2.96:1 (dark) at 11px — a
 * serious color-contrast violation on a designed state. The fix dims via
 * a full-opacity faint token (>= 4.5:1) instead of container opacity.
 *
 * Runs serial on its own hermetic instance (:7805) because it mutates
 * the ring via POST /e2e/obs-clear; must not race the 7799 baselines.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const BASE = "http://127.0.0.1:7805";
test.describe.configure({ mode: "serial" });
test.use({ baseURL: BASE });

const SCHEMES = ["light", "dark"] as const;

for (const scheme of SCHEMES) {
  test(`axe clean: /app/requests traffic-less (ghost lanes) [${scheme}]`, async ({
    page,
    request,
  }) => {
    // Empty the requests ring while the route stays 200 (obs_enabled
    // untouched) — the ghost-lane teaching state, distinct from the
    // route-absent 404 path.
    const reset = await request.post(`${BASE}/e2e/reset`);
    expect(reset.ok()).toBeTruthy();
    const cleared = await request.post(`${BASE}/e2e/obs-clear`, {
      data: { topic: "requests" },
    });
    expect(cleared.ok()).toBeTruthy();

    // Same determinism discipline as axe.spec.ts.
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
    await page.goto("/app/requests");

    // Settle: the ghost teaching copy + the dimmed lane head are live.
    await expect(page.getByTestId("lane-ghost")).toBeVisible();
    await expect(page.getByTestId("lane-canvas")).toHaveClass(
      /lane-canvas-ghost/,
    );
    // The four fixed role chips render even with zero traffic — these
    // are the nodes that failed AA before the fix.
    for (const role of [
      "sketcher",
      "autoformalizer",
      "tactician",
      "fixer",
    ] as const) {
      await expect(page.getByTestId(`lane-${role}`)).toBeVisible();
    }

    await expectAxeClean(page);
  });
}

async function expectAxeClean(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(
    results.violations.map(
      (v) => `${v.id}: ${v.nodes.map((n) => n.target).join(", ")}`,
    ),
  ).toEqual([]);
}

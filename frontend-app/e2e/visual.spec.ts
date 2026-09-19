/**
 * AC-B.21: visual-regression baselines for the routed pages x
 * light/dark, reduced-motion FORCED for determinism, on the
 * single-machine Windows baseline. Detail is pinned in BOTH health
 * states (clean marker with papers; drifted marker with the empty
 * papers state) — the drift sentence is a design deliverable.
 */
import { expect, test, type Page } from "@playwright/test";

const SCHEMES = ["light", "dark"] as const;

async function settleFonts(page: Page) {
  // Fonts settle before pixels are pinned (STIX/JetBrains woff2).
  await page.evaluate(() => document.fonts.ready);
}

for (const scheme of SCHEMES) {
  test(`notebooks page visual [${scheme}]`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
    await page.goto("/app/");
    await expect(page.getByTestId("notebooks-status")).toHaveText("2 notebooks");
    await settleFonts(page);
    await expect(page).toHaveScreenshot(`notebooks-${scheme}.png`, { fullPage: true });
  });

  test(`notebook detail visual, clean marker [${scheme}]`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
    await page.goto("/app/notebooks/bridgeland-stability");
    await expect(page.getByTestId("health-sentence")).toContainText(
      "marker and LanceDB agree",
    );
    await expect(page.getByTestId("papers-status")).toHaveText("2 papers");
    await settleFonts(page);
    await expect(page).toHaveScreenshot(`detail-ok-${scheme}.png`, { fullPage: true });
  });

  test(`notebook detail visual, drifted marker [${scheme}]`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
    await page.goto("/app/notebooks/fourier-duality");
    await expect(page.getByTestId("health-sentence")).toContainText("marker says");
    await settleFonts(page);
    await expect(page).toHaveScreenshot(`detail-drift-${scheme}.png`, { fullPage: true });
  });

  test(`math fixture visual [${scheme}]`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
    await page.goto("/app/specimen/math");
    await expect(
      page.getByTestId("math-fixture-body").locator(".katex").first(),
    ).toBeVisible();
    await settleFonts(page);
    await expect(page).toHaveScreenshot(`mathfix-${scheme}.png`, { fullPage: true });
  });

  // arx-b3 observability surfaces: seeded fixture events carry FIXED
  // timestamps (2026-07-04T12:00Z anchor) and the lane window anchors
  // to the data, not the wall clock — pixels are deterministic.
  test(`logs page visual [${scheme}]`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
    await page.goto("/app/logs");
    await expect(page.getByTestId("logs-status")).toContainText("live (SSE)");
    await settleFonts(page);
    await expect(page).toHaveScreenshot(`logs-${scheme}.png`, { fullPage: true });
  });

  test(`requests page visual [${scheme}]`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
    await page.goto("/app/requests");
    await expect(page.getByTestId("requests-status")).toContainText("live (SSE)");
    await expect(page.getByTestId("lane-sketcher").locator("circle").first()).toBeVisible();
    await settleFonts(page);
    await expect(page).toHaveScreenshot(`requests-${scheme}.png`, { fullPage: true });
  });

  test(`connections page visual [${scheme}]`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
    await page.goto("/app/connections");
    await expect(page.getByTestId("trust-header")).toContainText("corpus v1690");
    await expect(page.getByTestId("ingest-history-status")).toContainText(
      "live (SSE)",
    );
    await settleFonts(page);
    await expect(page).toHaveScreenshot(`connections-${scheme}.png`, {
      fullPage: true,
    });
  });

  // arx-b3 config + graph surfaces: the capabilities fixture list and
  // the Tier-0 neighbor tree are fully deterministic (seeded profiles,
  // synthetic adjacency). The Tier-2 WebGL canvas is deliberately NOT
  // baselined — force layouts are nondeterministic by construction;
  // Tier-0 is the acceptance surface (AC-B.23).
  test(`capabilities page visual [${scheme}]`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
    await page.goto("/app/capabilities");
    await expect(page.getByTestId("caps-status")).toHaveText(
      "2 profiles in force",
    );
    await expect(page.getByTestId("denied-website")).toBeVisible();
    await settleFonts(page);
    await expect(page).toHaveScreenshot(`capabilities-${scheme}.png`, {
      fullPage: true,
    });
  });

  test(`graph page visual, tier-0 [${scheme}]`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
    await page.goto("/app/notebooks/bridgeland-stability/graph");
    await expect(page.getByTestId("graph-status")).toHaveText(
      "2 direct cites neighbors of 0705.3794",
    );
    await expect(page.getByTestId("graph-caption")).toContainText(
      "corpus v1690",
    );
    await settleFonts(page);
    await expect(page).toHaveScreenshot(`graph-tier0-${scheme}.png`, {
      fullPage: true,
    });
  });
}

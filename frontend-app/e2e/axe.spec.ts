/**
 * AC-B.14: @axe-core/playwright zero-violation gate on every routed
 * page, light AND dark (wcag2a, wcag2aa, wcag21aa). Each route carries
 * its own deterministic settle condition (an aria-live region or
 * heading that only appears once data has loaded).
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const ROUTES: { path: string; settle: (page: Page) => Promise<void> }[] = [
  {
    path: "/app/",
    settle: async (page) => {
      await expect(page.getByTestId("notebooks-status")).toHaveText("2 notebooks");
    },
  },
  {
    // Notebook detail, clean marker: stat block + papers table.
    path: "/app/notebooks/bridgeland-stability",
    settle: async (page) => {
      await expect(page.getByTestId("health-sentence")).toContainText(
        "marker and LanceDB agree",
      );
      await expect(page.getByTestId("papers-status")).toHaveText("2 papers");
    },
  },
  {
    // Notebook detail, DRIFTED marker: the amber sentence + reconcile
    // affordance must both clear the same AA bar.
    path: "/app/notebooks/fourier-duality",
    settle: async (page) => {
      await expect(page.getByTestId("health-sentence")).toContainText("marker says");
      await expect(
        page.getByRole("button", { name: "Reconcile marker from recount" }),
      ).toBeVisible();
    },
  },
  {
    // Logs tail (arx-b3): facet rail + viewport + retention banner,
    // settled once the seeded fixture tail is live over SSE.
    path: "/app/logs",
    settle: async (page) => {
      await expect(page.getByTestId("logs-status")).toContainText("live (SSE)");
      await expect(page.getByTestId("logs-retention")).toBeVisible();
    },
  },
  {
    // Requests (arx-b3): lane hero + table + rejection strip.
    path: "/app/requests",
    settle: async (page) => {
      // Wait for the SSE transport so the status line is deterministic.
      await expect(page.getByTestId("requests-status")).toContainText(
        "live (SSE)",
      );
      await expect(page.getByTestId("lane-sketcher")).toBeVisible();
    },
  },
  {
    // Connections (arx-b3): trust header + roster meters + history.
    path: "/app/connections",
    settle: async (page) => {
      await expect(page.getByTestId("trust-header")).toContainText(
        "corpus v1690",
      );
      await expect(page.getByTestId("ingest-history-status")).toContainText(
        "live (SSE)",
      );
    },
  },
  {
    // Capability config (arx-b3): D5 teaching block + effective
    // profile rows (the seeded allowlist row carries the denied copy).
    path: "/app/capabilities",
    settle: async (page) => {
      await expect(page.getByTestId("caps-status")).toHaveText(
        "2 profiles in force",
      );
      await expect(page.getByTestId("denied-website")).toBeVisible();
    },
  },
  {
    // Graph Tier-0 (arx-b3): the accessible neighbor explorer IS the
    // AT acceptance surface (AC-B.23) — axe must hold on it.
    path: "/app/notebooks/bridgeland-stability/graph",
    settle: async (page) => {
      await expect(page.getByTestId("graph-status")).toHaveText(
        "2 direct cites neighbors of 0705.3794",
      );
      await expect(page.getByTestId("graph-caption")).toBeVisible();
    },
  },
  {
    // AC-B.24 math fixture: 20+ mixed formulas through the KaTeX
    // track; settle once the lazy KaTeX chunk has rendered.
    path: "/app/specimen/math",
    settle: async (page) => {
      await expect(
        page.getByRole("heading", { name: "Math rendering fixture" }),
      ).toBeVisible();
      await expect(
        page.getByTestId("math-fixture-body").locator(".katex").first(),
      ).toBeVisible();
    },
  },
];

const SCHEMES = ["light", "dark"] as const;

for (const route of ROUTES) {
  for (const scheme of SCHEMES) {
    test(`axe clean: ${route.path} [${scheme}]`, async ({ page }) => {
      // reducedMotion forced for determinism (same discipline as the
      // visual suite): the vendored reveal wrappers otherwise animate
      // opacity on intersection, and axe sampling mid-reveal reports
      // blended foreground colors as contrast failures (a race, not a
      // token defect — the settled colors are the AA-verified pairs).
      await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
      await page.goto(route.path);
      await route.settle(page);
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze();
      expect(
        results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(", ")}`),
      ).toEqual([]);
    });
  }
}

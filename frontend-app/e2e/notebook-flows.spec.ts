/**
 * Notebook management flows against the STATEFUL hermetic server on
 * :7800 (the :7799 instance stays read-only for the visual/axe
 * suites). Serial + POST /e2e/reset per test: deterministic state, no
 * cross-worker races. The create flow runs keyboard-only — the
 * AC-B.15 discipline seed for the management surfaces.
 */
import { expect, test } from "@playwright/test";

const BASE = "http://127.0.0.1:7800";

test.describe.configure({ mode: "serial" });
test.use({ baseURL: BASE });

test.beforeEach(async ({ request }) => {
  const reset = await request.post(`${BASE}/e2e/reset`);
  expect(reset.ok()).toBe(true);
});

test("create notebook, keyboard-only: form → announce → fresh row", async ({ page }) => {
  await page.goto("/app/");
  await expect(page.getByTestId("notebooks-status")).toHaveText("2 notebooks");

  // Keyboard-only: focus the slug field via the keyboard path, type,
  // tab to display name, type, submit with Enter (no pointer events).
  await page.getByLabel("slug").focus();
  await page.keyboard.type("spectral-forms");
  await page.keyboard.press("Tab");
  await page.keyboard.type("Spectral forms");
  await page.keyboard.press("Enter");

  await expect(page.getByTestId("create-status")).toHaveText(
    "Notebook spectral-forms created.",
  );
  await expect(page.getByTestId("notebooks-status")).toHaveText("3 notebooks");
  await expect(page.getByRole("link", { name: "Spectral forms" })).toBeVisible();

  // The fresh row navigates to a working detail page (no_marker state).
  await page.getByRole("link", { name: "Spectral forms" }).click();
  await expect(page.getByTestId("health-sentence")).toContainText(
    "run `make ingest` first",
  );
});

test("reconcile flow: drift → POST reconcile → ok", async ({ page }) => {
  await page.goto("/app/notebooks/fourier-duality");
  await expect(page.getByTestId("health-sentence")).toContainText("marker says");

  await page.getByRole("button", { name: "Reconcile marker from recount" }).click();

  await expect(page.getByTestId("reconcile-status")).toContainText(
    "drift resolved -1",
  );
  await expect(page.getByTestId("health-sentence")).toContainText(
    "marker and LanceDB agree",
  );
});

test("discovery propose→confirm feeds the papers table", async ({ page }) => {
  await page.goto("/app/notebooks/fourier-duality");
  await expect(page.getByTestId("papers-status")).toHaveText("0 papers");

  await page.getByRole("button", { name: "Run discovery" }).click();
  await expect(page.getByTestId("discover-status")).toContainText(
    "2 candidates proposed",
  );
  await expect(
    page.getByText("Stability conditions under Fourier–Mukai transforms", {
      exact: true,
    }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Add to notebook" }).first().click();
  await expect(page.getByTestId("discover-status")).toContainText("Added 2406.01234");
  await expect(page.getByTestId("papers-status")).toHaveText("1 paper");
});

test("rename + topic edits stick on the detail header", async ({ page }) => {
  await page.goto("/app/notebooks/bridgeland-stability");
  await expect(page.getByTestId("detail-title")).toHaveText("Bridgeland stability");

  await page.getByRole("button", { name: "Rename" }).click();
  await page.getByLabel("display name").fill("Bridgeland stability conditions");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByTestId("rename-status")).toHaveText("Display name saved.");
  await expect(page.getByTestId("detail-title")).toHaveText(
    "Bridgeland stability conditions",
  );

  await page.getByRole("button", { name: "Edit topic" }).click();
  await page.getByLabel("category").selectOption("math.NT");
  await page.getByRole("button", { name: "Save topic" }).click();
  await expect(page.getByTestId("topic-status")).toHaveText("Topic saved.");
});

test("delete notebook: two-step confirm returns to a shrunken index", async ({ page }) => {
  await page.goto("/app/notebooks/fourier-duality");
  await page.getByRole("button", { name: "Delete notebook…" }).click();
  await page.getByRole("button", { name: "Confirm delete" }).click();

  await expect(page.getByTestId("notebooks-status")).toHaveText("1 notebook");
  await expect(page.getByText("Fourier duality")).toHaveCount(0);
});

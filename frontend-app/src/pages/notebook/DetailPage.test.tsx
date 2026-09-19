/**
 * NotebookDetailPage component tests over the ApiProvider seam —
 * zero live server. Covers: the loaded two-register screen (editorial
 * header + telemetry stats + margin channel), the drift indicator's
 * amber path with the full reconcile round-trip (button → POST →
 * health refetch flips to ok), the papers empty state, and the
 * designed not-found state.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ApiProvider } from "../../api/ApiProvider";
import { makeClient } from "../../api/client";
import {
  FIXTURE_HEALTH,
  jsonResponse,
  mockFetch,
  mockRoute,
} from "../../api/mock";
import type { HealthResult } from "../../api/types";
import { NotebookDetailPage } from "./DetailPage";

function renderDetail(slug: string, fetchImpl: typeof fetch) {
  return render(
    <ApiProvider client={makeClient(fetchImpl, "http://127.0.0.1")}>
      <MemoryRouter initialEntries={[`/notebooks/${slug}`]}>
        <Routes>
          <Route path="/notebooks/:slug" element={<NotebookDetailPage />} />
        </Routes>
      </MemoryRouter>
    </ApiProvider>,
  );
}

describe("NotebookDetailPage — loaded state (clean marker)", () => {
  it("renders editorial header, stat block, papers table, margin channel", async () => {
    renderDetail("bridgeland-stability", mockFetch);

    // Editorial header: title + description prose.
    expect(await screen.findByTestId("detail-title")).toHaveProperty(
      "textContent",
      "Bridgeland stability",
    );
    // Header prose + the topic editor's display both carry the topic
    // description (two-register screen).
    expect(
      screen.getAllByText("Stability conditions on derived categories").length,
    ).toBeGreaterThan(0);

    // Quiet health line + full corpus-version.json stat block (AC-B.18).
    expect(screen.getByTestId("health-sentence").textContent).toContain(
      "marker and LanceDB agree",
    );
    const stats = screen.getByTestId("stat-block");
    expect(stats.textContent).toContain("v1690");
    expect(stats.textContent).toContain("12672");
    expect(stats.textContent).toContain("2026-06-22T04:00:11Z");

    // Papers table: junction rows with chips; count in the live region.
    expect(screen.getByTestId("papers-status").textContent).toBe("2 papers");
    expect(screen.getByText("0705.3794")).toBeTruthy();

    // Margin-metadata channel: embedder/chunker provenance (1c3dc4b).
    const provenance = screen.getByLabelText("Provenance");
    expect(provenance.textContent).toContain("bge-m3@567");
    expect(provenance.textContent).toContain("2026-06-22T03:08:28Z");

    // Export affordance points at the binary /api/v1 route.
    expect(screen.getByTestId("export-link").getAttribute("href")).toBe(
      "/api/v1/notebooks/bridgeland-stability/export",
    );
  });
});

describe("NotebookDetailPage — drift path", () => {
  it("shows the amber drift sentence and reconciles through the API", async () => {
    // Stateful per-test fetch: health flips to ok after the reconcile
    // POST (mock.ts itself stays stateless by design).
    let reconciled = false;
    const healthOk: HealthResult = {
      ...FIXTURE_HEALTH["fourier-duality"],
      status: "ok",
      marker_chunk_count: 2050,
      actual_chunk_count: 2050,
      drift: 0,
      detail: null,
    };
    const statefulFetch: typeof fetch = (input, init) => {
      const url = new URL(
        typeof input === "string" || input instanceof URL ? String(input) : input.url,
        "http://127.0.0.1",
      );
      const method = init?.method ?? (input instanceof Request ? input.method : "GET");
      if (
        method === "POST" &&
        url.pathname === "/api/v1/notebooks/fourier-duality/reconcile-marker"
      ) {
        reconciled = true;
        return Promise.resolve(
          jsonResponse({
            format_version: 1,
            slug: "fourier-duality",
            before: { chunk_count: 2051, paper_count: 1 },
            after: { chunk_count: 2050, paper_count: 1 },
            drift_resolved: -1,
          }),
        );
      }
      if (
        method === "GET" &&
        url.pathname === "/api/v1/notebooks/fourier-duality/health" &&
        reconciled
      ) {
        return Promise.resolve(jsonResponse(healthOk));
      }
      return Promise.resolve(
        mockRoute(method, url.pathname) ??
          jsonResponse({ error: "not_mocked", path: url.pathname }, 404),
      );
    };

    renderDetail("fourier-duality", statefulFetch);

    // Amber sentence carries the server's authoritative detail copy.
    const sentence = await screen.findByTestId("health-sentence");
    expect(sentence.className).toContain("drift-note");
    expect(sentence.textContent).toContain("marker says 2051 chunks");

    // Papers empty state teaches the next action.
    expect(screen.getByText("No papers in this notebook.")).toBeTruthy();

    // Reconcile round-trip.
    fireEvent.click(
      screen.getByRole("button", { name: "Reconcile marker from recount" }),
    );
    expect(
      (await screen.findByTestId("reconcile-status")).textContent,
    ).toContain("drift resolved -1");

    // The health refetch flips the indicator to the quiet ok line.
    expect(
      (await screen.findByText(/marker and LanceDB agree/)).className,
    ).not.toContain("drift-note");
  });
});

describe("NotebookDetailPage — not found", () => {
  it("renders the designed not-found state with a way back", async () => {
    renderDetail("no-such-notebook", mockFetch);
    expect(await screen.findByText("Notebook not found")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Back to notebooks/ })).toBeTruthy();
  });
});

describe("NotebookDetailPage — degraded health endpoint", () => {
  it("names the failing endpoint without killing the page", async () => {
    const partialFetch: typeof fetch = (input, init) => {
      const url = new URL(
        typeof input === "string" || input instanceof URL ? String(input) : input.url,
        "http://127.0.0.1",
      );
      const method = init?.method ?? (input instanceof Request ? input.method : "GET");
      if (url.pathname.endsWith("/health")) {
        return Promise.resolve(jsonResponse({ detail: "boom" }, 500));
      }
      return Promise.resolve(
        mockRoute(method, url.pathname) ??
          jsonResponse({ error: "not_mocked" }, 404),
      );
    };
    renderDetail("bridgeland-stability", partialFetch);
    // Header still renders; the health line names the dependency.
    expect(await screen.findByTestId("detail-title")).toBeTruthy();
    expect(screen.getByTestId("health-status").textContent).toContain(
      "/health failed (500)",
    );
    // Papers table is unaffected by the health failure.
    expect(screen.getByTestId("papers-status").textContent).toBe("2 papers");
  });
});

/**
 * NotebooksPage component tests through the ApiProvider seam — the
 * page renders against makeClient(mockFetch) with zero live server
 * (IF-1 decoupling at the component-test tier). The three designed
 * states (live / empty / error, brief §7) are each asserted.
 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { ReactElement } from "react";
import { ApiProvider } from "../api/ApiProvider";
import { makeClient } from "../api/client";
import { jsonResponse, mockFetch, pageEnvelope } from "../api/mock";
import { NotebooksPage } from "./NotebooksPage";

function renderWithApi(ui: ReactElement, fetchImpl: typeof fetch) {
  return render(
    <ApiProvider client={makeClient(fetchImpl, "http://127.0.0.1")}>
      <MemoryRouter>{ui}</MemoryRouter>
    </ApiProvider>,
  );
}

describe("NotebooksPage over the ApiProvider seam", () => {
  it("renders the fixture notebooks as rule-separated rows", async () => {
    renderWithApi(<NotebooksPage />, mockFetch);
    // aria-live status region reports the count once loaded.
    expect(await screen.findByText("2 notebooks")).toBeTruthy();
    expect(screen.getByText("Bridgeland stability")).toBeTruthy();
    expect(screen.getByText("Fourier duality")).toBeTruthy();
    // Telemetry chips carry the machine facts.
    expect(screen.getByText("bridgeland-stability")).toBeTruthy();
    for (const chip of screen.getAllByText("math.AG")) {
      expect(chip.tagName).toBe("SPAN");
    }
  });

  it("shows the teaching empty state when the corpus has no notebooks", async () => {
    const emptyFetch: typeof fetch = () =>
      Promise.resolve(jsonResponse(pageEnvelope([])));
    renderWithApi(<NotebooksPage />, emptyFetch);
    expect(await screen.findByText("0 notebooks")).toBeTruthy();
    expect(screen.getByText("No notebooks yet.")).toBeTruthy();
  });

  it("names the failing dependency in the error state", async () => {
    const failingFetch: typeof fetch = () =>
      Promise.resolve(jsonResponse({ detail: "boom" }, 500));
    renderWithApi(<NotebooksPage />, failingFetch);
    expect(
      await screen.findByText(/GET \/api\/v1\/notebooks failed \(500\)/),
    ).toBeTruthy();
  });
});

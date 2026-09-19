/**
 * Requests surface: the session-lane hero (role lanes, tier fills,
 * error ring, per-lane cap meters, ghost-lane teaching empty state),
 * the request table with the window-p95 latency bars, URL-addressable
 * facets, the cap-rejection strip, and the waterfall drawer (phases
 * that actually ran vs the single-bar fallback).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { ObsProvider } from "../../api/ObsProvider";
import type { ObsApi } from "../../api/obs";
import { RequestsPage } from "./RequestsPage";
import { FakeEventSource, makeFakeObs } from "./testDoubles";

function renderRequests(
  api: ObsApi,
  { sse = true, url = "/requests" }: { sse?: boolean; url?: string } = {},
) {
  FakeEventSource.reset();
  const factory = sse ? (u: string) => new FakeEventSource(u) : () => null;
  const view = render(
    <ObsProvider api={api}>
      <MemoryRouter initialEntries={[url]}>
        <RequestsPage
          eventSourceFactory={factory}
          pollIntervalMs={20}
          sessionsPollMs={20}
        />
      </MemoryRouter>
    </ObsProvider>,
  );
  return { view, es: () => FakeEventSource.instances[0] };
}

async function waitLoaded() {
  await waitFor(() =>
    expect(screen.getByTestId("requests-status").textContent).toContain(
      "retained",
    ),
  );
}

describe("RequestsPage", () => {
  beforeEach(() => FakeEventSource.reset());

  it("renders one lane per pipeline role with pulses and cap meters", async () => {
    const { api } = makeFakeObs();
    renderRequests(api);
    await waitLoaded();

    // The four fixed roles always have lanes (brief §7.0).
    for (const role of ["sketcher", "autoformalizer", "tactician", "fixer"]) {
      expect(screen.getByTestId(`lane-${role}`)).toBeDefined();
    }
    // Pulses land in their role's lane; error status gets the ring.
    const sketcherLane = screen.getByTestId("lane-sketcher");
    expect(sketcherLane.querySelectorAll("circle.pulse")).toHaveLength(3);
    const tacticianLane = screen.getByTestId("lane-tactician");
    expect(
      tacticianLane.querySelectorAll("circle.pulse-error"),
    ).toHaveLength(1);
    // Cap meters ride the lane head from the sessions snapshot.
    await waitFor(() =>
      expect(
        sketcherLane.querySelector('[data-testid="cap-search_papers"]'),
      ).not.toBeNull(),
    );
    // The tier legend names the observed cache layers.
    expect(screen.getByTestId("lane-legend").textContent).toContain("tier1");
    // No ghost state while traffic exists.
    expect(screen.queryByTestId("lane-ghost")).toBeNull();
  });

  it("shows the ghost-lane teaching state when no traffic exists", async () => {
    const { api } = makeFakeObs({ requests: [] });
    renderRequests(api);
    await waitLoaded();
    const ghost = screen.getByTestId("lane-ghost");
    expect(ghost.textContent).toContain("Arxmcp-Agent-Role");
    expect(screen.getByTestId("lane-canvas").className).toContain(
      "lane-canvas-ghost",
    );
  });

  it("renders the table newest-first with tier, bytes and status badges", async () => {
    const { api } = makeFakeObs();
    renderRequests(api);
    await waitLoaded();
    const rows = screen.getAllByTestId("request-row");
    expect(rows).toHaveLength(4);
    expect(rows[0].textContent).toContain("lean_verify");
    expect(rows[0].textContent).toContain("error");
    expect(rows[3].textContent).toContain("tier1");
    // Cap-rejection strip counts the denied/cap population (R6-lite).
    expect(screen.getByTestId("cap-rejection-strip").textContent).toContain(
      "1 cap/authz rejection",
    );
    // Latency-bar scale note names the window p95.
    expect(screen.getByTestId("requests-p95").textContent).toContain("p95");
  });

  it("facets by status and honors URL filters from cross-navigation", async () => {
    const { api } = makeFakeObs();
    renderRequests(api, { url: "/requests?tool=search_papers" });
    await waitLoaded();
    expect(screen.getAllByTestId("request-row")).toHaveLength(2);

    const statusGroup = screen.getByTestId("rfacet-status");
    const capChip = Array.from(statusGroup.querySelectorAll("button")).find(
      (b) => b.textContent?.startsWith("cap"),
    );
    fireEvent.click(capChip!);
    await waitFor(() =>
      expect(screen.getAllByTestId("request-row")).toHaveLength(1),
    );
    const capRow = screen.getAllByTestId("request-row")[0];
    expect(capRow.textContent).toContain("search_papers");
    expect(capRow.textContent).toContain("cap");

    // error status chip now counts 0 under tool=search_papers: dim, present.
    const errorChip = Array.from(
      statusGroup.querySelectorAll<HTMLButtonElement>("button"),
    ).find((b) => b.textContent?.startsWith("error"));
    expect(errorChip).toBeDefined();
    expect(errorChip!.disabled).toBe(true);
  });

  it("opens the waterfall drawer with only the phases that ran", async () => {
    const { api } = makeFakeObs();
    renderRequests(api);
    await waitLoaded();
    fireEvent.click(screen.getByTestId("request-open-1"));
    const drawer = await screen.findByTestId("waterfall-drawer");
    expect(screen.getByTestId("phase-cache_probe")).toBeDefined();
    expect(screen.getByTestId("phase-embed")).toBeDefined();
    expect(screen.getByTestId("phase-ann")).toBeDefined();
    // dense-only shipped: no phantom rerank phase (211 R-B).
    expect(screen.queryByTestId("phase-rerank")).toBeNull();
    expect(drawer.textContent).toContain("cache_probe: 1.2 ms");
    expect(screen.getByTestId("waterfall-ruler").textContent).toContain("p50");
    expect(drawer.textContent).toContain("corpus");
    // Escape closes.
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByTestId("waterfall-drawer")).toBeNull(),
    );
  });

  it("falls back to a single labeled bar when no phase capture exists", async () => {
    const { api } = makeFakeObs();
    renderRequests(api);
    await waitLoaded();
    fireEvent.click(screen.getByTestId("request-open-2"));
    await screen.findByTestId("waterfall-drawer");
    expect(screen.getByTestId("phase-total")).toBeDefined();
    expect(screen.getByTestId("waterfall-fallback").textContent).toContain(
      "no phase capture",
    );
  });

  it("appends live SSE request events into lanes and table", async () => {
    const { api } = makeFakeObs();
    const { es } = renderRequests(api);
    await waitLoaded();
    es().emit("ready", { topics: ["requests"], cursors: { requests: 4 } });
    es().emit("requests", {
      seq: 5, ts: 1783166500, tool: "find_equation", status: "ok",
      error_code: null, session_id: "a1b2c3d4e5f60718", role: "fixer",
      profile: "default", notebook: null, latency_ms: 12.0,
      cache_layer: "tier1", result_bytes: 128, k: 3, corpus_version: 1690,
    });
    await waitFor(() =>
      expect(screen.getAllByTestId("request-row")).toHaveLength(5),
    );
    const fixerLane = screen.getByTestId("lane-fixer");
    expect(fixerLane.querySelectorAll("circle.pulse")).toHaveLength(1);
  });

  it("states the A1-spine unavailable case honestly", async () => {
    const { api } = makeFakeObs({ unavailable: true });
    renderRequests(api, { sse: false });
    const empty = await screen.findByTestId("requests-unavailable");
    expect(empty.textContent).toContain("GET /api/v1/requests");
    expect(screen.queryByTestId("lane-canvas")).toBeNull();
  });
});

/**
 * GraphPage component tests over the Graph/Api/Obs provider seams —
 * zero live server. Covers: the Tier-0 accessible neighbor explorer
 * (traverse / expand with the cycle guard / focus re-rooting),
 * direction faceting on the URL, the NO-18 data caption, all four
 * degradation states (route-absent A1 spine, graph absent, graph
 * unavailable, transport error), and the Tier-2 gate: the 3-D module
 * loads only on operator activation, and a WebGL-less session
 * degrades to a note with Tier-0 intact (AC-B.22/B.23).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ApiProvider } from "../../api/ApiProvider";
import { makeClient } from "../../api/client";
import type { GraphApi } from "../../api/graph";
import { GraphProvider } from "../../api/GraphProvider";
import { mockFetch } from "../../api/mock";
import { ObsProvider } from "../../api/ObsProvider";
import { GraphPage } from "./GraphPage";
import { makeFakeGraph, makeObsStub } from "./testDoubles";

// The Tier-2 module tree (3d-force-graph → three) cannot run in
// jsdom; the mock records construction so the LAZY-LOAD GATE itself
// is testable: constructed = the chunk was imported and mounted.
const constructed: HTMLElement[] = [];
vi.mock("3d-force-graph", () => {
  class FakeForceGraph {
    calls: Record<string, unknown[][]> = {};
    constructor(el: HTMLElement) {
      constructed.push(el);
      const record =
        (name: string) =>
        (...args: unknown[]) => {
          (this.calls[name] ??= []).push(args);
          return proxy;
        };
      const proxy = new Proxy(this, {
        get(target, prop: string) {
          if (prop in target) return target[prop as keyof FakeForceGraph];
          return record(prop);
        },
      });
      return proxy;
    }
  }
  return { default: FakeForceGraph };
});

function renderGraph(
  graphApi: GraphApi,
  {
    url = "/notebooks/bridgeland-stability/graph",
    webgl = false,
    corpus = 1690 as number | null,
  } = {},
) {
  return render(
    <ApiProvider client={makeClient(mockFetch, "http://127.0.0.1")}>
      <ObsProvider api={makeObsStub(corpus)}>
        <GraphProvider api={graphApi}>
          <MemoryRouter initialEntries={[url]}>
            <Routes>
              <Route
                path="/notebooks/:slug/graph"
                element={
                  <GraphPage
                    webglSupported={() => webgl}
                    prefersReducedMotion={() => true}
                  />
                }
              />
            </Routes>
          </MemoryRouter>
        </GraphProvider>
      </ObsProvider>
    </ApiProvider>,
  );
}

describe("GraphPage — Tier-0 explorer", () => {
  it("renders the root's neighbors with edge metadata and corpus markers", async () => {
    const { api, queries } = makeFakeGraph();
    renderGraph(api);
    // Default root = first junction paper (added_at DESC).
    await waitFor(() =>
      expect(screen.getByTestId("graph-status").textContent).toBe(
        "2 direct cites neighbors of 0705.3794",
      ),
    );
    expect(queries[0]).toEqual({
      slug: "bridgeland-stability",
      q: { paper_id: "0705.3794", direction: "cites", depth: 1, limit: 50 },
    });
    const inCorpus = screen.getByTestId("node-0708.2247");
    expect(inCorpus.textContent).toContain("in corpus");
    expect(inCorpus.textContent).toContain("cites · hop 1 · openAlex");
    expect(inCorpus.textContent).toContain("confidence 1.00");
    expect(screen.getByTestId("node-0811.2435").textContent).not.toContain(
      "in corpus",
    );
  });

  it("expands one hop with aria-expanded and guards cycles", async () => {
    const { api } = makeFakeGraph();
    renderGraph(api);
    const expand = await screen.findByTestId("expand-0708.2247");
    expect(expand.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(expand);
    expect(expand.getAttribute("aria-expanded")).toBe("true");
    // The child branch arrives (1106.5217) and the back-edge to the
    // root renders as a cycle note, not an expandable node.
    await screen.findByTestId("node-1106.5217");
    const cycleNode = screen.getAllByTestId("node-0705.3794")[0];
    expect(cycleNode.textContent).toContain("(cycle — expanded above)");
    expect(cycleNode.querySelector('[data-testid="expand-0705.3794"]')).toBeNull();
    // Collapse works.
    fireEvent.click(expand);
    expect(expand.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByTestId("node-1106.5217")).toBeNull();
  });

  it("focus re-roots the tree and moves keyboard focus to the heading", async () => {
    const { api, queries } = makeFakeGraph();
    renderGraph(api);
    fireEvent.click(await screen.findByTestId("focus-0708.2247"));
    await waitFor(() =>
      expect(screen.getByTestId("graph-root").textContent).toContain(
        "0708.2247",
      ),
    );
    expect(
      queries.some((c) => c.q.paper_id === "0708.2247"),
    ).toBe(true);
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByTestId("graph-root")),
    );
    // The re-rooted tree lists 0708.2247's neighbors.
    await screen.findByTestId("node-1106.5217");
  });

  it("direction chips refetch and land in the URL state", async () => {
    const { api, queries } = makeFakeGraph();
    renderGraph(api);
    await screen.findByTestId("graph-tree");
    const chip = screen.getByTestId("direction-cited_by");
    expect(chip.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(chip);
    await waitFor(() =>
      expect(chip.getAttribute("aria-pressed")).toBe("true"),
    );
    await waitFor(() =>
      expect(
        queries.some((c) => c.q.direction === "cited_by"),
      ).toBe(true),
    );
    await screen.findByTestId("node-1203.4613");
  });

  it("renders the NO-18 caption from the explored model + /status", async () => {
    const { api } = makeFakeGraph();
    renderGraph(api);
    // Root + 2 neighbors, 2 edges.
    await waitFor(() =>
      expect(screen.getByTestId("graph-caption").textContent).toBe(
        "3 papers · 2 edges explored · corpus v1690",
      ),
    );
    // Expanding accumulates (1106.5217 new; cycle edge new).
    fireEvent.click(screen.getByTestId("expand-0708.2247"));
    await waitFor(() =>
      expect(screen.getByTestId("graph-caption").textContent).toBe(
        "4 papers · 4 edges explored · corpus v1690",
      ),
    );
  });

  it("degrades the caption quietly when /status is unreachable", async () => {
    const { api } = makeFakeGraph();
    renderGraph(api, { corpus: null });
    await waitFor(() =>
      expect(screen.getByTestId("graph-caption").textContent).toContain(
        "corpus version unknown",
      ),
    );
  });
});

describe("GraphPage — degradation states", () => {
  it("route-absent 404 (A1 spine): names the missing endpoint and the slice", async () => {
    const { api } = makeFakeGraph({ transport: "unavailable" });
    renderGraph(api);
    const block = await screen.findByTestId("graph-route-unavailable");
    expect(block.textContent).toContain("graph/neighbors");
    expect(block.textContent).toContain("arx-a45");
    expect(block.textContent).not.toContain("!");
    // No Tier-0 tree, no Tier-2 affordance — nothing pretends.
    expect(screen.queryByTestId("graph-tree")).toBeNull();
    expect(screen.queryByTestId("open-3d")).toBeNull();
  });

  it("graph absent: teaches the ingest command", async () => {
    const { api } = makeFakeGraph({ status: "absent" });
    renderGraph(api);
    const block = await screen.findByTestId("graph-absent");
    expect(block.textContent).toContain("ingest.graph_ingest");
    expect(screen.getByTestId("graph-status").textContent).toBe("graph absent");
  });

  it("graph unavailable: points at the WARNING log", async () => {
    const { api } = makeFakeGraph({ status: "unavailable" });
    renderGraph(api);
    const block = await screen.findByTestId("graph-degraded");
    expect(block.textContent).toContain("WARNING");
  });

  it("transport error: the detail lands in the live status line", async () => {
    const { api } = makeFakeGraph({
      transport: "error",
      errorDetail: "graph neighbors fetch failed (503)",
    });
    renderGraph(api);
    await waitFor(() =>
      expect(screen.getByTestId("graph-status").textContent).toContain("503"),
    );
  });
});

describe("GraphPage — Tier-2 gate (AC-B.22/B.23)", () => {
  it("does not construct the 3-D view until activation; WebGL-less degrades", async () => {
    constructed.length = 0;
    const { api } = makeFakeGraph();
    renderGraph(api, { webgl: false });
    await screen.findByTestId("graph-tree");
    expect(constructed).toHaveLength(0);
    fireEvent.click(screen.getByTestId("open-3d"));
    // No WebGL: a note, Tier-0 stands, still no 3-D construction.
    await screen.findByTestId("webgl-note");
    expect(screen.getByTestId("graph-tree")).toBeTruthy();
    expect(constructed).toHaveLength(0);
  });

  it("activates on demand with the caption riding along", async () => {
    constructed.length = 0;
    const { api } = makeFakeGraph();
    renderGraph(api, { webgl: true });
    await screen.findByTestId("graph-tree");
    expect(constructed).toHaveLength(0);
    fireEvent.click(screen.getByTestId("open-3d"));
    // The lazy chunk resolves and mounts exactly one scene.
    await screen.findByTestId("force-3d");
    await waitFor(() => expect(constructed).toHaveLength(1));
    expect(screen.getByTestId("force-3d-caption").textContent).toContain(
      "3 papers · 2 edges explored · corpus v1690",
    );
    // Tier-0 stays: the list is the AT surface, never replaced.
    expect(screen.getByTestId("graph-tree")).toBeTruthy();
    // Close destroys the mount point.
    fireEvent.click(screen.getByTestId("close-3d"));
    await waitFor(() => expect(screen.queryByTestId("force-3d")).toBeNull());
  });
});

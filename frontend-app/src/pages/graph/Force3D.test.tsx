/**
 * Force3D lifecycle tests against a recording 3d-force-graph mock
 * (jsdom has no WebGL; the wrapper's DISCIPLINE is what needs pinning):
 * <= 3 s cooldown freeze (AC-B.23), static warmup layout under
 * reduced motion (AC-B.16 — trigger-time flag, zero animation), no
 * programmatic camera motion, palette from live CSS tokens, teardown
 * on unmount, and the NO-18 caption on the figure.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Force3D from "./Force3D";

interface Recorded {
  el: HTMLElement;
  calls: Record<string, unknown[][]>;
}

const instances: Recorded[] = [];
vi.mock("3d-force-graph", () => {
  class FakeForceGraph {
    calls: Record<string, unknown[][]> = {};
    constructor(el: HTMLElement) {
      instances.push({ el, calls: this.calls });
      const calls = this.calls;
      const proxy: unknown = new Proxy(this, {
        get(target, prop: string) {
          if (prop in target) return target[prop as keyof FakeForceGraph];
          return (...args: unknown[]) => {
            (calls[prop] ??= []).push(args);
            return proxy;
          };
        },
      });
      return proxy as FakeForceGraph;
    }
  }
  return { default: FakeForceGraph };
});

const NODES = [
  { id: "0705.3794", inCorpus: true },
  { id: "0708.2247", inCorpus: false },
];
const LINKS = [{ source: "0705.3794", target: "0708.2247" }];

describe("Force3D", () => {
  it("configures the <=3s cooldown freeze in full-motion mode", () => {
    instances.length = 0;
    render(
      <Force3D nodes={NODES} links={LINKS} caption="cap" reducedMotion={false} />,
    );
    const g = instances[0];
    expect(g.calls.cooldownTime?.[0]).toEqual([3000]);
    expect(g.calls.warmupTicks).toBeUndefined();
    // Camera only on user action: no programmatic moves, ever.
    expect(g.calls.cameraPosition).toBeUndefined();
    expect(g.calls.zoomToFit).toBeUndefined();
    // The graph data went in verbatim (defensive copies).
    const data = g.calls.graphData?.[0]?.[0] as {
      nodes: unknown[];
      links: unknown[];
    };
    expect(data.nodes).toHaveLength(2);
    expect(data.links).toHaveLength(1);
    expect(data.nodes[0]).not.toBe(NODES[0]);
  });

  it("renders a static settled layout under reduced motion", () => {
    instances.length = 0;
    render(
      <Force3D nodes={NODES} links={LINKS} caption="cap" reducedMotion={true} />,
    );
    const g = instances[0];
    expect(g.calls.warmupTicks?.[0]).toEqual([120]);
    expect(g.calls.cooldownTicks?.[0]).toEqual([0]);
    expect(g.calls.cooldownTime).toBeUndefined();
  });

  it("reads the palette from the live CSS tokens", () => {
    instances.length = 0;
    document.documentElement.style.setProperty("--paper", "#101010");
    document.documentElement.style.setProperty("--accent", "#204060");
    try {
      render(
        <Force3D nodes={NODES} links={LINKS} caption="cap" reducedMotion />,
      );
      const g = instances[0];
      expect(g.calls.backgroundColor?.[0]).toEqual(["#101010"]);
      const nodeColor = g.calls.nodeColor?.[0]?.[0] as (n: unknown) => string;
      expect(nodeColor({ id: "x", inCorpus: true })).toBe("#204060");
    } finally {
      document.documentElement.style.removeProperty("--paper");
      document.documentElement.style.removeProperty("--accent");
    }
  });

  it("destroys the scene on unmount and captions the figure (NO-18)", () => {
    instances.length = 0;
    const view = render(
      <Force3D
        nodes={NODES}
        links={LINKS}
        caption="2 papers · 1 edge explored · corpus v1690"
        reducedMotion
      />,
    );
    expect(screen.getByTestId("force-3d-caption").textContent).toContain(
      "2 papers · 1 edge explored · corpus v1690",
    );
    expect(
      screen.getByTestId("force-3d").getAttribute("aria-label"),
    ).toContain("corpus v1690");
    const g = instances[0];
    expect(g.calls._destructor).toBeUndefined();
    view.unmount();
    expect(g.calls._destructor?.[0]).toEqual([]);
  });
});
